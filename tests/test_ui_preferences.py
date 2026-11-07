"""Isolated settings API tests. Run in the auth dependency environment.

    python -m unittest discover -s tests -p test_ui_preferences.py -v

Set TEST_POSTGRES_DSN to an expendable PostgreSQL for the migration test.
No production configuration, key files, Redis or providers are used.
"""

import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool


# Import the application logic without importing its configured DB or JWT keys.
database = types.ModuleType("backend.services.auth.app.database")
database.Base = declarative_base()
database.SessionLocal = lambda: None
sys.modules[database.__name__] = database
dependencies = types.ModuleType("backend.services.auth.app.dependencies")
dependencies.get_current_user = lambda: 7
sys.modules[dependencies.__name__] = dependencies

from backend.services.auth.app import crud, models, schemas  # noqa: E402
from backend.services.auth.app.routers import user_profile  # noqa: E402


class MemoryStore:
    def __init__(self):
        self.values = {}
        self.available = True

    async def get_settings(self, user_id):
        if not self.available:
            raise ConnectionError("synthetic Redis outage")
        return self.values.get(user_id)

    async def set_settings(self, user_id, settings):
        if not self.available:
            return False
        self.values[user_id] = dict(settings)
        return True


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        database.Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            db.add(models.User(id=7, email="synthetic@example.invalid"))
            db.commit()
        self.store = MemoryStore()
        self.store_patch = patch.object(user_profile, "get_settings_store", return_value=self.store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.addCleanup(self.engine.dispose)
        app = FastAPI()
        app.include_router(user_profile.router)

        def get_db():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[user_profile.get_db] = get_db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_new_user_defaults_and_profile(self):
        settings = self.client.get("/user/settings").json()["settings"]
        self.assertEqual((settings["ui_language"], settings["theme"]), ("en", "dark"))
        profile = self.client.get("/user/profile").json()
        self.assertEqual(profile["settings"]["ui_language"], "en")
        self.assertEqual(profile["settings"]["theme"], "dark")

    def test_preferences_round_trip_after_cache_loss_and_partial_update(self):
        response = self.client.put("/user/settings", json={"ui_language": "ru", "theme": "light"})
        self.assertEqual(response.status_code, 200)
        self.store.values.clear()
        response = self.client.put("/user/settings", json={"microphone_enabled": True})
        self.assertEqual(response.status_code, 200)
        stored = self.client.get("/user/settings").json()["settings"]
        self.assertEqual((stored["ui_language"], stored["theme"]), ("ru", "light"))
        self.assertTrue(stored["microphone_enabled"])
        self.assertIn("original_language", self.store.values[7])
        self.assertIn("tab_audio_enabled", self.store.values[7])

    def test_old_cache_is_rehydrated_from_saved_preferences(self):
        self.client.put("/user/settings", json={"ui_language": "ru", "theme": "light"})
        self.store.values[7] = {"original_language": "EN", "_user_id": 7}
        response = self.client.get("/user/settings").json()
        self.assertEqual(response["source"], "postgresql")
        self.assertEqual(response["settings"]["ui_language"], "ru")
        self.assertEqual(response["settings"]["theme"], "light")
        self.assertNotIn("_user_id", response["settings"])
        self.assertIn("microphone_enabled", self.store.values[7])

    def test_unavailable_redis_uses_postgresql(self):
        self.store.available = False
        response = self.client.put("/user/settings", json={"theme": "light"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "postgresql")
        self.assertEqual(self.client.get("/user/settings").json()["settings"]["theme"], "light")

    def test_invalid_preferences_are_rejected_without_overwriting_settings(self):
        for payload in ({"ui_language": "de"}, {"theme": "sepia"}, {"ui_language": None}, {"theme": None}):
            self.assertEqual(self.client.put("/user/settings", json=payload).status_code, 422)
        settings = self.client.get("/user/settings").json()["settings"]
        self.assertEqual((settings["ui_language"], settings["theme"]), ("en", "dark"))

    def test_omitted_preferences_are_not_in_partial_update(self):
        update = schemas.UserSettingsUpdate(original_language="ES")
        self.assertEqual(update.model_dump(exclude_unset=True), {"original_language": "ES"})


@unittest.skipUnless(os.environ.get("TEST_POSTGRES_DSN"), "requires an expendable PostgreSQL")
class MigrationTests(unittest.TestCase):
    def test_existing_rows_backfill_defaults_and_downgrade_preserves_data(self):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        path = Path(__file__).resolve().parents[1] / (
            "backend/services/auth/app/alembic/versions/0005_ui_preferences.py"
        )
        spec = importlib.util.spec_from_file_location("ui_preferences_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = create_engine(os.environ["TEST_POSTGRES_DSN"])
        try:
            with engine.begin() as connection:
                # A temporary table shadows user_settings even on a shared server.
                connection.execute(text("CREATE TEMP TABLE user_settings (id integer PRIMARY KEY, note text)"))
                connection.execute(text("INSERT INTO user_settings VALUES (1, 'preserve me')"))
                context = MigrationContext.configure(connection)
                with Operations.context(context):
                    migration.upgrade()
                    rows = connection.execute(text("SELECT note, ui_language, theme FROM user_settings")).all()
                    self.assertEqual(rows, [("preserve me", "en", "dark")])
                    connection.execute(text("INSERT INTO user_settings (id, note) VALUES (2, 'new user')"))
                    defaults = connection.execute(text("SELECT ui_language, theme FROM user_settings WHERE id=2")).one()
                    self.assertEqual(defaults, ("en", "dark"))
                    migration.downgrade()
                    self.assertEqual(connection.execute(text("SELECT note FROM user_settings ORDER BY id")).all(),
                                     [("preserve me",), ("new user",)])
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()

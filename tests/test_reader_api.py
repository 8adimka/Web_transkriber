"""Reader API regressions using synthetic text, isolated DB and mocked providers.

Run in the transcriber dependency environment:
    python -m unittest discover -s tests -p test_reader_api.py -v

TEST_POSTGRES_DSN optionally enables additive-table and real concurrent-PATCH tests
against an expendable PostgreSQL. No live keys or conversations are used.
"""

import asyncio
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
import logging
from unittest import TestCase, skipUnless
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.services.transcriber.app import crud, database, main, reader_routes as reader
from backend.services.transcriber.app.document_import import DocumentImportError

logging.getLogger("httpx").setLevel(logging.WARNING)


class ReaderTests(TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        database.Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.addCleanup(self.engine.dispose)
        app = FastAPI()
        app.include_router(reader.router)
        # Test the actual list/download/delete handlers alongside the new routes.
        app.add_api_route("/transcriptions", main.get_transcriptions, methods=["GET"], response_model=main.schemas.TranscriptionList)
        app.add_api_route("/transcriptions/{transcription_id}", main.delete_transcription, methods=["DELETE"])
        app.add_api_route("/transcriptions/{transcription_id}/download", main.download_transcription, methods=["GET"])

        def get_db():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[database.get_db] = get_db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.token_patch = patch.object(reader, "verify_token", side_effect=self.verify_token)
        self.token_patch.start()
        self.addCleanup(self.token_patch.stop)
        self.main_token_patch = patch.object(main, "verify_token", side_effect=self.verify_token)
        self.main_token_patch.start()
        self.addCleanup(self.main_token_patch.stop)
        self.headers = {"Authorization": "Bearer owner-7"}

    @staticmethod
    def verify_token(token):
        if token == "owner-7":
            return {"sub": "7"}
        if token == "owner-8":
            return {"sub": "8"}
        raise reader.HTTPException(401, detail="Synthetic invalid token")

    def create(self, content="One paragraph.\n\nA second paragraph.", **changes):
        data = {"title": "A synthetic book", "content": content, "client_id": str(uuid4()), "source_lang": "EN", "target_lang": "RU", **changes}
        response = self.client.post("/reader/documents", json=data, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), data

    def test_create_autosaves_to_existing_library_and_download(self):
        document, _ = self.create()
        listed = self.client.get("/transcriptions", params={"token": "owner-7"}).json()
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["transcriptions"][0]["id"], document["id"])
        self.assertEqual(listed["transcriptions"][0]["content"], document["content"])
        download = self.client.get(f'/transcriptions/{document["id"]}/download', params={"token": "owner-7"})
        self.assertEqual(download.text, document["content"])
        self.assertEqual((document["position"], document["page"], document["progress_updated_at_ms"]), (0, 1, 0))

    def test_creation_retry_is_idempotent_and_different_payload_conflicts(self):
        first, data = self.create()
        retry = self.client.post("/reader/documents", json=data, headers=self.headers)
        self.assertEqual(retry.json()["id"], first["id"])
        changed = self.client.post("/reader/documents", json={**data, "content": "different text"}, headers=self.headers)
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.json()["detail"]["code"], "idempotency_conflict")
        with self.sessions() as db:
            self.assertEqual(crud.count_user_transcriptions(db, 7), 1)
        # Creation keys are scoped to each authenticated account.
        other = self.client.post("/reader/documents", json=data, headers={"Authorization": "Bearer owner-8"})
        self.assertEqual(other.status_code, 200)
        self.assertNotEqual(other.json()["id"], first["id"])

    def test_existing_audio_text_opens_and_progress_uses_utf16_offsets(self):
        with self.sessions() as db:
            record = crud.create_transcription(db, user_id=7, filename="old_dialog.txt", content="A😀B", orig_language="ES", translate_to="EN")
            record_id = record.id
        path = f"/reader/documents/{record_id}"
        opened = self.client.get(path, headers=self.headers)
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(opened.json()["content"], "A😀B")
        saved = self.client.patch(path + "/progress", json={"position": 4, "page": 2}, headers=self.headers)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.client.get(path, headers=self.headers).json()["position"], 4)
        invalid = self.client.patch(path + "/progress", json={"position": 5, "page": 2}, headers=self.headers)
        self.assertEqual(invalid.status_code, 422)

    def test_late_progress_patch_cannot_overwrite_newer_anchor(self):
        document, _ = self.create(content="x" * 200)
        path = f'/reader/documents/{document["id"]}/progress'
        self.assertEqual(self.client.patch(path, json={"position": 100, "page": 5, "updated_at_ms": 2000}, headers=self.headers).status_code, 200)
        late = self.client.patch(path, json={"position": 5, "page": 1, "updated_at_ms": 1000}, headers=self.headers)
        self.assertEqual((late.json()["position"], late.json()["page"]), (100, 5))
        opened = self.client.get(path.removesuffix("/progress"), headers=self.headers).json()
        self.assertEqual(opened["progress_updated_at_ms"], 2000)

    def test_owner_is_checked_for_open_progress_and_legacy_actions(self):
        document, _ = self.create()
        other = {"Authorization": "Bearer owner-8"}
        path = f'/reader/documents/{document["id"]}'
        self.assertEqual(self.client.get(path, headers=other).status_code, 404)
        self.assertEqual(self.client.patch(path + "/progress", json={"position": 1, "page": 2}, headers=other).status_code, 404)
        self.assertEqual(self.client.get(f'/transcriptions/{document["id"]}/download?token=owner-8').status_code, 404)
        self.assertEqual(self.client.delete(f'/transcriptions/{document["id"]}?token=owner-8').status_code, 404)

    def test_deleting_saved_text_cascades_reader_state(self):
        document, _ = self.create()
        response = self.client.delete(f'/transcriptions/{document["id"]}?token=owner-7')
        self.assertEqual(response.status_code, 200)
        with self.sessions() as db:
            self.assertIsNone(db.get(database.ReaderState, document["id"]))
        self.assertEqual(self.client.get(f'/reader/documents/{document["id"]}', headers=self.headers).status_code, 404)

    def test_authentication_and_input_validation(self):
        for headers in ({}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer invalid"}):
            self.assertEqual(self.client.get("/reader/documents/1", headers=headers).status_code, 401)
        with patch.object(reader, "verify_token", return_value={"sub": "not-an-id"}):
            self.assertEqual(self.client.get("/reader/documents/1", headers=self.headers).status_code, 401)
        for content in ("  ", "nul\x00value", "bad\ud800"):
            response = self.client.post("/reader/documents", json={"title": "Book", "content": content, "client_id": str(uuid4())}, headers=self.headers)
            self.assertEqual(response.status_code, 422)
        document, _ = self.create()
        for patch_data in ({"position": -1, "page": 1}, {"position": 0, "page": 0}, {"position": True, "page": 1}, {"position": 0, "page": 1, "updated_at_ms": -1}):
            self.assertEqual(self.client.patch(f'/reader/documents/{document["id"]}/progress', json=patch_data, headers=self.headers).status_code, 422)

    def test_import_raw_document_and_retry_preserve_one_library_entry(self):
        headers = {**self.headers, "X-File-Name": "A%20Book.txt", "Idempotency-Key": str(uuid4()), "Content-Type": "application/octet-stream"}
        first = self.client.post("/reader/import?source_lang=en&target_lang=ru", content=b"Synthetic imported text", headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        again = self.client.post("/reader/import?source_lang=en&target_lang=ru", content=b"Synthetic imported text", headers=headers)
        self.assertEqual(first.json()["id"], again.json()["id"])
        self.assertEqual(first.json()["source_lang"], "EN")
        with self.sessions() as db:
            self.assertEqual(crud.count_user_transcriptions(db, 7), 1)

    def test_import_limits_and_explicit_parser_failures(self):
        headers = {**self.headers, "X-File-Name": "book.txt", "Idempotency-Key": str(uuid4())}
        with patch.object(reader, "MAX_UPLOAD_BYTES", 3):
            self.assertEqual(self.client.post("/reader/import", content=b"large", headers=headers).status_code, 413)
        self.assertEqual(self.client.post("/reader/import", content=b"", headers=headers).status_code, 422)
        self.assertEqual(self.client.post("/reader/import", content=b"book", headers=self.headers).status_code, 422)
        for code, status in (("unsupported_format", 415), ("file_too_large", 413), ("text_too_large", 413), ("encrypted_document", 422)):
            with patch.object(reader, "extract_document", side_effect=DocumentImportError(code, "Synthetic failure")):
                response = self.client.post("/reader/import", content=b"book", headers=headers)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["detail"]["code"], code)

    def test_library_preview_is_bounded_and_full_download_remains_available(self):
        document, _ = self.create(content="A" * 2000)
        preview = self.client.get("/transcriptions?token=owner-7&preview_chars=100").json()
        self.assertEqual(len(preview["transcriptions"][0]["content"]), 100)
        self.assertEqual(preview["total"], 1)
        empty = self.client.get("/transcriptions?token=owner-7&preview_chars=0").json()
        self.assertEqual(empty["transcriptions"][0]["content"], "")
        self.assertEqual(self.client.get(f'/reader/documents/{document["id"]}', headers=self.headers).json()["content"], "A" * 2000)
        self.assertEqual(self.client.get("/transcriptions?token=owner-7&preview_chars=501").status_code, 422)

    def test_translation_requires_selection_limits_and_explicit_configuration(self):
        with patch.dict(os.environ, {"DEEPL_API_KEY": ""}):
            response = self.client.post("/reader/translate", json={"text": "Hello", "source_lang": "EN", "target_lang": "RU"}, headers=self.headers)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["detail"]["code"], "translation_unavailable")
        for data in ({"text": " "}, {"text": "x" * 5001}, {"text": "word", "source_lang": "<bad>"}):
            self.assertEqual(self.client.post("/reader/translate", json=data, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.post("/reader/translate", json={"text": "Hello"}).status_code, 401)
        same = self.client.post("/reader/translate", json={"text": "Hello", "source_lang": "EN", "target_lang": "EN"}, headers=self.headers)
        self.assertEqual(same.json()["translated"], "Hello")

    @contextmanager
    def provider(self, response):
        limiter = type("Limiter", (), {"is_limited": AsyncMock(return_value=False)})()
        tracker = type("Tracker", (), {"track_deepl_usage": AsyncMock(return_value=True)})()
        client = AsyncMock()
        client.post.return_value = response
        client.__aenter__.return_value = client
        with patch.dict(os.environ, {"DEEPL_API_KEY": "synthetic-key:fx"}), patch.object(reader, "get_rate_limiter", return_value=limiter), patch.object(reader, "get_token_tracker", return_value=tracker), patch.object(reader.httpx, "AsyncClient", return_value=client):
            yield client, limiter, tracker

    def test_translation_sends_only_selection_and_tracks_success(self):
        response = httpx.Response(200, json={"translations": [{"text": "Привет"}]})
        with self.provider(response) as (client, limiter, tracker):
            result = self.client.post("/reader/translate", json={"text": "Hello", "source_lang": "en", "target_lang": "ru"}, headers=self.headers)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["translated"], "Привет")
            kwargs = client.post.call_args.kwargs
            self.assertEqual(kwargs["json"], {"text": ["Hello"], "source_lang": "EN", "target_lang": "RU"})
            self.assertTrue(client.post.call_args.args[0].startswith("https://api-free.deepl.com/"))
            tracker.track_deepl_usage.assert_awaited_once()
            self.assertEqual(limiter.is_limited.call_args.args[0], "7")

    def test_provider_failure_quota_and_invalid_result_are_never_fake_success(self):
        for status_code, expected in ((403, 503), (429, 429), (456, 429), (529, 429), (500, 502)):
            with self.provider(httpx.Response(status_code, json={"message": "Synthetic provider error"})):
                response = self.client.post("/reader/translate", json={"text": "Hello"}, headers=self.headers)
                self.assertEqual(response.status_code, expected)
                self.assertNotIn("translated", response.json())
        for body in ({}, {"translations": []}, {"translations": [{"text": ""}]}):
            with self.provider(httpx.Response(200, json=body)):
                self.assertEqual(self.client.post("/reader/translate", json={"text": "Hello"}, headers=self.headers).status_code, 502)
        with self.provider(httpx.Response(200, json={})) as (client, limiter, _):
            limiter.is_limited.return_value = True
            result = self.client.post("/reader/translate", json={"text": "Hello"}, headers=self.headers)
            self.assertEqual(result.status_code, 429)
            client.post.assert_not_called()
        with self.provider(httpx.Response(200, json={})) as (client, _, _):
            client.post.side_effect = httpx.ConnectError("Synthetic network outage")
            self.assertEqual(self.client.post("/reader/translate", json={"text": "Hello"}, headers=self.headers).status_code, 502)


@skipUnless(os.environ.get("TEST_POSTGRES_DSN"), "requires an expendable PostgreSQL")
class ReaderPostgresTests(TestCase):
    def test_additive_table_keeps_existing_text_and_progress_is_atomic(self):
        engine = create_engine(os.environ["TEST_POSTGRES_DSN"])
        schema = "reader_test_" + uuid4().hex
        try:
            with engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(text(f'SET search_path TO "{schema}"'))
                # Model a database from before Reader was introduced.
                database.Transcription.__table__.create(connection)
                connection.execute(database.Transcription.__table__.insert().values(user_id=7, filename="preserve.txt", content="old text", orig_language="EN", created_at=datetime.now(timezone.utc)))
                database.Base.metadata.create_all(connection)
                database.Base.metadata.create_all(connection)
                self.assertIn("reader_states", inspect(connection).get_table_names(schema=schema))
                self.assertEqual(connection.execute(text("SELECT content FROM transcriptions WHERE id=1")).scalar(), "old text")
            # Each request gets an independent transaction and connection.
            isolated = create_engine(os.environ["TEST_POSTGRES_DSN"], connect_args={"options": f"-csearch_path={schema}"})
            sessions = sessionmaker(bind=isolated)
            try:
                def apply(position, stamp):
                    with sessions() as db:
                        return reader.save_progress(reader.ReadingProgress(position=position, page=position + 1, updated_at_ms=stamp), document_id=1, user_id=7, db=db)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    list(pool.map(lambda pair: apply(*pair), ((1, 1000), (5, 2000))))
                apply(2, 1500)
                creation = reader.CreateDocument(title="Concurrent text", content="Only one entry", client_id=uuid4())
                def autosave(_):
                    with sessions() as db:
                        return reader.create_document(creation, user_id=7, db=db)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(autosave, range(2)))
                self.assertEqual(results[0]["id"], results[1]["id"])
                with sessions() as db:
                    self.assertEqual(crud.count_user_transcriptions(db, 7), 2)
                with sessions() as db:
                    state = db.get(database.ReaderState, 1)
                    self.assertEqual((state.position, state.position_updated_at_ms), (5, 2000))
                    document = db.get(database.Transcription, 1)
                    db.delete(document)
                    db.commit()
                    self.assertIsNone(db.get(database.ReaderState, 1))
            finally:
                isolated.dispose()
        finally:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            engine.dispose()

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_auth_host: str = "postgres_auth"
    postgres_auth_port: int = 5432
    postgres_auth_db: str = "authdb"
    postgres_auth_user: str = "postgres"
    postgres_auth_password: str = "auth_password_change_in_prod_123"

    # Для отладки
    def __str__(self):
        return f"Settings(postgres_auth_url={self.postgres_auth_url})"

    algorithm: str = "RS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Пути к RSA ключам
    private_key_path: str = "/app/keys/private.pem"
    public_key_path: str = "/app/keys/public.pem"

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8001/auth/callback/google"

    @property
    def postgres_auth_url(self) -> str:
        # Используем переменные окружения или значения по умолчанию
        user = os.getenv("POSTGRES_USER", self.postgres_auth_user)
        password = os.getenv("POSTGRES_AUTH_PASSWORD", self.postgres_auth_password)
        host = os.getenv("POSTGRES_AUTH_HOST", self.postgres_auth_host)
        port = os.getenv("POSTGRES_AUTH_PORT", str(self.postgres_auth_port))
        db = os.getenv("POSTGRES_AUTH_DB", self.postgres_auth_db)
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"

    @property
    def private_key(self) -> str:
        # Читаем приватный ключ из файла
        key_path = Path(self.private_key_path)
        if not key_path.exists():
            # Для разработки: если файла нет, используем ключ из переменной окружения
            private_key_env = os.getenv("AUTH_PRIVATE_KEY")
            if private_key_env:
                return private_key_env
            # Генерируем тестовый ключ для разработки
            return self._generate_fallback_private_key()
        return key_path.read_text()

    @property
    def public_key(self) -> str:
        # Читаем публичный ключ из файла
        key_path = Path(self.public_key_path)
        if not key_path.exists():
            # Для разработки: если файла нет, используем ключ из переменной окружения
            public_key_env = os.getenv("AUTH_PUBLIC_KEY")
            if public_key_env:
                return public_key_env
            # Генерируем тестовый ключ для разработки
            return self._generate_fallback_public_key()
        return key_path.read_text()

    def _generate_fallback_private_key(self) -> str:
        """Генерирует тестовый приватный ключ для разработки"""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        return private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

    def _generate_fallback_public_key(self) -> str:
        """Генерирует тестовый публичный ключ для разработки"""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        public_key = private_key.public_key()
        return public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

    model_config = {"env_file": "../../.env", "env_prefix": "AUTH_", "extra": "allow"}


settings = Settings()

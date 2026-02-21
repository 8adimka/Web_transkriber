import os
from base64 import b64decode, b64encode

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class EncryptionManager:
    def __init__(self):
        self.secret_key = os.getenv("ENCRYPTION_SECRET_KEY")
        if not self.secret_key:
            raise ValueError("ENCRYPTION_SECRET_KEY environment variable is required")

        salt = os.getenv(
            "ENCRYPTION_SALT", "default_salt_change_in_production"
        ).encode()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        key = b64encode(kdf.derive(self.secret_key.encode()))
        self.cipher = Fernet(key)

    def encrypt(self, data: str) -> str:
        encrypted = self.cipher.encrypt(data.encode())
        return b64encode(encrypted).decode()

    def decrypt(self, encrypted_data: str) -> str:
        decoded = b64decode(encrypted_data.encode())
        decrypted = self.cipher.decrypt(decoded)
        return decrypted.decode()


def get_encryption_manager():
    return EncryptionManager()

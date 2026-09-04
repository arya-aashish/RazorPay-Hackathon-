"""Encryption boundary for customer-uploaded evidence."""

import os
from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet:
    key = os.getenv("EVIDENCE_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("Evidence encryption is not configured.")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Evidence encryption key is invalid.") from exc


def encrypt_evidence(data: bytes) -> str:
    return _fernet().encrypt(data).decode("ascii")


def decrypt_evidence(token: str) -> bytes:
    try:
        return _fernet().decrypt(token.encode("ascii"))
    except InvalidToken as exc:
        raise RuntimeError("Stored evidence could not be decrypted.") from exc

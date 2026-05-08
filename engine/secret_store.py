from __future__ import annotations

import base64
import hashlib
import os


WEBHOOK_SECRET_PREFIX = "fernet:v1:"


class SecretEncryptionError(RuntimeError):
    pass


def _webhook_key() -> bytes:
    raw = os.environ.get("AI_TEAM_WEBHOOK_SECRET_KEY", "").strip()
    if not raw:
        raise SecretEncryptionError("AI_TEAM_WEBHOOK_SECRET_KEY is required to encrypt webhook secrets")
    return base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise SecretEncryptionError("cryptography is required for webhook secret encryption") from exc
    return Fernet(_webhook_key())


def is_encrypted_secret(value: str) -> bool:
    return bool(value and value.startswith(WEBHOOK_SECRET_PREFIX))


def encrypt_webhook_secret(secret: str) -> str:
    if is_encrypted_secret(secret):
        return secret
    token = _fernet().encrypt(secret.encode("utf-8")).decode("utf-8")
    return WEBHOOK_SECRET_PREFIX + token


def decrypt_webhook_secret(value: str) -> str:
    if not value:
        return value
    if not is_encrypted_secret(value):
        return value
    token = value[len(WEBHOOK_SECRET_PREFIX):]
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        raise SecretEncryptionError("failed to decrypt webhook secret") from exc

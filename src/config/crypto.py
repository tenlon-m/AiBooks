"""密钥加密工具 - 使用 cryptography Fernet 对称加密 AI 密钥."""
from __future__ import annotations

import os

from cryptography.fernet import Fernet

from src.config.app_config import AppConfig

_fernet: Fernet | None = None


def _get_or_create_key(config: AppConfig) -> bytes:
    key_file = config.data_dir / ".secret_key"
    if key_file.exists():
        return key_file.read_bytes()
    key = Fernet.generate_key()
    key_file.write_bytes(key)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return key


def init_crypto(config: AppConfig) -> None:
    global _fernet
    config.data_dir.mkdir(parents=True, exist_ok=True)
    key = _get_or_create_key(config)
    _fernet = Fernet(key)


def _fernet_instance() -> Fernet:
    if _fernet is None:
        raise RuntimeError("Crypto 未初始化，请先调用 init_crypto()")
    return _fernet


def encrypt_secret(plaintext: str) -> bytes:
    """加密明文密钥，返回密文 bytes."""
    if not plaintext:
        return b""
    return _fernet_instance().encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes) -> str:
    """解密密文，返回明文 str."""
    if not ciphertext:
        return ""
    return _fernet_instance().decrypt(ciphertext).decode("utf-8")
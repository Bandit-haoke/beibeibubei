"""
背备不悲 · API Key 解密

与 Java 的 com.beibei.common.AesCipher 严格对应：
  AES-256-GCM，密钥 = SHA-256(SECRET_KEY)，密文 = Base64(IV(12) ‖ 密文 ‖ TAG(16))

**解密失败一律返回原值**，这样：
  - 兼容早期直接存的明文
  - 即使 SECRET_KEY 换了，服务也不会因为解不开密钥而起不来
"""

from __future__ import annotations

import base64
import hashlib
import logging

logger = logging.getLogger(__name__)

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    _HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    _HAS_CRYPTO = False

_IV_LENGTH = 12


def decrypt(stored: str, secret: str) -> str:
    """解开 Java 侧加密的 API Key。解不开就原样返回。"""
    if not stored:
        return ""
    if not _HAS_CRYPTO or not secret:
        return stored

    try:
        raw = base64.b64decode(stored, validate=True)
    except Exception:  # noqa: BLE001
        return stored

    if len(raw) <= _IV_LENGTH:
        return stored

    try:
        key = hashlib.sha256(secret.encode("utf-8")).digest()
        aes = AESGCM(key)
        plain = aes.decrypt(raw[:_IV_LENGTH], raw[_IV_LENGTH:], None)
        return plain.decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug("API Key 解密失败，按明文处理：%s", type(exc).__name__)
        return stored


def encrypt(plain: str, secret: str) -> str:
    """加密（Python 侧一般不需要写，留给调试与测试用）。"""
    if not plain or not _HAS_CRYPTO or not secret:
        return plain
    import os

    key = hashlib.sha256(secret.encode("utf-8")).digest()
    iv = os.urandom(_IV_LENGTH)
    cipher_text = AESGCM(key).encrypt(iv, plain.encode("utf-8"), None)
    return base64.b64encode(iv + cipher_text).decode("ascii")


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "****"
    return value[:6] + "****" + value[-4:]

from __future__ import annotations

import hashlib

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

_IV = bytes(range(16))


def _key(working_key: str) -> bytes:
    if not working_key:
        raise ValueError("CCAvenue working key is not configured.")
    return hashlib.md5(working_key.encode("utf-8")).digest()


def encrypt(plain_text: str, working_key: str) -> str:
    cipher = AES.new(_key(working_key), AES.MODE_CBC, _IV)
    encrypted = cipher.encrypt(pad(plain_text.encode("utf-8"), AES.block_size))
    return encrypted.hex()


def decrypt(cipher_text: str, working_key: str) -> str:
    if not cipher_text:
        raise ValueError("CCAvenue response is empty.")
    try:
        encrypted = bytes.fromhex(cipher_text)
        cipher = AES.new(_key(working_key), AES.MODE_CBC, _IV)
        return unpad(cipher.decrypt(encrypted), AES.block_size).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("CCAvenue response could not be decrypted.") from exc

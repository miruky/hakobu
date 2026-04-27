"""Ed25519によるコード署名。

秘密鍵はPEM(PKCS8)でリリース担当者の手元に置き、公開鍵は
base64の生32バイトとしてアプリ側に同梱する。署名対象は
アーカイブ・パッチ・マニフェストのバイト列そのもの。
"""

from __future__ import annotations

import base64
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .errors import VerificationError


def generate() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def save_private(key: Ed25519PrivateKey, path: Path) -> None:
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(pem)
    path.chmod(0o600)


def load_private(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise VerificationError(f"Ed25519の秘密鍵でない: {path}")
    return key


def public_text(key: Ed25519PrivateKey) -> str:
    """公開鍵を配布用のbase64文字列にする。"""
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def public_from_text(text: str) -> Ed25519PublicKey:
    try:
        raw = base64.b64decode(text.strip(), validate=True)
        return Ed25519PublicKey.from_public_bytes(raw)
    except Exception as error:
        raise VerificationError(f"公開鍵として読めない: {error}") from error


def sign(key: Ed25519PrivateKey, data: bytes) -> str:
    return base64.b64encode(key.sign(data)).decode("ascii")


def verify(public: Ed25519PublicKey, data: bytes, signature_b64: str) -> None:
    """署名を検証する。不正なら VerificationError を投げる。"""
    try:
        signature = base64.b64decode(signature_b64, validate=True)
        public.verify(signature, data)
    except (InvalidSignature, ValueError) as error:
        raise VerificationError("署名の検証に失敗した") from error

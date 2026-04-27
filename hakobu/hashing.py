"""SHA-256によるファイルとツリーの指紋。

配布物の同一性検証はすべてここを通す。ツリーの指紋は
「相対パスからハッシュへの辞書」で、差分計算と更新後の検証に使う。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

STATE_FILE_NAME = ".hakobu-state.json"
"""インストール先に置く状態ファイル。配布物の指紋には含めない。"""


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 16):
            digest.update(chunk)
    return digest.hexdigest()


def hash_tree(root: Path) -> dict[str, str]:
    """root以下の全ファイルの指紋。キーはPOSIX形式の相対パス。"""
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel == STATE_FILE_NAME:
            continue
        result[rel] = hash_file(path)
    return result

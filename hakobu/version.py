"""バージョン番号の解釈と比較。

`1.2.3` 形式の数値ドット区切りだけを受け付ける。プレリリースタグや
ビルドメタデータは配布チャネル(stable / beta など)で表現する方針
のため、ここでは扱わない。
"""

from __future__ import annotations

import re

from .errors import ConfigError

_VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+)*$")


def parse(text: str) -> tuple[int, ...]:
    """バージョン文字列を比較可能なタプルにする。不正な形式は ConfigError。"""
    if not _VERSION_RE.match(text):
        raise ConfigError(f"バージョンとして解釈できない: {text!r}")
    return tuple(int(part) for part in text.split("."))


def is_newer(candidate: str, current: str) -> bool:
    """candidate が current より新しいか。桁数が違っても比較できる。"""
    a, b = parse(candidate), parse(current)
    length = max(len(a), len(b))
    return a + (0,) * (length - len(a)) > b + (0,) * (length - len(b))


def latest(versions: list[str]) -> str:
    """一覧の中で最も新しいバージョンを返す。空リストは ConfigError。"""
    if not versions:
        raise ConfigError("バージョンの一覧が空")
    result = versions[0]
    for version in versions[1:]:
        if is_newer(version, result):
            result = version
    return result

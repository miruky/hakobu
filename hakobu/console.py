"""端末向けの控えめな装飾。

配布ツールの出力は、成功・警告・失敗がひと目で分かると追いやすい。一方で
ログへリダイレクトされたりCIで走ったりもするので、色は端末に出すときだけに
する。`NO_COLOR`(https://no-color.org/)を尊重し、色だけに意味を持たせない
(語句そのものでも区別が付く)よう短いラベルを併用する。
"""

from __future__ import annotations

import os
import sys
import unicodedata
from typing import IO

_CODES = {
    "success": "32",
    "error": "31",
    "warn": "33",
    "head": "1;36",
    "bold": "1",
    "dim": "2",
}

_quiet = False


def set_quiet(flag: bool) -> None:
    """True にすると、エラー以外の出力(成功・補足・進捗)を止める。"""
    global _quiet
    _quiet = flag


def use_color(stream: IO[str]) -> bool:
    """この出力先に色を付けてよいか。NO_COLOR と非TTYでは付けない。"""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("HAKOBU_FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def style(text: str, kind: str, *, stream: IO[str] | None = None) -> str:
    """端末なら ANSI で装飾し、そうでなければ素のまま返す。"""
    target = stream if stream is not None else sys.stdout
    code = _CODES.get(kind)
    if code is None or not use_color(target):
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def cell_width(text: str) -> int:
    """端末上での表示幅。全角(東アジアの広い文字)は2、それ以外は1で数える。

    日本語の見出しを含む表は、文字数で揃えると桁がずれる。`list` の整列は
    この幅を基準にするので、全角まじりでも列が縦に揃う。
    """
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def pad(text: str, width: int, *, align: str = "left") -> str:
    """表示幅が width になるよう空白を足す。align="right" で右揃え。"""
    gap = max(0, width - cell_width(text))
    return " " * gap + text if align == "right" else text + " " * gap


def success(message: str) -> None:
    if _quiet:
        return
    print(style(message, "success"))


def detail(message: str) -> None:
    """主要メッセージに添える補足。控えめに表示する。"""
    if _quiet:
        return
    print(style(message, "dim"))


def heading(message: str) -> None:
    if _quiet:
        return
    print(style(message, "head"))


def line(message: str) -> None:
    """一覧などの主たる内容。装飾はしないが、--quiet では抑える。"""
    if _quiet:
        return
    print(message)


def fail(message: str) -> None:
    print(style(f"エラー: {message}", "error"), file=sys.stderr)


def progress(current: int, total: int, label: str, *, stream: IO[str] | None = None) -> None:
    """同じ行を上書きしながら進捗を見せる。完了(current>=total)で改行する。

    対話的な端末でだけ動く。ログやCIへ流すとき(非TTY)は1行も出さず、
    出力を進捗の断片で汚さない。
    """
    if _quiet:
        return
    target = stream if stream is not None else sys.stdout
    if not (hasattr(target, "isatty") and target.isatty()):
        return
    body = style(f"{label} ({current}/{total})", "dim", stream=target)
    target.write("\r" + body + ("\n" if current >= total else ""))
    target.flush()

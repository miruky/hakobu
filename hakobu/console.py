"""端末向けの控えめな装飾。

配布ツールの出力は、成功・警告・失敗がひと目で分かると追いやすい。一方で
ログへリダイレクトされたりCIで走ったりもするので、色は端末に出すときだけに
する。`NO_COLOR`(https://no-color.org/)を尊重し、色だけに意味を持たせない
(語句そのものでも区別が付く)よう短いラベルを併用する。
"""

from __future__ import annotations

import os
import sys
from typing import IO

_CODES = {
    "success": "32",
    "error": "31",
    "warn": "33",
    "head": "1;36",
    "bold": "1",
    "dim": "2",
}


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


def success(message: str) -> None:
    print(style(message, "success"))


def detail(message: str) -> None:
    """主要メッセージに添える補足。控えめに表示する。"""
    print(style(message, "dim"))


def heading(message: str) -> None:
    print(style(message, "head"))


def fail(message: str) -> None:
    print(style(f"エラー: {message}", "error"), file=sys.stderr)


def progress(current: int, total: int, label: str, *, stream: IO[str] | None = None) -> None:
    """同じ行を上書きしながら進捗を見せる。完了(current>=total)で改行する。

    対話的な端末でだけ動く。ログやCIへ流すとき(非TTY)は1行も出さず、
    出力を進捗の断片で汚さない。
    """
    target = stream if stream is not None else sys.stdout
    if not (hasattr(target, "isatty") and target.isatty()):
        return
    body = style(f"{label} ({current}/{total})", "dim", stream=target)
    target.write("\r" + body + ("\n" if current >= total else ""))
    target.flush()

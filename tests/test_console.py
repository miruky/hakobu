"""端末装飾が NO_COLOR・非TTY・強制色を正しく扱うことを確かめる。"""

import io
import subprocess
import sys

from hakobu import console


def test_no_color_env_disables_styling(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("HAKOBU_FORCE_COLOR", raising=False)
    assert console.style("x", "success", stream=io.StringIO()) == "x"


def test_force_color_wraps_in_ansi(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("HAKOBU_FORCE_COLOR", "1")
    out = console.style("x", "error", stream=io.StringIO())
    assert out.startswith("\x1b[31m")
    assert out.endswith("\x1b[0m")


def test_non_tty_stream_is_plain(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("HAKOBU_FORCE_COLOR", raising=False)
    assert console.style("x", "success", stream=io.StringIO()) == "x"


def test_unknown_kind_is_plain(monkeypatch):
    monkeypatch.setenv("HAKOBU_FORCE_COLOR", "1")
    assert console.style("x", "unknown", stream=io.StringIO()) == "x"


def test_success_writes_plain_under_capture(capsys, monkeypatch):
    monkeypatch.delenv("HAKOBU_FORCE_COLOR", raising=False)
    console.success("done")
    assert capsys.readouterr().out == "done\n"


def test_fail_prefixes_and_goes_to_stderr(capsys, monkeypatch):
    monkeypatch.delenv("HAKOBU_FORCE_COLOR", raising=False)
    console.fail("壊れた")
    assert capsys.readouterr().err == "エラー: 壊れた\n"


class _FakeTTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_progress_updates_line_on_tty(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    tty = _FakeTTY()
    console.progress(1, 3, "検証中", stream=tty)
    assert tty.getvalue() == "\r検証中 (1/3)"
    console.progress(3, 3, "検証中", stream=tty)
    assert tty.getvalue().endswith("\r検証中 (3/3)\n")


def test_progress_is_silent_on_non_tty():
    plain = io.StringIO()
    console.progress(2, 5, "x", stream=plain)
    assert plain.getvalue() == ""


def test_cell_width_counts_fullwidth_as_two():
    assert console.cell_width("abc") == 3
    assert console.cell_width("バージョン") == 10
    assert console.cell_width("1.2.0") == 5
    # 全角まじりは半角1・全角2で合算する。
    assert console.cell_width("v1リリース") == 2 + 8


def test_pad_aligns_by_display_width():
    # 表示幅(全角=2)を基準に詰めるので、文字数では揃わない混在文字列も揃う。
    assert console.pad("バージョン", 12) == "バージョン  "
    assert console.pad("1.2.0", 12) == "1.2.0       "
    assert console.cell_width(console.pad("バージョン", 12)) == 12
    assert console.cell_width(console.pad("1.2.0", 12)) == 12


def test_pad_right_alignment():
    assert console.pad("196 B", 8, align="right") == "   196 B"


def test_pad_does_not_truncate_when_already_wide():
    assert console.pad("バージョン", 3) == "バージョン"


def test_runnable_as_module():
    result = subprocess.run(
        [sys.executable, "-m", "hakobu", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "hakobu" in result.stdout

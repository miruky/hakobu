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


def test_runnable_as_module():
    result = subprocess.run(
        [sys.executable, "-m", "hakobu", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "hakobu" in result.stdout

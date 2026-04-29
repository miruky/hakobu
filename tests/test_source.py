"""Source がローカルパスとURLの取得失敗を SourceError へ正規化することの検証。

URLの分岐はネットワークに触れず、urlopen を差し替えて確かめる。
"""

import urllib.error

import pytest

from hakobu.errors import SourceError
from hakobu.update import DEFAULT_TIMEOUT, Source


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._data


def test_local_read_returns_bytes(tmp_path):
    (tmp_path / "manifest.json").write_bytes(b"{}")
    assert Source(str(tmp_path)).read("manifest.json") == b"{}"


def test_missing_local_file_becomes_source_error(tmp_path):
    with pytest.raises(SourceError) as exc:
        Source(str(tmp_path)).read("nai.json")
    assert "nai.json" in str(exc.value)


def test_trailing_slash_is_normalized(tmp_path):
    (tmp_path / "m.json").write_bytes(b"x")
    assert Source(f"{tmp_path}/").read("m.json") == b"x"


def test_url_read_forwards_timeout(monkeypatch):
    captured = {}

    def fake_urlopen(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return _FakeResponse(b"hi")

    monkeypatch.setattr("hakobu.update.urllib.request.urlopen", fake_urlopen)
    source = Source("https://example.com/repo", timeout=7.5)
    assert source.read("manifest.json") == b"hi"
    assert captured["url"] == "https://example.com/repo/manifest.json"
    assert captured["timeout"] == 7.5


def test_url_default_timeout_is_applied(monkeypatch):
    captured = {}

    def fake_urlopen(url, timeout=None):
        captured["timeout"] = timeout
        return _FakeResponse(b"")

    monkeypatch.setattr("hakobu.update.urllib.request.urlopen", fake_urlopen)
    Source("https://example.com/repo").read("manifest.json")
    assert captured["timeout"] == DEFAULT_TIMEOUT


def test_http_error_becomes_source_error(monkeypatch):
    def boom(url, timeout=None):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr("hakobu.update.urllib.request.urlopen", boom)
    with pytest.raises(SourceError) as exc:
        Source("https://example.com/repo").read("manifest.json")
    assert "404" in str(exc.value)


def test_url_unreachable_becomes_source_error(monkeypatch):
    def boom(url, timeout=None):
        raise urllib.error.URLError("名前解決に失敗")

    monkeypatch.setattr("hakobu.update.urllib.request.urlopen", boom)
    with pytest.raises(SourceError) as exc:
        Source("https://example.com/repo").read("manifest.json")
    assert "接続できない" in str(exc.value)


def test_url_timeout_becomes_source_error(monkeypatch):
    def boom(url, timeout=None):
        raise TimeoutError

    monkeypatch.setattr("hakobu.update.urllib.request.urlopen", boom)
    with pytest.raises(SourceError) as exc:
        Source("https://example.com/repo").read("manifest.json")
    assert "タイムアウト" in str(exc.value)

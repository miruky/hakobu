from pathlib import Path

import pytest

from hakobu import console, keys


@pytest.fixture(autouse=True)
def _reset_console():
    """consoleのquietはモジュール全体で共有されるので、毎テスト前に戻す。"""
    console.set_quiet(False)
    yield
    console.set_quiet(False)


DEFAULT_FILES = {
    "uranai/__init__.py": "VERSION = '{version}'\n",
    "uranai/main.py": "def run():\n    return 'うらない {version}'\n",
    "assets/messages.txt": "大吉\n中吉\n小吉\n",
}


def write_project(
    root: Path,
    version: str,
    files: dict[str, str] | None = None,
    *,
    name: str = "uranai",
) -> Path:
    """テスト用アプリのソースツリーを作る。filesの中身は {version} を展開する。"""
    root.mkdir(parents=True, exist_ok=True)
    config = f"""
[app]
name = "{name}"
version = "{version}"
entry = "uranai.main:run"

[files]
include = ["uranai/**/*.py", "assets/**/*"]
exclude = ["**/__pycache__/**"]
"""
    (root / "hakobu.toml").write_text(config, encoding="utf-8")
    for rel, body in (files or DEFAULT_FILES).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body.format(version=version), encoding="utf-8")
    return root


@pytest.fixture
def signing_key():
    return keys.generate()


@pytest.fixture
def public_text(signing_key):
    return keys.public_text(signing_key)

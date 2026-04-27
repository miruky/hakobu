import tarfile

import pytest

from hakobu import bundle
from hakobu.errors import ConfigError
from hakobu.hashing import hash_file, hash_tree
from tests.conftest import write_project


def test_build_collects_declared_files(tmp_path):
    project = write_project(tmp_path / "src", "1.0.0")
    result = bundle.build(project, tmp_path / "dist")
    assert result.name == "uranai"
    assert result.version == "1.0.0"
    assert sorted(result.files) == [
        "assets/messages.txt",
        "uranai/__init__.py",
        "uranai/main.py",
    ]
    assert result.archive.is_file()


def test_config_itself_is_not_bundled(tmp_path):
    project = write_project(tmp_path / "src", "1.0.0")
    result = bundle.build(project, tmp_path / "dist")
    assert "hakobu.toml" not in result.files


def test_exclude_patterns(tmp_path):
    project = write_project(tmp_path / "src", "1.0.0")
    cache = project / "uranai" / "__pycache__" / "main.cpython-313.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"\x00")
    result = bundle.build(project, tmp_path / "dist")
    assert all("__pycache__" not in rel for rel in result.files)


def test_build_is_deterministic(tmp_path):
    project = write_project(tmp_path / "src", "1.0.0")
    first = bundle.build(project, tmp_path / "dist1")
    second = bundle.build(project, tmp_path / "dist2")
    assert hash_file(first.archive) == hash_file(second.archive)


def test_extract_round_trip(tmp_path):
    project = write_project(tmp_path / "src", "1.0.0")
    result = bundle.build(project, tmp_path / "dist")
    dest = tmp_path / "extracted"
    bundle.extract_archive(result.archive, dest)
    assert hash_tree(dest) == result.files


def test_missing_config_raises(tmp_path):
    with pytest.raises(ConfigError):
        bundle.build(tmp_path, tmp_path / "dist")


def test_empty_include_raises(tmp_path):
    project = tmp_path / "src"
    project.mkdir()
    (project / "hakobu.toml").write_text(
        '[app]\nname = "x"\nversion = "1.0.0"\n[files]\ninclude = ["nai/**"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        bundle.build(project, tmp_path / "dist")


def test_malicious_archive_is_rejected(tmp_path):
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 0
        tar.addfile(info)
    with pytest.raises(ConfigError):
        bundle.extract_archive(archive, tmp_path / "out")

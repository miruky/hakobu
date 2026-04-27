"""CLIを実際のリリースフローの順に通すテスト。"""

import pytest

from hakobu.cli import main
from tests.conftest import write_project

V2_FILES = {
    "uranai/__init__.py": "VERSION = '{version}'\n",
    "uranai/main.py": "def run():\n    return 'うらない {version} 改'\n",
    "uranai/themes.py": "THEMES = ['和', '洋']\n",
}


@pytest.fixture
def keyset(tmp_path):
    keydir = tmp_path / "keys"
    assert main(["keygen", "--dir", str(keydir)]) == 0
    return keydir / "signing.key", keydir / "signing.pub"


def test_keygen_creates_pair(tmp_path):
    keydir = tmp_path / "keys"
    assert main(["keygen", "--dir", str(keydir)]) == 0
    assert (keydir / "signing.key").is_file()
    assert (keydir / "signing.pub").is_file()


def test_keygen_refuses_overwrite(tmp_path, capsys):
    keydir = tmp_path / "keys"
    main(["keygen", "--dir", str(keydir)])
    assert main(["keygen", "--dir", str(keydir)]) == 1
    assert "既に鍵がある" in capsys.readouterr().err


def test_build_reports_archive(tmp_path, capsys):
    project = write_project(tmp_path / "src", "1.0.0")
    assert main(["build", str(project), "--out", str(tmp_path / "dist")]) == 0
    out = capsys.readouterr().out
    assert "uranai 1.0.0" in out
    assert "sha256:" in out
    assert (tmp_path / "dist" / "uranai-1.0.0.tar.gz").is_file()


def test_release_flow_end_to_end(tmp_path, keyset, capsys):
    private, public = keyset
    repo = tmp_path / "repo"
    dest = tmp_path / "app"

    v1 = write_project(tmp_path / "src1", "1.0.0")
    assert main(["publish", str(v1), "--repo", str(repo), "--key", str(private)]) == 0
    assert main(["verify", "--repo", str(repo), "--pub", str(public)]) == 0
    assert main(["install", "--repo", str(repo), "--pub", str(public), "--dest", str(dest)]) == 0

    v2 = write_project(tmp_path / "src2", "1.1.0", V2_FILES)
    assert main(["publish", str(v2), "--repo", str(repo), "--key", str(private)]) == 0

    capsys.readouterr()
    assert (
        main(
            [
                "update",
                "--repo",
                str(repo),
                "--pub",
                str(public),
                "--dest",
                str(dest),
                "--check",
            ]
        )
        == 0
    )
    assert "1.0.0 から 1.1.0 へ更新できる(差分パッチ)" in capsys.readouterr().out

    assert main(["update", "--repo", str(repo), "--pub", str(public), "--dest", str(dest)]) == 0
    assert (dest / "uranai" / "themes.py").is_file()

    capsys.readouterr()
    assert main(["status", "--dest", str(dest)]) == 0
    assert "uranai 1.1.0" in capsys.readouterr().out


def test_update_when_current_says_so(tmp_path, keyset, capsys):
    private, public = keyset
    repo = tmp_path / "repo"
    dest = tmp_path / "app"
    project = write_project(tmp_path / "src", "1.0.0")
    main(["publish", str(project), "--repo", str(repo), "--key", str(private)])
    main(["install", "--repo", str(repo), "--pub", str(public), "--dest", str(dest)])
    capsys.readouterr()
    assert main(["update", "--repo", str(repo), "--pub", str(public), "--dest", str(dest)]) == 0
    assert "最新の状態にある" in capsys.readouterr().out


def test_error_paths_return_nonzero(tmp_path, capsys):
    assert main(["status", "--dest", str(tmp_path / "nai")]) == 1
    assert "エラー:" in capsys.readouterr().err

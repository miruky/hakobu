"""CLIを実際のリリースフローの順に通すテスト。"""

import json

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


def test_list_shows_releases(tmp_path, keyset, capsys):
    private, _ = keyset
    repo = tmp_path / "repo"
    v1 = write_project(tmp_path / "src1", "1.0.0")
    main(["publish", str(v1), "--repo", str(repo), "--key", str(private), "--notes", "初版"])
    v2 = write_project(tmp_path / "src2", "1.1.0", V2_FILES)
    main(["publish", str(v2), "--repo", str(repo), "--key", str(private)])
    capsys.readouterr()
    assert main(["list", "--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "リリース 2 件" in out
    assert "1.1.0" in out
    assert "1.0.0" in out
    assert "初版" in out


def test_quiet_suppresses_success_output(tmp_path, keyset, capsys):
    private, _ = keyset
    repo = tmp_path / "repo"
    v1 = write_project(tmp_path / "src1", "1.0.0")
    capsys.readouterr()
    assert main(["--quiet", "publish", str(v1), "--repo", str(repo), "--key", str(private)]) == 0
    assert "公開した" not in capsys.readouterr().out


def test_quiet_still_reports_errors(tmp_path, capsys):
    assert main(["--quiet", "status", "--dest", str(tmp_path / "nai")]) == 1
    assert "エラー:" in capsys.readouterr().err


def _install_v1(tmp_path, keyset):
    """v1 を公開して導入し、(repo, dest, public) を返す。"""
    private, public = keyset
    repo = tmp_path / "repo"
    dest = tmp_path / "app"
    v1 = write_project(tmp_path / "src1", "1.0.0")
    main(["publish", str(v1), "--repo", str(repo), "--key", str(private)])
    main(["install", "--repo", str(repo), "--pub", str(public), "--dest", str(dest)])
    return repo, dest, public


def test_install_into_missing_parent(tmp_path, keyset, capsys):
    private, public = keyset
    repo = tmp_path / "repo"
    v1 = write_project(tmp_path / "src1", "1.0.0")
    main(["publish", str(v1), "--repo", str(repo), "--key", str(private)])
    dest = tmp_path / "nai" / "fukai" / "app"
    assert main(["install", "--repo", str(repo), "--pub", str(public), "--dest", str(dest)]) == 0
    assert (dest / "uranai" / "main.py").is_file()


def test_missing_repo_reports_clean_error(tmp_path, keyset, capsys):
    _, public = keyset
    code = main(
        [
            "install",
            "--repo",
            str(tmp_path / "nai-repo"),
            "--pub",
            str(public),
            "--dest",
            str(tmp_path / "app"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "エラー:" in captured.err
    assert "Traceback" not in captured.err


def test_missing_public_key_reports_clean_error(tmp_path, keyset, capsys):
    private, _ = keyset
    repo = tmp_path / "repo"
    v1 = write_project(tmp_path / "src1", "1.0.0")
    main(["publish", str(v1), "--repo", str(repo), "--key", str(private)])
    capsys.readouterr()
    code = main(
        [
            "install",
            "--repo",
            str(repo),
            "--pub",
            str(tmp_path / "nai.pub"),
            "--dest",
            str(tmp_path / "app"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "公開鍵を読めない" in captured.err
    assert "Traceback" not in captured.err


def test_missing_private_key_reports_clean_error(tmp_path, capsys):
    repo = tmp_path / "repo"
    v1 = write_project(tmp_path / "src1", "1.0.0")
    code = main(["publish", str(v1), "--repo", str(repo), "--key", str(tmp_path / "nai.key")])
    captured = capsys.readouterr()
    assert code == 1
    assert "秘密鍵が見つからない" in captured.err
    assert "Traceback" not in captured.err


def test_status_json(tmp_path, keyset, capsys):
    _, dest, _ = _install_v1(tmp_path, keyset)
    capsys.readouterr()
    assert main(["status", "--dest", str(dest), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"app": "uranai", "channel": "stable", "version": "1.0.0"}


def test_list_json(tmp_path, keyset, capsys):
    private, _ = keyset
    repo = tmp_path / "repo"
    v1 = write_project(tmp_path / "src1", "1.0.0")
    main(["publish", str(v1), "--repo", str(repo), "--key", str(private), "--notes", "初版"])
    v2 = write_project(tmp_path / "src2", "1.1.0", V2_FILES)
    main(["publish", str(v2), "--repo", str(repo), "--key", str(private)])
    capsys.readouterr()
    assert main(["list", "--repo", str(repo), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["app"] == "uranai"
    versions = [r["version"] for r in payload["releases"]]
    assert versions == ["1.1.0", "1.0.0"]
    v1_record = next(r for r in payload["releases"] if r["version"] == "1.0.0")
    assert v1_record["notes"] == "初版"
    assert isinstance(v1_record["size"], int)
    v2_record = next(r for r in payload["releases"] if r["version"] == "1.1.0")
    assert v2_record["patches"] == ["1.0.0"]


def test_update_check_json_reports_available(tmp_path, keyset, capsys):
    repo, dest, public = _install_v1(tmp_path, keyset)
    private, _ = keyset
    v2 = write_project(tmp_path / "src2", "1.1.0", V2_FILES)
    main(["publish", str(v2), "--repo", str(repo), "--key", str(private)])
    capsys.readouterr()
    args = ["update", "--repo", str(repo), "--pub", str(public), "--dest", str(dest)]
    assert main([*args, "--check", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "current": "1.0.0",
        "available": True,
        "target": "1.1.0",
        "delta": True,
        "applied": False,
    }


def test_update_json_up_to_date(tmp_path, keyset, capsys):
    repo, dest, public = _install_v1(tmp_path, keyset)
    capsys.readouterr()
    args = ["update", "--repo", str(repo), "--pub", str(public), "--dest", str(dest), "--json"]
    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["available"] is False
    assert payload["current"] == "1.0.0"
    assert payload["applied"] is False


def test_update_json_applies(tmp_path, keyset, capsys):
    repo, dest, public = _install_v1(tmp_path, keyset)
    private, _ = keyset
    v2 = write_project(tmp_path / "src2", "1.1.0", V2_FILES)
    main(["publish", str(v2), "--repo", str(repo), "--key", str(private)])
    capsys.readouterr()
    args = ["update", "--repo", str(repo), "--pub", str(public), "--dest", str(dest), "--json"]
    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is True
    assert payload["target"] == "1.1.0"
    assert (dest / "uranai" / "themes.py").is_file()

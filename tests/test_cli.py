"""CLIを実際のリリースフローの順に通すテスト。"""

import json

import pytest

from hakobu import console
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


def test_list_table_columns_align(tmp_path, keyset, capsys):
    private, _ = keyset
    repo = tmp_path / "repo"
    v1 = write_project(tmp_path / "src1", "1.0.0")
    main(["publish", str(v1), "--repo", str(repo), "--key", str(private), "--notes", "初版"])
    v2 = write_project(tmp_path / "src2", "1.1.0", V2_FILES)
    main(["publish", str(v2), "--repo", str(repo), "--key", str(private)])
    capsys.readouterr()
    main(["list", "--repo", str(repo)])
    lines = capsys.readouterr().out.splitlines()
    header = next(line for line in lines if "公開日" in line)
    rows = [line for line in lines if "1.0.0" in line or "1.1.0" in line]
    assert "メモ" in header  # メモを持つリリースがあるので列が立つ

    def offset(line: str, needle: str) -> int:
        return console.cell_width(line[: line.index(needle)])

    # 公開日列の頭が、見出しと各データ行で同じ表示幅位置にある(全角込みで整列)。
    for row in rows:
        assert offset(row, "2026") == offset(header, "公開日")


def test_list_omits_memo_column_without_notes(tmp_path, keyset, capsys):
    private, _ = keyset
    repo = tmp_path / "repo"
    v1 = write_project(tmp_path / "src1", "1.0.0")
    main(["publish", str(v1), "--repo", str(repo), "--key", str(private)])
    capsys.readouterr()
    main(["list", "--repo", str(repo)])
    out = capsys.readouterr().out
    assert "バージョン" in out
    assert "メモ" not in out


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


def _publish_v2(tmp_path, repo, keyset):
    private, _ = keyset
    v2 = write_project(tmp_path / "src2", "1.1.0", V2_FILES)
    main(["publish", str(v2), "--repo", str(repo), "--key", str(private)])


def test_rollback_cli_restores_previous(tmp_path, keyset, capsys):
    repo, dest, public = _install_v1(tmp_path, keyset)
    _publish_v2(tmp_path, repo, keyset)
    main(["update", "--repo", str(repo), "--pub", str(public), "--dest", str(dest)])
    capsys.readouterr()
    assert main(["rollback", "--dest", str(dest)]) == 0
    assert "1.0.0 へ戻した" in capsys.readouterr().out
    assert not (dest / "uranai" / "themes.py").exists()
    capsys.readouterr()
    main(["status", "--dest", str(dest)])
    assert "uranai 1.0.0" in capsys.readouterr().out


def test_rollback_cli_json(tmp_path, keyset, capsys):
    repo, dest, public = _install_v1(tmp_path, keyset)
    _publish_v2(tmp_path, repo, keyset)
    main(["update", "--repo", str(repo), "--pub", str(public), "--dest", str(dest)])
    capsys.readouterr()
    assert main(["rollback", "--dest", str(dest), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"rolled_back_to": "1.0.0"}


def test_rollback_cli_without_backup_is_clean_error(tmp_path, keyset, capsys):
    _, dest, _ = _install_v1(tmp_path, keyset)
    capsys.readouterr()
    code = main(["rollback", "--dest", str(dest)])
    captured = capsys.readouterr()
    assert code == 1
    assert "戻せる前のバージョンがない" in captured.err
    assert "Traceback" not in captured.err


def test_update_announces_rollback(tmp_path, keyset, capsys):
    repo, dest, public = _install_v1(tmp_path, keyset)
    _publish_v2(tmp_path, repo, keyset)
    capsys.readouterr()
    main(["update", "--repo", str(repo), "--pub", str(public), "--dest", str(dest)])
    assert "rollback" in capsys.readouterr().out


def test_update_no_backup_disables_rollback(tmp_path, keyset, capsys):
    repo, dest, public = _install_v1(tmp_path, keyset)
    _publish_v2(tmp_path, repo, keyset)
    args = ["update", "--repo", str(repo), "--pub", str(public), "--dest", str(dest), "--no-backup"]
    assert main(args) == 0
    capsys.readouterr()
    assert main(["rollback", "--dest", str(dest)]) == 1
    assert "戻せる前のバージョンがない" in capsys.readouterr().err


def test_status_json_includes_rollback_to(tmp_path, keyset, capsys):
    repo, dest, public = _install_v1(tmp_path, keyset)
    _publish_v2(tmp_path, repo, keyset)
    main(["update", "--repo", str(repo), "--pub", str(public), "--dest", str(dest)])
    capsys.readouterr()
    assert main(["status", "--dest", str(dest), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == "1.1.0"
    assert payload["rollback_to"] == "1.0.0"


def test_keygen_shows_fingerprint(tmp_path, capsys):
    assert main(["keygen", "--dir", str(tmp_path / "keys")]) == 0
    assert "指紋" in capsys.readouterr().out


def test_verify_json(tmp_path, keyset, capsys):
    private, public = keyset
    repo = tmp_path / "repo"
    v1 = write_project(tmp_path / "src1", "1.0.0")
    main(["publish", str(v1), "--repo", str(repo), "--key", str(private)])
    capsys.readouterr()
    assert main(["verify", "--repo", str(repo), "--pub", str(public), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verified"] is True
    assert payload["app"] == "uranai"
    assert payload["releases"] == 1
    assert ":" in payload["fingerprint"]


def _publish_chain(tmp_path, repo, private, count):
    for minor in range(count):
        proj = write_project(tmp_path / f"src{minor}", f"1.{minor}.0")
        main(["publish", str(proj), "--repo", str(repo), "--key", str(private)])


def test_prune_cli_trims_and_repo_still_verifies(tmp_path, keyset, capsys):
    private, public = keyset
    repo = tmp_path / "repo"
    _publish_chain(tmp_path, repo, private, 4)
    capsys.readouterr()
    assert main(["prune", "--repo", str(repo), "--key", str(private), "--keep", "2"]) == 0
    assert "リリースを取り除いた" in capsys.readouterr().out
    # 整理後もリポジトリ全体が検証を通る。
    assert main(["verify", "--repo", str(repo), "--pub", str(public)]) == 0
    capsys.readouterr()
    main(["list", "--repo", str(repo), "--json"])
    versions = [r["version"] for r in json.loads(capsys.readouterr().out)["releases"]]
    assert versions == ["1.3.0", "1.2.0"]


def test_prune_cli_noop_within_keep(tmp_path, keyset, capsys):
    private, _ = keyset
    repo = tmp_path / "repo"
    _publish_chain(tmp_path, repo, private, 1)
    capsys.readouterr()
    assert main(["prune", "--repo", str(repo), "--key", str(private), "--keep", "5"]) == 0
    assert "取り除くリリースはなかった" in capsys.readouterr().out


def test_prune_cli_missing_key_is_clean_error(tmp_path, keyset, capsys):
    private, _ = keyset
    repo = tmp_path / "repo"
    _publish_chain(tmp_path, repo, private, 1)
    capsys.readouterr()
    code = main(["prune", "--repo", str(repo), "--key", str(tmp_path / "nai.key"), "--keep", "1"])
    captured = capsys.readouterr()
    assert code == 1
    assert "秘密鍵が見つからない" in captured.err
    assert "Traceback" not in captured.err

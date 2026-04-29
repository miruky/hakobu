import pytest

from hakobu import bundle, keys
from hakobu.errors import UpdateError, VerificationError
from hakobu.hashing import hash_tree
from hakobu.repo import Repository
from hakobu.update import State, Updater
from tests.conftest import write_project

V2_FILES = {
    "uranai/__init__.py": "VERSION = '{version}'\n",
    "uranai/main.py": "def run():\n    return 'うらない {version} 改'\n",
    "uranai/themes.py": "THEMES = ['和', '洋']\n",
}


@pytest.fixture
def repo(tmp_path, signing_key):
    repository = Repository(tmp_path / "repo")
    project = write_project(tmp_path / "src-1.0.0", "1.0.0")
    repository.publish(bundle.build(project, tmp_path / "dist1"), signing_key)
    return repository


def publish_v2(tmp_path, repo, signing_key, files=V2_FILES):
    project = write_project(tmp_path / "src-1.1.0", "1.1.0", files)
    return repo.publish(bundle.build(project, tmp_path / "dist2"), signing_key)


@pytest.fixture
def installed(tmp_path, repo, public_text):
    install_dir = tmp_path / "app"
    updater = Updater(str(repo.root), install_dir, public_text)
    updater.install()
    return updater


class TestInstall:
    def test_files_and_state(self, tmp_path, installed):
        install_dir = installed.install_dir
        assert (install_dir / "uranai" / "main.py").is_file()
        state = State.load(install_dir)
        assert state.app == "uranai"
        assert state.version == "1.0.0"

    def test_refuses_non_empty_dir(self, tmp_path, repo, public_text):
        dest = tmp_path / "occupied"
        dest.mkdir()
        (dest / "sonzai.txt").write_text("x")
        with pytest.raises(UpdateError):
            Updater(str(repo.root), dest, public_text).install()

    def test_creates_missing_parent_dirs(self, tmp_path, repo, public_text):
        # ~/apps/foo のように親がまだ無いパスへも新規導入できる。
        dest = tmp_path / "nai" / "fukai" / "app"
        release = Updater(str(repo.root), dest, public_text).install()
        assert release.version == "1.0.0"
        assert (dest / "uranai" / "main.py").is_file()
        assert State.load(dest).version == "1.0.0"

    def test_specific_version(self, tmp_path, repo, signing_key, public_text):
        publish_v2(tmp_path, repo, signing_key)
        dest = tmp_path / "pinned"
        release = Updater(str(repo.root), dest, public_text).install("1.0.0")
        assert release.version == "1.0.0"


class TestCheck:
    def test_up_to_date_returns_none(self, installed):
        assert installed.check() is None

    def test_newer_release_is_planned_as_delta(self, tmp_path, repo, signing_key, installed):
        publish_v2(tmp_path, repo, signing_key)
        plan = installed.check()
        assert plan is not None
        assert plan.current == "1.0.0"
        assert plan.target.version == "1.1.0"
        assert plan.delta


class TestApply:
    def test_delta_update(self, tmp_path, repo, signing_key, installed):
        publish_v2(tmp_path, repo, signing_key)
        plan = installed.check()
        release = installed.apply(plan)
        assert release.version == "1.1.0"
        assert State.load(installed.install_dir).version == "1.1.0"
        assert (installed.install_dir / "uranai" / "themes.py").is_file()
        assert not (installed.install_dir / "assets").exists()
        assert hash_tree(installed.install_dir) == release.files

    def test_full_update_when_no_patch(self, tmp_path, repo, signing_key, installed):
        publish_v2(tmp_path, repo, signing_key)
        plan = installed.check()
        plan.patch = None
        release = installed.apply(plan)
        assert release.version == "1.1.0"
        assert hash_tree(installed.install_dir) == release.files

    def test_tampered_patch_leaves_install_intact(self, tmp_path, repo, signing_key, installed):
        release = publish_v2(tmp_path, repo, signing_key)
        patch_path = repo.root / release.patches[0].name
        patch_path.write_bytes(patch_path.read_bytes() + b"x")
        plan = installed.check()
        before = hash_tree(installed.install_dir)
        with pytest.raises(VerificationError):
            installed.apply(plan)
        assert hash_tree(installed.install_dir) == before
        assert State.load(installed.install_dir).version == "1.0.0"

    def test_tampered_manifest_is_rejected(self, repo, installed):
        data = repo.manifest_path().read_bytes()
        repo.manifest_path().write_bytes(data.replace(b"1.0.0", b"9.9.9", 1))
        with pytest.raises(VerificationError):
            installed.check()

    def test_wrong_public_key_rejects_everything(self, tmp_path, repo):
        stranger = keys.public_text(keys.generate())
        dest = tmp_path / "another"
        with pytest.raises(VerificationError):
            Updater(str(repo.root), dest, stranger).install()

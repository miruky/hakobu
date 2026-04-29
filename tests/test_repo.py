import pytest

from hakobu import bundle, keys
from hakobu.errors import ConfigError
from hakobu.hashing import hash_file
from hakobu.manifest import Manifest
from hakobu.repo import Repository
from tests.conftest import write_project


def publish_version(tmp_path, repo, key, version, files=None):
    project = write_project(tmp_path / f"src-{version}", version, files)
    result = bundle.build(project, tmp_path / f"dist-{version}")
    return repo.publish(result, key)


def test_publish_writes_signed_manifest(tmp_path, signing_key, public_text):
    repo = Repository(tmp_path / "repo")
    publish_version(tmp_path, repo, signing_key, "1.0.0")
    data = repo.manifest_path().read_bytes()
    signature = (repo.root / "manifest.json.sig").read_text().strip()
    keys.verify(keys.public_from_text(public_text), data, signature)
    manifest = Manifest.from_bytes(data)
    assert manifest.app == "uranai"
    assert [release.version for release in manifest.releases] == ["1.0.0"]


def test_archive_artifact_matches_disk(tmp_path, signing_key):
    repo = Repository(tmp_path / "repo")
    release = publish_version(tmp_path, repo, signing_key, "1.0.0")
    path = repo.root / release.archive.name
    assert path.is_file()
    assert hash_file(path) == release.archive.sha256
    assert path.stat().st_size == release.archive.size


def test_second_release_gets_patch(tmp_path, signing_key):
    repo = Repository(tmp_path / "repo")
    publish_version(tmp_path, repo, signing_key, "1.0.0")
    release = publish_version(tmp_path, repo, signing_key, "1.1.0")
    assert [patch.from_version for patch in release.patches] == ["1.0.0"]
    assert (repo.root / release.patches[0].name).is_file()


def test_patch_count_is_capped(tmp_path, signing_key):
    repo = Repository(tmp_path / "repo")
    for minor in range(5):
        publish_version(tmp_path, repo, signing_key, f"1.{minor}.0")
    manifest = repo.load_manifest()
    newest = manifest.latest()
    assert newest.version == "1.4.0"
    assert len(newest.patches) == 3
    assert [p.from_version for p in newest.patches] == ["1.1.0", "1.2.0", "1.3.0"]


def test_duplicate_version_rejected(tmp_path, signing_key):
    repo = Repository(tmp_path / "repo")
    publish_version(tmp_path, repo, signing_key, "1.0.0")
    with pytest.raises(ConfigError):
        publish_version(tmp_path, repo, signing_key, "1.0.0")


def test_other_app_rejected(tmp_path, signing_key):
    repo = Repository(tmp_path / "repo")
    publish_version(tmp_path, repo, signing_key, "1.0.0")
    project = write_project(tmp_path / "other", "1.0.0", name="betsu")
    result = bundle.build(project, tmp_path / "dist-other")
    with pytest.raises(ConfigError):
        repo.publish(result, signing_key)


class TestPrune:
    def _five_releases(self, tmp_path, repo, key):
        for minor in range(5):
            publish_version(tmp_path, repo, key, f"1.{minor}.0")

    def test_keeps_newest_and_drops_old(self, tmp_path, signing_key, public_text):
        repo = Repository(tmp_path / "repo")
        self._five_releases(tmp_path, repo, signing_key)
        old_archive = repo.root / "archives/uranai-1.0.0.tar.gz"
        assert old_archive.is_file()

        result = repo.prune(signing_key, keep=2)

        assert result.removed_versions == ["1.0.0", "1.1.0", "1.2.0"]
        manifest = repo.load_manifest()
        assert sorted(r.version for r in manifest.releases) == ["1.3.0", "1.4.0"]
        assert not old_archive.exists()
        # 残ったマニフェストは署名し直されており、元の公開鍵で検証できる。
        data = repo.manifest_path().read_bytes()
        signature = (repo.root / "manifest.json.sig").read_text().strip()
        keys.verify(keys.public_from_text(public_text), data, signature)
        assert manifest.latest().version == "1.4.0"

    def test_drops_stale_patches_in_kept_releases(self, tmp_path, signing_key):
        repo = Repository(tmp_path / "repo")
        self._five_releases(tmp_path, repo, signing_key)
        newest = repo.load_manifest().latest()
        stale_name = next(p.name for p in newest.patches if p.from_version == "1.1.0")
        assert (repo.root / stale_name).is_file()

        repo.prune(signing_key, keep=2)

        newest = repo.load_manifest().latest()
        assert [p.from_version for p in newest.patches] == ["1.3.0"]
        assert not (repo.root / stale_name).exists()

    def test_noop_when_within_keep(self, tmp_path, signing_key):
        repo = Repository(tmp_path / "repo")
        publish_version(tmp_path, repo, signing_key, "1.0.0")
        publish_version(tmp_path, repo, signing_key, "1.1.0")
        result = repo.prune(signing_key, keep=5)
        assert result.removed_versions == []
        assert result.removed_files == []
        assert len(repo.load_manifest().releases) == 2

    def test_keep_below_one_rejected(self, tmp_path, signing_key):
        repo = Repository(tmp_path / "repo")
        publish_version(tmp_path, repo, signing_key, "1.0.0")
        with pytest.raises(ConfigError):
            repo.prune(signing_key, keep=0)

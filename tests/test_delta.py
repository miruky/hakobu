import shutil

import pytest

from hakobu.delta import apply_patch, make_patch, plan
from hakobu.errors import VerificationError
from hakobu.hashing import hash_tree
from tests.conftest import write_project

V2_FILES = {
    "uranai/__init__.py": "VERSION = '{version}'\n",
    "uranai/main.py": "def run():\n    return 'うらない {version} 改'\n",
    "uranai/themes.py": "THEMES = ['和', '洋']\n",
}


class TestPlan:
    def test_changed_added_removed(self):
        old = {"a.py": "1", "b.py": "2", "c.py": "3"}
        new = {"a.py": "1", "b.py": "9", "d.py": "4"}
        diff = plan(old, new)
        assert diff.changed == ["b.py", "d.py"]
        assert diff.removed == ["c.py"]

    def test_identical_trees(self):
        files = {"a.py": "1"}
        diff = plan(files, files)
        assert diff.changed == []
        assert diff.removed == []


@pytest.fixture
def trees(tmp_path):
    old_tree = write_project(tmp_path / "v1", "1.0.0")
    new_tree = write_project(tmp_path / "v2", "1.1.0", V2_FILES)
    (old_tree / "hakobu.toml").unlink()
    (new_tree / "hakobu.toml").unlink()
    return old_tree, new_tree


def test_patch_round_trip(tmp_path, trees):
    old_tree, new_tree = trees
    patch = make_patch(
        app="uranai",
        from_version="1.0.0",
        old_files=hash_tree(old_tree),
        to_version="1.1.0",
        new_tree=new_tree,
        dest=tmp_path / "patch.tar.gz",
    )
    work = tmp_path / "work"
    shutil.copytree(old_tree, work)
    apply_patch(patch, work, expect_app="uranai", expect_to="1.1.0")
    assert hash_tree(work) == hash_tree(new_tree)
    assert not (work / "assets").exists()


def test_patch_smaller_than_full_copy(tmp_path, trees):
    old_tree, new_tree = trees
    patch = make_patch(
        app="uranai",
        from_version="1.0.0",
        old_files=hash_tree(old_tree),
        to_version="1.1.0",
        new_tree=new_tree,
        dest=tmp_path / "patch.tar.gz",
    )
    total = sum(p.stat().st_size for p in new_tree.rglob("*") if p.is_file())
    unchanged = (new_tree / "uranai" / "__init__.py").stat().st_size
    assert patch.stat().st_size > 0
    # 据え置きのファイルはパッチに入らない
    assert total - unchanged > 0


def test_wrong_target_version_rejected(tmp_path, trees):
    old_tree, new_tree = trees
    patch = make_patch(
        app="uranai",
        from_version="1.0.0",
        old_files=hash_tree(old_tree),
        to_version="1.1.0",
        new_tree=new_tree,
        dest=tmp_path / "patch.tar.gz",
    )
    work = tmp_path / "work"
    shutil.copytree(old_tree, work)
    with pytest.raises(VerificationError):
        apply_patch(patch, work, expect_app="uranai", expect_to="9.9.9")


def test_wrong_app_rejected(tmp_path, trees):
    old_tree, new_tree = trees
    patch = make_patch(
        app="uranai",
        from_version="1.0.0",
        old_files=hash_tree(old_tree),
        to_version="1.1.0",
        new_tree=new_tree,
        dest=tmp_path / "patch.tar.gz",
    )
    work = tmp_path / "work"
    shutil.copytree(old_tree, work)
    with pytest.raises(VerificationError):
        apply_patch(patch, work, expect_app="betsu-app", expect_to="1.1.0")

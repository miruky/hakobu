"""差分配布のパッチ。

リリース間のファイル指紋を比べ、変更・追加されたファイルの実体と
削除リストだけを `patch.json` 込みのtar.gzに収める。全体を
配り直すより小さく、適用結果はリリースのファイル指紋で検証できる。
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from .bundle import extract_archive, write_archive
from .errors import ConfigError, VerificationError
from .hashing import hash_tree
from .manifest import canonical_json

PATCH_META = "patch.json"
PATCH_FILES_DIR = "files"


@dataclass
class PatchPlan:
    from_version: str
    to_version: str
    changed: list[str]
    removed: list[str]


def plan(old_files: dict[str, str], new_files: dict[str, str]) -> PatchPlan:
    """2つのファイル指紋から、書き込むファイルと消すファイルを割り出す。"""
    changed = [rel for rel, digest in new_files.items() if old_files.get(rel) != digest]
    removed = [rel for rel in old_files if rel not in new_files]
    return PatchPlan(
        from_version="", to_version="", changed=sorted(changed), removed=sorted(removed)
    )


def make_patch(
    *,
    app: str,
    from_version: str,
    old_files: dict[str, str],
    to_version: str,
    new_tree: Path,
    dest: Path,
) -> Path:
    """新バージョンの実ツリーと旧指紋から差分パッチを書き出す。"""
    new_files = hash_tree(new_tree)
    diff = plan(old_files, new_files)
    meta = {
        "app": app,
        "from": from_version,
        "to": to_version,
        "changed": {rel: new_files[rel] for rel in diff.changed},
        "removed": diff.removed,
    }
    with TemporaryDirectory() as tmp:
        stage = Path(tmp)
        (stage / PATCH_META).write_bytes(canonical_json(meta))
        members = [PATCH_META]
        for rel in diff.changed:
            target = stage / PATCH_FILES_DIR / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((new_tree / rel).read_bytes())
            members.append(f"{PATCH_FILES_DIR}/{rel}")
        write_archive(dest, stage, members)
    return dest


def apply_patch(patch_archive: Path, tree: Path, *, expect_app: str, expect_to: str) -> None:
    """インストールツリーへパッチを適用する。

    呼び出し側はツリーの複製に対して適用し、検証が済んでから
    本体と入れ替えること。ここでは入れ替えやロールバックは行わない。
    """
    with TemporaryDirectory() as tmp:
        stage = Path(tmp)
        extract_archive(patch_archive, stage)
        meta_path = stage / PATCH_META
        if not meta_path.is_file():
            raise ConfigError("パッチに patch.json が入っていない")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("app") != expect_app or meta.get("to") != expect_to:
            raise VerificationError(
                f"パッチの対象が合わない: {meta.get('app')} {meta.get('to')} "
                f"(期待: {expect_app} {expect_to})"
            )
        for rel in meta["removed"]:
            target = tree / rel
            if target.is_file():
                target.unlink()
        for rel in meta["changed"]:
            source = stage / PATCH_FILES_DIR / rel
            if not source.is_file():
                raise VerificationError(f"パッチ内のファイルが欠けている: {rel}")
            target = tree / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    _prune_empty_dirs(tree)


def _prune_empty_dirs(tree: Path) -> None:
    """削除で空になったディレクトリを底から畳む。"""
    for path in sorted((p for p in tree.rglob("*") if p.is_dir()), reverse=True):
        with contextlib.suppress(OSError):
            path.rmdir()

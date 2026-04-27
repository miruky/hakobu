"""自動更新クライアント。

マニフェストの署名検証から原子的な入れ替えまでを担う。流れは
チェック(check)と適用(apply)に分かれ、適用は次の順で進む。

1. 成果物(差分パッチか完全アーカイブ)を取得し、ハッシュと署名を検証
2. インストール先の複製に適用し、結果のツリーをリリースの指紋と照合
3. ディレクトリのrenameで本体と入れ替え。失敗したら元に戻す

検証前のバイト列がインストール先に触れることはなく、入れ替えの
途中で失敗しても元のバージョンが残る。
"""

from __future__ import annotations

import json
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import keys
from . import version as version_mod
from .bundle import extract_archive
from .delta import apply_patch
from .errors import UpdateError, VerificationError
from .hashing import STATE_FILE_NAME, hash_bytes, hash_tree
from .manifest import Artifact, Manifest, Release
from .repo import MANIFEST_NAME, SIGNATURE_NAME


class Source:
    """リポジトリの読み出し口。ローカルパスと http(s) URLを同じ顔で扱う。"""

    def __init__(self, location: str) -> None:
        self.location = location.rstrip("/")
        self._is_url = location.startswith(("http://", "https://"))

    def read(self, rel: str) -> bytes:
        if self._is_url:
            with urllib.request.urlopen(f"{self.location}/{rel}") as response:
                return response.read()
        return (Path(self.location) / rel).read_bytes()


@dataclass
class State:
    app: str
    channel: str
    version: str

    @classmethod
    def load(cls, install_dir: Path) -> State:
        path = install_dir / STATE_FILE_NAME
        if not path.is_file():
            raise UpdateError(f"hakobuの管理下にない: {install_dir}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(app=raw["app"], channel=raw["channel"], version=raw["version"])

    def write(self, install_dir: Path) -> None:
        payload = {"app": self.app, "channel": self.channel, "version": self.version}
        (install_dir / STATE_FILE_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


@dataclass
class UpdatePlan:
    current: str
    target: Release
    patch: Artifact | None

    @property
    def delta(self) -> bool:
        return self.patch is not None


class Updater:
    def __init__(self, source: Source | str, install_dir: Path, public_key_text: str) -> None:
        self.source = Source(source) if isinstance(source, str) else source
        self.install_dir = install_dir
        self.public_key: Ed25519PublicKey = keys.public_from_text(public_key_text)

    def fetch_manifest(self) -> Manifest:
        """署名を検証してからマニフェストを読む。"""
        data = self.source.read(MANIFEST_NAME)
        signature = self.source.read(SIGNATURE_NAME).decode("ascii").strip()
        keys.verify(self.public_key, data, signature)
        return Manifest.from_bytes(data)

    def install(self, target_version: str | None = None) -> Release:
        """空のインストール先へ完全アーカイブから導入する。"""
        if self.install_dir.exists() and any(self.install_dir.iterdir()):
            raise UpdateError(f"インストール先が空でない: {self.install_dir}")
        manifest = self.fetch_manifest()
        release = manifest.release(target_version) if target_version else manifest.latest()
        with TemporaryDirectory(dir=self.install_dir.parent) as tmp:
            staging = Path(tmp) / "tree"
            self._stage_full(release, staging)
            State(app=manifest.app, channel=manifest.channel, version=release.version).write(
                staging
            )
            self.install_dir.parent.mkdir(parents=True, exist_ok=True)
            if self.install_dir.exists():
                self.install_dir.rmdir()
            staging.rename(self.install_dir)
        return release

    def check(self) -> UpdatePlan | None:
        """更新があれば計画を返す。最新なら None。"""
        state = State.load(self.install_dir)
        manifest = self.fetch_manifest()
        if manifest.app != state.app:
            raise UpdateError(
                f"リポジトリは {manifest.app} 用で、インストール済みの {state.app} と合わない"
            )
        release = manifest.latest()
        if not version_mod.is_newer(release.version, state.version):
            return None
        return UpdatePlan(
            current=state.version,
            target=release,
            patch=release.patch_from(state.version),
        )

    def apply(self, plan: UpdatePlan) -> Release:
        """計画に従って更新する。差分が使えなければ完全アーカイブに切り替える。"""
        state = State.load(self.install_dir)
        with TemporaryDirectory(dir=self.install_dir.parent) as tmp:
            staging = Path(tmp) / "tree"
            if plan.patch is not None:
                shutil.copytree(self.install_dir, staging)
                (staging / STATE_FILE_NAME).unlink(missing_ok=True)
                data = self._verified_bytes(plan.patch)
                patch_file = Path(tmp) / "patch.tar.gz"
                patch_file.write_bytes(data)
                apply_patch(
                    patch_file,
                    staging,
                    expect_app=state.app,
                    expect_to=plan.target.version,
                )
            else:
                self._stage_full(plan.target, staging)
            self._verify_tree(staging, plan.target)
            State(app=state.app, channel=state.channel, version=plan.target.version).write(staging)
            self._swap(staging)
        return plan.target

    def _stage_full(self, release: Release, staging: Path) -> None:
        data = self._verified_bytes(release.archive)
        with TemporaryDirectory() as tmp:
            archive = Path(tmp) / "bundle.tar.gz"
            archive.write_bytes(data)
            extract_archive(archive, staging)
        self._verify_tree(staging, release)

    def _verified_bytes(self, artifact: Artifact) -> bytes:
        data = self.source.read(artifact.name)
        if hash_bytes(data) != artifact.sha256:
            raise VerificationError(f"{artifact.name} のハッシュが合わない")
        keys.verify(self.public_key, data, artifact.signature)
        return data

    def _verify_tree(self, tree: Path, release: Release) -> None:
        actual = hash_tree(tree)
        if actual != release.files:
            mismatched = {
                rel
                for rel in set(actual) | set(release.files)
                if actual.get(rel) != release.files.get(rel)
            }
            raise VerificationError(
                f"更新後のファイルがマニフェストと一致しない: {', '.join(sorted(mismatched))}"
            )

    def _swap(self, staging: Path) -> None:
        backup = self.install_dir.with_name(self.install_dir.name + ".hakobu-old")
        if backup.exists():
            shutil.rmtree(backup)
        self.install_dir.rename(backup)
        try:
            staging.rename(self.install_dir)
        except OSError as error:
            backup.rename(self.install_dir)
            raise UpdateError(f"入れ替えに失敗したため元に戻した: {error}") from error
        shutil.rmtree(backup)

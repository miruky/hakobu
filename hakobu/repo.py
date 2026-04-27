"""リリースリポジトリの管理。

リポジトリは静的ファイルだけのディレクトリで、そのままWebサーバーや
オブジェクトストレージに置ける。publishはビルド済みバンドルを
取り込み、直前リリースからの差分パッチを作り、全成果物と
マニフェストに署名する。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from . import keys
from .bundle import BuildResult, extract_archive
from .delta import make_patch
from .errors import ConfigError
from .hashing import hash_file
from .manifest import Artifact, Manifest, Patch, Release, now_utc

MANIFEST_NAME = "manifest.json"
SIGNATURE_NAME = "manifest.json.sig"
ARCHIVE_DIR = "archives"
PATCH_DIR = "patches"


@dataclass
class Repository:
    root: Path

    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    def load_manifest(self) -> Manifest:
        path = self.manifest_path()
        if not path.is_file():
            raise ConfigError(f"マニフェストがない: {path}")
        return Manifest.from_bytes(path.read_bytes())

    def publish(
        self,
        build: BuildResult,
        key: Ed25519PrivateKey,
        *,
        channel: str = "stable",
        notes: str = "",
        max_patches: int = 3,
    ) -> Release:
        """ビルド結果をリリースとして取り込み、署名済みマニフェストを書き直す。

        差分パッチは直近 max_patches 件の既存リリースから新バージョンへ
        向けて作る。既存と同じバージョンの再公開は拒否する。
        """
        manifest = self._load_or_init(build.name, channel)
        if any(release.version == build.version for release in manifest.releases):
            raise ConfigError(f"バージョン {build.version} は公開済み。番号を上げること")

        archive_rel = f"{ARCHIVE_DIR}/{build.archive.name}"
        archive_dest = self.root / archive_rel
        archive_dest.parent.mkdir(parents=True, exist_ok=True)
        archive_dest.write_bytes(build.archive.read_bytes())

        release = Release(
            version=build.version,
            created=now_utc(),
            files=dict(build.files),
            archive=self._artifact(archive_rel, key),
            notes=notes,
        )
        release.patches = self._build_patches(manifest, build, key, max_patches)
        manifest.releases.append(release)
        manifest.updated = now_utc()
        self._write_signed(manifest, key)
        return release

    def _build_patches(
        self,
        manifest: Manifest,
        build: BuildResult,
        key: Ed25519PrivateKey,
        max_patches: int,
    ) -> list[Patch]:
        recent = sorted(manifest.releases, key=lambda r: r.created)[-max_patches:]
        patches: list[Patch] = []
        with TemporaryDirectory() as tmp:
            new_tree = Path(tmp) / "tree"
            extract_archive(build.archive, new_tree)
            for old in recent:
                patch_rel = f"{PATCH_DIR}/{build.name}-{old.version}-to-{build.version}.tar.gz"
                make_patch(
                    app=build.name,
                    from_version=old.version,
                    old_files=old.files,
                    to_version=build.version,
                    new_tree=new_tree,
                    dest=self.root / patch_rel,
                )
                artifact = self._artifact(patch_rel, key)
                patches.append(
                    Patch(
                        name=artifact.name,
                        size=artifact.size,
                        sha256=artifact.sha256,
                        signature=artifact.signature,
                        from_version=old.version,
                    )
                )
        return patches

    def _artifact(self, rel: str, key: Ed25519PrivateKey) -> Artifact:
        path = self.root / rel
        data = path.read_bytes()
        return Artifact(
            name=rel,
            size=len(data),
            sha256=hash_file(path),
            signature=keys.sign(key, data),
        )

    def _load_or_init(self, app: str, channel: str) -> Manifest:
        if self.manifest_path().is_file():
            manifest = self.load_manifest()
            if manifest.app != app:
                raise ConfigError(f"リポジトリは {manifest.app} 用で、{app} は公開できない")
            if manifest.channel != channel:
                raise ConfigError(
                    f"リポジトリは {manifest.channel} チャネルで、{channel} とは合わない"
                )
            return manifest
        return Manifest(app=app, channel=channel, updated=now_utc())

    def _write_signed(self, manifest: Manifest, key: Ed25519PrivateKey) -> None:
        data = manifest.to_bytes()
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path().write_bytes(data)
        (self.root / SIGNATURE_NAME).write_text(keys.sign(key, data), encoding="ascii")

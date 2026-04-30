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
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import keys
from . import version as version_mod
from .bundle import extract_archive
from .delta import apply_patch
from .errors import SourceError, UpdateError, VerificationError
from .hashing import STATE_FILE_NAME, hash_bytes, hash_tree
from .manifest import Artifact, Manifest, Release
from .repo import MANIFEST_NAME, SIGNATURE_NAME

DEFAULT_TIMEOUT = 30.0
"""URLリポジトリへの接続・読み出しの既定タイムアウト(秒)。"""

BACKUP_SUFFIX = ".hakobu-backup"
"""更新時に直前の版を残すバックアップディレクトリの接尾辞。入れ替え先の隣に置く。"""

SCRATCH_SUFFIX = ".hakobu-old"
"""入れ替えの最中だけ存在する退避先の接尾辞。成功後は残らない。"""


class Source:
    """リポジトリの読み出し口。ローカルパスと http(s) URLを同じ顔で扱う。

    取得の失敗はすべて SourceError に正規化する。接続不可・404・タイムアウト・
    ファイル不在のどれであっても、呼び出し側は同じ例外で扱える。
    """

    def __init__(self, location: str, *, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.location = location.rstrip("/")
        self._is_url = location.startswith(("http://", "https://"))
        self.timeout = timeout

    def read(self, rel: str) -> bytes:
        if self._is_url:
            return self._read_url(f"{self.location}/{rel}", rel)
        path = Path(self.location) / rel
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise SourceError(f"リポジトリに {rel} がない: {path}") from error
        except OSError as error:
            raise SourceError(f"リポジトリを読めない: {path}({error})") from error

    def _read_url(self, url: str, rel: str) -> bytes:
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise SourceError(
                f"リポジトリから {rel} を取得できない(HTTP {error.code}): {url}"
            ) from error
        except urllib.error.URLError as error:
            raise SourceError(f"リポジトリに接続できない: {url}({error.reason})") from error
        except TimeoutError as error:
            raise SourceError(f"リポジトリへの接続がタイムアウトした: {url}") from error


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
        # 別アプリの名残のバックアップは新規導入には無関係なので片付ける。
        backup = _backup_dir(self.install_dir)
        if backup.exists():
            shutil.rmtree(backup)
        manifest = self.fetch_manifest()
        release = manifest.release(target_version) if target_version else manifest.latest()
        # 作業用の一時ディレクトリは入れ替え先と同じ親に置く(renameを同一FS内に保つ)
        # ため、親を先に用意しておく。深いパスへの新規導入でもここで作られる。
        self.install_dir.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=self.install_dir.parent) as tmp:
            staging = Path(tmp) / "tree"
            self._stage_full(release, staging)
            State(app=manifest.app, channel=manifest.channel, version=release.version).write(
                staging
            )
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

    def apply(self, plan: UpdatePlan, *, keep_backup: bool = True) -> Release:
        """計画に従って更新する。差分が使えなければ完全アーカイブに切り替える。

        keep_backup が真なら、入れ替え後に直前の版を `<dest>.hakobu-backup` として
        残し、`rollback()` で1つ前へ戻せるようにする。容量を惜しむ場合は偽にする。
        """
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
            self._swap(staging, keep_backup=keep_backup)
        return plan.target

    def rollback(self) -> str:
        """直前の版へ戻す。戻し先のバージョンを返す。"""
        return rollback(self.install_dir)

    def rollback_target(self) -> str | None:
        """ロールバックで戻る先のバージョン。残っていなければ None。"""
        return rollback_target(self.install_dir)

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

    def _swap(self, staging: Path, *, keep_backup: bool = True) -> None:
        """検証済みのツリーを原子的に本体へ入れ替える。

        旧版はまず退避先(scratch)へ rename し、新版を本体へ rename する。
        途中で失敗したら退避先を戻す。成功後、keep_backup なら退避先を
        バックアップへ昇格させ(rollback 用)、そうでなければ捨てる。
        """
        scratch = self.install_dir.with_name(self.install_dir.name + SCRATCH_SUFFIX)
        if scratch.exists():
            shutil.rmtree(scratch)
        self.install_dir.rename(scratch)
        try:
            staging.rename(self.install_dir)
        except OSError as error:
            scratch.rename(self.install_dir)
            raise UpdateError(f"入れ替えに失敗したため元に戻した: {error}") from error
        backup = _backup_dir(self.install_dir)
        if backup.exists():
            shutil.rmtree(backup)
        if keep_backup:
            scratch.rename(backup)
        else:
            shutil.rmtree(scratch)


def _backup_dir(install_dir: Path) -> Path:
    """インストール先の隣に置くバックアップディレクトリのパス。"""
    return install_dir.with_name(install_dir.name + BACKUP_SUFFIX)


def rollback_target(install_dir: Path) -> str | None:
    """直前の版(ロールバック先)のバージョン。残っていなければ None。"""
    backup = _backup_dir(install_dir)
    if not (backup / STATE_FILE_NAME).is_file():
        return None
    try:
        return State.load(backup).version
    except UpdateError:
        return None


def rollback(install_dir: Path) -> str:
    """直前の版へ原子的に戻し、戻し先のバージョンを返す。

    update が `keep_backup=True`(既定)で残したバックアップを使う。戻すと
    バックアップは消費されるので、続けて2世代前へは戻れない。検証済みの
    ツリーを入れ替えるだけなので、リポジトリにも公開鍵にも接続しない。
    """
    backup = _backup_dir(install_dir)
    target = rollback_target(install_dir)
    if target is None:
        raise UpdateError(f"戻せる前のバージョンがない: {install_dir}")
    scratch = install_dir.with_name(install_dir.name + SCRATCH_SUFFIX)
    if scratch.exists():
        shutil.rmtree(scratch)
    install_dir.rename(scratch)
    try:
        backup.rename(install_dir)
    except OSError as error:
        scratch.rename(install_dir)
        raise UpdateError(f"ロールバックに失敗したため元に戻した: {error}") from error
    shutil.rmtree(scratch)
    return target

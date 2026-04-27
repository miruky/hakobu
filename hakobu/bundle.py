"""配布バンドルのビルド。

プロジェクトの `hakobu.toml` で対象ファイルを宣言し、決定的な
tar.gz に固める。同じ入力からは必ず同じバイト列ができるため、
ハッシュと署名が安定し、ビルド環境の差が配布物に漏れない。
"""

from __future__ import annotations

import gzip
import io
import os
import tarfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError
from .hashing import hash_file

CONFIG_NAME = "hakobu.toml"


@dataclass
class BundleConfig:
    name: str
    version: str
    include: list[str]
    exclude: list[str]
    entry: str = ""

    @classmethod
    def load(cls, project_dir: Path) -> BundleConfig:
        path = project_dir / CONFIG_NAME
        if not path.is_file():
            raise ConfigError(f"{CONFIG_NAME} が見つからない: {project_dir}")
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
            app = raw["app"]
            files = raw.get("files", {})
            return cls(
                name=app["name"],
                version=app["version"],
                include=list(files.get("include", ["**/*"])),
                exclude=list(files.get("exclude", [])),
                entry=app.get("entry", ""),
            )
        except (KeyError, TypeError, tomllib.TOMLDecodeError) as error:
            raise ConfigError(f"{CONFIG_NAME} を読めない: {error}") from error


@dataclass
class BuildResult:
    name: str
    version: str
    archive: Path
    files: dict[str, str]


def collect_files(project_dir: Path, config: BundleConfig) -> list[str]:
    """includeパターンに合いexcludeに合わない通常ファイルの相対パス一覧。"""
    selected: set[str] = set()
    for pattern in config.include:
        for path in project_dir.glob(pattern):
            if path.is_file():
                selected.add(path.relative_to(project_dir).as_posix())
    for pattern in config.exclude:
        for path in project_dir.glob(pattern):
            if path.is_file():
                selected.discard(path.relative_to(project_dir).as_posix())
    selected.discard(CONFIG_NAME)
    if not selected:
        raise ConfigError("バンドルに入るファイルが1つもない。includeパターンを見直すこと")
    return sorted(selected)


def write_archive(dest: Path, root: Path, rel_paths: list[str]) -> None:
    """決定的tar.gzを書く。mtime・所有者・並び順を固定する。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with (
        dest.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz,
        tarfile.open(fileobj=gz, mode="w") as tar,
    ):
        for rel in sorted(rel_paths):
            source = root / rel
            data = source.read_bytes()
            info = tarfile.TarInfo(rel)
            info.size = len(data)
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o755 if os.access(source, os.X_OK) else 0o644
            tar.addfile(info, io.BytesIO(data))


def extract_archive(archive: Path, dest: Path) -> None:
    """tar.gzを安全に展開する。絶対パスと上方参照は拒否する。"""
    with tarfile.open(archive, mode="r:gz") as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if member.name.startswith("/") or ".." in parts:
                raise ConfigError(f"アーカイブに不正なパスが含まれる: {member.name}")
        dest.mkdir(parents=True, exist_ok=True)
        tar.extractall(dest, filter="data")


def build(project_dir: Path, out_dir: Path) -> BuildResult:
    """hakobu.toml に従ってバンドルを作り、ファイル指紋を返す。"""
    config = BundleConfig.load(project_dir)
    rel_paths = collect_files(project_dir, config)
    archive = out_dir / f"{config.name}-{config.version}.tar.gz"
    write_archive(archive, project_dir, rel_paths)
    files = {rel: hash_file(project_dir / rel) for rel in rel_paths}
    return BuildResult(name=config.name, version=config.version, archive=archive, files=files)

"""チャネルマニフェスト。

リポジトリの `manifest.json` が配布の唯一の台帳で、各リリースの
ファイル指紋・アーカイブ・差分パッチと、それぞれの署名を持つ。
JSONは正規形(キーをソートし空白なし)で書き、バイト列への署名が
再現できるようにする。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import version as version_mod
from .errors import ConfigError


def canonical_json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Artifact:
    """リポジトリ内の配布ファイル1つ。nameはリポジトリルートからの相対パス。"""

    name: str
    size: int
    sha256: str
    signature: str


@dataclass
class Patch(Artifact):
    """from_version からこのリリースへ上げる差分パッチ。"""

    from_version: str = ""


@dataclass
class Release:
    version: str
    created: str
    files: dict[str, str]
    archive: Artifact
    patches: list[Patch] = field(default_factory=list)
    notes: str = ""

    def patch_from(self, current: str) -> Patch | None:
        for patch in self.patches:
            if patch.from_version == current:
                return patch
        return None


@dataclass
class Manifest:
    app: str
    channel: str
    updated: str
    releases: list[Release] = field(default_factory=list)

    def latest(self) -> Release:
        if not self.releases:
            raise ConfigError(f"{self.app} の {self.channel} チャネルにリリースがない")
        newest = version_mod.latest([release.version for release in self.releases])
        return self.release(newest)

    def release(self, target: str) -> Release:
        for release in self.releases:
            if release.version == target:
                return release
        raise ConfigError(f"バージョン {target} はマニフェストにない")

    def to_bytes(self) -> bytes:
        return canonical_json(asdict(self))

    @classmethod
    def from_bytes(cls, data: bytes) -> Manifest:
        try:
            raw = json.loads(data)
            releases = [
                Release(
                    version=item["version"],
                    created=item["created"],
                    files=dict(item["files"]),
                    archive=Artifact(**item["archive"]),
                    patches=[Patch(**patch) for patch in item.get("patches", [])],
                    notes=item.get("notes", ""),
                )
                for item in raw["releases"]
            ]
            return cls(
                app=raw["app"],
                channel=raw["channel"],
                updated=raw["updated"],
                releases=releases,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ConfigError(f"マニフェストを読めない: {error}") from error

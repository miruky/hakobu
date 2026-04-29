"""hakobuのコマンドラインインターフェース。

リリース側(keygen / build / publish / verify)と
利用側(install / update / status)の両方をここから操作する。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__, bundle, console, keys
from . import version as version_mod
from .errors import ConfigError, HakobuError, VerificationError
from .hashing import hash_file
from .repo import Repository
from .update import DEFAULT_TIMEOUT, Source, State, Updater

PRIVATE_KEY_NAME = "signing.key"
PUBLIC_KEY_NAME = "signing.pub"
_TIMEOUT_HELP = "URLリポジトリへの接続タイムアウト秒(ローカルパスでは無視)"


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    console.set_quiet(args.quiet)
    try:
        return args.handler(args)
    except HakobuError as error:
        console.fail(str(error))
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hakobu",
        description="Pythonアプリの配布ツールチェーン。ビルド・署名・差分配布・自動更新",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="エラー以外の出力を抑える(サブコマンドの前に置く)",
    )
    sub = parser.add_subparsers(required=True)

    keygen = sub.add_parser("keygen", help="署名鍵ペアを作る")
    keygen.add_argument("--dir", type=Path, default=Path("keys"), help="鍵の出力先")
    keygen.set_defaults(handler=_cmd_keygen)

    build = sub.add_parser("build", help="hakobu.toml に従ってバンドルを作る")
    build.add_argument("project", type=Path, help="プロジェクトディレクトリ")
    build.add_argument("--out", type=Path, default=Path("dist"), help="アーカイブの出力先")
    build.set_defaults(handler=_cmd_build)

    publish = sub.add_parser("publish", help="ビルドしてリポジトリへ公開する")
    publish.add_argument("project", type=Path)
    publish.add_argument("--repo", type=Path, required=True, help="リリースリポジトリ")
    publish.add_argument("--key", type=Path, required=True, help="署名用の秘密鍵")
    publish.add_argument("--channel", default="stable")
    publish.add_argument("--notes", default="")
    publish.add_argument("--max-patches", type=int, default=3)
    publish.set_defaults(handler=_cmd_publish)

    verify = sub.add_parser("verify", help="リポジトリ全体の署名とハッシュを検証する")
    verify.add_argument("--repo", type=Path, required=True)
    verify.add_argument("--pub", type=Path, required=True, help="公開鍵ファイル")
    verify.set_defaults(handler=_cmd_verify)

    install = sub.add_parser("install", help="リポジトリから新規に導入する")
    install.add_argument("--repo", required=True, help="リポジトリのパスかURL")
    install.add_argument("--pub", type=Path, required=True)
    install.add_argument("--dest", type=Path, required=True)
    install.add_argument("--app-version", default=None, help="導入するバージョン。省略時は最新")
    install.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help=_TIMEOUT_HELP)
    install.set_defaults(handler=_cmd_install)

    update = sub.add_parser("update", help="導入済みディレクトリを最新へ更新する")
    update.add_argument("--repo", required=True, help="リポジトリのパスかURL")
    update.add_argument("--pub", type=Path, required=True)
    update.add_argument("--dest", type=Path, required=True)
    update.add_argument("--check", action="store_true", help="確認だけして適用しない")
    update.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help=_TIMEOUT_HELP)
    update.add_argument("--json", action="store_true", help="結果をJSONで出力する")
    update.set_defaults(handler=_cmd_update)

    status = sub.add_parser("status", help="導入済みのアプリとバージョンを表示する")
    status.add_argument("--dest", type=Path, required=True)
    status.add_argument("--json", action="store_true", help="状態をJSONで出力する")
    status.set_defaults(handler=_cmd_status)

    listing = sub.add_parser("list", help="リポジトリのリリース一覧を表示する")
    listing.add_argument("--repo", type=Path, required=True, help="リリースリポジトリ")
    listing.add_argument("--json", action="store_true", help="一覧をJSONで出力する")
    listing.set_defaults(handler=_cmd_list)

    return parser


def _cmd_keygen(args: argparse.Namespace) -> int:
    args.dir.mkdir(parents=True, exist_ok=True)
    private_path = args.dir / PRIVATE_KEY_NAME
    if private_path.exists():
        raise HakobuError(f"既に鍵がある: {private_path}")
    key = keys.generate()
    keys.save_private(key, private_path)
    (args.dir / PUBLIC_KEY_NAME).write_text(keys.public_text(key) + "\n", encoding="ascii")
    console.success("署名鍵ペアを作成した")
    console.detail(f"  秘密鍵: {private_path}(リリース担当者だけが持つ)")
    console.detail(f"  公開鍵: {args.dir / PUBLIC_KEY_NAME}(アプリ側に同梱する)")
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    result = bundle.build(args.project, args.out)
    size = result.archive.stat().st_size
    console.success(f"{result.name} {result.version} をビルドした")
    console.detail(f"  {result.archive}({size} bytes, {len(result.files)} files)")
    console.detail(f"  sha256: {hash_file(result.archive)}")
    return 0


def _cmd_publish(args: argparse.Namespace) -> int:
    try:
        key = keys.load_private(args.key)
    except FileNotFoundError as error:
        raise ConfigError(f"秘密鍵が見つからない: {args.key}") from error
    console.detail("  ビルド中…")
    result = bundle.build(args.project, args.repo / "archives")
    console.detail("  署名して公開中…")
    release = Repository(args.repo).publish(
        result,
        key,
        channel=args.channel,
        notes=args.notes,
        max_patches=args.max_patches,
    )
    console.success(f"{result.name} {release.version} を {args.channel} チャネルへ公開した")
    for patch in release.patches:
        console.detail(f"  差分: {patch.from_version} から({patch.size} bytes)")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    public = keys.public_from_text(_public_text(args.pub))
    repo = Repository(args.repo)
    data = repo.manifest_path().read_bytes()
    signature = (args.repo / "manifest.json.sig").read_text(encoding="ascii").strip()
    keys.verify(public, data, signature)
    manifest = repo.load_manifest()
    artifacts = [a for release in manifest.releases for a in [release.archive, *release.patches]]
    for index, artifact in enumerate(artifacts, start=1):
        path = args.repo / artifact.name
        if hash_file(path) != artifact.sha256:
            raise VerificationError(f"{artifact.name} のハッシュが合わない")
        keys.verify(public, path.read_bytes(), artifact.signature)
        console.progress(index, len(artifacts), "  検証中")
    console.success("署名とハッシュをすべて検証した")
    console.detail(f"  アプリ: {manifest.app}({manifest.channel} チャネル)")
    console.detail(f"  リリース {len(manifest.releases)} 件 / 成果物 {len(artifacts)} 件")
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    updater = _updater(args)
    release = updater.install(args.app_version)
    console.success(f"{release.version} を {args.dest} へ導入した")
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    updater = _updater(args)
    plan = updater.check()
    if plan is None:
        if args.json:
            _emit_json(_update_record(State.load(args.dest).version))
        else:
            console.success("最新の状態にある")
        return 0
    how = "差分パッチ" if plan.delta else "完全アーカイブ"
    if args.check:
        if args.json:
            _emit_json(_update_record(plan.current, plan.target.version, delta=plan.delta))
        else:
            console.success(f"{plan.current} から {plan.target.version} へ更新できる({how})")
        return 0
    release = updater.apply(plan)
    if args.json:
        _emit_json(_update_record(plan.current, release.version, delta=plan.delta, applied=True))
    else:
        console.success(f"{plan.current} から {release.version} へ更新した({how})")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    state = State.load(args.dest)
    if args.json:
        _emit_json({"app": state.app, "channel": state.channel, "version": state.version})
        return 0
    console.heading(f"{state.app} {state.version}({state.channel} チャネル)")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    manifest = Repository(args.repo).load_manifest()
    # 公開時刻の降順。同じ秒に並んだリリースはバージョンで決定的に分ける。
    releases = sorted(
        manifest.releases,
        key=lambda r: (r.created, version_mod.parse(r.version)),
        reverse=True,
    )
    if args.json:
        _emit_json(
            {
                "app": manifest.app,
                "channel": manifest.channel,
                "releases": [
                    {
                        "version": release.version,
                        "created": release.created,
                        "size": release.archive.size,
                        "patches": [patch.from_version for patch in release.patches],
                        "notes": release.notes,
                    }
                    for release in releases
                ],
            }
        )
        return 0
    header = f"{manifest.app}({manifest.channel} チャネル): リリース {len(manifest.releases)} 件"
    console.heading(header)
    for release in releases:
        date = release.created[:10]
        size = _human_size(release.archive.size)
        note = f"  {release.notes}" if release.notes else ""
        row = f"  {release.version:<10} {date}  {size:>9}  パッチ{len(release.patches)}"
        console.line(row + note)
    return 0


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _update_record(
    current: str,
    target: str | None = None,
    *,
    delta: bool = False,
    applied: bool = False,
) -> dict[str, object]:
    """update --json の1レコード。target が None なら更新なしを表す。"""
    return {
        "current": current,
        "available": target is not None,
        "target": target,
        "delta": delta,
        "applied": applied,
    }


def _emit_json(payload: dict[str, object]) -> None:
    """機械可読の出力。利用側がパースするため --quiet でも必ず出す。"""
    print(json.dumps(payload, ensure_ascii=False))


def _public_text(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii")
    except OSError as error:
        raise ConfigError(f"公開鍵を読めない: {path}") from error


def _updater(args: argparse.Namespace) -> Updater:
    return Updater(Source(args.repo, timeout=args.timeout), args.dest, _public_text(args.pub))


if __name__ == "__main__":
    raise SystemExit(main())

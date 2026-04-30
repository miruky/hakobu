<img src="docs/logo.svg" width="88" align="right" alt="hakobuのロゴ">

# hakobu

[![CI](https://github.com/miruky/hakobu/actions/workflows/ci.yml/badge.svg)](https://github.com/miruky/hakobu/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![Ed25519](https://img.shields.io/badge/Signing-Ed25519-c66b2e)
![License](https://img.shields.io/badge/License-MIT-green)

**Pythonアプリの配布ツールチェーン。決定的ビルド・Ed25519署名・差分配布・原子的な自動更新を、静的ファイルのリポジトリだけで完結させる。**

## 概要

社内ツールや常駐スクリプトを各マシンへ配って回ると、すぐに「どこに何のバージョンが入っているか分からない」状態になる。PyPIに上げるほどでもなく、かといってzipを手で配るのは更新のたびに事故る。hakobuはこの中間を埋める。リリース側は `hakobu publish` 一発でビルド・署名・差分パッチ生成までを済ませ、利用側は `hakobu update` 一発で検証つきの更新を受け取る。

配布の経路に専用サーバーは要らない。リポジトリはマニフェストとtar.gzが並んだだけのディレクトリで、Webサーバー・オブジェクトストレージ・共有フォルダのどれに置いても動く。改竄対策はEd25519署名で行い、検証を通らないバイト列がインストール先に触れることはない。更新はディレクトリのrenameによる入れ替えなので、途中で電源が落ちても旧バージョンが残る。

## アーキテクチャ

![アーキテクチャ図](docs/architecture.svg)

リリース側と利用側は `manifest.json` だけで会話する。マニフェストは各リリースのファイル指紋(SHA-256)・アーカイブ・差分パッチと、それぞれの署名を持つ正規形JSONで、それ自体にも署名が付く。

## 技術スタック

| 領域 | 採用技術 |
|------|---------|
| 言語 | Python 3.12+ |
| 署名 | Ed25519([cryptography](https://cryptography.io/)) |
| ハッシュ | SHA-256 |
| アーカイブ | 決定的tar.gz(標準ライブラリ) |
| 設定 | hakobu.toml(tomllib) |
| テスト | pytest |
| リンタ・フォーマッタ | Ruff |
| CI | GitHub Actions |

## 使い方

### 1. 鍵を作る

```
$ hakobu keygen --dir keys
秘密鍵: keys/signing.key(リリース担当者だけが持つ)
公開鍵: keys/signing.pub(アプリ側に同梱する)
指紋: 2c67:6661:e30d:8886
```

指紋は公開鍵の短いダイジェストで、配布側と利用側が同じ鍵を使っているかを目で照合するのに使う。`hakobu verify` も検証に使った鍵の指紋を併せて表示する。

### 2. プロジェクトに hakobu.toml を置く

```toml
[app]
name = "uranai"
version = "1.0.0"
entry = "uranai.main:run"

[files]
include = ["uranai/**/*.py", "assets/**/*"]
exclude = ["**/__pycache__/**"]
```

### 3. 公開する

```
$ hakobu publish ./uranai --repo ./repo --key keys/signing.key
uranai 1.0.0 を stable チャネルへ公開した
```

2回目以降の公開では、直近リリースからの差分パッチが自動で作られる。

```
$ hakobu publish ./uranai --repo ./repo --key keys/signing.key
uranai 1.1.0 を stable チャネルへ公開した
  差分: 1.0.0 から(303 bytes)
```

repoディレクトリをそのままWebサーバーなどへ同期すれば配布開始になる。`hakobu verify --repo ./repo --pub keys/signing.pub` で、リポジトリ全成果物の署名とハッシュを一括検証できる。

公開済みのリリースは `hakobu list --repo ./repo` で一覧でき、古い版がたまってきたら整理する。

```
$ hakobu prune --repo ./repo --key keys/signing.key --keep 5
2 件のリリースを取り除いた
  バージョン: 1.0.0, 1.1.0
  ファイル 7 件を削除した
```

`prune` は最新の数件だけを残し、外したバージョンのアーカイブと、もう使われない差分パッチを消す。マニフェストは残った内容で署名し直されるので、整理後も `verify` を通る。

### 4. 利用側で導入・更新する

```
$ hakobu install --repo https://example.com/repo --pub signing.pub --dest ~/apps/uranai
1.0.0 を ~/apps/uranai へ導入した

$ hakobu update --repo https://example.com/repo --pub signing.pub --dest ~/apps/uranai --check
1.0.0 から 1.1.0 へ更新できる(差分パッチ)

$ hakobu update --repo https://example.com/repo --pub signing.pub --dest ~/apps/uranai
1.0.0 から 1.1.0 へ更新した(差分パッチ)
```

`--repo` はローカルパスでもURLでもよい。URLからの取得は `--timeout` 秒(既定30)で打ち切るので、配信元が落ちていても更新コマンドが固まらない。現在の状態は `hakobu status --dest DIR` で確認できる。

更新すると直前の版を `<dest>.hakobu-backup` として隣に残し、新版に不具合が出たら1つ前へ戻せる。`status` は戻し先のバージョンも示す。

```
$ hakobu rollback --dest ~/apps/uranai
1.0.0 へ戻した
```

戻せるのは直前の1世代だけで、戻すとバックアップは消費される。容量を惜しむ環境では `update --no-backup` でバックアップを残さないようにできる(その場合ロールバックはできない)。ロールバックはローカルのディレクトリを入れ替えるだけなので、リポジトリにも公開鍵にも接続しない。

`status` `list` `verify` と `update --check` は `--json` を付けると機械可読の出力に切り替わる。更新の有無を別プロセスから判定したいときに使う。

```
$ hakobu update --repo https://example.com/repo --pub signing.pub --dest ~/apps/uranai --check --json
{"current": "1.0.0", "available": true, "target": "1.1.0", "delta": true, "applied": false}
```

### ライブラリとして組み込む

アプリ自身に更新機能を持たせる場合は `Updater` を直接使う。

```python
from pathlib import Path
from hakobu import Updater

updater = Updater("https://example.com/repo", Path("~/apps/uranai").expanduser(), PUBLIC_KEY)
plan = updater.check()
if plan is not None:
    print(f"{plan.current} から {plan.target.version} へ更新します")
    updater.apply(plan)
    # 起動確認に失敗したら直前の版へ戻す
    if not launches_ok():
        updater.rollback()
```

## プロジェクト構成

- `hakobu/`
  - `bundle.py` — hakobu.toml の解釈と決定的tar.gzのビルド
  - `keys.py` — Ed25519の鍵生成・署名・検証
  - `manifest.py` — 正規形JSONのチャネルマニフェスト
  - `delta.py` — 差分パッチの生成と適用
  - `repo.py` — リリースリポジトリへの公開と署名
  - `update.py` — 検証・差分適用・原子的入れ替え・ロールバックを行う更新クライアント
  - `version.py` — バージョン番号の比較
  - `cli.py` — keygen / build / publish / verify / list / prune / install / update / rollback / status
- `tests/` — 単体テストとCLIを通したリリースフローのテスト

## はじめ方

前提: Python 3.12以上。

```
git clone https://github.com/miruky/hakobu.git
cd hakobu
python -m venv .venv && source .venv/bin/activate
make install   # pip install -e ".[dev]"
```

テストとlint:

```
make test   # pytest
make lint   # ruff check + ruff format --check
```

## 設計方針

**検証してからでなければ書かない。** ダウンロードしたバイト列はハッシュ照合と署名検証を通ってから初めて展開され、適用はインストール先の複製に対して行う。複製のツリー全体がマニフェストの指紋と一致して初めて、renameで本体と入れ替える。失敗したらどの段階でも元のバージョンが残る。

**前へ戻れるようにする。** 入れ替えで押し出した直前の版は捨てずに隣へ残す。新版が検証を通っても実環境で動かないことはあるので、`rollback` で1コマンド戻せるようにした。戻しも検証済みツリーのrenameだけで、ネットワークには触れない。保持するのは1世代分で、容量を惜しむ場合は残さない選択もできる。

**ビルドを決定的にする。** tar.gzのmtime・所有者・並び順を固定し、同じソースからは同じバイト列を作る。ハッシュと署名が安定するため、「ビルドし直したら配布物が変わった」が起きない。

**サーバーを持たない。** リポジトリは静的ファイルのみで、配信側に計算を要求しない。動的なライセンス管理や段階的ロールアウトが必要な規模には向かない。差分パッチはファイル単位で、1ファイル内の部分差分(bsdiffの類)はしない。Pythonのソースツリー程度のサイズではファイル単位で十分小さいからだ。

**運用の単位はチャネル。** リポジトリ1つが1チャネル(stableなど)を持つ。ベータ配信は別ディレクトリの別リポジトリとして運用する。プレリリースタグ付きのバージョン番号は扱わない。

## ライセンス

[MIT](LICENSE)

"""hakobu全体で使う例外。

呼び出し側(CLI・自動更新クライアント)が原因別に扱えるよう、
設定・取得・検証・更新の系統に分ける。すべて HakobuError を継承するので、
CLIは基底だけを捕まえて利用者向けのメッセージに変換できる。
"""


class HakobuError(Exception):
    """hakobuの操作の失敗の基底。"""


class ConfigError(HakobuError):
    """hakobu.toml やリポジトリ構成の不備。"""


class SourceError(HakobuError):
    """リポジトリの読み出しに失敗した。接続不可・不在・HTTPエラーなど。"""


class VerificationError(HakobuError):
    """ハッシュ不一致・署名不正。改竄か破損を意味するため、更新は中断する。"""


class UpdateError(HakobuError):
    """更新の適用に失敗した。インストール先は元の状態に戻されている。"""

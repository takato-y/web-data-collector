"""Web から取得した文字列を、帳票と通知に安全に載せるための処理（REQ-013）。"""
from __future__ import annotations

from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

# Excel・表計算ソフトが数式の始まりとして扱う文字
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def safe_cell(value):
    """セルに書く値を無害化する。

    - 文字列以外（数値・日時・None）はそのまま返す
    - Excel に書けない制御文字を取り除く
    - 先頭が数式の始まりになる文字なら、先頭に ' を付けて文字列として扱わせる
    """
    if not isinstance(value, str):
        return value
    value = ILLEGAL_CHARACTERS_RE.sub("", value)
    if value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def escape_slack(text: str) -> str:
    """Slack の書式で特別な意味を持つ < > & を置き換える（全員宛ての呼び出し記法 <!channel> 等を無効化）。"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def neutralize_mentions(text: str) -> str:
    """@everyone・@here・@channel を呼び出しとして働かない形にする（ゼロ幅スペースを挟む）。"""
    for word in ("everyone", "here", "channel"):
        text = text.replace("@" + word, "@​" + word)
    return text

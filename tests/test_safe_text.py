"""REQ-013 Web 由来の文字列の無害化のテスト。"""
import pytest

from webcollector.safe_text import escape_slack, neutralize_mentions, safe_cell


@pytest.mark.parametrize("raw, expected", [
    ("=HYPERLINK(\"https://example.com\")", "'=HYPERLINK(\"https://example.com\")"),
    ("+3色ボールペン", "'+3色ボールペン"),
    ("-20%OFF", "'-20%OFF"),
    ("@ペンケース", "'@ペンケース"),
    ("\t=1+1", "'\t=1+1"),
    ("\r=1+1", "'\r=1+1"),
    ("\n=1+1", "'\n=1+1"),
    ("方眼ノート", "方眼ノート"),
    ("A=B", "A=B"),            # 先頭以外の = はそのまま
    ("\x01=1+1", "'=1+1"),     # 制御文字を除いた結果が = で始まる場合も無害化
])
def test_safe_cell_strings(raw, expected):
    assert safe_cell(raw) == expected


def test_safe_cell_keeps_non_strings():
    assert safe_cell(-82) == -82
    assert safe_cell(None) is None


def test_slack_and_mentions():
    assert escape_slack("<!channel> A&B") == "&lt;!channel&gt; A&amp;B"
    assert neutralize_mentions("@everyone セール") == "@​everyone セール"

"""FN-005 解析のテスト。"""
import pytest

from webcollector.config import AppConfig, FieldSpec
from webcollector.models import IN_STOCK, LOW_STOCK, OUT_OF_STOCK, UNKNOWN
from webcollector.parser import clean_text, find_next_url, parse_items, parse_price, normalize_stock

WORDS = AppConfig(targets=[]).stock_words


@pytest.mark.parametrize("text, expected", [
    ("¥1,280", 1280), ("￥980", 980), ("1,280円（税込）", 1280), ("税込 ３９８円", 398),
    ("価格: 2個で 310円", 310), ("550", 550), ("価格未定", None), ("", None), (None, None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("在庫あり", IN_STOCK), ("残りわずか", LOW_STOCK), ("在庫切れ", OUT_OF_STOCK),
    ("売り切れ（入荷未定）", OUT_OF_STOCK), ("お問い合わせください", UNKNOWN), (None, UNKNOWN),
])
def test_normalize_stock(text, expected):
    assert normalize_stock(text, WORDS) == expected


def test_parse_items_and_next():
    html = """
    <ul><li class="c" data-product-id="X1"><a class="l" href="/p/X1"><span class="n"> ノート\n A5 </span></a>
    <span class="p">¥1,000</span></li>
    <li class="c" data-product-id="X2"><span class="n">ペン</span></li></ul>
    <a class="next" href="?page=2">次へ</a>"""
    fields = {
        "product_id": FieldSpec(attr="data-product-id"),
        "name": FieldSpec(".n"),
        "price": FieldSpec(".p", type="price"),
        "url": FieldSpec("a.l", "href", "url"),
    }
    rows = parse_items(html, "http://shop.example.com/list", "li.c", fields, WORDS)
    assert rows[0] == {"product_id": "X1", "name": "ノート A5", "price": 1000, "url": "http://shop.example.com/p/X1"}
    assert rows[1]["price"] is None and rows[1]["url"] is None
    assert find_next_url(html, "http://shop.example.com/list", "a.next") == "http://shop.example.com/list?page=2"
    assert find_next_url(html, "http://shop.example.com/list", "a.none") is None


def test_clean_text_truncates_long_text():
    assert len(clean_text("あ" * 500)) == 200
    assert clean_text("   ") is None

"""HTML の解析: CSS セレクタで値を取り出し、価格・在庫を正規化する（FN-005）。"""
from __future__ import annotations

import logging
import re
import unicodedata
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from webcollector.config import FieldSpec
from webcollector.models import IN_STOCK, LOW_STOCK, OUT_OF_STOCK, UNKNOWN

log = logging.getLogger(__name__)

MAX_TEXT_LEN = 200  # 想定外に長い文字列を保存しない
_PRICE_WITH_MARK = re.compile(r"[¥￥]\s*([0-9][0-9,]*)|([0-9][0-9,]*)\s*円")
_NUMBER = re.compile(r"[0-9][0-9,]*")


def clean_text(text: str | None) -> str | None:
    """前後の空白と連続する空白・改行を詰める。空なら None。"""
    if text is None:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_TEXT_LEN] or None


def parse_price(text: str | None) -> int | None:
    """「¥1,280」「1,280円（税込）」などから整数の価格を取り出す。取り出せなければ None。"""
    if not text:
        return None
    text = unicodedata.normalize("NFKC", text)
    m = _PRICE_WITH_MARK.search(text)
    raw = (m.group(1) or m.group(2)) if m else None
    if raw is None:
        m2 = _NUMBER.search(text)
        raw = m2.group(0) if m2 else None
    if raw is None:
        return None
    try:
        return int(raw.replace(",", ""))
    except ValueError:
        return None


def normalize_stock(text: str | None, words: dict[str, list[str]]) -> str:
    """在庫の表示を 4 区分に揃える。品切れ系の語を先に見る（「在庫あり→在庫切れ」の誤判定を避ける）。"""
    if not text:
        return UNKNOWN
    for key, code in (("out_of_stock", OUT_OF_STOCK), ("low_stock", LOW_STOCK), ("in_stock", IN_STOCK)):
        if any(w in text for w in words.get(key, [])):
            return code
    return UNKNOWN


def extract(el: Tag, spec: FieldSpec, base_url: str, stock_words: dict[str, list[str]]):
    """1 項目を取り出し、型に応じて変換する。"""
    node = el.select_one(spec.selector) if spec.selector else el
    if node is None:
        return None
    raw = node.get(spec.attr) if spec.attr else node.get_text(" ")
    if isinstance(raw, list):  # class 属性などは配列で返る
        raw = " ".join(raw)
    if spec.type == "price":
        return parse_price(raw)
    if spec.type == "stock":
        return normalize_stock(raw, stock_words)
    if spec.type == "url":
        return urljoin(base_url, raw.strip()) if raw else None
    return clean_text(raw)


def parse_items(html: str, base_url: str, item_selector: str, fields: dict[str, FieldSpec],
                stock_words: dict[str, list[str]]) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for el in soup.select(item_selector):
        rows.append({name: extract(el, spec, base_url, stock_words) for name, spec in fields.items()})
    return rows


def find_next_url(html: str, base_url: str, selector: str | None) -> str | None:
    if not selector:
        return None
    node = BeautifulSoup(html, "html.parser").select_one(selector)
    if node is None or not node.get("href"):
        return None
    return urljoin(base_url, node["href"])


def parse_detail(html: str, base_url: str, fields: dict[str, FieldSpec],
                 stock_words: dict[str, list[str]]) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    return {name: extract(soup, spec, base_url, stock_words) for name, spec in fields.items()}

"""差分検出（FN-008）。前回までの記録と今回の収集結果を比べ、6 種類の変更を求める。

誤報を避けるための決まり（ADR-0003）:
- 初回の実行は比べる相手が無いため、変更を出さない（全商品が「新商品」になるのを防ぐ）
- 値が取れなかった項目（None・在庫「不明」）は比べない
- 掲載終了は、今回の実行がすべてのページを取得できた場合（success）だけ判定する
"""
from __future__ import annotations

from dataclasses import dataclass

from webcollector.models import AVAILABLE, OUT_OF_STOCK, STOCK_LABELS, UNKNOWN, ProductItem

EVENT_LABELS = {
    "price_down": "値下げ",
    "price_up": "値上げ",
    "out_of_stock": "在庫切れ",
    "restock": "再入荷",
    "new": "新商品",
    "delisted": "掲載終了",
}
EVENT_ORDER = list(EVENT_LABELS)


@dataclass
class ChangeEvent:
    product_id: str
    event_type: str
    old_value: str | None = None
    new_value: str | None = None
    price_diff: int | None = None


@dataclass
class PreviousState:
    """比較の相手（前回までに分かっていること）。"""

    has_previous_run: bool
    known_products: set[str]           # これまでに一度でも見た商品
    listed_products: set[str]          # 前回まで掲載中だった商品
    last_price: dict[str, int]         # 商品ごとの直近の価格（取れた値のみ）
    last_stock: dict[str, str]         # 商品ごとの直近の在庫（不明を除く）


def _yen(value: int | None) -> str | None:
    return None if value is None else f"{value:,}円"


def detect_changes(prev: PreviousState, items: list[ProductItem], run_status: str) -> list[ChangeEvent]:
    if not prev.has_previous_run:
        return []
    events: list[ChangeEvent] = []
    current_ids = set()
    for item in items:
        pid = item.product_id
        current_ids.add(pid)
        if pid not in prev.known_products:
            events.append(ChangeEvent(pid, "new", None, _yen(item.price)))
            continue
        old_price = prev.last_price.get(pid)
        if item.price is not None and old_price is not None and item.price != old_price:
            kind = "price_down" if item.price < old_price else "price_up"
            events.append(ChangeEvent(pid, kind, _yen(old_price), _yen(item.price), item.price - old_price))
        old_stock = prev.last_stock.get(pid)
        new_stock = item.stock
        if old_stock and new_stock and new_stock != UNKNOWN:
            if old_stock in AVAILABLE and new_stock == OUT_OF_STOCK:
                events.append(ChangeEvent(pid, "out_of_stock", STOCK_LABELS[old_stock], STOCK_LABELS[new_stock]))
            elif old_stock == OUT_OF_STOCK and new_stock in AVAILABLE:
                events.append(ChangeEvent(pid, "restock", STOCK_LABELS[old_stock], STOCK_LABELS[new_stock]))
    if run_status == "success":
        for pid in sorted(prev.listed_products - current_ids):
            events.append(ChangeEvent(pid, "delisted", _yen(prev.last_price.get(pid)), None))
    events.sort(key=lambda e: (EVENT_ORDER.index(e.event_type), e.product_id))
    return events

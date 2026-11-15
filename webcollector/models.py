"""分析部で使うデータ型。値は履歴DB（sql/schema.sql）の列に対応する。"""
from __future__ import annotations

from dataclasses import dataclass

# 在庫状況の区分（収集部が price_snapshots.stock に書く値）
IN_STOCK = "in_stock"
LOW_STOCK = "low_stock"
OUT_OF_STOCK = "out_of_stock"
UNKNOWN = "unknown"

STOCK_LABELS = {
    IN_STOCK: "在庫あり",
    LOW_STOCK: "残りわずか",
    OUT_OF_STOCK: "在庫切れ",
    UNKNOWN: "不明",
}

AVAILABLE = (IN_STOCK, LOW_STOCK)


@dataclass
class SnapshotItem:
    """1 回の収集での 1 商品の価格・在庫。取れなかった値は None。"""

    product_id: str
    price: int | None = None
    stock: str | None = None

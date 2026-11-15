"""収集結果を受け渡すためのデータ型。"""
from __future__ import annotations

from dataclasses import dataclass, field

# 在庫状況の区分（表示名は STOCK_LABELS）
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
class ProductItem:
    """1 商品ぶんの収集結果。取れなかった値は None。"""

    product_id: str
    name: str | None = None
    price: int | None = None
    stock: str | None = None
    category: str | None = None
    url: str | None = None


@dataclass
class CollectResult:
    """1 対象ぶんの収集結果。

    status: success=全ページ取得 / partial=一部失敗 / failed=1 件も取れない /
            skipped=robots.txt などの理由で今回は収集しない
    """

    target: str
    items: list[ProductItem] = field(default_factory=list)
    pages_fetched: int = 0
    error_count: int = 0
    status: str = "success"
    message: str = ""

"""分析部のテスト用: 収集部（collector/src/storage.ts）と同じ書き方で履歴DB に収集結果を入れる。

収集部と分析部の受け渡しは履歴DB だけなので、収集部を動かさずに分析部を試験できる。
両方をつないだ確認は scripts/e2e.sh（両言語をまたぐ通し試験）で行う。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "demo_site" / "data"
STOCK_CODES = {"在庫あり": "in_stock", "残りわずか": "low_stock", "在庫切れ": "out_of_stock"}


def seed_run(conn: sqlite3.Connection, target: str, items: list[dict], status: str = "success",
             started_at: str = "2026-11-15T09:00:00+09:00", pages: int = 1, errors: int = 0) -> int:
    """1 回の収集を記録する。items は product_id・name・price・stock・category・url を持つ辞書。"""
    cur = conn.execute("INSERT INTO collection_runs (target_name, started_at) VALUES (?, ?)", (target, started_at))
    run_id = cur.lastrowid
    if status in ("success", "partial"):
        for it in items:
            conn.execute(
                """INSERT INTO products (target_name, product_id, name, category, url, first_seen_run_id, last_seen_run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (target_name, product_id) DO UPDATE SET
                     name = COALESCE(excluded.name, products.name),
                     category = COALESCE(excluded.category, products.category),
                     url = COALESCE(excluded.url, products.url),
                     last_seen_run_id = excluded.last_seen_run_id""",
                (target, it["product_id"], it.get("name"), it.get("category"), it.get("url"), run_id, run_id))
            conn.execute(
                "INSERT INTO price_snapshots (run_id, target_name, product_id, price, stock, collected_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, target, it["product_id"], it.get("price"), it.get("stock"), started_at))
    conn.execute(
        "UPDATE collection_runs SET finished_at = ?, status = ?, pages_fetched = ?, items_collected = ?, "
        "error_count = ? WHERE run_id = ?", (started_at, status, pages, len(items), errors, run_id))
    conn.commit()
    return run_id


def demo_items(day: str) -> list[dict]:
    """デモショップのデータ（day1.json / day2.json）を、収集部が取り出す形に変える。"""
    data = json.loads((DATA / day).read_text(encoding="utf-8"))
    return [{"product_id": p["id"], "name": p["name"], "price": p["price"], "stock": STOCK_CODES[p["stock"]],
             "category": p["category"], "url": f"http://127.0.0.1:8000/products/{p['id']}"} for p in data["products"]]

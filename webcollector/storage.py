"""履歴DB の読み書き（分析部）。

収集部（collector/src/storage.ts）が書いた実行・商品・スナップショットを読み、
差分検出（FN-008）の結果を change_events に書く。分析部が書き込む列は
products.is_listed・collection_runs.analyzed_at・change_events のみ（基本設計書 2.2）。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from webcollector.diff import ChangeEvent, PreviousState, detect_changes
from webcollector.models import UNKNOWN, SnapshotItem

SCHEMA = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class AnalyzedRun:
    run_id: int
    target: str
    status: str
    events: list[ChangeEvent]


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA.read_text(encoding="utf-8"))

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self):
        """途中で失敗したら、その中で書いた内容をすべて取り消す。"""
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # --- 差分検出（FN-008） -----------------------------------------------
    def _previous_state(self, target: str, run_id: int) -> PreviousState:
        c = self.conn
        has_prev = c.execute(
            "SELECT 1 FROM collection_runs WHERE target_name = ? AND run_id < ? "
            "AND status IN ('success', 'partial') LIMIT 1", (target, run_id)).fetchone() is not None
        # この実行より前に初めて見た商品だけを「既知」とする（収集部は今回の商品も products に書いているため）
        products = c.execute(
            "SELECT product_id, is_listed FROM products WHERE target_name = ? AND first_seen_run_id < ?",
            (target, run_id)).fetchall()
        last_price = {r["product_id"]: r["price"] for r in c.execute(
            """SELECT s.product_id, s.price FROM price_snapshots s
               JOIN (SELECT product_id, MAX(run_id) AS run_id FROM price_snapshots
                     WHERE target_name = ? AND run_id < ? AND price IS NOT NULL GROUP BY product_id) m
                 ON s.product_id = m.product_id AND s.run_id = m.run_id
               WHERE s.target_name = ?""", (target, run_id, target))}
        last_stock = {r["product_id"]: r["stock"] for r in c.execute(
            """SELECT s.product_id, s.stock FROM price_snapshots s
               JOIN (SELECT product_id, MAX(run_id) AS run_id FROM price_snapshots
                     WHERE target_name = ? AND run_id < ? AND stock IS NOT NULL AND stock <> ?
                     GROUP BY product_id) m
                 ON s.product_id = m.product_id AND s.run_id = m.run_id
               WHERE s.target_name = ?""", (target, run_id, UNKNOWN, target))}
        return PreviousState(
            has_previous_run=has_prev,
            known_products={r["product_id"] for r in products},
            listed_products={r["product_id"] for r in products if r["is_listed"]},
            last_price=last_price,
            last_stock=last_stock,
        )

    def pending_runs(self) -> list[sqlite3.Row]:
        """収集が終わっていて、まだ分析していない実行（古い順）。"""
        return self.conn.execute(
            "SELECT * FROM collection_runs WHERE analyzed_at IS NULL AND status <> 'running' ORDER BY run_id").fetchall()

    def analyze_pending(self) -> list[AnalyzedRun]:
        """未分析の実行を古い順に分析する。1 実行ごとに 1 つのトランザクションで書く。"""
        done: list[AnalyzedRun] = []
        for run in self.pending_runs():
            done.append(self._analyze_run(run))
        return done

    def _analyze_run(self, run: sqlite3.Row) -> AnalyzedRun:
        run_id, target, status = run["run_id"], run["target_name"], run["status"]
        events: list[ChangeEvent] = []
        with self.tx() as c:
            if status in ("success", "partial"):
                items = [SnapshotItem(r["product_id"], r["price"], r["stock"]) for r in c.execute(
                    "SELECT product_id, price, stock FROM price_snapshots WHERE run_id = ? ORDER BY product_id",
                    (run_id,))]
                events = detect_changes(self._previous_state(target, run_id), items, status)
                detected_at = run["finished_at"] or run["started_at"]
                c.executemany("UPDATE products SET is_listed = 1 WHERE target_name = ? AND product_id = ?",
                              [(target, i.product_id) for i in items])
                for e in events:
                    if e.event_type == "delisted":
                        c.execute("UPDATE products SET is_listed = 0 WHERE target_name = ? AND product_id = ?",
                                  (target, e.product_id))
                    c.execute(
                        "INSERT INTO change_events (run_id, target_name, product_id, event_type, old_value, "
                        "new_value, price_diff, detected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (run_id, target, e.product_id, e.event_type, e.old_value, e.new_value, e.price_diff,
                         detected_at))
            c.execute("UPDATE collection_runs SET analyzed_at = ? WHERE run_id = ?", (now_iso(), run_id))
        return AnalyzedRun(run_id, target, status, events)

    # --- 読み出し（帳票・通知用） ---------------------------------------
    def latest_runs(self) -> list[sqlite3.Row]:
        """対象ごとの最新の実行。"""
        return self.conn.execute(
            """SELECT * FROM collection_runs WHERE run_id IN
               (SELECT MAX(run_id) FROM collection_runs GROUP BY target_name) ORDER BY target_name""").fetchall()

    def events_for_runs(self, run_ids: list[int]) -> list[sqlite3.Row]:
        if not run_ids:
            return []
        marks = ",".join("?" * len(run_ids))
        return self.conn.execute(
            f"""SELECT e.*, p.name, p.url FROM change_events e
                JOIN products p ON p.target_name = e.target_name AND p.product_id = e.product_id
                WHERE e.run_id IN ({marks}) ORDER BY e.event_id""", run_ids).fetchall()

    def listed_products(self) -> list[sqlite3.Row]:
        """掲載中の商品と、その最新のスナップショット。"""
        return self.conn.execute(
            """SELECT p.target_name, p.product_id, p.name, p.category, p.url, s.price, s.stock, s.collected_at
               FROM products p
               JOIN price_snapshots s ON s.target_name = p.target_name AND s.product_id = p.product_id
                                     AND s.run_id = p.last_seen_run_id
               WHERE p.is_listed = 1 ORDER BY p.target_name, p.product_id""").fetchall()

    def price_history(self, target: str, product_ids: list[str]) -> list[sqlite3.Row]:
        if not product_ids:
            return []
        marks = ",".join("?" * len(product_ids))
        return self.conn.execute(
            f"""SELECT r.run_id, r.started_at, s.product_id, s.price FROM price_snapshots s
                JOIN collection_runs r ON r.run_id = s.run_id
                WHERE s.target_name = ? AND s.product_id IN ({marks}) ORDER BY r.run_id""",
            [target, *product_ids]).fetchall()

    def changed_price_products(self, target: str) -> list[str]:
        return [r[0] for r in self.conn.execute(
            """SELECT product_id FROM change_events WHERE target_name = ?
               AND event_type IN ('price_down', 'price_up') GROUP BY product_id ORDER BY MIN(event_id)""",
            (target,))]

    def unnotified_events(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT e.*, p.name, p.url FROM change_events e
               JOIN products p ON p.target_name = e.target_name AND p.product_id = e.product_id
               WHERE e.notified_at IS NULL ORDER BY e.target_name, e.event_id""").fetchall()

    def mark_notified(self, event_ids: list[int], at: str | None = None) -> None:
        if not event_ids:
            return
        with self.tx() as c:
            c.executemany("UPDATE change_events SET notified_at = ? WHERE event_id = ?",
                          [(at or now_iso(), i) for i in event_ids])

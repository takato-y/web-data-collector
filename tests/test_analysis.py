"""FN-008 差分検出（履歴DB の読み書きを含む）のテスト。"""
import sqlite3

import pytest

from webcollector.storage import Storage
from tests.db_seed import demo_items, seed_run


def kinds(events):
    return sorted((e.event_type, e.product_id) for e in events)


def test_demo_day1_to_day2(demo_db):
    done = demo_db.analyze_pending()
    assert [len(d.events) for d in done] == [0, 8]  # 初回は基準を記録するだけ
    assert kinds(done[1].events) == sorted([
        ("price_down", "A-1001"), ("price_down", "A-1010"), ("price_up", "A-1005"),
        ("out_of_stock", "A-1003"), ("restock", "A-1008"),
        ("new", "A-1013"), ("new", "A-1014"), ("delisted", "A-1012"),
    ])
    rows = demo_db.events_for_runs([done[1].run_id])
    assert len(rows) == 8 and all(r["notified_at"] is None for r in rows)
    assert rows[0]["detected_at"] == "2026-11-15T09:00:00+09:00"
    listed = {r["product_id"] for r in demo_db.listed_products()}
    assert "A-1012" not in listed and "A-1014" in listed and len(listed) == 13
    assert [h["price"] for h in demo_db.price_history("demo_shop", ["A-1001"])] == [480, 398]
    assert demo_db.changed_price_products("demo_shop") == ["A-1001", "A-1010", "A-1005"]
    assert demo_db.pending_runs() == []
    assert demo_db.analyze_pending() == []  # 2 回目は何もしない（二重に検出しない）


def test_runs_are_analyzed_in_order_even_if_piled_up(tmp_path):
    st = Storage(tmp_path / "h.db")
    a = {"product_id": "A", "name": "ノート", "price": 100, "stock": "in_stock"}
    seed_run(st.conn, "x", [a])
    seed_run(st.conn, "x", [{**a, "price": 90}, {"product_id": "B", "price": 50}])
    seed_run(st.conn, "x", [{**a, "price": 90}])  # B が掲載終了
    done = st.analyze_pending()
    assert [kinds(d.events) for d in done] == [[], [("new", "B"), ("price_down", "A")], [("delisted", "B")]]


def test_partial_run_does_not_delist_and_failed_run_is_marked(tmp_path):
    st = Storage(tmp_path / "h.db")
    seed_run(st.conn, "x", [{"product_id": "A", "price": 100}, {"product_id": "B", "price": 200}])
    seed_run(st.conn, "x", [{"product_id": "A", "price": 100}], status="partial", errors=1)
    seed_run(st.conn, "x", [], status="failed", errors=3)
    seed_run(st.conn, "x", [], status="skipped")
    done = st.analyze_pending()
    assert [d.events for d in done] == [[], [], [], []]
    assert {r["product_id"] for r in st.listed_products()} == {"A", "B"}
    assert st.conn.execute("SELECT COUNT(*) FROM collection_runs WHERE analyzed_at IS NULL").fetchone()[0] == 0


def test_relisted_product_is_not_new(tmp_path):
    st = Storage(tmp_path / "h.db")
    a, b = {"product_id": "A", "price": 100}, {"product_id": "B", "price": 200}
    seed_run(st.conn, "x", [a, b])
    seed_run(st.conn, "x", [a])
    seed_run(st.conn, "x", [a, b])
    done = st.analyze_pending()
    assert kinds(done[1].events) == [("delisted", "B")]
    assert done[2].events == []  # 再掲載は「新商品」にしない
    assert {r["product_id"] for r in st.listed_products()} == {"A", "B"}


def test_running_run_is_not_analyzed(tmp_path):
    st = Storage(tmp_path / "h.db")
    st.conn.execute("INSERT INTO collection_runs (target_name, started_at) VALUES ('x', '2026-11-15T09:00:00+09:00')")
    st.conn.commit()
    assert st.analyze_pending() == []  # 収集部が書き込み中の実行には触れない


def test_unnotified_and_mark_notified(demo_db):
    demo_db.analyze_pending()
    ids = [e["event_id"] for e in demo_db.unnotified_events()]
    assert len(ids) == 8
    demo_db.mark_notified(ids)
    assert demo_db.unnotified_events() == []


def test_failure_inside_transaction_rolls_back(tmp_path, monkeypatch):
    st = Storage(tmp_path / "h.db")
    seed_run(st.conn, "x", [{"product_id": "A", "price": 100}])
    seed_run(st.conn, "x", [{"product_id": "A", "price": 90}])
    import webcollector.storage as mod

    def broken(prev, items, status):
        from webcollector.diff import ChangeEvent
        if not prev.has_previous_run:
            return []
        return [ChangeEvent("A", "unknown_kind")]  # CHECK 制約に違反する種類

    monkeypatch.setattr(mod, "detect_changes", broken)
    with pytest.raises(sqlite3.IntegrityError):
        st.analyze_pending()
    # 1 件目（初回）は確定済み、2 件目は取り消されて未分析のまま残る
    assert [r["run_id"] for r in st.pending_runs()] == [2]
    assert st.conn.execute("SELECT COUNT(*) FROM change_events").fetchone()[0] == 0

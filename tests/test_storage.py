"""FN-007 履歴保存のテスト（デモショップの 1 日目 → 2 日目を実際に収集して保存する）。"""
import sqlite3

import pytest

from webcollector.collector import Collector
from webcollector.fetcher import Fetcher
from webcollector.models import CollectResult, ProductItem
from webcollector.storage import Storage
from tests.conftest import NoWaitLimiter, make_config


def run_once(cfg, storage, target):
    c = Collector(cfg, fetcher=Fetcher(cfg.request, cfg.user_agent, NoWaitLimiter(), sleep=lambda s: None))
    run_id = storage.start_run(target.name)
    result = c.collect(target)
    return run_id, result, storage.record_result(run_id, result)


def test_day1_then_day2_detects_changes(site, tmp_path):
    cfg = make_config(site.base, tmp_path)
    st = Storage(tmp_path / "h.db")
    t = cfg.targets[0]
    _, r1, ev1 = run_once(cfg, st, t)
    assert r1.status == "success" and ev1 == []  # 初回は基準を記録するだけ
    site.use("day2.json")
    run2, r2, ev2 = run_once(cfg, st, t)
    got = sorted((e.event_type, e.product_id) for e in ev2)
    assert got == sorted([
        ("price_down", "A-1001"), ("price_down", "A-1010"), ("price_up", "A-1005"),
        ("out_of_stock", "A-1003"), ("restock", "A-1008"),
        ("new", "A-1013"), ("new", "A-1014"), ("delisted", "A-1012"),
    ])
    rows = st.events_for_runs([run2])
    assert len(rows) == 8 and all(r["notified_at"] is None for r in rows)
    listed = {r["product_id"] for r in st.listed_products()}
    assert "A-1012" not in listed and "A-1014" in listed and len(listed) == 13
    hist = st.price_history(t.name, ["A-1001"])
    assert [h["price"] for h in hist] == [480, 398]
    assert st.changed_price_products(t.name) == ["A-1001", "A-1010", "A-1005"]
    runs = st.latest_runs()
    assert runs[0]["status"] == "success" and runs[0]["items_collected"] == 13 and runs[0]["finished_at"]


def test_same_data_twice_has_no_events(site, tmp_path):
    cfg = make_config(site.base, tmp_path)
    st = Storage(tmp_path / "h.db")
    run_once(cfg, st, cfg.targets[0])
    _, _, ev = run_once(cfg, st, cfg.targets[0])
    assert ev == []


def test_skipped_run_saves_no_snapshots(tmp_path):
    st = Storage(tmp_path / "h.db")
    rid = st.start_run("x")
    st.record_result(rid, CollectResult(target="x", status="skipped", message="見送り"))
    assert st.conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == 0
    assert st.latest_runs()[0]["status"] == "skipped"


def test_unnotified_and_mark_notified(tmp_path):
    st = Storage(tmp_path / "h.db")
    r1 = st.start_run("x")
    st.record_result(r1, CollectResult(target="x", items=[ProductItem("A", "ノート", 100)]))
    r2 = st.start_run("x")
    st.record_result(r2, CollectResult(target="x", items=[ProductItem("A", "ノート", 90)]))
    ids = [e["event_id"] for e in st.unnotified_events()]
    assert len(ids) == 1
    st.mark_notified(ids)
    assert st.unnotified_events() == []


def test_failure_inside_transaction_rolls_back(tmp_path):
    st = Storage(tmp_path / "h.db")
    rid = st.start_run("x")
    bad = CollectResult(target="x", items=[ProductItem("A", "ノート", -1)])  # 価格の CHECK 制約に違反
    with pytest.raises(sqlite3.IntegrityError):
        st.record_result(rid, bad)
    assert st.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
    assert st.latest_runs()[0]["status"] == "running"

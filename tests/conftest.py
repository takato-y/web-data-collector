"""テスト共通の部品。"""
from pathlib import Path

import pytest

from webcollector.storage import Storage
from tests.db_seed import demo_items, seed_run

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def demo_db(tmp_path):
    """デモショップの 1 日目 → 2 日目を収集した状態の履歴DB（分析前）。"""
    st = Storage(tmp_path / "h.db")
    seed_run(st.conn, "demo_shop", demo_items("day1.json"), started_at="2026-11-14T09:00:00+09:00")
    seed_run(st.conn, "demo_shop", demo_items("day2.json"), started_at="2026-11-15T09:00:00+09:00")
    yield st
    st.close()

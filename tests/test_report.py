"""FN-009 Excel レポートのテスト（デモショップの 1 日目 → 2 日目を収集した結果から作る）。"""
import zipfile
from datetime import datetime

import pytest
from openpyxl import load_workbook

from webcollector.report import EVENT_FILLS, build_report
from webcollector.storage import Storage
from tests.test_storage import run_once
from tests.conftest import make_config


@pytest.fixture
def report_path(site, tmp_path):
    cfg = make_config(site.base, tmp_path)
    st = Storage(tmp_path / "h.db")
    run_once(cfg, st, cfg.targets[0])
    site.use("day2.json")
    run_once(cfg, st, cfg.targets[0])
    return build_report(st, tmp_path / "out", now=datetime(2026, 11, 15, 9, 0, 0))


def test_sheets_and_counts(report_path):
    assert report_path.name == "report_20261115_090000.xlsx"
    wb = load_workbook(report_path)
    assert wb.sheetnames == ["サマリー", "変更一覧", "最新一覧", "価格推移"]
    changes = wb["変更一覧"]
    assert changes.max_row == 1 + 8
    kinds = [changes.cell(row=r, column=3).value for r in range(2, 10)]
    assert kinds.count("値下げ") == 2 and kinds.count("新商品") == 2 and "掲載終了" in kinds
    assert wb["最新一覧"].max_row == 1 + 13


def test_change_rows_are_colored(report_path):
    ws = load_workbook(report_path)["変更一覧"]
    for r in range(2, ws.max_row + 1):
        kind = ws.cell(row=r, column=3).value
        expected = {"値下げ": "price_down", "値上げ": "price_up", "在庫切れ": "out_of_stock",
                    "再入荷": "restock", "新商品": "new", "掲載終了": "delisted"}[kind]
        assert ws.cell(row=r, column=1).fill.fgColor.rgb.endswith(EVENT_FILLS[expected])


def test_formula_like_names_are_neutralized(report_path):
    wb = load_workbook(report_path)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                assert cell.data_type != "f", f"{ws.title}!{cell.coordinate} が数式になっている"
    names = [c.value for c in wb["最新一覧"]["C"] if c.value]
    assert "'=HYPERLINK(\"https://example.com\",\"詳細\") 付箋セット" in names
    assert "'+3色ボールペン 限定カラー" in names


def test_price_chart_exists(report_path):
    ws = load_workbook(report_path)["価格推移"]
    assert ws["A1"].value == "対象: demo_shop"
    assert ws.cell(row=3, column=2).value == 480 and ws.cell(row=4, column=2).value == 398
    with zipfile.ZipFile(report_path) as z:
        charts = [n for n in z.namelist() if n.startswith("xl/charts/chart")]
        assert charts and b"lineChart" in z.read(charts[0])


def test_empty_database_still_makes_report(tmp_path):
    path = build_report(Storage(tmp_path / "h.db"), tmp_path / "out")
    wb = load_workbook(path)
    assert wb["変更一覧"]["A2"].value == "今回の実行で検出した変更はありません"
    assert wb["価格推移"]["A1"].value == "価格が変わった商品はまだありません"

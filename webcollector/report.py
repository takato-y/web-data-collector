"""Excel レポートの作成（FN-009）。帳票レイアウトは docs/02_基本設計.md の 4 章。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from webcollector.diff import EVENT_LABELS, EVENT_ORDER
from webcollector.models import OUT_OF_STOCK, STOCK_LABELS
from webcollector.safe_text import safe_cell
from webcollector.storage import Storage

MAX_CHART_PRODUCTS = 10  # 1 対象あたりのグラフに載せる商品数の上限
STATUS_LABELS = {"running": "実行中", "success": "成功", "partial": "一部失敗", "failed": "失敗", "skipped": "見送り"}
EVENT_FILLS = {
    "price_down": "C6EFCE",    # 緑
    "price_up": "FFE0B2",      # 橙
    "out_of_stock": "FFC7CE",  # 赤
    "restock": "D9F2FA",       # 水色
    "new": "BDD7EE",           # 青
    "delisted": "E0E0E0",      # 灰
}
HEADER_FILL = PatternFill("solid", fgColor="2F5D8A")
HEADER_FONT = Font(bold=True, color="FFFFFF")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def _write_table(ws, start_row: int, headers: list[str], rows: list[list], widths: list[int]) -> None:
    """見出しつきの表を書く。すべての値は safe_cell を通す。"""
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=start_row, column=col, value=safe_cell(h))
        cell.fill, cell.font, cell.border = HEADER_FILL, HEADER_FONT, BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for r, row in enumerate(rows, start_row + 1):
        for col, value in enumerate(row, 1):
            cell = ws.cell(row=r, column=col, value=safe_cell(value))
            cell.border = BORDER
            if isinstance(value, int):
                cell.number_format = "#,##0"
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = w


def _fill_row(ws, row: int, ncols: int, color: str) -> None:
    fill = PatternFill("solid", fgColor=color)
    for col in range(1, ncols + 1):
        ws.cell(row=row, column=col).fill = fill


def build_report(storage: Storage, out_dir: Path, now: datetime | None = None) -> Path:
    now = now or datetime.now()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"report_{now:%Y%m%d_%H%M%S}.xlsx"
    runs = storage.latest_runs()
    events = storage.events_for_runs([r["run_id"] for r in runs])

    wb = Workbook()
    # --- サマリー ---------------------------------------------------------
    ws = wb.active
    ws.title = "サマリー"
    ws["A1"] = "価格・在庫 収集レポート"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"作成日時: {now:%Y-%m-%d %H:%M}"
    _write_table(ws, 4, ["対象", "実行日時", "状態", "取得ページ数", "取得件数", "エラー件数", "備考"],
                 [[r["target_name"], _fmt_dt(r["started_at"]), STATUS_LABELS.get(r["status"], r["status"]),
                   r["pages_fetched"], r["items_collected"], r["error_count"], r["message"] or ""] for r in runs],
                 [18, 18, 10, 12, 10, 10, 40])
    counts = {k: 0 for k in EVENT_ORDER}
    for e in events:
        counts[e["event_type"]] += 1
    start = 6 + len(runs)
    _write_table(ws, start, ["変更の種類", "件数"], [[EVENT_LABELS[k], counts[k]] for k in EVENT_ORDER], [18, 18])
    for i, k in enumerate(EVENT_ORDER, start + 1):
        ws.cell(row=i, column=1).fill = PatternFill("solid", fgColor=EVENT_FILLS[k])

    # --- 変更一覧 ---------------------------------------------------------
    ws = wb.create_sheet("変更一覧")
    headers = ["検出日時", "対象", "種類", "商品ID", "商品名", "変更前", "変更後", "差額", "URL"]
    rows = [[_fmt_dt(e["detected_at"]), e["target_name"], EVENT_LABELS[e["event_type"]], e["product_id"],
             e["name"], e["old_value"], e["new_value"], e["price_diff"], e["url"]] for e in events]
    _write_table(ws, 1, headers, rows, [17, 16, 10, 10, 40, 12, 12, 9, 40])
    for i, e in enumerate(events, 2):
        _fill_row(ws, i, len(headers), EVENT_FILLS[e["event_type"]])
    ws.freeze_panes = "A2"
    if events:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(events) + 1}"
    else:
        ws.cell(row=2, column=1, value="今回の実行で検出した変更はありません")

    # --- 最新一覧 ---------------------------------------------------------
    ws = wb.create_sheet("最新一覧")
    listed = storage.listed_products()
    headers = ["対象", "商品ID", "商品名", "カテゴリ", "価格", "在庫", "最終取得日時", "URL"]
    rows = [[p["target_name"], p["product_id"], p["name"], p["category"], p["price"],
             STOCK_LABELS.get(p["stock"] or "unknown", "不明"), _fmt_dt(p["collected_at"]), p["url"]] for p in listed]
    _write_table(ws, 1, headers, rows, [16, 10, 40, 12, 10, 12, 17, 40])
    for i, p in enumerate(listed, 2):
        if p["stock"] == OUT_OF_STOCK:
            _fill_row(ws, i, len(headers), EVENT_FILLS["out_of_stock"])
    ws.freeze_panes = "A2"
    if listed:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(listed) + 1}"

    # --- 価格推移 ---------------------------------------------------------
    _price_sheet(wb.create_sheet("価格推移"), storage, [r["target_name"] for r in runs])

    wb.properties.creator = "WebDataCollector"
    wb.save(path)
    return path


def _fmt_dt_sec(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M:%S") if iso else ""
    except ValueError:
        return iso or ""


def _price_sheet(ws, storage: Storage, targets: list[str]) -> None:
    """対象ごとに「表 + 折れ線グラフ」の区画を縦に並べる。価格が変わった商品だけを載せる。"""
    names = {(p["target_name"], p["product_id"]): p["name"] for p in storage.listed_products()}
    row = 1
    for t in targets:
        pids = storage.changed_price_products(t)[:MAX_CHART_PRODUCTS]
        if not pids:
            continue
        ws.cell(row=row, column=1, value=safe_cell(f"対象: {t}")).font = Font(bold=True)
        by_run: dict[int, tuple[str, dict[str, int]]] = {}
        for h in storage.price_history(t, pids):
            by_run.setdefault(h["run_id"], (_fmt_dt_sec(h["started_at"]), {}))[1][h["product_id"]] = h["price"]
        headers = ["取得日時"] + [f"{pid} {(names.get((t, pid)) or '')[:20]}".strip() for pid in pids]
        rows = [[label] + [values.get(pid) for pid in pids] for _, (label, values) in sorted(by_run.items())]
        header_row = row + 1
        _write_table(ws, header_row, headers, rows, [20] + [24] * len(pids))

        chart = LineChart()
        chart.title = f"価格推移（{t}）"
        chart.y_axis.title = "価格（円）"
        chart.x_axis.title = "取得日時"
        chart.height, chart.width = 8, 20
        last = header_row + len(rows)
        chart.add_data(Reference(ws, min_col=2, max_col=len(headers), min_row=header_row, max_row=last),
                       titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=1, min_row=header_row + 1, max_row=last))
        ws.add_chart(chart, f"A{last + 2}")
        row = last + 20  # グラフの高さぶん空けて次の対象へ
    if row == 1:
        ws["A1"] = "価格が変わった商品はまだありません"

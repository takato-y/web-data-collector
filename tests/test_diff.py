"""FN-008 差分検出のテスト（判定の決まりそのもの）。"""
from webcollector.diff import PreviousState, detect_changes
from webcollector.models import IN_STOCK, LOW_STOCK, OUT_OF_STOCK, UNKNOWN, SnapshotItem as P


def prev(**kw):
    base = dict(has_previous_run=True, known_products={"A", "B", "C"}, listed_products={"A", "B", "C"},
                last_price={"A": 1000, "B": 500, "C": 300}, last_stock={"A": IN_STOCK, "B": OUT_OF_STOCK, "C": LOW_STOCK})
    base.update(kw)
    return PreviousState(**base)


def kinds(events):
    return [(e.event_type, e.product_id) for e in events]


def test_first_run_produces_no_events():
    assert detect_changes(prev(has_previous_run=False), [P("A", price=1)], "success") == []


def test_all_six_kinds():
    items = [P("A", price=900, stock=OUT_OF_STOCK), P("B", price=550, stock=IN_STOCK), P("D", price=100)]
    ev = detect_changes(prev(), items, "success")
    assert kinds(ev) == [("price_down", "A"), ("price_up", "B"), ("out_of_stock", "A"),
                         ("restock", "B"), ("new", "D"), ("delisted", "C")]
    down = ev[0]
    assert (down.old_value, down.new_value, down.price_diff) == ("1,000円", "900円", -100)


def test_partial_run_does_not_report_delisted():
    ev = detect_changes(prev(), [P("A", price=1000, stock=IN_STOCK)], "partial")
    assert ev == []


def test_missing_values_are_not_compared():
    items = [P("A", price=None, stock=None), P("B", price=500, stock=UNKNOWN), P("C", price=300, stock=LOW_STOCK)]
    assert detect_changes(prev(), items, "success") == []


def test_low_stock_to_out_is_out_of_stock_and_in_to_low_is_not_event():
    items = [P("A", price=1000, stock=LOW_STOCK), P("B", price=500, stock=OUT_OF_STOCK), P("C", price=300, stock=OUT_OF_STOCK)]
    assert kinds(detect_changes(prev(), items, "success")) == [("out_of_stock", "C")]


def test_relisted_known_product_is_not_new():
    ev = detect_changes(prev(listed_products={"A", "B"}), [P("A", price=1000), P("B", price=500), P("C", price=300)], "success")
    assert ev == []

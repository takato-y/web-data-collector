"""FN-005 一覧・詳細の解析と、収集の流れ（robots.txt・間隔・失敗時の扱い）のテスト。"""
import pytest

from webcollector import js_fetcher
from webcollector.collector import Collector
from webcollector.fetcher import Fetcher
from webcollector.models import IN_STOCK, OUT_OF_STOCK
from tests.conftest import NoWaitLimiter, closed_port_url, make_config


def collector_for(cfg, renderer=None):
    limiter = NoWaitLimiter()
    fetcher = Fetcher(cfg.request, cfg.user_agent, limiter, sleep=lambda s: None)
    return Collector(cfg, fetcher=fetcher, renderer=renderer), limiter


def test_collects_all_pages_and_details(site, tmp_path):
    cfg = make_config(site.base, tmp_path)
    c, limiter = collector_for(cfg)
    r = c.collect(cfg.targets[0])
    assert r.status == "success" and r.error_count == 0
    assert len(r.items) == 12
    assert r.pages_fetched == 3 + 12  # 一覧 3 ページ + 詳細 12 ページ
    by_id = {i.product_id: i for i in r.items}
    assert by_id["A-1001"].price == 480 and by_id["A-1001"].stock == IN_STOCK
    assert by_id["A-1008"].stock == OUT_OF_STOCK and by_id["A-1008"].category == "事務用品"
    assert by_id["A-1001"].url == site.base + "/products/A-1001"
    # robots.txt の Crawl-delay: 1 が設定の 0.5 秒より長いため、1 秒の間隔で待つ
    page_waits = [iv for _, iv in limiter.calls]
    assert page_waits[0] == 0.5            # robots.txt 自体の取得は設定の間隔
    assert set(page_waits[1:]) == {1.0}


def test_start_url_disallowed_by_robots_is_skipped(site, tmp_path):
    cfg = make_config(site.base, tmp_path)
    t = cfg.targets[0]
    t.start_url = site.base + "/admin/"
    c, limiter = collector_for(cfg)
    r = c.collect(t)
    assert r.status == "skipped" and "robots.txt" in r.message
    assert len(limiter.calls) == 1  # robots.txt だけ取得し、/admin/ は取得していない


def test_robots_unavailable_skips_site(tmp_path):
    cfg = make_config(closed_port_url(), tmp_path)
    cfg.request.max_retries = 0
    c, _ = collector_for(cfg)
    r = c.collect(cfg.targets[0])
    assert r.status == "skipped" and "見送り" in r.message


def test_max_pages_marks_partial(site, tmp_path):
    cfg = make_config(site.base, tmp_path)
    cfg.request.max_pages = 2
    cfg.targets[0].detail_fields = {}
    c, _ = collector_for(cfg)
    r = c.collect(cfg.targets[0])
    assert r.status == "partial" and len(r.items) == 10 and "上限" in r.message


def test_detail_failure_marks_partial(make_site, tmp_path):
    site = make_site()
    cfg = make_config(site.base, tmp_path)
    c, _ = collector_for(cfg)
    # 詳細ページの 1 件を存在しない URL に差し替える
    orig = c._to_items

    def broken(rows, target, result):
        items = orig(rows, target, result)
        items[0].url = site.base + "/products/NOPE"
        return items

    c._to_items = broken
    r = c.collect(cfg.targets[0])
    assert r.status == "partial" and r.error_count == 1 and len(r.items) == 12
    assert r.items[0].stock is None  # 取れなかった値は空のまま（在庫切れと誤判定しない）


def test_js_target_with_renderer(site, tmp_path):
    cfg = make_config(site.base, tmp_path)
    html = '<li class="product-card" data-product-id="N-1"><span class="name">万年筆</span>' \
           '<span class="price">¥3,300</span><span class="stock">在庫あり</span></li>'
    c, _ = collector_for(cfg, renderer=lambda url, ua, wait, timeout: html)
    r = c.collect(cfg.targets[1])
    assert r.status == "success" and r.items[0].price == 3300 and r.items[0].stock == IN_STOCK


def test_js_target_skipped_when_playwright_missing(site, tmp_path):
    cfg = make_config(site.base, tmp_path)

    def missing(*a):
        raise js_fetcher.JsUnavailable("Playwright が導入されていません")

    c, _ = collector_for(cfg, renderer=missing)
    r = c.collect(cfg.targets[1])
    assert r.status == "skipped" and "Playwright" in r.message


@pytest.mark.js
@pytest.mark.skipif(not js_fetcher.is_available(), reason="Playwright 未導入")
def test_js_target_with_real_browser(site, tmp_path):
    cfg = make_config(site.base, tmp_path)
    c, _ = collector_for(cfg)  # 実際のブラウザで描画する
    try:
        r = c.collect(cfg.targets[1])
    except js_fetcher.JsUnavailable as e:
        pytest.skip(str(e))
    if r.status == "skipped":
        pytest.skip(r.message)
    assert r.status == "success"
    assert {i.product_id for i in r.items} == {"N-2001", "N-2002"}

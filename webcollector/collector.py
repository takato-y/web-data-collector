"""1 対象ぶんの収集の流れ（一覧のページ送り → 詳細 → 結果のまとめ）。"""
from __future__ import annotations

import logging
from typing import Callable
from urllib.parse import urlparse

from webcollector import js_fetcher
from webcollector.config import AppConfig, TargetConfig
from webcollector.fetcher import Fetcher, FetchError
from webcollector.models import CollectResult, ProductItem
from webcollector.parser import find_next_url, parse_detail, parse_items
from webcollector.politeness import RateLimiter, RobotsPolicy

log = logging.getLogger(__name__)

ITEM_FIELDS = ("name", "price", "stock", "category", "url")

# JavaScript ページの描画関数の型（差し替え可能にしてテストする）
Renderer = Callable[[str, str, "str | None", float], str]


class Collector:
    def __init__(self, cfg: AppConfig, fetcher: Fetcher | None = None,
                 robots: RobotsPolicy | None = None, renderer: Renderer | None = None):
        self.cfg = cfg
        self.fetcher = fetcher or Fetcher(cfg.request, cfg.user_agent, RateLimiter())
        self.robots = robots or RobotsPolicy(self.fetcher.fetch_robots, cfg.user_agent)
        self.renderer = renderer or js_fetcher.render

    # --- 取得の共通部分 -------------------------------------------------
    def _check_robots(self, url: str) -> bool:
        if self.robots.allowed(url):
            return True
        log.warning("robots.txt で禁止されているため取得しません: %s", url)
        return False

    def _get_html(self, url: str) -> str:
        interval = self.robots.interval_for(url, self.cfg.request.interval_sec)
        return self.fetcher.get(url, interval).text

    # --- 本体 -----------------------------------------------------------
    def collect(self, target: TargetConfig) -> CollectResult:
        result = CollectResult(target=target.name)
        if self.robots.is_unavailable(target.start_url):
            result.status, result.message = "skipped", "robots.txt を取得できないため見送り"
            return result
        if not self._check_robots(target.start_url):
            result.status, result.message = "skipped", "開始 URL が robots.txt で禁止されている"
            return result
        if target.type == "js":
            rows = self._collect_js(target, result)
        else:
            rows = self._collect_static(target, result)
        if result.status == "skipped":
            return result
        result.items = self._to_items(rows, target, result)
        if target.detail_fields:
            self._fill_details(target, result)
        self._decide_status(result)
        return result

    def _collect_static(self, target: TargetConfig, result: CollectResult) -> list[dict]:
        rows: list[dict] = []
        url: str | None = target.start_url
        visited: set[str] = set()
        while url:
            if url in visited:
                log.warning("同じページに戻ったため、ページ送りを止めます: %s", url)
                break
            if result.pages_fetched >= self.cfg.request.max_pages:
                log.warning("取得ページ数の上限 (%d) に達したため止めます", self.cfg.request.max_pages)
                result.error_count += 1
                result.message = "取得ページ数の上限に達した"
                break
            if urlparse(url).netloc != target.host:
                log.warning("別のホストへのリンクはたどりません: %s", url)
                break
            if not self._check_robots(url):
                result.error_count += 1
                break
            visited.add(url)
            try:
                html = self._get_html(url)
            except FetchError as e:
                log.error("一覧ページを取得できません: %s", e)
                result.error_count += 1
                break
            result.pages_fetched += 1
            page_rows = parse_items(html, url, target.item_selector, target.fields, self.cfg.stock_words)
            log.info("一覧 %s から %d 件", url, len(page_rows))
            rows.extend(page_rows)
            url = find_next_url(html, url, target.next_page)
        return rows

    def _collect_js(self, target: TargetConfig, result: CollectResult) -> list[dict]:
        interval = self.robots.interval_for(target.start_url, self.cfg.request.interval_sec)
        self.fetcher.limiter.wait(target.host, interval)
        try:
            html = self.renderer(target.start_url, self.cfg.user_agent, target.wait_for,
                                 self.cfg.request.timeout_sec)
        except js_fetcher.JsUnavailable as e:
            log.warning("JavaScript ページを見送ります: %s", e)
            result.status, result.message = "skipped", str(e)
            return []
        except Exception as e:  # ブラウザ側の誤りは種類が多いため、まとめて記録して続行する
            log.error("JavaScript ページを取得できません: %s (%s)", target.start_url, e)
            result.error_count += 1
            return []
        result.pages_fetched += 1
        rows = parse_items(html, target.start_url, target.item_selector, target.fields, self.cfg.stock_words)
        log.info("JavaScript ページ %s から %d 件", target.start_url, len(rows))
        return rows

    def _to_items(self, rows: list[dict], target: TargetConfig, result: CollectResult) -> list[ProductItem]:
        items: dict[str, ProductItem] = {}
        for row in rows:
            pid = row.get("product_id")
            if not pid:
                log.warning("商品ID が取れない行を飛ばします: %s", row)
                continue
            if pid in items:
                continue  # 同じ商品が複数ページに出た場合は最初のものを使う
            items[pid] = ProductItem(product_id=pid, **{k: row.get(k) for k in ITEM_FIELDS})
        return list(items.values())

    def _fill_details(self, target: TargetConfig, result: CollectResult) -> None:
        for item in result.items:
            if not item.url:
                continue
            if urlparse(item.url).netloc != target.host or not self._check_robots(item.url):
                continue
            try:
                html = self._get_html(item.url)
            except FetchError as e:
                log.error("詳細ページを取得できません: %s", e)
                result.error_count += 1
                continue
            result.pages_fetched += 1
            detail = parse_detail(html, item.url, target.detail_fields, self.cfg.stock_words)
            for key, value in detail.items():
                if key in ITEM_FIELDS and value is not None:
                    setattr(item, key, value)

    @staticmethod
    def _decide_status(result: CollectResult) -> None:
        if result.error_count == 0:
            result.status = "success"
        elif result.items:
            result.status = "partial"
        else:
            result.status = "failed"

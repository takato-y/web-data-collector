"""JavaScript で描画されるページの取得（FN-006）。Playwright が入っている場合だけ使える。"""
from __future__ import annotations

import importlib.util
import logging
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# 収集に不要な読み込みは止め、対象サイトへの負荷を減らす
BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}


def is_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


class JsUnavailable(RuntimeError):
    """Playwright またはブラウザ本体が無い。"""


def render(url: str, user_agent: str, wait_for: str | None, timeout_sec: float) -> str:
    """ページを開き、wait_for の要素が現れるまで待ってから HTML を返す。"""
    if not is_available():
        raise JsUnavailable("Playwright が導入されていません（requirements-js.txt を参照）")
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    host = urlparse(url).netloc
    timeout_ms = int(timeout_sec * 1000)

    def route_filter(route):
        req = route.request
        # 同じホスト以外への通信と、画像などの不要な読み込みは行わない
        if urlparse(req.url).netloc != host or req.resource_type in BLOCKED_RESOURCE_TYPES:
            return route.abort()
        return route.continue_()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=user_agent)
                page.route("**/*", route_filter)
                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                if wait_for:
                    page.wait_for_selector(wait_for, timeout=timeout_ms)
                return page.content()
            finally:
                browser.close()
    except PlaywrightError as e:
        if "Executable doesn't exist" in str(e):
            raise JsUnavailable("ブラウザ本体がありません（playwright install chromium-headless-shell を実行）") from None
        raise

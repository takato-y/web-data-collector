"""ページ取得: 名乗り・タイムアウト・間隔を広げる再試行（FN-004）。"""
from __future__ import annotations

import logging
import time
from typing import Callable
from urllib.parse import urlparse

import requests

from webcollector.config import RequestConfig
from webcollector.politeness import RateLimiter

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    """取得に失敗した（再試行しても回復しなかった、または再試行しない誤り）。"""

    def __init__(self, url: str, reason: str, status: int | None = None):
        super().__init__(f"{reason}: {url}")
        self.url = url
        self.reason = reason
        self.status = status


def _retry_after_seconds(value: str | None) -> float | None:
    """Retry-After（秒数の形式のみ対応）を読む。読めなければ None。"""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


class Fetcher:
    def __init__(self, req: RequestConfig, user_agent: str, limiter: RateLimiter | None = None,
                 session: requests.Session | None = None, sleep: Callable[[float], None] = time.sleep):
        self.req = req
        self.user_agent = user_agent
        self.limiter = limiter or RateLimiter()
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Language": "ja,en;q=0.5"})
        self._sleep = sleep
        self.request_count = 0  # 実際に送った要求の数（再試行を含む）

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        wait = retry_after if retry_after is not None else self.req.backoff_base_sec * (2 ** attempt)
        return min(wait, self.req.max_retry_after_sec)

    def get(self, url: str, interval: float | None = None) -> requests.Response:
        """URL を取得する。混雑・一時的な誤り・通信エラーは再試行し、それ以外の 4xx は即座に失敗とする。"""
        host = urlparse(url).netloc
        interval = self.req.interval_sec if interval is None else interval
        last_reason, last_status = "", None
        for attempt in range(self.req.max_retries + 1):
            self.limiter.wait(host, interval)
            self.request_count += 1
            retry_after = None
            try:
                resp = self.session.get(url, timeout=self.req.timeout_sec)
            except requests.ConnectTimeout:
                last_reason, last_status = "接続できません（タイムアウト）", None
            except requests.Timeout:
                last_reason, last_status = "タイムアウト", None
            except requests.ConnectionError:
                last_reason, last_status = "接続できません", None
            else:
                if resp.status_code in RETRYABLE_STATUS:
                    last_reason, last_status = f"一時的な誤り (HTTP {resp.status_code})", resp.status_code
                    retry_after = _retry_after_seconds(resp.headers.get("Retry-After"))
                elif resp.status_code >= 400:
                    raise FetchError(url, f"HTTP {resp.status_code}", resp.status_code)
                else:
                    if urlparse(resp.url).netloc != host:
                        raise FetchError(url, f"別のホストへ転送されました ({urlparse(resp.url).netloc})")
                    if resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
                        resp.encoding = resp.apparent_encoding
                    return resp
            if attempt >= self.req.max_retries:
                break
            wait = self._backoff(attempt, retry_after)
            log.warning("%s。%.1f 秒後に再試行します (%d/%d): %s",
                        last_reason, wait, attempt + 1, self.req.max_retries, url)
            self._sleep(wait)
        raise FetchError(url, f"再試行しても取得できません（{last_reason}）", last_status)

    def fetch_robots(self, robots_url: str) -> tuple[int | None, str]:
        """robots.txt を取得する。4xx は (status, '')、取得できなければ (None or 5xx, '')。"""
        try:
            resp = self.get(robots_url)
        except FetchError as e:
            return e.status, ""
        return resp.status_code, resp.text

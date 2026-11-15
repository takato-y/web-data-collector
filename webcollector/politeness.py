"""対象サイトへの配慮: robots.txt の確認（FN-002）とアクセス間隔の制御（FN-003）。

判断に迷う場合は「取得しない」側に倒す（ADR-0003）。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

log = logging.getLogger(__name__)


class RateLimiter:
    """同じホストへの要求の間隔を保つ。時計と sleep は差し替え可能（テスト用）。"""

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, interval: float) -> float:
        """必要な分だけ待ってから戻る。待った秒数を返す。"""
        with self._lock:
            now = self._clock()
            last = self._last.get(host)
            waited = 0.0
            if last is not None:
                remaining = interval - (now - last)
                if remaining > 0:
                    self._sleep(remaining)
                    waited = remaining
            self._last[host] = self._clock()
            return waited


@dataclass
class RobotsRule:
    """1 ホストぶんの robots.txt の判定結果。

    state: ok=取得できた / missing=存在しない（制限なし） / unavailable=一時的に取得できない（全て取得しない）
    """

    state: str
    parser: RobotFileParser | None = None
    detail: str = ""

    def allowed(self, user_agent: str, url: str) -> bool:
        if self.state == "missing":
            return True
        if self.state == "unavailable" or self.parser is None:
            return False
        return self.parser.can_fetch(user_agent, url)

    def crawl_delay(self, user_agent: str) -> float | None:
        if self.parser is None:
            return None
        delay = self.parser.crawl_delay(user_agent)
        return float(delay) if delay is not None else None


# robots.txt を取得する関数の型: URL を受け取り (ステータスコード or None, 本文) を返す。
# 通信エラーで応答が無いときはステータスに None を返す。
RobotsFetcher = Callable[[str], "tuple[int | None, str]"]


class RobotsPolicy:
    """ホストごとに robots.txt を 1 回だけ取得し、取得可否と待ち時間を答える。"""

    def __init__(self, fetch: RobotsFetcher, user_agent: str):
        self._fetch = fetch
        self._ua = user_agent
        self._agent_token = user_agent.split("/")[0]  # robots.txt の User-agent 行と照合する名前
        self._cache: dict[str, RobotsRule] = {}

    def rule_for(self, url: str) -> RobotsRule:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._cache:
            self._cache[origin] = self._load(origin + "/robots.txt")
        return self._cache[origin]

    def _load(self, robots_url: str) -> RobotsRule:
        status, body = self._fetch(robots_url)
        if status is None or status >= 500:
            log.warning("robots.txt を取得できないため、このサイトの収集を見送ります: %s (status=%s)", robots_url, status)
            return RobotsRule("unavailable", detail=f"status={status}")
        if 400 <= status < 500:
            log.info("robots.txt がありません（制限なしとして扱います）: %s (status=%s)", robots_url, status)
            return RobotsRule("missing", detail=f"status={status}")
        parser = RobotFileParser()
        parser.parse(body.splitlines())
        log.info("robots.txt を確認しました: %s", robots_url)
        return RobotsRule("ok", parser=parser)

    def allowed(self, url: str) -> bool:
        return self.rule_for(url).allowed(self._agent_token, url)

    def is_unavailable(self, url: str) -> bool:
        return self.rule_for(url).state == "unavailable"

    def interval_for(self, url: str, configured: float) -> float:
        """設定の間隔と Crawl-delay の長い方を返す。"""
        delay = self.rule_for(url).crawl_delay(self._agent_token)
        return max(configured, delay or 0.0)

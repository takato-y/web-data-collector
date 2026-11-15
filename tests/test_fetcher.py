"""FN-004 ページ取得（名乗り・再試行・タイムアウト）のテスト。"""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from webcollector.config import RequestConfig
from webcollector.fetcher import Fetcher, FetchError
from tests.conftest import NoWaitLimiter, closed_port_url

UA = "WebDataCollector/1.0 (+https://example.com/bot-info)"


class Recorder:
    def __init__(self):
        self.sleeps = []

    def __call__(self, sec):
        self.sleeps.append(sec)


def serve(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def make_fetcher(**req):
    sleeper = Recorder()
    cfg = RequestConfig(**{"interval_sec": 0.5, "timeout_sec": 2, "max_retries": 3, "backoff_base_sec": 1.0, **req})
    return Fetcher(cfg, UA, NoWaitLimiter(), sleep=sleeper), sleeper


def test_sends_user_agent():
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["ua"] = self.headers.get("User-Agent")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("こんにちは".encode())

        def log_message(self, *a):
            pass

    server, base = serve(H)
    try:
        f, _ = make_fetcher()
        assert f.get(base + "/").text == "こんにちは"
        assert seen["ua"] == UA
    finally:
        server.shutdown()


def test_retry_after_is_respected_then_succeeds(make_site):
    site = make_site(fail_first=2)  # 最初の 2 回は 503 + Retry-After: 1
    f, sleeper = make_fetcher()
    assert f.get(site.base + "/products").status_code == 200
    assert f.request_count == 3
    assert sleeper.sleeps == [1.0, 1.0]


def test_gives_up_after_max_retries(make_site):
    site = make_site(fail_first=100)
    f, sleeper = make_fetcher(max_retries=2)
    with pytest.raises(FetchError) as e:
        f.get(site.base + "/products")
    assert e.value.status == 503
    assert f.request_count == 3 and len(sleeper.sleeps) == 2


def test_exponential_backoff_without_retry_after():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(500)
            self.end_headers()

        def log_message(self, *a):
            pass

    server, base = serve(H)
    try:
        f, sleeper = make_fetcher(max_retries=3, backoff_base_sec=0.01)
        with pytest.raises(FetchError):
            f.get(base + "/")
        assert sleeper.sleeps == [0.01, 0.02, 0.04]
    finally:
        server.shutdown()


def test_404_is_not_retried(make_site):
    site = make_site()
    f, sleeper = make_fetcher()
    with pytest.raises(FetchError) as e:
        f.get(site.base + "/products/NOPE")
    assert e.value.status == 404
    assert f.request_count == 1 and sleeper.sleeps == []


def test_timeout_is_retried_then_fails():
    class Slow(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(1.5)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    server, base = serve(Slow)
    try:
        f, sleeper = make_fetcher(timeout_sec=1, max_retries=1, backoff_base_sec=0)
        started = time.monotonic()
        with pytest.raises(FetchError, match="タイムアウト"):
            f.get(base + "/")
        assert f.request_count == 2
        assert time.monotonic() - started < 5  # 打ち切られている
    finally:
        server.shutdown()


def test_connection_refused_is_reported():
    f, _ = make_fetcher(max_retries=1, backoff_base_sec=0)
    with pytest.raises(FetchError, match="接続できません"):
        f.get(closed_port_url() + "/")


def test_retry_after_is_capped():
    f, _ = make_fetcher(max_retry_after_sec=60)
    assert f._backoff(0, 3600) == 60

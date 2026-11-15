"""FN-010 Webhook 通知のテスト（送信先は手元の受信用モックのみ）。"""
import json
from datetime import datetime

import pytest

from webcollector.config import NotifyConfig
from webcollector.models import CollectResult, ProductItem
from webcollector.notify import (WebhookUrlError, build_payload, mask_url, notify_pending,
                                 validate_webhook_url)
from webcollector.storage import Storage
from tools import mock_webhook

NOW = datetime(2026, 11, 15, 9, 0)


@pytest.fixture
def storage(tmp_path):
    st = Storage(tmp_path / "h.db")
    r1 = st.start_run("demo_shop")
    st.record_result(r1, CollectResult(target="demo_shop", items=[
        ProductItem("A-1", "方眼ノート", 480), ProductItem("A-2", "ボールペン", 980)]))
    r2 = st.start_run("demo_shop")
    st.record_result(r2, CollectResult(target="demo_shop", items=[
        ProductItem("A-1", "方眼ノート", 398), ProductItem("A-2", "ボールペン", 980),
        ProductItem("A-3", "<!channel> @everyone 付箋", 300)]))
    return st


@pytest.fixture
def mock(tmp_path):
    servers = []

    def _start(fail_first=0):
        s = mock_webhook.start(tmp_path / "recv", fail_first=fail_first)
        servers.append(s)
        return s, f"http://127.0.0.1:{s.server_port}/hook"

    yield _start
    for s in servers:
        s.shutdown()


def test_slack_payload_escapes_and_lists(storage):
    payload = build_payload(storage.unnotified_events(), "slack", 20, NOW)
    text = payload["text"]
    assert text.splitlines()[0] == "[価格・在庫の変化] demo_shop 2026-11-15 09:00"
    assert "値下げ 1件 / 新商品 1件" in text
    assert "・値下げ A-1 方眼ノート: 480円 → 398円 (-82円)" in text
    assert "<!channel>" not in text and "&lt;!channel&gt;" in text
    assert "@everyone" not in text


def test_discord_disables_mentions(storage):
    payload = build_payload(storage.unnotified_events(), "discord", 20, NOW)
    assert payload["allowed_mentions"] == {"parse": []}
    assert "content" in payload and "@everyone" not in payload["content"]


def test_generic_has_structured_events_and_truncation(storage):
    payload = build_payload(storage.unnotified_events(), "generic", 1, NOW)
    assert len(payload["events"]) == 2
    assert "ほか 1 件は Excel レポートを参照" in payload["text"]


@pytest.mark.parametrize("url", ["http://example.com/hook", "ftp://127.0.0.1/", "", None, "https://"])
def test_rejects_unsafe_urls(url):
    with pytest.raises(WebhookUrlError):
        validate_webhook_url(url)


def test_accepts_https_and_local_http():
    assert validate_webhook_url("https://hooks.example.com/abc")
    assert validate_webhook_url("http://127.0.0.1:8765/hook")
    assert mask_url("https://hooks.example.com/services/SECRET") == "https://hooks.example.com/***"


def test_send_to_mock_marks_notified(storage, mock, tmp_path):
    _, url = mock()
    out = notify_pending(storage, NotifyConfig(), env={"WEBHOOK_URL": url}, now=NOW)
    assert out.status == "sent" and len(out.sent_ids) == 2
    received = json.loads((tmp_path / "recv" / "received_001.json").read_text(encoding="utf-8"))
    assert received["text"] == out.payload["text"]
    assert storage.unnotified_events() == []
    again = notify_pending(storage, NotifyConfig(), env={"WEBHOOK_URL": url}, now=NOW)
    assert again.status == "nothing"


def test_failure_keeps_events_for_next_time(storage, mock):
    _, url = mock(fail_first=1)
    first = notify_pending(storage, NotifyConfig(), env={"WEBHOOK_URL": url}, now=NOW)
    assert first.status == "failed" and first.message == "HTTP 500"
    assert len(storage.unnotified_events()) == 2
    second = notify_pending(storage, NotifyConfig(), env={"WEBHOOK_URL": url}, now=NOW)
    assert second.status == "sent"


def test_missing_env_and_dry_run(storage):
    assert notify_pending(storage, NotifyConfig(), env={}).status == "skipped"
    dry = notify_pending(storage, NotifyConfig(), env={}, dry_run=True)
    assert dry.status == "dry_run" and dry.payload["text"]
    assert len(storage.unnotified_events()) == 2
    assert notify_pending(storage, NotifyConfig(enabled=False), env={}).status == "skipped"

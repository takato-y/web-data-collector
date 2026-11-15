"""Webhook 通知（FN-010）。未通知の変更を通知形式に整えて送り、成功したものだけ通知済みにする。"""
from __future__ import annotations

import ipaddress
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

import requests

from webcollector.config import NotifyConfig
from webcollector.diff import EVENT_LABELS, EVENT_ORDER
from webcollector.safe_text import escape_slack, neutralize_mentions
from webcollector.storage import Storage

log = logging.getLogger(__name__)

USER_AGENT = "WebDataCollector-Notifier/1.0"


class WebhookUrlError(ValueError):
    """Webhook の URL が使えない（未設定・平文の外部通信など）。"""


def validate_webhook_url(url: str | None) -> str:
    """https のみ受け付ける。http は手元（127.0.0.1・localhost）の受け口に限る。"""
    if not url:
        raise WebhookUrlError("Webhook の URL が環境変数に設定されていません")
    p = urlparse(url)
    if p.scheme == "https" and p.hostname:
        return url
    if p.scheme == "http" and p.hostname:
        try:
            local = p.hostname == "localhost" or ipaddress.ip_address(p.hostname).is_loopback
        except ValueError:
            local = False
        if local:
            return url
    raise WebhookUrlError("Webhook の URL は https で指定してください（http は 127.0.0.1 の受け口のみ）")


def mask_url(url: str) -> str:
    """ログに URL の秘密部分（利用者名・パスワード・パス・クエリ）を残さない。ホスト名とポートだけを残す。"""
    p = urlparse(url)
    host = p.hostname or ""
    if ":" in host:  # IPv6 の表記
        host = f"[{host}]"
    port = f":{p.port}" if p.port else ""
    return f"{p.scheme}://{host}{port}/***"


def _line(e) -> str:
    label = EVENT_LABELS[e["event_type"]]
    name = e["name"] or ""
    if e["event_type"] in ("price_down", "price_up"):
        sign = "+" if (e["price_diff"] or 0) > 0 else ""
        detail = f"{e['old_value']} → {e['new_value']} ({sign}{e['price_diff']:,}円)"
    elif e["event_type"] in ("out_of_stock", "restock"):
        detail = f"{e['old_value']} → {e['new_value']}"
    elif e["event_type"] == "new":
        detail = e["new_value"] or "価格不明"
    else:
        detail = f"最終価格 {e['old_value'] or '不明'}"
    return f"・{label} {e['product_id']} {name}: {detail}"


def build_text(events: list, max_items: int, now: datetime) -> str:
    counts: dict[str, int] = {}
    for e in events:
        counts[e["event_type"]] = counts.get(e["event_type"], 0) + 1
    targets = sorted({e["target_name"] for e in events})
    head = f"[価格・在庫の変化] {', '.join(targets)} {now:%Y-%m-%d %H:%M}"
    summary = " / ".join(f"{EVENT_LABELS[k]} {counts[k]}件" for k in EVENT_ORDER if k in counts)
    ordered = sorted(events, key=lambda e: (EVENT_ORDER.index(e["event_type"]), e["product_id"]))
    lines = [_line(e) for e in ordered[:max_items]]
    if len(ordered) > max_items:
        lines.append(f"（ほか {len(ordered) - max_items} 件は Excel レポートを参照）")
    return "\n".join([head, summary, *lines])


def build_payload(events: list, fmt: str, max_items: int, now: datetime) -> dict:
    text = build_text(events, max_items, now)
    if fmt == "slack":
        return {"text": neutralize_mentions(escape_slack(text))}
    if fmt == "discord":
        # 本文中の @ を呼び出しとして扱わせない
        return {"content": neutralize_mentions(text), "allowed_mentions": {"parse": []}}
    if fmt == "teams":
        return {"text": neutralize_mentions(text)}
    return {
        "text": text,
        "events": [{k: e[k] for k in ("target_name", "product_id", "name", "event_type", "old_value",
                                       "new_value", "price_diff", "url", "detected_at")} for e in events],
    }


@dataclass
class NotifyOutcome:
    status: str  # sent / nothing / skipped / failed / dry_run
    sent_ids: list[int] = field(default_factory=list)
    payload: dict | None = None
    message: str = ""


def notify_pending(storage: Storage, cfg: NotifyConfig, env: dict | None = None, dry_run: bool = False,
                   now: datetime | None = None, session: requests.Session | None = None) -> NotifyOutcome:
    env = os.environ if env is None else env
    now = now or datetime.now()
    if not cfg.enabled:
        return NotifyOutcome("skipped", message="通知は無効（notify.enabled: false）")
    events = storage.unnotified_events()
    if not events:
        return NotifyOutcome("nothing", message="未通知の変更はありません")
    payload = build_payload(events, cfg.format, cfg.max_items, now)
    if dry_run:
        return NotifyOutcome("dry_run", payload=payload, message=f"{len(events)} 件（送信せず表示のみ）")
    try:
        url = validate_webhook_url(env.get(cfg.webhook_url_env))
    except WebhookUrlError as e:
        log.warning("通知を送りません: %s", e)
        return NotifyOutcome("skipped", payload=payload, message=str(e))
    http = session or requests.Session()
    try:
        resp = http.post(url, json=payload, timeout=cfg.timeout_sec, headers={"User-Agent": USER_AGENT})
    except requests.RequestException as e:
        log.error("通知を送れません（次回に再送します）: %s %s", mask_url(url), type(e).__name__)
        return NotifyOutcome("failed", payload=payload, message=type(e).__name__)
    if not 200 <= resp.status_code < 300:
        log.error("通知が受け付けられません（次回に再送します）: %s HTTP %s", mask_url(url), resp.status_code)
        return NotifyOutcome("failed", payload=payload, message=f"HTTP {resp.status_code}")
    ids = [e["event_id"] for e in events]
    storage.mark_notified(ids)
    log.info("通知しました: %d 件 → %s", len(ids), mask_url(url))
    return NotifyOutcome("sent", sent_ids=ids, payload=payload, message=f"{len(ids)} 件を送信")

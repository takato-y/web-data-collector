"""設定ファイル（YAML）の読込と検査（FN-001）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import yaml

DEFAULT_USER_AGENT = "WebDataCollector/1.0 (+https://example.com/bot-info)"
MIN_INTERVAL_SEC = 0.5  # 設定で短くしすぎないための下限
FIELD_TYPES = ("text", "price", "stock", "url")
NOTIFY_FORMATS = ("slack", "discord", "teams", "generic")


class ConfigError(ValueError):
    """設定の誤り。"""


@dataclass
class FieldSpec:
    """1 項目の取り出し方。selector が空なら要素自身から取り出す。"""

    selector: str | None = None
    attr: str | None = None
    type: str = "text"


@dataclass
class RequestConfig:
    interval_sec: float = 1.0
    timeout_sec: float = 10.0
    max_retries: int = 3
    backoff_base_sec: float = 1.0
    max_retry_after_sec: float = 60.0
    max_pages: int = 50


@dataclass
class TargetConfig:
    name: str
    start_url: str
    item_selector: str
    fields: dict[str, FieldSpec]
    type: str = "static"
    next_page: str | None = None
    detail_fields: dict[str, FieldSpec] = field(default_factory=dict)
    wait_for: str | None = None

    @property
    def host(self) -> str:
        return urlparse(self.start_url).netloc


@dataclass
class NotifyConfig:
    enabled: bool = True
    format: str = "slack"
    webhook_url_env: str = "WEBHOOK_URL"
    max_items: int = 20
    timeout_sec: float = 10.0


@dataclass
class AppConfig:
    targets: list[TargetConfig]
    user_agent: str = DEFAULT_USER_AGENT
    request: RequestConfig = field(default_factory=RequestConfig)
    db_path: Path = Path("data/history.db")
    report_dir: Path = Path("output")
    log_dir: Path = Path("logs")
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    stock_words: dict[str, list[str]] = field(default_factory=lambda: {
        "out_of_stock": ["在庫切れ", "売り切れ", "品切れ", "入荷待ち"],
        "low_stock": ["残りわずか", "残り僅か", "在庫僅少"],
        "in_stock": ["在庫あり", "在庫有り", "在庫有"],
    })


def _field_specs(raw: dict | None, where: str) -> dict[str, FieldSpec]:
    specs: dict[str, FieldSpec] = {}
    for name, value in (raw or {}).items():
        if isinstance(value, str):
            value = {"selector": value}
        if not isinstance(value, dict):
            raise ConfigError(f"{where}.{name} の書き方が正しくありません")
        spec = FieldSpec(value.get("selector") or None, value.get("attr"), value.get("type", "text"))
        if spec.type not in FIELD_TYPES:
            raise ConfigError(f"{where}.{name}.type は {FIELD_TYPES} のいずれかです: {spec.type}")
        specs[name] = spec
    return specs


def _positive(value, name: str, minimum: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{name} は数値で指定してください: {value!r}") from None
    if number < minimum:
        raise ConfigError(f"{name} は {minimum} 以上にしてください: {number}")
    return number


def parse_config(data: dict, base_dir: Path) -> AppConfig:
    """辞書から設定を作る。パスは設定ファイルのあるフォルダからの相対で解決する。"""
    if not isinstance(data, dict):
        raise ConfigError("設定ファイルの中身が空か、形式が正しくありません")

    req_raw = data.get("request") or {}
    req = RequestConfig(
        interval_sec=_positive(req_raw.get("interval_sec", 1.0), "request.interval_sec", MIN_INTERVAL_SEC),
        timeout_sec=_positive(req_raw.get("timeout_sec", 10.0), "request.timeout_sec", 1.0),
        max_retries=int(_positive(req_raw.get("max_retries", 3), "request.max_retries")),
        backoff_base_sec=_positive(req_raw.get("backoff_base_sec", 1.0), "request.backoff_base_sec"),
        max_retry_after_sec=_positive(req_raw.get("max_retry_after_sec", 60.0), "request.max_retry_after_sec"),
        max_pages=int(_positive(req_raw.get("max_pages", 50), "request.max_pages", 1)),
    )

    targets: list[TargetConfig] = []
    names: set[str] = set()
    for i, t in enumerate(data.get("targets") or []):
        where = f"targets[{i}]"
        for key in ("name", "start_url", "item_selector"):
            if not t.get(key):
                raise ConfigError(f"{where}.{key} は必須です")
        if t["name"] in names:
            raise ConfigError(f"対象名が重複しています: {t['name']}")
        names.add(t["name"])
        parsed = urlparse(t["start_url"])
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ConfigError(f"{where}.start_url は http(s) の URL で指定してください")
        fields = _field_specs(t.get("fields"), f"{where}.fields")
        if "product_id" not in fields:
            raise ConfigError(f"{where}.fields.product_id は必須です（前回と比べるための鍵）")
        ttype = t.get("type", "static")
        if ttype not in ("static", "js"):
            raise ConfigError(f"{where}.type は static か js です: {ttype}")
        targets.append(TargetConfig(
            name=t["name"], start_url=t["start_url"], item_selector=t["item_selector"],
            fields=fields, type=ttype, next_page=t.get("next_page"),
            detail_fields=_field_specs(t.get("detail_fields"), f"{where}.detail_fields"),
            wait_for=t.get("wait_for"),
        ))
    if not targets:
        raise ConfigError("targets に収集対象を 1 件以上指定してください")

    n_raw = data.get("notify") or {}
    notify = NotifyConfig(
        enabled=bool(n_raw.get("enabled", True)),
        format=n_raw.get("format", "slack"),
        webhook_url_env=n_raw.get("webhook_url_env", "WEBHOOK_URL"),
        max_items=int(_positive(n_raw.get("max_items", 20), "notify.max_items", 1)),
        timeout_sec=_positive(n_raw.get("timeout_sec", 10.0), "notify.timeout_sec", 1.0),
    )
    if notify.format not in NOTIFY_FORMATS:
        raise ConfigError(f"notify.format は {NOTIFY_FORMATS} のいずれかです: {notify.format}")
    if "webhook_url" in n_raw:
        # URL そのものを設定ファイルに書くと、共有やコミットで漏れるため受け付けない
        raise ConfigError("notify.webhook_url は使えません。URL は環境変数で渡してください（notify.webhook_url_env）")

    cfg = AppConfig(
        targets=targets,
        user_agent=data.get("user_agent") or DEFAULT_USER_AGENT,
        request=req,
        db_path=base_dir / data.get("storage", {}).get("db_path", "data/history.db"),
        report_dir=base_dir / data.get("report", {}).get("output_dir", "output"),
        log_dir=base_dir / data.get("log", {}).get("dir", "logs"),
        notify=notify,
    )
    if data.get("stock_words"):
        cfg.stock_words.update(data["stock_words"])
    return cfg


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"設定ファイルが見つかりません: {path.name}")
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"設定ファイルを読めません（YAML の書き方の誤り）: {e}") from None
    return parse_config(data, path.resolve().parent)

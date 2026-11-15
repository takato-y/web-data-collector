"""設定ファイル（YAML）の読込と検査（FN-001・分析部）。

収集部と同じ config.yaml を読み、分析部が使う storage・report・log・notify だけを検査する。
収集対象（targets）などの検査は収集部（collector/src/config.ts）が行う。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

NOTIFY_FORMATS = ("slack", "discord", "teams", "generic")


class ConfigError(ValueError):
    """設定の誤り。"""


@dataclass
class NotifyConfig:
    enabled: bool = True
    format: str = "slack"
    webhook_url_env: str = "WEBHOOK_URL"
    max_items: int = 20
    timeout_sec: float = 10.0


@dataclass
class AppConfig:
    db_path: Path = Path("data/history.db")
    report_dir: Path = Path("output")
    log_dir: Path = Path("logs")
    notify: NotifyConfig = field(default_factory=NotifyConfig)


def _number(value, name: str, minimum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{name} は数値で指定してください: {value!r}") from None
    if number < minimum:
        raise ConfigError(f"{name} は {minimum} 以上にしてください: {number}")
    return number


def _section(data: dict, key: str) -> dict:
    value = data.get(key) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"{key} の書き方が正しくありません")
    return value


def parse_config(data: dict, base_dir: Path) -> AppConfig:
    """辞書から設定を作る。パスは設定ファイルのあるフォルダからの相対で解決する。"""
    if not isinstance(data, dict):
        raise ConfigError("設定ファイルの中身が空か、形式が正しくありません")
    n_raw = _section(data, "notify")
    if "webhook_url" in n_raw:
        # URL そのものを設定ファイルに書くと、共有やコミットで漏れるため受け付けない
        raise ConfigError("notify.webhook_url は使えません。URL は環境変数で渡してください（notify.webhook_url_env）")
    notify = NotifyConfig(
        enabled=bool(n_raw.get("enabled", True)),
        format=n_raw.get("format", "slack"),
        webhook_url_env=str(n_raw.get("webhook_url_env", "WEBHOOK_URL")),
        max_items=int(_number(n_raw.get("max_items", 20), "notify.max_items", 1)),
        timeout_sec=_number(n_raw.get("timeout_sec", 10.0), "notify.timeout_sec", 1.0),
    )
    if notify.format not in NOTIFY_FORMATS:
        raise ConfigError(f"notify.format は {NOTIFY_FORMATS} のいずれかです: {notify.format}")
    return AppConfig(
        db_path=base_dir / _section(data, "storage").get("db_path", "data/history.db"),
        report_dir=base_dir / _section(data, "report").get("output_dir", "output"),
        log_dir=base_dir / _section(data, "log").get("dir", "logs"),
        notify=notify,
    )


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

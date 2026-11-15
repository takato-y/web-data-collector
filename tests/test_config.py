"""FN-001 設定読込（分析部）のテスト。"""
import pytest
import yaml

from webcollector.config import ConfigError, load_config, parse_config
from tests.conftest import ROOT


def base():
    return yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))


def test_example_config_loads():
    cfg = load_config(ROOT / "config.example.yaml")
    assert cfg.db_path.name == "history.db" and cfg.db_path.is_absolute()
    assert cfg.notify.format == "slack" and cfg.notify.webhook_url_env == "WEBHOOK_URL"


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["notify"].update(format="mail"), "notify.format"),
    (lambda d: d["notify"].update(webhook_url="https://example.com/hook"), "環境変数"),
    (lambda d: d["notify"].update(max_items=0), "max_items"),
    (lambda d: d.update(storage="data.db"), "storage"),
])
def test_invalid_config_is_rejected(tmp_path, mutate, message):
    data = base()
    mutate(data)
    with pytest.raises(ConfigError, match=message):
        parse_config(data, tmp_path)


def test_missing_file_and_broken_yaml(tmp_path):
    with pytest.raises(ConfigError, match="見つかりません"):
        load_config(tmp_path / "none.yaml")
    broken = tmp_path / "broken.yaml"
    broken.write_text("notify: [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML"):
        load_config(broken)

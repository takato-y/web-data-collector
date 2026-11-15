"""FN-001 設定読込のテスト。"""
import pytest
import yaml

from webcollector.config import ConfigError, load_config, parse_config
from tests.conftest import ROOT


def base():
    return yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))


def test_example_config_loads(tmp_path):
    cfg = load_config(ROOT / "config.example.yaml")
    assert [t.name for t in cfg.targets] == ["demo_shop", "demo_shop_new"]
    assert cfg.targets[1].type == "js"
    assert cfg.request.interval_sec == 1.0
    assert cfg.db_path.name == "history.db" and cfg.db_path.is_absolute()


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["request"].update(interval_sec=0.1), "interval_sec"),
    (lambda d: d["targets"][0]["fields"].pop("product_id"), "product_id"),
    (lambda d: d["targets"][0].update(start_url="ftp://example.com/"), "start_url"),
    (lambda d: d["targets"][1].update(name="demo_shop"), "重複"),
    (lambda d: d["notify"].update(format="mail"), "notify.format"),
    (lambda d: d["notify"].update(webhook_url="https://example.com/hook"), "環境変数"),
    (lambda d: d.update(targets=[]), "targets"),
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
    broken.write_text("targets: [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML"):
        load_config(broken)

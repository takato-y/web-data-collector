"""テスト共通の部品: デモショップを 127.0.0.1 の空いているポートで起動する。"""
from __future__ import annotations

import shutil
import threading
from pathlib import Path

import pytest
import yaml
from werkzeug.serving import make_server

from demo_site.app import create_app
from webcollector.config import parse_config

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "demo_site" / "data"


class LiveSite:
    def __init__(self, data_file: Path, fail_first: int = 0):
        self.data_file = data_file
        self.app = create_app(data_file, fail_first)
        self.server = make_server("127.0.0.1", 0, self.app, threaded=True)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def use(self, name: str) -> None:
        """商品データを day1.json / day2.json に差し替える。"""
        shutil.copy(DATA / name, self.data_file)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()


@pytest.fixture
def site(tmp_path):
    data_file = tmp_path / "current.json"
    shutil.copy(DATA / "day1.json", data_file)
    with LiveSite(data_file) as s:
        yield s


@pytest.fixture
def make_site(tmp_path):
    started = []

    def _make(fail_first: int = 0, data: str = "day1.json") -> LiveSite:
        data_file = tmp_path / f"site{len(started)}.json"
        shutil.copy(DATA / data, data_file)
        s = LiveSite(data_file, fail_first).__enter__()
        started.append(s)
        return s

    yield _make
    for s in started:
        s.__exit__()


def make_config(base_url: str, tmp_path: Path, **overrides):
    """config.example.yaml の URL をテスト用のポートに置き換えて読み込む。"""
    data = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    for t in data["targets"]:
        t["start_url"] = t["start_url"].replace("http://127.0.0.1:8000", base_url)
    data["request"]["interval_sec"] = 0.5
    data["request"]["backoff_base_sec"] = 0.0
    for key, value in overrides.items():
        data[key] = value
    return parse_config(data, tmp_path)


def closed_port_url() -> str:
    """待ち受けの無いポートの URL（一度確保してすぐ閉じたポート）。"""
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


class NoWaitLimiter:
    """間隔制御の待ちを記録だけして実際には待たない（テストを速くするため）。"""

    def __init__(self):
        self.calls: list[tuple[str, float]] = []

    def wait(self, host: str, interval: float) -> float:
        self.calls.append((host, interval))
        return 0.0

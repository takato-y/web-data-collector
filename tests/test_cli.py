"""FN-011 分析部のコマンドのテスト。"""
import json

import yaml

from webcollector.cli import main
from webcollector.storage import Storage
from tests.conftest import ROOT
from tests.db_seed import demo_items, seed_run
from tools import mock_webhook


def write_config(tmp_path, **notify):
    data = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    data["notify"].update(notify)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def seed(tmp_path):
    st = Storage(tmp_path / "data" / "history.db")
    seed_run(st.conn, "demo_shop", demo_items("day1.json"))
    seed_run(st.conn, "demo_shop", demo_items("day2.json"))
    st.close()


def test_run_analyzes_reports_and_notifies(tmp_path, capsys, monkeypatch):
    seed(tmp_path)
    server = mock_webhook.start(tmp_path / "recv")
    try:
        monkeypatch.setenv("WEBHOOK_URL", f"http://127.0.0.1:{server.server_port}/hook")
        code = main(["run", "-c", str(write_config(tmp_path))])
    finally:
        server.shutdown()
    out = capsys.readouterr().out
    assert code == 0
    assert "[分析] 実行 2 (demo_shop, success): 値下げ 2件" in out
    assert "[通知] sent: 8 件を送信" in out
    assert len(list((tmp_path / "output").glob("report_*.xlsx"))) == 1
    assert json.loads((tmp_path / "recv" / "received_001.json").read_text(encoding="utf-8"))["text"]
    assert (tmp_path / "logs" / "analysis.log").read_text(encoding="utf-8").count("通知しました") == 1


def test_notify_failure_returns_1(tmp_path, monkeypatch, capsys):
    seed(tmp_path)
    server = mock_webhook.start(tmp_path / "recv", fail_first=5)
    try:
        monkeypatch.setenv("WEBHOOK_URL", f"http://127.0.0.1:{server.server_port}/hook")
        assert main(["run", "-c", str(write_config(tmp_path))]) == 1
    finally:
        server.shutdown()
    assert "/hook" not in (tmp_path / "logs" / "analysis.log").read_text(encoding="utf-8")  # URL のパスをログに残さない


def test_config_error_returns_2(tmp_path, capsys):
    assert main(["analyze", "-c", str(tmp_path / "none.yaml")]) == 2
    assert main(["analyze", "-c", str(write_config(tmp_path, format="mail"))]) == 2


def test_dry_run_prints_payload(tmp_path, capsys, monkeypatch):
    seed(tmp_path)
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    cfg = str(write_config(tmp_path))
    main(["analyze", "-c", cfg])
    assert main(["notify", "-c", cfg, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "[通知] dry_run: 8 件" in out and '"text"' in out


def test_db_open_error_is_logged_and_returns_1(tmp_path, capsys):
    """履歴DB を開けないときも「想定外の誤り」として analysis.log に残し、終了コード 1 を返す（TC-011-06）。"""
    data = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    (tmp_path / "blocker").write_text("フォルダではなくファイル", encoding="utf-8")
    data["storage"] = {"db_path": "blocker/history.db"}  # 親がファイルのため作れない
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert main(["analyze", "-c", str(path)]) == 1
    assert "想定外の誤りで止まりました" in (tmp_path / "logs" / "analysis.log").read_text(encoding="utf-8")

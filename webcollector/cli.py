"""分析部のコマンド（FN-011）。

  python -m webcollector analyze -c config.yaml   未分析の実行の差分を検出
  python -m webcollector report  -c config.yaml   Excel レポートを出力
  python -m webcollector notify  -c config.yaml [--dry-run]
  python -m webcollector run     -c config.yaml   analyze → report → notify

終了コード: 0=成功 / 1=通知の送信失敗など一部失敗 / 2=設定エラー
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from logging.handlers import RotatingFileHandler

from webcollector.config import ConfigError, load_config
from webcollector.diff import EVENT_LABELS
from webcollector.notify import notify_pending
from webcollector.report import build_report
from webcollector.storage import Storage

log = logging.getLogger("webcollector")


def setup_logging(log_dir, verbose: bool) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [analysis] %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler = RotatingFileHandler(log_dir / "analysis.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    console.setLevel(logging.INFO if verbose else logging.WARNING)
    root = logging.getLogger()
    root.handlers[:] = [file_handler, console]
    root.setLevel(logging.INFO)


def cmd_analyze(st: Storage) -> int:
    done = st.analyze_pending()
    if not done:
        print("[分析] 未分析の実行はありません")
    for d in done:
        counts: dict[str, int] = {}
        for e in d.events:
            counts[e.event_type] = counts.get(e.event_type, 0) + 1
        summary = " / ".join(f"{EVENT_LABELS[k]} {v}件" for k, v in counts.items()) or "変更なし"
        print(f"[分析] 実行 {d.run_id} ({d.target}, {d.status}): {summary}")
    return 0


def cmd_report(st: Storage, cfg) -> int:
    path = build_report(st, cfg.report_dir)
    print(f"[帳票] {path.name} を出力しました")
    return 0


def cmd_notify(st: Storage, cfg, dry_run: bool) -> int:
    out = notify_pending(st, cfg.notify, dry_run=dry_run)
    print(f"[通知] {out.status}: {out.message}")
    if dry_run and out.payload:
        print(json.dumps(out.payload, ensure_ascii=False, indent=2))
    return 1 if out.status == "failed" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="webcollector", description="価格・在庫の差分検出・帳票・通知（分析部）")
    parser.add_argument("command", choices=["analyze", "report", "notify", "run"])
    parser.add_argument("-c", "--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="通知を送らず内容だけ表示する")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"設定エラー: {e}", file=sys.stderr)
        return 2
    setup_logging(cfg.log_dir, args.verbose)
    st = Storage(cfg.db_path)
    try:
        if args.command == "analyze":
            return cmd_analyze(st)
        if args.command == "report":
            return cmd_report(st, cfg)
        if args.command == "notify":
            return cmd_notify(st, cfg, args.dry_run)
        codes = [cmd_analyze(st), cmd_report(st, cfg), cmd_notify(st, cfg, args.dry_run)]
        return max(codes)
    except Exception:
        log.exception("想定外の誤りで止まりました")
        return 1
    finally:
        st.close()

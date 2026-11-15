#!/usr/bin/env bash
# 両言語をまたぐ通し試験（TC-E2E-01）。すべて 127.0.0.1 の中で完結し、外部には通信しない。
#   1. 架空のデモショップ（1 日目のデータ）と受信用モックを起動
#   2. scripts/run.sh で 収集（TypeScript）→ 分析・帳票・通知（Python）  … 初回は基準の記録のみ
#   3. デモショップのデータを 2 日目に差し替え
#   4. もう一度 scripts/run.sh                                           … 変更を検出して帳票と通知
#   5. 履歴DB・帳票・受信した通知の中身を表示
# 使い方: scripts/e2e.sh [作業フォルダ]   （既定: 一時フォルダ）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${1:-$(mktemp -d)}"
mkdir -p "$WORK"
SITE_PORT="${SITE_PORT:-18080}"
HOOK_PORT="${HOOK_PORT:-18765}"
PY="$ROOT/.venv/bin/python"

cleanup() {
  [ -n "${SITE_PID:-}" ] && kill "$SITE_PID" 2>/dev/null || true
  [ -n "${HOOK_PID:-}" ] && kill "$HOOK_PID" 2>/dev/null || true
}
trap cleanup EXIT

wait_up() {
  for _ in $(seq 1 50); do
    if "$PY" -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=1)" "$1" 2>/dev/null; then return 0; fi
    sleep 0.2
  done
  echo "起動を確認できません: $1" >&2
  return 1
}

cp "$ROOT/demo_site/data/day1.json" "$WORK/current.json"
sed -e "s#http://127.0.0.1:8000#http://127.0.0.1:$SITE_PORT#" \
    -e "s#format: slack #format: generic#" "$ROOT/config.example.yaml" > "$WORK/config.yaml"

cd "$ROOT"
"$PY" -m demo_site --data "$WORK/current.json" --port "$SITE_PORT" > "$WORK/demo_site_access.log" 2>&1 &
SITE_PID=$!
"$PY" -m tools.mock_webhook --port "$HOOK_PORT" --out "$WORK/received" > "$WORK/mock_webhook.log" 2>&1 &
HOOK_PID=$!
wait_up "http://127.0.0.1:$SITE_PORT/robots.txt"
sleep 0.5

export WEBHOOK_URL="http://127.0.0.1:$HOOK_PORT/hook"
export RUN_LOG_DIR="$WORK/logs"

echo "########## 1 回目（1 日目のデータ） ##########"
set +e
scripts/run.sh "$WORK/config.yaml"
echo "終了コード: $?"

echo
echo "########## デモショップのデータを 2 日目に差し替え ##########"
cp "$ROOT/demo_site/data/day2.json" "$WORK/current.json"

echo
echo "########## 2 回目（2 日目のデータ） ##########"
scripts/run.sh "$WORK/config.yaml"
echo "終了コード: $?"
set -e

echo
echo "########## 履歴DB の中身 ##########"
"$PY" - "$WORK/data/history.db" <<'PYEOF'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
print("collection_runs:")
for r in c.execute("SELECT run_id, target_name, status, pages_fetched, items_collected, error_count, analyzed_at IS NOT NULL FROM collection_runs"):
    print("  run_id=%s target=%s status=%s pages=%s items=%s errors=%s analyzed=%s" % r)
print("change_events:")
for r in c.execute("SELECT run_id, event_type, product_id, old_value, new_value, notified_at IS NOT NULL FROM change_events ORDER BY event_id"):
    print("  run_id=%s %-12s %-7s %s -> %s notified=%s" % r)
PYEOF

echo
echo "########## 帳票 ##########"
ls "$WORK/output"

echo
echo "########## 受信用モックが受け取った通知 ##########"
ls "$WORK/received"
"$PY" -c "import json,sys; print(json.load(open(sys.argv[1], encoding='utf-8'))['text'])" "$WORK/received/received_001.json"

echo
echo "########## デモショップ側のアクセス記録（先頭 6 行と件数） ##########"
head -n 6 "$WORK/demo_site_access.log"
echo "要求の件数: $(grep -c ' GET ' "$WORK/demo_site_access.log")"
"$PY" - "$WORK/demo_site_access.log" <<'PYEOF'
# 収集部が自分で送った要求（ブラウザが読み込む付随ファイル /static・/api を除く）の最短間隔
import sys
from datetime import datetime
times = []
for line in open(sys.argv[1], encoding="utf-8"):
    if "UA=WebDataCollector" in line and " GET /static" not in line and " GET /api" not in line:
        times.append(datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S,%f"))
gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
print(f"収集部の要求: {len(times)} 件 / 最短の間隔: {min(gaps):.3f} 秒 / 平均: {sum(gaps) / len(gaps):.3f} 秒")
PYEOF
echo "作業フォルダ: $WORK"

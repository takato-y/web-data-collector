#!/usr/bin/env bash
# 収集部（TypeScript）→ 分析部（Python）を順に実行する。cron から呼ぶ想定。
#   使い方: scripts/run.sh [設定ファイル]   （既定: リポジトリ直下の config.yaml）
#   終了コード: 0=成功 / 1=一部失敗（収集の一部失敗・通知の送信失敗） / 2=設定エラー / 3=前回の実行が終わっていない
#   Webhook の URL は環境変数 WEBHOOK_URL で渡す（このファイルにも設定ファイルにも書かない）
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="$(realpath "${1:-$ROOT/config.yaml}")"
LOG_DIR="${RUN_LOG_DIR:-$ROOT/logs}"
NODE="${NODE_BIN:-node}"
PYTHON="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/run_$(date +%Y%m%d).log"

# 同時に 2 本動かさない（履歴DB を収集部と分析部が同時に書かないため）
exec 9>"$LOG_DIR/.run.lock"
if ! flock -n 9; then
  echo "$(date '+%F %T') 前回の実行が終わっていないため、今回は実行しません" | tee -a "$LOG"
  exit 3
fi

echo "$(date '+%F %T') ===== 開始 (設定: $(basename "$CONFIG")) =====" | tee -a "$LOG"
cd "$ROOT"
"$NODE" collector/dist/src/cli.js collect -c "$CONFIG" 2>&1 | tee -a "$LOG"
collect_code=${PIPESTATUS[0]}
if [ "$collect_code" -eq 2 ]; then
  echo "$(date '+%F %T') 設定エラーのため中止します" | tee -a "$LOG"
  exit 2
fi
# 収集が一部失敗でも、取れた分の分析・帳票・通知は行う（掲載終了の判定は分析部が控える）
"$PYTHON" -m webcollector run -c "$CONFIG" 2>&1 | tee -a "$LOG"
analysis_code=${PIPESTATUS[0]}

code=$(( collect_code > analysis_code ? collect_code : analysis_code ))
echo "$(date '+%F %T') ===== 終了 (収集=$collect_code, 分析=$analysis_code) =====" | tee -a "$LOG"
exit "$code"

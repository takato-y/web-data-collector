/** ログ出力。画面（標準エラー）に出し、ファイルの保存は実行スクリプト側でまとめて行う。 */
type Level = "INFO" | "WARNING" | "ERROR";

let quiet = false;
export function setQuiet(value: boolean): void {
  quiet = value;
}

function stamp(): string {
  const d = new Date();
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

// node --test の実行中はログを出さない（結果の一覧を読みやすくするため。WDC_LOG=1 で表示）
const underTest = process.env.NODE_TEST_CONTEXT !== undefined && process.env.WDC_LOG !== "1";

function write(level: Level, msg: string): void {
  if (underTest || (quiet && level === "INFO")) return;
  process.stderr.write(`${stamp()} ${level} [collector] ${msg}\n`);
}

export const log = {
  info: (msg: string) => write("INFO", msg),
  warn: (msg: string) => write("WARNING", msg),
  error: (msg: string) => write("ERROR", msg),
};

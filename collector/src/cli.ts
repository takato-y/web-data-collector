/**
 * 収集部のコマンド（FN-011）。
 *   node dist/src/cli.js collect -c ../config.yaml [--target 名前] [--quiet]
 * 終了コード: 0=すべて成功（見送りを含む） / 1=一部失敗・失敗あり / 2=設定エラー
 */
import { Collector } from "./collector.js";
import { ConfigError, loadConfig } from "./config.js";
import { log, setQuiet } from "./log.js";
import { Storage } from "./storage.js";

const STATUS_LABELS: Record<string, string> = { success: "成功", partial: "一部失敗", failed: "失敗", skipped: "見送り" };

export async function main(argv: string[]): Promise<number> {
  const [command, ...rest] = argv;
  let configPath = "config.yaml";
  let only: string | undefined;
  for (let i = 0; i < rest.length; i++) {
    if (rest[i] === "-c" || rest[i] === "--config") configPath = rest[++i];
    else if (rest[i] === "--target") only = rest[++i];
    else if (rest[i] === "--quiet") setQuiet(true);
  }
  if (command !== "collect") {
    process.stderr.write("使い方: cli.js collect -c config.yaml [--target 名前] [--quiet]\n");
    return 2;
  }
  let cfg;
  try {
    cfg = loadConfig(configPath);
  } catch (e) {
    if (e instanceof ConfigError) {
      log.error(`設定エラー: ${e.message}`);
      return 2;
    }
    throw e;
  }
  const targets = cfg.targets.filter((t) => !only || t.name === only);
  if (targets.length === 0) {
    log.error(`対象が見つかりません: ${only}`);
    return 2;
  }
  const storage = new Storage(cfg.dbPath);
  const collector = new Collector(cfg);
  let exit = 0;
  try {
    for (const t of targets) {
      const runId = storage.startRun(t.name);
      log.info(`収集を開始します: ${t.name} (${t.startUrl})`);
      const result = await collector.collect(t);
      storage.saveResult(runId, result);
      const label = STATUS_LABELS[result.status];
      process.stdout.write(
        `[収集] ${t.name}: ${label} 取得ページ ${result.pagesFetched} / 商品 ${result.items.length} 件 / エラー ${result.errorCount} 件` +
          (result.message ? ` (${result.message})` : "") + "\n",
      );
      if (result.status === "partial" || result.status === "failed") exit = 1;
    }
    process.stdout.write(`[収集] 送信した要求の数（再試行を含む）: ${collector.fetcher.requestCount}\n`);
  } finally {
    storage.close();
  }
  return exit;
}

main(process.argv.slice(2)).then(
  (code) => process.exit(code),
  (e) => {
    log.error(`想定外の誤り: ${(e as Error).stack ?? e}`);
    process.exit(1);
  },
);

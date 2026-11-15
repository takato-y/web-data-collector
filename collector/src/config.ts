/** 設定ファイル（YAML）の読込と検査（FN-001）。収集部が使う項目だけを検査する。 */
import { readFileSync, existsSync } from "node:fs";
import { dirname, resolve, basename } from "node:path";
import { parse as parseYaml } from "yaml";

export const DEFAULT_USER_AGENT = "WebDataCollector/1.0 (+https://example.com/bot-info)";
export const MIN_INTERVAL_SEC = 0.5; // 設定で短くしすぎないための下限
const FIELD_TYPES = ["text", "price", "stock", "url"] as const;
export type FieldType = (typeof FIELD_TYPES)[number];

export class ConfigError extends Error {}

/** 1 項目の取り出し方。selector が無ければ要素自身から取り出す。 */
export interface FieldSpec {
  selector?: string;
  attr?: string;
  type: FieldType;
}

export interface RequestConfig {
  intervalSec: number;
  timeoutSec: number;
  maxRetries: number;
  backoffBaseSec: number;
  maxRetryAfterSec: number;
  maxPages: number;
}

export interface TargetConfig {
  name: string;
  type: "static" | "js";
  startUrl: string;
  itemSelector: string;
  nextPage?: string;
  fields: Record<string, FieldSpec>;
  detailFields: Record<string, FieldSpec>;
  waitFor?: string;
}

export type StockWords = Record<"out_of_stock" | "low_stock" | "in_stock", string[]>;

export interface CollectorConfig {
  userAgent: string;
  request: RequestConfig;
  targets: TargetConfig[];
  dbPath: string;
  stockWords: StockWords;
}

export const DEFAULT_STOCK_WORDS: StockWords = {
  out_of_stock: ["在庫切れ", "売り切れ", "品切れ", "入荷待ち"],
  low_stock: ["残りわずか", "残り僅か", "在庫僅少"],
  in_stock: ["在庫あり", "在庫有り", "在庫有"],
};

type Raw = Record<string, unknown>;

function isObject(v: unknown): v is Raw {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function num(value: unknown, fallback: number, name: string, min = 0): number {
  const n = value === undefined || value === null ? fallback : Number(value);
  if (!Number.isFinite(n)) throw new ConfigError(`${name} は数値で指定してください: ${String(value)}`);
  if (n < min) throw new ConfigError(`${name} は ${min} 以上にしてください: ${n}`);
  return n;
}

function fieldSpecs(raw: unknown, where: string): Record<string, FieldSpec> {
  const specs: Record<string, FieldSpec> = {};
  if (raw === undefined || raw === null) return specs;
  if (!isObject(raw)) throw new ConfigError(`${where} の書き方が正しくありません`);
  for (const [name, value] of Object.entries(raw)) {
    const v: Raw = typeof value === "string" ? { selector: value } : isObject(value) ? value : {};
    if (!isObject(value) && typeof value !== "string") {
      throw new ConfigError(`${where}.${name} の書き方が正しくありません`);
    }
    const type = (v.type ?? "text") as FieldType;
    if (!FIELD_TYPES.includes(type)) {
      throw new ConfigError(`${where}.${name}.type は ${FIELD_TYPES.join(" / ")} のいずれかです: ${String(type)}`);
    }
    specs[name] = {
      selector: typeof v.selector === "string" && v.selector ? v.selector : undefined,
      attr: typeof v.attr === "string" ? v.attr : undefined,
      type,
    };
  }
  return specs;
}

export function parseConfig(data: unknown, baseDir: string): CollectorConfig {
  if (!isObject(data)) throw new ConfigError("設定ファイルの中身が空か、形式が正しくありません");
  const r = isObject(data.request) ? data.request : {};
  const request: RequestConfig = {
    intervalSec: num(r.interval_sec, 1.0, "request.interval_sec", MIN_INTERVAL_SEC),
    timeoutSec: num(r.timeout_sec, 10, "request.timeout_sec", 1),
    maxRetries: Math.floor(num(r.max_retries, 3, "request.max_retries")),
    backoffBaseSec: num(r.backoff_base_sec, 1.0, "request.backoff_base_sec"),
    maxRetryAfterSec: num(r.max_retry_after_sec, 60, "request.max_retry_after_sec"),
    maxPages: Math.floor(num(r.max_pages, 50, "request.max_pages", 1)),
  };

  const targets: TargetConfig[] = [];
  const names = new Set<string>();
  const rawTargets = Array.isArray(data.targets) ? data.targets : [];
  rawTargets.forEach((t: unknown, i: number) => {
    const where = `targets[${i}]`;
    if (!isObject(t)) throw new ConfigError(`${where} の書き方が正しくありません`);
    for (const key of ["name", "start_url", "item_selector"]) {
      if (!t[key]) throw new ConfigError(`${where}.${key} は必須です`);
    }
    const name = String(t.name);
    if (names.has(name)) throw new ConfigError(`対象名が重複しています: ${name}`);
    names.add(name);
    let url: URL;
    try {
      url = new URL(String(t.start_url));
    } catch {
      throw new ConfigError(`${where}.start_url は http(s) の URL で指定してください`);
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      throw new ConfigError(`${where}.start_url は http(s) の URL で指定してください`);
    }
    const fields = fieldSpecs(t.fields, `${where}.fields`);
    if (!fields.product_id) throw new ConfigError(`${where}.fields.product_id は必須です（前回と比べるための鍵）`);
    const type = (t.type ?? "static") as string;
    if (type !== "static" && type !== "js") throw new ConfigError(`${where}.type は static か js です: ${type}`);
    targets.push({
      name,
      type,
      startUrl: url.toString(),
      itemSelector: String(t.item_selector),
      nextPage: typeof t.next_page === "string" ? t.next_page : undefined,
      fields,
      detailFields: fieldSpecs(t.detail_fields, `${where}.detail_fields`),
      waitFor: typeof t.wait_for === "string" ? t.wait_for : undefined,
    });
  });
  if (targets.length === 0) throw new ConfigError("targets に収集対象を 1 件以上指定してください");

  const storage = isObject(data.storage) ? data.storage : {};
  const stockWords = { ...DEFAULT_STOCK_WORDS, ...(isObject(data.stock_words) ? (data.stock_words as Partial<StockWords>) : {}) };
  return {
    userAgent: typeof data.user_agent === "string" && data.user_agent ? data.user_agent : DEFAULT_USER_AGENT,
    request,
    targets,
    dbPath: resolve(baseDir, typeof storage.db_path === "string" ? storage.db_path : "data/history.db"),
    stockWords,
  };
}

export function loadConfig(path: string): CollectorConfig {
  if (!existsSync(path)) throw new ConfigError(`設定ファイルが見つかりません: ${basename(path)}`);
  let data: unknown;
  try {
    data = parseYaml(readFileSync(path, "utf-8"));
  } catch (e) {
    throw new ConfigError(`設定ファイルを読めません（YAML の書き方の誤り）: ${(e as Error).message}`);
  }
  return parseConfig(data, dirname(resolve(path)));
}

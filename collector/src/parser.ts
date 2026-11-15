/** HTML の解析: CSS セレクタで値を取り出し、価格・在庫を正規化する（FN-005）。 */
import * as cheerio from "cheerio";
import type { Cheerio, CheerioAPI } from "cheerio";
import type { AnyNode } from "domhandler";
import type { FieldSpec, StockWords } from "./config.js";
import { STOCK, type Stock } from "./models.js";

export const MAX_TEXT_LEN = 200; // 想定外に長い文字列を保存しない

/** 前後の空白と連続する空白・改行を詰める。空なら null。 */
export function cleanText(text: string | null | undefined): string | null {
  if (text === null || text === undefined) return null;
  const t = text.replace(/\s+/g, " ").trim().slice(0, MAX_TEXT_LEN);
  return t || null;
}

/** 「¥1,280」「1,280円（税込）」などから整数の価格を取り出す。取り出せなければ null。 */
export function parsePrice(text: string | null | undefined): number | null {
  if (!text) return null;
  const t = text.normalize("NFKC");
  const marked = /[¥￥]\s*([0-9][0-9,]*)|([0-9][0-9,]*)\s*円/.exec(t);
  const raw = marked ? marked[1] ?? marked[2] : /[0-9][0-9,]*/.exec(t)?.[0];
  if (!raw) return null;
  const n = Number(raw.replace(/,/g, ""));
  return Number.isSafeInteger(n) ? n : null;
}

/** 在庫の表示を 4 区分に揃える。品切れ系の語を先に見る。 */
export function normalizeStock(text: string | null | undefined, words: StockWords): Stock {
  if (!text) return STOCK.UNKNOWN;
  const order: [keyof StockWords, Stock][] = [
    ["out_of_stock", STOCK.OUT],
    ["low_stock", STOCK.LOW],
    ["in_stock", STOCK.IN],
  ];
  for (const [key, code] of order) {
    if ((words[key] ?? []).some((w) => text.includes(w))) return code;
  }
  return STOCK.UNKNOWN;
}

export type FieldValue = string | number | null;

function extract($el: Cheerio<AnyNode>, spec: FieldSpec, baseUrl: string, words: StockWords): FieldValue {
  const node = spec.selector ? $el.find(spec.selector).first() : $el;
  if (node.length === 0) return null;
  const raw = spec.attr ? node.attr(spec.attr) ?? null : node.text();
  if (spec.type === "price") return parsePrice(raw);
  if (spec.type === "stock") return normalizeStock(raw, words);
  if (spec.type === "url") {
    if (!raw) return null;
    try {
      return new URL(raw.trim(), baseUrl).toString();
    } catch {
      return null;
    }
  }
  return cleanText(raw);
}

export function parseItems(
  html: string, baseUrl: string, itemSelector: string, fields: Record<string, FieldSpec>, words: StockWords,
): Record<string, FieldValue>[] {
  const $ = cheerio.load(html);
  return $(itemSelector)
    .toArray()
    .map((el) => {
      const row: Record<string, FieldValue> = {};
      for (const [name, spec] of Object.entries(fields)) row[name] = extract($(el), spec, baseUrl, words);
      return row;
    });
}

export function findNextUrl(html: string, baseUrl: string, selector?: string): string | null {
  if (!selector) return null;
  const href = cheerio.load(html)(selector).first().attr("href");
  if (!href) return null;
  return new URL(href, baseUrl).toString();
}

export function parseDetail(
  html: string, baseUrl: string, fields: Record<string, FieldSpec>, words: StockWords,
): Record<string, FieldValue> {
  const $: CheerioAPI = cheerio.load(html);
  const row: Record<string, FieldValue> = {};
  for (const [name, spec] of Object.entries(fields)) row[name] = extract($.root(), spec, baseUrl, words);
  return row;
}

/** 1 対象ぶんの収集の流れ（一覧のページ送り → 詳細 → 結果のまとめ）。 */
import type { CollectorConfig, TargetConfig } from "./config.js";
import { Fetcher, FetchError } from "./fetcher.js";
import { JsUnavailable, renderWithPlaywright, type Renderer } from "./jsRenderer.js";
import { log } from "./log.js";
import { emptyResult, type CollectResult, type ProductItem, type Stock } from "./models.js";
import { findNextUrl, parseDetail, parseItems, type FieldValue } from "./parser.js";
import { RobotsPolicy } from "./politeness.js";

const ITEM_FIELDS = ["name", "price", "stock", "category", "url"] as const;

export interface CollectorDeps {
  fetcher?: Fetcher;
  robots?: RobotsPolicy;
  renderer?: Renderer;
}

export class Collector {
  readonly fetcher: Fetcher;
  readonly robots: RobotsPolicy;
  private renderer: Renderer;

  constructor(private cfg: CollectorConfig, deps: CollectorDeps = {}) {
    this.fetcher = deps.fetcher ?? new Fetcher(cfg.request, cfg.userAgent);
    this.robots = deps.robots ?? new RobotsPolicy(this.fetcher.fetchRobots, cfg.userAgent);
    this.renderer = deps.renderer ?? renderWithPlaywright;
  }

  private async checkRobots(url: string): Promise<boolean> {
    if (await this.robots.allowed(url)) return true;
    log.warn(`robots.txt で禁止されているため取得しません: ${url}`);
    return false;
  }

  private async getHtml(url: string): Promise<string> {
    const interval = await this.robots.intervalFor(url, this.cfg.request.intervalSec);
    return (await this.fetcher.get(url, interval)).text;
  }

  async collect(target: TargetConfig): Promise<CollectResult> {
    const result = emptyResult(target.name);
    if (await this.robots.isUnavailable(target.startUrl)) {
      return { ...result, status: "skipped", message: "robots.txt を取得できないため見送り" };
    }
    if (!(await this.checkRobots(target.startUrl))) {
      return { ...result, status: "skipped", message: "開始 URL が robots.txt で禁止されている" };
    }
    const rows = target.type === "js" ? await this.collectJs(target, result) : await this.collectStatic(target, result);
    if (result.status === "skipped") return result;
    result.items = this.toItems(rows);
    if (Object.keys(target.detailFields).length > 0) await this.fillDetails(target, result);
    result.status = result.errorCount === 0 ? "success" : result.items.length > 0 ? "partial" : "failed";
    return result;
  }

  private async collectStatic(target: TargetConfig, result: CollectResult): Promise<Record<string, FieldValue>[]> {
    const rows: Record<string, FieldValue>[] = [];
    const host = new URL(target.startUrl).host;
    const visited = new Set<string>();
    let url: string | null = target.startUrl;
    while (url) {
      if (visited.has(url)) {
        log.warn(`同じページに戻ったため、ページ送りを止めます: ${url}`);
        break;
      }
      if (result.pagesFetched >= this.cfg.request.maxPages) {
        log.warn(`取得ページ数の上限 (${this.cfg.request.maxPages}) に達したため止めます`);
        result.errorCount++;
        result.message = "取得ページ数の上限に達した";
        break;
      }
      if (new URL(url).host !== host) {
        log.warn(`別のホストへのリンクはたどりません: ${url}`);
        break;
      }
      if (!(await this.checkRobots(url))) {
        result.errorCount++;
        break;
      }
      visited.add(url);
      let html: string;
      try {
        html = await this.getHtml(url);
      } catch (e) {
        if (!(e instanceof FetchError)) throw e;
        log.error(`一覧ページを取得できません: ${e.message}`);
        result.errorCount++;
        break;
      }
      result.pagesFetched++;
      const pageRows = parseItems(html, url, target.itemSelector, target.fields, this.cfg.stockWords);
      log.info(`一覧 ${url} から ${pageRows.length} 件`);
      rows.push(...pageRows);
      url = findNextUrl(html, url, target.nextPage);
    }
    return rows;
  }

  private async collectJs(target: TargetConfig, result: CollectResult): Promise<Record<string, FieldValue>[]> {
    const interval = await this.robots.intervalFor(target.startUrl, this.cfg.request.intervalSec);
    await this.fetcher.limiter.wait(new URL(target.startUrl).host, interval);
    let html: string;
    try {
      html = await this.renderer(target.startUrl, this.cfg.userAgent, target.waitFor, this.cfg.request.timeoutSec);
    } catch (e) {
      if (e instanceof JsUnavailable) {
        log.warn(`JavaScript ページを見送ります: ${e.message}`);
        result.status = "skipped";
        result.message = e.message;
        return [];
      }
      // ブラウザ側の誤りは種類が多いため、まとめて記録して続行する
      log.error(`JavaScript ページを取得できません: ${target.startUrl} (${(e as Error).message.split("\n")[0]})`);
      result.errorCount++;
      return [];
    }
    result.pagesFetched++;
    const rows = parseItems(html, target.startUrl, target.itemSelector, target.fields, this.cfg.stockWords);
    log.info(`JavaScript ページ ${target.startUrl} から ${rows.length} 件`);
    return rows;
  }

  private toItems(rows: Record<string, FieldValue>[]): ProductItem[] {
    const items = new Map<string, ProductItem>();
    for (const row of rows) {
      const pid = row.product_id;
      if (!pid) {
        log.warn(`商品ID が取れない行を飛ばします: ${JSON.stringify(row)}`);
        continue;
      }
      const id = String(pid);
      if (items.has(id)) continue; // 同じ商品が複数ページに出た場合は最初のものを使う
      items.set(id, {
        productId: id,
        name: (row.name as string) ?? null,
        price: typeof row.price === "number" ? row.price : null,
        stock: (row.stock as Stock) ?? null,
        category: (row.category as string) ?? null,
        url: (row.url as string) ?? null,
      });
    }
    return [...items.values()];
  }

  private async fillDetails(target: TargetConfig, result: CollectResult): Promise<void> {
    const host = new URL(target.startUrl).host;
    for (const item of result.items) {
      if (!item.url || new URL(item.url).host !== host) continue;
      if (!(await this.checkRobots(item.url))) continue;
      let html: string;
      try {
        html = await this.getHtml(item.url);
      } catch (e) {
        if (!(e instanceof FetchError)) throw e;
        log.error(`詳細ページを取得できません: ${e.message}`);
        result.errorCount++;
        continue;
      }
      result.pagesFetched++;
      const detail = parseDetail(html, item.url, target.detailFields, this.cfg.stockWords);
      for (const key of ITEM_FIELDS) {
        const v = detail[key];
        if (v !== null && v !== undefined) (item as unknown as Record<string, FieldValue>)[key] = v;
      }
    }
  }
}

/** テスト用の部品: 127.0.0.1 の空いているポートで小さな Web サーバーを起動する。 */
import { createServer, type IncomingMessage, type ServerResponse, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { parseConfig, type CollectorConfig } from "../src/config.js";
import { RateLimiter } from "../src/politeness.js";

export type Handler = (req: IncomingMessage, res: ServerResponse) => void;

export interface TestServer {
  base: string;
  requests: { path: string; ua: string | undefined }[];
  close(): Promise<void>;
}

export async function startServer(handler: Handler): Promise<TestServer> {
  const requests: { path: string; ua: string | undefined }[] = [];
  const server: Server = createServer((req, res) => {
    requests.push({ path: req.url ?? "", ua: req.headers["user-agent"] });
    handler(req, res);
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const { port } = server.address() as AddressInfo;
  return {
    base: `http://127.0.0.1:${port}`,
    requests,
    close: () => new Promise((r) => { server.closeAllConnections(); server.close(() => r()); }),
  };
}

/** 待ち受けの無いポートの URL（一度確保してすぐ閉じたポート）。 */
export async function closedPortUrl(): Promise<string> {
  const s = await startServer(() => undefined);
  await s.close();
  return s.base;
}

/** 待ちを記録だけして実際には待たない間隔制御（テストを速くするため）。 */
export class NoWaitLimiter extends RateLimiter {
  calls: [string, number][] = [];
  override wait(host: string, interval: number): Promise<number> {
    this.calls.push([host, interval]);
    return Promise.resolve(0);
  }
}

export const noSleep = async (_sec: number) => undefined;

const PRODUCTS = [
  { id: "A-1", name: "方眼ノート", price: 480, stock: "在庫あり", category: "ノート" },
  { id: "A-2", name: "ボールペン", price: 980, stock: "在庫切れ", category: "筆記具" },
  { id: "A-3", name: "ふせん", price: 420, stock: "残りわずか", category: "ふせん" },
];

/** デモショップと同じ形のページを返す小さなショップ（1 ページ 2 件）。 */
export function shopHandler(opts: { robots?: string | null; robotsStatus?: number; failDetail?: string } = {}): Handler {
  return (req, res) => {
    const url = new URL(req.url ?? "/", "http://x");
    const html = (body: string) => {
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(`<!doctype html><html><body>${body}</body></html>`);
    };
    if (url.pathname === "/robots.txt") {
      if (opts.robots === null) { res.writeHead(404); res.end(); return; }
      res.writeHead(opts.robotsStatus ?? 200, { "Content-Type": "text/plain" });
      res.end(opts.robots ?? "User-agent: *\nDisallow: /admin/\nCrawl-delay: 1\n");
      return;
    }
    if (url.pathname === "/products") {
      const page = Number(url.searchParams.get("page") ?? "1");
      const items = PRODUCTS.slice((page - 1) * 2, page * 2);
      const cards = items.map((p) =>
        `<li class="product-card" data-product-id="${p.id}"><a class="product-link" href="/products/${p.id}">` +
        `<span class="name">${p.name}</span></a><span class="price">¥${p.price.toLocaleString()}</span></li>`).join("");
      const next = page * 2 < PRODUCTS.length ? `<a class="next" href="/products?page=${page + 1}">次へ</a>` : "";
      return html(`<ul>${cards}</ul>${next}`);
    }
    const m = /^\/products\/(.+)$/.exec(url.pathname);
    if (m && m[1] !== opts.failDetail) {
      const p = PRODUCTS.find((x) => x.id === m[1]);
      if (p) return html(`<span class="stock">${p.stock}</span><span class="category">${p.category}</span>`);
    }
    if (url.pathname === "/loop") return html(`<li class="product-card" data-product-id="L"></li><a class="next" href="/loop">次へ</a>`);
    res.writeHead(404);
    res.end("not found");
  };
}

export function makeConfig(base: string, overrides: Record<string, unknown> = {}): CollectorConfig {
  return parseConfig({
    request: { interval_sec: 0.5, backoff_base_sec: 0, max_retries: 2, timeout_sec: 2 },
    targets: [
      {
        name: "shop", start_url: `${base}/products`, item_selector: "li.product-card", next_page: "a.next",
        fields: {
          product_id: { attr: "data-product-id" }, name: { selector: ".name" },
          price: { selector: ".price", type: "price" }, url: { selector: "a.product-link", attr: "href", type: "url" },
        },
        detail_fields: { stock: { selector: ".stock", type: "stock" }, category: { selector: ".category" } },
      },
      {
        name: "shop_js", type: "js", start_url: `${base}/new`, wait_for: "li.product-card", item_selector: "li.product-card",
        fields: { product_id: { attr: "data-product-id" }, name: ".name", price: { selector: ".price", type: "price" },
          stock: { selector: ".stock", type: "stock" } },
      },
    ],
    storage: { db_path: "h.db" },
    ...overrides,
  }, "/tmp");
}

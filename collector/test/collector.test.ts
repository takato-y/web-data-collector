/** 収集の流れ（FN-002〜006 の組み合わせ）のテスト。 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { Collector } from "../src/collector.js";
import { Fetcher } from "../src/fetcher.js";
import { JsUnavailable, renderWithPlaywright, type Renderer } from "../src/jsRenderer.js";
import { NoWaitLimiter, closedPortUrl, makeConfig, noSleep, shopHandler, startServer } from "./helpers.js";

function build(base: string, renderer?: Renderer) {
  const cfg = makeConfig(base);
  const limiter = new NoWaitLimiter();
  const fetcher = new Fetcher(cfg.request, cfg.userAgent, { limiter, sleep: noSleep });
  return { cfg, limiter, c: new Collector(cfg, { fetcher, renderer }) };
}

test("全ページと詳細を取得し、Crawl-delay の間隔で待つ（TC-005-04, TC-003-02）", async () => {
  const s = await startServer(shopHandler());
  try {
    const { cfg, c, limiter } = build(s.base);
    const r = await c.collect(cfg.targets[0]);
    assert.equal(r.status, "success");
    assert.equal(r.items.length, 3);
    assert.equal(r.pagesFetched, 2 + 3);
    const a2 = r.items.find((i) => i.productId === "A-2")!;
    assert.deepEqual([a2.price, a2.stock, a2.category], [980, "out_of_stock", "筆記具"]);
    // 1 回目は robots.txt 自体の取得（設定の 0.5 秒）、以降は Crawl-delay: 1
    assert.equal(limiter.calls[0][1], 0.5);
    assert.deepEqual([...new Set(limiter.calls.slice(1).map((x) => x[1]))], [1]);
    assert.ok(s.requests.every((q) => q.ua?.startsWith("WebDataCollector/1.0")));
  } finally { await s.close(); }
});

test("開始 URL が robots.txt で禁止なら取得しない（TC-002-05）", async () => {
  const s = await startServer(shopHandler());
  try {
    const { cfg, c } = build(s.base);
    const t = { ...cfg.targets[0], startUrl: `${s.base}/admin/` };
    const r = await c.collect(t);
    assert.equal(r.status, "skipped");
    assert.deepEqual(s.requests.map((q) => q.path), ["/robots.txt"]);
  } finally { await s.close(); }
});

test("robots.txt に接続できなければ見送り（TC-002-06）", async () => {
  const base = await closedPortUrl();
  const { cfg, c } = build(base);
  const r = await c.collect(cfg.targets[0]);
  assert.equal(r.status, "skipped");
  assert.match(r.message, /見送り/);
});

test("取得ページ数の上限で止め、一部失敗とする（TC-005-05）", async () => {
  const s = await startServer(shopHandler());
  try {
    const { cfg, c } = build(s.base);
    cfg.request.maxPages = 1;
    const r = await c.collect({ ...cfg.targets[0], detailFields: {} });
    assert.equal(r.status, "partial");
    assert.equal(r.items.length, 2);
    assert.match(r.message, /上限/);
  } finally { await s.close(); }
});

test("同じページへ戻るページ送りは止める（TC-005-06）", async () => {
  const s = await startServer(shopHandler());
  try {
    const { cfg, c } = build(s.base);
    const r = await c.collect({ ...cfg.targets[0], startUrl: `${s.base}/loop`, detailFields: {} });
    assert.equal(r.pagesFetched, 1);
    assert.equal(r.status, "success");
  } finally { await s.close(); }
});

test("詳細の取得に失敗したら一部失敗、値は空のまま（TC-005-07）", async () => {
  const s = await startServer(shopHandler({ failDetail: "A-1" }));
  try {
    const { cfg, c } = build(s.base);
    const r = await c.collect(cfg.targets[0]);
    assert.equal(r.status, "partial");
    assert.equal(r.errorCount, 1);
    assert.equal(r.items.find((i) => i.productId === "A-1")!.stock, null);
  } finally { await s.close(); }
});

test("前回は商品があったのに今回 0 件なら失敗とし、掲載終了を判定させない（TC-005-09）", async () => {
  const s = await startServer(shopHandler());
  try {
    const { cfg, c } = build(s.base);
    const t = { ...cfg.targets[0], itemSelector: "li.no-such-card", detailFields: {} };
    const r = await c.collect(t, 3);
    assert.equal(r.status, "failed");
    assert.equal(r.errorCount, 1);
    assert.equal(r.pagesFetched, 2); // 一覧は取得できている（ページ送りのリンクはセレクタと別のため 2 ページ）
    assert.match(r.message, /商品が 0 件（前回 3 件）/);
    // JavaScript ページでも同じ
    const { cfg: cfg2, c: c2 } = build(s.base, async () => "<ul></ul>");
    const rj = await c2.collect(cfg2.targets[1], 2);
    assert.equal(rj.status, "failed");
    assert.match(rj.message, /前回 2 件/);
  } finally { await s.close(); }
});

test("初回・前回も 0 件の対象は 0 件でも成功のまま（TC-005-10）", async () => {
  const s = await startServer(shopHandler());
  try {
    const { cfg, c } = build(s.base);
    const t = { ...cfg.targets[0], itemSelector: "li.no-such-card", detailFields: {} };
    for (const prev of [undefined, 0]) {
      const r = await c.collect(t, prev);
      assert.equal(r.status, "success");
      assert.equal(r.errorCount, 0);
    }
  } finally { await s.close(); }
});

test("JavaScript ページを描画関数経由で解析（TC-006-01）", async () => {
  const s = await startServer(shopHandler());
  try {
    const html = '<li class="product-card" data-product-id="N-1"><span class="name">万年筆</span><span class="price">¥3,300</span><span class="stock">在庫あり</span></li>';
    const { cfg, c } = build(s.base, async () => html);
    const r = await c.collect(cfg.targets[1]);
    assert.equal(r.status, "success");
    assert.deepEqual([r.items[0].price, r.items[0].stock], [3300, "in_stock"]);
  } finally { await s.close(); }
});

test("Playwright が無ければ JavaScript ページは見送り（TC-006-02）", async () => {
  const s = await startServer(shopHandler());
  try {
    const { cfg, c } = build(s.base, async () => { throw new JsUnavailable("Playwright が導入されていません"); });
    const r = await c.collect(cfg.targets[1]);
    assert.equal(r.status, "skipped");
    assert.match(r.message, /Playwright/);
  } finally { await s.close(); }
});

test("実際のブラウザで JavaScript ページを描画（TC-006-03・ブラウザ未導入なら飛ばす）", async (t) => {
  const page = `<!doctype html><html><body><ul id="a"></ul><script>
    setTimeout(function(){var li=document.createElement('li');li.className='product-card';li.setAttribute('data-product-id','N-9');
    li.innerHTML='<span class="name">手帳</span><span class="price">¥1,650</span><span class="stock">残りわずか</span>';
    document.getElementById('a').appendChild(li);},100);</script></body></html>`;
  const s = await startServer((req, res) => {
    if (req.url === "/robots.txt") { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" }); res.end(page);
  });
  try {
    const { cfg, c } = build(s.base, renderWithPlaywright);
    const r = await c.collect(cfg.targets[1]);
    if (r.status === "skipped") { t.skip(r.message); return; }
    assert.equal(r.status, "success");
    assert.deepEqual(r.items.map((i) => [i.productId, i.price, i.stock]), [["N-9", 1650, "low_stock"]]);
    assert.ok(s.requests.every((q) => q.ua?.startsWith("WebDataCollector/1.0")));
  } finally { await s.close(); }
});

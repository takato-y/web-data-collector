/** FN-004 ページ取得（名乗り・再試行・タイムアウト・文字コード）のテスト。 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseConfig } from "../src/config.js";
import { Fetcher, FetchError, decodeBody } from "../src/fetcher.js";
import { NoWaitLimiter, closedPortUrl, startServer } from "./helpers.js";

const UA = "WebDataCollector/1.0 (+https://example.com/bot-info)";

function makeFetcher(req: Record<string, number> = {}) {
  const cfg = parseConfig({
    request: { interval_sec: 0.5, timeout_sec: 2, max_retries: 3, backoff_base_sec: 1, ...req },
    targets: [{ name: "t", start_url: "http://127.0.0.1/", item_selector: "x", fields: { product_id: "x" } }],
  }, "/tmp");
  const sleeps: number[] = [];
  const f = new Fetcher(cfg.request, UA, { limiter: new NoWaitLimiter(), sleep: async (s) => { sleeps.push(s); } });
  return { f, sleeps };
}

test("名乗り（User-Agent）を送る（TC-004-01）", async () => {
  const s = await startServer((_q, r) => { r.writeHead(200, { "Content-Type": "text/html; charset=utf-8" }); r.end("こんにちは"); });
  try {
    const { f } = makeFetcher();
    assert.equal((await f.get(s.base + "/")).text, "こんにちは");
    assert.equal(s.requests[0].ua, UA);
  } finally { await s.close(); }
});

test("503 + Retry-After に従って再試行し、回復したら成功（TC-004-02）", async () => {
  let n = 0;
  const s = await startServer((_q, r) => {
    if (n++ < 2) { r.writeHead(503, { "Retry-After": "1" }); r.end(); return; }
    r.writeHead(200); r.end("ok");
  });
  try {
    const { f, sleeps } = makeFetcher();
    assert.equal((await f.get(s.base + "/")).text, "ok");
    assert.equal(f.requestCount, 3);
    assert.deepEqual(sleeps, [1, 1]);
  } finally { await s.close(); }
});

test("再試行の上限で諦める（TC-004-03）", async () => {
  const s = await startServer((_q, r) => { r.writeHead(503); r.end(); });
  try {
    const { f, sleeps } = makeFetcher({ max_retries: 2, backoff_base_sec: 0 });
    await assert.rejects(f.get(s.base + "/"), (e: FetchError) => e.status === 503);
    assert.equal(f.requestCount, 3);
    assert.equal(sleeps.length, 2);
  } finally { await s.close(); }
});

test("Retry-After が無ければ待ち時間を倍々に広げる（TC-004-04）", async () => {
  const s = await startServer((_q, r) => { r.writeHead(500); r.end(); });
  try {
    const { f, sleeps } = makeFetcher({ max_retries: 3, backoff_base_sec: 0.01 });
    await assert.rejects(f.get(s.base + "/"));
    assert.deepEqual(sleeps, [0.01, 0.02, 0.04]);
  } finally { await s.close(); }
});

test("404 は再試行しない（TC-004-05）", async () => {
  const s = await startServer((_q, r) => { r.writeHead(404); r.end(); });
  try {
    const { f, sleeps } = makeFetcher();
    await assert.rejects(f.get(s.base + "/"), (e: FetchError) => e.status === 404);
    assert.equal(f.requestCount, 1);
    assert.deepEqual(sleeps, []);
  } finally { await s.close(); }
});

test("応答が遅いと打ち切って再試行し、最後は失敗（TC-004-06）", async () => {
  const s = await startServer((_q, r) => { setTimeout(() => { r.writeHead(200); r.end("late"); }, 1500); });
  try {
    const { f } = makeFetcher({ timeout_sec: 1, max_retries: 1, backoff_base_sec: 0 });
    const started = Date.now();
    await assert.rejects(f.get(s.base + "/"), /タイムアウト/);
    assert.equal(f.requestCount, 2);
    assert.ok(Date.now() - started < 4000);
  } finally { await s.close(); }
});

test("接続できない場合の誤り（TC-004-07）", async () => {
  const { f } = makeFetcher({ max_retries: 1, backoff_base_sec: 0 });
  await assert.rejects(f.get((await closedPortUrl()) + "/"), /接続できません/);
});

test("別のホストへの転送は受け付けない（TC-004-08）", async () => {
  const other = await startServer((_q, r) => { r.writeHead(200); r.end("other"); });
  const port = new URL(other.base).port;
  const s = await startServer((_q, r) => { r.writeHead(302, { Location: `http://localhost:${port}/` }); r.end(); });
  try {
    const { f } = makeFetcher({ max_retries: 0 });
    await assert.rejects(f.get(s.base + "/"), /別のホスト/);
  } finally { await s.close(); await other.close(); }
});

test("Shift_JIS のページも文字化けせずに読む（TC-004-09）", () => {
  // 「在庫あり」を Shift_JIS で表したバイト列
  const sjis = new Uint8Array([0x8d, 0xdd, 0x8c, 0xc9, 0x82, 0xa0, 0x82, 0xe8]).buffer;
  assert.equal(decodeBody(sjis, "text/html; charset=Shift_JIS"), "在庫あり");
  const withMeta = new Uint8Array([...new TextEncoder().encode('<meta charset="shift_jis">'), 0x8d, 0xdd, 0x8c, 0xc9]).buffer;
  assert.ok(decodeBody(withMeta, "text/html").endsWith("在庫"));
});

test("Retry-After の上限（TC-004-10）", () => {
  const { f } = makeFetcher();
  assert.equal(f.backoff(0, 3600), 60);
});

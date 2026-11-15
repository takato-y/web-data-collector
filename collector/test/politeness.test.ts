/** FN-002 robots.txt 確認・FN-003 アクセス間隔制御のテスト。 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { RateLimiter, RobotsPolicy } from "../src/politeness.js";

const UA = "WebDataCollector/1.0 (+https://example.com/bot-info)";

test("同じホストへの間隔を保ち、別ホストは待たない（TC-003-01）", async () => {
  let now = 100;
  const slept: number[] = [];
  const rl = new RateLimiter(() => now, async (s) => { slept.push(Number(s.toFixed(3))); now += s; });
  await rl.wait("a.example.com", 1);
  now += 0.3;
  await rl.wait("a.example.com", 1);
  await rl.wait("b.example.com", 1);
  now += 5;
  await rl.wait("a.example.com", 1);
  assert.deepEqual(slept, [0.7]);
});

test("robots.txt の禁止と Crawl-delay、取得はホストごとに 1 回（TC-002-01）", async () => {
  const fetched: string[] = [];
  const p = new RobotsPolicy(async (u) => { fetched.push(u); return { status: 200, body: "User-agent: *\nDisallow: /admin/\nCrawl-delay: 2\n" }; }, UA);
  assert.equal(await p.allowed("http://shop.example.com/products"), true);
  assert.equal(await p.allowed("http://shop.example.com/admin/"), false);
  assert.equal(await p.intervalFor("http://shop.example.com/products", 1), 2);
  assert.equal(await p.intervalFor("http://shop.example.com/products", 3), 3);
  assert.deepEqual(fetched, ["http://shop.example.com/robots.txt"]);
});

test("このツール名を名指しした禁止に従う（TC-002-02）", async () => {
  const p = new RobotsPolicy(async () => ({ status: 200, body: "User-agent: WebDataCollector\nDisallow: /\n\nUser-agent: *\nAllow: /\n" }), UA);
  assert.equal(await p.allowed("http://shop.example.com/products"), false);
});

test("robots.txt が無い（404・410）なら制限なし（TC-002-03）", async () => {
  for (const status of [404, 410]) {
    const p = new RobotsPolicy(async () => ({ status, body: "" }), UA);
    assert.equal(await p.allowed("http://shop.example.com/x"), true);
    assert.equal(await p.isUnavailable("http://shop.example.com/"), false);
  }
});

test("robots.txt が 5xx・通信エラーなら全て取得しない（TC-002-04）", async () => {
  for (const status of [503, null]) {
    const p = new RobotsPolicy(async () => ({ status, body: "" }), UA);
    assert.equal(await p.isUnavailable("http://shop.example.com/"), true);
    assert.equal(await p.allowed("http://shop.example.com/products"), false);
  }
});

test("robots.txt が 404・410 以外の 4xx（401・403・429 など）なら全て取得しない（TC-002-07）", async () => {
  for (const status of [400, 401, 403, 429]) {
    const p = new RobotsPolicy(async () => ({ status, body: "" }), UA);
    assert.equal(await p.isUnavailable("http://shop.example.com/"), true, `status=${status}`);
    assert.equal(await p.allowed("http://shop.example.com/products"), false, `status=${status}`);
  }
});

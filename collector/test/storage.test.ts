/** FN-007 履歴保存のテスト（受け渡し口の列が設計どおりに書かれるか）。 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Storage, nowIso } from "../src/storage.js";
import type { CollectResult } from "../src/models.js";

function tmpDb() {
  return new Storage(join(mkdtempSync(join(tmpdir(), "wdc-")), "h.db"));
}

const ok = (items: CollectResult["items"]): CollectResult =>
  ({ target: "shop", items, pagesFetched: 3, errorCount: 0, status: "success", message: "" });

test("実行・商品・スナップショットを保存する（TC-007-01）", () => {
  const st = tmpDb();
  const run = st.startRun("shop", "2026-11-15T09:00:00+09:00");
  st.saveResult(run, ok([{ productId: "A-1", name: "ノート", price: 480, stock: "in_stock", category: "ノート", url: "http://x/A-1" }]));
  const r = st.db.prepare("SELECT * FROM collection_runs").get() as Record<string, unknown>;
  assert.deepEqual([r.status, r.pages_fetched, r.items_collected, r.analyzed_at], ["success", 3, 1, null]);
  const p = st.db.prepare("SELECT * FROM products").get() as Record<string, unknown>;
  assert.deepEqual([p.first_seen_run_id, p.last_seen_run_id, p.is_listed], [run, run, 1]);
  const s = st.db.prepare("SELECT price, stock FROM price_snapshots").get();
  assert.deepEqual({ ...(s as object) }, { price: 480, stock: "in_stock" });
  st.close();
});

test("2 回目は商品を更新し、掲載中の印（分析部が書く列）には触れない（TC-007-02）", () => {
  const st = tmpDb();
  const r1 = st.startRun("shop");
  st.saveResult(r1, ok([{ productId: "A-1", name: "ノート", price: 480, stock: null, category: null, url: null }]));
  st.db.prepare("UPDATE products SET is_listed = 0").run(); // 分析部が掲載終了にした状態
  const r2 = st.startRun("shop");
  st.saveResult(r2, ok([{ productId: "A-1", name: null, price: 398, stock: null, category: "ノート", url: null }]));
  const p = st.db.prepare("SELECT * FROM products").get() as Record<string, unknown>;
  assert.deepEqual([p.name, p.category, p.first_seen_run_id, p.last_seen_run_id, p.is_listed], ["ノート", "ノート", r1, r2, 0]);
  assert.equal((st.db.prepare("SELECT COUNT(*) n FROM price_snapshots").get() as { n: number }).n, 2);
  st.close();
});

test("見送りの実行はスナップショットを保存しない（TC-007-03）", () => {
  const st = tmpDb();
  const run = st.startRun("shop");
  st.saveResult(run, { ...ok([]), status: "skipped", message: "見送り" });
  assert.equal((st.db.prepare("SELECT COUNT(*) n FROM price_snapshots").get() as { n: number }).n, 0);
  assert.equal((st.db.prepare("SELECT status FROM collection_runs").get() as { status: string }).status, "skipped");
  st.close();
});

test("制約違反なら、その実行の書き込みをすべて取り消す（TC-007-04）", () => {
  const st = tmpDb();
  const run = st.startRun("shop");
  assert.throws(() => st.saveResult(run, ok([
    { productId: "A-1", name: "ノート", price: 100, stock: null, category: null, url: null },
    { productId: "A-2", name: "ペン", price: -1, stock: null, category: null, url: null }, // 価格の CHECK 制約に違反
  ])));
  assert.equal((st.db.prepare("SELECT COUNT(*) n FROM products").get() as { n: number }).n, 0);
  assert.equal((st.db.prepare("SELECT status FROM collection_runs").get() as { status: string }).status, "running");
  st.close();
});

test("日時は分析部（Python）が読める形式（TC-007-05）", () => {
  assert.match(nowIso(new Date()), /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$/);
});

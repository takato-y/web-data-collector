/** FN-001 設定読込（収集部）のテスト。 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { ConfigError, loadConfig, parseConfig } from "../src/config.js";

const EXAMPLE = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "config.example.yaml");
const base = () => ({ targets: [{ name: "t", start_url: "http://127.0.0.1/", item_selector: "li", fields: { product_id: { attr: "id" } } }] });

test("設定例を読める（TC-001-01）", () => {
  const cfg = loadConfig(EXAMPLE);
  assert.deepEqual(cfg.targets.map((t) => [t.name, t.type]), [["demo_shop", "static"], ["demo_shop_new", "js"]]);
  assert.equal(cfg.request.intervalSec, 1);
  assert.ok(cfg.dbPath.endsWith("data/history.db"));
});

test("誤った設定は理由つきで止める（TC-001-02）", () => {
  const cases: [(d: any) => void, RegExp][] = [
    [(d) => (d.request = { interval_sec: 0.1 }), /interval_sec/],
    [(d) => delete d.targets[0].fields.product_id, /product_id/],
    [(d) => (d.targets[0].start_url = "ftp://example.com/"), /start_url/],
    [(d) => d.targets.push({ ...d.targets[0] }), /重複/],
    [(d) => (d.targets[0].type = "browser"), /static か js/],
    [(d) => (d.targets = []), /targets/],
  ];
  for (const [mutate, msg] of cases) {
    const d = base();
    mutate(d);
    assert.throws(() => parseConfig(d, "/tmp"), (e: Error) => e instanceof ConfigError && msg.test(e.message));
  }
});

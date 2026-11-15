/** FN-005 解析のテスト。 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_STOCK_WORDS } from "../src/config.js";
import { cleanText, findNextUrl, normalizeStock, parseItems, parsePrice } from "../src/parser.js";

test("価格の取り出し（TC-005-01）", () => {
  const cases: [string | null, number | null][] = [
    ["¥1,280", 1280], ["￥980", 980], ["1,280円（税込）", 1280], ["税込 ３９８円", 398],
    ["価格: 2個で 310円", 310], ["550", 550], ["価格未定", null], ["", null], [null, null],
  ];
  for (const [text, expected] of cases) assert.equal(parsePrice(text), expected, String(text));
});

test("在庫の正規化（TC-005-02）", () => {
  const cases: [string | null, string][] = [
    ["在庫あり", "in_stock"], ["残りわずか", "low_stock"], ["在庫切れ", "out_of_stock"],
    ["売り切れ（入荷未定）", "out_of_stock"], ["お問い合わせください", "unknown"], [null, "unknown"],
  ];
  for (const [text, expected] of cases) assert.equal(normalizeStock(text, DEFAULT_STOCK_WORDS), expected, String(text));
});

test("一覧の項目と次ページの URL（TC-005-03）", () => {
  const html = `<ul><li class="c" data-product-id="X1"><a class="l" href="/p/X1"><span class="n"> ノート\n A5 </span></a>
    <span class="p">¥1,000</span></li><li class="c" data-product-id="X2"><span class="n">ペン</span></li></ul>
    <a class="next" href="?page=2">次へ</a>`;
  const rows = parseItems(html, "http://shop.example.com/list", "li.c", {
    product_id: { attr: "data-product-id", type: "text" }, name: { selector: ".n", type: "text" },
    price: { selector: ".p", type: "price" }, url: { selector: "a.l", attr: "href", type: "url" },
  }, DEFAULT_STOCK_WORDS);
  assert.deepEqual(rows[0], { product_id: "X1", name: "ノート A5", price: 1000, url: "http://shop.example.com/p/X1" });
  assert.equal(rows[1].price, null);
  assert.equal(rows[1].url, null);
  assert.equal(findNextUrl(html, "http://shop.example.com/list", "a.next"), "http://shop.example.com/list?page=2");
  assert.equal(findNextUrl(html, "http://shop.example.com/list", "a.none"), null);
});

test("長すぎる文字列は 200 文字で切る", () => {
  assert.equal(cleanText("あ".repeat(500))?.length, 200);
  assert.equal(cleanText("   "), null);
});

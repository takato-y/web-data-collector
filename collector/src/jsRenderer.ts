/** JavaScript で描画されるページの取得（FN-006）。Playwright が入っている場合だけ使える。 */

// 収集に不要な読み込みは止め、対象サイトへの負荷を減らす
const BLOCKED_RESOURCE_TYPES = new Set(["image", "media", "font", "stylesheet"]);

/** Playwright またはブラウザ本体が無い。 */
export class JsUnavailable extends Error {}

export type Renderer = (url: string, userAgent: string, waitFor: string | undefined, timeoutSec: number) => Promise<string>;

/** ページを開き、waitFor の要素が現れるまで待ってから HTML を返す。 */
export const renderWithPlaywright: Renderer = async (url, userAgent, waitFor, timeoutSec) => {
  // ブラウザ本体は collector/node_modules の中に入れる運用（npm run install-browser）
  process.env.PLAYWRIGHT_BROWSERS_PATH ??= "0";
  let chromium: typeof import("playwright").chromium;
  try {
    ({ chromium } = await import("playwright"));
  } catch {
    throw new JsUnavailable("Playwright が導入されていません（collector で npm install を実行）");
  }
  const host = new URL(url).host;
  const timeout = timeoutSec * 1000;
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
  } catch (e) {
    if (String(e).includes("Executable doesn't exist")) {
      throw new JsUnavailable("ブラウザ本体がありません（collector で npm run install-browser を実行）");
    }
    throw e;
  }
  try {
    const page = await browser.newPage({ userAgent });
    await page.route("**/*", (route) => {
      const req = route.request();
      // 同じホスト以外への通信と、画像などの不要な読み込みは行わない
      if (new URL(req.url()).host !== host || BLOCKED_RESOURCE_TYPES.has(req.resourceType())) return route.abort();
      return route.continue();
    });
    await page.goto(url, { timeout, waitUntil: "domcontentloaded" });
    if (waitFor) await page.waitForSelector(waitFor, { timeout });
    return await page.content();
  } finally {
    await browser.close();
  }
};

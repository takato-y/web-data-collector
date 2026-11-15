/** ページ取得: 名乗り・タイムアウト・間隔を広げる再試行（FN-004）。 */
import type { RequestConfig } from "./config.js";
import { log } from "./log.js";
import { RateLimiter, realSleep, type Sleep } from "./politeness.js";

export const RETRYABLE_STATUS = new Set([429, 500, 502, 503, 504]);

/** 取得に失敗した（再試行しても回復しなかった、または再試行しない誤り）。 */
export class FetchError extends Error {
  constructor(public url: string, public reason: string, public status: number | null = null) {
    super(`${reason}: ${url}`);
  }
}

export interface FetchResult {
  status: number;
  url: string;
  text: string;
}

/** Retry-After（秒数の形式のみ対応）を読む。読めなければ null。 */
export function retryAfterSeconds(value: string | null): number | null {
  if (!value) return null;
  const n = Number(value);
  return Number.isFinite(n) ? Math.max(0, n) : null;
}

/** Content-Type または meta charset から文字コードを決めて復号する（Shift_JIS のページにも対応）。 */
export function decodeBody(buf: ArrayBuffer, contentType: string | null): string {
  let charset = /charset=["']?([\w-]+)/i.exec(contentType ?? "")?.[1];
  if (!charset) {
    const head = new TextDecoder("latin1").decode(buf.slice(0, 2048));
    charset = /<meta[^>]+charset=["']?([\w-]+)/i.exec(head)?.[1];
  }
  try {
    return new TextDecoder(charset ?? "utf-8").decode(buf);
  } catch {
    return new TextDecoder("utf-8").decode(buf); // 知らない文字コード名は UTF-8 として読む
  }
}

export interface FetcherOptions {
  limiter?: RateLimiter;
  sleep?: Sleep;
  fetchImpl?: typeof fetch;
}

export class Fetcher {
  readonly limiter: RateLimiter;
  private sleep: Sleep;
  private fetchImpl: typeof fetch;
  requestCount = 0; // 実際に送った要求の数（再試行を含む）

  constructor(private req: RequestConfig, readonly userAgent: string, opts: FetcherOptions = {}) {
    this.limiter = opts.limiter ?? new RateLimiter();
    this.sleep = opts.sleep ?? realSleep;
    this.fetchImpl = opts.fetchImpl ?? fetch;
  }

  backoff(attempt: number, retryAfter: number | null): number {
    const wait = retryAfter ?? this.req.backoffBaseSec * 2 ** attempt;
    return Math.min(wait, this.req.maxRetryAfterSec);
  }

  /** URL を取得する。混雑・一時的な誤り・通信エラーは再試行し、それ以外の 4xx は即座に失敗とする。 */
  async get(url: string, intervalSec?: number): Promise<FetchResult> {
    const host = new URL(url).host;
    const interval = intervalSec ?? this.req.intervalSec;
    let lastReason = "";
    let lastStatus: number | null = null;
    for (let attempt = 0; attempt <= this.req.maxRetries; attempt++) {
      await this.limiter.wait(host, interval);
      this.requestCount++;
      let retryAfter: number | null = null;
      try {
        const res = await this.fetchImpl(url, {
          headers: { "User-Agent": this.userAgent, "Accept-Language": "ja,en;q=0.5" },
          redirect: "follow",
          signal: AbortSignal.timeout(this.req.timeoutSec * 1000), // 本文の受信まで含めて打ち切る
        });
        if (RETRYABLE_STATUS.has(res.status)) {
          lastReason = `一時的な誤り (HTTP ${res.status})`;
          lastStatus = res.status;
          retryAfter = retryAfterSeconds(res.headers.get("Retry-After"));
          await res.body?.cancel();
        } else if (res.status >= 400) {
          await res.body?.cancel();
          throw new FetchError(url, `HTTP ${res.status}`, res.status);
        } else {
          const finalHost = new URL(res.url || url).host;
          if (finalHost !== host) {
            await res.body?.cancel();
            throw new FetchError(url, `別のホストへ転送されました (${finalHost})`);
          }
          const text = decodeBody(await res.arrayBuffer(), res.headers.get("Content-Type"));
          return { status: res.status, url: res.url || url, text };
        }
      } catch (e) {
        if (e instanceof FetchError) throw e;
        const err = e as Error & { cause?: { code?: string } };
        lastStatus = null;
        lastReason = err.name === "TimeoutError" ? "タイムアウト" : `接続できません (${err.cause?.code ?? err.name})`;
      }
      if (attempt >= this.req.maxRetries) break;
      const wait = this.backoff(attempt, retryAfter);
      log.warn(`${lastReason}。${wait.toFixed(1)} 秒後に再試行します (${attempt + 1}/${this.req.maxRetries}): ${url}`);
      await this.sleep(wait);
    }
    throw new FetchError(url, `再試行しても取得できません（${lastReason}）`, lastStatus);
  }

  /** robots.txt を取得する。4xx（再試行後の 429 を含む）は status をそのまま、取得できなければ null か 5xx を返す。 */
  fetchRobots = async (robotsUrl: string): Promise<{ status: number | null; body: string }> => {
    try {
      const res = await this.get(robotsUrl);
      return { status: res.status, body: res.text };
    } catch (e) {
      if (e instanceof FetchError) return { status: e.status, body: "" };
      throw e;
    }
  };
}

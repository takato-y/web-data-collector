/**
 * 対象サイトへの配慮: robots.txt の確認（FN-002）とアクセス間隔の制御（FN-003）。
 * 判断に迷う場合は「取得しない」側に倒す（ADR-0003）。
 */
import { createRequire } from "node:module";

/** robots-parser の判定結果（同梱の型定義は ESM から既定の関数として呼べないため、必要な部分だけ書く）。 */
interface Robot {
  isAllowed(url: string, ua?: string): boolean | undefined;
  getCrawlDelay(ua?: string): number | undefined;
}
const robotsParser = createRequire(import.meta.url)("robots-parser") as (url: string, body: string) => Robot;
import { log } from "./log.js";

export type Clock = () => number; // 秒
export type Sleep = (sec: number) => Promise<void>;

export const realClock: Clock = () => performance.now() / 1000;
export const realSleep: Sleep = (sec) => new Promise((r) => setTimeout(r, sec * 1000));

/** 同じホストへの要求の間隔を保つ。時計と sleep は差し替え可能（テスト用）。 */
export class RateLimiter {
  private last = new Map<string, number>();
  private queue: Promise<unknown> = Promise.resolve();

  constructor(private clock: Clock = realClock, private sleep: Sleep = realSleep) {}

  /** 必要な分だけ待ってから戻る。待った秒数を返す。呼び出しは順番に処理する。 */
  wait(host: string, intervalSec: number): Promise<number> {
    const run = async () => {
      const now = this.clock();
      const prev = this.last.get(host);
      let waited = 0;
      if (prev !== undefined) {
        const remaining = intervalSec - (now - prev);
        if (remaining > 0) {
          await this.sleep(remaining);
          waited = remaining;
        }
      }
      this.last.set(host, this.clock());
      return waited;
    };
    const p = this.queue.then(run, run);
    this.queue = p.catch(() => undefined);
    return p;
  }
}

/** robots.txt を取得する関数の型。通信エラーで応答が無いときは status に null を返す。 */
export type RobotsFetch = (url: string) => Promise<{ status: number | null; body: string }>;

type RobotsState = "ok" | "missing" | "unavailable";
interface RobotsRule {
  state: RobotsState;
  robots?: Robot;
}

/** ホストごとに robots.txt を 1 回だけ取得し、取得可否と待ち時間を答える。 */
export class RobotsPolicy {
  private cache = new Map<string, Promise<RobotsRule>>();
  private agentToken: string;

  constructor(private fetchRobots: RobotsFetch, userAgent: string) {
    // robots.txt の User-agent 行と照合する名前（「WebDataCollector/1.0 (...)」の「WebDataCollector」）
    this.agentToken = userAgent.split("/")[0];
  }

  private rule(url: string): Promise<RobotsRule> {
    const origin = new URL(url).origin;
    let p = this.cache.get(origin);
    if (!p) {
      p = this.load(`${origin}/robots.txt`);
      this.cache.set(origin, p);
    }
    return p;
  }

  private async load(robotsUrl: string): Promise<RobotsRule> {
    const { status, body } = await this.fetchRobots(robotsUrl);
    if (status === null || status >= 500) {
      log.warn(`robots.txt を取得できないため、このサイトの収集を見送ります: ${robotsUrl} (status=${status})`);
      return { state: "unavailable" };
    }
    if (status >= 400) {
      log.info(`robots.txt がありません（制限なしとして扱います）: ${robotsUrl} (status=${status})`);
      return { state: "missing" };
    }
    log.info(`robots.txt を確認しました: ${robotsUrl}`);
    return { state: "ok", robots: robotsParser(robotsUrl, body) };
  }

  async allowed(url: string): Promise<boolean> {
    const r = await this.rule(url);
    if (r.state === "missing") return true;
    if (r.state === "unavailable" || !r.robots) return false;
    return r.robots.isAllowed(url, this.agentToken) === true; // 判定できない（undefined）場合も取得しない
  }

  async isUnavailable(url: string): Promise<boolean> {
    return (await this.rule(url)).state === "unavailable";
  }

  /** 設定の間隔と Crawl-delay の長い方を返す。 */
  async intervalFor(url: string, configuredSec: number): Promise<number> {
    const r = await this.rule(url);
    const delay = r.robots?.getCrawlDelay(this.agentToken);
    return Math.max(configuredSec, typeof delay === "number" ? delay : 0);
  }
}

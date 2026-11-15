/**
 * 履歴の保存（FN-007）。収集部は collection_runs・products・price_snapshots に書き込む。
 * 列ごとの書き込み担当は基本設計書 2.2 のとおりで、is_listed・analyzed_at・change_events は分析部が書く。
 */
import Database from "better-sqlite3";
import { mkdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { CollectResult } from "./models.js";

// collector/dist/src/storage.js からリポジトリ直下の sql/schema.sql を探す
const HERE = dirname(fileURLToPath(import.meta.url));
export const SCHEMA_PATH = resolve(HERE, "..", "..", "..", "sql", "schema.sql");

export function nowIso(d: Date = new Date()): string {
  // 分析部（Python の datetime.fromisoformat）と同じ形式: 2026-11-15T09:00:00+09:00
  const p = (n: number) => String(Math.trunc(Math.abs(n))).padStart(2, "0");
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}` +
    `${sign}${p(off / 60)}:${p(off % 60)}`;
}

export class Storage {
  readonly db: Database.Database;

  constructor(path: string, schemaPath: string = SCHEMA_PATH) {
    mkdirSync(dirname(path), { recursive: true });
    this.db = new Database(path);
    this.db.pragma("foreign_keys = ON");
    this.db.exec(readFileSync(schemaPath, "utf-8"));
  }

  close(): void {
    this.db.close();
  }

  startRun(target: string, startedAt: string = nowIso()): number {
    const info = this.db.prepare("INSERT INTO collection_runs (target_name, started_at) VALUES (?, ?)").run(target, startedAt);
    return Number(info.lastInsertRowid);
  }

  /** 収集結果を 1 つのトランザクションで保存する。途中で失敗したら、この実行の書き込みはすべて取り消す。 */
  saveResult(runId: number, result: CollectResult, at: string = nowIso()): void {
    const upsert = this.db.prepare(`
      INSERT INTO products (target_name, product_id, name, category, url, first_seen_run_id, last_seen_run_id)
      VALUES (@target, @productId, @name, @category, @url, @runId, @runId)
      ON CONFLICT (target_name, product_id) DO UPDATE SET
        name = COALESCE(excluded.name, products.name),
        category = COALESCE(excluded.category, products.category),
        url = COALESCE(excluded.url, products.url),
        last_seen_run_id = excluded.last_seen_run_id`);
    const snap = this.db.prepare(`
      INSERT INTO price_snapshots (run_id, target_name, product_id, price, stock, collected_at)
      VALUES (?, ?, ?, ?, ?, ?)`);
    const finish = this.db.prepare(`
      UPDATE collection_runs SET finished_at = ?, status = ?, pages_fetched = ?, items_collected = ?,
             error_count = ?, message = ? WHERE run_id = ?`);
    const tx = this.db.transaction(() => {
      if (result.status === "success" || result.status === "partial") {
        for (const it of result.items) {
          upsert.run({ target: result.target, productId: it.productId, name: it.name, category: it.category, url: it.url, runId });
          snap.run(runId, result.target, it.productId, it.price, it.stock, at);
        }
      }
      finish.run(nowIso(), result.status, result.pagesFetched, result.items.length, result.errorCount, result.message, runId);
    });
    tx();
  }
}

-- 履歴DB（SQLite）の定義。収集部（collector/src/storage.ts）と分析部（webcollector/storage.py）の受け渡し口。
-- 両方の部が起動時に実行する（CREATE ... IF NOT EXISTS のため何度実行してもよい）。
-- 論理名・項目の説明は docs/04_テーブル定義書.md を参照。

PRAGMA foreign_keys = ON;

-- 収集実行
CREATE TABLE IF NOT EXISTS collection_runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_name     TEXT    NOT NULL,
    started_at      TEXT    NOT NULL,
    finished_at     TEXT,
    status          TEXT    NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running', 'success', 'partial', 'failed', 'skipped')),
    pages_fetched   INTEGER NOT NULL DEFAULT 0,
    items_collected INTEGER NOT NULL DEFAULT 0,
    error_count     INTEGER NOT NULL DEFAULT 0,
    message         TEXT,
    analyzed_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_target ON collection_runs (target_name, status, run_id);

-- 商品
CREATE TABLE IF NOT EXISTS products (
    target_name       TEXT    NOT NULL,
    product_id        TEXT    NOT NULL,
    name              TEXT,
    category          TEXT,
    url               TEXT,
    first_seen_run_id INTEGER NOT NULL REFERENCES collection_runs (run_id),
    last_seen_run_id  INTEGER NOT NULL REFERENCES collection_runs (run_id),
    is_listed         INTEGER NOT NULL DEFAULT 1 CHECK (is_listed IN (0, 1)),
    PRIMARY KEY (target_name, product_id)
);

-- 価格・在庫のスナップショット（実行ごとに追記し、上書きしない）
CREATE TABLE IF NOT EXISTS price_snapshots (
    run_id       INTEGER NOT NULL REFERENCES collection_runs (run_id),
    target_name  TEXT    NOT NULL,
    product_id   TEXT    NOT NULL,
    price        INTEGER CHECK (price IS NULL OR price >= 0),
    stock        TEXT    CHECK (stock IS NULL OR stock IN ('in_stock', 'low_stock', 'out_of_stock', 'unknown')),
    collected_at TEXT    NOT NULL,
    PRIMARY KEY (run_id, product_id),
    FOREIGN KEY (target_name, product_id) REFERENCES products (target_name, product_id)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_product ON price_snapshots (target_name, product_id, run_id);

-- 変更（差分検出の結果と通知の状態）
CREATE TABLE IF NOT EXISTS change_events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES collection_runs (run_id),
    target_name TEXT    NOT NULL,
    product_id  TEXT    NOT NULL,
    event_type  TEXT    NOT NULL
                CHECK (event_type IN ('price_down', 'price_up', 'out_of_stock', 'restock', 'new', 'delisted')),
    old_value   TEXT,
    new_value   TEXT,
    price_diff  INTEGER,
    detected_at TEXT    NOT NULL,
    notified_at TEXT,
    FOREIGN KEY (target_name, product_id) REFERENCES products (target_name, product_id)
);
CREATE INDEX IF NOT EXISTS idx_events_unnotified ON change_events (notified_at, event_id);

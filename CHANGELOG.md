# 変更履歴

この文書の書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に、版の付け方は [セマンティック バージョニング](https://semver.org/lang/ja/) に従います。

## [1.0.0] - 2026-11-15

### 追加

- 収集部（TypeScript / Node.js）: robots.txt の確認、Crawl-delay を含む取得の間隔制御、Retry-After と倍々の待ち時間による再試行、タイムアウト、一覧のページ送りと詳細の取得、Shift_JIS のページの復号、Playwright による JavaScript ページの取得、履歴DB（SQLite）への保存
- 分析部（Python）: 未分析の実行の差分検出（値下げ・値上げ・在庫切れ・再入荷・新商品・掲載終了）、Excel レポート（サマリー・変更一覧の色分け・最新一覧・価格推移グラフ）、数式の無害化、Webhook 通知（Slack・Discord・Teams・汎用の形式、呼び出しの無効化、失敗時は次回に再送）
- 定期実行: cron 用 `scripts/run.sh`、タスクスケジューラ用 `scripts/run.ps1`、`scripts/cron.example`
- 架空のデモショップ（Flask）と Webhook の受信用モック、両言語をまたぐ通し試験 `scripts/e2e.sh`
- 設計書一式（要件定義・基本設計・詳細設計・テーブル定義・テスト仕様・導入運用手順・ADR 4 件）

### 変更

- 開発の途中で、すべて Python で作っていた収集処理を TypeScript の収集部に置き換え、Python は分析・帳票・通知に専念する構成にした（ADR-0004）

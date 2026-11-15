"""架空のデモショップ。

収集ツールの動作確認だけを目的とした、手元で動く小さな Web ショップ。
- 商品一覧（ページ送りあり）・商品詳細・robots.txt・JavaScript で描画するページを持つ
- 商品データは JSON ファイルから毎回読み直すため、ファイルを差し替えると
  「価格が変わった」「在庫が切れた」状態を作れる
- 127.0.0.1 でのみ待ち受ける（外部から接続させない）
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import threading
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request

PAGE_SIZE = 5
DEFAULT_DATA = Path(__file__).parent / "data" / "day1.json"

ROBOTS_TXT = """User-agent: *
Disallow: /admin/
Disallow: /cart
Crawl-delay: 1
"""

access_log = logging.getLogger("demo_site.access")


def create_app(data_path: Path | str = DEFAULT_DATA, fail_first: int = 0) -> Flask:
    """アプリを作る。

    fail_first: 起動直後の n 回のページ要求に 503 を返す（再試行の確認用）。
    """
    app = Flask(__name__)
    app.config["DATA_PATH"] = Path(data_path)
    state = {"remaining_failures": fail_first}
    lock = threading.Lock()

    def load() -> dict:
        with open(app.config["DATA_PATH"], encoding="utf-8") as f:
            return json.load(f)

    @app.before_request
    def maybe_fail():
        # robots.txt は常に返し、それ以外の要求を指定回数だけ失敗させる
        if request.path == "/robots.txt":
            return None
        with lock:
            if state["remaining_failures"] > 0:
                state["remaining_failures"] -= 1
                return ("一時的に混み合っています", 503, {"Retry-After": "1"})
        return None

    @app.after_request
    def log_access(response):
        access_log.info(
            "%s %s %s UA=%s", request.method, request.full_path.rstrip("?"),
            response.status_code, request.headers.get("User-Agent", "-"),
        )
        return response

    @app.get("/robots.txt")
    def robots():
        return ROBOTS_TXT, 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/products")
    def product_list():
        products = load()["products"]
        pages = max(1, math.ceil(len(products) / PAGE_SIZE))
        page = request.args.get("page", default=1, type=int)
        if page < 1 or page > pages:
            abort(404)
        items = products[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        return render_template("list.html", items=items, page=page, pages=pages)

    @app.get("/products/<product_id>")
    def product_detail(product_id: str):
        for p in load()["products"]:
            if p["id"] == product_id:
                return render_template("detail.html", p=p)
        abort(404)

    @app.get("/new-arrivals")
    def new_arrivals():
        # 商品は含めず、ブラウザ上の JavaScript が /api/new-arrivals から描画する
        return render_template("new_arrivals.html")

    @app.get("/api/new-arrivals")
    def api_new_arrivals():
        return jsonify(load().get("new_arrivals", []))

    @app.get("/admin/")
    def admin():
        return "管理画面（robots.txt で収集を禁止している場所）", 200

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="架空のデモショップを起動する")
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="商品データの JSON")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--fail-first", type=int, default=0,
                        help="起動直後の n 回の要求に 503 を返す（再試行の確認用）")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app = create_app(args.data, args.fail_first)
    # 外部から接続させないため 127.0.0.1 に固定する
    app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()

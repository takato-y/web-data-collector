"""通知の受け口の代わりになる、手元だけで動く受信用モック。

受け取った JSON を 1 件ずつファイルに保存し、内容を画面に表示する。
127.0.0.1 でのみ待ち受ける。実在のチャットサービスには一切接続しない。
"""
from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def make_handler(out_dir: Path, fail_first: int = 0):
    state = {"count": 0, "fail": fail_first}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            with lock:
                if state["fail"] > 0:
                    state["fail"] -= 1
                    self.send_response(500)
                    self.end_headers()
                    return
                state["count"] += 1
                n = state["count"]
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self.send_response(400)
                self.end_headers()
                return
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"received_{n:03d}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"--- 受信 {n} 件目 ({self.path}) ---")
            print(data.get("text") or data.get("content") or json.dumps(data, ensure_ascii=False))
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    return Handler


def start(out_dir: Path, port: int = 0, fail_first: int = 0) -> ThreadingHTTPServer:
    """テスト用: 別スレッドで起動して server を返す（server.server_port でポートが分かる）。"""
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(out_dir, fail_first))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Webhook の受信用モック（127.0.0.1 のみ）")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--out", default="mock_webhook_received")
    parser.add_argument("--fail-first", type=int, default=0, help="最初の n 回に 500 を返す")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(Path(args.out), args.fail_first))
    print(f"受信用モックを起動しました: http://127.0.0.1:{args.port}/hook")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

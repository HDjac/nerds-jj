#!/usr/bin/env python3
"""Local, read-only React preview for Release 2D.1.

This process binds to 127.0.0.1 only. It serves a staged production React
build with synthetic /api/tasks responses and deliberately never connects
to VNC, the study database, or the Submit service. It is a visual preview,
NOT a participant session or end-to-end instrumentation test.
"""
import argparse
import json
from http import cookies
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

PREVIEW_JS = """
<script>
/* R2D.1 local preview ONLY: prevent real VNC or network sessions. */
(function () {
  class InertPreviewWebSocket {
    constructor() {
      this.readyState = 0;
      this.binaryType = "arraybuffer";
      this.bufferedAmount = 0;
      this.protocol = "";
    }
    addEventListener() {}
    removeEventListener() {}
    send() {}
    close() {}
  }
  InertPreviewWebSocket.CONNECTING = 0;
  InertPreviewWebSocket.OPEN = 1;
  InertPreviewWebSocket.CLOSING = 2;
  InertPreviewWebSocket.CLOSED = 3;
  window.WebSocket = InertPreviewWebSocket;
  window.__NERDS_VISUAL_PREVIEW_ONLY__ = true;
})();
</script>
<style>
#nerds-preview-banner {
  position: fixed; right: 12px; bottom: 10px; z-index: 20000;
  background: #fff4bf; color: #262626;
  border: 1px solid #8b7100; border-radius: 5px;
  font: 12px/1.35 sans-serif; padding: 5px 8px;
  pointer-events: none;
}
</style>
"""
PREVIEW_BANNER = (
    '<div id="nerds-preview-banner" aria-label="Read only UI preview">'
    'READ-ONLY UI PREVIEW — No CLI / Firefox / telemetry</div>'
)


def make_handler(assets, descriptions):
    class PreviewHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(assets), **kwargs)

        def do_GET(self):
            target = urlsplit(self.path)
            if target.path == "/select":
                params = parse_qs(target.query)
                order = params.get("order", ["dense_first"])[0]
                position = params.get("position", ["1"])[0]
                if order not in ("dense_first", "lowyield_first") or position not in ("1", "2"):
                    return self.send_json({"error": "Invalid preview assignment"}, 400)
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", f"nerds_r2d1_preview={order}:{position}; Path=/; SameSite=Strict; HttpOnly; Max-Age=3600")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if target.path == "/api/tasks":
                choice = "dense_first:1"
                try:
                    cookie = cookies.SimpleCookie()
                    cookie.load(self.headers.get("Cookie", ""))
                    item = cookie.get("nerds_r2d1_preview")
                    if item:
                        choice = item.value
                except cookies.CookieError:
                    pass
                if choice not in ("dense_first:1", "dense_first:2", "lowyield_first:1", "lowyield_first:2"):
                    choice = "dense_first:1"
                order, position = choice.split(":")
                pos = int(position)
                code = (
                    ("dense_v2", "lowyield_v1") if order == "dense_first"
                    else ("lowyield_v1", "dense_v2")
                )[pos - 1]
                return self.send_json({
                    "mode": "pilot1",
                    "pending_outcome": None,
                    "completion_receipt": None,
                    "tasks": [{
                        "task_no": pos,
                        "position": pos,
                        "task_code": code,
                        "title": f"Task {pos}",
                        "desc": descriptions[code][position],
                    }],
                })
            if target.path in ("/", "/index.html"):
                html = (assets / "index.html").read_text(encoding="utf-8")
                if "<head>" not in html or "</body>" not in html:
                    return self.send_json({"error": "Unexpected React index.html"}, 500)
                html = html.replace("<head>", "<head>" + PREVIEW_JS, 1)
                html = html.replace("</body>", PREVIEW_BANNER + "</body>", 1)
                data = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            if target.path.startswith("/api/") or target.path.startswith("/log-"):
                return self.send_json({"error": "Preview is read-only; collection is disabled"}, 403)
            return super().do_GET()

        def do_POST(self):
            # No request-body reads: no copy, clipboard, AI, or task text saved.
            return self.send_json({"error": "Preview is read-only; submissions are disabled"}, 403)

        def do_PUT(self):
            return self.do_POST()

        def do_DELETE(self):
            return self.do_POST()

        def send_json(self, obj, status=200):
            data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            # Log only HTTP metadata; requests cannot reach study services.
            super().log_message(format, *args)

    return PreviewHandler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--descriptions", type=Path, required=True)
    parser.add_argument("--port", type=int, default=19081)
    args = parser.parse_args()
    if not (args.assets / "index.html").is_file():
        parser.error("Missing built React index.html")
    descriptions = json.loads(args.descriptions.read_text(encoding="utf-8"))
    for code in ("dense_v2", "lowyield_v1"):
        for position in ("1", "2"):
            assert descriptions[code][position].startswith("<h2>Task "), (code, position)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.assets, descriptions))
    print(f"R2D.1 read-only React visual preview: http://127.0.0.1:{args.port}", flush=True)
    for order in ("dense_first", "lowyield_first"):
        for position in (1, 2):
            print(f"  http://127.0.0.1:{args.port}/select?order={order}&position={position}", flush=True)
    print("Remote desktop, Submit, task outcomes, and collection are disabled. Ctrl+C to close.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Local dev server with hot reload. No dependencies.

Usage: ./dev.py [port]   (default 8000)

Serves the repo root, injects a tiny client into HTML responses, and pushes a
reload over Server-Sent Events when any file changes. CSS-only changes swap
the stylesheet in place without a full page reload.
"""
import os
import sys
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
IGNORE = {".git", ".github", "__pycache__"}
EVENTS_PATH = "/__reload"

CLIENT = b"""<script>
new EventSource("/__reload").onmessage = (e) => {
  if (e.data === "css") {
    document.querySelectorAll('link[rel="stylesheet"]').forEach((l) => {
      const u = new URL(l.href);
      u.searchParams.set("_", Date.now());
      l.href = u;
    });
  } else {
    location.reload();
  }
};
</script>"""


def snapshot():
    state = {}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in IGNORE]
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                state[path] = os.stat(path).st_mtime_ns
            except OSError:
                pass
    return state


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        if not self.path.startswith(EVENTS_PATH):
            super().log_message(fmt, *args)

    def do_GET(self):
        if self.path.startswith(EVENTS_PATH):
            return self.stream_events()
        path = self.translate_path(self.path.split("?")[0])
        if os.path.isdir(path):
            path = os.path.join(path, "index.html")
        if path.endswith(".html") and os.path.isfile(path):
            with open(path, "rb") as f:
                body = f.read()
            i = body.lower().rfind(b"</body>")
            body = body[:i] + CLIENT + body[i:] if i != -1 else body + CLIENT
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def stream_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        last = snapshot()
        try:
            while True:
                time.sleep(0.3)
                now = snapshot()
                if now != last:
                    changed = {p for p in now if now[p] != last.get(p)} | (last.keys() - now.keys())
                    kind = "css" if all(p.endswith(".css") for p in changed) else "full"
                    self.wfile.write(f"data: {kind}\n\n".encode())
                    self.wfile.flush()
                    last = now
                else:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=ROOT))
    print(f"Serving on http://localhost:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

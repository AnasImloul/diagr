"""Live preview for `diagr watch --serve`: a local server for the output folder and a page script that reloads
on each rebuild, keeping the scenario, frame and scroll position."""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION_PATH = "/__diagr/version"

SCRIPT = """<script>(function () {
  var key = "diagr-live:" + location.pathname, seen = null;
  try {
    var s = JSON.parse(sessionStorage.getItem(key) || "null");
    sessionStorage.removeItem(key);
    if (s && window.diagr) {
      if (s.scenario) diagr.scenario(s.scenario);
      diagr.seek(Math.min(s.frame, diagr.frames));
      if (s.looping) diagr.play();
    }
    if (s) window.scrollTo(0, s.y);
  } catch (e) {}
  function save() {
    var s = { y: window.scrollY };
    if (window.diagr) { s.scenario = diagr.scenario(); s.frame = diagr.frame(); s.looping = diagr.looping(); }
    try { sessionStorage.setItem(key, JSON.stringify(s)); } catch (e) {}
  }
  function poll() {
    fetch("__VERSION__", { cache: "no-store" }).then(function (r) { return r.text(); }).then(function (v) {
      if (seen === null) seen = v;
      else if (v !== seen) { save(); location.reload(); }
    }).catch(function () {}).then(function () { setTimeout(poll, 500); });
  }
  poll();
})();</script>""".replace("__VERSION__", VERSION_PATH)


class _Handler(SimpleHTTPRequestHandler):
    version_ref: list[int] = [0]

    def _local(self) -> bool:
        """Whether the request names this machine. A page elsewhere can point a name of its own at 127.0.0.1 (DNS
        rebinding); its requests carry that name, and must not read the folder."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        return host in ("127.0.0.1", "localhost")

    def do_HEAD(self):
        if not self._local():
            self.send_error(403)
            return
        super().do_HEAD()

    def do_GET(self):
        if not self._local():
            self.send_error(403)
            return
        if self.path.split("?")[0] == VERSION_PATH:
            body = str(self.version_ref[0]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def list_directory(self, path):
        # Only the pages and images are served, not a listing of the folder.
        self.send_error(404)
        return None

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format, *args):
        pass


class LiveServer:
    """Serves a folder on localhost; bump() tells open pages to reload."""

    def __init__(self, folder: Path, port: int = 8001):
        folder.mkdir(parents=True, exist_ok=True)
        self.version = [0]
        handler = type("Handler", (_Handler,), {"version_ref": self.version})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), partial(handler, directory=str(folder)))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def bump(self) -> None:
        self.version[0] += 1

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

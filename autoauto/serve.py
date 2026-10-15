#!/usr/bin/env python3
"""Build and serve autoauto on a port isolated from the original UI."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent
THREE_BUNDLE = REPOSITORY / "tools" / "depgraph" / "viewer" / "three-bundle.js"

try:
    from .build import build
except ImportError:  # Direct execution: python3 autoauto/serve.py
    from build import build


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_GET(self) -> None:
        if self.path == "/healthz":
            payload = json.dumps({"ok": True, "ui": "autoauto", "scope": "issues-42-47"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/vendor/three-bundle.js":
            size = THREE_BUNDLE.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with THREE_BUNDLE.open("rb") as stream:
                self.copyfile(stream, self.wfile)
            return
        super().do_GET()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4514)
    arguments = parser.parse_args()
    build()
    handler = partial(Handler, directory=str(HERE))
    server = ThreadingHTTPServer((arguments.host, arguments.port), handler)
    print(f"autoauto ready at http://{arguments.host}:{arguments.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

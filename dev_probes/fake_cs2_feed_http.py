"""Plain-HTTP fake CS2 feed on http://127.0.0.1:3000/state (no TLS), with CORS +
Private Network Access + no-cache + POST. Used to test whether a SignalRGB
effect can read plain HTTP at all (if yes, we can drop the whole HTTPS/CA
machinery). Reuses the animated fake_state from fake_cs2_feed.

    python dev_probes/fake_cs2_feed_http.py
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_cs2_feed import fake_state


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _hdrs(self, body_len):
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(body_len))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        origin = self.headers.get("Origin", "*")
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")

    def _serve(self):
        body = json.dumps(fake_state()).encode("utf-8")
        self.send_response(200)
        self._hdrs(len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._serve()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n:
            try:
                self.rfile.read(n)
            except Exception:
                pass
        self._serve()

    def do_OPTIONS(self):
        self.send_response(204)
        self._hdrs(0)
        self.end_headers()


def main():
    httpd = ThreadingHTTPServer(("127.0.0.1", 3000), H)
    print("HTTP fake feed on http://127.0.0.1:3000/state (CORS + PNA + no-cache)")
    httpd.serve_forever()


if __name__ == "__main__":
    main()

"""Local web demo: python3 demo/server.py  ->  http://localhost:8765

GET  /                 index.html (text box + Chrome Web Speech mic, ko-KR)
GET  /api/translate?q= {"gloss": [...], "question": bool, "method", "score", "matched", "subtitle"}
POST /api/refine      {"q", "seq"} -> {"seq", "gloss", "question", "negation", "time", "fingerspell", "subtitle"} | {"seq", "error"|"skipped"}
"""
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from claude_refine import refine
from gloss_subtitle import load_lexicon, load_pairs, ngrams, subtitle, translate

PORT = 8765
HERE = os.path.dirname(os.path.abspath(__file__))
PAIRS = load_pairs()
VOCAB = load_lexicon(PAIRS)
INDEX = [ngrams(p["korean"]) for p in PAIRS]  # built once, not per request
LOG = os.path.join(HERE, "logs", "requests.jsonl")  # local only; holds recognized speech text


def log(entry):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.strftime("%H:%M:%S"), **entry}, ensure_ascii=False) + "\n")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            with open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if url.path == "/api/translate":
            q = parse_qs(url.query).get("q", [""])[0].strip()[:500]
            if not q:
                return self._send(400, json.dumps({"error": "q is required"}), "application/json")
            r = translate(q, PAIRS, VOCAB, INDEX)
            r["subtitle"] = subtitle(r)
            log({"q": q, **r})
            return self._send(200, json.dumps(r, ensure_ascii=False), "application/json; charset=utf-8")
        self._send(404, "not found", "text/plain")

    def do_POST(self):
        if urlparse(self.path).path != "/api/refine":
            return self._send(404, "not found", "text/plain")
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 10_000)))
            q, seq = str(body["q"]).strip()[:500], body.get("seq")
        except (ValueError, KeyError, TypeError):
            return self._send(400, json.dumps({"error": "bad request"}), "application/json")
        if not q:
            return self._send(400, json.dumps({"error": "q is required"}), "application/json")
        res, info = refine(q, PAIRS, INDEX)
        out = {"seq": seq, **info, **(res or {})}
        if res:
            out["subtitle"] = subtitle(res)
        log({"q": q, "refine": out})
        self._send(200, json.dumps(out, ensure_ascii=False), "application/json; charset=utf-8")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

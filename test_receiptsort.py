"""End-to-end test against a stub Ollama server (no model needed)."""
import json
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import receiptsort

# one canned answer per call, in order
ANSWERS = [
    {"vendor": "Figma", "date": "2026-09-03", "invoice_number": "INV-1", "currency": "usd",
     "subtotal": 12.0, "tax": 0, "total": 12.0, "category": "Software"},
    {"vendor": "Uber", "date": "2026-09-10", "invoice_number": "", "currency": "INR",
     "subtotal": 300, "tax": 15, "total": 400, "category": "Travel"},  # doesn't add up
    {"vendor": "", "date": "garbage", "invoice_number": "", "currency": "INR",
     "subtotal": None, "tax": None, "total": None, "category": "Bogus"},
    {"vendor": "Figma", "date": "2026-09-03", "invoice_number": "INV-1", "currency": "USD",
     "subtotal": 12.0, "tax": 0, "total": 12.0, "category": "Software"},  # duplicate
]
calls = []


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["messages"][0]["images"], "image missing"
        a = ANSWERS[len(calls)]
        calls.append(1)
        out = json.dumps({"message": {"content": json.dumps(a)}}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_pipeline():
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tmp = Path(tempfile.mkdtemp())
    inbox, out = tmp / "in", tmp / "out"
    inbox.mkdir()
    for i in range(4):
        (inbox / f"r{i}.png").write_bytes(b"\x89PNG fake" + bytes([i]))
    args = SimpleNamespace(inbox=str(inbox), out=str(out), model="x",
                           host=f"http://127.0.0.1:{srv.server_port}")
    assert receiptsort.run(args) == 0
    rows = receiptsort.read_ledger(out / "ledger.csv")
    assert len(rows) == 4
    assert rows[0]["filed_as"].startswith("2026-09/Software/2026-09-03_Figma_12.00")
    assert "totals don't add up" in rows[1]["needs_review"]
    assert rows[2]["category"] == "Other" and rows[2]["filed_as"].startswith("_needs_review")
    assert "possible duplicate" in rows[3]["needs_review"]
    # rerun is idempotent: no model calls
    n = len(calls)
    receiptsort.run(args)
    assert len(calls) == n
    shutil.rmtree(tmp)


if __name__ == "__main__":
    test_pipeline()
    print("ok")

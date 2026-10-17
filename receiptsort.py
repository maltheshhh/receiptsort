#!/usr/bin/env python3
"""receiptsort: local receipt/invoice sorter for freelancers.

Reads receipts (jpg/png/webp/pdf) with an open-weight vision model served by
Ollama, extracts vendor/date/total/tax/category, files copies into
OUT/YYYY-MM/Category/, and keeps a ledger.csv. Nothing leaves your machine.
"""
import argparse
import base64
import csv
import hashlib
import json
import re
import shutil
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

CATEGORIES = [
    "Software", "Hardware", "Travel", "Meals", "Office", "Marketing",
    "Professional Services", "Utilities", "Income", "Other",
]
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}
LEDGER_FIELDS = [
    "date", "vendor", "invoice_number", "currency", "subtotal", "tax",
    "total", "category", "needs_review", "filed_as", "source", "sha256",
]

SCHEMA = {
    "type": "object",
    "properties": {
        "vendor": {"type": "string"},
        "date": {"type": "string", "description": "YYYY-MM-DD"},
        "invoice_number": {"type": "string"},
        "currency": {"type": "string", "description": "ISO code, e.g. INR, USD"},
        "subtotal": {"type": ["number", "null"]},
        "tax": {"type": ["number", "null"]},
        "total": {"type": ["number", "null"]},
        "category": {"type": "string", "enum": CATEGORIES},
    },
    "required": ["vendor", "date", "total", "category"],
}

PROMPT = (
    "You are an accounting assistant. Read this receipt or invoice and return "
    "JSON with: vendor, date (YYYY-MM-DD), invoice_number (empty if none), "
    "currency (ISO code), subtotal, tax, total (numbers only), and category "
    f"from this list: {', '.join(CATEGORIES)}. Use null for numbers you cannot "
    "read. Do not guess."
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_image_b64(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise RuntimeError("PDF support needs: pip install pymupdf")
        with fitz.open(path) as doc:
            pix = doc[0].get_pixmap(dpi=150)
            return base64.b64encode(pix.tobytes("png")).decode()
    return base64.b64encode(path.read_bytes()).decode()


def ask_model(host: str, model: str, image_b64: str, timeout: int = 180) -> dict:
    body = json.dumps({
        "model": model,
        "stream": False,
        "format": SCHEMA,
        "options": {"temperature": 0},
        "messages": [{"role": "user", "content": PROMPT, "images": [image_b64]}],
    }).encode()
    req = urllib.request.Request(
        f"{host}/api/chat", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    return json.loads(data["message"]["content"])


def to_num(v):
    if v is None or v == "":
        return None
    try:
        return round(float(str(v).replace(",", "")), 2)
    except ValueError:
        return None


def clean(raw: dict) -> dict:
    review = []
    vendor = (raw.get("vendor") or "").strip()
    if not vendor:
        review.append("vendor")
    date = ""
    try:
        date = datetime.strptime((raw.get("date") or "").strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        review.append("date")
    total = to_num(raw.get("total"))
    subtotal, tax = to_num(raw.get("subtotal")), to_num(raw.get("tax"))
    if total is None:
        review.append("total")
    elif subtotal is not None and tax is not None and abs(subtotal + tax - total) > 0.02:
        review.append("totals don't add up")
    category = raw.get("category") if raw.get("category") in CATEGORIES else "Other"
    return {
        "date": date, "vendor": vendor,
        "invoice_number": (raw.get("invoice_number") or "").strip(),
        "currency": (raw.get("currency") or "").strip().upper(),
        "subtotal": subtotal, "tax": tax, "total": total,
        "category": category, "needs_review": "; ".join(review),
    }


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:40] or "unknown"


def file_copy(src: Path, out: Path, rec: dict) -> Path:
    if rec["needs_review"]:
        folder = out / "_needs_review"
    else:
        folder = out / rec["date"][:7] / rec["category"].replace(" ", "_")
    folder.mkdir(parents=True, exist_ok=True)
    total = f"{rec['total']:.2f}" if rec["total"] is not None else "NA"
    name = f"{rec['date'] or 'undated'}_{slug(rec['vendor'])}_{total}{src.suffix.lower()}"
    dest, i = folder / name, 1
    while dest.exists():
        dest = folder / f"{dest.stem.rsplit('_dup', 1)[0]}_dup{i}{src.suffix.lower()}"
        i += 1
    shutil.copy2(src, dest)
    return dest


def read_ledger(path: Path) -> list:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_ledger(path: Path, rows: list):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        w.writeheader()
        w.writerows(rows)


def run(args) -> int:
    inbox, out = Path(args.inbox), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ledger_path = out / "ledger.csv"
    rows = read_ledger(ledger_path)
    seen = {r["sha256"] for r in rows}
    files = sorted(p for p in inbox.rglob("*") if p.suffix.lower() in IMG_EXT | {".pdf"})
    new = errors = 0
    for p in files:
        digest = sha256(p)
        if digest in seen:
            continue
        try:
            raw = ask_model(args.host, args.model, load_image_b64(p))
        except Exception as e:  # keep going; one bad file shouldn't stop the batch
            print(f"  ! {p.name}: {e}", file=sys.stderr)
            errors += 1
            continue
        rec = clean(raw)
        # duplicate by content: same vendor + date + total from a different file
        if any(r["vendor"] == rec["vendor"] and r["date"] == rec["date"]
               and str(r["total"]) == str(rec["total"]) for r in rows) and rec["vendor"]:
            rec["needs_review"] = (rec["needs_review"] + "; possible duplicate").strip("; ")
        dest = file_copy(p, out, rec)
        rec.update(filed_as=str(dest.relative_to(out)), source=str(p), sha256=digest)
        rows.append(rec)
        seen.add(digest)
        new += 1
        flag = f"  [review: {rec['needs_review']}]" if rec["needs_review"] else ""
        print(f"  {p.name} -> {rec['vendor']} {rec['currency']} {rec['total']} ({rec['category']}){flag}")
    write_ledger(ledger_path, rows)

    totals = {}
    for r in rows:
        if r["total"] not in ("", "None", None):
            key = (r["category"], r["currency"])
            totals[key] = totals.get(key, 0) + float(r["total"])
    print(f"\n{new} new, {len(rows)} total, {errors} errors. Ledger: {ledger_path}")
    for (cat, cur), amt in sorted(totals.items()):
        print(f"  {cat:<24}{cur:<5}{amt:>12,.2f}")
    return 1 if errors and not new else 0


def main():
    ap = argparse.ArgumentParser(description="Sort receipts locally with an open-weight vision model.")
    ap.add_argument("inbox", help="folder of receipt images/PDFs")
    ap.add_argument("--out", default="sorted", help="output folder (default: sorted)")
    ap.add_argument("--model", default="qwen2.5vl:7b", help="any Ollama vision model")
    ap.add_argument("--host", default="http://localhost:11434")
    sys.exit(run(ap.parse_args()))


if __name__ == "__main__":
    main()

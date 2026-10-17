# receiptsort

Local receipt and invoice sorter for freelancers. An open-weight vision model reads each receipt on your own machine, files it by month and category, and keeps a ledger you can hand to your accountant. No cloud, no per-page fees, no client data leaving the laptop.

## Setup

```bash
# 1. Install Ollama (https://ollama.com) and pull an open vision model
ollama pull qwen2.5vl:7b

# 2. Optional, for PDF receipts
pip install pymupdf

# 3. Run
python3 receiptsort.py ~/Downloads/receipts --out ~/receipts-sorted
```

Output:

```
sorted/
  ledger.csv                  one row per receipt
  2026-09/Software/2026-09-03_Figma_12.00.png
  2026-09/Travel/...
  _needs_review/              unreadable fields, totals that don't add up
```

Originals are never moved or modified. Re-running skips files already in the ledger (SHA-256), so you can drop new receipts into the same folder every week.

## What it flags for review

- Missing vendor, date, or total
- Subtotal + tax that doesn't match total
- Same vendor, date, and total as an earlier receipt (possible duplicate)

## Swap the model

Any Ollama vision model works: `--model llama3.2-vision`, `--model minicpm-v`, or your own fine-tune. Edit `CATEGORIES` in `receiptsort.py` to match your chart of accounts.

## Test

```bash
python3 test_receiptsort.py   # runs against a stub Ollama server, no model needed
```

## Selling it

- One-time license or small monthly fee for freelancers and small studios who can't send client invoices to a cloud API.
- Setup service: install, tune categories to the client's books, export format for their accountant (Tally, Zoho, QuickBooks CSV).
- Cost to run is zero per receipt, so margins don't depend on volume.

## Post draft: why open mattered

Receipts and invoices carry client names, rates, and bank details. Freelancers are often under NDAs, and "upload it to a cloud API" is a non-starter for them. Running an open-weight vision model through Ollama keeps every file on the laptop and works offline.

It also fixes the economics. Closed vision APIs charge per page, so a tool priced for a freelancer's budget loses money at volume. Local inference costs nothing per receipt, so the price is just what the software is worth.

Because the model is swappable, I can try a newer one the week it ships, or fine-tune for a niche (local-language bills, GST invoices, restaurant suppliers) without waiting on a vendor. Structured JSON output through Ollama's schema constraint made a 7B model reliable enough, and the review flags catch the cases where it isn't.

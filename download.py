"""Download the 16 public syllabi listed in syllabi.csv into syllabi/ and verify their SHA-256.

The PDFs are not redistributed here (copyright belongs to their institutions).
If a file has changed or moved since 2026-10-25, the checksum will not match and results may differ.

  python download.py
"""
import csv
import hashlib
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
out = HERE / "syllabi"
out.mkdir(exist_ok=True)

ok = 0
with open(HERE / "syllabi.csv", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        dest = out / f"{row['id']}.pdf"
        try:
            req = urllib.request.Request(row["url"], headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=60).read()
        except Exception as e:
            print(f"[FAIL] {row['id']}: {e}")
            continue
        dest.write_bytes(data)
        match = hashlib.sha256(data).hexdigest() == row["sha256"]
        ok += match
        print(f"[{'OK' if match else 'CHANGED'}] {row['id']}")
print(f"\n{ok}/16 files match the benchmark version.")

# scripts/build_reports_index.py
import os
import re
import json
import glob
from pathlib import Path
from datetime import datetime

REPORT_DIR = Path("reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# --- Date parsing helpers ----------------------------------------------------

# Try to coerce a date-like string into YYYY-MM-DD
def normalize_date(s: str) -> str | None:
if not s:
return None
s = s.strip()

# 1) YYYY-MM-DD (or with slashes)
m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
if m:
y, mo, d = m.groups()
try:
return datetime(int(y), int(mo), int(d)).strftime("%Y-%m-%d")
except ValueError:
return None

# 2) YYYYMMDD
m = re.search(r"\b(\d{4})(\d{2})(\d{2})\b", s)
if m:
y, mo, d = m.groups()
try:
return datetime(int(y), int(mo), int(d)).strftime("%Y-%m-%d")
except ValueError:
return None

# 3) D Mon YYYY or Mon D, YYYY
# e.g., "27 Oct 2025" or "Oct 27, 2025"
m = re.search(
r"(?:(\d{1,2})\s+([A-Za-z]{3,})\s*,?\s*(\d{4}))|"
r"(([A-Za-z]{3,})\s+(\d{1,2}),?\s*(\d{4}))",
s,
)
months = {
"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
"jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12
}
if m:
if m.group(1) and m.group(2) and m.group(3):
# D Mon YYYY
d = int(m.group(1))
mo = months.get(m.group(2)[:3].lower())
y = int(m.group(3))
else:
# Mon D, YYYY
mo = months.get(m.group(5)[:3].lower())
d = int(m.group(6))
y = int(m.group(7))
if mo:
try:
return datetime(y, mo, d).strftime("%Y-%m-%d")
except ValueError:
return None

return None


def extract_date_from_meta(html_text: str) -> str | None:
# <meta name="report-date" content="YYYY-MM-DD">
m = re.search(
r'<meta[^>]+name=["\']report-date["\'][^>]*content=["\']([^"\']+)["\']',
html_text, flags=re.IGNORECASE,
)
if m:
return normalize_date(m.group(1))
return None


def extract_date_from_heading(html_text: str) -> str | None:
# e.g., <h2>Negative reviews for 2025-10-27</h2>
m = re.search(r"Negative\s+reviews\s+for\s+([^<\n]+)", html_text, flags=re.IGNORECASE)
if m:
return normalize_date(m.group(1))
return None


def extract_date_from_filename(name: str) -> str | None:
"""
Try a few filename patterns:
report_YYYY-MM-DD.html
YYYY-MM-DD.html
daily-YYYYMMDD.html
anything-YYYY-MM-DD-*.html
"""
base = Path(name).name

# report_YYYY-MM-DD.html or anyprefix_YYYY-MM-DD.html
m = re.search(r"(\d{4})-(\d{2})-(\d{2})", base)
if m:
y, mo, d = m.groups()
try:
return datetime(int(y), int(mo), int(d)).strftime("%Y-%m-%d")
except ValueError:
pass

# daily-YYYYMMDD.html or *YYYYMMDD*.html
m = re.search(r"\b(\d{4})(\d{2})(\d{2})\b", base)
if m:
y, mo, d = m.groups()
try:
return datetime(int(y), int(mo), int(d)).strftime("%Y-%m-%d")
except ValueError:
pass

# pure stem is a date (e.g., 2025-10-27.html)
stem = Path(base).stem
dt = normalize_date(stem)
if dt:
return dt

return None


# --- Build index -------------------------------------------------------------

def main() -> None:
# Find all HTML reports (support nested dirs), exclude index.html
html_paths = [
p for p in REPORT_DIR.rglob("*.html")
if p.name.lower() != "index.html"
]

items: list[dict] = []

for p in html_paths:
try:
text = p.read_text(encoding="utf-8", errors="ignore")
except Exception:
text = ""

# Priority 1: meta
date = extract_date_from_meta(text)

# Priority 2: filename patterns
if not date:
date = extract_date_from_filename(p.name)

# Priority 3: headings fallback
if not date and text:
date = extract_date_from_heading(text)

if not date:
# Skip files without any recognizable date
# (alternatively, you could log and continue including them).
# print(f"Skipping {p} (no date found)")
continue

rel_path = p.relative_to(Path(".")).as_posix()
# Ensure path starts with 'reports/' for your alerts page
if not rel_path.startswith("reports/"):
rel_path = f"reports/{p.name}"

items.append({
"date": date, # normalized YYYY-MM-DD
"path": rel_path # e.g., reports/report_2025-10-27.html
})

# Sort by *actual date* descending
def sort_key(obj):
try:
return datetime.strptime(obj["date"], "%Y-%m-%d")
except Exception:
return datetime.min

items.sort(key=sort_key, reverse=True)

out_path = REPORT_DIR / "index.json"
out_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"Wrote index with {len(items)} entries -> {out_path.as_posix()}")


if __name__ == "__main__":
main()

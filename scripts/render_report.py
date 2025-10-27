# scripts/render_report.py
import sys
import re
import argparse
import pathlib
from datetime import datetime

try:
import markdown # pip install markdown
except ImportError:
sys.stderr.write("Missing 'markdown' package. Add 'markdown' to requirements.txt\n")
sys.exit(1)


STYLE = """
<style>
body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin:0; padding:0; }
.main { max-width: 980px; margin: 24px auto; padding: 0 16px; }
table { border-collapse: collapse; width:100%; font-size: 14px; }
th, td { border: 1px solid #eee; padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: #fafafa; }
code, pre { background:#f6f7f9; border-radius:6px; padding:2px 4px; }
h1,h2,h3 { margin-top: 1.2em; }
.note { color:#555; font-size:12px; margin:6px 0; }
</style>
"""

HTML_WRAP = """<!doctype html>
<html><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
{meta}
{style}
</head><body>
<div class="main">
{body}
</div>
</body></html>
"""


# ---------------------- helpers ----------------------
def normalize_date(s: str) -> str | None:
"""Coerce many date formats into YYYY-MM-DD."""
if not s:
return None
s = s.strip()

# 1) YYYY-MM-DD (or YYYY/MM/DD)
m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
if m:
y, mo, d = map(int, m.groups())
try:
return datetime(y, mo, d).strftime("%Y-%m-%d")
except ValueError:
return None

# 2) YYYYMMDD
m = re.search(r"\b(\d{4})(\d{2})(\d{2})\b", s)
if m:
y, mo, d = map(int, m.groups())
try:
return datetime(y, mo, d).strftime("%Y-%m-%d")
except ValueError:
return None

# 3) "27 Oct 2025" OR "Oct 27, 2025"
m = re.search(
r"(?:(\d{1,2})\s+([A-Za-z]{3,})\s*,?\s*(\d{4}))|(([A-Za-z]{3,})\s+(\d{1,2}),?\s*(\d{4}))",
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

# 4) Fallback: already normalized token
m = re.search(r"\b\d{4}-\d{2}-\d{2}\b", s)
if m:
return m.group(0)

return None


def infer_date_from_filename(path: pathlib.Path) -> str | None:
return normalize_date(path.stem) or normalize_date(path.name)


def inject_meta_and_title(html_body: str, report_date: str | None) -> str:
title = "Daily Alert Report"
meta = ""
if report_date:
title = f"Daily Alert Report — {report_date}"
meta = f'<meta name="report-date" content="{report_date}"/>'
return HTML_WRAP.format(title=title, meta=meta, style=STYLE, body=html_body)


# ---- negative table filtering (within the rendered HTML string) ----
def _find_table_by_id(html: str, table_id: str) -> tuple[int, int] | None:
"""Return (start_idx, end_idx) of a table with a given id, or None."""
m = re.search(rf'<table[^>]*\bid=["\']{re.escape(table_id)}["\'][^>]*>', html, flags=re.IGNORECASE)
if not m:
return None
start = m.start()
# naive close finder
close = re.search(r"</table\s*>", html[m.end():], flags=re.IGNORECASE)
if not close:
return None
end = m.end() + close.end()
return (start, end)


def _find_table_after_heading(html: str, pattern: str = r"negative") -> tuple[int, int] | None:
"""Find first <table> after a heading that matches pattern (e.g., 'Negative')."""
h = re.search(rf"<h[1-6][^>]*>[^<]*{pattern}[^<]*</h[1-6]>", html, flags=re.IGNORECASE)
if not h:
return None
after = html[h.end():]
t = re.search(r"<table\b[^>]*>", after, flags=re.IGNORECASE)
if not t:
return None
start = h.end() + t.start()
rest = after[t.end():]
close = re.search(r"</table\s*>", rest, flags=re.IGNORECASE)
if not close:
return None
end = h.end() + t.end() + close.end()
return (start, end)


def _detect_date_col_idx(table_html: str) -> int:
"""Try to detect 'Date' column index; fallback to 0."""
# From thead
thead = re.search(r"<thead\b[^>]*>(.*?)</thead>", table_html, flags=re.IGNORECASE | re.DOTALL)
if thead:
headers = re.findall(r"<th[^>]*>(.*?)</th>", thead.group(1), flags=re.IGNORECASE | re.DOTALL)
headers_text = [re.sub("<.*?>", "", h).strip().lower() for h in headers]
for i, txt in enumerate(headers_text):
if "date" in txt:
return i
# From first row ths
first_tr = re.search(r"<tr\b[^>]*>(.*?)</tr>", table_html, flags=re.IGNORECASE | re.DOTALL)
if first_tr:
ths = re.findall(r"<th[^>]*>(.*?)</th>", first_tr.group(1), flags=re.IGNORECASE | re.DOTALL)
ths_text = [re.sub("<.*?>", "", h).strip().lower() for h in ths]
for i, txt in enumerate(ths_text):
if "date" in txt:
return i
return 0


def _filter_table_rows_by_date(table_html: str, target_date: str) -> tuple[str, int]:
"""
Keep only rows whose date cell (in detected date column) matches target_date.
Returns (new_table_html, kept_count).
"""
date_col = _detect_date_col_idx(table_html)

# Split table into head/body/tail
m_body = re.search(r"(<tbody\b[^>]*>)(.*?)(</tbody>)", table_html, flags=re.IGNORECASE | re.DOTALL)
if not m_body:
# fallback: operate on all <tr> after the first (header) row
rows = re.findall(r"(<tr\b[^>]*>.*?</tr>)", table_html, flags=re.IGNORECASE | re.DOTALL)
if not rows:
return (table_html, 0)
head = table_html
kept_rows = []
# naive: keep rows that match
for tr in rows[1:]:
cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, flags=re.IGNORECASE | re.DOTALL)
if not cells:
continue
date_txt = re.sub("<.*?>", "", cells[min(date_col, len(cells)-1)]).strip()
if normalize_date(date_txt) == target_date:
kept_rows.append(tr)
kept = len(kept_rows)
if kept_rows:
new_html = table_html.replace(rows[1], rows[1] + "".join(kept_rows)) # crude but avoids deep parsing
return (new_html, kept)
return (table_html, 0)

open_tb, body_html, close_tb = m_body.groups()
# Find each row
rows = re.findall(r"(<tr\b[^>]*>.*?</tr>)", body_html, flags=re.IGNORECASE | re.DOTALL)
kept_rows = []
for tr in rows:
cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, flags=re.IGNORECASE | re.DOTALL)
if not cells:
continue
date_txt = re.sub("<.*?>", "", cells[min(date_col, len(cells)-1)]).strip()
if normalize_date(date_txt) == target_date:
kept_rows.append(tr)

kept = len(kept_rows)
new_body = "".join(kept_rows) if kept_rows else ""
new_table = re.sub(
r"(<tbody\b[^>]*>)(.*?)(</tbody>)",
lambda _: f"{open_tb}{new_body}{close_tb}",
table_html,
flags=re.IGNORECASE | re.DOTALL
)
return (new_table, kept)


def filter_negative_section(html: str, report_date: str) -> str:
"""Find the Negative section table and filter rows to the report_date."""
# 1) Prefer an explicit id="negative-reviews" if present
loc = _find_table_by_id(html, "negative-reviews")
if not loc:
# 2) Else find first table after a heading containing 'Negative'
loc = _find_table_after_heading(html, pattern=r"negative")
if not loc:
return html # nothing to do

start, end = loc
before, table_html, after = html[:start], html[start:end], html[end:]

new_table, kept = _filter_table_rows_by_date(table_html, report_date)

# Add a small note before the table
note_html = f'<div class="note">Showing negative reviews for {report_date} ({kept} found)</div>'

return before + note_html + new_table + after


# ---------------------- main flow ----------------------
def render(md_path: pathlib.Path, out_path: pathlib.Path, report_date: str | None, filter_negatives: bool) -> None:
md_text = md_path.read_text(encoding="utf-8")
html_body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])

# Inject meta + title
doc = inject_meta_and_title(html_body, report_date)

# Filter negative table if requested and date is known
if filter_negatives and report_date:
doc = filter_negative_section(doc, report_date)

out_path.write_text(doc, encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
"""
Backward-compatible:
python scripts/render_report.py input.md output.html
Extended:
python scripts/render_report.py input.md output.html --date YYYY-MM-DD [--no-filter-negatives]
"""
# If exactly 2 positional args (old style), keep working without argparse flags.
if len(argv) == 3 and not argv[1].startswith("-") and not argv[2].startswith("-"):
ns = argparse.Namespace(input=argv[1], output=argv[2], date=None, filter_negatives=True)
return ns

p = argparse.ArgumentParser()
p.add_argument("input", help="Input markdown file")
p.add_argument("output", help="Output HTML file")
p.add_argument("--date", help="Report date (YYYY-MM-DD). If omitted, inferred from input filename when possible.")
p.add_argument("--no-filter-negatives", action="store_true", help="Disable filtering of the Negative Reviews table by date.")
args = p.parse_args(argv[1:])
args.filter_negatives = not args.no_filter_negatives
return args


def main(argv: list[str]) -> int:
args = parse_args(argv)

in_path = pathlib.Path(args.input)
out_path = pathlib.Path(args.output)

rep_date = normalize_date(args.date) if args.date else infer_date_from_filename(in_path)

render(in_path, out_path, rep_date, args.filter_negatives)
return 0


if __name__ == "__main__":
sys.exit(main(sys.argv))

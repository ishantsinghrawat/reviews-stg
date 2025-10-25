# scripts/build_reports_index.py
import os
import json
import glob

REPORT_DIR = "reports/"
os.makedirs(REPORT_DIR, exist_ok=True)

items = []
for p in glob.glob(os.path.join(REPORT_DIR, "*.html")):
    fn = os.path.basename(p)
    if fn.lower() == "index.html":
        continue
    date = fn[:-5]  # strip .html
    items.append({"date": date, "path": f"reports/{fn}"})

items.sort(key=lambda x: x["date"], reverse=True)

with open(os.path.join(REPORT_DIR, "index.json"), "w", encoding="utf-8") as f:
    json.dump(items, f, ensure_ascii=False, indent=2)

print(f"Wrote index with {len(items)} entries")

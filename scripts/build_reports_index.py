# scripts/build_reports_index.py
import os
import json
import glob

os.makedirs("docs/reports", exist_ok=True)

items = []
for p in glob.glob("docs/reports/*.md"):
    fn = os.path.basename(p)
    if fn.lower() == "index.md":
        continue
    date = fn[:-3]  # strip .md
    items.append({"date": date, "path": f"reports/{fn}"})

items.sort(key=lambda x: x["date"], reverse=True)

with open("docs/reports/index.json", "w", encoding="utf-8") as f:
    json.dump(items, f, ensure_ascii=False, indent=2)

print(f"Wrote index with {len(items)} entries")

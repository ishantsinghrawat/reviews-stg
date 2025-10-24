# scripts/compare_negatives.py
# -*- coding: utf-8 -*-

import argparse, json, os
from collections import defaultdict

SENTI_MAP = {
    "negative":"Negative","NEGATIVE":"Negative","LABEL_0":"Negative",
    "neutral":"Neutral","NEUTRAL":"Neutral","LABEL_1":"Neutral",
    "positive":"Positive","POSITIVE":"Positive","LABEL_2":"Positive"
}

def load_json(path):
    return json.load(open(path, "r", encoding="utf-8")) if os.path.exists(path) else []

def canon_sent(s):
    return SENTI_MAP.get(str(s), s or "")

def neg_counts(rows):
    """Count Negative reviews per category (keeps your original logic)."""
    by = defaultdict(int)
    for r in rows:
        cat = str(r.get("category","")).strip()
        if canon_sent(r.get("sentiment_std") or r.get("sentiment")) == "Negative":
            by[cat] += 1
    return dict(by)

def file_hash(path):
    if not os.path.exists(path): return ""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f: h.update(f.read())
    return h.hexdigest()

def examples(rows, category, max_n=5):
    """Your existing bullet samples (kept)."""
    out = []
    n = 0
    for r in rows:
        if str(r.get("category","")).strip()==category and canon_sent(r.get("sentiment_std") or r.get("sentiment"))=="Negative":
            txt = (r.get("review") or "").strip().replace("\n"," ")
            if txt:
                out.append(f"- {txt[:200]}{'…' if len(txt)>200 else ''}")
                n += 1
                if n >= max_n: break
    return "\n".join(out) or "_no sample_"

def _esc_md_cell(s):
    """Escape pipes/newlines for Markdown tables."""
    s = "" if s is None else str(s)
    return s.replace("\n"," ").replace("|","\\|").strip()

def append_details_table(path, rows, only_categories=None, max_rows=300):
    """
    Append a Markdown table with columns:
      Category | Review | App Version | Date
    - rows: list of dicts (new_data.json)
    - only_categories: optional set of categories to include (e.g., only those with increases)
    """
    # Filter to Negative
    neg = []
    for r in rows:
        if canon_sent(r.get("sentiment_std") or r.get("sentiment")) != "Negative":
            continue
        cat = str(r.get("category","")).strip()
        if only_categories and cat not in only_categories:
            continue
        review = (r.get("review") or "").replace("\r"," ").replace("\n"," ").strip()
        if len(review) > 200:
            review = review[:200] + "…"
        neg.append({
            "Category": cat or "Uncategorized",
            "Review": review,
            "App Version": str(r.get("app_version") or "Unknown"),
            "Date": str(r.get("review_date") or ""), 
            "Source": str(r.get("source") or "Unknown"),
        })

    with open(path, "a", encoding="utf-8") as f:
        f.write("\n\n---\n\n### Negative Review Details (latest run)\n\n")
        if not neg:
            f.write("_(no negative rows to display)_\n")
            return
        # Build Markdown table manually (no extra deps)
        cols = ["Category","Review","App Version","Date"]
        f.write("| " + " | ".join(cols) + " |\n")
        f.write("| " + " | ".join(["---"]*len(cols)) + " |\n")
        for i, row in enumerate(neg):
            if i >= max_rows: break
            f.write("| " + " | ".join(_esc_md_cell(row[c]) for c in cols) + " |\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--threshold-abs", type=int, default=3)
    ap.add_argument("--threshold-rel", type=float, default=0.2)
    args = ap.parse_args()

    cur = load_json(args.current)
    new = load_json(args.new)

    # "updated" = file content changed at all (baseline heuristic)
    updated = (file_hash(args.current) != file_hash(args.new))

    cur_neg = neg_counts(cur)
    new_neg = neg_counts(new)

    cats = sorted(set(cur_neg) | set(new_neg))
    increases = []
    for c in cats:
        a = cur_neg.get(c,0); b = new_neg.get(c,0)
        delta = b - a
        rel = (delta / a) if a>0 else (1.0 if b>0 else 0.0)
        if delta>0 and (delta >= args.threshold_abs or rel >= args.threshold_rel):
            increases.append((c, a, b, delta, rel))

    alert = bool(increases)

    # ---- Write the report (summary + samples) ----
    with open(args.report, "w", encoding="utf-8") as f:
        f.write(f"# Negative Sentiment Delta Report\n\n")
        f.write(f"- Updated file content: **{'yes' if updated else 'no'}**\n")
        f.write(f"- Alert conditions: abs ≥ {args.threshold_abs} or rel ≥ {int(args.threshold_rel*100)}%\n\n")

        if not increases:
            f.write("No categories exceeded thresholds.\n")
        else:
            f.write("| Category | Neg (old) | Neg (new) | Δ | Δ% |\n|---|---:|---:|---:|---:|\n")
            for (c, a, b, d, r) in increases:
                f.write(f"| {c or '_uncategorized_'} | {a} | {b} | +{d} | {round(r*100,1)}% |\n")
            f.write("\n")
            for (c, a, b, d, r) in increases:
                f.write(f"### {c or '_uncategorized_'} — new negative samples\n")
                f.write(examples(new, c, 5) + "\n\n")

    # ---- Append the detailed table (Category, Review, App Version, Date) ----
    incr_cats = {c for (c, *_rest) in increases} if increases else None  # pass None to include none if no increases
    append_details_table(args.report, new, only_categories=incr_cats)

    # ---- Emit step outputs for GitHub Actions ----
    print(f"updated={str(updated).lower()}")
    print(f"alert={str(alert).lower()}")
    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as fh:
            fh.write(f"updated={str(updated).lower()}\n")
            fh.write(f"alert={str(alert).lower()}\n")

if __name__ == "__main__":
    main()

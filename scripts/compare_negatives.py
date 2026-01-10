# scripts/compare_negatives.py
# -*- coding: utf-8 -*-

import argparse
import json
import os
from collections import defaultdict

SENTI_MAP = {
    "negative": "Negative", "NEGATIVE": "Negative", "LABEL_0": "Negative",
    "neutral": "Neutral", "NEUTRAL": "Neutral", "LABEL_1": "Neutral",
    "positive": "Positive", "POSITIVE": "Positive", "LABEL_2": "Positive"
}

def load_json(path):
    return json.load(open(path, "r", encoding="utf-8")) if os.path.exists(path) else []

def canon_sent(s):
    return SENTI_MAP.get(str(s), s or "")

def is_negative(r):
    return canon_sent(r.get("sentiment_std") or r.get("sentiment")) == "Negative"

def norm_source(s):
    """Normalize to two buckets so reporting is crystal clear."""
    s = (s or "").strip().lower()
    if "app store" in s or ("app" in s and "store" in s):
        return "App Store"
    if "google" in s or "play" in s:
        return "Google Play"
    return (s or "Unknown").title()

def get_window_negatives(rows):
    """new_data_1d.json is already LAST_DAYS=1, so include all negatives in this window."""
    return [r for r in rows if is_negative(r)]

def _esc_md_cell(s):
    s = "" if s is None else str(s)
    return s.replace("\n", " ").replace("\r", " ").replace("|", "\\|").strip()

def append_details_table(path, rows, max_rows=300):
    neg = []
    for r in rows:
        if not is_negative(r):
            continue

        review = (r.get("review") or "").replace("\r", " ").replace("\n", " ").strip()
        if len(review) > 800:
            review = review[:800] + "…"

        neg.append({
            "Category": str(r.get("category", "")).strip() or "Uncategorized",
            "Review": review,
            "App Version": str(r.get("app_version") or "Unknown"),
            "Date": str(r.get("review_date") or ""),
            "Source": norm_source(r.get("source")),
        })

    with open(path, "a", encoding="utf-8") as f:
        f.write("\n\n---\n\n### Negative Review Details (last 1-day window)\n\n")
        if not neg:
            f.write("_(no negative rows in the last 1-day window)_\n")
            return

        cols = ["Category", "Review", "App Version", "Date", "Source"]
        f.write("| " + " | ".join(cols) + " |\n")
        f.write("| " + " | ".join(["---"] * len(cols)) + " |\n")

        for i, row in enumerate(neg):
            if i >= max_rows:
                break
            f.write("| " + " | ".join(_esc_md_cell(row[c]) for c in cols) + " |\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", required=True, help="Previous baseline (data_1d.json) (kept for compatibility)")
    ap.add_argument("--new", required=True, help="Newly scraped data (new_data_1d.json)")
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    new = load_json(args.new)

    # Counts for proof/debug
    total_by_source = defaultdict(int)
    for r in new:
        total_by_source[norm_source(r.get("source"))] += 1

    negatives = get_window_negatives(new)
    neg_by_source = defaultdict(int)
    for r in negatives:
        neg_by_source[norm_source(r.get("source"))] += 1

    alert = len(negatives) > 0
    updated = alert

    with open(args.report, "w", encoding="utf-8") as f:
        f.write("# Negative Sentiment Daily Report\n\n")
        f.write(f"- Total reviews in last 1-day window: **{len(new)}**\n")
        f.write(f"- Negative reviews in last 1-day window: **{len(negatives)}**\n")
        f.write(f"- Alert triggered: **{'yes' if alert else 'no'}**\n\n")

        f.write("## Total reviews by Source (last 1-day window)\n\n")
        for k in sorted(total_by_source.keys()):
            f.write(f"- {k}: **{total_by_source[k]}**\n")
        f.write("\n")

        f.write("## Negative reviews by Source (last 1-day window)\n\n")
        if not negatives:
            f.write("- _(none)_\n\n")
        else:
            for k in sorted(neg_by_source.keys()):
                f.write(f"- {k}: **{neg_by_source[k]}**\n")
            f.write("\n")

    append_details_table(args.report, negatives)

    print(f"updated={str(updated).lower()}")
    print(f"alert={str(alert).lower()}")

    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"updated={str(updated).lower()}\n")
            fh.write(f"alert={str(alert).lower()}\n")

if __name__ == "__main__":
    main()

# scripts/compare_negatives.py
# -*- coding: utf-8 -*-

import argparse
import json
import os
import hashlib

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

def _norm_text(s, limit=800):
    s = "" if s is None else str(s)
    s = s.replace("\r", " ").replace("\n", " ").strip()
    return s[:limit]

def review_uid(r):
    """
    Stable ID for dedupe.
    - Google Play: review_id exists
    - App Store: hash of stable fields
    """
    rid = (r.get("review_id") or "").strip()
    if rid:
        return f"gp:{rid}"

    sig = "|".join([
        (r.get("source") or ""),
        (r.get("user_name") or ""),
        (r.get("review_title") or ""),
        str(r.get("rating") or ""),
        str(r.get("review_date") or ""),
        (r.get("app_version") or ""),
        _norm_text(r.get("review") or "", limit=400),
    ])
    return "hash:" + hashlib.sha256(sig.encode("utf-8")).hexdigest()

def _esc_md_cell(s):
    s = "" if s is None else str(s)
    return s.replace("\n", " ").replace("\r", " ").replace("|", "\\|").strip()

def write_details_table(path, rows, max_rows=300):
    # rows are already filtered to negatives, but keep it safe
    neg = [r for r in rows if is_negative(r)]

    with open(path, "a", encoding="utf-8") as f:
        if not neg:
            f.write("_(No new negative reviews since yesterday.)_\n")
            return

        cols = ["Category", "Review", "App Version", "Date", "Rating", "Source"]
        f.write("| " + " | ".join(cols) + " |\n")
        f.write("| " + " | ".join(["---"] * len(cols)) + " |\n")

        for i, r in enumerate(neg):
            if i >= max_rows:
                break
            row = {
                "Category": str(r.get("category", "")).strip() or "Uncategorized",
                "Review": _norm_text(r.get("review") or "", limit=800),
                "App Version": str(r.get("app_version") or "Unknown"),
                "Date": str(r.get("review_date") or ""),
                "Rating": str(r.get("rating") or ""),
                "Source": str(r.get("source") or "Unknown"),
            }
            f.write("| " + " | ".join(_esc_md_cell(row[c]) for c in cols) + " |\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", required=True, help="Previous baseline (data_1d.json)")
    ap.add_argument("--new", required=True, help="Newly scraped data (new_data_1d.json)")
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    cur = load_json(args.current)
    new = load_json(args.new)

    cur_ids = {review_uid(r) for r in cur}
    new_only = [r for r in new if review_uid(r) not in cur_ids]
    new_negatives = [r for r in new_only if is_negative(r)]

    alert = len(new_negatives) > 0
    updated = alert

    # Minimal report (no extra sections)
    with open(args.report, "w", encoding="utf-8") as f:
        f.write("# Negative Sentiment Daily Report\n\n")
        f.write(f"- New negative reviews since yesterday: **{len(new_negatives)}**\n")
        f.write(f"- Alert triggered: **{'yes' if alert else 'no'}**\n\n")
        f.write("### New Negative Review Details\n\n")

    write_details_table(args.report, new_negatives)

    # GitHub Action outputs
    print(f"updated={str(updated).lower()}")
    print(f"alert={str(alert).lower()}")

    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"updated={str(updated).lower()}\n")
            fh.write(f"alert={str(alert).lower()}\n")

if __name__ == "__main__":
    main()

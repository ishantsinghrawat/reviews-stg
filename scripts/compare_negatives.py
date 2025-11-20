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


def latest_review_date(rows):
    dates = [str(r.get("review_date")) for r in rows if r.get("review_date")]
    return max(dates) if dates else None


def get_today_negative_reviews(rows):
    latest = latest_review_date(rows)
    if not latest:
        return []
    out = []
    for r in rows:
        if str(r.get("review_date")) == latest and \
           canon_sent(r.get("sentiment_std") or r.get("sentiment")) == "Negative":
            out.append(r)
    return out


def _esc_md_cell(s):
    s = "" if s is None else str(s)
    return s.replace("\n", " ").replace("|", "\\|").strip()


def append_details_table(path, rows, max_rows=300):
    neg = []
    for r in rows:
        review = (r.get("review") or "").replace("\r", " ").replace("\n", " ").strip()
        if len(review) > 800:
            review = review[:800] + "…"
        neg.append({
            "Category": str(r.get("category", "")).strip() or "Uncategorized",
            "Review": review,
            "App Version": str(r.get("app_version") or "Unknown"),
            "Date": str(r.get("review_date") or ""),
            "Source": str(r.get("source") or "Unknown"),
        })

    with open(path, "a", encoding="utf-8") as f:
        f.write("\n\n---\n\n### Negative Review Details (today)\n\n")
        if not neg:
            f.write("_(no negative rows today)_\n")
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
    ap.add_argument("--current", required=True, help="Previous baseline (data_1d.json)")
    ap.add_argument("--new", required=True, help="Newly scraped data (new_data_1d.json)")
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    new = load_json(args.new)

    # ------------------------------------------------------
    # NEW ALERT LOGIC: alert = did today produce ≥1 negatives?
    # ------------------------------------------------------
    today_negatives = get_today_negative_reviews(new)
    alert = len(today_negatives) > 0
    updated = alert  # Updated = yes when new negative reviews exist today

    # ---- Write summary report ----
    with open(args.report, "w", encoding="utf-8") as f:
        f.write("# Negative Sentiment Daily Report\n\n")
        f.write(f"- New negative reviews today: **{len(today_negatives)}**\n")
        f.write(f"- Alert triggered: **{'yes' if alert else 'no'}**\n\n")

        if not alert:
            f.write("No negative reviews were posted today.\n")
        else:
            f.write("Negative reviews were detected today.\n")

    # ---- Append today's negative reviews table ----
    append_details_table(args.report, today_negatives)

    # ---- GitHub Action Outputs ----
    print(f"updated={str(updated).lower()}")
    print(f"alert={str(alert).lower()}")

    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as fh:
            fh.write(f"updated={str(updated).lower()}\n")
            fh.write(f"alert={str(alert).lower()}\n")


if __name__ == "__main__":
    main()


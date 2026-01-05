# scripts/compare_negatives.py
# -*- coding: utf-8 -*-

import argparse
import json
import os
from collections import Counter

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
    """Negative = sentiment == Negative. (Sentiment is computed in build_reviews_json.py)"""
    return canon_sent(r.get("sentiment_std") or r.get("sentiment")) == "Negative"


def normalize_source(s):
    """Normalize store/source values for consistent reporting."""
    s = (s or "").strip()
    if not s:
        return "Unknown"
    s_low = s.lower()
    if "app" in s_low and "store" in s_low:
        return "App Store"
    if "google" in s_low or "play" in s_low:
        return "Google Play"
    return s


def _esc_md_cell(s):
    s = "" if s is None else str(s)
    return s.replace("\n", " ").replace("\r", " ").replace("|", "\\|").strip()


def append_details_table(path, rows, max_rows=300):
    """
    Append a Markdown table of negative reviews in the provided rows.
    Rows should ideally already be filtered to negatives, but we re-check is_negative() for safety.
    """
    neg = []
    for r in rows:
        if not is_negative(r):
            continue

        review = (r.get("review") or "").replace("\r", " ").replace("\n", " ").strip()
        if len(review) > 800:
            review = review[:800] + "…"

        neg.append({
            "Category": str(r.get("category", "")).strip() or "Uncategorized",
            "Review": review or "_(empty)_",
            "App Version": str(r.get("app_version") or "Unknown"),
            "Date": str(r.get("review_date") or ""),
            "Source": normalize_source(r.get("source")),
        })

    with open(path, "a", encoding="utf-8") as f:
        f.write("\n\n---\n\n### Negative Review Details (last 1 day window)\n\n")
        if not neg:
            f.write("_(no negative rows in the last 1 day window)_\n")
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
    ap.add_argument("--current", required=False, help="Previous baseline (data_1d.json) (unused in daily-negative mode)")
    ap.add_argument("--new", required=True, help="Newly scraped data (new_data_1d.json)")
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    new = load_json(args.new)

    # ------------------------------------------------------
    # DAILY ALERT LOGIC:
    # Dataset is already LAST_DAYS=1 in workflow,
    # so "today" = the last 1 day window. Show ALL negatives in that window.
    # ------------------------------------------------------
    negatives = [r for r in new if is_negative(r)]
    alert = len(negatives) > 0
    updated = alert  # Updated = yes when new negative reviews exist in last 1 day window

    # quick breakdowns (useful for debugging visibility)
    sources = [normalize_source(r.get("source")) for r in negatives]
    by_source = Counter(sources)

    # ---- Write summary report ----
    with open(args.report, "w", encoding="utf-8") as f:
        f.write("# Negative Sentiment Daily Report\n\n")
        f.write(f"- Negative reviews in last 1 day window: **{len(negatives)}**\n")
        f.write(f"- Alert triggered: **{'yes' if alert else 'no'}**\n\n")

        if negatives:
            f.write("## Breakdown by Source\n\n")
            for src, cnt in by_source.most_common():
                f.write(f"- {src}: **{cnt}**\n")
            f.write("\n")

            # Optional: show latest review_date values we saw (helps validate RSS lag)
            dates = sorted({str(r.get("review_date")) for r in negatives if r.get("review_date")})
            if dates:
                f.write("## Dates Seen (negative reviews)\n\n")
                f.write(f"- Min date: **{dates[0]}**\n")
                f.write(f"- Max date: **{dates[-1]}**\n\n")
        else:
            f.write("No negative reviews were found in the last 1 day window.\n")

    # ---- Append negatives table ----
    append_details_table(args.report, negatives)

    # ---- GitHub Action Outputs ----
    print(f"updated={str(updated).lower()}")
    print(f"alert={str(alert).lower()}")

    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"updated={str(updated).lower()}\n")
            fh.write(f"alert={str(alert).lower()}\n")


if __name__ == "__main__":
    main()

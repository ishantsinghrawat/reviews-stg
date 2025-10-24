# scripts/compare_negatives.py
import argparse
import pandas as pd

SENTI_NEG = "Negative"

def load(df_path):
    df = pd.read_json(df_path)
    for c in ["category", "sentiment_std", "source", "app_version"]:
        if c not in df.columns:
            df[c] = None
    # normalize a bit
    df["source"] = df["source"].fillna("Unknown")
    df["category"] = df["category"].fillna("Uncategorized")
    df["app_version"] = df["app_version"].fillna("Unknown")
    return df

def neg_counts_by_keys(df):
    mask = df["sentiment_std"].eq(SENTI_NEG)
    grp = (
        df[mask]
        .groupby(["source", "app_version", "category"])
        .size()
        .reset_index(name="neg_count")
    )
    return grp

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--report", default="delta_report.md")
    ap.add_argument("--threshold-abs", type=int, default=3)
    ap.add_argument("--threshold-rel", type=float, default=0.2)
    args = ap.parse_args()

    cur = load(args.current)
    new = load(args.new)

    cur_neg = neg_counts_by_keys(cur).set_index(["source", "app_version", "category"])
    new_neg = neg_counts_by_keys(new).set_index(["source", "app_version", "category"])

    all_idx = sorted(set(cur_neg.index).union(set(new_neg.index)))
    rows = []
    for key in all_idx:
        prev = int(cur_neg.loc[key, "neg_count"]) if key in cur_neg.index else 0
        nxt = int(new_neg.loc[key, "neg_count"]) if key in new_neg.index else 0
        abs_delta = nxt - prev
        rel_delta = (abs_delta / prev) if prev > 0 else (1.0 if abs_delta > 0 else 0.0)
        rows.append({
            "source": key[0],
            "app_version": key[1],
            "category": key[2],
            "prev": prev,
            "curr": nxt,
            "abs_delta": abs_delta,
            "rel_delta": rel_delta,
        })
    delta = pd.DataFrame(rows)

    increases = delta[
        (delta["abs_delta"] >= args.threshold_abs) |
        (delta["rel_delta"] >= args.threshold_rel)
    ]
    alert = not increases.empty

    # Write Markdown report
    with open(args.report, "w", encoding="utf-8") as f:
        f.write("# Negative sentiment changes (by Store, Version, Category)\n\n")
        if increases.empty:
            f.write("_No significant increases detected_\n")
        else:
            for (src, ver), grp in increases.sort_values(
                ["source", "app_version", "abs_delta"], ascending=[True, True, False]
            ).groupby(["source", "app_version"]):
                f.write(f"## {src} — v{ver}\n\n")
                for _, r in grp.iterrows():
                    f.write(
                        f"- **{r['category']}**: {r['prev']} → {r['curr']} "
                        f"(Δ {r['abs_delta']:+}, {r['rel_delta']:.0%})\n"
                    )
                f.write("\n")

        # Optional: full snapshot (debug)
        f.write("\n---\n\n### Full snapshot (debug)\n\n")
        if len(delta):
            f.write(delta.sort_values(["source", "app_version", "category"]).to_string(index=False))
            f.write("\n")

    # outputs for GH Actions
    print(f"alert={'true' if alert else 'false'}")
    updated = (
        new_neg.reset_index().sort_values(["source","app_version","category"]).values.tolist()
        != cur_neg.reset_index().sort_values(["source","app_version","category"]).values.tolist()
    )
    print(f"updated={'true' if updated else 'false'}")

if __name__ == "__main__":
    main()

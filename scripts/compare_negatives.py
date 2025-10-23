import argparse, pandas as pd, sys

SENTI_MAP = {
"negative": "Negative", "NEGATIVE": "Negative", "LABEL_0": "Negative",
"neutral": "Neutral", "NEUTRAL": "Neutral", "LABEL_1": "Neutral",
"positive": "Positive", "POSITIVE": "Positive", "LABEL_2": "Positive",
}

def load(df_path):
  df = pd.read_json(df_path)
  # normalize columns we rely on
  for c in ["category", "sentiment_std", "source"]:
  if c not in df.columns:
  df[c] = None
  # map sentiment if raw labels slipped through
  df["sentiment_std"] = df["sentiment_std"].map(SENTI_MAP).fillna(df["sentiment_std"])
  # fill missing source for safety
  df["source"] = df["source"].fillna("Unknown")
  df["category"] = df["category"].fillna("Uncategorized")
  return df

def neg_counts_by_source_category(df):
  mask = df["sentiment_std"].eq("Negative")
  grp = df[mask].groupby(["source","category"]).size().reset_index(name="neg_count")
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
  
  cur_neg = neg_counts_by_source_category(cur).set_index(["source","category"])
  new_neg = neg_counts_by_source_category(new).set_index(["source","category"])
  
  # join, compute delta
  all_idx = sorted(set(cur_neg.index).union(set(new_neg.index)))
  rows = []
  for sc in all_idx:
    prev = int(cur_neg.loc[sc, "neg_count"]) if sc in cur_neg.index else 0
    nxt = int(new_neg.loc[sc, "neg_count"]) if sc in new_neg.index else 0
    abs_delta = nxt - prev
    rel_delta = (abs_delta / prev) if prev > 0 else (1.0 if abs_delta > 0 else 0.0)
    rows.append({"source": sc[0], "category": sc[1],
    "prev": prev, "curr": nxt,
    "abs_delta": abs_delta, "rel_delta": rel_delta})
    delta = pd.DataFrame(rows)

# flag increases
  increases = delta[(delta["abs_delta"] >= args.threshold_abs) |
  (delta["rel_delta"] >= args.threshold_rel)]
  alert = not increases.empty
  
  # write report grouped by store
  with open(args.report, "w", encoding="utf-8") as f:
  f.write("# Negative sentiment changes by Store and Category\n\n")
  if increases.empty:
  f.write("_No significant increases detected_\n")
  else:
  for store, grp in increases.sort_values(["source","abs_delta"], ascending=[True, False]).groupby("source"):
  f.write(f"## {store}\n\n")
  for _, r in grp.iterrows():
  f.write(f"- **{r['category']}**: {r['prev']} → {r['curr']} "
  f"(Δ {r['abs_delta']:+}, {r['rel_delta']:.0%} relative)\n")
  f.write("\n")

# Optional: summary table for all (debugging)
  f.write("\n---\n\n### Full snapshot (debug)\n\n")
  if len(delta):
  f.write(delta.sort_values(["source","category"]).to_string(index=False))
  f.write("\n")
  
  # expose outputs to GH Actions
  # updated means the dataset changed at all (size or values) — cheap heuristic: hash neg table
  updated = (new_neg.reset_index().sort_values(["source","category"]).values.tolist()
  != cur_neg.reset_index().sort_values(["source","category"]).values.tolist())
  
  # print outputs for Actions (GITHUB_OUTPUT)
  out = []
  out.append(f"alert={'true' if alert else 'false'}")
  out.append(f"updated={'true' if updated else 'false'}")
  sys.stdout.write("\n".join([f"{x}" for x in out]))
  sys.stdout.flush()

if __name__ == "__main__":
main()

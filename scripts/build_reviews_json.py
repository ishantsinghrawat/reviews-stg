  # scripts/build_reviews_json.py
import os, sys, json, argparse, datetime as dt
import pandas as pd
import numpy as np
import requests
import time

# data source
from google_play_scraper import reviews_all, Sort

# nlp
from transformers import pipeline

# --------------------------
# Config & helpers
# --------------------------
SENTI_MAP = {
    "negative": "Negative", "NEGATIVE": "Negative", "LABEL_0": "Negative",
    "neutral":  "Neutral",  "NEUTRAL":  "Neutral",  "LABEL_1": "Neutral",
    "positive": "Positive", "POSITIVE": "Positive", "LABEL_2": "Positive",
}

DEFAULT_LABELS = [
    "Authentication/Login", "Performance/Speed", "UI/UX",
    "Crashes/Bugs", "Payments", "Rewards/Offers",
    "Feature Requests", "Customer Support", "Location/Geolocation",
    "Refunds", "Delivery"
]

def log(msg: str):
    print(msg, flush=True)

def parse_args():
    p = argparse.ArgumentParser(description="Fetch Google Play reviews → sentiment + zero-shot → JSON")
    p.add_argument("--package", default=os.getenv("GP_PACKAGE", "com.mcdonalds.superapp"))
    p.add_argument("--country", default=os.getenv("GP_COUNTRY", "ca"))
    p.add_argument("--lang", default=os.getenv("GP_LANG", "en"))
    p.add_argument("--min-date", default=os.getenv("MIN_DATE", ""))          # e.g., 2025-01-01
    p.add_argument("--only-version", default=os.getenv("ONLY_VERSION", ""))  # e.g., 9.105.3
    p.add_argument("--labels", default=os.getenv("ZS_LABELS", ",".join(DEFAULT_LABELS)))
    p.add_argument("--out-new", default="new_data.json")
    p.add_argument("--out-reviews", default="reviews.json")  # your static pages read this
    return p.parse_args()

# --------------------------
# Fetch Google Play reviews
# --------------------------
def fetch_google_play(package: str, lang: str, country: str) -> pd.DataFrame:
    log(f"[fetch] Google Play reviews for {package} ({lang}-{country}) …")
    rows = reviews_all(
        package,
        sleep_milliseconds=0,
        lang=lang,
        country=country,
        sort=Sort.NEWEST,
    )
    if not rows:
        return pd.DataFrame(columns=["review"])
    g_df = pd.DataFrame(np.array(rows), columns=["review"])
    df = g_df.join(pd.DataFrame(g_df.pop("review").tolist()))
    # drop unused & rename
    drop_cols = {"userImage", "reviewCreatedVersion"}
    df.drop(columns=[c for c in drop_cols if c in df.columns], inplace=True, errors="ignore")
    df.rename(
        columns={
            "score": "rating",
            "userName": "user_name",
            "reviewId": "review_id",
            "content": "review",
            "at": "review_date",
            "replyContent": "developer_response",
            "repliedAt": "developer_response_date",
            "thumbsUpCount": "thumbs_up",
            "appVersion": "app_version",
        },
        inplace=True,
    )
    # standard extras
    df.insert(loc=0, column="source", value="Google Play")
    df["language_code"] = lang
    df["country_code"] = country
    # dates
    if "review_date" in df.columns:
        df["review_date"] = pd.to_datetime(df["review_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return df
# --- Apple RSS fetcher (no external scraper packages needed) ---
def fetch_app_store_rss(app_id=375695000, country="ca", lang="en", max_pages=10, sleep=0.3):
  """
  Pulls the most recent ~500 reviews from Apple's public RSS feed.
  Returns a DataFrame with the project's schema and source='App Store'.
  """
  def rss_url(page):
    return (f"https://itunes.apple.com/rss/customerreviews/page={page}/id={app_id}"
    f"/sortby=mostrecent/json?l={lang}&cc={country}")
  rows = []
  for page in range(1, max_pages + 1):
    r = requests.get(rss_url(page), timeout=30)
    if r.status_code != 200:
      log(f"[appstore] HTTP {r.status_code} on page {page}; stopping.")
      break
    data = r.json()
    entries = data.get("feed", {}).get("entry", [])
    if not entries or len(entries) <= 1:
      break # only app metadata or no more reviews
    for e in entries[1:]:
      updated = e.get("updated", {}).get("label")
      rows.append({
          "source": "App Store",
          "review": (e.get("content", {}) or {}).get("label"),
          "rating": int((e.get("im:rating", {}) or {}).get("label", "0") or 0),
          "review_date": pd.to_datetime(updated, errors="coerce").strftime("%Y-%m-%d") if updated else None,
          "user_name": (e.get("author", {}) or {}).get("name", {}).get("label"),
          "review_title": (e.get("title", {}) or {}).get("label"),
          "app_version": (e.get("im:version", {}) or {}).get("label"),
          "developer_response": None,
          "country_code": country,
          "language_code": lang,
      })
    time.sleep(sleep)

  if not rows:
    return pd.DataFrame(columns=["review","rating","review_date","source"])
  df = pd.DataFrame(rows)
  df["review"] = df["review"].astype(str).str.strip()
  df = df[df["review"].str.len() > 0].reset_index(drop=True)
  return df
# --------------------------
# NLP
# --------------------------
def run_models(df: pd.DataFrame, labels: list[str]) -> pd.DataFrame:
    if df.empty:
        return df.assign(sentiment_std=None, sentiment_score=None, category=None, category_score=None)

    log("[nlp] loading pipelines (sentiment + zero-shot)…")
    senti_pipe = pipeline("sentiment-analysis", model="cardiffnlp/twitter-roberta-base-sentiment-latest")
    zshot_pipe = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")

    texts = df["review"].astype(str).tolist()
    # sentiment
    senti_std, senti_score = [], []
    for i, t in enumerate(texts):
        s = senti_pipe(t[:512])[0]
        senti_std.append(SENTI_MAP.get(s["label"], s["label"]))
        senti_score.append(float(s.get("score", 0.0)))
        if (i + 1) % 50 == 0:
            log(f"[nlp] sentiment {i+1}/{len(df)}")

    # zero-shot
    cat_pred, cat_score = [], []
    for i, t in enumerate(texts):
        z = zshot_pipe(t[:512], candidate_labels=labels, multi_label=False)
        cat_pred.append(z["labels"][0])
        cat_score.append(float(z["scores"][0]))
        if (i + 1) % 50 == 0:
            log(f"[nlp] zeroshot {i+1}/{len(df)}")

    out = df.copy()
    out["sentiment_std"] = senti_std
    out["sentiment_score"] = senti_score
    out["category"] = out.get("category", "")
    # overwrite empty categories with zero-shot
    out["category"] = out["category"].mask(out["category"].isna() | (out["category"] == ""), cat_pred)
    out["category_score"] = cat_score
    return out

# --------------------------
# Main
# --------------------------
def main():
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    args = parse_args()
    labels = [x.strip() for x in args.labels.split(",") if x.strip()]

    df_gp = fetch_google_play(args.package, args.lang, args.country)
        # NEW: toggle Apple via env/flags if you want (or just always fetch)
    include_ios = os.getenv("INCLUDE_APPSTORE", "true").lower() == "true"
    ios_app_id = int(os.getenv("IOS_APP_ID", "375695000"))
    ios_country = os.getenv("IOS_COUNTRY", "ca")
    ios_lang = os.getenv("IOS_LANG", "en")
    
    if include_ios:
      log(f"[fetch] also pulling App Store reviews id={ios_app_id} ({ios_lang}-{ios_country})…")
      df_ios = fetch_app_store_rss(app_id=ios_app_id, country=ios_country, lang=ios_lang)
    else:
      df_ios = pd.DataFrame(columns=df_gp.columns)
    
    # Merge the sources
    df = pd.concat([df_gp, df_ios], ignore_index=True)
    
    # (rest of your script stays the same: date filters, NLP, JSON outputs)
    # optional filters
    if args.min_date:
        try:
            min_d = pd.to_datetime(args.min_date).strftime("%Y-%m-%d")
            df = df[df["review_date"] >= min_d]
            log(f"[filter] >= {min_d}: {len(df)} rows")
        except Exception:
            log("[warn] invalid --min-date; ignoring")
    if args.only_version:
        df = df[df.get("app_version", "").astype(str) == str(args.only_version)]
        log(f"[filter] app_version == {args.only_version}: {len(df)} rows")

    # keep minimum needed columns before NLP
    if "review" not in df.columns:
        log("[error] no 'review' column after fetch. Exiting.")
        json.dump([], open(args.out_new, "w", encoding="utf-8"))
        return

    # run NLP
    enriched = run_models(df, labels)

    # final schema for your site & comparator
    final_cols = ["review", "category", "sentiment_std", "rating", "review_date"]
    for c in final_cols:
        if c not in enriched.columns:
            enriched[c] = None

    # write both files:
    # - new_data.json: used by comparator and (optionally) to become data.json
    # - reviews.json: what your site pages load
    enriched[final_cols].to_json(args.out_new, orient="records", date_format="iso", force_ascii=False)
    enriched[final_cols].to_json(args.out_reviews, orient="records", date_format="iso", force_ascii=False)

    log(f"[ok] wrote {args.out_new} and {args.out_reviews} with {len(enriched)} rows")

if __name__ == "__main__":
    main()

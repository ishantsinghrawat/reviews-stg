# scripts/build_reviews_json.py
import os, sys, json, argparse, time
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import requests

# Google Play
from google_play_scraper import reviews_all, Sort

# NLP
from transformers import pipeline

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

def log(m: str): print(m, flush=True)

def parse_args():
    p = argparse.ArgumentParser(description="Fetch GP + iOS reviews → NLP → JSON")
    # GP
    p.add_argument("--package", default=os.getenv("GP_PACKAGE", "com.mcdonalds.superapp"))
    p.add_argument("--country", default=os.getenv("GP_COUNTRY", "ca"))
    p.add_argument("--lang", default=os.getenv("GP_LANG", "en"))
    # iOS
    p.add_argument("--include-appstore", default=os.getenv("INCLUDE_APPSTORE", "true"))
    p.add_argument("--ios-app-id", type=int, default=int(os.getenv("IOS_APP_ID", "375695000")))
    p.add_argument("--ios-country", default=os.getenv("IOS_COUNTRY", "ca"))
    p.add_argument("--ios-lang", default=os.getenv("IOS_LANG", "en"))
    p.add_argument("--ios-only-version", default=os.getenv("IOS_ONLY_VERSION", ""))  # optional: pin iOS version
    # Date / version filters
    p.add_argument("--min-date", default=os.getenv("MIN_DATE", ""))       # e.g. 2025-01-01
    p.add_argument("--last-days", type=int, default=int(os.getenv("LAST_DAYS", "30")))
    p.add_argument("--only-version", default=os.getenv("ONLY_VERSION", ""))  # optional: pin GP & iOS
    # NLP + outputs
    p.add_argument("--labels", default=os.getenv("ZS_LABELS", ",".join(DEFAULT_LABELS)))
    p.add_argument("--out-new", default="new_data.json")
    p.add_argument("--out-reviews", default="data.json")
    return p.parse_args()

# --------------------------
# Google Play
# --------------------------
def fetch_google_play(package: str, lang: str, country: str) -> pd.DataFrame:
    log(f"[fetch] Google Play {package} ({lang}-{country}) …")
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
    df.drop(columns=[c for c in ["userImage", "reviewCreatedVersion"] if c in df.columns],
            inplace=True, errors="ignore")
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
    df.insert(0, "source", "Google Play")
    df["language_code"] = lang
    df["country_code"] = country
    if "review_date" in df.columns:
        df["review_date"] = pd.to_datetime(df["review_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return df[:50]

# --------------------------
# Apple RSS
# --------------------------
def fetch_app_store_rss(
    app_id: int,
    country: str,
    lang: str,
    max_pages: int = 10,
    sleep: float = 0.3,
    only_version: str = "",
) -> pd.DataFrame:
    """
    Apple public RSS (~recent pages). We filter by version if provided after fetch.
    """
    def rss_url(page):
        return (f"https://itunes.apple.com/rss/customerreviews/page={page}/id={app_id}"
                f"/sortby=mostrecent/json?l={lang}&cc={country}")
    rows = []
    for page in range(1, max_pages + 1):
        r = requests.get(rss_url(page), timeout=30)
        if r.status_code != 200:
            log(f"[appstore] HTTP {r.status_code} page {page}; stop.")
            break
        data = r.json()
        entries = data.get("feed", {}).get("entry", [])
        if not entries or len(entries) <= 1:
            break
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
    if only_version:
        df = df[df["app_version"].astype(str) == str(only_version)]
        log(f"[appstore] filter version == {only_version}: {len(df)} rows")
    return df[:25]

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
        if (i + 1) % 50 == 0: log(f"[nlp] sentiment {i+1}/{len(df)}")

    # zero-shot
    cat_pred, cat_score = [], []
    for i, t in enumerate(texts):
        z = zshot_pipe(t[:512], candidate_labels=labels, multi_label=False)
        cat_pred.append(z["labels"][0])
        cat_score.append(float(z["scores"][0]))
        if (i + 1) % 50 == 0: log(f"[nlp] zeroshot {i+1}/{len(df)}")

    out = df.copy()
    out["sentiment_std"] = senti_std
    out["sentiment_score"] = senti_score
    # honor existing category if present; otherwise fill with zero-shot
    if "category" not in out.columns:
        out["category"] = None
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

    # --- fetch both sources ---
    df_gp = fetch_google_play(args.package, args.lang, args.country)

    include_ios = str(args.include_appstore).lower() == "true"
    if include_ios:
        log(f"[fetch] App Store id={args.ios_app_id} ({args.ios_lang}-{args.ios_country})")
        df_ios = fetch_app_store_rss(
            app_id=args.ios_app_id,
            country=args.ios_country,
            lang=args.ios_lang,
            only_version=(args.ios_only_version or ""),
        )
    else:
        df_ios = pd.DataFrame(columns=df_gp.columns)

    df = pd.concat([df_gp, df_ios], ignore_index=True, sort=False)

    # --- date filter: last-days or min-date ---
    if args.last_days and args.last_days > 0:
        cutoff = (datetime.utcnow() - timedelta(days=args.last_days)).strftime("%Y-%m-%d")
        df = df[pd.to_datetime(df["review_date"], errors="coerce") >= pd.to_datetime(cutoff)]
        log(f"[filter] last {args.last_days} days (>= {cutoff}): {len(df)} rows")
    elif args.min_date:
        try:
            min_d = pd.to_datetime(args.min_date).strftime("%Y-%m-%d")
            df = df[df["review_date"] >= min_d]
            log(f"[filter] >= {min_d}: {len(df)} rows")
        except Exception:
            log("[warn] invalid --min-date; ignoring")

    # --- optional global version pin (applies to both stores) ---
    if args.only_version:
        df = df[df.get("app_version", "").astype(str) == str(args.only_version)]
        log(f"[filter] app_version == {args.only_version}: {len(df)} rows")

    # --- safety: must have review text ---
    if "review" not in df.columns:
        log("[error] no 'review' column after fetch. Exiting.")
        with open(args.out_new, "w", encoding="utf-8") as f: json.dump([], f)
        return

    # --- NLP ---
    enriched = run_models(df, labels)

    # --- final output for site + comparator ---
    final_cols = [
        "review", "category", "sentiment_std", "rating", "review_date",
        "source", "app_version"  # <-- keep store & version visible
    ]
    for c in final_cols:
        if c not in enriched.columns:
            enriched[c] = None

    enriched[final_cols].to_json(args.out_new, orient="records", date_format="iso", force_ascii=False)
    # keep reviews.json for optional use; safe to keep identical schema
    enriched[final_cols].to_json(args.out_reviews, orient="records", date_format="iso", force_ascii=False)

    log(f"[ok] wrote {args.out_new} and {args.out_reviews} with {len(enriched)} rows")

if __name__ == "__main__":
    main()

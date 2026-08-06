"""
research.py
------------
Turns raw GSC performance data (pulled via the official Search Console API,
gsc_client.py) into a prioritized topic backlog - same logic used in the
manual Topical Content Map, now automated. $0 cost: everything here runs on
your own GSC data only, no paid keyword-volume lookups.

Scoped to blog content only: the property-wide GSC data includes every page
on the site (product pages, category pages, etc.), but this tool only ever
writes blog posts - so every pull is filtered to SITE_BLOG_PATH (default
"/blog/") both server-side (GSC's own filter, cheaper) and again client-side
as a safety net, so a stray non-blog URL can never sneak into the backlog.

Produces two kinds of backlog items:
  1. REVIVAL   - existing pages with real impressions but poor CTR (fix, don't rewrite)
  2. GAP       - queries with decent impressions where you have no strong ranking
                 page at all (candidates for a brand-new post)
  3. MANUAL    - added directly by a person through the dashboard, skipping
                 GSC entirely (see add_manual_topic below)
"""

import csv
import os
import re
from datetime import datetime

import pandas as pd

import paths

BACKLOG_PATH = paths.BACKLOG_PATH
BACKLOG_FIELDS = [
    "id", "type", "topic_or_page", "category", "priority", "clicks",
    "impressions", "ctr", "position", "evidence", "status", "date_added",
]


def _to_dataframe(rows: list) -> pd.DataFrame:
    """rows come from gsc_client.get_performance_data() - a flat list of dicts
    already shaped as {query, page, clicks, impressions, ctr, position}."""
    df = pd.DataFrame(rows)
    for col in ("query", "page", "clicks", "impressions", "ctr", "position"):
        if col not in df.columns:
            df[col] = None
    return df


_STOPWORDS = {
    "a", "an", "the", "of", "for", "to", "in", "on", "and", "is", "are", "how",
    "what", "types", "type", "kind", "kinds", "list", "different", "best",
}
# NOTE - honest limitation: this catches word-reordering and common filler
# words ("furniture styles" == "styles of furniture" == "types of furniture
# styles"), but does NOT do stemming, so plain singular/plural variants like
# "furniture style" vs "furniture styles" still won't merge. Good enough to
# meaningfully reduce double-counting without pulling in a full NLP library
# for a $0-budget tool; if this matters a lot, a proper stemmer (e.g. NLTK's
# PorterStemmer) would close that last gap.


def _normalize_query(q: str) -> str:
    """Collapses word-order/stopword variants to the same signature, e.g.
    'furniture styles' / 'styles of furniture' / 'types of furniture styles'
    all normalize to the same set of core words - this was flagged as a real
    problem in your GSC data (same demand split across many rows)."""
    words = [w for w in str(q).lower().split() if w not in _STOPWORDS]
    return " ".join(sorted(set(words)))


def _cluster_fragmented_queries(df: pd.DataFrame) -> pd.DataFrame:
    """Merges near-duplicate queries (same core words, different phrasing/order)
    into one row before gap analysis, summing clicks/impressions and using the
    highest-impression variant as the representative surface form.

    Uses vectorized groupby().agg() rather than groupby().apply() - avoids a
    pandas FutureWarning about grouping-column handling in apply(), and is
    faster on a real 1,000+ row GSC export."""
    q_df = df.dropna(subset=["query"]).copy()
    if q_df.empty:
        return q_df
    q_df["_signature"] = q_df["query"].apply(_normalize_query)
    q_df["_weighted_position"] = q_df["position"].fillna(0) * q_df["impressions"].fillna(0)

    grouped = q_df.groupby("_signature").agg(
        clicks=("clicks", "sum"),
        impressions=("impressions", "sum"),
        _weighted_position_sum=("_weighted_position", "sum"),
        variant_count=("query", "count"),
    ).reset_index()
    grouped["position"] = grouped["_weighted_position_sum"] / grouped["impressions"].replace(0, pd.NA)

    # Representative surface form = the highest-impression variant per signature.
    representative = (
        q_df.sort_values("impressions", ascending=False)
        .drop_duplicates(subset="_signature")[["_signature", "query"]]
    )
    merged = grouped.merge(representative, on="_signature", how="left")
    return merged.drop(columns=["_signature", "_weighted_position_sum"])


def categorize(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ["dining", "table", "chair"]):
        return "Dining"
    if any(k in t for k in ["bed", "bedroom", "nightstand", "dresser"]):
        return "Bedroom"
    if any(k in t for k in ["desk", "office"]):
        return "Home Office"
    if any(k in t for k in ["outdoor", "patio"]):
        return "Outdoor"
    if any(k in t for k in ["bar", "kitchen", "stool"]):
        return "Bar/Kitchen"
    if any(k in t for k in ["entryway", "console", "sideboard"]):
        return "Entryway"
    return "General"


def compute_revival_candidates(df: pd.DataFrame, impression_threshold: int = 5000) -> pd.DataFrame:
    page_df = df.dropna(subset=["page"]).copy()
    if page_df.empty:
        return page_df
    agg = page_df.groupby("page").agg(
        clicks=("clicks", "sum"),
        impressions=("impressions", "sum"),
    ).reset_index()
    agg["ctr"] = agg["clicks"] / agg["impressions"].replace(0, pd.NA)
    agg = agg[agg["impressions"] >= impression_threshold]
    agg = agg.sort_values("ctr").head(25)
    agg["priority"] = agg.apply(
        lambda r: "Critical" if r["impressions"] > 100000 else ("High" if r["impressions"] > 20000 else "Medium"),
        axis=1,
    )
    agg["category"] = agg["page"].apply(categorize)
    return agg


def compute_gap_candidates(df: pd.DataFrame, min_impressions: int = 500) -> pd.DataFrame:
    merged = _cluster_fragmented_queries(df)
    if merged.empty:
        return merged
    # Real demand (decent impressions) but ranking poorly / far down = a gap
    # worth a dedicated page, not paid keyword-volume data - just your own signal.
    gaps = merged[(merged["impressions"] >= min_impressions) & (merged["position"] > 15)]
    gaps = gaps.sort_values("impressions", ascending=False).head(25).copy()
    gaps["priority"] = gaps.apply(
        lambda r: "Critical" if r["impressions"] > 20000 else ("High" if r["impressions"] > 5000 else "Medium"),
        axis=1,
    )
    gaps["category"] = gaps["query"].apply(categorize)
    return gaps


def _load_existing_backlog() -> list:
    if not BACKLOG_PATH.exists():
        return []
    with open(BACKLOG_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _next_id(existing: list) -> int:
    if not existing:
        return 1
    return max(int(r["id"]) for r in existing) + 1


def update_backlog(revival_df: pd.DataFrame, gap_df: pd.DataFrame) -> int:
    """Appends new topics to data/topic_backlog.csv (dedupes by topic_or_page).
    Returns count of newly added rows."""
    BACKLOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_existing_backlog()
    existing_keys = {r["topic_or_page"] for r in existing}
    next_id = _next_id(existing)
    new_rows = []
    today = datetime.now().strftime("%Y-%m-%d")

    for _, r in revival_df.iterrows():
        if r["page"] in existing_keys:
            continue
        new_rows.append({
            "id": next_id, "type": "REVIVAL", "topic_or_page": r["page"],
            "category": r["category"], "priority": r["priority"],
            "clicks": int(r["clicks"]), "impressions": int(r["impressions"]),
            "ctr": round(float(r["ctr"]), 5) if pd.notna(r["ctr"]) else "",
            "position": "", "evidence": "High impressions, low CTR vs. site average",
            "status": "queued", "date_added": today,
        })
        next_id += 1

    for _, r in gap_df.iterrows():
        if r["query"] in existing_keys:
            continue
        new_rows.append({
            "id": next_id, "type": "GAP", "topic_or_page": r["query"],
            "category": r["category"], "priority": r["priority"],
            "clicks": int(r["clicks"]), "impressions": int(r["impressions"]),
            "ctr": "", "position": round(float(r["position"]), 1),
            "evidence": "Real search demand, no strong ranking page yet",
            "status": "queued", "date_added": today,
        })
        next_id += 1

    all_rows = existing + new_rows
    with open(BACKLOG_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=BACKLOG_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)

    return len(new_rows)


def add_manual_topic(topic: str, category: str = "General", priority: str = "Medium",
                      evidence: str = "Manually added from the dashboard") -> dict:
    """Adds one topic straight to the backlog, bypassing GSC entirely - this
    is what the dashboard's 'Add topic' button calls. Lets someone queue a
    post for a topic they already know they want written, without waiting
    on (or having) Search Console data for it."""
    BACKLOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_existing_backlog()
    if topic in {r["topic_or_page"] for r in existing}:
        return {"ok": False, "error": "That topic is already in the backlog."}
    row = {
        "id": _next_id(existing), "type": "MANUAL", "topic_or_page": topic,
        "category": category or "General", "priority": priority or "Medium",
        "clicks": "", "impressions": "", "ctr": "", "position": "",
        "evidence": evidence, "status": "queued",
        "date_added": datetime.now().strftime("%Y-%m-%d"),
    }
    existing.append(row)
    with open(BACKLOG_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=BACKLOG_FIELDS)
        writer.writeheader()
        writer.writerows(existing)
    return {"ok": True, "row": row}


def run_research(service_account_file: str, site_url: str, impression_threshold: int = 5000,
                  gap_min_impressions: int = 500, blog_path: str = "/blog/"):
    import gsc_client

    print(f"Pulling GSC performance data for {site_url} via the official Search Console API...")
    if blog_path:
        print(f"Scoping to blog content only: pages containing \"{blog_path}\"")
    rows = gsc_client.get_performance_data(
        service_account_file, site_url, days=90, dimensions=["query", "page"],
        page_filter_contains=blog_path or None,
    )
    df = _to_dataframe(rows)
    if blog_path and not df.empty and "page" in df.columns:
        # Safety net in addition to GSC's own server-side filter, in case a
        # domain-property pull ever includes something unexpected.
        df = df[df["page"].fillna("").str.contains(re.escape(blog_path), case=False)]
    if df.empty:
        print("No data returned - check that the service account was added as a")
        print("User on this exact property in Search Console (Settings > Users and permissions),")
        print("that GSC_SITE_URL in config.env matches the property exactly, and that")
        print(f"SITE_BLOG_PATH (\"{blog_path}\") actually matches your blog's URL structure.")
        return 0

    revival = compute_revival_candidates(df, impression_threshold)
    gaps = compute_gap_candidates(df, gap_min_impressions)
    added = update_backlog(revival, gaps)
    print(f"Added {added} new topics to {BACKLOG_PATH} "
          f"({len(revival)} revival candidates, {len(gaps)} gap candidates reviewed).")
    return added


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv("config.env")
    run_research(
        os.environ["GSHEETS_SERVICE_ACCOUNT_FILE"], os.environ["GSC_SITE_URL"],
        int(os.environ.get("REVIVAL_IMPRESSION_THRESHOLD", 5000)),
        int(os.environ.get("GAP_IMPRESSION_THRESHOLD", 500)),
        os.environ.get("SITE_BLOG_PATH", "/blog/"),
    )

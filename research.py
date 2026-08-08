"""
research.py
------------
Turns raw GSC performance data (pulled via the official Search Console API,
gsc_client.py) into a prioritized topic backlog - same logic used in the
manual Topical Content Map, now automated. $0 cost: everything here runs on
your own GSC data only, no paid keyword-volume lookups.

Two different GSC pulls are used for two different questions:
  - REVIVAL uses a BLOG-SCOPED pull (page contains SITE_BLOG_PATH) - the
    question is "which of OUR blog pages get impressions but a poor CTR."
  - GAP uses a SITE-WIDE pull (no page filter) - the question is "is there
    real search demand where NOTHING on the whole site ranks well." Scoping
    that pull to blog pages only would be self-defeating: it could only ever
    return queries where a blog page already shows up in the data at all,
    which made every "gap" a query some existing post was already touching -
    exactly backwards from what a gap is supposed to mean. Site-wide data
    lets a query's best-ranking page (blog, product, or otherwise) genuinely
    decide whether it's still an open opportunity.

Produces three kinds of backlog items:
  1. REVIVAL   - existing blog pages with real impressions but poor CTR (fix, don't rewrite)
  2. GAP       - queries with decent impressions where NO page anywhere on the
                 site ranks well (candidates for a brand-new post)
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


def _cluster_fragmented_queries(df: pd.DataFrame, blog_path: str = None) -> pd.DataFrame:
    """Merges near-duplicate queries (same core words, different phrasing/order)
    into one row before gap analysis, summing clicks/impressions and tracking
    the BEST (minimum) position any page achieves for that query cluster -
    not a weighted average. A weighted average can look "bad" even when one
    specific page already ranks well, because it gets dragged down by other
    weaker pages showing for slight phrasing variants; minimum position is
    the honest answer to "does anything already rank for this."

    If blog_path is given, also tracks best_blog_position separately - the
    best position achieved specifically by a page under that path, or NaN if
    no blog page shows for this query cluster at all.

    Uses vectorized groupby().agg() rather than groupby().apply() - avoids a
    pandas FutureWarning about grouping-column handling in apply(), and is
    faster on a real 1,000+ row GSC export."""
    q_df = df.dropna(subset=["query"]).copy()
    if q_df.empty:
        return q_df
    q_df["_signature"] = q_df["query"].apply(_normalize_query)
    q_df["_is_blog"] = False
    if blog_path:
        q_df["_is_blog"] = q_df["page"].fillna("").str.contains(re.escape(blog_path), case=False)

    grouped = q_df.groupby("_signature").agg(
        clicks=("clicks", "sum"),
        impressions=("impressions", "sum"),
        position=("position", "min"),
        variant_count=("query", "count"),
    ).reset_index()

    if blog_path:
        blog_only = q_df[q_df["_is_blog"]]
        blog_best = blog_only.groupby("_signature")["position"].min().reset_index().rename(
            columns={"position": "best_blog_position"})
        grouped = grouped.merge(blog_best, on="_signature", how="left")
    else:
        grouped["best_blog_position"] = pd.NA

    # Representative surface form = the highest-impression variant per signature.
    representative = (
        q_df.sort_values("impressions", ascending=False)
        .drop_duplicates(subset="_signature")[["_signature", "query"]]
    )
    merged = grouped.merge(representative, on="_signature", how="left")
    return merged.drop(columns=["_signature"])


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


def compute_gap_candidates(df: pd.DataFrame, min_impressions: int = 500, blog_path: str = None) -> pd.DataFrame:
    """`df` should be SITE-WIDE data (no page filter) - see the module
    docstring for why. A gap candidate is a query with real demand where the
    best-ranking page ANYWHERE on the site (blog or not) is still weak."""
    merged = _cluster_fragmented_queries(df, blog_path=blog_path)
    if merged.empty:
        return merged
    # Real demand (decent impressions) but the best page anywhere on the site
    # still ranks poorly = a genuine gap worth a dedicated page. "position"
    # here is already the BEST (minimum) position across every page that
    # showed for this query, so this can't fire just because one weak page
    # among several drags an average down - see _cluster_fragmented_queries.
    gaps = merged[(merged["impressions"] >= min_impressions) & (merged["position"] > 15)]
    # Belt-and-suspenders: even if the site-wide best position for a query
    # is technically >15, don't suggest it as a NEW post if a blog page is
    # already the one showing (however weakly) - that's a revival situation
    # for that existing post, not a case for writing a second, competing one.
    if "best_blog_position" in gaps.columns:
        gaps = gaps[gaps["best_blog_position"].isna() | (gaps["best_blog_position"] > 30)]
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
    """Appends new topics to data/topic_backlog.csv. Dedupes GAP topics by
    normalized signature (so "dining table size" and "sizes of dining
    tables" are treated as the same topic even with different phrasing/word
    order) and REVIVAL topics by exact page URL (URLs don't have the
    phrasing-variant problem queries do). Returns count of newly added rows."""
    BACKLOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_existing_backlog()
    existing_pages = {r["topic_or_page"] for r in existing if r["type"] == "REVIVAL"}
    existing_signatures = {_normalize_query(r["topic_or_page"]) for r in existing if r["type"] != "REVIVAL"}
    next_id = _next_id(existing)
    new_rows = []
    today = datetime.now().strftime("%Y-%m-%d")

    for _, r in revival_df.iterrows():
        if r["page"] in existing_pages:
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
        sig = _normalize_query(r["query"])
        if sig in existing_signatures:
            continue
        existing_signatures.add(sig)  # also dedupe within this same batch
        new_rows.append({
            "id": next_id, "type": "GAP", "topic_or_page": r["query"],
            "category": r["category"], "priority": r["priority"],
            "clicks": int(r["clicks"]), "impressions": int(r["impressions"]),
            "ctr": "", "position": round(float(r["position"]), 1) if pd.notna(r["position"]) else "",
            "evidence": "Real search demand, no page anywhere on the site ranks well",
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
    new_sig = _normalize_query(topic)
    if any(_normalize_query(r["topic_or_page"]) == new_sig for r in existing if r["type"] != "REVIVAL"):
        return {"ok": False, "error": "A very similar topic is already in the backlog."}
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

    # --- Blog-scoped pull: powers REVIVAL (existing blog pages, poor CTR) ---
    if blog_path:
        print(f"Blog-scoped pull for REVIVAL candidates: pages containing \"{blog_path}\"")
    blog_rows = gsc_client.get_performance_data(
        service_account_file, site_url, days=90, dimensions=["query", "page"],
        page_filter_contains=blog_path or None,
    )
    blog_df = _to_dataframe(blog_rows)
    if blog_path and not blog_df.empty and "page" in blog_df.columns:
        # Safety net in addition to GSC's own server-side filter.
        blog_df = blog_df[blog_df["page"].fillna("").str.contains(re.escape(blog_path), case=False)]

    # --- Site-wide pull: powers GAP (is anything, anywhere, already ranking?) ---
    print("Site-wide pull for GAP candidates: every page on the property, so a query "
          "already covered by a well-ranking page (blog or otherwise) is correctly excluded")
    sitewide_rows = gsc_client.get_performance_data(
        service_account_file, site_url, days=90, dimensions=["query", "page"],
        page_filter_contains=None,
    )
    sitewide_df = _to_dataframe(sitewide_rows)

    if blog_df.empty and sitewide_df.empty:
        print("No data returned - check that the service account was added as a")
        print("User on this exact property in Search Console (Settings > Users and permissions),")
        print("that GSC_SITE_URL in config.env matches the property exactly, and that")
        print(f"SITE_BLOG_PATH (\"{blog_path}\") actually matches your blog's URL structure.")
        return 0

    revival = compute_revival_candidates(blog_df, impression_threshold) if not blog_df.empty else pd.DataFrame()
    gaps = compute_gap_candidates(sitewide_df, gap_min_impressions, blog_path=blog_path) if not sitewide_df.empty else pd.DataFrame()
    added = update_backlog(revival, gaps)
    print(f"Added {added} new topics to {BACKLOG_PATH} "
          f"({len(revival)} revival candidates, {len(gaps)} gap candidates reviewed).")
    return added


def find_query_data(service_account_file: str, site_url: str, seed: str, blog_path: str = "/blog/") -> list:
    """Real-data lookup used by keyword research (see seo_research.py):
    pulls site-wide GSC data and returns actual impressions/clicks/position
    for any query already containing the seed phrase - so keyword ideas can
    be tagged with real numbers where they exist, instead of only ever
    showing AI-guessed ideas with no signal behind them. Returns [] quietly
    on any failure (missing config, GSC error) - this is a nice-to-have
    enrichment, not a step that should ever block keyword research from
    returning results."""
    import gsc_client

    try:
        rows = gsc_client.get_performance_data(
            service_account_file, site_url, days=90, dimensions=["query", "page"], page_filter_contains=None,
        )
    except Exception as e:
        print(f"  (real-data lookup skipped: {e})")
        return []
    df = _to_dataframe(rows)
    if df.empty:
        return []
    seed_words = set(str(seed).lower().split())
    mask = df["query"].fillna("").str.lower().apply(lambda q: seed_words.issubset(set(q.split())) or seed.lower() in q)
    matched = df[mask]
    if matched.empty:
        return []
    clustered = _cluster_fragmented_queries(matched, blog_path=blog_path)
    out = []
    for _, r in clustered.sort_values("impressions", ascending=False).head(20).iterrows():
        out.append({
            "query": r["query"], "impressions": int(r["impressions"]), "clicks": int(r["clicks"]),
            "position": round(float(r["position"]), 1) if pd.notna(r["position"]) else None,
            "has_blog_page": bool(pd.notna(r.get("best_blog_position"))),
        })
    return out


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv("config.env")
    run_research(
        os.environ["GSHEETS_SERVICE_ACCOUNT_FILE"], os.environ["GSC_SITE_URL"],
        int(os.environ.get("REVIVAL_IMPRESSION_THRESHOLD", 5000)),
        int(os.environ.get("GAP_IMPRESSION_THRESHOLD", 500)),
        os.environ.get("SITE_BLOG_PATH", "/blog/"),
    )

"""
free_keyword_tools.py
----------------------
Two free, zero-setup sources of REAL keyword signal, used to strengthen the
AI-generated ideas from seo_research.research_keywords() before they're
shown to a person:

  1. Google Autocomplete - the actual suggestion list Google shows as you
     type. Free, no API key, no account. Gives real phrasing people search,
     not a volume number. Uses the same public JSON endpoint Google's own
     search box calls (client=firefox), which is what most free "keyword
     suggestion" tools out there are built on.

  2. Google Trends (via the unofficial `pytrends` library) - relative
     search interest over the last 12 months (0-100 scale, NOT absolute
     volume - Google doesn't expose absolute numbers for free anywhere).
     Useful for telling a rising topic from a declining or flat one. Free,
     no API key, no account - but it's an UNOFFICIAL wrapper around an
     undocumented Google endpoint, so it can rate-limit or change shape
     without notice. Every call here is wrapped to degrade gracefully:
     if Trends is unavailable, keyword research still returns everything
     else and simply omits the trend badge for that keyword.

Honest limitation, stated plainly so it's never confused with paid tools:
neither of these gives you a Semrush/Ahrefs-style absolute search-volume
number. For that, the only free (as in no subscription) option is Google
Keyword Planner via the Google Ads API - which needs a Google Ads account,
a developer token Google has to approve, and OAuth setup, and even then
often returns volume as a bucketed range rather than an exact number
unless the account has ad-spend history. That's a deliberate later upgrade,
not something wired in here - see README.md "Adding real search volume
(Google Keyword Planner)" for the setup path if you want to add it.
"""

import re
import time

import requests

AUTOCOMPLETE_URL = "https://suggestqueries.google.com/complete/search"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BlogHeroKeywordResearch/1.0)"}


def get_autocomplete_suggestions(seed: str, max_results: int = 10) -> list:
    """Real phrases Google itself suggests for this seed - free, no key.
    Returns [] on any failure (network, rate limit, unexpected response
    shape) rather than raising, since this is an enrichment step that
    should never block keyword research from returning the AI ideas."""
    try:
        resp = requests.get(
            AUTOCOMPLETE_URL,
            params={"client": "firefox", "q": seed},
            headers=_HEADERS, timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        # Response shape: [query, [suggestion1, suggestion2, ...], ...]
        suggestions = data[1] if len(data) > 1 and isinstance(data[1], list) else []
        cleaned = [s.strip() for s in suggestions if isinstance(s, str) and s.strip()]
        return cleaned[:max_results]
    except Exception as e:
        print(f"  (autocomplete lookup skipped: {e})")
        return []


def get_trends_interest(keywords: list, max_keywords: int = 5) -> dict:
    """Relative search interest (0-100, last 12 months) per keyword, plus a
    simple rising/steady/declining direction (second-half average vs
    first-half average of the trend line). Google Trends only accepts up to
    5 keywords per request, so `keywords` is capped to max_keywords - pass
    in your highest-priority phrases first (e.g. the seed plus the top few
    AI-suggested ideas), not the whole list.

    Returns {keyword: {"score": int, "direction": "rising"|"steady"|"declining"}}
    - keywords with no data (too low volume for Trends to report, or the
    lookup failed) are simply absent from the returned dict; callers should
    treat a missing key as "no trend data available", not "zero interest"."""
    keywords = [k for k in keywords if k][:max_keywords]
    if not keywords:
        return {}
    try:
        from pytrends.request import TrendReq

        pytrends = TrendReq(hl="en-US", tz=360, timeout=(5, 10))
        pytrends.build_payload(keywords, timeframe="today 12-m", geo="US")
        df = pytrends.interest_over_time()
        if df is None or df.empty:
            return {}
        out = {}
        for kw in keywords:
            if kw not in df.columns:
                continue
            series = df[kw]
            if series.sum() == 0:
                continue  # Trends has no meaningful signal for this term
            half = len(series) // 2
            first_half_avg = series.iloc[:half].mean() if half > 0 else series.mean()
            second_half_avg = series.iloc[half:].mean()
            if second_half_avg > first_half_avg * 1.15:
                direction = "rising"
            elif second_half_avg < first_half_avg * 0.85:
                direction = "declining"
            else:
                direction = "steady"
            out[kw] = {"score": int(round(series.mean())), "direction": direction}
        return out
    except ImportError:
        print("  (Trends skipped: pytrends isn't installed - pip install pytrends)")
        return {}
    except Exception as e:
        # pytrends wraps an undocumented Google endpoint - rate limits and
        # occasional breakage are expected, not exceptional. Never let this
        # block the rest of keyword research.
        print(f"  (Trends lookup skipped: {e})")
        return {}

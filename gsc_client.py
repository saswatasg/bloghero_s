"""
gsc_client.py
-------------
Pulls Google Search Console performance data via Google's OFFICIAL,
free Search Console API - no OpenSEO, no third-party MCP server, no paid
plan of any kind.

Why not OpenSEO's MCP (as originally planned): OpenSEO's own docs state
their Search Console MCP tools are bundled with their $10/month hosted plan
(self-hosting avoids the fee but requires setting up your own Google OAuth
client anyway - the exact setup step OpenSEO was meant to save you from).
Given the $0 budget for this workflow, the official API is the correct
choice: it's genuinely free, extremely well-documented, stable (Google's
own product), and reuses the SAME service account this tool already needs
for Google Sheets logging - one credential, two scopes, nothing extra to set up.

ONE MANUAL STEP GOOGLE DOESN'T LET ANY TOOL SKIP:
You must add your service account's email as a USER on the Search Console
property (Search Console > Settings > Users and permissions > Add user).
The email looks like: your-service-account@your-project.iam.gserviceaccount.com
(find it inside your service account JSON key file, field "client_email").
Without this step, every call below will fail with a 403 permission error -
this isn't a bug, it's how Google's API works for every tool, not just this one.
"""

import time
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


def get_service(service_account_file: str):
    creds = service_account.Credentials.from_service_account_file(
        service_account_file, scopes=SCOPES,
    )
    return build("searchconsole", "v1", credentials=creds)


def _execute_with_retry(request, max_attempts: int = 4):
    """Google's API rate-limits (HTTP 429) and transient 5xx errors under
    real usage - retry with exponential backoff (2s, 4s, 8s, 16s) rather
    than letting a scheduled run just die on a transient blip."""
    last_error = None
    for attempt in range(max_attempts):
        try:
            return request.execute()
        except HttpError as e:
            last_error = e
            if e.resp.status not in (429, 500, 502, 503):
                raise  # a real error (e.g. 403 permission), no point retrying
            wait = 2 ** (attempt + 1)
            print(f"  GSC API call failed ({e.resp.status}); retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"GSC API call failed after {max_attempts} attempts: {last_error}")


def list_properties(service_account_file: str) -> list:
    """Sanity-check call: lists every GSC property this service account can see.
    Run this first (via `python main.py check-gsc`) to confirm the service
    account was added as a user correctly before trying anything else."""
    service = get_service(service_account_file)
    resp = _execute_with_retry(service.sites().list())
    return [s["siteUrl"] for s in resp.get("siteEntry", [])]


def get_performance_data(service_account_file: str, site_url: str,
                          days: int = 90, dimensions=None, row_limit: int = 25000,
                          page_filter_contains: str = None) -> list:
    """Returns a flat list of dicts: [{query, page, clicks, impressions, ctr, position}, ...]
    Paginates automatically (Google caps each response at row_limit rows).

    page_filter_contains: if given, only rows whose page URL CONTAINS this
    substring are returned (e.g. "/blog/") - applied server-side via GSC's
    own dimensionFilterGroups, so it doesn't just filter what we display, it
    reduces what Google returns in the first place. Pass None/empty to get
    every page on the property (old behavior)."""
    from datetime import date, timedelta

    dimensions = dimensions or ["query", "page"]
    service = get_service(service_account_file)

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    all_rows = []
    start_row = 0
    while True:
        body = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "dimensions": dimensions,
            "rowLimit": row_limit,
            "startRow": start_row,
        }
        if page_filter_contains:
            body["dimensionFilterGroups"] = [{
                "filters": [{
                    "dimension": "page",
                    "operator": "contains",
                    "expression": page_filter_contains,
                }]
            }]
        resp = _execute_with_retry(service.searchanalytics().query(siteUrl=site_url, body=body))
        rows = resp.get("rows", [])
        if not rows:
            break
        for r in rows:
            keys = r.get("keys", [])
            entry = {dim: keys[i] if i < len(keys) else None for i, dim in enumerate(dimensions)}
            entry.update({
                "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "ctr": r.get("ctr", 0),
                "position": r.get("position", 0),
            })
            all_rows.append(entry)
        if len(rows) < row_limit:
            break
        start_row += row_limit

    return all_rows


if __name__ == "__main__":
    # Quick manual check: `python gsc_client.py` lists GSC properties visible
    # to your service account - confirms the "add as user" step worked.
    import os
    from dotenv import load_dotenv

    load_dotenv("config.env")
    sa_file = os.environ.get("GSHEETS_SERVICE_ACCOUNT_FILE", "data/gsheets_service_account.json")
    if not Path(sa_file).exists():
        print(f"Service account file not found at {sa_file} - set it up first (see README.md).")
    else:
        props = list_properties(sa_file)
        print("GSC properties visible to this service account:")
        for p in props:
            print(" -", p)
        if not props:
            print("\nNone found. Did you add the service account email as a User in")
            print("Search Console > Settings > Users and permissions?")

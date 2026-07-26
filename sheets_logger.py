"""
sheets_logger.py
-----------------
Logs every generated post to a Google Sheet so review stays fast: one row per
post, with links to the WordPress draft, fact-check flags, and image source.

Setup (one-time, per person running this tool):
  1. Google Cloud Console > create a project > enable "Google Sheets API"
  2. Create a Service Account, download its JSON key -> save as
     data/gsheets_service_account.json
  3. Create a Google Sheet, share it with the service account's email
     (found inside the JSON key file) with Editor access
  4. Put the Sheet's ID (from its URL) into config.env as GSHEETS_SHEET_ID
"""

from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

LOG_HEADERS = [
    "Date", "Topic", "Type", "Category", "Priority", "WordPress Edit Link",
    "Image Source", "Fact-Check Flags", "Word Count", "Status",
]


def _get_worksheet(service_account_file: str, sheet_id: str, tab_name: str):
    creds = Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab_name, rows=1000, cols=len(LOG_HEADERS))
        ws.append_row(LOG_HEADERS)
    if ws.row_values(1) != LOG_HEADERS:
        ws.update("A1", [LOG_HEADERS])
    return ws


def log_run(service_account_file: str, sheet_id: str, tab_name: str, entry: dict):
    ws = _get_worksheet(service_account_file, sheet_id, tab_name)
    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        entry.get("topic", ""),
        entry.get("type", ""),
        entry.get("category", ""),
        entry.get("priority", ""),
        entry.get("edit_link", ""),
        entry.get("image_source", ""),
        entry.get("fact_check_flag_count", ""),
        entry.get("word_count", ""),
        entry.get("status", "Drafted - pending review"),
    ]
    ws.append_row(row)

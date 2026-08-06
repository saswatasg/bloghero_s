"""
config_store.py
-----------------
Single source of truth for what config.env contains, used by:
  - the setup wizard UI (renders form fields from SETUP_STEPS)
  - the API (reads/writes config.env)

Keeping the schema in one place means the web form and the actual .env file
can never drift out of sync with each other.
"""

import re

import paths

CONFIG_PATH = paths.CONFIG_PATH
TEMPLATE_PATH = paths.CONFIG_TEMPLATE_PATH
SERVICE_ACCOUNT_PATH = paths.SERVICE_ACCOUNT_PATH

# Fields the wizard should mask when displaying back to the user (never echo
# a secret into the UI once it's saved - show a placeholder instead).
SECRET_FIELDS = {"GEMINI_API_KEY", "WP_APP_PASSWORD", "ANTHROPIC_API_KEY"}

REQUIRED_FIELDS = ["GEMINI_API_KEY", "GSC_SITE_URL", "GSHEETS_SERVICE_ACCOUNT_FILE"]

# Each step is one screen in the web wizard.
SETUP_STEPS = [
    {
        "id": "site",
        "title": "Your website",
        "fields": [
            {"key": "SITE_DOMAIN", "label": "Website domain", "default": "sierralivingconcepts.com",
             "help": "No https:// - just the domain."},
            {"key": "SITE_BASE_URL", "label": "Full website URL", "default": "https://www.sierralivingconcepts.com",
             "help": ""},
            {"key": "SITE_BLOG_PATH", "label": "Blog path", "default": "/blog/",
             "help": "This tool only ever writes blog posts. Research is scoped to pages whose "
                     "URL contains this - so product pages, category pages etc. are never pulled in "
                     "as topics. Change it if your blog lives somewhere other than /blog/."},
        ],
    },
    {
        "id": "gemini",
        "title": "Gemini API key",
        "intro": "This is what powers the SEO research step (always Gemini) and generates fallback "
                 "images. Also used for writing if you pick Gemini as your writing model on the next "
                 "step. Free to get, with usage limits on the free tier.",
        "link": {"label": "Get a key at aistudio.google.com/apikey", "url": "https://aistudio.google.com/apikey"},
        "fields": [
            {"key": "GEMINI_API_KEY", "label": "Gemini API key", "default": "", "secret": True, "required": True,
             "help": "Sign in with any Google account, click 'Create API key', paste it here."},
            {"key": "GEMINI_TEXT_MODEL", "label": "Text model", "default": "gemini-2.5-flash",
             "help": "Leave as default unless you know you want a different one."},
            {"key": "GEMINI_IMAGE_MODEL", "label": "Image model", "default": "gemini-2.5-flash-image",
             "help": "Leave as default unless you know you want a different one."},
        ],
    },
    {
        "id": "writer",
        "title": "Writing model",
        "intro": "The research step that turns Search Console data into a topic backlog always uses "
                 "Gemini. This step chooses which model actually WRITES the post - drafting, "
                 "fact-checking, the humanize polish pass, and SEO metadata all follow this choice.",
        "fields": [
            {"key": "WRITER_PROVIDER", "label": "Write posts with", "type": "select", "default": "gemini",
             "options": [
                 {"value": "gemini", "label": "Gemini"},
                 {"value": "claude", "label": "Claude"},
             ],
             "help": "You can switch this any time - it only affects future runs."},
            {"key": "ANTHROPIC_API_KEY", "label": "Anthropic (Claude) API key", "default": "", "secret": True,
             "help": "Only needed if you chose Claude above. Get one at console.anthropic.com."},
            {"key": "ANTHROPIC_MODEL", "label": "Claude model", "default": "claude-sonnet-4-6",
             "help": "Leave as default unless you know you want a different one."},
        ],
    },
    {
        "id": "google_cloud",
        "title": "Google service account",
        "intro": "One free credential powers both the Search Console data pull and the Google Sheets log. "
                 "Create a Google Cloud project, enable 'Google Sheets API' and 'Google Search Console API', "
                 "then create a Service Account and download its JSON key.",
        "link": {"label": "Open Google Cloud Console", "url": "https://console.cloud.google.com"},
        "fields": [
            {"key": "_service_account_upload", "label": "Upload the service account JSON key file",
             "type": "file", "help": f"Will be saved as {SERVICE_ACCOUNT_PATH}"},
        ],
    },
    {
        "id": "search_console",
        "title": "Search Console access",
        "intro": "Add your service account's email as a User in Search Console (Settings > Users and "
                 "permissions > Add user) - Restricted access is enough, this only ever reads data.",
        "link": {"label": "Open Search Console", "url": "https://search.google.com/search-console"},
        "fields": [
            {"key": "GSC_SITE_URL", "label": "Search Console property", "default": "", "type": "gsc_picker",
             "help": "Pick from the list once your service account has access (button below)."},
        ],
    },
    {
        "id": "wordpress",
        "title": "WordPress",
        "intro": "This tool only ever creates DRAFT posts - it never publishes automatically. "
                 "Use an Application Password (WP Admin > Users > Profile > Application Passwords), "
                 "not your real login password.",
        "fields": [
            {"key": "WP_SITE_URL", "label": "WordPress site URL", "default": ""},
            {"key": "WP_USERNAME", "label": "WordPress username", "default": ""},
            {"key": "WP_APP_PASSWORD", "label": "Application password", "default": "", "secret": True},
        ],
    },
    {
        "id": "sheets",
        "title": "Google Sheet (review log)",
        "intro": "Create a blank Google Sheet, share it with the same service account email as Editor, "
                 "then paste its ID (from the URL) below.",
        "link": {"label": "Open Google Sheets", "url": "https://sheets.google.com"},
        "fields": [
            {"key": "GSHEETS_SHEET_ID", "label": "Sheet ID", "default": ""},
            {"key": "GSHEETS_LOG_TAB", "label": "Tab name", "default": "Run Log"},
        ],
    },
    {
        "id": "behavior",
        "title": "Run behavior",
        "intro": "Sensible defaults - most people can just accept these.",
        "fields": [
            {"key": "MAX_TOPICS_PER_RUN", "label": "Posts to draft per run", "default": "2"},
            {"key": "MIN_WORD_COUNT", "label": "Minimum words per post", "default": "1200"},
            {"key": "MAX_WORD_COUNT", "label": "Maximum words per post", "default": "1500"},
            {"key": "REVIVAL_IMPRESSION_THRESHOLD", "label": "Revival impression threshold", "default": "5000"},
            {"key": "GAP_IMPRESSION_THRESHOLD", "label": "Gap impression threshold", "default": "500"},
        ],
    },
]


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    values = {}
    for line in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip()
    return values


def save_config(updates: dict) -> None:
    """Merges `updates` into config.env, preserving the template's comments/
    layout (same approach as the CLI wizard used) so the file stays readable."""
    existing = load_config()
    existing.update({k: v for k, v in updates.items() if v is not None})

    lines = []
    if TEMPLATE_PATH.exists():
        for line in TEMPLATE_PATH.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key = line.split("=", 1)[0].strip()
                if key in existing:
                    lines.append(f"{key}={existing[key]}")
                    continue
            lines.append(line)
    else:
        lines = [f"{k}={v}" for k, v in existing.items()]

    CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def needs_setup() -> bool:
    values = load_config()
    for key in REQUIRED_FIELDS:
        if not values.get(key) or "your_" in values.get(key, ""):
            return True
    if (values.get("WRITER_PROVIDER") or "gemini").strip().lower() == "claude":
        if not values.get("ANTHROPIC_API_KEY"):
            return True
    return False


def masked_config() -> dict:
    """Returns config values safe to send to the browser - secrets replaced
    with a placeholder rather than ever echoing them back into the UI."""
    values = load_config()
    out = {}
    for key, val in values.items():
        if key in SECRET_FIELDS and val:
            out[key] = "\u2022" * 10 + " (saved - re-enter to change)"
        else:
            out[key] = val
    out["_service_account_present"] = SERVICE_ACCOUNT_PATH.exists()
    return out

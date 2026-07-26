"""
paths.py
---------
Centralizes every filesystem path the app touches, because a packaged
PyInstaller .exe/.app cannot safely assume "the current directory" the way
a script run with `python app.py` from a project folder can.

Two categories:
  RESOURCE_DIR - read-only files bundled INTO the app (static/, the config
                 template, the example product catalog). Inside a frozen
                 build these live under PyInstaller's extraction path
                 (sys._MEIPASS); in dev mode they're just next to this file.
  DATA_DIR     - files the app WRITES (config.env, the backlog, saved
                 drafts, the Google service account key). These must live
                 in a real per-user, always-writable location - NOT next
                 to the app bundle, which may not be writable and 
                 shouldn't be assumed to persist across an app update.
                 Uses the standard per-OS app-data location:
                   Windows: %APPDATA%\\BlogHero
                   Mac:     ~/Library/Application Support/BlogHero
                   Linux:   ~/.local/share/BlogHero
"""

import os
import sys
from pathlib import Path


def _resource_dir() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def _data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / "BlogHero"
    path.mkdir(parents=True, exist_ok=True)
    return path


RESOURCE_DIR = _resource_dir()
DATA_DIR = _data_dir()

STATIC_DIR = RESOURCE_DIR / "static"
CONFIG_TEMPLATE_PATH = RESOURCE_DIR / "config.env.example"

CONFIG_PATH = DATA_DIR / "config.env"
SERVICE_ACCOUNT_PATH = DATA_DIR / "gsheets_service_account.json"
BACKLOG_PATH = DATA_DIR / "topic_backlog.csv"
DRAFTS_DIR = DATA_DIR / "drafts"
GENERATED_IMAGES_DIR = DATA_DIR / "generated_images"

DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    print("RESOURCE_DIR:", RESOURCE_DIR, "(exists:", RESOURCE_DIR.exists(), ")")
    print("DATA_DIR:", DATA_DIR, "(exists:", DATA_DIR.exists(), ")")
    print("STATIC_DIR:", STATIC_DIR, "(exists:", STATIC_DIR.exists(), ")")
    print("CONFIG_PATH:", CONFIG_PATH)

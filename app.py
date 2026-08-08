"""
app.py
------
FastAPI backend for the BlogHero dashboard. Run directly for local
development (`python app.py`, then open http://127.0.0.1:8765), or launched
inside a native window by desktop.py for the packaged app.

Log streaming design: each research/write run executes as a SEPARATE
PROCESS via `multiprocessing` (pipeline_worker.py), not a background thread
and not a subprocess.exec(sys.executable, script) call - see
pipeline_worker.py's docstring for why both of those break in a frozen
PyInstaller build specifically.
"""

import asyncio
import csv
import io
import multiprocessing
import re
import shutil
import zipfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import config_store
import paths
import pipeline_worker
import research
import runner
import seo_research

app = FastAPI(title="BlogHero")

BACKLOG_PATH = paths.BACKLOG_PATH
DRAFTS_DIR = paths.DRAFTS_DIR
STATIC_DIR = paths.STATIC_DIR

RUN_STATE = {"running": False, "action": None, "paused": False}
# The multiprocessing.Manager (and the pause/stop Events it hands out) live
# for the lifetime of the currently-running job only - see start_run below.
_current_manager = None
_pause_event = None
_stop_event = None
_ws_clients: list[WebSocket] = []
_main_loop: asyncio.AbstractEventLoop | None = None


def build_credentials_zip_bytes() -> bytes:
    """Shared by the FastAPI /api/export-credentials route (used when
    running as a plain webpage, e.g. `python app.py` opened in a browser)
    AND by desktop.py's native pywebview save-file bridge (used by the
    actual packaged app - see desktop.py for why window.location.href-style
    downloads don't work inside a pywebview window). Keeping the zip-building
    logic in exactly one place means both call paths can never drift apart."""
    if not paths.CONFIG_PATH.exists():
        raise FileNotFoundError("Nothing to export yet - finish setup first.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(paths.CONFIG_PATH, arcname="config.env")
        if paths.SERVICE_ACCOUNT_PATH.exists():
            zf.write(paths.SERVICE_ACCOUNT_PATH, arcname="gsheets_service_account.json")
        readme = (
            "BlogHero credentials bundle\n"
            "----------------------------\n"
            "Contains config.env and (if present) the Google service account key.\n"
            "This includes API keys and other secrets in plain text.\n\n"
            "To use on another PC: install BlogHero, open it once (it'll show the setup\n"
            "wizard), then instead of filling the wizard, click Import credentials\n"
            "and pick this zip file. Everything will be filled in automatically.\n"
        )
        zf.writestr("README.txt", readme)
    return buf.getvalue()


def restore_credentials_from_zip_bytes(data: bytes) -> dict:
    """The import-side counterpart to build_credentials_zip_bytes - same
    shared-function pattern, same reason (FastAPI route + desktop.py native
    open-file bridge both call this)."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        if "config.env" not in names:
            raise ValueError("That zip doesn't contain a config.env - is this a BlogHero credentials bundle?")
        paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with zf.open("config.env") as src, open(paths.CONFIG_PATH, "wb") as dst:
            shutil.copyfileobj(src, dst)
        if "gsheets_service_account.json" in names:
            paths.SERVICE_ACCOUNT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with zf.open("gsheets_service_account.json") as src, open(paths.SERVICE_ACCOUNT_PATH, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return {"ok": True, "needs_setup": config_store.needs_setup()}


@app.on_event("startup")
async def _capture_loop():
    global _main_loop
    _main_loop = asyncio.get_running_loop()

    # First-run convenience: put a real, editable copy of the product
    # catalog template somewhere the user can actually find and edit it -
    # the bundled .example file lives inside the (possibly read-only,
    # possibly temporary) app bundle, not a normal folder.
    user_catalog = paths.DATA_DIR / "product_catalog.csv"
    bundled_example = paths.RESOURCE_DIR / "data" / "product_catalog.csv.example"
    if not user_catalog.exists() and bundled_example.exists():
        shutil.copy(bundled_example, user_catalog.with_suffix(".csv.example"))


async def _safe_send(ws: WebSocket, text: str):
    try:
        await ws.send_text(text)
    except Exception:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


# ---------------------------------------------------------------------------
# Static dashboard
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Setup / config
# ---------------------------------------------------------------------------

@app.get("/api/setup-schema")
async def setup_schema():
    return config_store.SETUP_STEPS


@app.get("/api/status")
async def status():
    return {
        "needs_setup": config_store.needs_setup(),
        "config": config_store.masked_config(),
        "running": RUN_STATE["running"],
    }


@app.post("/api/setup")
async def save_setup(updates: dict):
    # Never let a blank field silently overwrite a previously-saved secret -
    # only write fields that were actually given a non-empty value, EXCEPT
    # non-secret fields where blanking is a legitimate edit.
    existing = config_store.load_config()
    to_save = {}
    for key, val in updates.items():
        if key in config_store.SECRET_FIELDS and not val:
            continue  # keep whatever was already saved
        to_save[key] = val
    config_store.save_config(to_save)
    return {"ok": True, "needs_setup": config_store.needs_setup()}


@app.post("/api/upload-service-account")
async def upload_service_account(file: UploadFile = File(...)):
    paths.SERVICE_ACCOUNT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(paths.SERVICE_ACCOUNT_PATH, "wb") as out:
        shutil.copyfileobj(file.file, out)

    client_email = None
    try:
        import json
        with open(paths.SERVICE_ACCOUNT_PATH, encoding="utf-8") as f:
            client_email = json.load(f).get("client_email")
    except Exception:
        pass

    config_store.save_config({"GSHEETS_SERVICE_ACCOUNT_FILE": str(paths.SERVICE_ACCOUNT_PATH)})
    return {"ok": True, "client_email": client_email}


@app.get("/api/gsc-properties")
async def gsc_properties():
    cfg = config_store.load_config()
    if not paths.SERVICE_ACCOUNT_PATH.exists():
        return JSONResponse({"error": "No service account file uploaded yet."}, status_code=400)
    try:
        result = await run_in_threadpool(runner.check_gsc, cfg)
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ---------------------------------------------------------------------------
# Credentials export/import - "run BlogHero on any PC"
#
# Everything the app needs to run (config.env, including all API keys, plus
# the Google service account JSON) lives in paths.DATA_DIR. Zipping that up
# lets someone hand off a single file alongside the BlogHero app itself and
# have it work immediately on another machine, with no re-typing of keys.
#
# This intentionally includes secrets in plain text inside the zip - same
# trust model as sharing config.env directly. Only share this file the same
# way you'd share a password: not over public/unencrypted channels.
# ---------------------------------------------------------------------------

@app.get("/api/export-credentials")
async def export_credentials():
    try:
        data = build_credentials_zip_bytes()
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return StreamingResponse(
        io.BytesIO(data), media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=bloghero_credentials.zip"},
    )


@app.post("/api/import-credentials")
async def import_credentials(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        result = restore_credentials_from_zip_bytes(contents)
        return result
    except zipfile.BadZipFile:
        return JSONResponse({"error": "That file isn't a valid zip."}, status_code=400)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ---------------------------------------------------------------------------
# Backlog / drafts
# ---------------------------------------------------------------------------

@app.get("/api/backlog")
async def backlog():
    if not BACKLOG_PATH.exists():
        return []
    with open(BACKLOG_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@app.post("/api/backlog")
async def add_topic(payload: dict):
    """Manual 'Add topic' button on the dashboard - queues a topic directly,
    skipping Search Console entirely. See research.add_manual_topic()."""
    topic = (payload.get("topic") or "").strip()
    if not topic:
        return JSONResponse({"error": "Topic can't be empty."}, status_code=400)
    result = await run_in_threadpool(
        research.add_manual_topic, topic,
        payload.get("category", "General"), payload.get("priority", "Medium"),
    )
    if not result.get("ok"):
        return JSONResponse({"error": result.get("error", "Couldn't add that topic.")}, status_code=400)
    return result


@app.get("/api/drafts")
async def drafts():
    if not DRAFTS_DIR.exists():
        return []
    out = []
    for path in sorted(DRAFTS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        text = path.read_text(encoding="utf-8")
        title_match = re.search(r"^#\s*(.+)$", text, re.MULTILINE)
        meta_match = re.search(r"<!--\s*meta_description:\s*(.*?)\s*-->", text)
        flags_match = re.search(r"<!--\s*fact_check_flags:\s*(\d+)\s*-->", text)
        word_count_match = re.search(r"<!--\s*word_count:\s*(\d+)\s*-->", text)
        needs_review_match = re.search(r"<!--\s*NEEDS_REVIEW:\s*(.*?)\s*-->", text)
        out.append({
            "filename": path.name,
            "is_revival": path.name.startswith("REVIVAL_"),
            "title": title_match.group(1) if title_match else path.stem,
            "meta_description": meta_match.group(1) if meta_match else "",
            "fact_check_flags": int(flags_match.group(1)) if flags_match else 0,
            "word_count": int(word_count_match.group(1)) if word_count_match else None,
            "needs_review": needs_review_match.group(1) if needs_review_match else None,
            "preview": text[:600],
            "full_length": len(text),
        })
    return out


@app.get("/api/drafts/{filename}")
async def draft_content(filename: str):
    path = DRAFTS_DIR / filename
    resolved_drafts_dir = DRAFTS_DIR.resolve()
    if not path.exists() or resolved_drafts_dir not in path.resolve().parents:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"filename": filename, "content": path.read_text(encoding="utf-8")}


# ---------------------------------------------------------------------------
# Keyword research (on-demand, separate from the automatic per-topic brief)
# ---------------------------------------------------------------------------

@app.post("/api/keyword-research")
async def keyword_research(payload: dict):
    seed = (payload.get("seed") or "").strip()
    if not seed:
        return JSONResponse({"error": "Enter a seed topic or keyword first."}, status_code=400)
    cfg = config_store.load_config()
    if not cfg.get("GEMINI_API_KEY"):
        return JSONResponse({"error": "Gemini isn't configured yet - keyword research always uses Gemini, same as research."}, status_code=400)
    try:
        ideas = await run_in_threadpool(runner.run_keyword_research, cfg, seed)
        return {"seed": seed, "ideas": ideas}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ---------------------------------------------------------------------------
# Running the pipeline
# ---------------------------------------------------------------------------

async def _run_pipeline_process(action: str):
    global _current_manager, _pause_event, _stop_event
    manager = multiprocessing.Manager()
    queue = manager.Queue()
    pause_event = manager.Event()
    stop_event = manager.Event()
    _current_manager = manager
    _pause_event = pause_event
    _stop_event = stop_event

    process = multiprocessing.Process(
        target=pipeline_worker.worker_entry, args=(action, queue, pause_event, stop_event),
    )
    process.start()

    def _drain_queue():
        """Runs in a thread pool worker - blocking queue.get() calls are fine
        here since this thread does nothing else and never touches sys.stdout."""
        while True:
            item = queue.get()
            if item is None:
                break
            if _main_loop is not None:
                asyncio.run_coroutine_threadsafe(_broadcast(item), _main_loop)

    await run_in_threadpool(_drain_queue)
    await run_in_threadpool(process.join)
    RUN_STATE["running"] = False
    RUN_STATE["action"] = None
    RUN_STATE["paused"] = False
    _current_manager = None
    _pause_event = None
    _stop_event = None


async def _broadcast(text: str):
    print(text, end="")
    for ws in list(_ws_clients):
        await _safe_send(ws, text)


# IMPORTANT: these three specific routes MUST be registered before
# /api/run/{action} below. FastAPI/Starlette matches routes in registration
# order, so a wildcard path parameter registered first will swallow
# "/api/run/pause" etc. before they ever reach their own handlers - this was
# a real bug here (pause/resume/stop all silently fell into start_run's
# "Unknown action" branch instead of their own logic).
@app.post("/api/run/pause")
async def pause_run():
    """Only meaningful for a 'write' (or 'run-all') run - see runner.run_write,
    which is the only loop that actually checks this, between topics."""
    if not RUN_STATE["running"] or _pause_event is None:
        return JSONResponse({"error": "Nothing is running"}, status_code=409)
    _pause_event.set()
    RUN_STATE["paused"] = True
    return {"ok": True, "paused": True}


@app.post("/api/run/resume")
async def resume_run():
    if not RUN_STATE["running"] or _pause_event is None:
        return JSONResponse({"error": "Nothing is running"}, status_code=409)
    _pause_event.clear()
    RUN_STATE["paused"] = False
    return {"ok": True, "paused": False}


@app.post("/api/run/stop")
async def stop_run():
    if not RUN_STATE["running"] or _stop_event is None:
        return JSONResponse({"error": "Nothing is running"}, status_code=409)
    _stop_event.set()
    if _pause_event is not None:
        _pause_event.clear()  # unblock a paused loop so it can see stop_event and exit
    return {"ok": True, "stopping": True}


@app.post("/api/run/{action}")
async def start_run(action: str):
    if action not in ("research", "write", "run-all"):
        return JSONResponse({"error": "Unknown action"}, status_code=400)
    if RUN_STATE["running"]:
        return JSONResponse({"error": "A run is already in progress"}, status_code=409)
    if config_store.needs_setup():
        return JSONResponse({"error": "Setup isn't complete yet"}, status_code=400)

    RUN_STATE["running"] = True
    RUN_STATE["action"] = action
    RUN_STATE["paused"] = False
    asyncio.create_task(_run_pipeline_process(action))
    return {"ok": True, "action": action}


@app.get("/api/run-status")
async def run_status():
    return RUN_STATE


# ---------------------------------------------------------------------------
# Live log WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # just used to detect disconnect
    except WebSocketDisconnect:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)

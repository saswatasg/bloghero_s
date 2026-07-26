"""
app.py
------
FastAPI backend for the BlogHero dashboard. Run directly for local
development (`python app.py`, then open http://127.0.0.1:8765), or launched
inside a native window by desktop.py for the packaged app.

Log streaming design: each research/write run executes as a SEPARATE
SUBPROCESS (run_pipeline.py), not a background thread. An earlier version
used contextlib.redirect_stdout() in a background thread to capture the
existing modules' print() output - that mutates sys.stdout globally for the
whole process, and running it in a thread while the main thread (serving
other requests) also touches stdout caused a real, reproducible segfault
during testing. Subprocess isolation avoids that shared-mutable-state
problem entirely: the run gets its own real stdout, which this process
reads line-by-line and forwards to connected dashboard WebSockets.
"""

import asyncio
import csv
import re
import shutil
import sys
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import config_store
import runner

app = FastAPI(title="BlogHero")

BACKLOG_PATH = Path("data/topic_backlog.csv")
DRAFTS_DIR = Path("data/drafts")
STATIC_DIR = Path(__file__).parent / "static"
PIPELINE_SCRIPT = Path(__file__).parent / "run_pipeline.py"

RUN_STATE = {"running": False, "action": None}
_ws_clients: list[WebSocket] = []


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
    config_store.SERVICE_ACCOUNT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config_store.SERVICE_ACCOUNT_PATH, "wb") as out:
        shutil.copyfileobj(file.file, out)

    client_email = None
    try:
        import json
        with open(config_store.SERVICE_ACCOUNT_PATH, encoding="utf-8") as f:
            client_email = json.load(f).get("client_email")
    except Exception:
        pass

    config_store.save_config({"GSHEETS_SERVICE_ACCOUNT_FILE": str(config_store.SERVICE_ACCOUNT_PATH)})
    return {"ok": True, "client_email": client_email}


@app.get("/api/gsc-properties")
async def gsc_properties():
    cfg = config_store.load_config()
    if not config_store.SERVICE_ACCOUNT_PATH.exists():
        return JSONResponse({"error": "No service account file uploaded yet."}, status_code=400)
    try:
        result = await run_in_threadpool(runner.check_gsc, cfg)
        return result
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
        out.append({
            "filename": path.name,
            "is_revival": path.name.startswith("REVIVAL_"),
            "title": title_match.group(1) if title_match else path.stem,
            "meta_description": meta_match.group(1) if meta_match else "",
            "fact_check_flags": int(flags_match.group(1)) if flags_match else 0,
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
# Running the pipeline
# ---------------------------------------------------------------------------

async def _run_pipeline_subprocess(action: str, cfg: dict):
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(PIPELINE_SCRIPT), action,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(Path(__file__).parent),
    )
    try:
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            text = line.decode(errors="replace")
            sys.__stdout__.write(text)
            for ws in list(_ws_clients):
                await _safe_send(ws, text)
        await process.wait()
    finally:
        RUN_STATE["running"] = False
        RUN_STATE["action"] = None


@app.post("/api/run/{action}")
async def start_run(action: str):
    if action not in ("research", "write", "run-all"):
        return JSONResponse({"error": "Unknown action"}, status_code=400)
    if RUN_STATE["running"]:
        return JSONResponse({"error": "A run is already in progress"}, status_code=409)
    if config_store.needs_setup():
        return JSONResponse({"error": "Setup isn't complete yet"}, status_code=400)

    cfg = config_store.load_config()
    RUN_STATE["running"] = True
    RUN_STATE["action"] = action
    asyncio.create_task(_run_pipeline_subprocess(action, cfg))
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

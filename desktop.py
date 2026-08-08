"""
desktop.py
-----------
Entry point for the packaged desktop app. Starts the FastAPI backend on a
local port in a background thread, then opens it inside a native window via
pywebview (no visible address bar/browser chrome - looks like installed
software rather than "open your browser and go to localhost").

IMPORTANT - honest limitation: this file could not be executed/tested in
the sandbox this was built in (no display server available in a headless
Linux container). It's written to pywebview's documented API as of when
this was built, but the FIRST real test of this file has to happen on an
actual Windows or Mac machine (or via the GitHub Actions build - see
.github/workflows/build.yml). If it doesn't open a window correctly,
check:
  1. `pip show pywebview` - confirm it installed its native backend deps
     (on Windows this pulls in pythonnet/edgechromium bits automatically)
  2. Run `python app.py` directly instead, then open the printed URL in a
     regular browser - this isolates whether the problem is the FastAPI
     backend or the pywebview wrapper specifically.

Credentials export/import bridge - why this exists:
pywebview's window is a native OS webview, NOT a full browser. It has no
download manager, so navigating to a URL that returns a file attachment
(what the "Export credentials" button used to do via window.location.href)
silently does nothing inside the packaged app, even though it works fine
when the same page is opened in a real browser during development - which
is exactly why this bug wasn't caught by dev-mode testing. The fix is to
give the page a genuine bridge into Python (`js_api`) that opens a native
Save/Open file dialog and writes bytes directly to whatever path the user
picks - no HTTP round-trip, no browser download behavior required at all.
"""

import multiprocessing
import platform
import socket
import threading
import time

import uvicorn
import webview

import app as app_module


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_server(port: int):
    config = uvicorn.Config(app_module.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


def _wait_for_server(port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


class Api:
    """Exposed to the page as `window.pywebview.api.*` - see static/app.js,
    which calls these instead of a browser-style download/upload whenever
    it detects it's running inside the packaged app (window.pywebview is
    only present there, never when app.py is opened directly in a browser
    during development - app.js falls back to the old HTTP-based flow in
    that case, so both dev and packaged modes keep working)."""

    def export_credentials(self):
        try:
            data = app_module.build_credentials_zip_bytes()
        except FileNotFoundError as e:
            return {"ok": False, "error": str(e)}
        window = webview.windows[0]
        result = window.create_file_dialog(
            webview.SAVE_DIALOG, directory="", save_filename="bloghero_credentials.zip",
        )
        # create_file_dialog returns None (cancelled) or a tuple/str depending
        # on platform/pywebview version - normalize both.
        if not result:
            return {"ok": False, "error": "cancelled"}
        target_path = result[0] if isinstance(result, (list, tuple)) else result
        with open(target_path, "wb") as f:
            f.write(data)
        return {"ok": True, "path": target_path}

    def import_credentials(self):
        window = webview.windows[0]
        result = window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=False, file_types=("Zip files (*.zip)", "All files (*.*)"),
        )
        if not result:
            return {"ok": False, "error": "cancelled"}
        source_path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            with open(source_path, "rb") as f:
                data = f.read()
            return app_module.restore_credentials_from_zip_bytes(data)
        except Exception as e:
            return {"ok": False, "error": str(e)}


def main():
    port = _find_free_port()
    print(f"Starting BlogHero on {platform.system()} (port {port})...")

    server_thread = threading.Thread(target=_run_server, args=(port,), daemon=True)
    server_thread.start()

    if not _wait_for_server(port):
        print("Server didn't respond in time - something may have failed to start.")

    url = f"http://127.0.0.1:{port}"
    api = Api()
    window = webview.create_window(
        "BlogHero", url,
        width=1320, height=880, min_size=(960, 640),
        js_api=api,
    )
    # gui=None lets pywebview auto-pick the right native backend per OS
    # (EdgeChromium on Windows, Cocoa/WebKit on Mac) - no manual OS branching needed.
    webview.start()


if __name__ == "__main__":
    multiprocessing.freeze_support()  # required for multiprocessing inside a frozen app (esp. Windows)
    main()

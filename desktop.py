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
"""

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


def main():
    port = _find_free_port()
    print(f"Starting BlogHero on {platform.system()} (port {port})...")

    server_thread = threading.Thread(target=_run_server, args=(port,), daemon=True)
    server_thread.start()

    if not _wait_for_server(port):
        print("Server didn't respond in time - something may have failed to start.")

    url = f"http://127.0.0.1:{port}"
    window = webview.create_window(
        "BlogHero", url,
        width=1320, height=880, min_size=(960, 640),
    )
    # gui=None lets pywebview auto-pick the right native backend per OS
    # (EdgeChromium on Windows, Cocoa/WebKit on Mac) - no manual OS branching needed.
    webview.start()


if __name__ == "__main__":
    main()

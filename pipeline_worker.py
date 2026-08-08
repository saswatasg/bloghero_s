"""
pipeline_worker.py
-------------------
Runs one pipeline job (research/write/run-all) in a genuinely separate
PROCESS, launched via Python's `multiprocessing` module rather than
`subprocess.exec(sys.executable, "some_script.py", ...)`.

Why not subprocess + sys.executable: that works fine in development, where
sys.executable is a real Python interpreter. Inside a PyInstaller-frozen
app, sys.executable IS THE PACKAGED APP ITSELF - there's no separate
interpreter to hand a script filename to. `multiprocessing.Process` is the
approach PyInstaller explicitly supports for this (see
multiprocessing.freeze_support() in desktop.py's entry point) - it knows
how to correctly re-invoke a frozen executable to run a specific worker
function rather than restarting the whole app from main().

Why a separate process at all (vs. a thread): redirecting stdout to capture
print() output is only safe here because each run gets ITS OWN process,
with its own private sys.stdout - no shared mutable state with the main
app to race on. An earlier thread-based design that used
contextlib.redirect_stdout() in a background thread caused a real,
reproducible segfault (that mutates sys.stdout globally for the whole
process). This design avoids that class of bug entirely.
"""

import contextlib
import io

import config_store
import runner


class _QueueWriter(io.TextIOBase):
    """Every line written here goes onto a multiprocessing Queue instead of
    a real stdout - safe to do because this only ever runs inside its own
    freshly-spawned process, so there's nothing else touching sys.stdout
    to race against."""

    def __init__(self, queue):
        self.queue = queue

    def write(self, text):
        if text:
            self.queue.put(text)
        return len(text)

    def flush(self):
        pass


def worker_entry(action: str, queue, pause_event=None, stop_event=None):
    """Entry point for the child process. Puts a final `None` sentinel onto
    the queue when done (success or failure) so the parent knows to stop
    reading. pause_event/stop_event are multiprocessing.Manager Events,
    created fresh per run in app.py and passed down here - see runner.py's
    run_write for how they're checked (between topics only)."""
    writer = _QueueWriter(queue)
    with contextlib.redirect_stdout(writer):
        try:
            cfg = config_store.load_config()
            if action in ("research", "run-all"):
                runner.run_research(cfg)
            if action in ("write", "run-all"):
                runner.run_write(cfg, pause_event=pause_event, stop_event=stop_event)
            print(">>> Done.")
        except Exception as e:
            print(f">>> Run failed: {e}")
    queue.put(None)

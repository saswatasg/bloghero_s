"""
run_pipeline.py
-----------------
Standalone entry point for one pipeline run, launched as a SUBPROCESS by
app.py rather than a background thread. This is deliberate: the original
thread-based design used contextlib.redirect_stdout() to capture print()
output for the dashboard's live log, but redirect_stdout mutates sys.stdout
globally for the WHOLE PROCESS, not just the calling thread - running that
in a background thread while the main thread (serving other API requests)
also touches stdout caused a real, reproducible segfault during testing.

Running as a subprocess instead means each run gets its own real stdout,
with zero shared mutable state to race on. app.py reads this subprocess's
stdout line-by-line and forwards it to connected dashboard WebSockets.
"""

import sys

import config_store
import runner


def main():
    if len(sys.argv) < 2:
        print(">>> Run failed: no action specified")
        return
    action = sys.argv[1]
    cfg = config_store.load_config()
    try:
        if action in ("research", "run-all"):
            runner.run_research(cfg)
        if action in ("write", "run-all"):
            runner.run_write(cfg)
        print(">>> Done.")
    except Exception as e:
        print(f">>> Run failed: {e}")


if __name__ == "__main__":
    main()

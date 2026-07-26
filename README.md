# BlogHero

A desktop dashboard for Sierra Living Concepts' content pipeline: pulls real
Google Search Console data, finds revival/gap opportunities, drafts blog
posts with Gemini, creates WordPress drafts, and logs everything to a
Google Sheet - all through a proper app window, not a terminal.

No coding experience needed to *use* the finished app - download the right
installer, open it, and a setup wizard walks you through everything with
plain-English explanations and links to exactly where to go.

---

## How this is built (architecture, for reference)

- **`app.py`** - a FastAPI backend serving both a JSON API and the dashboard's
  static files (`static/index.html`, `style.css`, `app.js`).
- **`research.py`, `content_writer.py`, `gsc_client.py`, `image_handler.py`,
  `wordpress_publisher.py`, `sheets_logger.py`** - the actual pipeline logic
  (unchanged from the earlier CLI version of this tool - same tested logic,
  now called from API routes instead of command-line arguments).
- **`runner.py`** - wires the pipeline modules together for one research/write
  run.
- **`run_pipeline.py`** - a small standalone script that runs one pipeline
  action (research/write/run-all). Deliberately run as a **subprocess**, not
  a background thread - see "Why a subprocess" below.
- **`config_store.py`** - the single schema both the web setup wizard and
  `config.env` read from, so they can never drift out of sync.
- **`desktop.py`** - wraps the FastAPI server in a native window via
  `pywebview`, so the packaged app looks like installed software, not "open
  your browser and go to localhost".
- **`.github/workflows/build.yml`** - GitHub Actions CI that builds a real
  Windows `.exe` (on a GitHub-hosted Windows machine) and a real Mac `.app`
  (on a GitHub-hosted Mac machine) automatically, with no Python installed
  needed on your end at all - not for building, and not for using the result.

### Why a subprocess instead of a background thread
An earlier version of this ran each research/write job in a background
thread and captured its `print()` output via `contextlib.redirect_stdout()`
to stream into the dashboard's live log. That's a real bug, not just a style
choice: `redirect_stdout` swaps `sys.stdout` **globally for the entire
process**, not just the calling thread. Running that in a background thread
while the main thread (serving other dashboard requests) also touches
stdout caused a reproducible segfault during testing. Running each pipeline
job as a separate subprocess instead means it gets its own real stdout, with
nothing shared to race on - `app.py` just reads that subprocess's output
line by line and forwards it to the dashboard's WebSocket. Confirmed this
actually fixes it by reproducing the crash, then re-running the identical
scenario after the fix with a clean exit.

---

## Running it in development (before a packaged build exists)

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Then open **http://127.0.0.1:8765** in any browser. This runs the exact same
backend the packaged app will use - useful for testing changes without
waiting for a full PyInstaller build.

To test the actual native-window wrapper locally (only meaningful if you
have a real display - this could not be tested in the sandbox this was
built in, since it had no display server):
```bash
python desktop.py
```

---

## Getting an actual installer (Windows .exe / Mac .app)

This repo's CI builds both automatically. To trigger it:

```bash
git tag v1.0
git push --tags
```

Then check the **Actions** tab on GitHub - two jobs run (`build-windows`,
`build-mac`), each on GitHub's own hardware for that OS. Once they finish
(a few minutes), a **Release** is created automatically with both files
attached:
- `BlogHero.exe` - just double-click it on Windows, no install step
- `BlogHero-Mac.zip` - unzip it, drag `BlogHero.app` to Applications on Mac

Anyone can then download the file for their OS from the repo's Releases
page and just open it. No Python, no terminal, no `pip install` - the
PyInstaller build bundles Python itself inside the executable.

You can also trigger a build any time without a new version tag, from the
**Actions** tab → "Build BlogHero Desktop App" → "Run workflow".

---

## What's been tested vs. what genuinely needs a real machine to confirm

Built in a headless Linux container with no display and no access to a
real Windows or Mac machine, so here's an honest split:

**Fully tested here (all pass):**
- Every API route (`/api/status`, `/api/setup`, `/api/backlog`, `/api/drafts`,
  `/api/run/{action}`, `/api/gsc-properties`) via FastAPI's TestClient
- The WebSocket log stream, confirmed to actually deliver live output from a
  real subprocess run
- The full server-launch sequence `desktop.py` uses (finding a free port,
  starting `uvicorn` in a background thread, waiting for it to respond) -
  tested with a real HTTP server and real requests, not just TestClient
- The subprocess-vs-thread stdout bug: reproduced the segfault, then
  confirmed the fix resolves it with the identical test scenario
- A path-traversal safety check that was silently broken (comparing a
  relative path against resolved absolute paths, so it rejected legitimate
  files too) - found and fixed

**Cannot be tested until run on a real machine or through the CI pipeline:**
- `pywebview` actually opening a native window (no display here to render one)
- The PyInstaller builds themselves - whether `--add-data` paths resolve
  correctly inside a frozen `.exe`/`.app`, whether pywebview's native
  backend (EdgeChromium on Windows, WebKit on Mac) bundles correctly
- Any Windows-specific or Mac-specific pywebview rendering quirks

If the first CI build fails or the window doesn't open correctly, the
fastest way to isolate the problem is `python app.py` + a regular browser
(confirms the backend is fine) vs. `python desktop.py` on that same machine
(isolates it to the pywebview wrapper specifically).

---

## The wizard, dashboard, and everything else

Functionally identical to the earlier CLI tool's setup wizard and pipeline -
same questions, same "where to get it" explanations, same revival/gap
logic, same fact-checking pass, same "drafts only, never auto-publish"
behavior. The only thing that changed is *how* you interact with it: a real
app window instead of typing commands into a terminal.

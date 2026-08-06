# BlogHero

A desktop dashboard for Sierra Living Concepts' content pipeline: pulls real
Google Search Console data (scoped to blog pages only), runs a detailed SEO
research pass, drafts blog posts with Gemini or Claude, humanizes the prose,
creates WordPress drafts, and logs everything to a Google Sheet - all
through a proper app window, not a terminal.

No coding experience needed to *use* the finished app - download the right
installer, open it, and a setup wizard walks you through everything with
plain-English explanations and links to exactly where to go.

---

## What's new in this update

1. **Research is now scoped to blog pages only.** Previously it pulled GSC
   data for every page on the site. Now it's filtered (both server-side via
   GSC's own API filter, and again client-side as a safety net) to pages
   containing `SITE_BLOG_PATH` (default `/blog/`, editable in Setup > Your
   website). See `research.py` and `gsc_client.py`.
2. **Export/Import credentials, so the app runs on any PC.** Dashboard →
   "Export credentials" downloads a zip with `config.env` (all your API
   keys) and the Google service account JSON. Share that zip alongside the
   installer, and on the new machine: open the app, click "Import
   credentials" on the setup screen, pick the zip - done, no retyping keys.
   See the `/api/export-credentials` and `/api/import-credentials` routes
   in `app.py`. The zip contains secrets in plain text - treat it like a
   password, don't share it over public channels.
3. **Clearer dashboard UI.** "Run Research" / "Run Write" are now "Find new
   topics" (step 1) and "Write queued posts" (step 2), each with a plain-
   English explanation of what it actually does directly underneath it.
   There's also a new **"+ Add a topic manually"** button for queuing a
   topic without waiting on Search Console data at all.
4. **A detailed SEO research step, before drafting.** New `seo_research.py`
   module: for each topic, before it's written, generates a proper research
   brief (search intent, target keyword phrases, suggested subheadings,
   real "people also ask" questions, competitive gap, internal-link ideas).
   The draft prompt is built around this brief instead of just a topic
   string. This step always uses Gemini.
5. **Choice of writing model: Gemini or Claude.** New "Writing model" setup
   step (`WRITER_PROVIDER` in config.env). Drafting, fact-checking, the
   humanize pass, and SEO metadata generation all follow this choice.
   Research (above) always stays on Gemini regardless of this setting.
6. **A humanize pass before anything is finalized.** After fact-checking
   the raw draft (so factual flags are based on the real claims, not
   post-polish phrasing), a new pass smooths out AI-writing tells - robotic
   transitions, repetitive sentence rhythm, generic hedging - while
   explicitly preserving every `[VERIFY: ...]` marker, all headings, and
   the word count. SEO metadata is then generated from this final text.

---

## How this is built (architecture, for reference)

- **`app.py`** - a FastAPI backend serving both a JSON API and the dashboard's
  static files (`static/index.html`, `style.css`, `app.js`).
- **`research.py`, `seo_research.py`, `content_writer.py`, `gsc_client.py`,
  `image_handler.py`, `wordpress_publisher.py`, `sheets_logger.py`** - the
  pipeline logic. `research.py` decides WHICH topics are worth writing (from
  GSC gap/CTR data, scoped to blog pages); `seo_research.py` does detailed
  per-topic research (always Gemini) BEFORE drafting; `content_writer.py`
  drafts/fact-checks/humanizes/generates metadata (Gemini or Claude, per
  `WRITER_PROVIDER`).
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

### Two bugs found only after the first real build ran on actual hardware

**1. Frozen apps can't subprocess `sys.executable script.py`.** The first
version ran each research/write job as a separate subprocess
(`subprocess.exec(sys.executable, "run_pipeline.py", action)`) to avoid a
different bug (see below). That's correct in development, where
`sys.executable` is a real Python interpreter - but inside a
PyInstaller-frozen app, `sys.executable` **is the packaged app itself**,
with no separate interpreter to hand a script filename to. Switched to
Python's `multiprocessing` module instead (`pipeline_worker.py` +
`multiprocessing.Process`), which is what PyInstaller explicitly documents
support for (`multiprocessing.freeze_support()` in `desktop.py`'s entry
point). Log streaming still works the same way from the dashboard's point
of view - the worker process pushes lines onto a `multiprocessing.Queue`
instead of a stdout pipe, and a background thread drains that queue and
forwards to the WebSocket.

**2. Relative paths ("config.env", "data/...") don't mean anything
predictable once double-clicked from Finder/Explorer.** Everything
originally assumed it could read/write files relative to "wherever the app
happens to be running from" - fine for `python app.py` in a project folder,
not fine for a packaged app launched by double-clicking, where the working
directory is unpredictable and may not even be writable. Added
**`paths.py`**, which splits every path into two categories: bundled
read-only resources (resolved via PyInstaller's `sys._MEIPASS` when frozen)
and user-writable data (`config.env`, the backlog, saved drafts, the Google
service account key), which now go to the standard per-OS app-data folder
(`~/Library/Application Support/BlogHero` on Mac, `%APPDATA%\BlogHero` on
Windows) instead of next to the app.

Why the original thread-based design was replaced with subprocess (and then
subprocess with multiprocessing): an even earlier version ran each job in a
background **thread** and captured its `print()` output via
`contextlib.redirect_stdout()`. That call swaps `sys.stdout` **globally for
the entire process**, not just the calling thread - running that in a
background thread while the main thread (serving other dashboard requests)
also touches stdout caused a reproducible segfault. Both later designs
(subprocess, then multiprocessing) exist specifically to give each run its
own private stdout with nothing shared to race on.

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

"""
runner.py
----------
The actual research/write pipeline - same logic as the CLI tool's main.py,
adapted to be called from API routes instead of argparse commands. Anything
that used input() or print()-only CLI flow has been removed; print()
statements stay, since app.py captures stdout to stream into the dashboard's
live log panel.

Queue ordering: GAP/MANUAL (new topics) are ALWAYS written before any
REVIVAL, regardless of priority level - see _load_queued_topics.

Write pipeline per GAP/MANUAL topic, in order:
  1. seo_research.build_brief()        - detailed research brief (always Gemini)
  1b. internal_links.build_link_index() - real, verified internal link candidates
  2. content_writer.draft_post()       - draft with a strict 1200-1500 word
                                          gate (both bounds enforced, Gemini
                                          or Claude per config)
  3. content_writer.fact_check()       - flags claims to verify, on the RAW draft
  4. content_writer.humanize_draft()   - polish pass with the same 1200-1500
                                          gate re-checked on the FINAL text
  5. content_writer.generate_seo_metadata() - metadata from the FINAL text
  6. image_handler.select_images_for_post() + embed body images inline
  7. save locally + optionally push a WordPress draft + log to Sheet
"""

import csv
import time

import content_writer
import gsc_client
import image_handler
import internal_links
import paths
import research
import seo_research
import sheets_logger
import wordpress_publisher

BACKLOG_PATH = paths.BACKLOG_PATH
DRAFTS_DIR = paths.DRAFTS_DIR


def _load_queued_topics(limit: int) -> list:
    """New topics (GAP/MANUAL) are ALWAYS processed before any REVIVAL,
    regardless of priority level - a Critical REVIVAL still waits behind a
    Low-priority GAP. Within each of those two groups, priority still
    applies. This is a deliberate, strict rule (not just a sort-order
    nudge): growing the content library takes precedence over touching up
    what already exists, every run."""
    if not BACKLOG_PATH.exists():
        return []
    with open(BACKLOG_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    queued = [r for r in rows if r["status"] == "queued"]
    priority_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    type_order = {"GAP": 0, "MANUAL": 0, "REVIVAL": 1}
    queued.sort(key=lambda r: (type_order.get(r["type"], 0), priority_order.get(r["priority"], 9)))
    return queued[:limit]


def _mark_status(topic_id: str, new_status: str):
    with open(BACKLOG_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r["id"] == topic_id:
            r["status"] = new_status
    with open(BACKLOG_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=research.BACKLOG_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def run_research(cfg: dict):
    print(">>> Step 1: Research - pulling GSC data and updating the backlog...")
    print("    (REVIVAL uses blog pages only; GAP uses the whole site, so a query already")
    print("     covered by any well-ranking page - blog or not - is correctly excluded.)")
    added = research.run_research(
        cfg["GSHEETS_SERVICE_ACCOUNT_FILE"], cfg["GSC_SITE_URL"],
        int(cfg.get("REVIVAL_IMPRESSION_THRESHOLD", 5000)),
        int(cfg.get("GAP_IMPRESSION_THRESHOLD", 500)),
        cfg.get("SITE_BLOG_PATH", "/blog/"),
    )
    print(f">>> Research complete. {added} new topic(s) added to the backlog.")
    return added


def run_keyword_research(cfg: dict, seed: str) -> list:
    """Powers the dashboard's on-demand 'Keyword research' panel. Combines
    three sources, each doing a different honest job:

      1. seo_research.research_keywords()  - AI-generated ideas (Gemini)
      2. research.find_query_data()        - your OWN real GSC history,
                                              wherever it exists
      3. free_keyword_tools                - Google Autocomplete (real
                                              phrases Google itself
                                              suggests) + Google Trends
                                              (relative interest/direction,
                                              NOT absolute volume)

    None of these ever fabricates a search-volume number - see
    free_keyword_tools.py's docstring for why that's a deliberate line and
    what a paid/registered upgrade path (Google Keyword Planner) would add."""
    ideas = seo_research.research_keywords(
        gemini_api_key=cfg["GEMINI_API_KEY"], gemini_model=cfg.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash"),
        seed=seed,
    )

    # --- Your own real GSC history, if configured ---
    real_data = []
    if cfg.get("GSHEETS_SERVICE_ACCOUNT_FILE") and cfg.get("GSC_SITE_URL"):
        real_data = research.find_query_data(
            cfg["GSHEETS_SERVICE_ACCOUNT_FILE"], cfg["GSC_SITE_URL"], seed, cfg.get("SITE_BLOG_PATH", "/blog/"),
        )
    real_by_signature = {research._normalize_query(r["query"]): r for r in real_data}
    for idea in ideas:
        match = real_by_signature.get(research._normalize_query(idea["keyword"]))
        idea["real_data"] = match  # None if no GSC history exists for this idea yet
    # Also surface any real query the model didn't happen to suggest -
    # actual search history is worth showing even if the AI missed it.
    suggested_sigs = {research._normalize_query(i["keyword"]) for i in ideas}
    for r in real_data:
        if research._normalize_query(r["query"]) not in suggested_sigs:
            ideas.append({"keyword": r["query"], "intent": "from your search data", "why": "", "real_data": r})
            suggested_sigs.add(research._normalize_query(r["query"]))

    # --- Google Autocomplete: real phrases Google itself suggests ---
    import free_keyword_tools

    print("  Checking Google Autocomplete for real phrasing...")
    autocomplete = free_keyword_tools.get_autocomplete_suggestions(seed)
    for phrase in autocomplete:
        sig = research._normalize_query(phrase)
        if sig not in suggested_sigs:
            ideas.append({"keyword": phrase, "intent": "from Google Autocomplete", "why": "", "real_data": None})
            suggested_sigs.add(sig)

    # --- Google Trends: relative interest + direction, top phrases only ---
    # Capped at 5 (Trends' own per-request limit) - the seed plus the
    # highest-value ideas (real GSC data first, since those are already
    # proven demand; AI ideas fill any remaining slots).
    print("  Checking Google Trends for interest direction...")
    priority_order = sorted(ideas, key=lambda i: 0 if i.get("real_data") else 1)
    trend_targets = [seed] + [i["keyword"] for i in priority_order if i["keyword"].lower() != seed.lower()]
    trends = free_keyword_tools.get_trends_interest(trend_targets, max_keywords=5)
    for idea in ideas:
        idea["trend"] = trends.get(idea["keyword"])  # None if not in the capped batch or no signal

    return ideas


def _embed_body_images(cfg: dict, md: str, body_images: list) -> str:
    """Resolves each body image to an embeddable URL (uploads AI-generated
    local files to WordPress media if configured, uses real product photo
    URLs directly - see wordpress_publisher.resolve_image_url) and inserts
    markdown image syntax after the 1st and roughly-middle H2 heading.
    Images that fail to resolve are skipped, not left as broken links."""
    if not body_images:
        return md

    resolved = []
    for img in body_images:
        if cfg.get("WP_SITE_URL") and cfg.get("WP_USERNAME"):
            url = wordpress_publisher.resolve_image_url(
                cfg["WP_SITE_URL"], cfg["WP_USERNAME"], cfg.get("WP_APP_PASSWORD", ""), img["ref"],
            )
        else:
            # No WordPress configured - use directly if already a public
            # URL (real product photo); a local AI-generated file can't be
            # embedded as a working web image without an upload target, so
            # skip it in local-only mode rather than write a broken link.
            url = img["ref"] if img["ref"].startswith("http") else ""
        if url:
            resolved.append(f'![{img["alt"]}]({url})')
        else:
            print(f"  Skipping one body image (couldn't resolve a usable URL): {img['ref']}")

    if not resolved:
        return md

    lines = md.split("\n")
    h2_indices = [i for i, line in enumerate(lines) if line.strip().startswith("## ")]
    if not h2_indices:
        # No H2 headings found (unexpected but not fatal) - just append images at the end.
        return md + "\n\n" + "\n\n".join(resolved) + "\n"

    insert_at = []
    if len(resolved) >= 1:
        insert_at.append(h2_indices[0])  # right after the first H2 section starts
    if len(resolved) >= 2 and len(h2_indices) > 1:
        insert_at.append(h2_indices[len(h2_indices) // 2])
    elif len(resolved) >= 2:
        insert_at.append(h2_indices[0])  # only one H2 - both go near it, still valid

    # Insert from the bottom up so earlier insertions don't shift later indices.
    for image_md, idx in sorted(zip(resolved, insert_at), key=lambda x: x[1], reverse=True):
        lines.insert(idx + 1, "")
        lines.insert(idx + 2, image_md)
        lines.insert(idx + 3, "")
    return "\n".join(lines)


def _handle_gap(cfg, t):
    # Step 1 of writing: detailed SEO research brief for THIS topic - always
    # Gemini, independent of WRITER_PROVIDER (see seo_research.py docstring).
    try:
        brief = seo_research.build_brief(
            gemini_api_key=cfg["GEMINI_API_KEY"], gemini_model=cfg.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash"),
            topic=t["topic_or_page"], category=t["category"], evidence=t["evidence"],
        )
    except Exception as e:
        print(f"  SEO research step failed, continuing without a brief: {e}")
        brief = {}

    # Step 1b: build/reuse the internal link index and shortlist candidates
    # for THIS topic - real, verified pages only (see internal_links.py).
    try:
        link_index = internal_links.build_link_index(cfg)
        link_candidates = internal_links.shortlist_relevant_links(
            link_index, topic=t["topic_or_page"], category=t["category"], max_candidates=12,
        )
        print(f"  {len(link_candidates)} internal link candidate(s) shortlisted for this topic.")
    except Exception as e:
        print(f"  Internal link index unavailable, continuing without link candidates: {e}")
        link_candidates = []

    # Step 2: first draft, on whichever provider WRITER_PROVIDER selects.
    # Includes the hard word-count gate (up to 4 attempts) and internal-link
    # validation - see content_writer.draft_post.
    provider = (cfg.get("WRITER_PROVIDER") or "gemini").strip().lower()
    print(f"  Drafting with {'Claude' if provider == 'claude' else 'Gemini'}...")
    min_words = int(cfg.get("MIN_WORD_COUNT", 1200))
    max_words = int(cfg.get("MAX_WORD_COUNT", 1500))
    draft_result = content_writer.draft_post(
        cfg=cfg, topic=t["topic_or_page"], category=t["category"], evidence=t["evidence"],
        min_words=min_words, max_words=max_words,
        brief=brief, internal_link_candidates=link_candidates,
    )
    draft_md = draft_result["draft"]

    # Step 3: fact-check the RAW draft, before any stylistic polishing.
    flags = content_writer.fact_check(cfg=cfg, draft=draft_md)

    # Step 4: humanize pass - polish tone/rhythm, keep facts, [VERIFY:...],
    # and internal links intact (explicitly instructed not to touch markdown links).
    # Also re-enforces the 1200-1500 word gate on the FINAL text - the count
    # stored and reviewed below is the humanized one, not the raw draft's.
    print("  Running humanize pass...")
    humanized = content_writer.humanize_draft(cfg=cfg, draft=draft_md, min_words=min_words, max_words=max_words)
    final_md = humanized["text"]
    final_count = humanized["word_count"]
    final_length_ok = humanized["in_range"]

    # Step 5: SEO metadata from the FINAL (humanized) text.
    seo = content_writer.generate_seo_metadata(cfg=cfg, draft=final_md)

    # Step 6: images - hero (featured image) + up to 2 in-body images,
    # embedded directly into the post content.
    images = image_handler.select_images_for_post(
        api_key=cfg["GEMINI_API_KEY"], image_model=cfg.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image"),
        topic=t["topic_or_page"], category=t["category"],
    )
    final_md = _embed_body_images(cfg, final_md, images.get("body_images", []))

    safe_name = "".join(c if c.isalnum() else "_" for c in t["topic_or_page"].lower())[:60]
    local_path = DRAFTS_DIR / f"{safe_name}.md"
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(f"# {seo.get('title') or t['topic_or_page']}\n\n")
        f.write(f"<!-- meta_description: {seo.get('meta_description', '')} -->\n")
        f.write(f"<!-- fact_check_flags: {len(flags)} -->\n")
        f.write(f"<!-- written_with: {provider} -->\n")
        f.write(f"<!-- word_count: {final_count} -->\n")
        if not final_length_ok:
            f.write(f"<!-- NEEDS_REVIEW: word count {final_count} is outside the "
                     f"{min_words}-{max_words} target after drafting and the humanize pass -->\n")
        f.write("\n")
        f.write(final_md)
    print(f"Saved local draft: {local_path}")
    if not final_length_ok:
        print(f"  NEEDS REVIEW: final word count ({final_count}) is outside the {min_words}-{max_words} target.")

    edit_link = ""
    if cfg.get("WP_SITE_URL") and cfg.get("WP_USERNAME"):
        try:
            title = seo.get("title") or t["topic_or_page"]
            if not final_length_ok:
                title = f"[NEEDS REVIEW - word count] {title}"
            result = wordpress_publisher.create_draft_post(
                site_url=cfg["WP_SITE_URL"], username=cfg["WP_USERNAME"], app_password=cfg["WP_APP_PASSWORD"],
                title=title, markdown_body=final_md, slug=seo.get("slug", ""),
                meta_description=seo.get("meta_description", ""), featured_image_url=images.get("hero_image", ""),
            )
            edit_link = result["edit_link"]
            print(f"Created WordPress draft: {edit_link}")
        except Exception as e:
            print(f"WordPress draft creation failed (saved locally instead): {e}")
    else:
        print("WordPress not configured - local file only.")

    _log_to_sheet(cfg, t, edit_link or str(local_path), images.get("source", ""), len(flags), final_count)


def _handle_revival(cfg, t):
    fix = content_writer.draft_revival_fix(
        cfg=cfg, topic=t["topic_or_page"], category=t["category"], evidence=t["evidence"],
    )
    safe_name = "".join(c if c.isalnum() else "_" for c in t["topic_or_page"].lower())[:60]
    local_path = DRAFTS_DIR / f"REVIVAL_{safe_name}.md"
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(f"# Revival fix for: {t['topic_or_page']}\n\n")
        f.write(f"**Why flagged:** {t['evidence']}\n\n## Title options\n")
        for i, title in enumerate(fix.get("titles", []), start=1):
            f.write(f"{i}. {title}\n")
        f.write("\n## Meta description options\n")
        for i, meta in enumerate(fix.get("meta_descriptions", []), start=1):
            f.write(f"{i}. {meta}\n")
        f.write(f"\n## Rewritten opening paragraph\n{fix.get('rewritten_opening', '')}\n")
    print(f"Saved revival fix: {local_path} (apply manually - no WordPress draft created)")
    _log_to_sheet(cfg, t, str(local_path), "n/a (revival)", 0, 0)


def _log_to_sheet(cfg, t, edit_link, image_source, flag_count, word_count):
    if cfg.get("GSHEETS_SHEET_ID"):
        try:
            sheets_logger.log_run(
                service_account_file=cfg["GSHEETS_SERVICE_ACCOUNT_FILE"], sheet_id=cfg["GSHEETS_SHEET_ID"],
                tab_name=cfg.get("GSHEETS_LOG_TAB", "Run Log"),
                entry={
                    "topic": t["topic_or_page"], "type": t["type"], "category": t["category"],
                    "priority": t["priority"], "edit_link": edit_link, "image_source": image_source,
                    "fact_check_flag_count": flag_count, "word_count": word_count,
                },
            )
            print("Logged to Google Sheet.")
        except Exception as e:
            print(f"Sheet logging failed: {e}")


def run_write(cfg: dict, pause_event=None, stop_event=None):
    """pause_event / stop_event are optional multiprocessing.Event-likes
    (see pipeline_worker.py). Checked BETWEEN topics only - there's no
    clean way to pause mid-API-call, and topic boundaries are a natural,
    always-safe point to stop: nothing is left half-written, the current
    topic's status is set correctly either way, and everything after it
    simply stays 'queued' for next time."""
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    max_topics = int(cfg.get("MAX_TOPICS_PER_RUN", 2))
    topics = _load_queued_topics(max_topics)
    if not topics:
        print("No queued topics in the backlog. Run Research first, or add a topic manually.")
        return

    print(f">>> Step 2: Write - drafting {len(topics)} topic(s)...")
    print("    Each GAP/MANUAL topic runs: SEO research \u2192 internal links \u2192 draft (word-count gated) "
          "\u2192 fact-check \u2192 humanize \u2192 SEO metadata \u2192 images embedded.")
    for t in topics:
        if stop_event is not None and stop_event.is_set():
            print("\n>>> Stopped. Remaining queued topics were left untouched.")
            return
        if pause_event is not None and pause_event.is_set():
            print("\n>>> Paused - waiting to resume (remaining topics stay queued until then)...")
            while pause_event.is_set():
                if stop_event is not None and stop_event.is_set():
                    print(">>> Stopped while paused. Remaining queued topics were left untouched.")
                    return
                time.sleep(1)
            print(">>> Resumed.")

        print(f"\n--- {t['type']}: {t['topic_or_page']} ({t['category']}, {t['priority']}) ---")
        try:
            if t["type"] == "REVIVAL":
                _handle_revival(cfg, t)
            else:
                _handle_gap(cfg, t)
            _mark_status(t["id"], "drafted")
        except Exception as e:
            print(f"Failed to process this topic, leaving it queued: {e}")
    print(">>> Write run complete.")


def check_gsc(cfg: dict) -> dict:
    props = gsc_client.list_properties(cfg["GSHEETS_SERVICE_ACCOUNT_FILE"])
    return {"properties": props, "configured": cfg.get("GSC_SITE_URL", "")}

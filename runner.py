"""
runner.py
----------
The actual research/write pipeline - same logic as the CLI tool's main.py,
adapted to be called from API routes instead of argparse commands. Anything
that used input() or print()-only CLI flow has been removed; print()
statements stay, since app.py captures stdout to stream into the dashboard's
live log panel.

Write pipeline per GAP/MANUAL topic, in order:
  1. seo_research.build_brief()   - detailed research brief (always Gemini)
  2. content_writer.draft_post()  - first draft (Gemini or Claude, per config)
  3. content_writer.fact_check()  - flags claims to verify, on the RAW draft
  4. content_writer.humanize_draft() - polish pass, after facts are flagged
  5. content_writer.generate_seo_metadata() - metadata from the FINAL text
  6. image_handler.select_images_for_post()
  7. save locally + optionally push a WordPress draft + log to Sheet
"""

import csv

import content_writer
import gsc_client
import image_handler
import paths
import research
import seo_research
import sheets_logger
import wordpress_publisher

BACKLOG_PATH = paths.BACKLOG_PATH
DRAFTS_DIR = paths.DRAFTS_DIR


def _load_queued_topics(limit: int) -> list:
    if not BACKLOG_PATH.exists():
        return []
    with open(BACKLOG_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    queued = [r for r in rows if r["status"] == "queued"]
    priority_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    queued.sort(key=lambda r: priority_order.get(r["priority"], 9))
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
    print(">>> Step 1: Research - pulling GSC data (blog pages only) and updating the backlog...")
    added = research.run_research(
        cfg["GSHEETS_SERVICE_ACCOUNT_FILE"], cfg["GSC_SITE_URL"],
        int(cfg.get("REVIVAL_IMPRESSION_THRESHOLD", 5000)),
        int(cfg.get("GAP_IMPRESSION_THRESHOLD", 500)),
        cfg.get("SITE_BLOG_PATH", "/blog/"),
    )
    print(f">>> Research complete. {added} new topic(s) added to the backlog.")
    return added


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

    # Step 2: first draft, on whichever provider WRITER_PROVIDER selects.
    provider = (cfg.get("WRITER_PROVIDER") or "gemini").strip().lower()
    print(f"  Drafting with {'Claude' if provider == 'claude' else 'Gemini'}...")
    draft_md = content_writer.draft_post(
        cfg=cfg, topic=t["topic_or_page"], category=t["category"], evidence=t["evidence"],
        min_words=int(cfg.get("MIN_WORD_COUNT", 1200)), max_words=int(cfg.get("MAX_WORD_COUNT", 1500)),
        brief=brief,
    )

    # Step 3: fact-check the RAW draft, before any stylistic polishing.
    flags = content_writer.fact_check(cfg=cfg, draft=draft_md)

    # Step 4: humanize pass - polish tone/rhythm, keep facts and [VERIFY:...] intact.
    print("  Running humanize pass...")
    final_md = content_writer.humanize_draft(cfg=cfg, draft=draft_md)

    # Step 5: SEO metadata from the FINAL (humanized) text.
    seo = content_writer.generate_seo_metadata(cfg=cfg, draft=final_md)

    images = image_handler.select_images_for_post(
        api_key=cfg["GEMINI_API_KEY"], image_model=cfg.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image"),
        topic=t["topic_or_page"], category=t["category"],
    )

    safe_name = "".join(c if c.isalnum() else "_" for c in t["topic_or_page"].lower())[:60]
    local_path = DRAFTS_DIR / f"{safe_name}.md"
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(f"# {seo.get('title') or t['topic_or_page']}\n\n")
        f.write(f"<!-- meta_description: {seo.get('meta_description', '')} -->\n")
        f.write(f"<!-- fact_check_flags: {len(flags)} -->\n")
        f.write(f"<!-- written_with: {provider} -->\n\n")
        f.write(final_md)
    print(f"Saved local draft: {local_path}")

    edit_link = ""
    if cfg.get("WP_SITE_URL") and cfg.get("WP_USERNAME"):
        try:
            result = wordpress_publisher.create_draft_post(
                site_url=cfg["WP_SITE_URL"], username=cfg["WP_USERNAME"], app_password=cfg["WP_APP_PASSWORD"],
                title=seo.get("title") or t["topic_or_page"], markdown_body=final_md, slug=seo.get("slug", ""),
                meta_description=seo.get("meta_description", ""), featured_image_url=images.get("hero_image", ""),
            )
            edit_link = result["edit_link"]
            print(f"Created WordPress draft: {edit_link}")
        except Exception as e:
            print(f"WordPress draft creation failed (saved locally instead): {e}")
    else:
        print("WordPress not configured - local file only.")

    _log_to_sheet(cfg, t, edit_link or str(local_path), images.get("source", ""), len(flags), len(final_md.split()))


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


def run_write(cfg: dict):
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    max_topics = int(cfg.get("MAX_TOPICS_PER_RUN", 2))
    topics = _load_queued_topics(max_topics)
    if not topics:
        print("No queued topics in the backlog. Run Research first, or add a topic manually.")
        return

    print(f">>> Step 2: Write - drafting {len(topics)} topic(s)...")
    print("    Each GAP/MANUAL topic runs: SEO research \u2192 draft \u2192 fact-check \u2192 humanize \u2192 SEO metadata.")
    for t in topics:
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

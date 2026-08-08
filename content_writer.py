"""
content_writer.py
------------------
Drafts the actual blog post, fact-checks it, humanizes it, then generates
SEO metadata. Every one of those four steps can run on either Gemini or
Claude - whichever WRITER_PROVIDER is set to in config.env (the setup
wizard's "Writing model" step). This is entirely separate from
seo_research.py, which always uses Gemini for the research brief step,
regardless of this setting.

Uses the current `google-genai` SDK (`pip install google-genai`) for Gemini,
NOT the older `google-generativeai` package - that one is officially
deprecated. Uses the official `anthropic` SDK for Claude.

Every public function here takes `cfg: dict` (the loaded config.env values)
rather than a raw api_key/model_name pair, so the provider choice lives in
exactly one place (_resolve_provider) instead of being threaded through
every call site in runner.py.
"""

import json
import re
import time

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"

BRAND_VOICE = """
You are writing for Sierra Living Concepts, a D2C luxury solid-wood furniture
brand (~90% US, ~10% Canada customers, average order value ~$3,800). Their
core differentiator: genuine solid wood construction, no veneer, made-to-order
in customer-chosen size/stain/wood. Buyers are high-consideration, doing real
research before a big purchase - they want substance, not fluff.

Voice: warm, confident, knowledgeable - like a craftsperson who actually knows
wood, not a generic lifestyle blogger. Avoid AI-writing tells: no "In today's
world...", no excessive rhetorical questions, no listicle padding, no forced
enthusiasm ("Let's dive in!"). Write like a person who has actually measured
a room and moved a bed frame through a doorway.
"""

DRAFT_PROMPT_TEMPLATE = """{brand_voice}

Write a blog post on this topic: "{topic}"
Category: {category}
Context on why this topic matters: {evidence}

SEO research brief for this post (use it - it reflects real search demand
and real questions buyers are asking; don't ignore it in favor of generic
structure):
{brief_text}

Internal links you may use (REAL pages that actually exist on the site right
now - use ONLY urls from this list, never invent or guess a URL, never modify
one):
{internal_links_text}

Requirements:
- {min_words}-{max_words} words.
- Open with a direct, specific answer to the core question in the first
  2-3 sentences (this helps with AI Overview / answer-engine visibility -
  readers and search engines should get the answer immediately, details after).
- Work the target keywords in naturally - never force a phrase somewhere it
  reads awkwardly.
- Make sure every "people also ask" question from the brief gets a clear
  answer somewhere in the post, even if not as its own subheading.
- Include concrete, specific numbers where relevant (dimensions, clearances,
  wood properties) - mark any number you are not fully certain of with
  [VERIFY: claim] so it can be fact-checked before publishing.
- Structure with clear H2/H3 subheadings (use markdown ##/###).
- Naturally mention solid wood construction quality where genuinely relevant
  to the topic - do not force a sales pitch into every paragraph.
- Link to 2-4 of the internal pages listed above where it's genuinely useful
  to the reader - a product/category link when discussing a specific type of
  furniture, a blog link when a related question is covered elsewhere on the
  site. Use natural anchor text (never "click here" or the raw URL). Do NOT
  force a link where none of the candidates genuinely fit - it's fine to use
  fewer than 2 if nothing matches well, and fine to skip entirely if the
  candidate list is empty.
- End with a short, useful takeaway - not a generic call-to-action.
- Do NOT invent specific product names, prices, or SKUs outside of what's
  in the internal links list above.

Output as markdown, ready to review.
"""

FACT_CHECK_PROMPT_TEMPLATE = """You are fact-checking a furniture blog post before it gets published.
Go through the draft below and list every specific factual claim (measurements,
material properties, care instructions, historical/design claims) that:
  (a) is marked [VERIFY: ...],
  (b) sounds specific but has no clear sourcing, or
  (c) could plausibly be wrong.

For each, give a one-line note on what a human reviewer should check.
Do not fix the draft - just produce the flag list. Output as a JSON list of
objects: [{{"claim": "...", "why_flagged": "..."}}]

DRAFT:
{draft}
"""

HUMANIZE_PROMPT_TEMPLATE = """You are doing a final polish pass on a furniture blog draft before
publishing, specifically to remove anything that reads as obviously
AI-written - NOT to change facts, structure, or meaning.

What to fix:
- Robotic transitions and filler ("It's important to note that...",
  "In conclusion...", "Overall...", "Furthermore...")
- Repetitive sentence rhythm (too many same-length sentences in a row -
  vary it, the way a person actually writes)
- Overly symmetric lists or overly neat paragraph lengths
- Generic hedging that says nothing ("can vary depending on several factors")
- Any leftover AI-writing tells the brand voice below warns against

{brand_voice}

What to KEEP exactly as-is:
- Every factual claim and every [VERIFY: ...] marker - do not remove, resolve,
  or alter these; a separate fact-check step handles them
- All markdown headings (##/###) - keep the same structure and heading text
- The overall word count (stay within about 10% of the original)
- Any specific numbers, dimensions, or measurements

Return ONLY the revised markdown draft - no commentary, no explanation of
what you changed.

DRAFT:
{draft}
"""

SEO_METADATA_PROMPT_TEMPLATE = """Based on this blog post draft, write SEO metadata as JSON with exactly these keys:
title (under 60 chars), meta_description (under 155 chars), slug (lowercase-hyphenated),
suggested_alt_text (for the hero image, one sentence).

DRAFT:
{draft}
"""

REVIVAL_PROMPT_TEMPLATE = """{brand_voice}

An existing blog post is getting real search impressions but a poor
click-through rate, meaning the title/meta/opening aren't convincing people
to click even though Google is showing it. The post is about: "{topic}"
Category: {category}
Why it's flagged: {evidence}

Do NOT rewrite the whole post. Produce ONLY:
1. Three alternative titles (each under 60 characters, each a genuinely
   different angle - e.g. one direct-answer style, one number/specific-detail
   style, one comparison style)
2. Three alternative meta descriptions (each under 155 characters) matching
   each title
3. A rewritten opening paragraph (2-3 sentences) that answers the core
   question immediately and specifically - this is what actually gets read
   first and should give both the reader and Google's AI Overview a direct
   answer with real numbers/specifics where possible.

Output as JSON with exactly these keys:
{{"titles": ["...", "...", "..."], "meta_descriptions": ["...", "...", "..."],
"rewritten_opening": "..."}}
"""


# ---------------------------------------------------------------------------
# Provider abstraction - this is the only part of the file that knows which
# LLM is being used. Everything above is provider-agnostic prompt text.
# ---------------------------------------------------------------------------

def _resolve_provider(cfg: dict) -> str:
    provider = (cfg.get("WRITER_PROVIDER") or "gemini").strip().lower()
    return provider if provider in ("gemini", "claude") else "gemini"


def _generate_text(cfg: dict, prompt: str) -> str:
    """Single entry point every drafting/fact-check/humanize/metadata call
    below goes through. Picks Gemini or Claude based on cfg["WRITER_PROVIDER"]."""
    provider = _resolve_provider(cfg)
    if provider == "claude":
        return _generate_claude(cfg.get("ANTHROPIC_API_KEY", ""),
                                 cfg.get("ANTHROPIC_MODEL") or DEFAULT_CLAUDE_MODEL, prompt)
    return _generate_gemini(cfg.get("GEMINI_API_KEY", ""),
                             cfg.get("GEMINI_TEXT_MODEL") or DEFAULT_GEMINI_MODEL, prompt)


def _generate_gemini(api_key: str, model_name: str, prompt: str, max_attempts: int = 4,
                      max_output_tokens: int = 8192) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    # IMPORTANT: Gemini 2.5 models think by default, and that reasoning is
    # billed against the SAME output token budget as the actual answer. With
    # no max_output_tokens set, the SDK's default can be low enough that
    # thinking alone eats the whole budget - the response then looks
    # "complete" (no error) but cuts off after a paragraph or two, because
    # there were no tokens left for the rest of the answer. This was a real
    # bug here, not a hypothetical one - drafts were coming back as a single
    # paragraph. Fix: raise the budget explicitly AND turn thinking off for
    # these straightforward generation tasks (drafting, fact-check JSON,
    # humanize, metadata JSON all need writing quality, not multi-step
    # reasoning), so the full budget goes to the actual output.
    config = types.GenerateContentConfig(
        max_output_tokens=max_output_tokens,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    last_error = None
    for attempt in range(max_attempts):
        try:
            response = client.models.generate_content(model=model_name, contents=prompt, config=config)
            if not getattr(response, "candidates", None):
                raise RuntimeError("Empty response from Gemini (possibly safety-filtered)")
            finish_reason = getattr(response.candidates[0], "finish_reason", None)
            text = response.text or ""
            if finish_reason is not None and str(finish_reason).upper() in ("MAX_TOKENS", "2"):
                print(f"  Gemini response was cut off at the token limit (attempt {attempt + 1}) - retrying with more room...")
                max_output_tokens = min(max_output_tokens * 2, 32768)
                config = types.GenerateContentConfig(
                    max_output_tokens=max_output_tokens,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                )
                if attempt < max_attempts - 1:
                    continue
            if not text.strip():
                raise RuntimeError("Empty response from Gemini")
            return text
        except Exception as e:
            last_error = e
            wait = 2 ** (attempt + 1)
            print(f"  Gemini call failed ({e}); retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"Gemini call failed after {max_attempts} attempts: {last_error}")


def _generate_claude(api_key: str, model_name: str, prompt: str, max_attempts: int = 4,
                      max_tokens: int = 8192) -> str:
    """Requires the `anthropic` package (in requirements.txt). Kept as a
    lazy import so a Gemini-only install/user never needs it installed."""
    if not api_key:
        raise RuntimeError(
            "WRITER_PROVIDER is set to 'claude' but no ANTHROPIC_API_KEY is configured - "
            "add one in Setup > Writing model."
        )
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    last_error = None
    for attempt in range(max_attempts):
        try:
            response = client.messages.create(
                model=model_name,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
            if response.stop_reason == "max_tokens":
                print(f"  Claude response was cut off at the token limit (attempt {attempt + 1}) - retrying with more room...")
                max_tokens = min(max_tokens * 2, 16384)
                if attempt < max_attempts - 1:
                    continue
            if not text.strip():
                raise RuntimeError("Empty response from Claude")
            return text
        except Exception as e:
            last_error = e
            wait = 2 ** (attempt + 1)
            print(f"  Claude call failed ({e}); retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"Claude call failed after {max_attempts} attempts: {last_error}")


def _strip_json_fences(text: str) -> str:
    return re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()


# ---------------------------------------------------------------------------
# Public pipeline steps
# ---------------------------------------------------------------------------

def draft_post(cfg: dict, topic: str, category: str, evidence: str,
                min_words: int, max_words: int, brief: dict = None,
                internal_link_candidates: list = None) -> dict:
    """`brief` is the dict from seo_research.build_brief() - optional so this
    still works if the research step was skipped or failed for this topic.
    `internal_link_candidates` is the shortlist from
    internal_links.shortlist_relevant_links() - real {url, title, kind}
    dicts the model is allowed to link to; never invented.

    Returns {"draft": str, "word_count": int, "length_ok": bool,
    "attempts": int} - length_ok is the hard-gate result: True if the final
    attempt landed inside [min_words, max_words] (or within 10% under - see
    below), False if every retry still came up short and the draft needs a
    human's attention before it's considered done. Callers (runner.py)
    surface length_ok in the saved draft so it's never silently hidden."""
    import seo_research

    brief_text = seo_research.format_brief_for_prompt(brief or {})
    links_text = _format_internal_links(internal_link_candidates or [])
    allowed_urls = {c["url"] for c in (internal_link_candidates or [])}

    prompt = DRAFT_PROMPT_TEMPLATE.format(
        brand_voice=BRAND_VOICE, topic=topic, category=category, evidence=evidence,
        min_words=min_words, max_words=max_words, brief_text=brief_text,
        internal_links_text=links_text,
    )

    # Hard length gate: up to 3 attempts total, each with an increasingly
    # explicit nudge about the shortfall. A draft within 10% under min_words
    # is accepted (retrying forever over a handful of words isn't worth the
    # API cost) - anything short of THAT after 3 attempts is saved anyway
    # (so nothing is lost) but flagged length_ok=False for a human to see.
    draft = ""
    word_count = 0
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        draft = _generate_text(cfg, prompt)
        draft, stripped = _validate_internal_links(draft, allowed_urls)
        if stripped:
            print(f"  Stripped {stripped} invented/unlisted internal link(s) from the draft (kept as plain text).")
        word_count = len(draft.split())
        if word_count >= min_words * 0.9:
            break
        if attempt < max_attempts:
            print(f"  Draft attempt {attempt}: {word_count} words (wanted {min_words}-{max_words}) - retrying with a stronger nudge...")
            prompt = DRAFT_PROMPT_TEMPLATE.format(
                brand_voice=BRAND_VOICE, topic=topic, category=category, evidence=evidence,
                min_words=min_words, max_words=max_words, brief_text=brief_text,
                internal_links_text=links_text,
            ) + (
                f"\n\nIMPORTANT: your previous attempt was only {word_count} words, well short of the "
                f"{min_words}-{max_words} word requirement. Write the FULL post this time - cover every "
                f"subheading from the brief in real depth, with complete paragraphs, not a summary or outline."
            )

    length_ok = word_count >= min_words * 0.9
    if not length_ok:
        print(f"  WARNING: draft still only {word_count} words after {max_attempts} attempts "
              f"(target {min_words}-{max_words}) - saving anyway, flagged for review.")
    return {"draft": draft, "word_count": word_count, "length_ok": length_ok, "attempts": max_attempts}


def _format_internal_links(candidates: list) -> str:
    if not candidates:
        return "(No internal link candidates available for this topic - don't add any internal links.)"
    lines = [f"- {c['title']} | {c['url']} | ({c['kind']})" for c in candidates]
    return "\n".join(lines)


_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")


def _validate_internal_links(draft: str, allowed_urls: set) -> tuple:
    """Safety net run on every draft attempt (not just once at the end):
    scans for markdown links and strips (converts back to plain text) any
    whose URL isn't in the allowed shortlist - a model hallucinating a
    plausible-looking but nonexistent product URL is a real failure mode
    worth guarding against structurally, not just hoping the prompt is
    followed. Returns (cleaned_draft, count_stripped)."""
    stripped = 0

    def _replace(match):
        nonlocal stripped
        text, url = match.group(1), match.group(2)
        if url in allowed_urls:
            return match.group(0)
        stripped += 1
        return text

    cleaned = _MD_LINK_RE.sub(_replace, draft)
    return cleaned, stripped


def fact_check(cfg: dict, draft: str) -> list:
    prompt = FACT_CHECK_PROMPT_TEMPLATE.format(draft=draft)
    text = _strip_json_fences(_generate_text(cfg, prompt))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return [{"claim": "PARSE_ERROR", "why_flagged": text}]


def humanize_draft(cfg: dict, draft: str) -> str:
    """Final polish pass, run AFTER fact-check and BEFORE SEO metadata is
    generated (so the metadata reflects the actual final wording). Runs on
    whichever provider WRITER_PROVIDER is set to, same as drafting - a
    consistent voice matters more here than mixing providers mid-pipeline."""
    prompt = HUMANIZE_PROMPT_TEMPLATE.format(brand_voice=BRAND_VOICE, draft=draft)
    humanized = _generate_text(cfg, prompt).strip()
    # Defensive floor: if the model returned something drastically shorter
    # (e.g. it misread the instruction and summarized instead of polishing),
    # keep the original rather than silently publishing a truncated post.
    if len(humanized) < 0.5 * len(draft):
        print("  Humanize pass returned a much shorter draft than expected - keeping the pre-humanize version.")
        return draft
    return humanized


def generate_seo_metadata(cfg: dict, draft: str) -> dict:
    prompt = SEO_METADATA_PROMPT_TEMPLATE.format(draft=draft)
    text = _strip_json_fences(_generate_text(cfg, prompt))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"title": "", "meta_description": "", "slug": "", "suggested_alt_text": "", "raw": text}


def draft_revival_fix(cfg: dict, topic: str, category: str, evidence: str) -> dict:
    """For REVIVAL items: doesn't touch the post itself, just proposes the
    fix a human applies (title/meta/opening) - see runner.py's REVIVAL branch."""
    prompt = REVIVAL_PROMPT_TEMPLATE.format(brand_voice=BRAND_VOICE, topic=topic, category=category, evidence=evidence)
    text = _strip_json_fences(_generate_text(cfg, prompt))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"titles": [], "meta_descriptions": [], "rewritten_opening": "", "raw": text}

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
- End with a short, useful takeaway - not a generic call-to-action.
- Do NOT invent specific product names, prices, or SKUs.

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


def _generate_gemini(api_key: str, model_name: str, prompt: str, max_attempts: int = 4) -> str:
    from google import genai

    client = genai.Client(api_key=api_key)
    last_error = None
    for attempt in range(max_attempts):
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            if not getattr(response, "candidates", None):
                raise RuntimeError("Empty response from Gemini (possibly safety-filtered)")
            return response.text
        except Exception as e:
            last_error = e
            wait = 2 ** (attempt + 1)
            print(f"  Gemini call failed ({e}); retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"Gemini call failed after {max_attempts} attempts: {last_error}")


def _generate_claude(api_key: str, model_name: str, prompt: str, max_attempts: int = 4) -> str:
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
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
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
                min_words: int, max_words: int, brief: dict = None) -> str:
    """`brief` is the dict from seo_research.build_brief() - optional so this
    still works if the research step was skipped or failed for this topic."""
    import seo_research

    brief_text = seo_research.format_brief_for_prompt(brief or {})
    prompt = DRAFT_PROMPT_TEMPLATE.format(
        brand_voice=BRAND_VOICE, topic=topic, category=category, evidence=evidence,
        min_words=min_words, max_words=max_words, brief_text=brief_text,
    )
    return _generate_text(cfg, prompt)


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

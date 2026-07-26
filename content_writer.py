"""
content_writer.py
------------------
Drafts the actual blog post using Gemini, then runs a second fact-check pass.
Two separate calls on purpose - a model reviewing its own claims fresh (with
an explicit "find errors" instruction) catches more than asking it to be
careful the first time around.

Uses the current `google-genai` SDK (`pip install google-genai`), NOT the
older `google-generativeai` package - that one is officially deprecated
("all support has ended, no more updates or bug fixes" per Google's own
package notice) and shouldn't be relied on for anything running long-term.
"""

import json
import re
import time

from google import genai

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

Requirements:
- {min_words}-{max_words} words.
- Open with a direct, specific answer to the core question in the first
  2-3 sentences (this helps with AI Overview / answer-engine visibility -
  readers and search engines should get the answer immediately, details after).
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

SEO_METADATA_PROMPT_TEMPLATE = """Based on this blog post draft, write SEO metadata as JSON with exactly these keys:
title (under 60 chars), meta_description (under 155 chars), slug (lowercase-hyphenated),
suggested_alt_text (for the hero image, one sentence).

DRAFT:
{draft}
"""


def _get_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def _generate_with_retry(client: genai.Client, model_name: str, prompt: str, max_attempts: int = 4):
    """Free-tier Gemini rate limits (429s) are common under any real usage.
    Simple exponential backoff: 2s, 4s, 8s, 16s. Also guards against a
    response with no usable text (e.g. safety-filtered), which otherwise
    raises a confusing AttributeError deep inside the SDK."""
    last_error = None
    for attempt in range(max_attempts):
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            if not getattr(response, "candidates", None):
                raise RuntimeError("Empty response from Gemini (possibly safety-filtered)")
            return response
        except Exception as e:
            last_error = e
            wait = 2 ** (attempt + 1)
            print(f"  Gemini call failed ({e}); retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"Gemini call failed after {max_attempts} attempts: {last_error}")


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


def draft_revival_fix(api_key: str, model_name: str, topic: str, category: str, evidence: str) -> dict:
    """For REVIVAL items: doesn't touch the post itself, just proposes the
    fix a human applies (title/meta/opening) - see main.py's REVIVAL branch."""
    client = _get_client(api_key)
    prompt = REVIVAL_PROMPT_TEMPLATE.format(
        brand_voice=BRAND_VOICE, topic=topic, category=category, evidence=evidence,
    )
    response = _generate_with_retry(client, model_name, prompt)
    text = re.sub(r"^```(json)?|```$", "", response.text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"titles": [], "meta_descriptions": [], "rewritten_opening": "", "raw": text}


def draft_post(api_key: str, model_name: str, topic: str, category: str,
               evidence: str, min_words: int, max_words: int) -> str:
    client = _get_client(api_key)
    prompt = DRAFT_PROMPT_TEMPLATE.format(
        brand_voice=BRAND_VOICE, topic=topic, category=category,
        evidence=evidence, min_words=min_words, max_words=max_words,
    )
    response = _generate_with_retry(client, model_name, prompt)
    return response.text


def fact_check(api_key: str, model_name: str, draft: str) -> list:
    client = _get_client(api_key)
    prompt = FACT_CHECK_PROMPT_TEMPLATE.format(draft=draft)
    response = _generate_with_retry(client, model_name, prompt)
    text = response.text.strip()
    # Strip markdown code fences if the model wraps its JSON output.
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return [{"claim": "PARSE_ERROR", "why_flagged": text}]


def generate_seo_metadata(api_key: str, model_name: str, draft: str) -> dict:
    client = _get_client(api_key)
    prompt = SEO_METADATA_PROMPT_TEMPLATE.format(draft=draft)
    response = _generate_with_retry(client, model_name, prompt)
    text = re.sub(r"^```(json)?|```$", "", response.text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"title": "", "meta_description": "", "slug": "", "suggested_alt_text": "", "raw": text}

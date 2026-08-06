"""
seo_research.py
----------------
The detailed SEO research step that runs BEFORE a topic gets drafted -
separate from research.py (which only decides WHICH topics are worth
writing, from GSC gap/CTR data). This module goes one level deeper on a
single already-chosen topic: what should the post actually cover, in what
order, targeting which specific phrases, answering which real questions.

This ALWAYS uses Gemini, regardless of what WRITER_PROVIDER is set to for
drafting - the user's instruction was explicit: research uses Gemini, and
writing can be either Gemini or Claude. Keeping this module Gemini-only and
separate from content_writer.py's provider-switching logic is what makes
that split trivial to keep correct as the two evolve independently.

Output is a plain dict (a "brief") consumed by content_writer.draft_post -
see BRIEF_KEYS below for exactly what it contains.
"""

import json
import re
import time

from google import genai

BRIEF_KEYS = ["search_intent", "target_keywords", "suggested_subheadings",
              "people_also_ask", "competitive_angle", "internal_link_ideas"]

RESEARCH_PROMPT_TEMPLATE = """You are doing SEO research for a single blog post before anyone
writes it, for Sierra Living Concepts (a D2C luxury solid-wood furniture brand,
sierralivingconcepts.com/blog). Do NOT write the post. Produce a research brief only.

Topic: "{topic}"
Category: {category}
Why this topic was chosen: {evidence}

Think like an SEO strategist who also understands the buyer: someone doing real
research before a ~$3,800 furniture purchase, not someone browsing casually.

Produce a JSON object with exactly these keys:
- "search_intent": one sentence - what is the person actually trying to find out
  or decide when they search this?
- "target_keywords": 4-7 specific phrases this post should realistically be able
  to rank for (the main topic phrase plus close variants/related long-tail terms -
  not generic single words).
- "suggested_subheadings": 5-9 H2/H3-level subheadings in a sensible reading order
  that would make this the most useful page on the topic - specific, not generic
  ("How much clearance a dining table actually needs" not "Things to Consider").
- "people_also_ask": 4-6 real, specific questions a buyer would plausibly type into
  Google around this topic (phrase them as actual questions).
- "competitive_angle": 1-2 sentences on what most existing articles on this topic
  probably get wrong, skip, or oversimplify - the gap this post should fill,
  given Sierra Living Concepts' genuine solid-wood/no-veneer differentiator where
  it's actually relevant (don't force it if it isn't).
- "internal_link_ideas": 2-4 short phrases describing what kind of Sierra Living
  Concepts page this post could reasonably link to (e.g. "dining table size guide",
  "solid wood vs veneer explainer") - describe the page, don't invent a URL.

Output ONLY the JSON object, no markdown fences, no commentary.
"""


def _get_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def _generate_with_retry(client: genai.Client, model_name: str, prompt: str, max_attempts: int = 4):
    """Same retry shape as content_writer.py's Gemini calls - kept as its own
    small copy here rather than a shared import, so this module has zero
    dependency on content_writer.py and truly can't be affected by whichever
    provider that module is currently configured to write with."""
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
            print(f"  Gemini research call failed ({e}); retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"Gemini research call failed after {max_attempts} attempts: {last_error}")


def _empty_brief(raw: str = "") -> dict:
    brief = {k: ([] if k != "search_intent" and k != "competitive_angle" else "") for k in BRIEF_KEYS}
    if raw:
        brief["raw"] = raw
    return brief


def build_brief(gemini_api_key: str, gemini_model: str, topic: str, category: str, evidence: str) -> dict:
    """Returns the research brief dict described in BRIEF_KEYS above. Never
    raises on a malformed model response - falls back to an empty-but-valid
    brief so a research hiccup degrades gracefully instead of failing the
    whole write run (content_writer.draft_post handles an empty brief fine,
    it just won't have extra guidance to work from)."""
    print(f"  Researching: {topic}")
    client = _get_client(gemini_api_key)
    prompt = RESEARCH_PROMPT_TEMPLATE.format(topic=topic, category=category, evidence=evidence)
    response = _generate_with_retry(client, gemini_model, prompt)
    text = re.sub(r"^```(json)?|```$", "", response.text.strip(), flags=re.MULTILINE).strip()
    try:
        brief = json.loads(text)
    except json.JSONDecodeError:
        print("  Research brief wasn't valid JSON - continuing without one for this topic.")
        return _empty_brief(text)

    for key in BRIEF_KEYS:
        brief.setdefault(key, [] if key not in ("search_intent", "competitive_angle") else "")
    kw = len(brief.get("target_keywords") or [])
    paa = len(brief.get("people_also_ask") or [])
    print(f"  Research brief ready: {kw} target keyword(s), {paa} question(s) to answer.")
    return brief


def format_brief_for_prompt(brief: dict) -> str:
    """Turns the brief dict into readable text to embed inside the drafting
    prompt - kept separate from build_brief so content_writer.py can call
    this on a brief without needing to know or care how it was produced."""
    if not brief or not any(brief.get(k) for k in BRIEF_KEYS):
        return "(No research brief available for this topic - use your own judgement.)"

    lines = []
    if brief.get("search_intent"):
        lines.append(f"Search intent: {brief['search_intent']}")
    if brief.get("target_keywords"):
        lines.append("Target keywords/phrases to work in naturally: " + ", ".join(brief["target_keywords"]))
    if brief.get("suggested_subheadings"):
        lines.append("Suggested structure (use as a strong starting point, adapt as needed):")
        for h in brief["suggested_subheadings"]:
            lines.append(f"  - {h}")
    if brief.get("people_also_ask"):
        lines.append("Real questions readers are asking - make sure the post answers these:")
        for q in brief["people_also_ask"]:
            lines.append(f"  - {q}")
    if brief.get("competitive_angle"):
        lines.append(f"Gap to fill vs. existing articles: {brief['competitive_angle']}")
    if brief.get("internal_link_ideas"):
        lines.append("Natural internal-link opportunities to keep in mind: " + ", ".join(brief["internal_link_ideas"]))
    return "\n".join(lines)

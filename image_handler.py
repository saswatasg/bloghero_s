"""
image_handler.py
-----------------
Strategy: use REAL product photos from the site's own catalog first (free,
on-brand, zero hallucination risk). Only generate an AI image when no real
photo reasonably matches the topic - e.g. a "how to measure your room" post
needs an illustrative lifestyle shot no product photo can provide.

Requires: data/product_catalog.csv with columns:
  product_id, category, tags, image_url, product_page_url
Export this from your WordPress/WooCommerce product list once, and refresh
periodically. (There is no free universal way to auto-generate this file -
it has to come from your actual store data.)
"""

import base64
import csv
from pathlib import Path

from google import genai
from google.genai import types

CATALOG_PATH = Path("data/product_catalog.csv")


def load_catalog() -> list:
    if not CATALOG_PATH.exists():
        return []
    with open(CATALOG_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def find_matching_products(topic: str, category: str, limit: int = 3) -> list:
    catalog = load_catalog()
    topic_l = topic.lower()
    scored = []
    for row in catalog:
        tags = (row.get("tags") or "").lower()
        cat = (row.get("category") or "").lower()
        score = 0
        if category.lower() in cat:
            score += 2
        for word in topic_l.split():
            if word in tags or word in cat:
                score += 1
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[:limit]]


def generate_ai_image(api_key: str, model_name: str, prompt: str, out_path: str) -> str:
    """Falls back to Gemini's image model for a lifestyle/illustrative image
    when no real product photo fits. Verify GEMINI_IMAGE_MODEL in config.env
    against Google's current docs - image model names/APIs change.
    Uses the current google-genai SDK (google.generativeai is deprecated)."""
    client = genai.Client(api_key=api_key)
    full_prompt = (
        f"A warm, editorial-style lifestyle photograph for a luxury solid-wood "
        f"furniture blog. {prompt}. Natural light, realistic, no text or logos overlaid."
    )
    response = client.models.generate_content(
        model=model_name,
        contents=full_prompt,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )
    for part in response.parts:
        if getattr(part, "inline_data", None) is not None:
            data = part.inline_data.data
            img_bytes = base64.b64decode(data) if isinstance(data, str) else data
            with open(out_path, "wb") as f:
                f.write(img_bytes)
            return out_path
    raise RuntimeError("Gemini did not return image data - check GEMINI_IMAGE_MODEL and API access.")


def select_images_for_post(api_key: str, image_model: str, topic: str, category: str,
                            out_dir: str = "data/generated_images") -> dict:
    """Returns {"hero_image": path_or_url, "source": "product"|"ai_generated", "product_links": [...]}"""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    matches = find_matching_products(topic, category)
    if matches:
        return {
            "hero_image": matches[0]["image_url"],
            "source": "product",
            "product_links": [m["product_page_url"] for m in matches],
        }
    # No catalog match - fall back to AI generation.
    safe_name = "".join(c if c.isalnum() else "_" for c in topic.lower())[:60]
    out_path = f"{out_dir}/{safe_name}.png"
    path = generate_ai_image(api_key, image_model, topic, out_path)
    return {"hero_image": path, "source": "ai_generated", "product_links": []}

"""
wordpress_publisher.py
------------------------
Creates a DRAFT post via the WordPress REST API. Never publishes automatically
- status is always "draft" so a human reviews before it goes live, matching
the ~1-1.5 hr/week review workflow agreed with the client.

Auth: WordPress "Application Passwords" (WP Admin > Users > Profile).
This is NOT the account login password - treat WP_APP_PASSWORD like any
other secret and keep it out of shared documents/chat.
"""

import mimetypes
import os
from pathlib import Path

import markdown
import requests


def markdown_to_html(md_text: str) -> str:
    return markdown.markdown(md_text, extensions=["extra"])


def _upload_featured_image(site_url: str, username: str, app_password: str, image_ref: str):
    """Uploads a hero image to the WP media library and returns its media ID.
    image_ref can be a local file path (AI-generated images) or an http(s) URL
    (real product photos already hosted on the site). Returns None on any
    failure so post creation still succeeds without a featured image."""
    media_url = f"{site_url.rstrip('/')}/wp-json/wp/v2/media"

    try:
        if image_ref.startswith("http"):
            img_resp = requests.get(image_ref, timeout=30)
            img_resp.raise_for_status()
            content = img_resp.content
            filename = os.path.basename(image_ref.split("?")[0]) or "hero-image.jpg"
        else:
            path = Path(image_ref)
            if not path.exists():
                print(f"  Featured image path not found: {image_ref}")
                return None
            content = path.read_bytes()
            filename = path.name

        content_type = mimetypes.guess_type(filename)[0] or "image/jpeg"

        resp = requests.post(
            media_url,
            data=content,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": content_type,
            },
            auth=(username, app_password),
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception as e:
        print(f"  Featured image upload failed (post will still be created without one): {e}")
        return None


def create_draft_post(site_url: str, username: str, app_password: str,
                       title: str, markdown_body: str, slug: str = "",
                       meta_description: str = "", featured_image_url: str = "") -> dict:
    api_url = f"{site_url.rstrip('/')}/wp-json/wp/v2/posts"
    html_body = markdown_to_html(markdown_body)

    payload = {
        "title": title,
        "content": html_body,
        "status": "draft",   # always draft - human reviews before publishing
        "slug": slug,
        "excerpt": meta_description,
    }

    if featured_image_url:
        media_id = _upload_featured_image(site_url, username, app_password, featured_image_url)
        if media_id:
            payload["featured_media"] = media_id

    resp = requests.post(
        api_url,
        json=payload,
        auth=(username, app_password),
        timeout=30,
    )
    resp.raise_for_status()
    post = resp.json()

    return {
        "post_id": post.get("id"),
        "edit_link": f"{site_url.rstrip('/')}/wp-admin/post.php?post={post.get('id')}&action=edit",
        "status": post.get("status"),
        "featured_media_set": "featured_media" in payload,
    }


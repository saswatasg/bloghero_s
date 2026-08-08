"""
wordpress_publisher.py
------------------------
Creates a DRAFT post via the WordPress REST API. Never publishes automatically
- status is always "draft" so a human reviews before it goes live, matching
the ~1-1.5 hr/week review workflow agreed with the client.

Auth: WordPress "Application Passwords" (WP Admin > Users > Profile).
This is NOT the account login password - treat WP_APP_PASSWORD like any
other secret and keep it out of shared documents/chat.

Also used for two things beyond just creating the post:
  - resolve_image_url(): turns a local AI-generated image file OR an
    already-hosted product photo URL into a URL that can be embedded
    INSIDE the post body (not just set as the featured image) - see
    runner.py's image-embedding step.
  - fetch_recent_posts(): real, already-published blog post titles+URLs,
    used by internal_links.py to build real blog-to-blog link candidates
    (product/category link candidates come from the site's sitemap
    instead - see internal_links.py's docstring for why the split).
"""

import mimetypes
import os
from pathlib import Path

import markdown
import requests


def markdown_to_html(md_text: str) -> str:
    return markdown.markdown(md_text, extensions=["extra"])


def _upload_media(site_url: str, username: str, app_password: str, image_ref: str) -> dict:
    """Uploads an image to the WP media library and returns the full media
    object (has both "id" and "source_url"). image_ref can be a local file
    path (AI-generated images) or an http(s) URL (real product photos
    already hosted on the site - re-uploaded as a copy into WP's own media
    library so the resulting post doesn't depend on a third-party host).
    Returns {} on any failure so callers can degrade gracefully."""
    media_url = f"{site_url.rstrip('/')}/wp-json/wp/v2/media"
    try:
        if image_ref.startswith("http"):
            img_resp = requests.get(image_ref, timeout=30)
            img_resp.raise_for_status()
            content = img_resp.content
            filename = os.path.basename(image_ref.split("?")[0]) or "image.jpg"
        else:
            path = Path(image_ref)
            if not path.exists():
                print(f"  Image path not found: {image_ref}")
                return {}
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
        return resp.json()
    except Exception as e:
        print(f"  Image upload failed: {e}")
        return {}


def _upload_featured_image(site_url: str, username: str, app_password: str, image_ref: str):
    """Back-compat wrapper - returns just the media ID, as before."""
    media = _upload_media(site_url, username, app_password, image_ref)
    return media.get("id")


def resolve_image_url(site_url: str, username: str, app_password: str, image_ref: str) -> str:
    """Turns any image reference into a URL that can be embedded directly
    in the post body's markdown (![alt](url)). Real product photos are
    already public URLs and get used as-is - no need to duplicate them
    into WP's media library just to reference them. AI-generated images
    are local files and MUST be uploaded first to get any URL at all.
    Returns "" on failure - callers should skip that image, not break the
    whole post over one image upload glitch."""
    if image_ref.startswith("http"):
        return image_ref
    media = _upload_media(site_url, username, app_password, image_ref)
    return media.get("source_url", "")


def fetch_recent_posts(site_url: str, max_posts: int = 100) -> list:
    """Real, already-published blog posts - title + URL - for internal
    linking candidates. No auth needed (WP's posts endpoint is public read).
    Returns [] on any failure rather than raising - internal linking should
    degrade to sitemap-only candidates, not block drafting."""
    try:
        posts = []
        page = 1
        per_page = min(100, max_posts)
        while len(posts) < max_posts:
            resp = requests.get(
                f"{site_url.rstrip('/')}/wp-json/wp/v2/posts",
                params={"per_page": per_page, "page": page, "status": "publish"},
                timeout=15,
            )
            if resp.status_code != 200:
                break
            batch = resp.json()
            if not batch:
                break
            for p in batch:
                title = (p.get("title") or {}).get("rendered", "").strip()
                link = p.get("link", "")
                if title and link:
                    posts.append({"url": link, "title": title})
            if len(batch) < per_page:
                break
            page += 1
        return posts[:max_posts]
    except Exception as e:
        print(f"  (fetching existing blog posts for internal linking skipped: {e})")
        return []


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


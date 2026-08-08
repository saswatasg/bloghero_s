"""
internal_links.py
-------------------
Builds a real, verifiable index of pages on sierralivingconcepts.com that a
blog post can link to - and only ever lets the writer choose from THIS list,
never invent a URL. Two sources, because the site itself is split across two
platforms:

  1. Sitemap crawl (fetch_sitemap_urls) - the storefront (product pages,
     category pages, and most static pages) runs on a platform with no
     public API BlogHero has credentials for. The sitemap is the only free,
     zero-setup way to get a current, accurate list of those URLs. Titles
     aren't in a sitemap, so they're DERIVED from the URL slug - reliable
     here specifically because this site's slugs are clean, descriptive,
     and match the real product/category name almost verbatim (verified
     against real examples, e.g. /product/15090/marfa-two-tone-arched-bar-
     cabinet-with-glass-doors -> "Marfa Two Tone Arched Bar Cabinet With
     Glass Doors" - genuinely the product's name).

  2. WordPress REST API (wordpress_publisher.fetch_recent_posts) - the blog
     itself (under /blog/) IS WordPress, and BlogHero already has (or can
     read without auth, since the posts endpoint is public) real published
     post titles and URLs. Used for blog-to-blog link candidates - far more
     reliable than deriving a blog post's meaning from its slug.

The merged, deduped result is cached to disk (LINK_INDEX_CACHE_PATH) with a
timestamp, since crawling the whole sitemap on every single post write would
be slow and wasteful - refreshed automatically after CACHE_MAX_AGE_HOURS, or
on demand.

Honest limitation: an e-commerce sitemap can have thousands of URLs. This
caps how many it fetches (MAX_SITEMAP_URLS) - for a very large catalog this
means the index is a representative sample, not literally everything. That
tradeoff favors speed and staying well inside free-tier fetch limits over
completeness; if it's missing an obviously-relevant page, the sitemap cap
below is the first thing to raise.
"""

import json
import re
import time
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests

import paths

LINK_INDEX_CACHE_PATH = paths.DATA_DIR / "internal_link_index.json"
CACHE_MAX_AGE_HOURS = 24
MAX_SITEMAP_URLS = 800
MAX_CHILD_SITEMAPS = 15
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BlogHeroLinkIndexer/1.0)"}

# Common candidate paths, tried in order, since this codebase has to work
# across whatever platform a given deployment's storefront happens to run
# on - not every site is WordPress, and not every sitemap lives at the
# textbook /sitemap.xml path (confirmed against the real site this was
# built for, which links a human-readable "/sitemap" page in its footer
# rather than the XML convention).
_SITEMAP_CANDIDATES = [
    "/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml",
    "/sitemap.aspx", "/sitemap", "/wp-sitemap.xml",
]

# URL path fragments that are never worth linking to from a blog post -
# account/cart/utility pages, not content.
_EXCLUDED_PATH_FRAGMENTS = [
    "/cart", "/login", "/account", "/wishlist", "/checkout", "/search",
    "/affiliates", "/to-the-trade", "/privacy-policy", "/terms-of-use",
    "/affirm-financing", ".jpg", ".png", ".pdf", ".xml",
]

_KIND_PATTERNS = [
    (re.compile(r"/product/"), "product"),
    (re.compile(r"/category/"), "category"),
    (re.compile(r"/blog/"), "blog"),
]


def _classify(url: str) -> str:
    for pattern, kind in _KIND_PATTERNS:
        if pattern.search(url):
            return kind
    return "page"


def _title_from_slug(url: str) -> str:
    """Derives a readable title from a URL's final path segment - e.g.
    '/product/15090/marfa-two-tone-arched-bar-cabinet-with-glass-doors'
    -> 'Marfa Two Tone Arched Bar Cabinet With Glass Doors'. Strips a
    leading numeric ID segment (this site's product/category URLs are
    /product/{id}/{slug}) and title-cases the rest."""
    path = urlparse(url).path.rstrip("/")
    segments = [s for s in path.split("/") if s]
    if not segments:
        return url
    slug = segments[-1]
    slug = re.sub(r"^\d+[-_]?", "", slug)  # drop a leading numeric ID if the slug itself has one
    words = re.split(r"[-_]+", slug)
    words = [w for w in words if w]
    return " ".join(w.capitalize() for w in words) if words else url


def _is_excluded(url: str) -> bool:
    low = url.lower()
    return any(frag in low for frag in _EXCLUDED_PATH_FRAGMENTS)


def _fetch_xml(url: str, timeout: int = 15):
    resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "")
    text = resp.text.strip()
    if "xml" not in content_type and not text.startswith("<?xml") and not text.startswith("<urlset") and not text.startswith("<sitemapindex"):
        raise ValueError("not XML")
    return ElementTree.fromstring(resp.content)


def fetch_sitemap_urls(base_url: str, max_urls: int = MAX_SITEMAP_URLS) -> list:
    """Tries each candidate sitemap path until one parses as valid XML.
    Handles a sitemap INDEX (a file that just lists other sitemap files -
    common on larger sites) by fetching child sitemaps up to
    MAX_CHILD_SITEMAPS. Returns [] if nothing usable was found - callers
    should fall back to WordPress-only linking rather than fail entirely."""
    base_url = base_url.rstrip("/")
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    root = None
    found_at = None
    for candidate in _SITEMAP_CANDIDATES:
        try:
            root = _fetch_xml(base_url + candidate)
            found_at = candidate
            break
        except Exception:
            continue
    if root is None:
        print("  No parseable XML sitemap found at any common path - internal links will rely on the blog's own post list only.")
        return []
    print(f"  Found sitemap at {found_at}")

    urls = []
    tag = root.tag.lower()
    if tag.endswith("sitemapindex"):
        child_locs = [el.text.strip() for el in root.findall(".//sm:sitemap/sm:loc", ns) if el.text]
        for child_url in child_locs[:MAX_CHILD_SITEMAPS]:
            try:
                child_root = _fetch_xml(child_url)
                for loc_el in child_root.findall(".//sm:url/sm:loc", ns):
                    if loc_el.text:
                        urls.append(loc_el.text.strip())
                    if len(urls) >= max_urls:
                        break
            except Exception as e:
                print(f"  (child sitemap {child_url} skipped: {e})")
            if len(urls) >= max_urls:
                break
    elif tag.endswith("urlset"):
        for loc_el in root.findall(".//sm:url/sm:loc", ns):
            if loc_el.text:
                urls.append(loc_el.text.strip())
            if len(urls) >= max_urls:
                break
    else:
        print(f"  Unrecognized sitemap root element <{root.tag}> - skipping.")
        return []

    out = []
    seen = set()
    for url in urls:
        if url in seen or _is_excluded(url):
            continue
        seen.add(url)
        out.append({"url": url, "title": _title_from_slug(url), "kind": _classify(url)})
    print(f"  Parsed {len(out)} linkable URLs from the sitemap.")
    return out


def build_link_index(cfg: dict, force_refresh: bool = False) -> list:
    """The merged, deduped, cached index internal-link selection reads
    from. See module docstring for the two sources and why they're split."""
    if not force_refresh and LINK_INDEX_CACHE_PATH.exists():
        try:
            cached = json.loads(LINK_INDEX_CACHE_PATH.read_text(encoding="utf-8"))
            age_hours = (time.time() - cached.get("built_at", 0)) / 3600
            if age_hours < CACHE_MAX_AGE_HOURS:
                return cached.get("links", [])
        except Exception:
            pass  # corrupt/unreadable cache - just rebuild

    print("  Building internal link index (sitemap + existing blog posts)...")
    base_url = cfg.get("SITE_BASE_URL", "").rstrip("/")
    links = []
    if base_url:
        links.extend(fetch_sitemap_urls(base_url))

    if cfg.get("WP_SITE_URL"):
        import wordpress_publisher

        wp_posts = wordpress_publisher.fetch_recent_posts(cfg["WP_SITE_URL"], max_posts=200)
        seen_urls = {l["url"] for l in links}
        added = 0
        for p in wp_posts:
            if p["url"] not in seen_urls:
                links.append({"url": p["url"], "title": p["title"], "kind": "blog"})
                seen_urls.add(p["url"])
                added += 1
            else:
                # Prefer the WP API's real title over a slug-derived guess
                # for the same URL.
                for l in links:
                    if l["url"] == p["url"]:
                        l["title"] = p["title"]
                        break
        print(f"  Added {added} blog post(s) from WordPress ({len(wp_posts)} fetched total).")

    LINK_INDEX_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LINK_INDEX_CACHE_PATH.write_text(
        json.dumps({"built_at": time.time(), "links": links}), encoding="utf-8",
    )
    print(f"  Link index ready: {len(links)} total ({sum(1 for l in links if l['kind']=='product')} product, "
          f"{sum(1 for l in links if l['kind']=='category')} category, "
          f"{sum(1 for l in links if l['kind']=='blog')} blog, "
          f"{sum(1 for l in links if l['kind']=='page')} other).")
    return links


_STOPWORDS = {"a", "an", "the", "of", "for", "to", "in", "on", "and", "is", "are", "how",
              "what", "your", "with", "best", "guide"}


def _keywords(text: str) -> set:
    return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if w and w not in _STOPWORDS}


def shortlist_relevant_links(link_index: list, topic: str, category: str, max_candidates: int = 12) -> list:
    """Cheap, deterministic keyword-overlap scoring to cut a (possibly
    large) link index down to a manageable shortlist before it's handed to
    the writer - stuffing hundreds of links into a drafting prompt wastes
    tokens and buries the genuinely relevant ones. Always includes a mix:
    the top-scoring product/category links AND the top-scoring blog links,
    so a post isn't only ever pointed at products."""
    topic_kw = _keywords(topic) | _keywords(category)
    scored = []
    for link in link_index:
        link_kw = _keywords(link["title"])
        overlap = len(topic_kw & link_kw)
        if overlap > 0:
            scored.append((overlap, link))
    scored.sort(key=lambda x: x[0], reverse=True)

    product_category = [l for score, l in scored if l["kind"] in ("product", "category")]
    blog = [l for score, l in scored if l["kind"] == "blog"]
    other = [l for score, l in scored if l["kind"] == "page"]

    half = max_candidates // 2
    shortlist = product_category[:half] + blog[: max_candidates - half]
    if len(shortlist) < max_candidates:
        shortlist += other[: max_candidates - len(shortlist)]
    return shortlist[:max_candidates]


def format_links_for_prompt(candidates: list) -> str:
    if not candidates:
        return "(No internal link candidates available for this topic - don't add any internal links.)"
    lines = [f"- {c['title']} | {c['url']} | ({c['kind']})" for c in candidates]
    return "\n".join(lines)

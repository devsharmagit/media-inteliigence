"""
crawler/normaliser.py

Converts raw page dicts produced by scraper.py into a common schema:

    {
        "source_url":   str,
        "source_type":  str,          # "news" | "social" | "forum"
        "scraped_at":   str,          # ISO-8601 UTC
        "title":        str | None,
        "body":         str | None,
        "author":       str | None,
        "published_at": str | None,   # ISO-8601 UTC when known
    }

Rules:
- Missing fields are always None — never empty strings, never KeyError crashes.
- Each source type has its own normaliser function.
- The public entry point is `normalise(raw_pages)` which dispatches by source_type.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _none_if_blank(value: Any) -> str | None:
    """Return None if value is falsy or blank, otherwise return stripped string."""
    if not value:
        return None
    s = str(value).strip()
    return s if s else None


def _parse_reddit_timestamp(unix_ts: Any) -> str | None:
    """Convert a Reddit Unix timestamp (float/int) to ISO-8601 UTC."""
    try:
        ts = float(unix_ts)
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _extract_title_from_markdown(markdown: str) -> str | None:
    """
    Attempt to pull the first H1/H2 heading from markdown text.
    Returns None if no heading found.
    """
    if not markdown:
        return None
    for line in markdown.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return _none_if_blank(line.lstrip("# "))
        if line.startswith("## "):
            return _none_if_blank(line.lstrip("# "))
    return None


def _extract_body_from_markdown(markdown: str, skip_title: bool = True) -> str | None:
    """
    Return the body text from markdown, skipping the first heading if requested.
    Strips markdown link syntax and collapses whitespace.
    """
    if not markdown:
        return None

    lines = markdown.splitlines()
    body_lines: list[str] = []
    skipped_first_heading = not skip_title

    for line in lines:
        stripped = line.strip()
        # Skip the first H1/H2 heading (it becomes the title)
        if not skipped_first_heading and (stripped.startswith("# ") or stripped.startswith("## ")):
            skipped_first_heading = True
            continue
        body_lines.append(line)

    body = "\n".join(body_lines).strip()
    # Remove markdown image/link syntax — keep link text
    body = re.sub(r"!\[.*?\]\(.*?\)", "", body)
    body = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", body)
    # Collapse excessive blank lines
    body = re.sub(r"\n{3,}", "\n\n", body)
    return _none_if_blank(body)


def _extract_author_from_html(html: str) -> str | None:
    """
    Naive regex heuristics to extract author bylines from HTML.
    Works for Reuters and similar news sites.
    """
    if not html:
        return None

    # Reuters byline pattern: <a ... class="...author...">Name</a>
    patterns = [
        r'class="[^"]*author[^"]*"[^>]*>([^<]{2,60})</a>',
        r'"author"\s*:\s*"([^"]{2,60})"',        # JSON-LD
        r'<meta[^>]+name=["\']author["\'][^>]+content=["\']([^"\']{2,60})["\']',
        r'byline["\']?\s*[>:]\s*([A-Z][a-z]+ [A-Z][a-z]+)',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            if candidate and len(candidate) < 80:
                return candidate
    return None


def _extract_published_at_from_html(html: str) -> str | None:
    """
    Extract a published date from HTML meta tags or JSON-LD.
    Returns ISO-8601 string or None.
    """
    if not html:
        return None

    patterns = [
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']pubdate["\'][^>]+content=["\']([^"\']+)["\']',
        r'<time[^>]+datetime=["\']([^"\']+)["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            if raw:
                return raw  # Keep as-is; consumer can re-parse if needed
    return None


# ---------------------------------------------------------------------------
# Per-source normalisers
# ---------------------------------------------------------------------------

def _normalise_news(raw: dict) -> dict | None:
    """
    Normalise a news page (e.g. Reuters) scraped by crawl4ai.

    raw keys expected: url, html, markdown, source_type
    """
    markdown = raw.get("markdown", "") or ""
    html = raw.get("html", "") or ""

    title = _extract_title_from_markdown(markdown)
    body = _extract_body_from_markdown(markdown, skip_title=bool(title))
    author = _extract_author_from_html(html)
    published_at = _extract_published_at_from_html(html)

    # A page with no body at all is not useful — skip it
    if not body and not title:
        logger.debug("[news] Skipping empty page: %s", raw.get("url"))
        return None

    return {
        "source_url":   raw.get("url"),
        "source_type":  "news",
        "scraped_at":   _now_iso(),
        "title":        title,
        "body":         body,
        "author":       author,
        "published_at": published_at,
    }


def _normalise_social(raw: dict) -> dict | None:
    """
    Normalise a Reddit post dict.

    raw keys expected: url, raw_json (post data dict), source_type
    """
    post = raw.get("raw_json", {}) or {}

    title = _none_if_blank(post.get("title"))
    # selftext is the post body; link posts have no selftext
    body = _none_if_blank(post.get("selftext"))
    author = _none_if_blank(post.get("author"))
    published_at = _parse_reddit_timestamp(post.get("created_utc"))
    url = raw.get("url") or (
        "https://www.reddit.com" + post.get("permalink", "")
        if post.get("permalink")
        else None
    )

    if not title:
        logger.debug("[social] Skipping post with no title: %s", url)
        return None

    return {
        "source_url":   url,
        "source_type":  "social",
        "scraped_at":   _now_iso(),
        "title":        title,
        "body":         body,
        "author":       author,
        "published_at": published_at,
    }


def _normalise_forum(raw: dict) -> dict | None:
    """
    Normalise a Hacker News page scraped by crawl4ai.

    HN front page markdown typically contains story titles as links.
    Individual story /item pages contain comment threads.
    """
    markdown = raw.get("markdown", "") or ""
    url = raw.get("url", "")

    # Detect if this is the front page or a story/item page
    is_front_page = "item?id=" not in url

    if is_front_page:
        # Front page: extract list of story titles as one "document"
        titles = re.findall(r"\[([^\]]{5,200})\]\(https?://[^\)]+\)", markdown)
        title = "Hacker News Front Page"
        body = "\n".join(titles) if titles else _none_if_blank(markdown)
    else:
        # Story/comment page
        title = _extract_title_from_markdown(markdown)
        body = _extract_body_from_markdown(markdown, skip_title=bool(title))

    if not body and not title:
        logger.debug("[forum] Skipping empty HN page: %s", url)
        return None

    return {
        "source_url":   url,
        "source_type":  "forum",
        "scraped_at":   _now_iso(),
        "title":        title,
        "body":         body,
        "author":       None,       # HN doesn't surface authors at page level
        "published_at": None,
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_NORMALISERS = {
    "news":   _normalise_news,
    "social": _normalise_social,
    "forum":  _normalise_forum,
}


def normalise(raw_pages: list[dict]) -> list[dict]:
    """
    Convert a list of raw page dicts into normalised content dicts.

    Dispatches by source_type. Unknown types are logged and skipped.
    None results (empty pages) are filtered out.
    """
    normalised: list[dict] = []

    for raw in raw_pages:
        src_type = raw.get("source_type", "")
        fn = _NORMALISERS.get(src_type)

        if fn is None:
            logger.warning("No normaliser for source_type='%s' — skipping", src_type)
            continue

        try:
            item = fn(raw)
            if item is not None:
                normalised.append(item)
        except Exception as exc:
            logger.error(
                "Normaliser crashed on %s (%s): %s",
                raw.get("url", "?"),
                src_type,
                exc,
            )

    logger.info("Normalised %d / %d raw pages", len(normalised), len(raw_pages))
    return normalised


# ---------------------------------------------------------------------------
# Smoke test / checkpoint print
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import asyncio
    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    # Import here to avoid circular at module level
    from crawler.scraper import run_crawl  # noqa: E402

    print("Running smoke test — crawling all sources …")
    raw = run_crawl()
    items = normalise(raw)

    print(f"\n=== Normalised {len(items)} items total ===\n")

    # Print 1 example per source type
    seen: set[str] = set()
    for item in items:
        t = item["source_type"]
        if t not in seen:
            seen.add(t)
            print(f"--- [{t.upper()}] ---")
            print(f"  source_url  : {item['source_url']}")
            print(f"  title       : {item['title']}")
            print(f"  author      : {item['author']}")
            print(f"  published_at: {item['published_at']}")
            print(f"  scraped_at  : {item['scraped_at']}")
            body_preview = (item["body"] or "")[:200].replace("\n", " ")
            print(f"  body        : {body_preview}…")
            print()

        if len(seen) == len(_NORMALISERS):
            break

    if not items:
        print("WARNING: No items normalised — check network / config/sources.yaml")
        sys.exit(1)

"""
crawler/scraper.py

Multi-source web crawler built on crawl4ai.

Reads ALL configuration from config/sources.yaml — never hardcodes URLs.
Supports:
  - news      : Reuters (HTML pages)
  - social    : Reddit  (JSON API)
  - forum     : Hacker News (HTML)

Depth-limited BFS crawl per source. Domain-whitelist enforced so we never
follow links outside allowed domains.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml
from crawl4ai import AsyncWebCrawler, CacheMode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    """Load sources.yaml from config/. Path is relative to project root."""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "config", "sources.yaml"
    )
    with open(config_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


_DEFAULT_MAX_PAGES = 20  # fallback if not set in sources.yaml


def _domain(url: str) -> str:
    """Return the registered domain (host without www.)."""
    host = urlparse(url).netloc.lower()
    return host.lstrip("www.")


def _is_allowed(url: str, whitelist: list[str]) -> bool:
    """Return True if the URL's domain is in the whitelist."""
    dom = _domain(url)
    return any(dom == w or dom.endswith("." + w) for w in whitelist)


# ---------------------------------------------------------------------------
# Per-source raw fetchers
# ---------------------------------------------------------------------------

async def _crawl_news(
    seed_url: str,
    depth: int,
    whitelist: list[str],
    max_pages: int = _DEFAULT_MAX_PAGES,
) -> list[dict]:
    """
    Crawl a news website (e.g. Reuters) using crawl4ai.

    Returns a list of raw page dicts:
        {url, html, markdown, links, source_type}

    max_pages caps total pages visited to prevent BFS explosion.
    """
    results: list[dict] = []
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(seed_url, 0)]

    async with AsyncWebCrawler(verbose=False) as crawler:
        while queue and len(results) < max_pages:
            current_url, current_depth = queue.pop(0)
            if current_url in visited:
                continue
            if not _is_allowed(current_url, whitelist):
                logger.debug("Skipping out-of-whitelist URL: %s", current_url)
                continue

            visited.add(current_url)
            logger.info(
                "[news] Crawling (depth=%d, %d/%d): %s",
                current_depth, len(results) + 1, max_pages, current_url,
            )

            try:
                result = await crawler.arun(
                    url=current_url,
                    cache_mode=CacheMode.BYPASS,
                )
                if not result.success:
                    logger.warning("[news] Failed to fetch %s", current_url)
                    continue

                page = {
                    "url": current_url,
                    "html": result.html or "",
                    "markdown": result.markdown or "",
                    "links": [],
                    "source_type": "news",
                }

                # Collect outbound links for deeper crawl
                if current_depth < depth and result.links:
                    for link_obj in result.links.get("internal", []):
                        href = link_obj.get("href", "")
                        if href and href not in visited and _is_allowed(href, whitelist):
                            queue.append((href, current_depth + 1))
                            page["links"].append(href)

                results.append(page)

            except Exception as exc:
                logger.error("[news] Error crawling %s: %s", current_url, exc)

    logger.info("[news] Collected %d pages from %s", len(results), seed_url)
    return results


async def _crawl_social_reddit(
    seed_url: str,
    depth: int,
    whitelist: list[str],
    max_pages: int = _DEFAULT_MAX_PAGES,
) -> list[dict]:
    """
    Fetch Reddit JSON listings.

    Reddit's .json API returns structured data directly — no HTML parsing needed.
    We follow 'after' pagination instead of link-following for depth.
    max_pages caps total posts collected.
    """
    results: list[dict] = []
    headers = {
        "User-Agent": "MediaIntelligencePipeline/1.0 (educational project)",
    }

    # Normalise: ensure URL ends with .json
    base_url = seed_url if seed_url.endswith(".json") else seed_url.rstrip("/") + "/.json"

    pages_to_fetch = max(1, depth)  # depth maps to number of listing pages
    after: str | None = None

    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=20) as client:
        for page_num in range(pages_to_fetch):
            if len(results) >= max_pages:
                break

            params: dict[str, Any] = {"limit": min(25, max_pages - len(results))}
            if after:
                params["after"] = after

            logger.info("[social/reddit] Fetching page %d: %s", page_num + 1, base_url)
            try:
                resp = await client.get(base_url, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.error("[social/reddit] Failed to fetch %s: %s", base_url, exc)
                break

            posts = data.get("data", {}).get("children", [])
            if not posts:
                break

            for post in posts:
                post_data = post.get("data", {})
                results.append({
                    "url": "https://www.reddit.com" + post_data.get("permalink", ""),
                    "html": "",
                    "markdown": post_data.get("selftext", ""),
                    "raw_json": post_data,
                    "source_type": "social",
                    "links": [],
                })

            after = data.get("data", {}).get("after")
            if not after:
                break

    logger.info("[social/reddit] Collected %d posts from %s", len(results), seed_url)
    return results


async def _crawl_forum_hn(
    seed_url: str,
    depth: int,
    whitelist: list[str],
    max_pages: int = _DEFAULT_MAX_PAGES,
) -> list[dict]:
    """
    Crawl Hacker News front-page stories using crawl4ai.

    Strategy to avoid BFS explosion:
      - depth=0: fetch the front page only, collect item links
      - depth>=1: follow item links (depth=1), but NEVER recurse further from
        item pages — doing so would expand to hundreds of sub-item links.

    max_pages caps total pages visited.
    """
    results: list[dict] = []
    visited: set[str] = set()
    # Queue entries: (url, current_depth, is_front_page)
    queue: list[tuple[str, int]] = [(seed_url, 0)]

    async with AsyncWebCrawler(verbose=False) as crawler:
        while queue and len(results) < max_pages:
            current_url, current_depth = queue.pop(0)
            if current_url in visited:
                continue
            if not _is_allowed(current_url, whitelist):
                logger.debug("Skipping out-of-whitelist URL: %s", current_url)
                continue

            visited.add(current_url)
            logger.info(
                "[forum/hn] Crawling (depth=%d, %d/%d): %s",
                current_depth, len(results) + 1, max_pages, current_url,
            )

            try:
                result = await crawler.arun(
                    url=current_url,
                    cache_mode=CacheMode.BYPASS,
                )
                if not result.success:
                    logger.warning("[forum/hn] Failed to fetch %s", current_url)
                    continue

                page = {
                    "url": current_url,
                    "html": result.html or "",
                    "markdown": result.markdown or "",
                    "links": [],
                    "source_type": "forum",
                }

                # Only expand links FROM the front page (depth=0) to item pages.
                # Never expand from item pages — that causes exponential BFS.
                is_front_page = "item?id=" not in current_url
                if is_front_page and current_depth < depth and result.links:
                    slots_left = max_pages - len(results) - 1  # -1 for current page
                    added = 0
                    for link_obj in result.links.get("internal", []):
                        if added >= slots_left:
                            break
                        href = link_obj.get("href", "")
                        if href and "item?id=" in href and href not in visited:
                            full = (
                                href
                                if href.startswith("http")
                                else "https://news.ycombinator.com" + href
                            )
                            queue.append((full, current_depth + 1))
                            page["links"].append(full)
                            added += 1

                results.append(page)

            except Exception as exc:
                logger.error("[forum/hn] Error crawling %s: %s", current_url, exc)

    logger.info("[forum/hn] Collected %d pages from %s", len(results), seed_url)
    return results


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_SOURCE_CRAWLERS = {
    "news":   _crawl_news,
    "social": _crawl_social_reddit,
    "forum":  _crawl_forum_hn,
}


async def crawl_all() -> list[dict]:
    """
    Entry point for the scraper.

    Reads config/sources.yaml, crawls every source, and returns the combined
    list of raw page dicts. If one source fails entirely, it is logged and
    skipped — the rest continue.

    Respects crawl.max_pages_per_source (default: 20) to cap BFS expansion.
    """
    config = _load_config()
    depth: int = config.get("crawl", {}).get("depth", 1)
    whitelist: list[str] = config.get("crawl", {}).get("domain_whitelist", [])
    max_pages: int = config.get("crawl", {}).get("max_pages_per_source", _DEFAULT_MAX_PAGES)
    sources: list[dict] = config.get("sources", [])

    all_results: list[dict] = []

    for source in sources:
        url = source.get("url", "")
        src_type = source.get("type", "")

        if not url or not src_type:
            logger.warning("Skipping incomplete source config: %s", source)
            continue

        crawler_fn = _SOURCE_CRAWLERS.get(src_type)
        if crawler_fn is None:
            logger.warning("Unknown source type '%s' — skipping %s", src_type, url)
            continue

        try:
            logger.info(
                "=== Starting crawl: type=%s url=%s depth=%d max_pages=%d ===",
                src_type, url, depth, max_pages,
            )
            pages = await crawler_fn(url, depth, whitelist, max_pages)
            all_results.extend(pages)
        except Exception as exc:
            # One source failing must NOT abort the whole pipeline
            logger.error("Source '%s' (%s) failed: %s — continuing.", url, src_type, exc)

    logger.info("Total raw pages collected: %d", len(all_results))
    return all_results


# ---------------------------------------------------------------------------
# Sync wrapper (for use from run_pipeline.py)
# ---------------------------------------------------------------------------

def run_crawl() -> list[dict]:
    """Synchronous wrapper around crawl_all()."""
    return asyncio.run(crawl_all())


# ---------------------------------------------------------------------------
# Quick smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    pages = run_crawl()
    print(f"\nTotal pages/posts collected: {len(pages)}")
    for p in pages[:3]:
        print(f"  [{p['source_type']}] {p['url'][:80]}")

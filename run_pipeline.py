"""
run_pipeline.py

Main entry point for the Media Intelligence Pipeline.

Phases wired up here:
    Phase 1  — Crawl + Normalise
    Phase 2  — Entity extraction + DB storage          (TODO: Phase 2)
    Phase 3  — API server is started separately via uvicorn  (see README)

Usage:
    python run_pipeline.py
"""

from __future__ import annotations

import logging
import sys

# ---------------------------------------------------------------------------
# Logging — configure once at the top before any module import side-effects
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("pipeline")


# ---------------------------------------------------------------------------
# Phase 1 — Crawl & Normalise
# ---------------------------------------------------------------------------

def phase1_crawl_and_normalise() -> list[dict]:
    """
    Crawl all configured sources and normalise to the common schema.
    Returns a list of normalised content dicts.
    """
    from crawler.scraper import run_crawl
    from crawler.normaliser import normalise

    logger.info("=== PHASE 1: Crawl ===")
    raw_pages = run_crawl()
    logger.info("Raw pages collected: %d", len(raw_pages))

    logger.info("=== PHASE 1: Normalise ===")
    items = normalise(raw_pages)
    logger.info("Normalised items: %d", len(items))

    return items


# ---------------------------------------------------------------------------
# Phase 2 — Extract & Store  (stub — implemented in Phase 2)
# ---------------------------------------------------------------------------

def phase2_extract_and_store(items: list[dict]) -> None:
    """
    Extract entities + relationships from normalised items and store in SQLite.
    Implemented in Phase 2.
    """
    logger.info("=== PHASE 2: Extract & Store (not yet implemented) ===")
    # TODO Phase 2a: storage.db.insert_content(item) for each item
    # TODO Phase 2b: extractor.entities.extract_entities(item)
    # TODO Phase 2c: extractor.aliases.resolve_alias(name)
    # TODO Phase 2d: extractor.relationships.extract_relations(doc, entities)
    # TODO Phase 2e: storage.db.upsert_node / upsert_edge / link_edge_to_source


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("Media Intelligence Pipeline starting …")

    # --- Phase 1 ---
    items = phase1_crawl_and_normalise()

    if not items:
        logger.warning("No content collected — check config/sources.yaml and network.")
        sys.exit(1)

    # Print a brief summary per source type
    by_type: dict[str, int] = {}
    for item in items:
        by_type[item["source_type"]] = by_type.get(item["source_type"], 0) + 1
    for src_type, count in by_type.items():
        logger.info("  [%s] %d items", src_type, count)

    # --- Phase 2 (stub) ---
    phase2_extract_and_store(items)

    logger.info("Pipeline complete.")


if __name__ == "__main__":
    main()

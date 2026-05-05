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
# Phase 2 — Extract & Store
# ---------------------------------------------------------------------------

def phase2_extract_and_store(items: list[dict]) -> None:
    """
    Extract entities + relationships from normalised items and store in SQLite.
    
    For each content item:
      1. Insert content -> get content_id
      2. Extract entities -> normalise -> upsert nodes
      3. Extract relations -> upsert edges
      4. Link edges to content (provenance)
    """
    from storage.db import init_db, insert_content, upsert_node, upsert_edge, link_edge_to_source, get_all_nodes
    from extractor.entities import extract_entities, normalise_entity
    from extractor.relationships import extract_relations
    
    logger.info("=== PHASE 2: Extract & Store ===")
    
    # Initialize database
    logger.info("Initializing database …")
    init_db()
    
    # Track statistics
    stats = {
        "content_inserted": 0,
        "entities_extracted": 0,
        "nodes_created": 0,
        "relations_extracted": 0,
        "edges_created": 0,
    }
    
    # Get existing nodes for fuzzy matching
    known_nodes = [node["name"] for node in get_all_nodes()]
    
    for idx, item in enumerate(items, 1):
        logger.info("Processing item %d/%d: %s", idx, len(items), item.get("source_url", "?"))
        
        try:
            # Step 1: Insert content
            content_id = insert_content(item)
            stats["content_inserted"] += 1
            
            # Step 2: Extract and normalise entities
            raw_entities = extract_entities(item)
            stats["entities_extracted"] += len(raw_entities)
            
            # Normalise entity names and upsert nodes
            entity_map = {}  # raw_name -> (node_id, canonical_name)
            
            for ent in raw_entities:
                raw_name = ent["name"]
                ent_type = ent["type"]
                
                # Normalise the entity name
                canonical_name = normalise_entity(raw_name, ent_type, known_nodes)
                
                # Upsert node
                node_id = upsert_node(canonical_name, ent_type)
                entity_map[raw_name] = (node_id, canonical_name)
                
                # Add to known nodes for future fuzzy matching
                if canonical_name not in known_nodes:
                    known_nodes.append(canonical_name)
                    stats["nodes_created"] += 1
            
            # Step 3: Extract relationships
            relations = extract_relations(item, raw_entities)
            stats["relations_extracted"] += len(relations)
            
            # Step 4: Upsert edges and link to content
            for rel in relations:
                source_name = rel["source"]
                target_name = rel["target"]
                relation_type = rel["relation"]
                
                # Look up node IDs (use canonical names)
                source_info = entity_map.get(source_name)
                target_info = entity_map.get(target_name)
                
                if not source_info or not target_info:
                    logger.debug(
                        "Skipping relation (entity not in map): %s -[%s]-> %s",
                        source_name, relation_type, target_name
                    )
                    continue
                
                source_node_id = source_info[0]
                target_node_id = target_info[0]
                
                # Upsert edge
                edge_id = upsert_edge(source_node_id, target_node_id, relation_type)
                
                # Link edge to content (provenance)
                link_edge_to_source(edge_id, content_id)
                stats["edges_created"] += 1
        
        except Exception as exc:
            logger.error("Failed to process item %d (%s): %s", idx, item.get("source_url"), exc)
            continue
    
    # Log summary
    logger.info("=== Phase 2 Complete ===")
    logger.info("  Content inserted:      %d", stats["content_inserted"])
    logger.info("  Entities extracted:    %d", stats["entities_extracted"])
    logger.info("  Unique nodes created:  %d", stats["nodes_created"])
    logger.info("  Relations extracted:   %d", stats["relations_extracted"])
    logger.info("  Edges created/updated: %d", stats["edges_created"])


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

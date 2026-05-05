from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Database path — stored in project root
_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "media_intelligence.db"
)


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _get_connection() -> sqlite3.Connection:
    """Return a connection to the SQLite database."""
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row  # Access columns by name
    return conn


def init_db() -> None:
    """
    Initialize the database schema from storage/schema.sql.
    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS.
    """
    schema_path = os.path.join(
        os.path.dirname(__file__),
        "schema.sql"
    )
    
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema_sql = fh.read()
    
    conn = _get_connection()
    try:
        conn.executescript(schema_sql)
        conn.commit()
        logger.info("Database initialized: %s", _DB_PATH)
    finally:
        conn.close()


def insert_content(item: dict) -> int:
    """
    Insert a normalised content item into the content table.
    
    Args:
        item: dict with keys: source_url, source_type, scraped_at, 
              title, body, author, published_at
    
    Returns:
        content_id (int) of the inserted row
    """
    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO content (source_url, source_type, scraped_at, title, body, author, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.get("source_url"),
                item.get("source_type"),
                item.get("scraped_at"),
                item.get("title"),
                item.get("body"),
                item.get("author"),
                item.get("published_at"),
            )
        )
        conn.commit()
        content_id = cursor.lastrowid
        logger.debug("Inserted content id=%d: %s", content_id, item.get("source_url"))
        return content_id
    finally:
        conn.close()


def upsert_node(name: str, entity_type: str) -> int:
    """
    Insert or update a node (entity).
    
    If the node already exists (by name), increment mention_count.
    Otherwise, create a new node.
    
    Args:
        name: Canonical entity name (already normalised)
        entity_type: PERSON | ORG | GPE | TOPIC
    
    Returns:
        node_id (int)
    """
    conn = _get_connection()
    try:
        # Check if node exists
        cursor = conn.execute("SELECT id, mention_count FROM nodes WHERE name = ?", (name,))
        row = cursor.fetchone()
        
        if row:
            # Node exists — increment mention count
            node_id = row["id"]
            new_count = row["mention_count"] + 1
            conn.execute(
                "UPDATE nodes SET mention_count = ? WHERE id = ?",
                (new_count, node_id)
            )
            conn.commit()
            logger.debug("Updated node id=%d: %s (mentions=%d)", node_id, name, new_count)
            return node_id
        else:
            # Create new node
            cursor = conn.execute(
                """
                INSERT INTO nodes (name, type, first_seen, mention_count)
                VALUES (?, ?, ?, 1)
                """,
                (name, entity_type, _now_iso())
            )
            conn.commit()
            node_id = cursor.lastrowid
            logger.debug("Inserted node id=%d: %s (%s)", node_id, name, entity_type)
            return node_id
    finally:
        conn.close()


def upsert_edge(source_node_id: int, target_node_id: int, relation_type: str) -> int:
    """
    Insert or update an edge (relationship).
    
    If the edge already exists (same source, target, relation_type),
    increment weight and update last_seen.
    Otherwise, create a new edge.
    
    Args:
        source_node_id: ID of the source node
        target_node_id: ID of the target node
        relation_type: Type of relationship (e.g., "quoted_by", "accused_of")
    
    Returns:
        edge_id (int)
    """
    conn = _get_connection()
    try:
        # Check if edge exists
        cursor = conn.execute(
            """
            SELECT id, weight FROM edges
            WHERE source_node = ? AND target_node = ? AND relation_type = ?
            """,
            (source_node_id, target_node_id, relation_type)
        )
        row = cursor.fetchone()
        
        if row:
            # Edge exists — increment weight and update last_seen
            edge_id = row["id"]
            new_weight = row["weight"] + 1
            conn.execute(
                """
                UPDATE edges SET weight = ?, last_seen = ?
                WHERE id = ?
                """,
                (new_weight, _now_iso(), edge_id)
            )
            conn.commit()
            logger.debug(
                "Updated edge id=%d: %d -[%s]-> %d (weight=%d)",
                edge_id, source_node_id, relation_type, target_node_id, new_weight
            )
            return edge_id
        else:
            # Create new edge
            now = _now_iso()
            cursor = conn.execute(
                """
                INSERT INTO edges (source_node, target_node, relation_type, weight, first_seen, last_seen)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (source_node_id, target_node_id, relation_type, now, now)
            )
            conn.commit()
            edge_id = cursor.lastrowid
            logger.debug(
                "Inserted edge id=%d: %d -[%s]-> %d",
                edge_id, source_node_id, relation_type, target_node_id
            )
            return edge_id
    finally:
        conn.close()


def link_edge_to_source(edge_id: int, content_id: int) -> None:
    """
    Link an edge to the content it was extracted from (provenance).
    
    Uses INSERT OR IGNORE to avoid duplicate links.
    
    Args:
        edge_id: ID of the edge
        content_id: ID of the content record
    """
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO edge_sources (edge_id, content_id) VALUES (?, ?)",
            (edge_id, content_id)
        )
        conn.commit()
        logger.debug("Linked edge %d to content %d", edge_id, content_id)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Query helpers (for API use in Phase 3)
# ---------------------------------------------------------------------------

def get_node_by_name(name: str) -> dict | None:
    """
    Retrieve a node by its canonical name.
    
    Returns:
        dict with keys: id, name, type, first_seen, mention_count
        or None if not found
    """
    conn = _get_connection()
    try:
        cursor = conn.execute("SELECT * FROM nodes WHERE name = ?", (name,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_nodes() -> list[dict]:
    """Return all nodes as a list of dicts."""
    conn = _get_connection()
    try:
        cursor = conn.execute("SELECT * FROM nodes")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_all_edges() -> list[dict]:
    """Return all edges as a list of dicts."""
    conn = _get_connection()
    try:
        cursor = conn.execute("SELECT * FROM edges")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    
    print("Initializing database …")
    init_db()
    
    print("\nInserting test node …")
    node_id = upsert_node("Test Entity", "PERSON")
    print(f"  Created node_id={node_id}")
    
    print("\nUpserting same node again (should increment mention_count) …")
    node_id_2 = upsert_node("Test Entity", "PERSON")
    print(f"  Returned node_id={node_id_2} (should match {node_id})")
    
    print("\nInserting test content …")
    test_content = {
        "source_url": "https://example.com/test",
        "source_type": "news",
        "scraped_at": _now_iso(),
        "title": "Test Article",
        "body": "This is a test.",
        "author": "Test Author",
        "published_at": None,
    }
    content_id = insert_content(test_content)
    print(f"  Created content_id={content_id}")
    
    print("\nDatabase test complete. Check media_intelligence.db")

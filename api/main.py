from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# Database path
_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "media_intelligence.db"
)

app = FastAPI(
    title="Media Intelligence Graph API",
    description="Query entities, relationships, and emerging connections from scraped media content",
    version="1.0.0",
)


def _get_connection() -> sqlite3.Connection:
    """Return a connection to the SQLite database."""
    if not os.path.exists(_DB_PATH):
        raise HTTPException(
            status_code=503,
            detail=f"Database not found. Run the pipeline first: python3 run_pipeline.py"
        )
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/", tags=["Health"])
def health_check() -> dict:
    """
    Health check endpoint.
    
    Returns:
        Status and basic database statistics
    """
    try:
        conn = _get_connection()
        cursor = conn.execute("SELECT COUNT(*) as count FROM nodes")
        node_count = cursor.fetchone()["count"]
        
        cursor = conn.execute("SELECT COUNT(*) as count FROM edges")
        edge_count = cursor.fetchone()["count"]
        
        cursor = conn.execute("SELECT COUNT(*) as count FROM content")
        content_count = cursor.fetchone()["count"]
        
        conn.close()
        
        return {
            "status": "ok",
            "database": {
                "nodes": node_count,
                "edges": edge_count,
                "content": content_count,
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")


@app.get("/entity/{name}/network", tags=["Entities"])
def get_entity_network(
    name: str,
    depth: int = Query(2, ge=1, le=3, description="Network depth (1-3)")
) -> dict:
    """
    Get the network of connections for an entity.
    
    Returns depth-1 and depth-2 (or specified depth) connections.
    Uses fuzzy matching to find the entity if exact match fails.
    
    Args:
        name: Entity name (fuzzy matched)
        depth: How many hops from the center entity (default: 2)
    
    Returns:
        {
            "center": {"name": str, "type": str, "id": int},
            "nodes": [{"id": int, "name": str, "type": str, "mention_count": int}, ...],
            "edges": [{"from": str, "to": str, "relation": str, "weight": int}, ...]
        }
    """
    conn = _get_connection()
    
    try:
        # Find the entity (fuzzy match if needed)
        center_node = _find_entity_fuzzy(conn, name)
        
        if not center_node:
            raise HTTPException(
                status_code=404,
                detail=f"Entity '{name}' not found. Try a different spelling or check available entities."
            )
        
        # Get network
        nodes, edges = _get_network(conn, center_node["id"], depth)
        
        return {
            "center": {
                "id": center_node["id"],
                "name": center_node["name"],
                "type": center_node["type"],
            },
            "nodes": nodes,
            "edges": edges,
        }
    
    finally:
        conn.close()


def _find_entity_fuzzy(conn: sqlite3.Connection, name: str, threshold: int = 70) -> dict | None:
    """
    Find an entity by name using fuzzy matching.
    
    Args:
        conn: Database connection
        name: Entity name to search for
        threshold: Minimum fuzzy match score (0-100)
    
    Returns:
        Node dict or None if not found
    """
    # Try exact match first (case-insensitive)
    cursor = conn.execute(
        "SELECT * FROM nodes WHERE LOWER(name) = LOWER(?)",
        (name,)
    )
    row = cursor.fetchone()
    if row:
        return dict(row)
    
    # Try alias resolution
    from extractor.aliases import resolve_alias
    canonical = resolve_alias(name)
    if canonical != name:
        cursor = conn.execute(
            "SELECT * FROM nodes WHERE LOWER(name) = LOWER(?)",
            (canonical,)
        )
        row = cursor.fetchone()
        if row:
            logger.info(f"Alias resolved '{name}' to '{canonical}'")
            return dict(row)
    
    # Fuzzy match against all nodes
    cursor = conn.execute("SELECT * FROM nodes")
    all_nodes = [dict(row) for row in cursor.fetchall()]
    
    best_match = None
    best_score = 0
    
    for node in all_nodes:
        score = fuzz.ratio(name.lower(), node["name"].lower())
        if score > best_score:
            best_score = score
            best_match = node
    
    if best_score >= threshold:
        logger.info(f"Fuzzy matched '{name}' to '{best_match['name']}' (score={best_score})")
        return best_match
    
    return None


def _get_network(conn: sqlite3.Connection, center_id: int, depth: int) -> tuple[list[dict], list[dict]]:
    """
    Get the network around a center node up to specified depth.
    
    Args:
        conn: Database connection
        center_id: ID of the center node
        depth: How many hops from center
    
    Returns:
        (nodes, edges) tuple
    """
    visited_nodes = {center_id}
    visited_edges = set()
    nodes = []
    edges = []
    
    # BFS to specified depth
    current_layer = {center_id}
    
    for d in range(depth):
        next_layer = set()
        
        for node_id in current_layer:
            # Get outgoing edges
            cursor = conn.execute(
                """
                SELECT e.*, n1.name as source_name, n2.name as target_name
                FROM edges e
                JOIN nodes n1 ON e.source_node = n1.id
                JOIN nodes n2 ON e.target_node = n2.id
                WHERE e.source_node = ?
                """,
                (node_id,)
            )
            
            for row in cursor.fetchall():
                edge_id = row["id"]
                target_id = row["target_node"]
                
                if edge_id not in visited_edges:
                    visited_edges.add(edge_id)
                    edges.append({
                        "from": row["source_name"],
                        "to": row["target_name"],
                        "relation": row["relation_type"],
                        "weight": row["weight"],
                    })
                
                if target_id not in visited_nodes:
                    visited_nodes.add(target_id)
                    next_layer.add(target_id)
            
            # Get incoming edges
            cursor = conn.execute(
                """
                SELECT e.*, n1.name as source_name, n2.name as target_name
                FROM edges e
                JOIN nodes n1 ON e.source_node = n1.id
                JOIN nodes n2 ON e.target_node = n2.id
                WHERE e.target_node = ?
                """,
                (node_id,)
            )
            
            for row in cursor.fetchall():
                edge_id = row["id"]
                source_id = row["source_node"]
                
                if edge_id not in visited_edges:
                    visited_edges.add(edge_id)
                    edges.append({
                        "from": row["source_name"],
                        "to": row["target_name"],
                        "relation": row["relation_type"],
                        "weight": row["weight"],
                    })
                
                if source_id not in visited_nodes:
                    visited_nodes.add(source_id)
                    next_layer.add(source_id)
        
        current_layer = next_layer
    
    # Fetch node details for all visited nodes
    if visited_nodes:
        placeholders = ",".join("?" * len(visited_nodes))
        cursor = conn.execute(
            f"SELECT * FROM nodes WHERE id IN ({placeholders})",
            tuple(visited_nodes)
        )
        
        for row in cursor.fetchall():
            nodes.append({
                "id": row["id"],
                "name": row["name"],
                "type": row["type"],
                "mention_count": row["mention_count"],
            })
    
    return nodes, edges


# ---------------------------------------------------------------------------
# Emerging connections endpoint
# ---------------------------------------------------------------------------

@app.get("/connections/new", tags=["Connections"])
def get_emerging_connections(
    since: str = Query(..., description="ISO-8601 timestamp (e.g., 2025-01-01T00:00:00Z)")
) -> dict:
    """
    Get edges that are new or have grown significantly since a timestamp.
    
    An edge is flagged if:
    1. It's new (first_seen after 'since'), OR
    2. Its weight has increased by more than 2× its average daily rate
    
    Args:
        since: ISO-8601 timestamp
    
    Returns:
        {
            "since": str,
            "new_edges": [...],
            "growing_edges": [...]
        }
    """
    conn = _get_connection()
    
    try:
        # Validate timestamp
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid timestamp format. Use ISO-8601 (e.g., 2025-01-01T00:00:00Z)"
            )
        
        # Get new edges (first_seen after since)
        cursor = conn.execute(
            """
            SELECT e.*, n1.name as source_name, n2.name as target_name
            FROM edges e
            JOIN nodes n1 ON e.source_node = n1.id
            JOIN nodes n2 ON e.target_node = n2.id
            WHERE e.first_seen > ?
            ORDER BY e.first_seen DESC
            """,
            (since,)
        )
        
        new_edges = []
        for row in cursor.fetchall():
            new_edges.append({
                "from": row["source_name"],
                "to": row["target_name"],
                "relation": row["relation_type"],
                "weight": row["weight"],
                "first_seen": row["first_seen"],
            })
        
        # Get growing edges (weight increased significantly)
        # For simplicity, we flag edges where weight > 1 and last_seen > since
        # A more sophisticated approach would calculate daily rate
        cursor = conn.execute(
            """
            SELECT e.*, n1.name as source_name, n2.name as target_name
            FROM edges e
            JOIN nodes n1 ON e.source_node = n1.id
            JOIN nodes n2 ON e.target_node = n2.id
            WHERE e.first_seen <= ? AND e.last_seen > ? AND e.weight > 1
            ORDER BY e.weight DESC
            """,
            (since, since)
        )
        
        growing_edges = []
        for row in cursor.fetchall():
            # Calculate if growth is significant
            # Simplified: flag if weight > 2 (indicating multiple recent mentions)
            if row["weight"] >= 2:
                growing_edges.append({
                    "from": row["source_name"],
                    "to": row["target_name"],
                    "relation": row["relation_type"],
                    "weight": row["weight"],
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                })
        
        return {
            "since": since,
            "new_edges": new_edges,
            "growing_edges": growing_edges,
            "summary": {
                "new_count": len(new_edges),
                "growing_count": len(growing_edges),
            }
        }
    
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Centrality ranking endpoint
# ---------------------------------------------------------------------------

@app.get("/entities/central", tags=["Entities"])
def get_central_entities(
    limit: int = Query(20, ge=1, le=100, description="Number of entities to return")
) -> dict:
    """
    Rank entities by centrality score.
    
    Score formula:
        score = (degree × 0.5) + (unique_relation_types × 0.3) + (betweenness_proxy × 0.2)
    
    Where:
    - degree: number of direct connections
    - unique_relation_types: diversity of connection types
    - betweenness_proxy: how often entity bridges otherwise unconnected entities
    
    Args:
        limit: Maximum number of entities to return (default: 20)
    
    Returns:
        {
            "entities": [
                {
                    "name": str,
                    "type": str,
                    "score": float,
                    "metrics": {
                        "degree": int,
                        "unique_relations": int,
                        "betweenness_proxy": float
                    }
                },
                ...
            ]
        }
    """
    conn = _get_connection()
    
    try:
        # Get all nodes
        try:
            cursor = conn.execute("SELECT * FROM nodes")
        except sqlite3.OperationalError:
            # Handle empty/uninitialized database tables gracefully
            return {
                "entities": [],
                "total_entities": 0,
            }
        nodes = [dict(row) for row in cursor.fetchall()]
        
        # Calculate centrality for each node
        centrality_scores = []
        
        for node in nodes:
            node_id = node["id"]
            
            # Calculate degree (total connections)
            cursor = conn.execute(
                """
                SELECT COUNT(*) as count FROM edges
                WHERE source_node = ? OR target_node = ?
                """,
                (node_id, node_id)
            )
            degree = cursor.fetchone()["count"]
            
            # Calculate unique relation types
            cursor = conn.execute(
                """
                SELECT COUNT(DISTINCT relation_type) as count FROM edges
                WHERE source_node = ? OR target_node = ?
                """,
                (node_id, node_id)
            )
            unique_relations = cursor.fetchone()["count"]
            
            # Calculate betweenness proxy
            # Simplified: count how many unique pairs of neighbors this node connects
            cursor = conn.execute(
                """
                SELECT DISTINCT 
                    CASE WHEN source_node = ? THEN target_node ELSE source_node END as neighbor
                FROM edges
                WHERE source_node = ? OR target_node = ?
                """,
                (node_id, node_id, node_id)
            )
            neighbors = [row["neighbor"] for row in cursor.fetchall()]
            
            # Betweenness proxy: number of neighbor pairs
            betweenness_proxy = len(neighbors) * (len(neighbors) - 1) / 2 if len(neighbors) > 1 else 0
            
            # Calculate composite score
            score = (degree * 0.5) + (unique_relations * 0.3) + (betweenness_proxy * 0.2)
            
            centrality_scores.append({
                "name": node["name"],
                "type": node["type"],
                "score": round(score, 2),
                "metrics": {
                    "degree": degree,
                    "unique_relations": unique_relations,
                    "betweenness_proxy": round(betweenness_proxy, 2),
                }
            })
        
        # Sort by score descending
        centrality_scores.sort(key=lambda x: x["score"], reverse=True)
        
        return {
            "entities": centrality_scores[:limit],
            "total_entities": len(nodes),
        }
    
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Additional utility endpoints
# ---------------------------------------------------------------------------

@app.get("/entities", tags=["Entities"])
def list_entities(
    type: str | None = Query(None, description="Filter by entity type (PERSON, ORG, GPE)"),
    limit: int = Query(50, ge=1, le=500, description="Number of entities to return")
) -> dict:
    """
    List all entities, optionally filtered by type.
    
    Args:
        type: Entity type filter (optional)
        limit: Maximum number of entities to return
    
    Returns:
        List of entities with their metadata
    """
    conn = _get_connection()
    
    try:
        if type:
            cursor = conn.execute(
                "SELECT * FROM nodes WHERE type = ? ORDER BY mention_count DESC LIMIT ?",
                (type.upper(), limit)
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM nodes ORDER BY mention_count DESC LIMIT ?",
                (limit,)
            )
        
        entities = []
        for row in cursor.fetchall():
            entities.append({
                "id": row["id"],
                "name": row["name"],
                "type": row["type"],
                "mention_count": row["mention_count"],
                "first_seen": row["first_seen"],
            })
        
        return {
            "entities": entities,
            "count": len(entities),
        }
    
    finally:
        conn.close()


@app.get("/relations", tags=["Connections"])
def list_relations(
    relation_type: str | None = Query(None, description="Filter by relation type"),
    limit: int = Query(50, ge=1, le=500, description="Number of relations to return")
) -> dict:
    """
    List all relationships, optionally filtered by type.
    
    Args:
        relation_type: Relation type filter (optional)
        limit: Maximum number of relations to return
    
    Returns:
        List of relationships with their metadata
    """
    conn = _get_connection()
    
    try:
        if relation_type:
            cursor = conn.execute(
                """
                SELECT e.*, n1.name as source_name, n2.name as target_name
                FROM edges e
                JOIN nodes n1 ON e.source_node = n1.id
                JOIN nodes n2 ON e.target_node = n2.id
                WHERE e.relation_type = ?
                ORDER BY e.weight DESC
                LIMIT ?
                """,
                (relation_type, limit)
            )
        else:
            cursor = conn.execute(
                """
                SELECT e.*, n1.name as source_name, n2.name as target_name
                FROM edges e
                JOIN nodes n1 ON e.source_node = n1.id
                JOIN nodes n2 ON e.target_node = n2.id
                ORDER BY e.weight DESC
                LIMIT ?
                """,
                (limit,)
            )
        
        relations = []
        for row in cursor.fetchall():
            relations.append({
                "from": row["source_name"],
                "to": row["target_name"],
                "relation": row["relation_type"],
                "weight": row["weight"],
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
            })
        
        return {
            "relations": relations,
            "count": len(relations),
        }
    
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Run with: uvicorn api.main:app --reload
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

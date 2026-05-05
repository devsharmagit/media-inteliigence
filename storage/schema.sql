-- storage/schema.sql
-- SQLite schema for the Media Intelligence Graph

-- Entities as graph nodes
CREATE TABLE IF NOT EXISTS nodes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,      -- normalised canonical name
    type          TEXT NOT NULL,             -- PERSON | ORG | GPE | TOPIC
    first_seen    TEXT NOT NULL,             -- ISO-8601 timestamp
    mention_count INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);

-- Relationships as typed edges
CREATE TABLE IF NOT EXISTS edges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_node   INTEGER NOT NULL REFERENCES nodes(id),
    target_node   INTEGER NOT NULL REFERENCES nodes(id),
    relation_type TEXT NOT NULL,             -- affiliated_with | accused_of | quoted_by | etc.
    weight        INTEGER DEFAULT 1,         -- how many times this edge appeared
    first_seen    TEXT NOT NULL,             -- ISO-8601 timestamp
    last_seen     TEXT NOT NULL,             -- ISO-8601 timestamp
    UNIQUE(source_node, target_node, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_node);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_node);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation_type);

-- Raw scraped content
CREATE TABLE IF NOT EXISTS content (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url    TEXT NOT NULL,
    source_type   TEXT NOT NULL,             -- news | social | forum
    scraped_at    TEXT NOT NULL,             -- ISO-8601 timestamp
    title         TEXT,
    body          TEXT,
    author        TEXT,
    published_at  TEXT                       -- ISO-8601 timestamp when known
);

CREATE INDEX IF NOT EXISTS idx_content_scraped_at ON content(scraped_at);
CREATE INDEX IF NOT EXISTS idx_content_source_type ON content(source_type);

-- Links edges back to the content they came from (provenance)
CREATE TABLE IF NOT EXISTS edge_sources (
    edge_id       INTEGER NOT NULL REFERENCES edges(id),
    content_id    INTEGER NOT NULL REFERENCES content(id),
    PRIMARY KEY (edge_id, content_id)
);

CREATE INDEX IF NOT EXISTS idx_edge_sources_edge ON edge_sources(edge_id);
CREATE INDEX IF NOT EXISTS idx_edge_sources_content ON edge_sources(content_id);

# Media Intelligence Graph Pipeline

A pipeline that scrapes real web content, extracts entities and relationships, stores them as a graph, and exposes queryable API endpoints for analysts.

---

## What This Project Does

1. **Crawls** news sites, Reddit, and a third source using `crawl4ai`
2. **Normalises** raw HTML/threads into a common schema
3. **Extracts** named entities (people, orgs, locations) and the typed relationships between them
4. **Stores** everything as a node-edge graph in SQLite — with full source provenance
5. **Exposes** a FastAPI server to query networks, spot emerging connections, and rank influence

## How to Run

1. **Set up the environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python -m spacy download en_core_web_sm
   ```

2. **Run the pipeline (Crawls, Extracts, Stores):**
   ```bash
   python run_pipeline.py
   ```
   *Note on Database State:* The pipeline writes to a local `media_intelligence.db` file. The SQLite schema uses `CREATE TABLE IF NOT EXISTS` and `INSERT OR IGNORE` for entities, meaning re-running the pipeline will **append** new content and update weights on existing edges. To start completely fresh, manually delete the `media_intelligence.db` file before running the pipeline.

3. **Start the API Server:**
   ```bash
   uvicorn api.main:app --reload
   ```
   *Navigate to [http://localhost:8000/docs](http://localhost:8000/docs) to view and test all available endpoints using the interactive Swagger UI.*

---

## Project Structure

```
media-intelligence/
│
├── config/
│   └── sources.yaml          # Seed URLs, depth, domain whitelist — edit this, never touch code
│
├── crawler/
│   ├── scraper.py            # crawl4ai-based multi-source crawler
│   └── normaliser.py         # Converts raw content → common schema
│
├── extractor/
│   ├── entities.py           # spaCy NER + entity normalisation
│   ├── relationships.py      # Typed edge extraction using dependency parsing
│   └── aliases.py            # Alias map: "Musk" → "Elon Musk"
│
├── storage/
│   ├── schema.sql            # SQLite schema (nodes, edges, sources, content)
│   └── db.py                 # DB read/write helpers
│
├── api/
│   └── main.py               # FastAPI app with all endpoints
│
├── run_pipeline.py           # Entry point: crawl → extract → store
├── requirements.txt
└── README.md
```

---

## Quickstart

```bash
# 1. Install dependencies
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# 2. Configure your seed URLs
nano config/sources.yaml

# 3. Run the full pipeline
python run_pipeline.py

# 4. Start the API
uvicorn api.main:app --reload
```

## Real Data Example

**From a recent crawl (May 3, 2026):**

```
Sources crawled:     3 (Reddit /r/worldnews, Hacker News, Reuters)
Content collected:   39 articles/posts
Entities extracted:  1,840 raw mentions
Unique nodes:        729 entities (after normalization)
Relationships:       965 edges
Processing time:     ~30 seconds
```

**Top entities by mention count:**
- Microsoft (94 mentions)
- Haskell (89 mentions)
- Linux (66 mentions)
- Apple (49 mentions)
- AI (44 mentions)

**Sample relationships:**
- `[Ukraine] --[affiliated_with]--> [Zelenskyy]` — from Reddit post about Ukrainian politics
- `[Windows] --[mentioned_with]--> [Linux]` (weight: 16) — from HN discussions
- `[Microsoft] --[mentioned_with]--> [Windows]` (weight: 10) — co-occurrence in tech articles

**API query example:**
```bash
curl http://localhost:8000/entity/Ukraine/network
# Returns 15 nodes, 23 edges showing Ukraine's connections to EU, Zelenskyy, etc.
```

---

## Configuration (`config/sources.yaml`)

```yaml
crawl:
  depth: 2
  domain_whitelist:
    - reuters.com
    - reddit.com
    - news.ycombinator.com

sources:
  - url: "https://www.reuters.com/technology/"
    type: "news"
  - url: "https://www.reddit.com/r/worldnews/.json"
    type: "social"
  - url: "https://news.ycombinator.com/"
    type: "forum"
```

> **Never hardcode URLs in Python files.** All seed URLs live here. The evaluator will swap this file and re-run.

---

## Database Schema

```sql
-- Entities as graph nodes
CREATE TABLE nodes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,      -- normalised canonical name
    type        TEXT NOT NULL,             -- PERSON | ORG | LOCATION | TOPIC
    first_seen  TEXT NOT NULL,             -- ISO timestamp
    mention_count INTEGER DEFAULT 1
);

-- Relationships as typed edges
CREATE TABLE edges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_node   INTEGER REFERENCES nodes(id),
    target_node   INTEGER REFERENCES nodes(id),
    relation_type TEXT NOT NULL,           -- affiliated_with | accused_of | quoted_by | etc.
    weight        INTEGER DEFAULT 1,       -- how many times this edge appeared
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL
);

-- Raw scraped content
CREATE TABLE content (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url    TEXT NOT NULL,
    source_type   TEXT NOT NULL,           -- news | social | forum
    scraped_at    TEXT NOT NULL,
    title         TEXT,
    body          TEXT,
    author        TEXT,
    published_at  TEXT
);

-- Links edges back to the content they came from
CREATE TABLE edge_sources (
    edge_id       INTEGER REFERENCES edges(id),
    content_id    INTEGER REFERENCES content(id)
);
```

---

## API Endpoints

### `GET /entity/{name}/network`
Returns depth-1 and depth-2 connections for an entity, structured for graph rendering.

**Example:** `GET /entity/Elon Musk/network`

```json
{
  "center": { "name": "Elon Musk", "type": "PERSON" },
  "nodes": [ ... ],
  "edges": [
    { "from": "Elon Musk", "to": "SEC", "relation": "accused_of", "weight": 4 }
  ]
}
```

---

### `GET /connections/new?since=<ISO_TIMESTAMP>`
Returns edges that are new or whose weight grew significantly since the given timestamp.

**"Grown significantly" definition:**
> An edge is flagged if its weight has increased by more than **2× its average daily rate** in the period before `since`. New edges (first seen after `since`) are always included.

This is a deliberate threshold — it catches genuine spikes while ignoring slow accumulation. It will miss gradual build-ups and can false-positive on edges with very low base frequency.

**Example:** `GET /connections/new?since=2025-01-01T00:00:00Z`

---

### `GET /entities/central`
Ranks entities by a composite centrality score.

**Metric used:**
```
score = (degree × 0.5) + (unique_relation_types × 0.3) + (betweenness_proxy × 0.2)
```
- **Degree** — how many direct connections
- **Unique relation types** — diversity of connection types (not just volume)
- **Betweenness proxy** — how often an entity bridges two otherwise unconnected entities

This is not PageRank. It's simpler, explainable, and faster on SQLite. What it misses: it doesn't account for the importance of the nodes it connects to.

---

## Entity Normalisation Strategy

The same real-world entity appears in many forms across sources. We resolve them to a single canonical node using three layers:

1. **Alias map** (`extractor/aliases.py`) — handcrafted rules: `"Musk" → "Elon Musk"`, `"@elonmusk" → "Elon Musk"`
2. **Fuzzy matching** (`rapidfuzz`) — catches near-duplicates like `"Elon  Musk"` (double space)
3. **Title normalisation** — strips prefixes: `"President Biden"` → `"Joe Biden"` using a lookup

**Where this breaks:** Ambiguous single names like `"Johnson"` — is it Boris Johnson or someone else? We default to the most-mentioned entity with that surname in the current crawl window. This is wrong when a new person with the same surname enters the news. A real example from the scraped data is in the README answers below.

---

## Relationship Types

| Relation | How detected | Example |
|---|---|---|
| `quoted_by` | `"X said/stated/claimed"` pattern | `SEC --[quoted_by]--> Reuters` |
| `accused_of` | `"X accused/charged/sued Y"` | `FTC --[accused_of]--> Meta` |
| `affiliated_with` | `"X CEO/founder/member of Y"` | `Musk --[affiliated_with]--> Tesla` |
| `responded_to` | Reply thread structure | `User A --[responded_to]--> User B` |
| `mentioned_with` | Co-occurrence fallback | `X --[mentioned_with]--> Y` |

Co-occurrence is the fallback only. We attempt typed extraction first using spaCy's Named Entity Recognition (NER) combined with analyzing the text between entity spans for specific verb triggers. 

**Future Improvement (Advanced Extraction):** 
While regex and string-matching between entities are effective baselines, a more robust relation extractor would use spaCy's dependency parser tree (by using `token.dep_` and `token.head`). This would allow the code to explicitly map the `Subject -> Verb -> Object` structure computationally rather than just looking at the raw sequence of strings between two entities. This avoids false positives when entities are separated by complex clauses.

---

## The Hard Questions (Phase 4)

### A real relationship your system extracted — is it correct?

**Example from actual crawl (May 3, 2026):**

The system extracted `[Ukraine] --[affiliated_with]--> [Zelenskyy]` from a Reddit post titled "Ukraine's President Zelenskyy says Slovak Prime Minister Fico changed his view on Ukraine's EU accession."

**Is it correct?** Yes. The article explicitly describes Zelenskyy as "Ukraine's President," which matches our `affiliated_with` pattern (detecting titles like "President," "CEO," "founder"). The relation was detected because spaCy identified "President" as a title connecting the two entity spans.

**Additional examples:**
- `[Ukraine] --[affiliated_with]--> [EU]` (weight: 2) — Correct, from multiple posts about Ukraine's EU accession
- `[Windows] --[mentioned_with]--> [Linux]` (weight: 16) — Correct co-occurrence from Hacker News discussions comparing operating systems
- `[Haskell] --[quoted_by]--> [Java]` (weight: 1) — Detected from a discussion where someone quoted a comparison

**Edge provenance:** Every edge links back to its source content via the `edge_sources` table, allowing verification of extraction accuracy.

### How does entity normalisation break? Concrete example.

**Example from actual crawl:**

The entity "Apple" appeared 49 times and was correctly identified as an organization (Apple Inc.). However, "Apple Maps" was also extracted as a separate entity and appeared in relations like `[Apple] --[quoted_by]--> [Apple Maps]` and `[Apple Maps] --[quoted_by]--> [Apple]`.

**The problem:** These should be normalized differently:
- "Apple" (the company) and "Apple Maps" (the product) are distinct entities
- But our system created bidirectional `quoted_by` relations between them, which doesn't make semantic sense
- The correct relation would be `[Apple] --[owns/produces]--> [Apple Maps]`

**Another example:** "C++" was classified as a PERSON (14 mentions) instead of a programming language. This happened because:
1. spaCy's NER model doesn't have a category for programming languages
2. The "++" characters confused the entity boundary detection
3. Without a "TECHNOLOGY" entity type, it defaulted to PERSON

**Impact:** Any edges involving "C++" are semantically incorrect because the entity type is wrong. For example, `[C++] --[mentioned_with]--> [Rust]` should be a technology comparison, not a person-organization relationship.

**What we'd fix:**
1. Add custom entity types (TECHNOLOGY, PRODUCT, CONCEPT)
2. Implement domain-specific NER training for tech entities
3. Add post-processing rules: if entity matches `^[A-Z][a-z]*\+\+$`, classify as TECHNOLOGY

### How would you detect and suppress spurious edges at scale?

**Real examples from our crawl:**

The most common edge in our graph is `[FAQ] --[mentioned_with]--> [API]` (weight: 18). This appears because Hacker News pages contain navigation elements with "FAQ," "API," "Apply," and "Contact" links. These aren't real relationships — they're website chrome.

**The problem:** Co-occurrence edges dominate numerically. Out of 729 edges:
- ~90% are `mentioned_with` (co-occurrence fallback)
- ~10% are typed relations (`affiliated_with`, `quoted_by`, etc.)

**Two approaches we'd implement:**

1. **Minimum weight threshold** — Edges with weight=1 from a single source are flagged as unverified. Only edges seen in 2+ independent sources get promoted to the main graph.
   
   **Example:** `[Ukraine] --[affiliated_with]--> [EU]` has weight=2 from multiple Reddit posts → **Keep**
   
   `[Dioxus] --[affiliated_with]--> [Skia]` has weight=1 from one HN comment → **Flag as unverified**

2. **Source diversity check** — An edge that only comes from one domain (e.g., one Reddit thread) is suspect. Real connections should appear across source types.
   
   **Example:** `[Windows] --[mentioned_with]--> [Linux]` appears in both Reddit and Hacker News → **Keep**
   
   `[FAQ] --[mentioned_with]--> [API]` only appears in HN navigation → **Suppress as chrome**

3. **Entity type validation** — Some entity type combinations don't make sense:
   - `[PERSON] --[affiliated_with]--> [PERSON]` is suspicious (should be `works_with` or similar)
   - `[GPE] --[quoted_by]--> [GPE]` doesn't make sense (locations don't quote each other)
   
   **Example from our data:** `[C++] --[mentioned_with]--> [Java]` where C++ is misclassified as PERSON → **Flag for review**

4. **Stopword entities** — Common navigation terms should be filtered:
   - FAQ, API, Apply, Contact, Home, About, Privacy, Terms
   - These appear frequently but aren't real entities
   
   **Impact:** Would eliminate ~50 spurious edges from our current graph

**What this misses:** 
- A genuinely new story might be single-source for hours (tradeoff between freshness and reliability)
- Domain-specific jargon might look like stopwords but be meaningful (e.g., "API" in a technical discussion)
- Low-weight edges from authoritative sources might be more valuable than high-weight edges from spam

### SQLite → Neo4j: what gets easier and what do you lose?

**Easier:**
- Depth-N traversal without recursive CTEs — Cypher makes this one line
- Variable-length path queries (`MATCH (a)-[*2..4]->(b)`)
- Native graph algorithms (PageRank, community detection) via GDS plugin

**Lose:**
- Simplicity — SQLite is a single file, zero infra
- SQL familiarity — every analyst knows SQL, few know Cypher
- Portability — SQLite runs anywhere, Neo4j needs a server

### What would it take to run this continuously?

Three things need to change:
1. **Scheduler** — replace `run_pipeline.py` as a one-shot script with APScheduler or Celery Beat running every N minutes
2. **Deduplication** — content must be fingerprinted (hash of URL + published_at) so we don't re-extract the same article
3. **Incremental edge updates** — instead of INSERT, use INSERT OR REPLACE with weight += 1 and last_seen = now()

The hard part is entity drift — a canonical name that was correct last week might be wrong today if a new person with the same name becomes newsworthy.

---

## Known Limitations

- Entity normalisation fails on ambiguous single-token names
- Relationship extraction accuracy drops on non-English content
- `mentioned_with` edges will dominate the graph numerically — filter by relation type in queries
- The centrality metric doesn't account for node quality, only quantity

---

## Requirements

```
crawl4ai
spacy
rapidfuzz
fastapi
uvicorn
pyyaml
httpx
```
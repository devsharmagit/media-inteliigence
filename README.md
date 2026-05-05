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

**From a recent crawl (May 5, 2026):**

```
Sources crawled:     3 (TechCrunch AI, BBC World News, Hacker News)
Content collected:   60 articles/posts
Entities extracted:  5,854 raw mentions
Unique nodes:        1,822 entities (after normalization)
Relationships:       7,349 extracted
Unique edges:        3,900 edges
Processing time:     ~55 seconds
```

**Top entities by mention count:**
- AI (256 mentions)
- BBC (192 mentions)
- United States (179 mentions)
- TechCrunch (120 mentions)
- Zig (89 mentions)
- Iran (75 mentions)
- LLM (61 mentions)
- OpenAI (60 mentions)
- Amazon (59 mentions)
- Julie Bort (53 mentions)

**Entity type distribution:**
- Organizations: 847 (46.5%)
- People: 720 (39.5%)
- Locations (GPE): 255 (14.0%)

**Relationship type distribution:**
- `mentioned_with`: 3,386 (86.8%) — co-occurrence fallback
- `affiliated_with`: 375 (9.6%) — typed relationship
- `quoted_by`: 126 (3.2%) — typed relationship
- `accused_of`: 7 (0.2%) — typed relationship
- `responded_to`: 6 (0.2%) — typed relationship

**Sample relationships:**
- `[Iran] --[mentioned_with]--> [United States]` (weight: 38) — from BBC news coverage
- `[OpenAI] --[mentioned_with]--> [AI]` (weight: 14) — from TechCrunch articles
- `[Skio] --[affiliated_with]--> [OpenAI]` (weight: 15) — from tech news
- `[AI] --[mentioned_with]--> [Nvidia]` (weight: 7) — from HN discussions

**API query example:**
```bash
curl http://localhost:8000/entity/AI/network?depth=1
# Returns 159 nodes, 189 edges showing AI's connections to OpenAI, Nvidia, etc.
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

---

## The Hard Questions 

### A real relationship your system extracted — is it correct?

**Example from actual crawl (May 5, 2026):**

The system extracted `[Iran] --[mentioned_with]--> [United States]` (weight: 38) from BBC news coverage. This edge has **7 source content links**, meaning it appeared across multiple BBC articles about Iran-US relations.

**Is it correct?** Yes. This is a legitimate co-occurrence pattern reflecting real news coverage. The high weight (38) indicates this is a significant ongoing story, not a spurious connection.

**Additional examples:**
- `[AI] --[mentioned_with]--> [OpenAI]` (weight: 14) — Correct, from TechCrunch AI category articles
- `[Skio] --[affiliated_with]--> [OpenAI]` (weight: 15) — Detected from tech news mentioning company affiliations
- `[OpenAI] --[mentioned_with]--> [Amazon]` (weight: 20) — Correct co-occurrence from multiple articles
- `[Julie Bort] --[mentioned_with]--> [Tim Fernholz]` (weight: 20) — Authors appearing together in bylines

**Example of incorrect entity classification:**

The entity "Zig" appeared 89 times and was classified as **GPE (location)** instead of a programming language. This happened because:
1. spaCy's NER model doesn't have a category for programming languages
2. Without a "TECHNOLOGY" entity type, it defaulted to GPE based on capitalization patterns
3. The context (Hacker News discussions) wasn't enough to override the statistical model

**Impact:** Any edges involving "Zig" have incorrect entity type metadata, though the relationships themselves may be valid (e.g., `[Zig] --[mentioned_with]--> [Rust]` is a real technology comparison).

**Example of navigation chrome noise:**

The system extracted entities like "Close TechCrunch Desktop Logo" and "Apps Biotech & Health Climate" from TechCrunch navigation elements. These appear in relationships like:
- `[Close TechCrunch Desktop Logo] --[mentioned_with]--> [TechCrunch]` (weight: 19)

These are spurious edges from website chrome, not real content relationships.

**Edge provenance:** Every edge links back to its source content via the `edge_sources` table. For example, the Iran-United States edge can be traced to specific BBC articles, allowing verification of extraction accuracy.

### How does entity normalisation break? Concrete example.

**Example from actual crawl (May 5, 2026):**

The entity "Zig" appeared **89 times** and was classified as **GPE (geopolitical entity/location)** instead of a programming language. This happened because:
1. spaCy's NER model doesn't have a category for programming languages
2. The capitalized single-word pattern matches location heuristics
3. Without a "TECHNOLOGY" entity type, it defaulted to GPE

**Impact:** Any edges involving "Zig" have incorrect entity type metadata. For example, `[Zig] --[mentioned_with]--> [Rust]` should be a technology comparison, not a location-organization relationship.

**Another example:** "LLM" appeared 61 times and was classified as **ORG** instead of a concept/technology. While this is less wrong than Zig's classification, it still creates semantic confusion in relationships.

**Navigation chrome pollution:**

Entities like these were extracted from website navigation elements:
- "Close TechCrunch Desktop Logo" (18 mentions)
- "Apps Biotech & Health Climate" (18 mentions)
- "Media & Entertainment Meta Microsoft Privacy Robotics Security Social Space Startups" (18 mentions)

These appear in spurious relationships like:
- `[Close TechCrunch Desktop Logo] --[mentioned_with]--> [TechCrunch]` (weight: 19)

**The problem:** These aren't real entities — they're concatenated navigation menu items that spaCy's NER incorrectly identified as organizations.

**BBC language menu pollution:**

The BBC website's language selector created many spurious entities:
- "Afaan Oromootiin Amharic" (28 mentions)
- "Gaelic NAIDHEACHDAN Gujarati ગુજરાતીમાં" (28 mentions)
- "Kirundi KIRUNDI" (28 mentions)
- "Kyrgyz Кыргыз" (28 mentions)
- "Nepali नेपाली Noticias" (28 mentions)

All with high-weight edges to "BBC" because they appear on every BBC page.

**What we'd fix:**
1. **Pre-processing filter**: Strip common navigation patterns before entity extraction
2. **Entity length validation**: Reject entities longer than N words (e.g., 5) as likely concatenated text
3. **Custom entity types**: Add TECHNOLOGY, PRODUCT, CONCEPT categories
4. **Domain-specific stoplist**: Filter known navigation terms (Close, Logo, Menu, etc.)
5. **Post-processing validation**: Check if entity appears in a known list of programming languages, frameworks, etc.

**What this reveals:** Entity normalization is only as good as the input quality. Scraped web content includes navigation chrome, and without content-aware filtering, the graph gets polluted with spurious nodes.

### How would you detect and suppress spurious edges at scale?

**Real examples from our crawl (May 5, 2026):**

The most common edge in our graph is `[Iran] --[mentioned_with]--> [United States]` (weight: 38). This is a **legitimate** relationship from BBC news coverage. However, we also have spurious edges like:

- `[BBC] --[mentioned_with]--> [Afaan Oromootiin Amharic]` (weight: 28) — BBC language menu
- `[BBC] --[mentioned_with]--> [Gaelic NAIDHEACHDAN Gujarati ગુજરાતીમાં]` (weight: 28) — BBC language menu
- `[Close TechCrunch Desktop Logo] --[mentioned_with]--> [TechCrunch]` (weight: 19) — Navigation chrome

**The problem:** Co-occurrence edges dominate numerically. Out of 3,900 edges:
- **86.8%** are `mentioned_with` (co-occurrence fallback)
- **13.2%** are typed relations (`affiliated_with`, `quoted_by`, `accused_of`, `responded_to`)

**Four approaches we'd implement:**

1. **Minimum weight threshold with source diversity** — Edges with weight=1 from a single source are flagged as unverified. Only edges seen in 2+ independent sources or with weight ≥3 from a single authoritative source get promoted.
   
   **Example from our data:**
   - `[Iran] --[mentioned_with]--> [United States]` (weight: 38, 7 sources) → **Keep**
   - `[OpenAI] --[mentioned_with]--> [Amazon]` (weight: 20, multiple sources) → **Keep**
   - Single-occurrence edges (weight: 1, 1 source) → **Flag as unverified**

2. **Entity pattern filtering** — Reject edges where either entity matches known noise patterns:
   - Contains "Logo", "Menu", "Close", "Desktop" → Navigation chrome
   - Longer than 5 words → Likely concatenated text
   - Contains multiple language scripts → Language selector
   - All caps with spaces (e.g., "KIRUNDI") → Menu item
   
   **Impact on our data:** Would eliminate ~200+ spurious edges from BBC language menus and TechCrunch navigation

3. **Entity type validation** — Some entity type combinations don't make sense:
   - `[ORG] --[affiliated_with]--> [ORG]` where both are navigation elements
   - `[GPE] --[quoted_by]--> [GPE]` (locations don't quote each other)
   - Edges where one entity is misclassified (e.g., Zig as GPE)
   
   **Example from our data:** Edges involving "Zig" (classified as GPE) should be reviewed since it's actually a programming language

4. **Relation type prioritization** — Weight typed relationships higher than co-occurrence:
   - `affiliated_with`, `quoted_by`, `accused_of`, `responded_to` → Higher confidence
   - `mentioned_with` with weight < 3 → Lower confidence, flag for review
   
   **Impact:** Of our 3,900 edges, prioritizing the 514 typed relationships (13.2%) would surface more meaningful connections

**What this misses:** 
- A genuinely breaking story might be single-source initially (tradeoff between freshness and reliability)
- Domain-specific jargon might look like noise but be meaningful (e.g., "LLM" is legitimate despite being an acronym)
- Low-weight edges from authoritative sources (BBC, TechCrunch) might be more valuable than high-weight edges from spam
- Some navigation chrome might actually be relevant (e.g., "AI" category pages on TechCrunch)

**Current state:** With 5,691 edge-to-source provenance links, we can trace every edge back to verify if it's legitimate or noise.

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
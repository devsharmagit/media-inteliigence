from __future__ import annotations

import logging
import re
from typing import Any

import spacy

logger = logging.getLogger(__name__)

# Load spaCy model (reuse from entities.py if already loaded)
try:
    _nlp = spacy.load("en_core_web_sm")
except OSError:
    logger.error(
        "spaCy model 'en_core_web_sm' not found. "
        "Run: python -m spacy download en_core_web_sm"
    )
    raise


# Verb patterns for each relation type
_RELATION_PATTERNS = {
    "quoted_by": [
        r"\b(said|stated|claimed|announced|declared|reported|told|mentioned)\b",
    ],
    "accused_of": [
        r"\b(accused|charged|sued|prosecuted|indicted|alleged|blamed)\b",
    ],
    "affiliated_with": [
        r"\b(CEO|founder|president|director|member|employee|works for|part of|owns)\b",
    ],
    "responded_to": [
        r"\b(responded|replied|answered|reacted|commented)\b",
    ],
}


def extract_relations(content: dict, entities: list[dict]) -> list[dict]:
    """
    Extract typed relationships between entities in content.
    
    Args:
        content: dict with keys: title, body
        entities: list of entity dicts from extract_entities()
                  [{"name": str, "type": str}, ...]
    
    Returns:
        List of relation dicts:
        [
            {
                "source": str,        # entity name
                "target": str,        # entity name
                "relation": str,      # relation type
            },
            ...
        ]
    """
    text = ""
    if content.get("title"):
        text += content["title"] + "\n"
    if content.get("body"):
        text += content["body"]
    
    if not text.strip() or len(entities) < 2:
        return []
    
    doc = _nlp(text)
    relations: list[dict] = []
    
    # Build entity span map for quick lookup
    entity_spans = {}
    for ent in doc.ents:
        entity_spans[ent.start] = ent
    
    # Extract entity names for matching
    entity_names = {e["name"] for e in entities}
    
    # Process each sentence
    for sent in doc.sents:
        # Find entities in this sentence
        sent_entities = []
        for ent in sent.ents:
            if ent.text.strip() in entity_names:
                sent_entities.append(ent.text.strip())
        
        # Need at least 2 entities to form a relation
        if len(sent_entities) < 2:
            continue
        
        # Check all entity pairs in this sentence
        for i, source in enumerate(sent_entities):
            for target in sent_entities[i+1:]:
                if source == target:
                    continue
                
                # Try to find a typed relation
                relation_type = _find_relation_type(sent.text, source, target)
                
                relations.append({
                    "source": source,
                    "target": target,
                    "relation": relation_type,
                })
    
    logger.debug("Extracted %d relations from content", len(relations))
    return relations


def _find_relation_type(sentence: str, source: str, target: str) -> str:
    """
    Determine the relation type between two entities in a sentence.
    
    Checks for verb patterns in the text between the entities.
    Falls back to "mentioned_with" if no typed pattern matches.
    
    Args:
        sentence: The sentence text
        source: Source entity name
        target: Target entity name
    
    Returns:
        Relation type string
    """
    # Find positions of entities in sentence
    source_pos = sentence.lower().find(source.lower())
    target_pos = sentence.lower().find(target.lower())
    
    if source_pos == -1 or target_pos == -1:
        return "mentioned_with"
    
    # Get text between entities
    start = min(source_pos, target_pos)
    end = max(source_pos, target_pos)
    between_text = sentence[start:end].lower()
    
    # Check each relation type's patterns
    for relation_type, patterns in _RELATION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, between_text, re.IGNORECASE):
                return relation_type
    
    # Fallback: co-occurrence
    return "mentioned_with"


def extract_relations_from_thread(content: dict, entities: list[dict]) -> list[dict]:
    """
    Extract responded_to relations from threaded content (Reddit, HN).
    
    This is a specialized extractor for social/forum content where
    reply structure is explicit.
    
    Args:
        content: dict with keys: source_type, author, body
        entities: list of entity dicts
    
    Returns:
        List of relation dicts with relation="responded_to"
    """
    relations: list[dict] = []
    
    # Only applicable to social/forum content
    if content.get("source_type") not in ["social", "forum"]:
        return relations
    
    # For now, this is a stub — full implementation would parse
    # Reddit JSON comment trees or HN reply chains
    # We'll rely on the main extract_relations() for now
    
    return relations


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    
    test_content = {
        "title": "SEC Accuses Elon Musk of Securities Fraud",
        "body": (
            "The Securities and Exchange Commission announced today that it has accused "
            "Tesla CEO Elon Musk of securities fraud. The SEC stated that Musk made "
            "misleading statements on social media. Tesla responded to the allegations, "
            "with a spokesperson saying the company stands by its CEO."
        ),
    }
    
    test_entities = [
        {"name": "Securities and Exchange Commission", "type": "ORG"},
        {"name": "Elon Musk", "type": "PERSON"},
        {"name": "Tesla", "type": "ORG"},
    ]
    
    print("=== Relationship Extraction Test ===\n")
    print(f"Content: {test_content['title']}\n")
    print(f"Entities: {[e['name'] for e in test_entities]}\n")
    
    relations = extract_relations(test_content, test_entities)
    
    print(f"Extracted {len(relations)} relations:\n")
    for rel in relations:
        print(f"  [{rel['source']}] --[{rel['relation']}]--> [{rel['target']}]")

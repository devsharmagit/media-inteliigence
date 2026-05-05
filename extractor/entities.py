from __future__ import annotations

import logging
import re
from typing import Any

import spacy
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# Load spaCy model once at module import
try:
    _nlp = spacy.load("en_core_web_sm")
    logger.info("Loaded spaCy model: en_core_web_sm")
except OSError:
    logger.error(
        "spaCy model 'en_core_web_sm' not found. "
        "Run: python -m spacy download en_core_web_sm"
    )
    raise


# Entity types we care about
_VALID_ENTITY_TYPES = {"PERSON", "ORG", "GPE"}

# Fuzzy match threshold (0-100)
_FUZZY_THRESHOLD = 90


def extract_entities(content: dict) -> list[dict]:
    """
    Extract named entities from a content item.
    
    Args:
        content: dict with keys: title, body
    
    Returns:
        List of entity dicts: [{"name": str, "type": str}, ...]
        Names are NOT yet normalised — call normalise_entity() separately.
    """
    text = ""
    if content.get("title"):
        text += content["title"] + "\n"
    if content.get("body"):
        text += content["body"]
    
    if not text.strip():
        return []
    
    doc = _nlp(text)
    entities: list[dict] = []
    
    for ent in doc.ents:
        if ent.label_ in _VALID_ENTITY_TYPES:
            entities.append({
                "name": ent.text.strip(),
                "type": ent.label_,
            })
    
    logger.debug("Extracted %d entities from content", len(entities))
    return entities


def normalise_entity(name: str, entity_type: str, known_entities: list[str] | None = None) -> str:
    """
    Normalise an entity name to its canonical form.
    
    Steps:
      1. Strip whitespace and collapse multiple spaces
      2. Check alias map (imported from extractor.aliases)
      3. Fuzzy match against known_entities (if provided)
      4. Strip common title prefixes for PERSON entities
    
    Args:
        name: Raw entity name from NER
        entity_type: PERSON | ORG | GPE
        known_entities: Optional list of canonical names to fuzzy-match against
    
    Returns:
        Canonical entity name
    """
    from extractor.aliases import resolve_alias  # Import here to avoid circular dependency
    
    # Step 1: Basic cleanup
    name = re.sub(r"\s+", " ", name.strip())
    
    if not name:
        return name
    
    # Step 2: Check alias map
    canonical = resolve_alias(name)
    if canonical != name:
        logger.debug("Alias resolved: '%s' -> '%s'", name, canonical)
        return canonical
    
    # Step 3: Fuzzy match against known entities
    if known_entities:
        best_match = None
        best_score = 0
        
        for known in known_entities:
            score = fuzz.ratio(name.lower(), known.lower())
            if score > best_score:
                best_score = score
                best_match = known
        
        if best_score >= _FUZZY_THRESHOLD and best_match:
            logger.debug("Fuzzy matched: '%s' -> '%s' (score=%d)", name, best_match, best_score)
            return best_match
    
    # Step 4: Strip title prefixes for PERSON entities
    if entity_type == "PERSON":
        name = _strip_title_prefix(name)
    
    return name


def _strip_title_prefix(name: str) -> str:
    """
    Remove common title prefixes from person names.
    
    Examples:
      "President Biden" -> "Joe Biden" (if alias map has it)
      "Dr. Smith" -> "Smith"
      "Mr. John Doe" -> "John Doe"
    """
    prefixes = [
        r"^President\s+",
        r"^Prime Minister\s+",
        r"^CEO\s+",
        r"^Dr\.?\s+",
        r"^Mr\.?\s+",
        r"^Mrs\.?\s+",
        r"^Ms\.?\s+",
        r"^Prof\.?\s+",
    ]
    
    for prefix in prefixes:
        name = re.sub(prefix, "", name, flags=re.IGNORECASE)
    
    return name.strip()


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    
    test_content = {
        "title": "Elon Musk and Tesla Face SEC Investigation",
        "body": "The Securities and Exchange Commission announced today that it is investigating Tesla Inc. and its CEO Elon Musk over potential securities violations. The probe focuses on statements made by Musk on social media.",
    }
    
    print("=== Entity Extraction Test ===\n")
    entities = extract_entities(test_content)
    
    print(f"Extracted {len(entities)} entities:\n")
    for ent in entities:
        print(f"  {ent['name']:30s} [{ent['type']}]")
    
    print("\n=== Entity Normalisation Test ===\n")
    known = ["Elon Musk", "Tesla", "SEC"]
    
    test_names = [
        ("Elon  Musk", "PERSON"),      # Double space
        ("Musk", "PERSON"),            # Alias (if defined)
        ("President Biden", "PERSON"),
        ("Dr. Smith", "PERSON"),
    ]
    
    for raw_name, ent_type in test_names:
        canonical = normalise_entity(raw_name, ent_type, known)
        print(f"  '{raw_name}' -> '{canonical}'")

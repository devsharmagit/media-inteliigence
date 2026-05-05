from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Alias dictionary: variant -> canonical name
_ALIAS_MAP = {
    # People
    "Musk": "Elon Musk",
    "@elonmusk": "Elon Musk",
    "Biden": "Joe Biden",
    "President Biden": "Joe Biden",
    "Trump": "Donald Trump",
    "President Trump": "Donald Trump",
    "Zuckerberg": "Mark Zuckerberg",
    "Bezos": "Jeff Bezos",
    "Gates": "Bill Gates",
    
    # Organizations
    "SEC": "Securities and Exchange Commission",
    "FTC": "Federal Trade Commission",
    "FBI": "Federal Bureau of Investigation",
    "CIA": "Central Intelligence Agency",
    "NASA": "National Aeronautics and Space Administration",
    "WHO": "World Health Organization",
    "UN": "United Nations",
    
    # Companies
    "TSLA": "Tesla",
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "GOOGL": "Google",
    "META": "Meta",
    "FB": "Meta",
    "Facebook": "Meta",
    
    # Locations
    "US": "United States",
    "USA": "United States",
    "U.S.": "United States",
    "UK": "United Kingdom",
    "U.K.": "United Kingdom",
    "NYC": "New York City",
    "LA": "Los Angeles",
}


def resolve_alias(name: str) -> str:
    """
    Resolve an entity name through the alias map.
    
    Performs case-insensitive lookup. If no alias is found,
    returns the original name unchanged.
    
    Args:
        name: Raw entity name
    
    Returns:
        Canonical name (or original if no alias exists)
    """
    if not name:
        return name
    
    # Case-insensitive lookup
    for variant, canonical in _ALIAS_MAP.items():
        if name.lower() == variant.lower():
            return canonical
    
    return name


def add_alias(variant: str, canonical: str) -> None:
    """
    Add a new alias to the map at runtime.
    
    Useful for dynamically discovered aliases during pipeline runs.
    
    Args:
        variant: The variant name
        canonical: The canonical name it should map to
    """
    _ALIAS_MAP[variant] = canonical
    logger.info("Added alias: '%s' -> '%s'", variant, canonical)


def get_all_aliases() -> dict[str, str]:
    """Return a copy of the entire alias map."""
    return _ALIAS_MAP.copy()


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    
    print("=== Alias Resolution Test ===\n")
    
    test_names = [
        "Musk",
        "musk",           # Case-insensitive
        "@elonmusk",
        "SEC",
        "Biden",
        "Unknown Person",  # No alias
        "TSLA",
        "Facebook",
    ]
    
    for name in test_names:
        canonical = resolve_alias(name)
        if canonical != name:
            print(f"  '{name}' -> '{canonical}'")
        else:
            print(f"  '{name}' (no alias)")
    
    print(f"\nTotal aliases defined: {len(_ALIAS_MAP)}")

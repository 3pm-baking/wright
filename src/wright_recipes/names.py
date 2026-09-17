"""Ingredient name normalization for shopping-list consolidation.

Different recipe sites name the same ingredient differently ("Kosher
salt", "table salt", "sea salt"), so a consolidated list can show three
salt lines.  This module provides a conservative alias map and a
``key_fn`` for :func:`wright.generate_shopping_list` that merges those
variants under one canonical name.

The map is intentionally small and curated: only merge when the
variants are genuinely the same shopping item.  Brown sugar and sugar
stay separate; "coarse sea salt" and "Kosher salt" do not.
"""

from __future__ import annotations

from pathlib import Path

# Substring -> canonical name.  Longest keys are matched first, so
# "granulated sugar" wins over a hypothetical bare "sugar" rule.
NAME_ALIASES: dict[str, str] = {
    "kosher salt": "Salt",
    "table salt": "Salt",
    "sea salt": "Salt",
    "fine salt": "Salt",
    "granulated sugar": "Sugar",
    "caster sugar": "Sugar",
    "all-purpose flour": "All-Purpose Flour",
    "all purpose flour": "All-Purpose Flour",
    "ap flour": "All-Purpose Flour",
    "scallion": "Green Onion",
    "green onion": "Green Onion",
    "spring onion": "Green Onion",
    "bell pepper": "Bell Pepper",
    "sweet potato": "Sweet Potato",
    "chicken stock": "Chicken Stock",
    "chicken broth": "Chicken Stock",
    "vegetable stock": "Vegetable Stock",
    "vegetable broth": "Vegetable Stock",
    "olive oil": "Olive Oil",
    "extra-virgin olive oil": "Olive Oil",
    "extra virgin olive oil": "Olive Oil",
    "evoo": "Olive Oil",
    "vanilla extract": "Vanilla Extract",
    "vanilla essence": "Vanilla Extract",
}


def normalize_ingredient_name(name: str, aliases: dict[str, str] | None = None) -> str:
    """Map common ingredient-name variants to a canonical name.

    Substring match, longest alias first, so brand prefixes
    ("King Arthur Unbleached All-Purpose Flour") normalize too.
    Unmatched names pass through unchanged.

    *aliases* extends (and overrides) the built-in :data:`NAME_ALIASES`
    — bring your own mapping for ingredients wright does not know.
    """
    table = dict(NAME_ALIASES)
    if aliases:
        table.update(aliases)
    lowered = name.lower()
    for alias in sorted(table, key=len, reverse=True):
        if alias in lowered:
            return table[alias]
    return name


def variant_key(material, aliases: dict[str, str] | None = None) -> tuple:
    """``key_fn`` for generate_shopping_list: group by normalized name.

    Pass ``aliases`` (variant -> canonical) to extend or override the
    built-in map.
    """
    return (
        normalize_ingredient_name(material.name, aliases),
        tuple(sorted(material.require_tags)),
    )


def load_aliases(path: str | Path) -> dict[str, str]:
    """Load a custom alias mapping from a YAML or JSON file.

    Format: a flat mapping of variant name -> canonical name.

        # my-aliases.yaml
        "kosher salt": Salt
        "haricot verts": Green Beans
    """
    import json

    import yaml

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Alias file not found: {p}")
    text = p.read_text()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = yaml.safe_load(text)
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise ValueError(
            f"{p}: alias mapping must be a flat object of string -> string"
        )
    return data

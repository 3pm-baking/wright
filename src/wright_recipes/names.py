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


def normalize_ingredient_name(name: str) -> str:
    """Map common ingredient-name variants to a canonical name.

    Substring match, longest alias first, so brand prefixes
    ("King Arthur Unbleached All-Purpose Flour") normalize too.
    Unmatched names pass through unchanged.
    """
    lowered = name.lower()
    for alias in sorted(NAME_ALIASES, key=len, reverse=True):
        if alias in lowered:
            return NAME_ALIASES[alias]
    return name


def variant_key(material) -> tuple:
    """``key_fn`` for generate_shopping_list: group by normalized name."""
    return (
        normalize_ingredient_name(material.name),
        tuple(sorted(material.require_tags)),
    )

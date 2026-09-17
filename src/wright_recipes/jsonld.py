"""Extract schema.org Recipe structured data (JSON-LD) from page HTML.

Many recipe sites embed a JSON-LD ``Recipe`` object with clean
ingredient lines.  When present, it is authoritative input for
extraction — far more reliable than stripped page text.
"""

from __future__ import annotations

import json
import re


def extract_jsonld_recipe(html: str) -> dict | None:
    """Return the first schema.org Recipe object found in JSON-LD, or None.

    Handles ``@graph`` wrappers and lists of objects.
    """
    recipes: list[dict] = []
    for match in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.S | re.I,
    ):
        try:
            data = json.loads(match.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            continue
        _collect_recipes(data, recipes)
        if recipes:
            return recipes[0]
    return None


def _collect_recipes(node: object, out: list[dict]) -> None:
    """Recursively gather dicts whose @type includes Recipe."""
    if isinstance(node, list):
        for item in node:
            _collect_recipes(item, out)
    elif isinstance(node, dict):
        types = node.get("@type", [])
        types = types if isinstance(types, list) else [types]
        if any(t.lower() == "recipe" for t in types if isinstance(t, str)):
            out.append(node)
        graph = node.get("@graph")
        if graph:
            _collect_recipes(graph, out)


def structured_block(recipe: dict) -> str:
    """Render a JSON-LD recipe as compact text for the extraction prompt."""
    keep = {}
    for key in (
        "name",
        "recipeYield",
        "recipeIngredient",
        "recipeInstructions",
        "prepTime",
        "cookTime",
        "totalTime",
        "recipeCategory",
        "recipeCuisine",
    ):
        value = recipe.get(key)
        if value:
            keep[key] = value
    return json.dumps(keep, indent=2, ensure_ascii=False)

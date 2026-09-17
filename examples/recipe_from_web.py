"""From recipe web page to shopping list — agent-powered example.

Demonstrates the "agent as data source" pattern: an LLM extracts a
structured ``Recipe`` from a recipe web page, wright validates it and
generates the shopping list.  The LLM is injectable — wright itself
stays a pure library with no LLM dependency.

Usage:
    python examples/recipe_from_web.py [url]

With ``OPENAI_API_KEY`` set, the script fetches the URL and extracts
the recipe live.  Without a key, it falls back to a checked-in
fixture (``recipes/from-web-fixture.json``) so the demo always runs.
"""

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from wright import (
    DEFAULT_CATEGORY_RULES,
    ProductionItem,
    ProductionRun,
    Purchase,
    Recipe,
    generate_shopping_list,
    group_shopping_items,
)

FIXTURE_PATH = Path(__file__).parent / "recipes" / "from-web-fixture.json"
EXTRACTION_MODEL = "gpt-4o-mini"

EXTRACTION_PROMPT = """\
Extract the recipe from the following web page into structured JSON.

Rules:
- Use web-style units as written (cup, tbsp, tsp, each, g, ml).
- One component per logical section of the recipe (batter, topping, ...).
  If the recipe has no sections, use a single component named "Main".
- Omit optional garnishes and serving suggestions.
- Quantities must be numbers, never strings.

Shape (components is a LIST of objects, each with name + ingredients):
{{
  "name": "...",
  "components": [
    {{"name": "Main", "ingredients": [
      {{"name": "Flour", "quantity": 2, "unit": "cup"}}
    ]}}
  ],
  "prep_time": 15,
  "cook_time": 60,
  "servings": 8,
  "instructions": ["..."]
}}

Web page:
{page}
"""


def recipe_from_fixture(path: Path = FIXTURE_PATH) -> Recipe:
    """Load the checked-in fixture — the offline fallback data source."""
    return Recipe.model_validate(json.loads(path.read_text()))


def page_to_text(html: str, max_chars: int = 20_000) -> str:
    """Reduce raw HTML to readable text a small-context LLM can handle."""
    import re

    html = re.sub(
        r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I
    )
    html = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", html)
    return text[:max_chars]


def extract_recipe_from_url(url: str) -> Recipe:
    """Fetch a recipe page and extract a validated Recipe via OpenAI.

    The LLM returns JSON constrained by wright's own ``Recipe`` schema
    (structured outputs).  On validation failure, the error is fed back
    to the model for one retry — the agent-in-the-loop pattern.
    """
    import urllib.request

    import openai  # lazy: wright never requires this

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/128.0"
        },
    )
    with urllib.request.urlopen(request) as response:  # noqa: S310 - demo
        page = page_to_text(response.read().decode("utf-8", errors="replace"))

    client = openai.OpenAI()  # reads OPENAI_API_KEY from the environment

    def ask(extra: str = "") -> str:
        completion = client.chat.completions.create(
            model=EXTRACTION_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": EXTRACTION_PROMPT.format(page=page) + extra,
                }
            ],
        )
        return completion.choices[0].message.content or ""

    raw = ask()
    try:
        return Recipe.model_validate_json(raw)
    except ValidationError as exc:
        # One retry: show the model exactly what it got wrong.
        raw = ask(f"\n\nYour previous JSON failed validation:\n{exc}\nFix it.")
        return Recipe.model_validate_json(raw)


# ── Grocery prices (would come from your purchase history) ────────────

purchases = [
    Purchase(name="All-Purpose Flour", quantity=5000, unit="g", price=Decimal("4.49")),
    Purchase(name="Baking Soda", quantity=454, unit="g", price=Decimal("1.29")),
    Purchase(name="Salt", quantity=737, unit="g", price=Decimal("1.19")),
    Purchase(name="Butter", quantity=454, unit="g", price=Decimal("5.49")),
    Purchase(name="Brown Sugar", quantity=2000, unit="g", price=Decimal("2.79")),
    Purchase(name="Egg", quantity=12, unit="each", price=Decimal("4.99")),
    Purchase(name="Ripe Banana", quantity=1, unit="each", price=Decimal("0.35")),
    Purchase(name="Vanilla Extract", quantity=59, unit="ml", price=Decimal("7.99")),
    Purchase(name="Walnuts", quantity=454, unit="g", price=Decimal("9.99")),
]

density_data = {
    "volume_weights": {
        "All-Purpose Flour": {"cup": 120.0, "tbsp": 7.5, "tsp": 2.5},
        "Baking Soda": {"tsp": 4.8, "tbsp": 14.4},
        "Salt": {"tsp": 6.0, "tbsp": 18.0},
        "Butter": {"cup": 227.0, "tbsp": 14.2, "tsp": 4.7},
        "Brown Sugar": {"cup": 220.0, "tbsp": 13.8, "tsp": 4.6},
        "Vanilla Extract": {"tsp": 4.2, "tbsp": 12.6},
        "Walnuts": {"cup": 113.0, "tbsp": 7.1, "tsp": 2.4},
    },
}

# ── Get the recipe: live extraction or fixture ────────────────────────

url = sys.argv[1] if len(sys.argv) > 1 else None

if url:
    try:
        recipe = extract_recipe_from_url(url)
        source = f"extracted from {url}"
    except Exception as exc:  # noqa: BLE001 - demo: fall back gracefully
        print(f"Live extraction failed ({exc}); using fixture.\n")
        recipe = recipe_from_fixture()
        source = "fixture (extraction failed)"
else:
    recipe = recipe_from_fixture()
    source = "fixture (no URL given — pass one to extract live)"

print(f"Recipe: {recipe.name}  [{source}]")

# ── Plan a production run and generate the shopping list ──────────────

session = ProductionRun(
    date=date(2026, 9, 17),
    production=[ProductionItem(assembly=recipe.name, quantity=1)],
    target_dates=[date(2026, 9, 17)],
)

shopping = generate_shopping_list(session, [recipe])
grouped = group_shopping_items(
    shopping.all_items,
    category_rules=DEFAULT_CATEGORY_RULES,
)

# ── Display ───────────────────────────────────────────────────────────

width = 62
divider = "-" * width

print()
print("Shopping List".center(width))
print(divider)
print(f"  Making: {', '.join(shopping.production_summary)}")
print()

for group in grouped:
    header = f"  {group.group_name}  "
    print(f" {header:-<{width}}")
    for item in group.items:
        qty = f"{item.quantity:g} {item.unit}"
        print(f"  {item.name:<24s} {qty:>12s}")
    print()

print(divider)
print("  Units are normalized for accumulation (volume -> ml).")
print("  Wire in your purchase history for costs, like grocery_list.py.")
print()

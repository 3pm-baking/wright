---
name: wright-recipes
description: Work with recipes and food using the wright-core library and CLI. Parse recipe web pages into validated structured recipes, scale servings, build consolidated shopping lists, cost recipes against purchase history, detect allergens and dietary badges, analyze nutrition, and track pantry supply. Use for any task involving recipes, ingredients, grocery lists, or food production planning. Does not search for recipes itself — if the user has not supplied recipe URLs, ask for them or propose candidates and confirm before extracting.
license: MIT
metadata:
  author: 3pm-baking
  version: "0.3.0"
---

# Wright: recipes, shopping lists, and food planning

Wright (`wright-core` on PyPI) is a pure Python library for production
planning, costing, shopping-list aggregation, unit conversion, allergen
detection, and nutrition analysis. It ships a thin CLI (`wright-core`)
for the most common workflow, and the library covers everything else.

The core design idea: **extraction is probabilistic; planning is
deterministic.** An LLM turns a recipe web page into a validated
`Recipe`; everything after that (unit conversion, aggregation,
scaling, grouping) is testable library code. The boundary between the
two is where review happens.

## The CLI sliver (the common 80%)

```bash
# One pipe: recipe URL in, shopping list out
uvx --with openai wright-core parse https://example.com/recipe | uvx wright-core shop

# Two steps, with review in between
uvx --with openai wright-core parse URL > recipe.yaml
uvx wright-core scale recipe.yaml --servings 12 | uvx wright-core shop --units metric

# Per-recipe scaling, then consolidation
uvx --with openai wright-core parse URL_A | uvx wright-core scale --servings 24 > a.json
uvx --with openai wright-core parse URL_B | uvx wright-core scale --batches 2 > b.json
uvx wright-core shop a.json b.json

# Machine-readable output for further chaining
uvx --with openai wright-core parse URL | uvx wright-core shop --format json
```

| Command | Stage | Notes |
|---|---|---|
| `parse <url>` | extraction (LLM) | `--provider openai\|anthropic\|gemini`, `--key`, `--model`, `--context`, `--format json\|yaml` |
| `scale` | per-recipe transform | `--servings N`, `--batches N`; recipe in, scaled recipe out |
| `shop` | planning (deterministic) | files or stdin; `--units us\|metric`, `--format list\|json\|yaml`, `--aliases FILE`. Scaling flags are deprecated — use `scale` before `shop` |

Conventions: machine-readable output (JSON, YAML) on stdout; human
output and diagnostics on stderr; exit codes 0 (success), 1 (failure),
2 (bad flags). `shop` stdin accepts one JSON/YAML recipe, a JSON array,
or concatenated JSON objects (several `parse` runs joined).

Consolidation merges ingredient-name variants ("Kosher salt" and
"table salt" become one `Salt` line) via a built-in alias map. Bring
your own mapping:

```yaml
# my-aliases.yaml — variant -> canonical
"haricot verts": Green Beans
"prawns": Shrimp
```

```bash
wright-core shop a.yaml b.yaml --aliases my-aliases.yaml
```

## No CLI needed — speak the schema

The `parse` command is just one way to produce a Recipe. **The schema
is the contract**: any agent that can emit conforming Recipe JSON gets
the entire deterministic pipeline (scaling, consolidation, unit
normalization) without an LLM call, an SDK, or an API key.

### The Recipe schema

```json
{
  "name": "Classic Banana Bread",
  "components": [
    {
      "name": "Batter",
      "ingredients": [
        {"name": "All-Purpose Flour", "quantity": 2, "unit": "cup"},
        {"name": "Egg", "quantity": 2, "unit": "each"}
      ]
    }
  ],
  "prep_time": 15,
  "cook_time": 60,
  "servings": 8,
  "instructions": ["..."]
}
```

Extraction rules that make it work:

- Quantities are numbers, never strings ("2 1/2" → 2.5).
- Keep units exactly as written (cup, tbsp, tsp, each, g, ml, quart) —
  never convert; the library handles units.
- Clean, generic names: "sugar for boiling" is just "Sugar"; merge
  variety qualifiers ("vinegar" + "white vinegar" → "White vinegar").
- One component per logical section (batter, topping); a single-section
  recipe uses one component named "Main".
- Vague seasonings get assumed units, never null: "a pinch of nutmeg" →
  quantity 1, unit "pinch"; "salt to taste" → 1 tsp.
- Omit optional garnishes and "plus more for serving".
- Omit `prep_time`/`cook_time` (null) when the source does not state them.

Advanced fields (optional): `equivalent_quantity`/`equivalent_unit` for
packet-style items ("1 packet yeast = 7 g"), `require_tags` for variants
(e.g. `["unsalted"]` on butter). See the
[models docs](https://wright.germanbakingasheville.com/guides/core/models/).

### Paths that skip the LLM entirely

- **Page has JSON-LD?** Transform `schema.org/Recipe` fields directly —
  `recipeIngredient` lines → components/ingredients. Deterministic, no
  model call.
- **Already fetched the HTML?** Extract per the rules above and emit the
  JSON yourself.
- **User pasted the recipe as text?** Structure it per the schema.

Then feed it to the deterministic stage:

```bash
wright-core shop recipe.json                      # grouped list
wright-core scale recipe.json --servings 12 | wright-core shop   # scaled
echo '<recipe-json>' | wright-core shop           # via stdin
```

Or in Python:

```python
from wright import Recipe, generate_shopping_list, ProductionRun, ProductionItem

recipe = Recipe.model_validate(data)  # raises with the exact bad field
```

Validation is built in: pipe your JSON through `wright-core shop` (exit
0 = valid) or `Recipe.model_validate` — pydantic errors name the exact
field and what it expected.

## Missing inputs protocol

This skill does not search for recipes. If the user names a dish but
supplies no recipe URL ("I want to make pizza this week"):

1. State what is needed: "I need recipe URLs to extract the
   ingredients."
2. Optionally use your own web-search capability to propose candidate
   recipe URLs from well-known sites.
3. Present the candidates and **extract only after the user picks**.
   Never extract from unconfirmed URLs.

## The library is the rest

The CLI covers extract → scale → shop. The library covers costing,
allergens, nutrition, supply, and custom pipelines — all injectable,
no I/O in the core. Use a PEP 723 script:

```python
# /// script
# dependencies = ["wright-core"]
# ///
from decimal import Decimal
from wright import (
    Recipe,
    RecipeComponent,
    Ingredient,
    ProductionRun,
    ProductionItem,
    generate_shopping_list,
    calculate_shopping_list_cost,
    Purchase,
    detect_dietary_properties,
    margin_price,
)

cake = Recipe(
    name="Cake",
    components=[
        RecipeComponent(
            name="Batter",
            ingredients=[
                Ingredient(name="Flour", quantity=300, unit="g"),
                Ingredient(name="Butter", quantity=150, unit="g"),
            ],
        )
    ],
    prep_time=20,
    cook_time=40,
)

run = ProductionRun(
    date=__import__("datetime").date.today(),
    production=[ProductionItem(assembly="Cake", quantity=2)],
    target_dates=[__import__("datetime").date.today()],
)
shopping = generate_shopping_list(run, [cake])

# Cost it against your own purchase history
purchases = [Purchase(name="Flour", quantity=5000, unit="g", price=Decimal("4.49"))]
costs = calculate_shopping_list_cost(shopping, purchases)

# Allergens and pricing
print(detect_dietary_properties(cake))  # ["Gluten", "Dairy", "Eggs"]
print(margin_price(Decimal("2.00"), 0.67))  # price at 67% margin
```

Capability map (all importable from `wright`):

| Capability | Entry points |
|---|---|
| Models & validation | `Recipe`, `RecipeComponent`, `Ingredient`, `Assembly`, `Material` (pydantic) |
| Shopping lists | `generate_shopping_list`, `group_shopping_items`, `calculate_shopping_list_cost` |
| Costing & pricing | `calculate_recipe_cost`, `margin_price`, `Purchase` |
| Allergens & diet | `detect_dietary_properties` |
| Nutrition | `calculate_recipe_macros` |
| Supply / pantry | `Stock`, `SupplyItem` |
| Custom matching | `key_fn`, `item_factory`, pickers (all injectable) |
| Non-food domains | `Assembly` + `Material` directly (BOMs, brewing, construction) |

Run scripts with `uv run script.py` — uv resolves the dependency
inline. For exploration, `uv run --with wright-core python` starts a
REPL with wright available.

## Failure playbook

| Symptom | Cause | Fix |
|---|---|---|
| "content filter interrupted extraction" | Provider safety filter tripped by the page | Retry once; try `--provider anthropic` |
| HTTP 404 on parse | Guessed or dead URL | Verify the URL in a browser first |
| "The 'openai' package is not installed" | SDK missing | Run with `uvx --with openai` (or `--with anthropic`) |
| "No API key found" | No key in env or `--key` | Set `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` |
| Same ingredient on multiple lines | Sites name it differently | `--aliases FILE` with variant → canonical mappings |
| Fractional discrete quantities ("Egg 0.57 each", "0.5 can") | Scaling below the recipe's native yield | Exact scaled math, not a rounding error. Interpret in context: some items split fine (half a can), others do not (a fraction of an egg means "at least one"). Prefer `scale --batches` (whole-recipe multiples) when a recipe does not halve cleanly |
| Model output fails validation | Prose page, complex quantities | Built-in retry usually handles it; check JSON-LD pages for best results |

Pages with schema.org JSON-LD (`Recipe` structured data) extract
markedly better — the CLI feeds that data to the model as authoritative
input automatically.

## When not to use this skill

- **Finding or discovering recipes** — the user provides recipes; you
  may propose candidates via search, but only with confirmation.
- **Photo / scanned recipes** — no vision parsing.
- **Grocery cart automation** — no retailer integrations.
- **Meal-planning UIs** — this is a pipeline and a library, not an app.

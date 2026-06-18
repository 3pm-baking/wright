[![CI](https://github.com/3pm-baking/wright/actions/workflows/ci.yml/badge.svg)](https://github.com/3pm-baking/wright/actions/workflows/ci.yml)
[![docs](https://github.com/3pm-baking/wright/actions/workflows/docs.yml/badge.svg)](https://wright.germanbakingasheville.com)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

# wright

> **wright** /rīt/ — *noun*: a maker or builder. From Old English *wyrhta* (worker), as in *shipwright*, *wheelwright*, *playwright*. Here: a wright for your recipes, assemblies, and bills of materials.

<p align="center">
  <a href="https://wright.germanbakingasheville.com">
    <img src="https://media.githubusercontent.com/media/3pm-baking/wright/main/docs/assets/wright-logo.png" width="200" alt="wright">
  </a>
</p>

Pure Python library for production planning, cost calculation, shopping list
generation, allergen detection, nutrition analysis, and supply tracking.

Data-source agnostic. No I/O inside the core — models are plain Pydantic, the
`PurchasedItem` protocol accepts anything. Subclass to add your own fields.

**Domains**: food recipes, construction materials, brewing grain bills,
manufacturing BOMs — any domain where you need to aggregate named items with
quantities and units into a consolidated supply list with costs.

```bash
pip install wright
```

## Recipes and ingredients

```python
from wright import Recipe, Ingredient, RecipeComponent

cake = Recipe(
    name="Lemon Cake",
    components=[RecipeComponent(name="Batter", ingredients=[
        Ingredient(name="Flour", quantity=300, unit="g"),
        Ingredient(name="Butter", quantity=200, unit="g"),
        Ingredient(name="Lemon Juice", quantity=3, unit="tbsp"),
    ])],
    prep_time=30, cook_time=45,
    servings=12,
)

# Scale it
double_batch = cake * 2        # same as cake.size_up(2)
half_batch = cake * 0.5
```

## Costing

```python
from decimal import Decimal
from wright import Purchase, calculate_recipe_cost

groceries = [
    Purchase(name="Flour", quantity=1000, unit="g", price=Decimal("3.99")),
    Purchase(name="Butter", quantity=500, unit="g", price=Decimal("5.49")),
    Purchase(name="Lemon Juice", quantity=250, unit="ml", price=Decimal("1.99")),
]

cost = calculate_recipe_cost(cake, groceries)
print(cost.total_cost_range.midpoint)         # → 3.10
print(cost.cost_per_serving_range.midpoint)   # → 0.26
```

## Planning a production run

```python
from datetime import date
from wright import (
    ProductionRun, ProductionItem,
    generate_shopping_list, group_shopping_items,
    calculate_shopping_list_cost, analyze_menu,
    DEFAULT_CATEGORY_RULES,
)

session = ProductionRun(
    date=date(2026, 6, 20),
    production=[ProductionItem(assembly="Lemon Cake", quantity=3)],
    target_dates=[date(2026, 6, 20)],
)

shopping = generate_shopping_list(session, [cake])
```

Group items by store aisle:

```python
grouped = group_shopping_items(
    shopping.all_items,
    category_rules=DEFAULT_CATEGORY_RULES,
)
for group in grouped:
    for item in group.items:
        print(f"  {item.name:<22s} {item.quantity:g} {item.unit}")
```

```
  Dairy & Eggs  ----------------------------------------------
  Butter                        600 g
  Lemon Juice                   9 tbsp

  Dry Goods  -------------------------------------------------
  Flour                         900 g
```

Enrich with costs and analyze:

```python
costs = calculate_shopping_list_cost(shopping, groceries)
total = sum(c.total_cost for c in costs if c.total_cost is not None)
# → Decimal('9.30')

menu = analyze_menu(
    [ProductionItem(assembly="Lemon Cake", quantity=3)],
    [cake], groceries,
)
for item in menu.top_drivers:
    print(f"  {item.item.name}: ${item.total_cost} ({menu.cost_share(item):.0%})")
# → Butter: $3.29 (35%)
# → Flour: $2.39 (26%)
```

[Full grocery list example](https://github.com/3pm-baking/wright/blob/9f4b0d1/examples/grocery_list.py) with 3 recipes, 16 grocery items, and formatted output.
[Meal prep planner](https://github.com/3pm-baking/wright/blob/e25becf/examples/meal_prep.py) — 5-day week, 2 cook sessions, macros per day.

## Allergens and dietary badges

```python
from wright import detect_allergens, detect_dietary_properties

allergens = detect_allergens(cake, allergy_map={"milk": "Dairy", "wheat": "Wheat"})
# → ["Dairy", "Gluten", "Eggs"]

badges = detect_dietary_properties(cake)
# → ["VEGAN", "DAIRY-FREE", "GLUTEN-FREE"]
```

Supplement keyword detection with purchase data:

```python
badges = detect_dietary_properties(cake, ingredient_properties=lambda ing: (
    frozenset({"vegan", "gluten-free"}) if "gf" in ing.require_tags else frozenset()
))
```

## Nutrition

```python
from wright import calculate_recipe_macros, NutritionInfo, FoodRecord

registry = [
    FoodRecord(ingredient="Flour", nutrition=NutritionInfo(protein_g=10, carbs_g=76, fat_g=1, kcal=364)),
    FoodRecord(ingredient="Butter", nutrition=NutritionInfo(protein_g=0.9, carbs_g=0.1, fat_g=81, kcal=717)),
]

macros = calculate_recipe_macros(cake, nutrition_registry=registry)
print(macros.per_serving.kcal)
```

## Supply tracking

```python
from wright import Stock, SupplyItem

stock = Stock([SupplyItem(name="Flour", quantity=2000, unit="g")])
stock, deficit = stock.use([SupplyItem(name="Flour", quantity=900, unit="g")])
# deficit → []  — stock covers it
```

## Pricing

```python
from wright import margin_price, multiplier_price

margin_price(Decimal("2.00"), 0.67)     # → 6.06  (67% margin)
multiplier_price(Decimal("2.00"), 3)    # → 6.00  (3× cost)
```

## Everything is injectable

```python
from wright import chain, pinned_picker, cheapest_picker

# Compose pickers: pinned first, then cheapest
picker = chain(pinned_picker({"Butter": my_brand}), cheapest_picker)
items = calculate_shopping_list_cost(shopping, groceries, picker=picker)

# Custom volume display for metric users
shopping = generate_shopping_list(session, [cake],
    display_normalizer=lambda q, u: ...,
)

# Custom name matcher
cost = calculate_recipe_cost(cake, groceries,
    matcher=my_fuzzy_matcher,
)
```

## Non-food domains

``Assembly``, ``Component``, and ``Material`` work for construction, brewing,
manufacturing, or any bill-of-materials domain. No dummy food fields needed:

```python
from datetime import date
from decimal import Decimal
from wright import (
    Assembly, Component, ProductionItem, ProductionRun, Purchase,
    generate_shopping_list, calculate_item_costs,
)

# ── Two home projects ──────────────────────────────────────────────────────

deck = Assembly(name="Backyard Deck", components=[
    Component(name="Framing", materials=[
        Material(name="2x6 Pressure-Treated", quantity=48, unit="ft"),
        Material(name="Joist Hangers", quantity=16, unit="each"),
    ]),
    Component(name="Surface", materials=[
        Material(name='5/4" Cedar Decking', quantity=160, unit="ft"),
        Material(name='2" Stainless Screws', quantity=600, unit="each"),
    ]),
])

bed = Assembly(name="Raised Garden Bed", components=[
    Component(name="Frame", materials=[
        Material(name="2x8 Cedar", quantity=24, unit="ft"),
        Material(name='3" Deck Screws', quantity=64, unit="each"),
    ]),
])

# ── Hardware store prices ──────────────────────────────────────────────────

prices = [
    Purchase(name="2x6 Pressure-Treated", quantity=8, unit="ft",
             price=Decimal("12.97"), store="Home Depot"),
    Purchase(name='2" Stainless Screws', quantity=100, unit="each",
             price=Decimal("3.49"), store="Home Depot"),
]

# ── Cost one project ───────────────────────────────────────────────────────

deck_costs = calculate_item_costs(deck.all_materials, prices)
total = sum(c.total_cost for c in deck_costs if c.total_cost is not None)
print(f"Deck materials: ${total}")

# ── Plan a weekend build session ───────────────────────────────────────────

plan = ProductionRun(
    date=date(2026, 6, 20),
    production=[
        ProductionItem(assembly="Backyard Deck", quantity=1),
        ProductionItem(assembly="Raised Garden Bed", quantity=1),
    ],
    target_dates=[date(2026, 6, 20)],
)

shopping = generate_shopping_list(plan, [deck, bed])
for item in shopping.all_items:
    print(f"{item.name}: {item.quantity:.0f} {item.unit}")

# ── Cross-reference with home inventory ───────────────────────────────────

from wright import Stock, SupplyItem

# What's already in the garage
garage_stock = Stock([
    SupplyItem(name='2" Stainless Screws', quantity=100, unit="each"),
    SupplyItem(name="Joist Hangers", quantity=8, unit="each"),
])

# Deduct stock — get only what you still need to buy
garage_stock, buy_list = garage_stock.use(deck.all_materials)
for item in buy_list:
    print(f"Buy: {item.name} — {item.quantity:.0f} {item.unit}")
# → Buy: 2x6 Pressure-Treated — 48 ft
# → Buy: Joist Hangers — 8 each          (16 needed − 8 on hand)
# → Buy: 5/4" Cedar Decking — 160 ft
# → Buy: 2" Stainless Screws — 500 each  (600 needed − 100 on hand)
```

The same ``calculate_ingredient_cost()`` and ``Stock`` work across all domains.

## Requirements

Python 3.11+. Dependencies: `pydantic>=2.8.2`, `pint>=0.25`, `pyyaml>=6.0.3`.

## License

MIT. See [LICENSE](LICENSE).

<br>

<p align="center">
  <img src="https://media.githubusercontent.com/media/3pm-baking/wright/main/docs/assets/logo.png" width="120" alt="3pm German Baking">
</p>
<p align="center">
  <a href="https://github.com/3pm-baking/wright">wright</a> is created and maintained by
  <a href="https://germanbakingasheville.com">3pm German Baking, LLC</a>
  a farmers market bakery in Asheville, NC.
</p>

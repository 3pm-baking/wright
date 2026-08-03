---
title: Macro Tracking
description: Track protein, carbs, fat, and other numerical attributes across your recipes using purchase data and the USDA FoodData Central API.
---

# Macro Tracking

Every wright model — `Purchase`, `Material`, `SupplyItem`, and `Assembly` —
carries a `numeric_attrs: dict[str, float]` field for numerical data that
flows through the pipeline.

This keeps the library domain-agnostic: the same field works for
macronutrients (protein, carbs, fat), shelf life (days), yield percentage,
storage temperature, or any other numerical attribute you care about.

## The flow

```
Purchase.numeric_attrs       per-100g values from USDA or manual entry
       │ match + scale
       ▼
Material.numeric_attrs       scaled to recipe quantity
       │ sum across ingredients
       ▼
Recipe-level computation     total macros for the recipe
       │ ÷ servings
       ▼
Per-serving macros           what a customer eats
```

## Example: Green Smoothie macros

Let's work through a concrete example using the green smoothie recipe
from `examples/recipes/green-smoothie.yaml`:

```yaml
name: Green Smoothie
servings: 1
components:
  - name: Smoothie
    ingredients:
      - name: Spinach        # 2 cup
      - name: Banana         # 1 each
      - name: Protein Powder # 1 packet (30 g)
      - name: Almond Milk    # 240 ml
```

### 1. Purchases with macro data

Start with purchases that carry per-100g macronutrient values:

```python
from decimal import Decimal
from wright import Purchase

purchases = [
    Purchase(
        name="Spinach",
        quantity=5,
        unit="oz",
        price=Decimal("3.99"),
        numeric_attrs={"protein_g": 2.9, "carbs_g": 3.6, "fat_g": 0.4, "kcal": 23},
    ),
    Purchase(
        name="Banana",
        quantity=1,
        unit="lb",
        price=Decimal("0.69"),
        numeric_attrs={"protein_g": 1.1, "carbs_g": 23.0, "fat_g": 0.3, "kcal": 89},
    ),
    Purchase(
        name="Protein Powder",
        quantity=2,
        unit="lb",
        price=Decimal("29.99"),
        numeric_attrs={"protein_g": 80.0, "carbs_g": 10.0, "fat_g": 3.0, "kcal": 400},
    ),
    Purchase(
        name="Almond Milk",
        quantity=1,
        unit="gallon",
        price=Decimal("3.99"),
        numeric_attrs={"protein_g": 0.4, "carbs_g": 0.5, "fat_g": 1.0, "kcal": 17},
    ),
]
```

> **Tip:** Instead of typing macros by hand, use the
> [USDA FoodData Central](https://fdc.nal.usda.gov) API (free key required)
> to populate `numeric_attrs` from a purchase name.  See
> `examples/macro_tracking.py` for a complete `enrich_from_usda()`
> helper.  Use `dataType=Foundation,SR Legacy` to get whole-food data
> rather than branded products.

### 3. Compute macros per ingredient

Define a helper that matches an ingredient to its purchase, then
scales the per-100g values to the ingredient's quantity:

```python
from wright import (
    cheapest_picker,
    convert_ingredient_to_grams,
    find_matching_purchases,
)


def ingredient_macros(ingredient, purchases):
    matches = find_matching_purchases(ingredient, purchases)
    purchase = cheapest_picker(ingredient, matches)
    per_100g = getattr(purchase, "numeric_attrs", {})
    if not per_100g:
        return {}
    qty_g = convert_ingredient_to_grams(
        ingredient, raise_on_error=False, density_data={}
    )
    if qty_g <= 0:
        return {}
    factor = qty_g / 100
    return {k: round(v * factor, 1) for k, v in per_100g.items()}


for ingredient in smoothie.all_ingredients:
    macros = ingredient_macros(ingredient, purchases)
    print(f"{ingredient.name}: {macros}")
```

This works because `convert_ingredient_to_grams` now falls back to
density-based conversion — so `240 ml` of almond milk is correctly
converted to grams before applying the per-100g factor.

### 4. Recipe-level attributes

Recipe-level properties (shelf life of the prepared smoothie,
difficulty rating) live on `Assembly.numeric_attrs`, separate from
per-ingredient values:

```python
smoothie = Recipe(
    name="Green Smoothie",
    components=[...],
    prep_time=5,
    cook_time=0,
    servings=1,
    numeric_attrs={"shelf_life_days": 1, "difficulty": 1.0},
)
```

These propagate through `size_up()` but are distinct from the
per-ingredient macros — a blended smoothie spoils faster than its
individual ingredients.

### 5. Shopping list carry-through

When generating a shopping list, the `merge_numeric` callback controls
how same-name ingredients combine.  Default is **first-wins** (safe for
shelf life).  For macronutrients, use sum:

```python
def merge_sum(acc, inc):
    return {k: acc.get(k, 0) + v for k, v in inc.items()}


shopping = generate_shopping_list(
    session,
    recipes,
    merge_numeric=merge_sum,
)

for item in shopping.all_items:
    print(f"{item.name}: {item.numeric_attrs}")
```

The numeric attrs are preserved on `SupplyItem` objects through the
full stock lifecycle — `Stock.add()`, `Stock.use()`, and `Stock.remove()`
all carry the data forward.

### 6. Custom merge strategies

The `merge_numeric` callback receives `(accumulated, incoming)` dicts
and returns the merged result.  This lets you define per-key behavior:

```python
def merge_shelf_life(acc, inc):
    """Keep the shortest shelf life, sum everything else."""
    merged = {k: acc.get(k, 0) + inc.get(k, 0) for k in acc | inc}
    if "shelf_life_days" in acc and "shelf_life_days" in inc:
        merged["shelf_life_days"] = min(acc["shelf_life_days"], inc["shelf_life_days"])
    return merged
```

## Full example

A complete, runnable version of this workflow is available at
`examples/macro_tracking.py` in the wright repository.

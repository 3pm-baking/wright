---
title: Getting Started
description: Install wright with pip and go from zero to a costed, allergen-labeled production plan in three minutes.
---

# Getting Started

Three minutes to go from zero to a costed, allergen-labeled production plan.

```
pip install wright-core
```

```python
from decimal import Decimal
from datetime import date
from wright import (
    Recipe,
    Ingredient,
    RecipeComponent,
    Purchase,
    ProductionRun,
    ProductionItem,
    calculate_recipe_cost,
    generate_shopping_list,
    calculate_shopping_list_cost,
    analyze_menu,
    detect_allergens,
    detect_dietary_properties,
)

# 1. Define a recipe
recipe = Recipe(
    name="Overnight Oats",
    components=[
        RecipeComponent(
            name="Base",
            ingredients=[
                Ingredient(name="Rolled Oats", quantity=50, unit="g"),
                Ingredient(name="Greek Yogurt", quantity=100, unit="g"),
                Ingredient(name="Honey", quantity=1, unit="tbsp"),
            ],
        )
    ],
    prep_time=5,
    cook_time=0,
    servings=1,
)

# 2. Provide purchase data
groceries = [
    Purchase(name="Rolled Oats", quantity=1000, unit="g", price=Decimal("3.49")),
    Purchase(name="Greek Yogurt", quantity=500, unit="g", price=Decimal("4.99")),
    Purchase(name="Honey", quantity=340, unit="g", price=Decimal("5.99")),
]

# 3. Cost the recipe
cost = calculate_recipe_cost(recipe, groceries)
print(cost.total_cost_range.midpoint)  # → 1.32
print(cost.cost_per_serving_range.midpoint)  # → 1.32

# 4. Plan a production run
session = ProductionRun(
    date=date(2026, 6, 20),
    production=[ProductionItem(assembly="Overnight Oats", quantity=3)],
    target_dates=[date(2026, 6, 20)],
)
shopping = generate_shopping_list(session, [recipe])
print(shopping.production_summary)  # → ['3× Overnight Oats']

# 5. Detect allergens and dietary badges
allergy_map = {"milk": "Dairy", "egg": "Eggs"}
allergens = detect_allergens(recipe, allergy_map)
badges = detect_dietary_properties(recipe)

# 6. Enrich shopping list with costs
items = calculate_shopping_list_cost(shopping, groceries)
for item in items:
    print(f"{item.item.name}: ${item.total_cost}")

# 7. Analyze the full menu
analysis = analyze_menu(
    [ProductionItem(assembly="Overnight Oats", quantity=3)],
    [recipe],
    groceries,
)
print(f"Total cost: ${analysis.total_cost}")
for item in analysis.top_drivers:
    print(f"  {item.item.name}: ${item.total_cost}")
```

## Next steps

Dive deeper into each area:

- [Models](core/models.md) — Material, Component, subclassing, and the type system
- [Costing & Pricing](core/costing.md) — unit conversion, density data, margin calculation
- [Matching & Planning](core/planning.md) — pickers, menu analysis, categorization
- [Allergens & Nutrition](core/allergens-nutrition.md) — dietary badges, macros, nutrition callbacks

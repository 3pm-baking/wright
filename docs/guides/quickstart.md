# Quickstart

End-to-end walkthrough: define a recipe, cost it, plan a production run,
detect allergens, and enrich a shopping list with costs.

## 1. Define a recipe

```python
from wright import Recipe, Ingredient, RecipeComponent, ServingRange

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
```

## 2. Provide purchase data

Any object satisfying the `PurchasedItem` protocol works.  `Purchase`
is a built-in Pydantic model for convenience.

```python
from decimal import Decimal
from wright import Purchase

groceries = [
    Purchase(name="Rolled Oats", quantity=1000, unit="g", price=Decimal("3.49")),
    Purchase(name="Greek Yogurt", quantity=500, unit="g", price=Decimal("4.99")),
    Purchase(name="Honey", quantity=340, unit="g", price=Decimal("5.99")),
]
```

## 3. Calculate cost

```python
from wright import calculate_recipe_cost

cost = calculate_recipe_cost(recipe, groceries)
print(cost.total_cost_range)
# → PriceRange(min_price=Decimal('1.32'), max_price=Decimal('1.32'))
print(cost.cost_per_serving_range)
# → PriceRange(min_price=Decimal('1.32'), max_price=Decimal('1.32'))
```

## 4. Plan a production run

```python
from datetime import date
from wright import ProductionRun, ProductionItem, generate_shopping_list

session = ProductionRun(
    date=date(2026, 6, 20),
    production=[ProductionItem(recipe="Overnight Oats", quantity=3)],
    target_dates=[date(2026, 6, 20)],
)

recipes = {"Overnight Oats": recipe}
shopping = generate_shopping_list(session, recipes)

print(shopping.production_summary)
# → ['3× Overnight Oats']
```

## 5. Detect allergens and dietary badges

```python
from wright import detect_allergens, detect_dietary_properties

allergy_map = {"milk": "Milk", "egg": "Egg"}

allergens = detect_allergens(recipe, allergy_map)
badges = detect_dietary_properties(recipe)
```

## 6. Enrich shopping list with costs

```python
from wright import calculate_shopping_list_cost

items_with_cost = calculate_shopping_list_cost(shopping, groceries)
for item in items_with_cost:
    print(f"{item.item.name}: ${item.total_cost}")
```

## 7. Analyze a full menu

```python
from wright import analyze_menu

analysis = analyze_menu(
    [ProductionItem(recipe="Overnight Oats", quantity=3)],
    recipes,
    groceries,
)

print(f"Total cost: ${analysis.total_cost}")
for item in analysis.top_drivers:
    print(f"  {item.item.name}: ${item.total_cost} ({analysis.cost_share(item):.0%})")
```

## Next steps

- [Examples](examples.md) — copy-paste patterns for every workflow
- [Customization guide](customization.md) — inject custom matchers, pickers, and callbacks
- [Domains guide](domains.md) — construction, brewing, event planning, manufacturing
- [API Reference](../api.md) — full function and model documentation

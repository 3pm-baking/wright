# Costing & Pricing

## Costing a recipe

Provide purchase data — any object satisfying the `PurchasedItem` protocol
works. `Purchase` is a built-in Pydantic model for convenience.

```python
from decimal import Decimal
from wright import Purchase, calculate_recipe_cost, get_top_cost_drivers

groceries = [
    Purchase(name="Flour", quantity=1000, unit="g", price=Decimal("3.99")),
    Purchase(name="Butter", quantity=500, unit="g", price=Decimal("5.49")),
]

cost = calculate_recipe_cost(recipe, groceries)
```

`calculate_recipe_cost` returns a `RecipeCost` with:

| Attribute | Type | Description |
|-----------|------|-------------|
| `.total_cost_range` | `PriceRange` | min/max total cost for the recipe |
| `.cost_per_serving_range` | `PriceRange` | min/max cost divided by servings |
| `.ingredient_costs` | `list[IngredientCost]` | per-ingredient cost breakdown |

```python
print(cost.total_cost_range)
# → PriceRange(min_price=Decimal('1.99'), max_price=Decimal('1.99'))
print(cost.cost_per_serving_range.midpoint)
# → Decimal('0.20')
```

### Top cost drivers

```python
drivers = get_top_cost_drivers(cost, n=3)
# → list[IngredientCost] sorted by price_descending
for d in drivers:
    print(f"{d.ingredient_name}: ${d.price_range.midpoint}")
```

## Unit conversion

Recipes use grams. Purchases use pounds. `wc_right` handles conversion
transparently:

```python
# Recipe: 170g salmon. Supplier: 454g at $14.99
# → 170/454 * $14.99 = $5.61
```

For volume-to-weight conversions (e.g., olive oil), provide density data:

```python
density_data = {"liquids": {"Olive Oil": 0.91}}  # 0.91 g/ml
cost = calculate_recipe_cost(recipe, groceries, density_data=density_data)
```

For dry ingredients (spices, sugar), use volume weights:

```python
density_data = {
    "volume_weights": {
        "Cinnamon": {"tsp": 2.6, "tbsp": 7.8},
        "Sugar": {"tsp": 4.2, "tbsp": 12.5, "cup": 200.0},
    }
}
```

## Pricing

Two strategies, one idea: cover costs and leave margin.

```python
from wright import margin_price, multiplier_price

cost = Decimal("2.00")

margin_price(cost, 0.67)  # → Decimal('6.06')  — 67% margin
multiplier_price(cost, 3)  # → Decimal('6.00')  — 3× cost
```

Every pricing function returns a `Decimal`. No formatting or rounding inside
the library — do that at your UI layer.

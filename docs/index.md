# wright

Pure Python library for production planning, cost calculation, unit conversion,
allergen detection, nutrition analysis, supply tracking, and shopping list
aggregation.

Data-source agnostic — populate models from YAML, JSON, a database, or pure Python.
Subclass to add domain-specific metadata.

```bash
pip install wright
```

## What it does

| Module | Purpose |
|--------|---------|
| `models` | Core data models: `BaseIngredient`, `BaseRecipe`, `RecipeComponent`, `ServingRange`, `NutritionInfo`, `CategoryRule` — plus the `PurchasedItem` protocol |
| `costing` | Recursive ingredient cost calculation with unit conversion, density fallback, `product_ref` sub-recipe resolution, and top-N cost driver analysis |
| `matching` | Pluggable ingredient-to-purchase matching with composable pickers: `cheapest_picker`, `recent_picker`, `pinned_picker`, `chain()` |
| `planning` | Shopping list generation from production runs, cost enrichment, menu analysis, volume normalization |
| `pricing` | Margin and multiplier pricing functions |
| `allergens` | Allergen detection and dietary badge derivation — keyword-based with override callbacks |
| `macros` | Per-serving nutrition calculation via a central `NutritionRegistry`, with `product_ref` support |
| `supply` | Stock tracking: `supply_add`, `supply_deduct`, `subtract_supply` with unit-aware operations |
| `session` | `ProductionRun` and `ProductionItem` for multi-batch planning |
| `loader` | Optional YAML helpers (`load_base_recipe`, `load_purchases`, `load_density_data`) |
| `errors` | Typed exceptions: `IngredientNotFoundError`, `UnitConversionError`, `RecipeCostErrors` |
| `units` | Pint registry with common units and unit classification frozensets |

## Quick example

```python
from decimal import Decimal
from wright import BaseRecipe, BaseIngredient, RecipeComponent, SimplePurchase
from wright import calculate_recipe_cost

recipe = BaseRecipe(
    name="Overnight Oats",
    components=[RecipeComponent(name="Base", ingredients=[
        BaseIngredient(name="Rolled Oats", quantity=50, unit="g"),
        BaseIngredient(name="Greek Yogurt", quantity=100, unit="g"),
    ])],
    prep_time=5, cook_time=0, servings=1,
)

groceries = [
    SimplePurchase(name="Rolled Oats", quantity=1000, unit="g", price=Decimal("3.49")),
    SimplePurchase(name="Greek Yogurt", quantity=500, unit="g", price=Decimal("4.99")),
]

cost = calculate_recipe_cost(recipe, groceries)
print(f"Total: ${cost.total_cost_range.midpoint:.2f}")
```

## Design principles

- **No I/O.** Core functions take data in, return data out. No files, no databases, no network.
- **Protocol-based.** `PurchasedItem` is a protocol — any class with the right attributes works.
- **Pluggable.** Matchers, pickers, converters, normalizers, and callbacks are injected at every decision point.
- **Subclass-friendly.** Pydantic models are designed for inheritance. Add domain fields without monkey-patching.

## Requirements

Python 3.11+. Dependencies: `pydantic>=2.8.2`, `pint>=0.25`, `pyyaml>=6.0.3`.

## License

MIT. See [LICENSE](https://github.com/3pm-baking/wright/blob/main/LICENSE).

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
| `allergens` | Allergen detection (`detect_allergens`) and dietary badge derivation (`detect_dietary_properties`) — keyword-based with override callbacks |
| `macros` | Per-serving nutrition calculation via a central `NutritionRegistry`, with `product_ref` support |
| `supply` | Stock tracking: `supply_add`, `supply_deduct`, `subtract_supply` with unit-aware operations |
| `session` | `ProductionRun` and `ProductionItem` for multi-batch planning |
| `loader` | Optional YAML helpers (`load_base_recipe`, `load_purchases`, `load_density_data`) |
| `errors` | Typed exceptions: `IngredientNotFoundError`, `UnitConversionError`, `RecipeCostErrors` |
| `units` | Pint registry with common units (`each`, `packet`, `pinch`) and unit classification frozensets |

## Quick start

### Define recipes in pure Python

```python
from decimal import Decimal
from wright import BaseRecipe, BaseIngredient, RecipeComponent, ServingRange

recipe = BaseRecipe(
    name="Overnight Oats",
    components=[
        RecipeComponent(name="Base", ingredients=[
            BaseIngredient(name="Rolled Oats", quantity=50, unit="g"),
            BaseIngredient(name="Greek Yogurt", quantity=100, unit="g"),
            BaseIngredient(name="Honey", quantity=1, unit="tbsp"),
        ])
    ],
    prep_time=5,
    cook_time=0,
    servings=1,
)
```

### Purchase data — any object works

The `PurchasedItem` protocol means you can use dataclasses, SQLModel ORM objects, or plain classes:

```python
from wright import SimplePurchase

groceries = [
    SimplePurchase(name="Rolled Oats", quantity=1000, unit="g", price=Decimal("3.49")),
    SimplePurchase(name="Greek Yogurt", quantity=500, unit="g", price=Decimal("4.99")),
]
```

### Calculate costs

```python
from wright import calculate_recipe_cost

cost = calculate_recipe_cost(recipe, groceries)
print(f"Total: ${cost.total_cost_range.midpoint:.2f}")
```

### Plan a production run

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
```

### Detect allergens and dietary badges

```python
from wright import detect_allergens, detect_dietary_properties

allergy_map = {"milk": "Milk", "wheat": "Wheat", "egg": "Egg"}

allergens = detect_allergens(recipe, allergy_map)
# → ["Milk"] or []

badges = detect_dietary_properties(recipe)
# → ["VEGAN"] or ["GLUTEN-FREE"] or []
```

### Inject custom knowledge

Every decision point is injectable:

```python
from wright import chain, pinned_picker, cheapest_picker, detect_dietary_properties

# Choose which purchase price to use
picker = chain(pinned_picker({"Rolled Oats": my_preferred_oats}), cheapest_picker)

# Authoritative dietary properties from your own data
def my_properties(ingredient):
    if ingredient.name == "Protein Powder":
        return frozenset({"vegan", "gluten-free"})
    return frozenset()  # fall through to keyword matching

badges = detect_dietary_properties(recipe, ingredient_properties=my_properties)
```

## Design principles

- **No I/O.** Core functions take data in, return data out. No files, no databases, no network.
- **Protocol-based.** `PurchasedItem` is a protocol — any class with the right attributes works.
- **Pluggable.** Matchers, pickers, converters, normalizers, and callbacks are injected at every decision point.
- **Subclass-friendly.** Pydantic models are designed for inheritance. Add domain fields without monkey-patching.

## Requirements

Python 3.11+. Dependencies: `pydantic>=2.8.2`, `pint>=0.25`, `pyyaml>=6.0.3`.

## License

MIT. See [LICENSE](LICENSE).

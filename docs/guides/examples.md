# Examples

Building blocks for common tasks. Each section shows what functions return
so you can compose them with comprehensions, `sorted()`, `sum()`, etc.

See the `examples/` directory for the full self-testing scripts.

## Defining recipes

```python
from wright import Recipe, Ingredient, RecipeComponent, ServingRange

recipe = Recipe(
    name="Overnight Oats",
    components=[RecipeComponent(name="Base", ingredients=[
        Ingredient(name="Rolled Oats", quantity=50, unit="g"),
        Ingredient(name="Greek Yogurt", quantity=100, unit="g"),
    ])],
    prep_time=5, cook_time=0,
    servings=ServingRange(min_servings=2, max_servings=4),
)
# → Recipe with .all_ingredients, .servings.midpoint, .net_weight_grams

double = recipe * 2      # → Recipe (delegates to .size_up())
half = recipe * 0.5
```

## Costing

```python
from decimal import Decimal
from wright import Purchase, calculate_recipe_cost, get_top_cost_drivers

purchases = [
    Purchase(name="Rolled Oats", quantity=1000, unit="g", price=Decimal("3.49")),
    Purchase(name="Greek Yogurt", quantity=500, unit="g", price=Decimal("4.99")),
]

cost = calculate_recipe_cost(recipe, purchases)
# → RecipeCost(.total_cost_range, .cost_per_serving_range, .ingredient_costs)

drivers = get_top_cost_drivers(cost, n=3)
# → list[IngredientCost] sorted by .price_range.midpoint descending
```

## Pricing

```python
from decimal import Decimal
from wright import margin_price, multiplier_price

margin_price(Decimal("2.00"), 0.67)     # → 6.06
multiplier_price(Decimal("2.00"), 3)    # → 6.00
```

## Nutrition

```python
from wright import calculate_recipe_macros, NutritionInfo

registry = {
    "Rolled Oats": NutritionInfo(protein_g=13.5, carbs_g=66.3, fat_g=6.5, kcal=389),
    "Greek Yogurt": NutritionInfo(protein_g=10.0, carbs_g=3.6, fat_g=0.7, kcal=59),
}

macros = calculate_recipe_macros(recipe, nutrition_registry=registry)
# → RecipeMacros(.recipe_name, .total, .per_serving)
# .total: MacroPerServing(.protein_g, .carbs_g, .fat_g, .fiber_g, .kcal)
```

## Allergens and dietary badges

```python
from wright import detect_allergens, detect_dietary_properties

allergens = detect_allergens(recipe, allergy_map={"milk": "Milk", "wheat": "Wheat"})
# → list[str] — sorted allergen display names

badges = detect_dietary_properties(recipe)
# → list[str] — dietary badge labels (e.g. ["VEGAN", "GLUTEN-FREE"])
```

## Planning

```python
from datetime import date
from wright import ProductionRun, ProductionItem, generate_shopping_list

session = ProductionRun(
    date=date(2026, 6, 20),
    production=[ProductionItem(recipe="Overnight Oats", quantity=3)],
    target_dates=[date(2026, 6, 20)],
)

shopping = generate_shopping_list(session, {"Overnight Oats": recipe})
# → ShoppingList(.date, .production_summary, .groups, .all_items)
# .all_items → list[SupplyItem] each with .name, .quantity, .unit, .tags
```

## Enriching with costs

```python
from wright import calculate_shopping_list_cost

items = calculate_shopping_list_cost(shopping, purchases)
# → list[ShoppingItemWithCost]
#   each has .item (ShoppingItem), .total_cost, .store, .missing_price,
#   .price_per_unit, .price_unit, .purchase_date

total = sum(i.total_cost for i in items if i.total_cost is not None)
```

## Menu analysis

```python
from wright import analyze_menu

menu = analyze_menu(
    [ProductionItem(recipe="Overnight Oats", quantity=3)],
    {"Overnight Oats": recipe},
    purchases,
)
# → MenuAnalysis(.total_cost, .items, .top_drivers, .missing_ingredients)

sorted_items = sorted(menu.items, key=lambda i: i.total_cost or 0, reverse=True)
```

## Supply tracking

```python
from wright import Stock, SupplyItem

stock = Stock([SupplyItem(name="Flour", quantity=2000, unit="g")])
stock, deficit = stock.use([SupplyItem(name="Flour", quantity=900, unit="g")])
# deficit → []  — stock covers it, stock now has 1100g Flour
```

## Custom pickers

```python
from wright import chain, pinned_picker, cheapest_picker, calculate_shopping_list_cost

picker = chain(pinned_picker({"Rolled Oats": my_brand}), cheapest_picker)
items = calculate_shopping_list_cost(shopping, purchases, picker=picker)
```

Available pickers: `pinned_picker`, `cheapest_picker`, `recent_picker`,
`first_picker`, `compatible_unit_recent_picker` (default), `chain`.

## Ingredient categorization

```python
from wright import categorize_item, CategoryRule

categorize_item("Flour", rules=[
    CategoryRule(category="Aisle 1", priority=0, keywords=["flour", "sugar"]),
])
# → str | None — category name, or None if no rules match
```

## Construction domain

`Material` and `Component` work for any bill-of-materials domain:

```python
from wright import Material, Component, ProductionItem, generate_shopping_list

# Define a deck as components with materials
framing = Component(name="Deck Framing", materials=[
    Material(name="2x6 Pressure-Treated", quantity=24, unit="ft", require_tags=["#2"]),
    Material(name="3\" Deck Screws", quantity=200, unit="each"),
])
footings = Component(name="Footings", materials=[
    Material(name="Concrete Mix", quantity=6, unit="bag",
             equivalent_quantity=60, equivalent_unit="lb"),
])

# Scale for a bigger deck
big_framing = framing * 1.5
# → each material scaled by 1.5x

# Classify with construction-specific categories
from wright import CategoryRule, categorize_item

lumberyard_rules = [
    CategoryRule(category="Lumber", priority=0,
                 keywords=["lumber", "plywood", "2x", "stud"]),
    CategoryRule(category="Hardware", priority=1,
                 keywords=["screw", "nail", "bolt", "anchor"]),
    CategoryRule(category="Concrete", priority=2,
                 keywords=["concrete", "cement", "mortar"]),
]

cat = categorize_item("2x6 Pressure-Treated", rules=lumberyard_rules)
# → "Lumber"
```

## Subclassing Material for domain data

```python
from wright import Material

class Lumber(Material):
    grade: str | None = None
    waste_factor: float = 0.10  # 10% extra for offcuts
    species: str | None = None

stud = Lumber(name="2x4 Stud", quantity=12, unit="ft",
              grade="#2", species="Douglas Fir", waste_factor=0.05)
```

See the [Domains guide](domains.md) for full construction, brewing, and
manufacturing walkthroughs.

## Grocery list

[`examples/grocery_list.py`](https://github.com/3pm-baking/wright/blob/9f4b0d1/examples/grocery_list.py)
generates a consolidated shopping list from three recipes, groups items
by store aisle, and enriches each line with costs.

```python
from datetime import date
from wright import (
    DEFAULT_CATEGORY_RULES,
    ProductionRun, ProductionItem,
    generate_shopping_list, group_shopping_items,
    calculate_shopping_list_cost, analyze_menu,
)

recipes = {"Overnight Oats": oats, "Green Smoothie": smooth, "Quinoa Power Bowl": bowl}
groceries = [
    Purchase(name="Rolled Oats", quantity=1000, unit="g", price=Decimal("3.49")),
    # ... 15 more items
]

session = ProductionRun(
    date=date(2026, 6, 20),
    production=[
        ProductionItem(assembly="Overnight Oats", quantity=3),
        ProductionItem(assembly="Green Smoothie", quantity=2),
        ProductionItem(assembly="Quinoa Power Bowl", quantity=1),
    ],
    target_dates=[date(2026, 6, 20)],
)

shopping = generate_shopping_list(session, recipes)
grouped = group_shopping_items(shopping.all_items, category_rules=DEFAULT_CATEGORY_RULES)
costs = calculate_shopping_list_cost(shopping, groceries, density_data=density_data)
```

```
Shopping List
--------------------------------------------------------------
  Date: 2026-06-20
  Making: 3x Overnight Oats, 2x Green Smoothie, 1x Quinoa Power Bowl

   Dairy & Eggs  ----------------------------------------------
  Greek Yogurt                    300 g

   Dry Goods  -------------------------------------------------
  Protein Powder                   30 g
  Salt                            1 tsp [sea salt]

   Fats & Oils  -----------------------------------------------
  Olive Oil                      2 tbsp

   Produce  ---------------------------------------------------
  Banana                         2 each
  Spinach                       1 quart

   Specialty Items  -------------------------------------------
  Chia Seeds                     3 tbsp

--------------------------------------------------------------
  Estimated total:                     $17.77

  Top cost drivers
  1. Greek Yogurt           $  2.69  (15%)
  2. Sweet Potato           $  2.50  (14%)
  ...
--------------------------------------------------------------
```

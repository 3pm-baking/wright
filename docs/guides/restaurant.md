# Restaurants — Using wright for Food Service

`wright` is not a full restaurant management system, but it is a powerful
**embedded costing engine** for any food service tool.  It answers the core
question every kitchen needs: *what does this dish cost to make?*

## What wright handles (and what it doesn't)

| In scope | Out of scope (build on top) |
|----------|---------------------------|
| Recipe costing with per-serving breakdown | POS integration, table management |
| Sub-recipes and batch scaling | Labor scheduling, time clocks |
| Consolidated ordering lists from a menu plan | Vendor ordering, receiving workflow |
| Allergen detection for menu labeling | HACCP compliance, temperature logs |
| Nutrition calculation (if USDA data provided) | Inventory valuation (FIFO/LIFO) |
| Stock-on-hand tracking and deduction | Menu engineering dashboards |
| Margin and multiplier pricing | Food cost % trending over time |

Think of `wright` as the **math layer** — it computes costs, aggregates BOMs,
and tracks inventory.  The rest (dashboards, ordering, POS) lives in your
application.

## Quick Start: Cost a Dish

```python
from decimal import Decimal
from wright import Recipe, Ingredient, RecipeComponent, Purchase, calculate_recipe_cost

dish = Recipe(
    name="Pan-Seared Salmon",
    components=[
        RecipeComponent(
            name="Protein",
            ingredients=[
                Ingredient(name="Atlantic Salmon Fillet", quantity=170, unit="g"),
            ],
        ),
        RecipeComponent(
            name="Sides",
            ingredients=[
                Ingredient(name="Baby Spinach", quantity=85, unit="g"),
                Ingredient(name="Olive Oil", quantity=2, unit="tbsp"),
                Ingredient(name="Lemon Juice", quantity=1, unit="tbsp"),
            ],
        ),
    ],
    prep_time=10,
    cook_time=12,
    servings=1,
)

# Purchase prices from your supplier catalog
supplier_prices = [
    Purchase(
        name="Atlantic Salmon Fillet",
        quantity=454,
        unit="g",
        price=Decimal("14.99"),
        store="Sysco",
    ),
    Purchase(
        name="Baby Spinach",
        quantity=142,
        unit="g",
        price=Decimal("3.99"),
        store="Sysco",
    ),
    Purchase(
        name="Olive Oil", quantity=500, unit="ml", price=Decimal("8.49"), store="Sysco"
    ),
    Purchase(
        name="Lemon Juice",
        quantity=250,
        unit="ml",
        price=Decimal("1.99"),
        store="Sysco",
    ),
]

cost = calculate_recipe_cost(dish, supplier_prices)
print(f"Cost: ${cost.total_cost_range.midpoint}")
print(f"Food cost at $28 menu price: {float(cost.total_cost_range.midpoint / 28):.0%}")
```

## Sub-Recipes: The Restaurant Superpower

Kitchens don't make every component from scratch for each order. A stock,
sauce, or braise gets made once and used across multiple dishes.  `product_ref`
handles this with recursive costing:

```python
# Base component — made in bulk, costed once
chicken_stock = Recipe(
    name="Chicken Stock",
    components=[
        RecipeComponent(
            name="Base",
            ingredients=[
                Ingredient(name="Chicken Bones", quantity=2000, unit="g"),
                Ingredient(name="Onion", quantity=300, unit="g"),
                Ingredient(name="Carrot", quantity=200, unit="g"),
                Ingredient(name="Celery", quantity=150, unit="g"),
            ],
        )
    ],
    prep_time=15,
    cook_time=240,
    servings=None,  # not portioned as a dish
    net_weight_grams=1500,  # yield after reduction
)

# Dishes that use the stock
risotto = Recipe(
    name="Wild Mushroom Risotto",
    components=[
        RecipeComponent(
            name="Risotto",
            ingredients=[
                Ingredient(name="Arborio Rice", quantity=80, unit="g"),
                Ingredient(
                    name="Chicken Stock",
                    quantity=200,
                    unit="ml",
                    product_ref="Chicken Stock",
                ),  # recurses into stock cost
                Ingredient(name="Wild Mushrooms", quantity=60, unit="g"),
                Ingredient(name="Parmesan", quantity=15, unit="g"),
            ],
        )
    ],
    prep_time=10,
    cook_time=25,
    servings=1,
)

# When you cost the risotto, it automatically costs the stock proportionally
recipe_index = {"Chicken Stock": chicken_stock}
cost = calculate_recipe_cost(risotto, supplier_prices, recipe_index=recipe_index)
# Chicken Stock contribution: 200ml × (stock_cost / 1500g yield)
```

No duplication. Change the stock recipe (or its ingredient prices) and every
dish that uses it updates automatically.

## Menu Analysis: What Drives Your Costs?

Run a menu-wide analysis to identify your biggest cost drivers:

```python
from wright import analyze_menu, ProductionItem

menu = [
    ProductionItem(assembly="Pan-Seared Salmon", quantity=1),
    ProductionItem(assembly="Wild Mushroom Risotto", quantity=1),
    ProductionItem(assembly="Caesar Salad", quantity=1),
]

analysis = analyze_menu(menu, all_recipes, supplier_prices)

print(f"Total ingredient cost: ${analysis.total_cost}")
for item in analysis.top_drivers:
    print(f"  {item.item.name}: ${item.total_cost} ({analysis.cost_share(item):.0%})")
```

This tells you where to negotiate with suppliers, substitute ingredients, or
re-engineer a dish.

## Batch Planning: Prep for a Shift

Model a day's prep as a production run:

```python
from datetime import date
from wright import ProductionRun, generate_shopping_list

saturday_dinner = ProductionRun(
    date=date(2026, 6, 21),
    production=[
        ProductionItem(assembly="Pan-Seared Salmon", quantity=30),
        ProductionItem(assembly="Wild Mushroom Risotto", quantity=20),
        ProductionItem(assembly="Chicken Stock", quantity=2),  # make 2 batches
    ],
    target_dates=[date(2026, 6, 21)],
)

shopping = generate_shopping_list(saturday_dinner, all_recipes)

for group in shopping.groups:
    print(f"\n{group.group_name}:")
    for item in group.items:
        print(f"  {item.quantity} {item.unit} {item.name}")
```

This handles cross-recipe aggregation: salmon appears in one dish, spinach in
two, olive oil in four — the shopping list automatically consolidates.

## Unit Conversion for Kitchens

Recipes use grams and milliliters. Supplier catalogs use pounds and gallons.
`wright` handles this transparently:

```python
# Recipe says 170g salmon. Supplier sells by the pound.
# calculate_recipe_cost automatically converts: 170g → 0.375 lb
# And prices it: $14.99/lb × 0.375 lb = $5.62

# For volume-to-weight (olive oil), provide density data:
density_data = {"liquids": {"Olive Oil": 0.91}}  # 0.91 g/ml
cost = calculate_recipe_cost(dish, supplier_prices, density_data=density_data)
```

## Allergen Detection for Menus

Every dish should declare allergens. `wright` automates it:

```python
from wright import detect_allergens

allergy_map = {
    "milk": "Dairy",
    "cheese": "Dairy",
    "parmesan": "Dairy",
    "wheat": "Gluten",
    "flour": "Gluten",
    "egg": "Eggs",
    "fish": "Fish",
    "salmon": "Fish",
}

allergens = detect_allergens(dish, allergy_map)
print(f"Contains: {', '.join(allergens)}")  # → "Contains: Dairy, Fish"
```

## Nutrition Facts (USDA or Custom Data)

Per-serving nutrition with your own ingredient database:

```python
from wright import calculate_recipe_macros, NutritionInfo

nutrition_db = {
    "Atlantic Salmon Fillet": NutritionInfo(
        protein_g=20.4, carbs_g=0, fat_g=13.4, kcal=208
    ),
    "Baby Spinach": NutritionInfo(protein_g=2.9, carbs_g=3.6, fat_g=0.4, kcal=23),
}

macros = calculate_recipe_macros(dish, nutrition_registry=nutrition_db)
print(
    f"Per serving: {macros.per_serving.kcal:.0f} kcal, "
    f"{macros.per_serving.protein_g:.0f}g protein"
)
```

## Stock Tracking: Walk-In to Prep Sheet

Track what's in the walk-in and deduct what you use:

```python
from wright import Stock, SupplyItem

walk_in = Stock([
    SupplyItem(name="Atlantic Salmon Fillet", quantity=5000, unit="g"),
    SupplyItem(name="Arborio Rice", quantity=2000, unit="g"),
    SupplyItem(name="Olive Oil", quantity=3000, unit="ml"),
])

# Deduct 30 salmon dishes
needs = [SupplyItem(name="Atlantic Salmon Fillet", quantity=30 * 170, unit="g")]
walk_in, deficit = walk_in.use(needs)

if deficit:
    for d in deficit:
        print(f"Order: {d.quantity} {d.unit} {d.name}")
# → Nothing — 5000g stock covers 5100g needed? Wait, that's a deficit!
# → Order: 100.0 g Atlantic Salmon Fillet
```

## Pricing Rules

```python
from wright import margin_price, multiplier_price

cost = Decimal("5.62")

# Industry standard: 30% food cost target = 70% margin
price = margin_price(cost, 0.70)  # → $18.73

# Or simple 3x multiplier
price = multiplier_price(cost, 3)  # → $16.86
```

## Custom Categorization: Your Kitchen Layout

Map ingredients to your kitchen's prep stations:

```python
from wright import categorize_item, CategoryRule

station_rules = [
    CategoryRule(
        category="Butcher/Protein",
        priority=0,
        keywords=["salmon", "chicken", "beef", "pork", "fish"],
    ),
    CategoryRule(
        category="Produce Wash",
        priority=1,
        keywords=["spinach", "mushroom", "onion", "carrot", "celery", "lemon"],
    ),
    CategoryRule(
        category="Pantry/Dry Storage",
        priority=2,
        keywords=["rice", "flour", "oil", "salt", "sugar", "vinegar"],
    ),
    CategoryRule(
        category="Dairy/Cheese",
        priority=3,
        keywords=["butter", "cream", "cheese", "milk", "parmesan"],
    ),
]

for item in shopping.all_items:
    station = categorize_item(item.name, rules=station_rules)
    print(f"  [{station}] {item.name}")
```

## Where to Go From Here

- Build a prep list generator on top of `generate_shopping_list`
- Feed `Stock.use()` from your walk-in inventory database
- Use `analyze_menu` to track food cost % week over week
- Wire `calculate_recipe_cost` into your menu engineering spreadsheet

`wright` handles the math.  The application — ordering, scheduling, POS,
dashboards — is yours to build.

# Matching & Planning

## Matching ingredients to purchases

The default matcher does exact name matching. Compose pickers with `chain()`:

```python
from wright import chain, pinned_picker, cheapest_picker, calculate_shopping_list_cost

picker = chain(pinned_picker({"Rolled Oats": my_brand}), cheapest_picker)
items = calculate_shopping_list_cost(shopping, groceries, picker=picker)
```

Available pickers:

| Picker | Behavior |
|--------|----------|
| `first_picker` | First matching purchase, any store |
| `cheapest_picker` | Lowest price among matches |
| `recent_picker` | Most recent purchase date |
| `compatible_unit_recent_picker` | Most recent with compatible units *(default)* |
| `pinned_picker` | Override specific ingredients, fall through to next |
| `chain` | Compose multiple pickers in sequence |

Inject a custom name matcher:

```python
def fuzzy_matcher(ingredient, groceries):
    exact = [g for g in groceries if g.name == ingredient.name]
    if exact:
        return [g for g in exact if g.matches_requirements(ingredient.require_tags)]
    return [
        g
        for g in groceries
        if ingredient.name.lower() in g.name.lower()
        and g.matches_requirements(ingredient.require_tags)
    ]

cost = calculate_recipe_cost(recipe, groceries, matcher=fuzzy_matcher)
```

## Planning a production run

```python
from datetime import date
from wright import ProductionRun, ProductionItem, generate_shopping_list

session = ProductionRun(
    date=date(2026, 6, 20),
    production=[ProductionItem(assembly="Lemon Cake", quantity=3)],
    target_dates=[date(2026, 6, 20)],
)

shopping = generate_shopping_list(session, recipes)
# → ShoppingList(.date, .production_summary, .groups, .all_items)
# .all_items → list[SupplyItem] each with .name, .quantity, .unit, .tags
```

## Enriching with costs

```python
from wright import calculate_shopping_list_cost

items = calculate_shopping_list_cost(shopping, groceries)
for item in items:
    print(f"{item.item.name}: ${item.total_cost}")

total = sum(i.total_cost for i in items if i.total_cost is not None)
```

Each `ShoppingItemWithCost` carries:

| Attribute | Description |
|-----------|-------------|
| `.item` | The `SupplyItem` from the shopping list |
| `.total_cost` | Cost for the required quantity (`Decimal` or `None`) |
| `.store` | Where it was purchased |
| `.price_per_unit` | Unit price from the purchase record |
| `.price_unit` | Unit of the price (e.g. "g", "lb") |
| `.purchase_date` | When the price was recorded |

## Menu analysis

```python
from wright import analyze_menu

menu = analyze_menu(
    [ProductionItem(assembly="Lemon Cake", quantity=3)],
    recipes,
    groceries,
)
# → MenuAnalysis(.total_cost, .items, .top_drivers, .missing_ingredients)

print(f"Total cost: ${menu.total_cost}")
for item in menu.top_drivers:
    print(f"  {item.item.name}: ${item.total_cost} ({menu.cost_share(item):.0%})")
```

## Categorization

Group shopping list items by store aisle or kitchen station:

```python
from wright import categorize_item, CategoryRule

rules = [
    CategoryRule(category="Dry Goods", priority=0, keywords=["flour", "sugar", "rice"]),
    CategoryRule(category="Dairy & Eggs", priority=1, keywords=["butter", "milk", "cream", "egg"]),
    CategoryRule(category="Produce", priority=2, keywords=["spinach", "apple", "lemon"]),
]

for item in shopping.all_items:
    cat = categorize_item(item.name, rules=rules)
    print(f"  [{cat}] {item.name}")
```

Rules are applied in priority order (lowest number first). First keyword match
wins. Use `DEFAULT_CATEGORY_RULES` for grocery-store categories out of the box.

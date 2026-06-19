"""Grocery list generation — runnable example with formatted output.

Usage:
    python examples/grocery_list.py
"""

from datetime import date
from decimal import Decimal

from wright import (
    DEFAULT_CATEGORY_RULES,
    Ingredient,
    ProductionItem,
    ProductionRun,
    Purchase,
    Recipe,
    RecipeComponent,
    analyze_menu,
    calculate_shopping_list_cost,
    generate_shopping_list,
    group_shopping_items,
)

# ── Recipes ────────────────────────────────────────────────────────────

overnight_oats = Recipe(
    name="Overnight Oats",
    components=[
        RecipeComponent(
            name="Base",
            ingredients=[
                Ingredient(name="Rolled Oats", quantity=50, unit="g"),
                Ingredient(name="Greek Yogurt", quantity=100, unit="g"),
                Ingredient(name="Honey", quantity=1, unit="tbsp"),
                Ingredient(name="Chia Seeds", quantity=1, unit="tbsp"),
                Ingredient(name="Almond Milk", quantity=120, unit="ml"),
            ],
        )
    ],
    prep_time=5,
    cook_time=0,
    servings=1,
)

green_smoothie = Recipe(
    name="Green Smoothie",
    components=[
        RecipeComponent(
            name="Smoothie",
            ingredients=[
                Ingredient(name="Spinach", quantity=2, unit="cup"),
                Ingredient(name="Banana", quantity=1, unit="each"),
                Ingredient(
                    name="Protein Powder",
                    quantity=1,
                    unit="packet",
                    equivalent_quantity=30,
                    equivalent_unit="g",
                ),
                Ingredient(name="Almond Milk", quantity=240, unit="ml"),
            ],
        )
    ],
    prep_time=5,
    cook_time=0,
    servings=1,
)

power_bowl = Recipe(
    name="Quinoa Power Bowl",
    components=[
        RecipeComponent(
            name="Grain Base",
            ingredients=[
                Ingredient(name="Quinoa", quantity=200, unit="g"),
                Ingredient(name="Vegetable Broth", quantity=2, unit="cup"),
            ],
        ),
        RecipeComponent(
            name="Roasted Vegetables",
            ingredients=[
                Ingredient(name="Sweet Potato", quantity=2, unit="each"),
                Ingredient(name="Olive Oil", quantity=2, unit="tbsp"),
                Ingredient(
                    name="Salt", quantity=1, unit="tsp", require_tags=["sea salt"]
                ),
            ],
        ),
        RecipeComponent(
            name="Lemon Tahini Dressing",
            ingredients=[
                Ingredient(name="Tahini", quantity=3, unit="tbsp"),
                Ingredient(name="Lemon Juice", quantity=2, unit="tbsp"),
                Ingredient(name="Garlic", quantity=1, unit="clove"),
            ],
        ),
    ],
    prep_time=15,
    cook_time=20,
    servings=None,
)

# ── Grocery prices ─────────────────────────────────────────────────────

purchases = [
    Purchase(name="Rolled Oats", quantity=1000, unit="g", price=Decimal("3.49")),
    Purchase(name="Greek Yogurt", quantity=500, unit="g", price=Decimal("4.49")),
    Purchase(name="Honey", quantity=340, unit="g", price=Decimal("5.99")),
    Purchase(name="Chia Seeds", quantity=200, unit="g", price=Decimal("4.99")),
    Purchase(name="Almond Milk", quantity=946, unit="ml", price=Decimal("3.29")),
    Purchase(name="Spinach", quantity=150, unit="g", price=Decimal("3.99")),
    Purchase(name="Banana", quantity=1, unit="each", price=Decimal("0.29")),
    Purchase(name="Protein Powder", quantity=500, unit="g", price=Decimal("24.99")),
    Purchase(name="Quinoa", quantity=500, unit="g", price=Decimal("4.99")),
    Purchase(name="Vegetable Broth", quantity=946, unit="ml", price=Decimal("2.99")),
    Purchase(name="Sweet Potato", quantity=1, unit="each", price=Decimal("1.25")),
    Purchase(name="Olive Oil", quantity=500, unit="ml", price=Decimal("6.99")),
    Purchase(
        name="Salt",
        quantity=500,
        unit="g",
        price=Decimal("2.99"),
        tags="sea salt",
    ),
    Purchase(name="Tahini", quantity=450, unit="g", price=Decimal("5.99")),
    Purchase(name="Lemon Juice", quantity=473, unit="ml", price=Decimal("2.49")),
    Purchase(name="Garlic", quantity=1, unit="each", price=Decimal("0.50")),
]

# ── Density data for volume↔weight conversions ─────────────────────────

density_data = {
    "volume_weights": {
        "Honey": {"tbsp": 21.0, "tsp": 7.0},
        "Chia Seeds": {"tbsp": 10.0, "tsp": 3.3},
        "Salt": {"tbsp": 18.0, "tsp": 6.0},
        "Tahini": {"tbsp": 15.0, "tsp": 5.0},
    },
}

# ── Plan a production run ──────────────────────────────────────────────

session = ProductionRun(
    date=date(2026, 6, 20),
    production=[
        ProductionItem(assembly="Overnight Oats", quantity=3),
        ProductionItem(assembly="Green Smoothie", quantity=2),
        ProductionItem(assembly="Quinoa Power Bowl", quantity=1),
    ],
    target_dates=[date(2026, 6, 20)],
)

recipes = [overnight_oats, green_smoothie, power_bowl]

# ── Generate shopping list ─────────────────────────────────────────────

shopping = generate_shopping_list(session, recipes)
grouped = group_shopping_items(
    shopping.all_items,
    category_rules=DEFAULT_CATEGORY_RULES,
)

# ── Enrich with costs ──────────────────────────────────────────────────

costs = calculate_shopping_list_cost(shopping, purchases, density_data=density_data)

# ── Display ────────────────────────────────────────────────────────────

width = 62
divider = "-" * width

print()
print("Shopping List".center(width))
print(divider)
print(f"  Date: {shopping.date}")
print(f"  Making: {', '.join(shopping.production_summary)}")
print()

for group in grouped:
    header = f"  {group.group_name}  "
    print(f" {header:-<{width}}")
    for item in group.items:
        tags = f" [{', '.join(item.tags)}]" if item.tags else ""
        qty = f"{item.quantity:g} {item.unit}"
        print(f"  {item.name:<24s} {qty:>12s}{tags}")
    print()

print(divider)

# ── Cost summary ───────────────────────────────────────────────────────

total = Decimal("0")
for c in costs:
    if c.total_cost is not None:
        total += c.total_cost

print(f"  {'Estimated total:':<36s} ${total:.2f}")
print()

# ── Top cost drivers ──────────────────────────────────────────────────

menu = analyze_menu(
    [
        ProductionItem(assembly="Overnight Oats", quantity=3),
        ProductionItem(assembly="Green Smoothie", quantity=2),
        ProductionItem(assembly="Quinoa Power Bowl", quantity=1),
    ],
    recipes,
    purchases,
    density_data=density_data,
    date=date(2026, 6, 20),
)

print("  Top cost drivers")
for i, item in enumerate(menu.top_drivers[:5], 1):
    pct = menu.cost_share(item)
    print(f"  {i}. {item.item.name:<22s} ${item.total_cost:>6.2f}  ({pct:.0%})")

print(divider)
print()

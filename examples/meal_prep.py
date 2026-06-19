"""Meal prep planner — weekly schedule to grocery list + macros.

A 5-day work-week plan with two cook sessions (Sunday + Wednesday).
Composes wright primitives into a custom ``plan_week()`` function.

Usage:
    uv run python examples/meal_prep.py
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from wright import (
    DEFAULT_CATEGORY_RULES,
    Ingredient,
    MacroPerServing,
    ProductionItem,
    ProductionRun,
    Recipe,
    RecipeComponent,
    RecipeMacros,
    calculate_recipe_macros,
    format_quantity,
    generate_shopping_list,
    group_shopping_items,
)

# ── Density data (volume → grams) ─────────────────────────────────────

DENSITY = {
    "liquids": {
        "Almond Milk": 1.03,
        "Lemon Juice": 1.03,
        "Olive Oil": 0.91,
        "Vegetable Broth": 1.0,
    },
    "volume_weights": {
        "Chia Seeds": {"tbsp": 10.0, "tsp": 3.3},
        "Honey": {"tbsp": 21.0, "tsp": 7.0},
        "Salt": {"tbsp": 18.0, "tsp": 6.0},
        "Spinach": {"cup": 30.0},
        "Tahini": {"tbsp": 15.0, "tsp": 5.0},
    },
}

# ── 5 recipes: 2 breakfasts, 1 lunch, 2 dinners ───────────────────────

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
                Ingredient(name="Salt", quantity=1, unit="tsp"),
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
    servings=1,
)

lemon_chicken = Recipe(
    name="Grilled Lemon Chicken & Sweet Potato",
    components=[
        RecipeComponent(
            name="Protein",
            ingredients=[
                Ingredient(name="Chicken Breast", quantity=200, unit="g"),
                Ingredient(name="Lemon Juice", quantity=1, unit="tbsp"),
                Ingredient(name="Garlic", quantity=1, unit="clove"),
                Ingredient(name="Olive Oil", quantity=1, unit="tbsp"),
                Ingredient(name="Salt", quantity=0.5, unit="tsp"),
            ],
        ),
        RecipeComponent(
            name="Side",
            ingredients=[
                Ingredient(name="Sweet Potato", quantity=1, unit="each"),
            ],
        ),
    ],
    prep_time=10,
    cook_time=25,
    servings=1,
)

chickpea_bowl = Recipe(
    name="Quinoa Chickpea Bowl",
    components=[
        RecipeComponent(
            name="Base",
            ingredients=[
                Ingredient(name="Quinoa", quantity=100, unit="g"),
                Ingredient(name="Chickpeas", quantity=240, unit="g"),
            ],
        ),
        RecipeComponent(
            name="Greens",
            ingredients=[
                Ingredient(name="Spinach", quantity=2, unit="cup"),
                Ingredient(name="Tahini", quantity=2, unit="tbsp"),
                Ingredient(name="Lemon Juice", quantity=1, unit="tbsp"),
            ],
        ),
    ],
    prep_time=10,
    cook_time=20,
    servings=1,
)

# ── Nutrition registry (per 100g values) ───────────────────────────────

NUTRITION: dict[str, tuple[float, float, float, float, float]] = {
    "Rolled Oats": (13.5, 66.3, 6.5, 10.6, 389),
    "Greek Yogurt": (10.0, 3.6, 0.7, 0.0, 59),
    "Honey": (0.3, 82.4, 0.0, 0.0, 304),
    "Chia Seeds": (16.5, 42.1, 30.7, 34.4, 486),
    "Almond Milk": (0.4, 0.3, 1.5, 0.0, 17),
    "Spinach": (2.9, 3.6, 0.4, 2.2, 23),
    "Banana": (1.1, 22.8, 0.3, 2.6, 89),
    "Protein Powder": (80.0, 8.0, 5.0, 0.0, 400),
    "Quinoa": (14.1, 64.2, 6.1, 7.0, 368),
    "Vegetable Broth": (0.4, 1.0, 0.1, 0.0, 6),
    "Sweet Potato": (1.6, 20.1, 0.1, 3.0, 86),
    "Olive Oil": (0.0, 0.0, 100.0, 0.0, 884),
    "Salt": (0.0, 0.0, 0.0, 0.0, 0),
    "Tahini": (17.0, 21.2, 53.8, 9.2, 595),
    "Lemon Juice": (0.4, 3.2, 0.0, 0.1, 12),
    "Garlic": (6.4, 33.1, 0.5, 2.1, 149),
    "Chicken Breast": (31.0, 0.0, 3.6, 0.0, 165),
    "Chickpeas": (7.0, 27.4, 2.6, 7.6, 164),
}


def _nutrition_lookup(name: str):
    """Callback for calculate_recipe_macros — inline nutrition lookup."""
    from wright import NutritionInfo

    data = NUTRITION.get(name)
    if data is None:
        return None
    return NutritionInfo(
        protein_g=data[0],
        carbs_g=data[1],
        fat_g=data[2],
        fiber_g=data[3],
        kcal=data[4],
    )


# ── Week plan ──────────────────────────────────────────────────────────

# Schedule: (recipe_name, quantity_per_meal, slot)
SCHEDULE = {
    "Monday": [
        ("Overnight Oats", 1, "breakfast"),
        ("Quinoa Power Bowl", 1, "lunch"),
        ("Grilled Lemon Chicken & Sweet Potato", 1, "dinner"),
    ],
    "Tuesday": [
        ("Green Smoothie", 1, "breakfast"),
        ("Quinoa Power Bowl", 1, "lunch"),
        ("Grilled Lemon Chicken & Sweet Potato", 1, "dinner"),
    ],
    "Wednesday": [
        ("Overnight Oats", 1, "breakfast"),
        ("Quinoa Power Bowl", 1, "lunch"),
        ("Grilled Lemon Chicken & Sweet Potato", 1, "dinner"),
    ],
    "Thursday": [
        ("Overnight Oats", 1, "breakfast"),
        ("Quinoa Power Bowl", 1, "lunch"),
        ("Quinoa Chickpea Bowl", 1, "dinner"),
    ],
    "Friday": [
        ("Green Smoothie", 1, "breakfast"),
        ("Quinoa Power Bowl", 1, "lunch"),
        ("Quinoa Chickpea Bowl", 1, "dinner"),
    ],
}

RECIPES = {
    "Overnight Oats": overnight_oats,
    "Green Smoothie": green_smoothie,
    "Quinoa Power Bowl": power_bowl,
    "Grilled Lemon Chicken & Sweet Potato": lemon_chicken,
    "Quinoa Chickpea Bowl": chickpea_bowl,
}


@dataclass
class WeekPlan:
    """Output of plan_week()."""

    cook_sessions: list[tuple[str, ProductionRun]]
    """Labeled cook sessions (e.g. 'Sunday (Mon–Wed)')."""

    shopping_list: list  # ShoppingList
    """Consolidated grocery list for the full week."""

    daily_macros: dict[str, MacroPerServing]
    """Per-day macro totals keyed by weekday."""

    per_recipe: dict[str, RecipeMacros]
    """Per-recipe macro breakdown."""

    recipe_names: list[str] = field(default_factory=list)
    """Ordered recipe names for display."""


def plan_week(
    schedule: dict[str, list[tuple[str, float, str]]],
    recipes: dict[str, Recipe],
) -> WeekPlan:
    """Plan a week of meals — cook sessions, grocery list, daily macros.

    Groups days into two cook sessions (Sun + Wed), aggregates grocery
    items across all batches, and computes per-day + per-recipe macros.
    """
    sun_items: dict[str, float] = defaultdict(float)
    wed_items: dict[str, float] = defaultdict(float)

    mon_to_wed = {"Monday", "Tuesday", "Wednesday"}

    for day, meals in schedule.items():
        target = sun_items if day in mon_to_wed else wed_items
        for name, qty, _slot in meals:
            target[name] += qty

    # Build cook sessions
    sun_production = [
        ProductionItem(assembly=name, quantity=qty)
        for name, qty in sorted(sun_items.items())
    ]
    wed_production = [
        ProductionItem(assembly=name, quantity=qty)
        for name, qty in sorted(wed_items.items())
    ]

    sun_run = ProductionRun(
        date=date(2026, 6, 15),
        production=sun_production,
        target_dates=[date(2026, 6, 15), date(2026, 6, 17)],
    )
    wed_run = ProductionRun(
        date=date(2026, 6, 17),
        production=wed_production,
        target_dates=[date(2026, 6, 17), date(2026, 6, 19)],
    )

    # Combined grocery list (buy everything on Sunday)
    all_quantities: dict[str, float] = defaultdict(float)
    for name, qty in sun_items.items():
        all_quantities[name] += qty
    for name, qty in wed_items.items():
        all_quantities[name] += qty

    combined_production = [
        ProductionItem(assembly=name, quantity=qty)
        for name, qty in sorted(all_quantities.items())
    ]
    combined_run = ProductionRun(
        date=date(2026, 6, 15),
        production=combined_production,
        target_dates=[
            date(2026, 6, 15),
            date(2026, 6, 16),
            date(2026, 6, 17),
            date(2026, 6, 18),
            date(2026, 6, 19),
        ],
    )
    shopping = generate_shopping_list(combined_run, list(recipes.values()))

    # Per-recipe macros (ordered by first appearance in the week)
    recipe_set: dict[str, RecipeMacros] = {}
    recipe_order: list[str] = []
    seen: set[str] = set()
    for day in schedule:
        for name, _, _ in schedule[day]:
            if name not in seen:
                recipe_set[name] = calculate_recipe_macros(
                    recipes[name],
                    ingredient_nutrition_lookup=_nutrition_lookup,
                    density_data=DENSITY,
                )
                recipe_order.append(name)
                seen.add(name)

    # Daily macros — MacroPerServing supports + and *, so we can sum cleanly
    daily: dict[str, MacroPerServing] = {}
    for day, meals in schedule.items():
        daily[day] = sum(
            (recipe_set[name].total * qty for name, qty, _ in meals),
            start=MacroPerServing.zero(),
        )

    return WeekPlan(
        cook_sessions=[
            ("Sunday (Mon–Wed)", sun_run),
            ("Wednesday (Thu–Fri)", wed_run),
        ],
        shopping_list=shopping,
        daily_macros=daily,
        per_recipe=recipe_set,
        recipe_names=recipe_order,
    )


# ── Display ────────────────────────────────────────────────────────────

W = 68
DIV = "─" * W


def _prod_summary(run: ProductionRun) -> str:
    return ", ".join(
        f"{format_quantity(i.quantity)}× {i.assembly}" for i in run.production
    )


def main() -> None:
    plan = plan_week(SCHEDULE, RECIPES)
    grouped = group_shopping_items(
        plan.shopping_list.all_items,
        category_rules=DEFAULT_CATEGORY_RULES,
    )

    print()
    print("Weekly Meal Plan".center(W))
    print(DIV)

    for label, session in plan.cook_sessions:
        print(f"  {label}")
        print(f"    {_prod_summary(session)}")
    print(DIV)

    # Grocery list
    print()
    print("  Grocery List (buy Sunday morning)")
    print()
    for group in grouped:
        header = f"  {group.group_name}  "
        print(f" {header:-<{W - 2}}")
        for item in group.items:
            tags = f" [{', '.join(item.tags)}]" if item.tags else ""
            qty = f"{item.quantity:g} {item.unit}"
            print(f"    {item.name:<26s} {qty:>12s}{tags}")
        print()
    print(DIV)

    # Daily macros
    print()
    print("  Daily Macros")
    print(f"  {'':->6} {'Protein':>8} {'Carbs':>7} {'Fat':>7} {'Fiber':>7} {'Kcal':>7}")
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    for day in days:
        m = plan.daily_macros[day]
        print(
            f"  {day:<6s} "
            f"{m.protein_g:>7.0f}g "
            f"{m.carbs_g:>6.0f}g "
            f"{m.fat_g:>6.0f}g "
            f"{m.fiber_g:>6.0f}g "
            f"{m.kcal:>7.0f}"
        )
    print()
    print(DIV)

    # Per-recipe breakdown
    # Determine meal slot for each recipe
    slot_of: dict[str, str] = {}
    for day_m in SCHEDULE.values():
        for name, _, slot in day_m:
            slot_of[name] = slot

    print()
    print("  Per Recipe")
    print(f"  {'Recipe':<35s} {'serves':>6}  {'protein':>7} {'kcal':>6}  slot")
    for name in plan.recipe_names:
        rmac = plan.per_recipe[name]
        sv = rmac.servings_used or 1
        slot = slot_of.get(name, "")
        print(
            f"  {name:<35s} {sv:>6d}  "
            f"{rmac.total.protein_g:>6.0f}g "
            f"{rmac.total.kcal:>6.0f}  "
            f"{slot}"
        )
    print(DIV)
    print()


if __name__ == "__main__":
    main()

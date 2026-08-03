"""Macro tracking with Wright — hitting your protein goals all week.

This example shows how ``numeric_attrs`` lets you carry macronutrient
data through wright's matching and shopping list pipeline, then
compare your weekly meal plan against a macro goal.

Prerequisites (not included in wright's dependencies):
    ``pip install requests``  — for the USDA FoodData Central API.

You can skip the USDA step and set ``numeric_attrs`` manually instead.
"""

from __future__ import annotations

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
    cheapest_picker,
    convert_ingredient_to_grams,
    find_matching_purchases,
    generate_shopping_list,
)

# ── 0. Optional: fetch per-100g macros from the USDA ─────────────────────────

USDA_API_KEY = "DEMO_KEY"  # get a free API key at fdc.nal.usda.gov
NUTRIENT_IDS: dict[str, int] = {
    "protein_g": 1003,
    "fat_g": 1004,
    "carbs_g": 1005,
    "kcal": 1008,
}


def enrich_from_usda(purchase: Purchase) -> Purchase:
    """Look up macros from USDA FoodData Central and store on numeric_attrs."""
    import requests

    resp = requests.get(
        "https://api.nal.usda.gov/fdc/v1/foods/search",
        params={
            "query": purchase.name,
            "api_key": USDA_API_KEY,
            "pageSize": 1,
            "dataType": "Foundation,SR Legacy",
        },
    )
    foods = resp.json().get("foods", [])
    if not foods:
        return purchase
    nutrients = {n["nutrientId"]: n["value"] for n in foods[0].get("foodNutrients", [])}
    purchase.numeric_attrs = {
        key: nutrients.get(nid, 0.0) for key, nid in NUTRIENT_IDS.items()
    }
    return purchase


# ── 1. Purchases with macronutrient metadata ─────────────────────────────────

purchases = [
    enrich_from_usda(
        Purchase(
            name="Chicken Breast",
            quantity=1,
            unit="lb",
            price=Decimal("5.99"),
            store="Ingles",
        )
    ),
    enrich_from_usda(
        Purchase(
            name="Brown Rice",
            quantity=2,
            unit="lb",
            price=Decimal("2.49"),
            store="Ingles",
        )
    ),
    enrich_from_usda(
        Purchase(
            name="Broccoli",
            quantity=1,
            unit="lb",
            price=Decimal("1.99"),
            store="Ingles",
        )
    ),
    enrich_from_usda(
        Purchase(
            name="Rolled Oats",
            quantity=2,
            unit="lb",
            price=Decimal("3.49"),
            store="Ingles",
        )
    ),
    enrich_from_usda(
        Purchase(
            name="Greek Yogurt",
            quantity=32,
            unit="oz",
            price=Decimal("5.99"),
            store="Ingles",
        )
    ),
    enrich_from_usda(
        Purchase(
            name="Banana", quantity=1, unit="lb", price=Decimal("0.69"), store="Ingles"
        )
    ),
    enrich_from_usda(
        Purchase(
            name="Whole Milk",
            quantity=1,
            unit="gallon",
            price=Decimal("3.99"),
            store="Ingles",
        )
    ),
    enrich_from_usda(
        Purchase(
            name="Honey", quantity=12, unit="oz", price=Decimal("7.99"), store="Ingles"
        )
    ),
    enrich_from_usda(
        Purchase(
            name="Almonds", quantity=1, unit="lb", price=Decimal("8.99"), store="Ingles"
        )
    ),
]

# ── 2. Define your recipes ──────────────────────────────────────────────────

chicken_and_rice = Recipe(
    name="Chicken & Rice Bowl",
    components=[
        RecipeComponent(
            name="Bowl",
            ingredients=[
                Ingredient(name="Chicken Breast", quantity=200, unit="g"),
                Ingredient(name="Brown Rice", quantity=150, unit="g"),
                Ingredient(name="Broccoli", quantity=100, unit="g"),
            ],
        )
    ],
    prep_time=10,
    cook_time=20,
    servings=1,
)

morning_oats = Recipe(
    name="Morning Oats",
    components=[
        RecipeComponent(
            name="Oats",
            ingredients=[
                Ingredient(name="Rolled Oats", quantity=80, unit="g"),
                Ingredient(name="Greek Yogurt", quantity=100, unit="g"),
                Ingredient(name="Banana", quantity=100, unit="g"),
                Ingredient(name="Honey", quantity=15, unit="g"),
                Ingredient(name="Almonds", quantity=15, unit="g"),
                Ingredient(name="Whole Milk", quantity=200, unit="ml"),
            ],
        )
    ],
    prep_time=5,
    cook_time=0,
    servings=1,
)

# ── 3. Helper: compute macros for a single ingredient ───────────────────────


def ingredient_macros(ingredient: Ingredient) -> dict[str, float]:
    """Scale a purchase's per-100g macros to the recipe quantity."""
    try:
        matches = find_matching_purchases(ingredient, purchases)
    except Exception:
        return {}
    purchase = cheapest_picker(ingredient, matches)
    if purchase is None:
        return {}
    per_100g = getattr(purchase, "numeric_attrs", {})
    if not per_100g:
        return {}
    qty_g = convert_ingredient_to_grams(
        ingredient, raise_on_error=False, density_data={}
    )
    if qty_g <= 0:
        return {}
    factor = qty_g / 100
    return {k: round(v * factor, 1) for k, v in per_100g.items()}


def recipe_macros(recipe: Recipe) -> dict[str, float]:
    """Sum macro contributions across all ingredients in a recipe."""
    totals: dict[str, float] = {}
    for ingredient in recipe.all_ingredients:
        for k, v in ingredient_macros(ingredient).items():
            totals[k] = round(totals.get(k, 0.0) + v, 1)
    return totals


# ── 4. Calculate macros per recipe ──────────────────────────────────────────

for recipe in [morning_oats, chicken_and_rice]:
    macros = recipe_macros(recipe)
    print(f"\n{recipe.name} (per serving):")
    for k in ["kcal", "protein_g", "carbs_g", "fat_g"]:
        print(f"  {k}: {macros.get(k, 0.0)}")
# Expected output (approx):
#   Morning Oats (per serving):
#     kcal: 450.0  protein_g: 22.0  carbs_g: 65.0  fat_g: 12.0
#   Chicken & Rice Bowl (per serving):
#     kcal: 550.0  protein_g: 46.0  carbs_g: 55.0  fat_g: 15.0

# ── 5. Weekly meal plan — hitting a macro goal ──────────────────────────────

# Daily macro goal (e.g., for a 180 lb moderately active person)
GOAL = {"kcal": 2500, "protein_g": 150, "carbs_g": 250, "fat_g": 80}

MENU = [
    ProductionItem(assembly="Morning Oats", quantity=1),  # breakfast
    ProductionItem(assembly="Chicken & Rice Bowl", quantity=1),  # lunch
    ProductionItem(assembly="Chicken & Rice Bowl", quantity=1),  # dinner
]

daily_total: dict[str, float] = {}
for item in MENU:
    recipe = {"Morning Oats": morning_oats, "Chicken & Rice Bowl": chicken_and_rice}[
        item.assembly
    ]
    for k, v in recipe_macros(recipe).items():
        daily_total[k] = round(daily_total.get(k, 0.0) + v * item.quantity, 1)

print(f"\n{'Daily total':20} {'Goal':>8} {'%':>6}")
for k in ["kcal", "protein_g", "carbs_g", "fat_g"]:
    actual = daily_total.get(k, 0)
    goal = GOAL.get(k, 1)
    pct = round(actual / goal * 100, 1) if goal else 0
    print(f"{k:20} {actual:>8.1f} {goal:>8} {pct:>5.1f}%")

# ── 6. Shopping list carries macro data through ─────────────────────────────

week_session = ProductionRun(
    date=date(2026, 7, 20),
    production=[
        ProductionItem(assembly="Morning Oats", quantity=7),
        ProductionItem(assembly="Chicken & Rice Bowl", quantity=14),
    ],
    target_dates=[date(2026, 7, 20)],
)


def merge_sum(
    accumulated: dict[str, float],
    incoming: dict[str, float],
) -> dict[str, float]:
    """Sum numeric attrs when same-name ingredients are merged."""
    return {k: accumulated.get(k, 0.0) + v for k, v in incoming.items()}


shopping = generate_shopping_list(
    week_session,
    [morning_oats, chicken_and_rice],
    category_rules=DEFAULT_CATEGORY_RULES,
    merge_numeric=merge_sum,
)

print("\n── Weekly shopping list (macros per item) ──")
for group in shopping.groups:
    print(f"\n  {group.group_name}:")
    for item in sorted(group.items, key=lambda i: i.name):
        p = item.numeric_attrs.get("protein_g", 0)
        c = item.numeric_attrs.get("carbs_g", 0)
        f = item.numeric_attrs.get("fat_g", 0)
        print(
            f"    {item.name:<20} {item.quantity:>6.1f} {item.unit:<6}"
            f"  P:{p:>5.1f}g  C:{c:>5.1f}g  F:{f:>5.1f}g"
        )

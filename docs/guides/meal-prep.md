# Meal Prep

A 5-day work-week planner — define recipes, schedule your week, and generate
a consolidated grocery list with daily macro totals.  All built on wright
primitives composed into a custom `plan_week()` function.

[`examples/meal_prep.py`](https://github.com/3pm-baking/wright/blob/e25becf/examples/meal_prep.py)
— full runnable script.

## Scenario

You cook **Sunday** and **Wednesday** evenings.  Breakfast alternates between
overnight oats and a green smoothie.  Lunch is a quinoa power bowl every day.
Dinner is grilled lemon chicken Mon–Wed, then a chickpea bowl Thu–Fri.

## 1. Define your recipes

Five recipes: two breakfasts, one lunch, two dinners.  Each is a single serving
— scale batch sizes in the schedule.

```python
from wright import Recipe, Ingredient, RecipeComponent

overnight_oats = Recipe(
    name="Overnight Oats",
    components=[RecipeComponent(name="Base", ingredients=[
        Ingredient(name="Rolled Oats", quantity=50, unit="g"),
        Ingredient(name="Greek Yogurt", quantity=100, unit="g"),
        Ingredient(name="Honey", quantity=1, unit="tbsp"),
        Ingredient(name="Chia Seeds", quantity=1, unit="tbsp"),
        Ingredient(name="Almond Milk", quantity=120, unit="ml"),
    ])],
    prep_time=5, cook_time=0, servings=1,
)

lemon_chicken = Recipe(
    name="Grilled Lemon Chicken & Sweet Potato",
    components=[
        RecipeComponent(name="Protein", ingredients=[
            Ingredient(name="Chicken Breast", quantity=200, unit="g"),
            Ingredient(name="Lemon Juice", quantity=1, unit="tbsp"),
            Ingredient(name="Garlic", quantity=1, unit="clove"),
            Ingredient(name="Olive Oil", quantity=1, unit="tbsp"),
            Ingredient(name="Salt", quantity=0.5, unit="tsp"),
        ]),
        RecipeComponent(name="Side", ingredients=[
            Ingredient(name="Sweet Potato", quantity=1, unit="each"),
        ]),
    ],
    prep_time=10, cook_time=25, servings=1,
)

# ... green smoothie, quinoa power bowl, chickpea bowl
```

See the [full script](https://github.com/3pm-baking/wright/blob/e25becf/examples/meal_prep.py)
for all five.

## 2. Set your weekly schedule

A dict of weekday → list of `(recipe_name, quantity, slot)`:

```python
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
```

## 3. Build `plan_week()` — compose wright primitives

No new library code.  Everything delegates to wright:

- **Cook sessions** — aggregate Mon–Wed and Thu–Fri into two `ProductionRun` objects.
- **Grocery list** — combine both sessions into a single `generate_shopping_list()` call
  (you buy everything Sunday morning).
- **Macros** — `calculate_recipe_macros()` per recipe, then sum per day.

```python
from collections import defaultdict
from datetime import date
from wright import (
    ProductionItem, ProductionRun, MacroPerServing,
    generate_shopping_list, calculate_recipe_macros,
)

def plan_week(schedule, recipes):
    sun_items, wed_items = defaultdict(float), defaultdict(float)
    for day, meals in schedule.items():
        target = sun_items if day in ("Monday", "Tuesday", "Wednesday") else wed_items
        for name, qty, _slot in meals:
            target[name] += qty

    # Two cook sessions
    sun_run = ProductionRun(
        date=date(2026, 6, 15),
        production=[ProductionItem(assembly=n, quantity=q)
                    for n, q in sorted(sun_items.items())],
        target_dates=[date(2026, 6, 15), date(2026, 6, 17)],
    )
    wed_run = ProductionRun(
        date=date(2026, 6, 17),
        production=[ProductionItem(assembly=n, quantity=q)
                    for n, q in sorted(wed_items.items())],
        target_dates=[date(2026, 6, 17), date(2026, 6, 19)],
    )

    # Single grocery list — buy everything Sunday
    all_qty = defaultdict(float, sun_items)
    for k, v in wed_items.items():
        all_qty[k] += v
    combined = ProductionRun(
        date=date(2026, 6, 15),
        production=[ProductionItem(assembly=n, quantity=q)
                    for n, q in sorted(all_qty.items())],
        target_dates=[
            date(2026, 6, d) for d in range(15, 20)
        ],
    )
    shopping = generate_shopping_list(combined, recipes)

    # Per-recipe macros (uses a nutrition lookup callback)
    recipe_macros = {
        name: calculate_recipe_macros(
            recipes[name],
            ingredient_nutrition_lookup=my_nutrition_lookup,
            density_data=my_density_data,
        )
        for name in sorted(all_qty.keys())
    }

    # Daily macros — MacroPerServing supports + and * for clean aggregation
    daily = {}
    for day, meals in schedule.items():
        daily[day] = sum(
            (recipe_macros[name].total * qty for name, qty, _ in meals),
            start=MacroPerServing.zero(),
        )

    return {
        "sessions": [("Sunday (Mon–Wed)", sun_run), ("Wednesday (Thu–Fri)", wed_run)],
        "shopping": shopping,
        "daily_macros": daily,
        "per_recipe": recipe_macros,
    }
```

## 4. Output

Run `plan_week(SCHEDULE, RECIPES)` and display:

```
Weekly Meal Plan
────────────────────────────────────────────────────────────────────
  Sunday (Mon–Wed)
    1× Green Smoothie, 3× Grilled Lemon Chicken, 2× Overnight Oats, 3× Quinoa Power Bowl
  Wednesday (Thu–Fri)
    1× Green Smoothie, 1× Overnight Oats, 2× Quinoa Chickpea Bowl, 2× Quinoa Power Bowl

  Grocery List (buy Sunday morning)
   Dairy & Eggs  ────────────────────   Meat  ───────
    Greek Yogurt           300 g         Chicken Breast    600 g
    Almond Milk         28.4 floz
                                        Produce  ────
   Dry Goods  ──────────────────────    Banana           2 each
    Protein Powder          30 g         Spinach         2 quart
    Salt                  2.2 tbsp       Garlic          8 clove
                                        Sweet Potato   13 each
   Pantry  ────────────────────────
    Honey                   3 tbsp       ... etc ...
    Lemon Juice            15 tbsp

  Daily Macros
            Protein  Carbs   Fat   Fiber   Kcal
   Monday     119g    203g    93g    27g   2112
   Tuesday    127g    149g    90g    20g   1900
   Wednesday  119g    203g    93g    27g   2112
   Thursday    95g    341g   101g    56g   2616
   Friday     102g    288g    98g    49g   2405

  Per Recipe
   Recipe                            serves  protein   kcal  slot
   Overnight Oats                         1      19g    387  breakfast
   Quinoa Power Bowl                      1      38g   1274  lunch
   Grilled Lemon Chicken                  1      62g    451  dinner
   Green Smoothie                         1      27g    176  breakfast
   Quinoa Chickpea Bowl                   1      38g    956  dinner
```

## What you get

- **Two cook sessions** scheduled for Sunday and Wednesday.
- **One grocery trip** — consolidated shopping list grouped by store aisle
  (`DEFAULT_CATEGORY_RULES`).
- **Daily macro breakdown** — protein, carbs, fat, fiber, and calories per day.
- **Per-recipe reference** — macros and serving count for each recipe.

## Making it your own

- **Swap recipes** — replace any recipe in the schedule dict.
- **Change batch sizes** — adjust the quantity per meal (e.g. `("Overnight Oats", 2, "breakfast")`).
- **Add more cook days** — extend the `mon_to_wed` set to three or four cook sessions.
- **Add costs** — pipe the shopping list through `calculate_shopping_list_cost()` to get
  per-item and total costs (see the [grocery list example](examples.md#grocery-list)).
- **Custom categories** — pass your own `CategoryRule` list to `group_shopping_items()`
  for a store layout that matches where you shop.
- **Different nutrition sources** — swap the inline lookup table for
  `load_nutrition_registry("nutrients.yaml")` or a USDA API callback.

## How it fits together

```
schedule dict                 recipes dict
     │                              │
     └────────── plan_week() ───────┘
                    │
         ┌─────────┼─────────┐
         ▼         ▼         ▼
   ProductionRun   macros    shopping
  (2 cook sessions)          list
         │                    │
         ▼                    ▼
   daily macros      grouped by aisle
  (MacroPerServing)  (IngredientGroup[])
```

No new framework.  `plan_week()` is ~80 lines of pure composition on top of wright.
Copy it, tweak it, make it yours.

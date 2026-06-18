"""Basic usage of wright — pure Python, no file I/O required.

This demonstrates creating recipes and grocery items in code, then using
the core library operations on them.  The library functions themselves
are defined in the costing.py, matching.py, etc. modules — this example
just shows the model layer.
"""

from decimal import Decimal

from wright import (
    BaseIngredient,
    BaseRecipe,
    CategoryRule,
    DEFAULT_CATEGORY_RULES,
    NutritionInfo,
    PriceRange,
    RecipeComponent,
    ServingRange,
    SimplePurchase,
    are_compatible,
    calculate_recipe_macros,
    categorize_ingredient,
    parse_quantity,
    ureg,
)

# ── 1. Define a recipe in pure Python ──────────────────────────────────────

recipe = BaseRecipe(
    name="Overnight Oats",
    components=[
        RecipeComponent(
            name="Base Oats",
            ingredients=[
                BaseIngredient(name="Rolled Oats", quantity=50, unit="g"),
                BaseIngredient(name="Greek Yogurt", quantity=100, unit="g"),
                BaseIngredient(name="Honey", quantity=1, unit="tbsp"),
                BaseIngredient(name="Chia Seeds", quantity=1, unit="tbsp"),
                BaseIngredient(name="Almond Milk", quantity=120, unit="ml"),
            ],
        )
    ],
    instructions=["Combine all ingredients in a jar", "Refrigerate overnight"],
    prep_time=5,
    cook_time=0,
    servings=1,  # exact serving count
)

assert recipe.name == "Overnight Oats"
assert len(recipe.all_ingredients) == 5
assert recipe.servings == 1

# ── 2. Scaling ─────────────────────────────────────────────────────────────

doubled = recipe.double()
assert doubled.all_ingredients[0].quantity == 100  # 50 * 2
assert doubled.servings == 2

# ── 3. Serving ranges ──────────────────────────────────────────────────────

power_bowl = BaseRecipe(
    name="Quinoa Power Bowl",
    components=[
        RecipeComponent(
            name="Grain Base",
            ingredients=[
                BaseIngredient(name="Quinoa", quantity=200, unit="g"),
            ],
        )
    ],
    prep_time=15,
    cook_time=20,
    servings=ServingRange(min_servings=2, max_servings=4),
)

rng = power_bowl.servings
assert isinstance(rng, ServingRange)
assert rng.midpoint == 3.0

# ── 4. Unportioned recipes (products/sub-recipes) ──────────────────────────

sugar_recipe = BaseRecipe(
    name="Vanilla Sugar",
    components=[
        RecipeComponent(
            name="Mix",
            ingredients=[
                BaseIngredient(name="Sugar", quantity=200, unit="g"),
                BaseIngredient(name="Vanilla Bean", quantity=1, unit="each"),
            ],
        )
    ],
    prep_time=5,
    cook_time=0,
    servings=None,  # not portioned — only a gram yield
    net_weight_grams=200,
)

assert sugar_recipe.servings is None
assert sugar_recipe.net_weight_grams == 200

# ── 5. PurchasedItem protocol — any class that satisfies it works ────────────


class MyPurchasedItem:
    """A plain class — no Pydantic, no SQLModel, just attributes."""

    def __init__(self, name: str, qty: float, unit: str, price: Decimal):
        self.name = name
        self.tags = ""
        self.quantity = qty
        self.unit = unit
        self.price = price
        self.store = None

    @property
    def tag_set(self) -> set[str]:
        if not self.tags:
            return set()
        return {t.strip().lower() for t in self.tags.split(",") if t.strip()}

    def matches_requirements(self, require_tags: list[str]) -> bool:
        if not require_tags:
            return True
        item_tags = self.tag_set
        return all(tag.lower() in item_tags for tag in require_tags)


oats = MyPurchasedItem("Rolled Oats", 1000, "g", Decimal("3.49"))

# MyPurchasedItem satisfies PurchasedItem protocol for type checkers (mypy, pyright)

# ── 6. SimplePurchase — built-in Pydantic model for convenience ──────────

chia = SimplePurchase(
    name="Chia Seeds",
    quantity=200,
    unit="g",
    price=Decimal("4.99"),
    store="Farmers Market",
)

assert chia.tag_set == set()
assert chia.matches_requirements([]) is True

# Tagged grocery item
salt = SimplePurchase(
    name="Salt",
    tags="sea salt, coarse",
    quantity=500,
    unit="g",
    price=Decimal("2.99"),
)

assert salt.tag_set == {"sea salt", "coarse"}
assert salt.matches_requirements(["sea salt"]) is True
assert salt.matches_requirements(["kosher"]) is False

# ── 7. Unit conversion ─────────────────────────────────────────────────────

qty = parse_quantity(500, "g")
assert are_compatible("g", "oz") is True
assert are_compatible("g", "ml") is False

oz = ureg.Quantity(16, "oz")
grams = oz.to("g")
assert round(float(grams.magnitude)) == 454  # 16 oz ≈ 453.59 g

# ── 8. Ingredient categorization ────────────────────────────────────────────

cat = categorize_ingredient("Rolled Oats")
assert cat is None  # no default rules match — returns None

cat = categorize_ingredient("Spinach")
assert cat is None  # same — no default rules

# Using default rules (US grocery store layout)
cat = categorize_ingredient("Spinach", rules=DEFAULT_CATEGORY_RULES)
assert cat == "Produce"

cat = categorize_ingredient("Greek Yogurt", rules=DEFAULT_CATEGORY_RULES)
assert cat == "Dairy & Eggs"

cat = categorize_ingredient("Olive Oil", rules=DEFAULT_CATEGORY_RULES)
assert cat == "Fats & Oils"

# Custom rules for a different language or store layout
french_rules = [
    CategoryRule(category="Frais", priority=0, keywords=["lait", "beurre", "oeuf"]),
    CategoryRule(category="Sec", priority=1, keywords=["farine", "sucre", "sel"]),
    CategoryRule(category="Legumes", priority=2, keywords=["tomate", "epinard"]),
]

cat = categorize_ingredient("lait", rules=french_rules)
assert cat == "Frais"

cat = categorize_ingredient("farine", rules=french_rules)
assert cat == "Sec"

# ── 9. Macro calculation ─────────────────────────────────────────────────────
# Nutrition data lives in a central registry — not on individual ingredients

nutrition_registry = {
    "Rolled Oats": NutritionInfo(
        protein_g=13.5, carbs_g=66.3, fat_g=6.5, fiber_g=10.6, kcal=389
    ),
    "Greek Yogurt": NutritionInfo(
        protein_g=10.0, carbs_g=3.6, fat_g=0.7, fiber_g=0.0, kcal=59
    ),
}

macro_recipe = BaseRecipe(
    name="Overnight Oats",
    components=[
        RecipeComponent(
            name="Base Oats",
            ingredients=[
                BaseIngredient(name="Rolled Oats", quantity=50, unit="g"),
                BaseIngredient(name="Greek Yogurt", quantity=100, unit="g"),
            ],
        )
    ],
    prep_time=5,
    cook_time=0,
    servings=1,
)

macros = calculate_recipe_macros(macro_recipe, nutrition_registry=nutrition_registry)
assert round(macros.total.protein_g, 1) == 16.8
assert round(macros.total.kcal, 1) == 253.5
assert macros.per_serving is not None
assert macros.per_serving.protein_g == macros.total.protein_g

# ── 10. PriceRange arithmetic ────────────────────────────────────────────────

p1 = PriceRange(min_price=Decimal("2.00"), max_price=Decimal("3.00"))
p2 = PriceRange(min_price=Decimal("1.00"), max_price=Decimal("1.50"))
total = p1 + p2
assert total.min_price == Decimal("3.00")
assert total.max_price == Decimal("4.50")
assert p1.midpoint == Decimal("2.50")

# ── 11. Recipe with product_ref (recursive costing) ────────────────────────

cake_recipe = BaseRecipe(
    name="Lemon Cake",
    components=[
        RecipeComponent(
            name="Cake",
            ingredients=[
                BaseIngredient(name="Flour", quantity=300, unit="g"),
                BaseIngredient(
                    name="Vanilla Sugar",
                    quantity=1,
                    unit="packet",
                    equivalent_quantity=8,
                    equivalent_unit="g",
                    product_ref="vanilla-sugar",  # references another recipe
                ),
            ],
        )
    ],
    prep_time=15,
    cook_time=30,
    servings=8,
)

sugar_ingredient = cake_recipe.all_ingredients[1]
assert sugar_ingredient.product_ref == "vanilla-sugar"
assert sugar_ingredient.equivalent_quantity == 8

print("All assertions passed — wright works!")

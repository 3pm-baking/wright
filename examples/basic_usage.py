"""Basic usage of wright — pure Python, no file I/O required.

This demonstrates creating recipes and grocery items in code, then using
the core library operations on them.  The library functions themselves
are defined in the costing.py, matching.py, etc. modules — this example
just shows the model layer.
"""

from datetime import date
from decimal import Decimal

from wright import (
    DEFAULT_CATEGORY_RULES,
    CategoryRule,
    Component,
    Ingredient,
    Material,
    NutritionInfo,
    PriceRange,
    ProductionItem,
    ProductionRun,
    Purchase,
    Recipe,
    RecipeComponent,
    ServingRange,
    Stock,
    SupplyItem,
    are_compatible,
    calculate_item_costs,
    calculate_recipe_macros,
    categorize_item,
    parse_quantity,
    ureg,
)

# ── 1. Define a recipe in pure Python ──────────────────────────────────────

recipe = Recipe(
    name="Overnight Oats",
    components=[
        RecipeComponent(
            name="Base Oats",
            ingredients=[
                Ingredient(name="Rolled Oats", quantity=50, unit="g"),
                Ingredient(name="Greek Yogurt", quantity=100, unit="g"),
                Ingredient(name="Honey", quantity=1, unit="tbsp"),
                Ingredient(name="Chia Seeds", quantity=1, unit="tbsp"),
                Ingredient(name="Almond Milk", quantity=120, unit="ml"),
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

power_bowl = Recipe(
    name="Quinoa Power Bowl",
    components=[
        RecipeComponent(
            name="Grain Base",
            ingredients=[
                Ingredient(name="Quinoa", quantity=200, unit="g"),
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

sugar_recipe = Recipe(
    name="Vanilla Sugar",
    components=[
        RecipeComponent(
            name="Mix",
            ingredients=[
                Ingredient(name="Sugar", quantity=200, unit="g"),
                Ingredient(name="Vanilla Bean", quantity=1, unit="each"),
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

# ── 6. Purchase — built-in Pydantic model for convenience ──────────

chia = Purchase(
    name="Chia Seeds",
    quantity=200,
    unit="g",
    price=Decimal("4.99"),
    store="Farmers Market",
)

assert chia.tag_set == set()
assert chia.matches_requirements([]) is True

# Tagged grocery item
salt = Purchase(
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

cat = categorize_item("Rolled Oats")
assert cat is None  # no default rules match — returns None

cat = categorize_item("Spinach")
assert cat is None  # same — no default rules

# Using default rules (US grocery store layout)
cat = categorize_item("Spinach", rules=DEFAULT_CATEGORY_RULES)
assert cat == "Produce"

cat = categorize_item("Greek Yogurt", rules=DEFAULT_CATEGORY_RULES)
assert cat == "Dairy & Eggs"

cat = categorize_item("Olive Oil", rules=DEFAULT_CATEGORY_RULES)
assert cat == "Fats & Oils"

# Custom rules for a different language or store layout
french_rules = [
    CategoryRule(category="Frais", priority=0, keywords=["lait", "beurre", "oeuf"]),
    CategoryRule(category="Sec", priority=1, keywords=["farine", "sucre", "sel"]),
    CategoryRule(category="Legumes", priority=2, keywords=["tomate", "epinard"]),
]

cat = categorize_item("lait", rules=french_rules)
assert cat == "Frais"

cat = categorize_item("farine", rules=french_rules)
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

macro_recipe = Recipe(
    name="Overnight Oats",
    components=[
        RecipeComponent(
            name="Base Oats",
            ingredients=[
                Ingredient(name="Rolled Oats", quantity=50, unit="g"),
                Ingredient(name="Greek Yogurt", quantity=100, unit="g"),
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

cake_recipe = Recipe(
    name="Lemon Cake",
    components=[
        RecipeComponent(
            name="Cake",
            ingredients=[
                Ingredient(name="Flour", quantity=300, unit="g"),
                Ingredient(
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

# ── 12. Non-food domains: construction bill-of-materials ──────────────────

# ── Project 1: Build a 10'×12' backyard deck ──────────────────────────────

framing = Component(name="Deck Framing", materials=[
    Material(name="2x6 Pressure-Treated", quantity=48, unit="ft", require_tags=["#2"]),
    Material(name="2x6 Pressure-Treated", quantity=32, unit="ft", require_tags=["#1", "rim-joist"]),
    Material(name="Joist Hangers", quantity=16, unit="each"),
    Material(name="3\" Deck Screws", quantity=400, unit="each"),
])
decking = Component(name="Deck Surface", materials=[
    Material(name="5/4\" Cedar Decking", quantity=160, unit="ft"),
    Material(name="2\" Stainless Screws", quantity=600, unit="each"),
])
footings = Component(name="Concrete Footings", materials=[
    Material(name="Concrete Mix", quantity=8, unit="bag",
             equivalent_quantity=60, equivalent_unit="lb"),
    Material(name="Post Anchor", quantity=6, unit="each"),
])

# ── Project 2: Build a raised garden bed (8'×4'×2') ───────────────────────

garden_frame = Component(name="Garden Bed Frame", materials=[
    Material(name="2x8 Cedar", quantity=24, unit="ft", require_tags=["untreated"]),
    Material(name="4x4 Cedar Post", quantity=8, unit="ft"),
    Material(name="3\" Deck Screws", quantity=64, unit="each"),
])
garden_fill = Component(name="Garden Bed Fill", materials=[
    Material(name="Topsoil", quantity=1, unit="cu yd"),
    Material(name="Compost", quantity=0.5, unit="cu yd"),
])

# ── Pricing data from the hardware store ───────────────────────────────────

hardware_prices: list = [
    Purchase(name="2x6 Pressure-Treated", quantity=8, unit="ft",
             price=Decimal("12.97"), store="Home Depot", tags="#2"),
    Purchase(name="2x6 Pressure-Treated", quantity=8, unit="ft",
             price=Decimal("14.97"), store="Home Depot", tags="rim-joist,#1"),
    Purchase(name="5/4\" Cedar Decking", quantity=8, unit="ft",
             price=Decimal("9.97"), store="Home Depot"),
    Purchase(name="2x8 Cedar", quantity=8, unit="ft",
             price=Decimal("15.47"), store="Home Depot", tags="untreated"),
    Purchase(name="4x4 Cedar Post", quantity=8, unit="ft",
             price=Decimal("23.97"), store="Home Depot"),
    Purchase(name="Joist Hangers", quantity=1, unit="each",
             price=Decimal("2.47"), store="Lowe's"),
    Purchase(name="3\" Deck Screws", quantity=100, unit="each",
             price=Decimal("8.97"), store="Home Depot"),
    Purchase(name="2\" Stainless Screws", quantity=100, unit="each",
             price=Decimal("3.49"), store="Home Depot"),
    Purchase(name="Concrete Mix", quantity=1, unit="bag",
             price=Decimal("4.98"), store="Lowe's"),
    Purchase(name="Post Anchor", quantity=1, unit="each",
             price=Decimal("7.98"), store="Lowe's"),
    Purchase(name="Topsoil", quantity=1, unit="cu yd",
             price=Decimal("35.00"), store="Landscape Supply"),
    Purchase(name="Compost", quantity=1, unit="cu yd",
             price=Decimal("28.00"), store="Landscape Supply"),
]

# ── Cost individual materials per project ──────────────────────────────────

# Cost the deck framing materials
deck_framing_cost = calculate_item_costs(framing.materials, hardware_prices)
deck_framing_total = sum(
    c.total_cost for c in deck_framing_cost if c.total_cost is not None
)
print(f"\nDeck framing cost: ${deck_framing_total}")

# Cost the garden bed materials
garden_frame_cost = calculate_item_costs(garden_frame.materials, hardware_prices)
garden_frame_total = sum(
    c.total_cost for c in garden_frame_cost if c.total_cost is not None
)
print(f"Garden bed frame cost: ${garden_frame_total}")

# ── Generate a consolidated shopping list for both projects ────────────────

all_project_materials = (
    framing.materials
    + decking.materials
    + footings.materials
    + garden_frame.materials
    + garden_fill.materials
)

# Multi-project plan as a production run
weekend_plan = ProductionRun(
    date=date(2026, 6, 20),
    production=[
        ProductionItem(assembly="Backyard Deck", quantity=1),
        ProductionItem(assembly="Raised Garden Bed", quantity=1),
    ],
    target_dates=[date(2026, 6, 20), date(2026, 6, 21)],
)

# Aggregate and cost everything together
all_costs = calculate_item_costs(all_project_materials, hardware_prices)
grand_total = sum(c.total_cost for c in all_costs if c.total_cost is not None)
print(f"Combined materials total: ${grand_total}")

# Show items by cost impact
print("\nTop cost drivers:")
for c in sorted(all_costs, key=lambda x: x.total_cost or Decimal("0"), reverse=True)[:5]:
    if c.total_cost:
        print(f"  {c.item.name}: ${c.total_cost} ({c.store})")

# ── Supply tracking: deduct from stock ─────────────────────────────────────

# Current shop inventory
shop_stock = Stock([
    SupplyItem(name='3" Deck Screws', quantity=500, unit="each"),
    SupplyItem(name="Joist Hangers", quantity=20, unit="each"),
])

# Deduct framing materials — get reduced stock and what's still needed
shop_stock, remaining = shop_stock.use(framing.materials)
needed_names = {r.name for r in remaining}
print(f"\nAfter deducting framing from stock, still need: {needed_names}")
assert "Joist Hangers" not in needed_names  # 20 in stock >= 16 needed
assert "2x6 Pressure-Treated" in needed_names  # not in stock at all

# Now deduct remaining projects from reduced stock
all_materials = (
    decking.materials + garden_frame.materials + footings.materials + garden_fill.materials
)
shop_stock, all_remaining = shop_stock.use(all_materials)
needed_names = {r.name for r in all_remaining}
print(f"After all deductions, still need: {needed_names}")
# 3\" Deck Screws: 400 (deck) + 64 (garden) = 464 needed, 500 in stock = OK
deck_screw_def = next((r for r in all_remaining if r.name == '3" Deck Screws'), None)
assert deck_screw_def is None  # stock covers the 464 needed

# ── Construction-specific categorization ────────────────────────────────────

lumberyard_rules = [
    CategoryRule(category="Lumber", priority=0,
                 keywords=["2x", "5/4", "4x4", "cedar", "lumber", "plywood"]),
    CategoryRule(category="Hardware", priority=1,
                 keywords=["screw", "nail", "bolt", "anchor", "hanger"]),
    CategoryRule(category="Concrete & Masonry", priority=2,
                 keywords=["concrete", "cement", "mortar"]),
    CategoryRule(category="Landscape", priority=3,
                 keywords=["topsoil", "compost", "mulch", "gravel"]),
]

for mat in all_project_materials[:8]:
    cat = categorize_item(mat.name, rules=lumberyard_rules)
    print(f"  {mat.name} → {cat}")

# Subclass Material for domain-specific metadata (not in the library)
class Lumber(Material):
    grade: str | None = None
    species: str | None = None

stud = Lumber(name="2x4 Stud", quantity=12, unit="ft",
              grade="#2", species="Douglas Fir")
assert isinstance(stud, Material)  # still works everywhere Material is accepted
assert stud.grade == "#2"

print("\nConstruction examples passed")


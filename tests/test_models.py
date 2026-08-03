"""Tests for wright models."""

from __future__ import annotations

from decimal import Decimal

import pytest

from wright.models import (
    Assembly,
    CategoryRule,
    Component,
    Ingredient,
    IngredientCost,
    Material,
    PriceRange,
    Purchase,
    Recipe,
    RecipeComponent,
    RecipeCost,
    ServingRange,
    categorize_item,
)


class TestIngredient:
    def test_create_simple(self):
        ing = Ingredient(name="Sugar", quantity=200, unit="g")
        assert ing.name == "Sugar"
        assert ing.quantity == 200
        assert ing.unit == "g"
        assert ing.require_tags == []
        assert ing.byproduct is False
        assert ing.product_ref is None

    def test_with_tags(self):
        ing = Ingredient(
            name="Butter", quantity=100, unit="g", require_tags=["unsalted"]
        )
        assert ing.require_tags == ["unsalted"]

    def test_scale(self):
        ing = Ingredient(name="Sugar", quantity=200, unit="g")
        scaled = ing.scale(2)
        assert scaled.name == "Sugar"
        assert scaled.quantity == 400
        assert scaled.unit == "g"

    def test_scale_preserves_tags(self):
        ing = Ingredient(
            name="Butter", quantity=100, unit="g", require_tags=["unsalted"]
        )
        scaled = ing.scale(0.5)
        assert scaled.require_tags == ["unsalted"]
        assert scaled.quantity == 50

    def test_equivalent_quantity(self):
        ing = Ingredient(
            name="Vanilla Sugar",
            quantity=1,
            unit="packet",
            equivalent_quantity=8,
            equivalent_unit="g",
        )
        assert ing.equivalent_quantity == 8
        assert ing.equivalent_unit == "g"

    def test_byproduct(self):
        ing = Ingredient(name="Water", quantity=100, unit="ml", byproduct=True)
        assert ing.byproduct is True

    def test_product_ref(self):
        ing = Ingredient(
            name="Vanilla Sugar",
            quantity=1,
            unit="packet",
            equivalent_quantity=8,
            equivalent_unit="g",
            product_ref="vanilla-sugar",
        )
        assert ing.product_ref == "vanilla-sugar"


class TestRecipeComponent:
    def test_create(self):
        comp = RecipeComponent(
            name="Dough",
            ingredients=[
                Ingredient(name="Flour", quantity=300, unit="g"),
                Ingredient(name="Butter", quantity=150, unit="g"),
            ],
        )
        assert comp.name == "Dough"
        assert len(comp.ingredients) == 2

    def test_scale(self):
        comp = RecipeComponent(
            name="Dough",
            ingredients=[Ingredient(name="Flour", quantity=300, unit="g")],
        )
        scaled = comp.scale(2)
        assert scaled.name == "Dough"
        assert scaled.ingredients[0].quantity == 600

    def test_scale_polymorphic(self):
        """Scale should call the most specific scale() method."""
        from wright.models import Ingredient

        class CustomIngredient(Ingredient):
            flavour: str = "plain"

            def scale(self, factor: float):
                return CustomIngredient(
                    name=self.name,
                    quantity=self.quantity * factor,
                    unit=self.unit,
                    flavour=self.flavour,
                )

        comp = RecipeComponent(
            name="Filling",
            ingredients=[
                CustomIngredient(
                    name="Apple", quantity=100, unit="g", flavour="cinnamon"
                )
            ],
        )
        scaled = comp.scale(3)
        assert scaled.ingredients[0].quantity == 300
        assert isinstance(scaled.ingredients[0], CustomIngredient)
        assert scaled.ingredients[0].flavour == "cinnamon"


class TestServingRange:
    def test_create(self):
        sr = ServingRange(min_servings=2, max_servings=6)
        assert sr.min_servings == 2
        assert sr.max_servings == 6

    def test_midpoint(self):
        sr = ServingRange(min_servings=2, max_servings=6)
        assert sr.midpoint == 4.0

    def test_scale(self):
        sr = ServingRange(min_servings=2, max_servings=6)
        scaled = sr.scale(2)
        assert scaled.min_servings == 4
        assert scaled.max_servings == 12

    def test_min_must_be_positive(self):
        with pytest.raises(ValueError):
            ServingRange(min_servings=0, max_servings=4)


class TestRecipe:
    def test_create_minimal(self):
        r = Recipe(name="Bread", components=[], prep_time=10, cook_time=30)
        assert r.name == "Bread"
        assert r.prep_time == 10
        assert r.cook_time == 30
        assert r.servings is None
        assert r.instructions == []

    def test_servings_int(self):
        r = Recipe(name="Cake", components=[], prep_time=10, cook_time=30, servings=8)
        assert r.servings == 8

    def test_servings_range(self):
        r = Recipe(
            name="Cake",
            components=[],
            prep_time=10,
            cook_time=30,
            servings={"min_servings": 6, "max_servings": 10},
        )
        assert isinstance(r.servings, ServingRange)
        assert r.servings.min_servings == 6
        assert r.servings.max_servings == 10

    def test_all_ingredients(self):
        r = Recipe(
            name="Cake",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Flour", quantity=300, unit="g"),
                    ],
                ),
                RecipeComponent(
                    name="Topping",
                    ingredients=[
                        Ingredient(name="Sugar", quantity=100, unit="g"),
                        Ingredient(name="Butter", quantity=50, unit="g"),
                    ],
                ),
            ],
            prep_time=10,
            cook_time=30,
        )
        assert len(r.all_ingredients) == 3

    def test_double(self):
        r = Recipe(
            name="Cake",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[Ingredient(name="Flour", quantity=300, unit="g")],
                )
            ],
            prep_time=10,
            cook_time=30,
            servings=4,
        )
        d = r.double()
        assert d.all_ingredients[0].quantity == 600
        assert d.servings == 8

    def test_size_up_range(self):
        r = Recipe(
            name="Cake",
            components=[],
            prep_time=10,
            cook_time=30,
            servings={"min_servings": 2, "max_servings": 4},
        )
        d = r.size_up(1.5)
        assert isinstance(d.servings, ServingRange)
        assert d.servings.min_servings == 3
        assert d.servings.max_servings == 6

    def test_servings_bounds_none(self):
        r = Recipe(
            name="Product", components=[], prep_time=5, cook_time=0, servings=None
        )
        assert r._servings_bounds() == (1, 1)

    def test_servings_bounds_int(self):
        r = Recipe(name="Cake", components=[], prep_time=5, cook_time=5, servings=6)
        assert r._servings_bounds() == (6, 6)

    def test_servings_bounds_range(self):
        r = Recipe(
            name="Cake",
            components=[],
            prep_time=5,
            cook_time=5,
            servings={"min_servings": 4, "max_servings": 8},
        )
        assert r._servings_bounds() == (4, 8)


class TestNumericAttrsIngredient:
    def test_default_empty(self):
        ing = Ingredient(name="Sugar", quantity=200, unit="g")
        assert ing.numeric_attrs == {}

    def test_set_and_get(self):
        ing = Ingredient(
            name="Chicken",
            quantity=200,
            unit="g",
            numeric_attrs={"protein_g": 62.0, "kcal": 330},
        )
        assert ing.numeric_attrs["protein_g"] == 62.0
        assert ing.numeric_attrs["kcal"] == 330.0

    def test_scale_propagates(self):
        ing = Ingredient(
            name="Chicken", quantity=200, unit="g", numeric_attrs={"protein_g": 62.0}
        )
        scaled = ing.scale(0.5)
        assert scaled.numeric_attrs == {"protein_g": 62.0}
        assert scaled.quantity == 100

    def test_subclass_inherits(self):
        ing = Ingredient(
            name="Milk", quantity=200, unit="ml", numeric_attrs={"protein_g": 6.8}
        )
        assert ing.numeric_attrs["protein_g"] == 6.8


class TestNumericAttrsPurchase:
    def test_default_empty(self):
        g = Purchase(name="Sugar", quantity=1000, unit="g", price=Decimal("2.49"))
        assert g.numeric_attrs == {}

    def test_set_and_get(self):
        g = Purchase(
            name="Chicken Breast",
            quantity=1,
            unit="lb",
            price=Decimal("5.99"),
            numeric_attrs={"protein_g": 31.0, "kcal": 165},
        )
        assert g.numeric_attrs["protein_g"] == 31.0
        assert g.numeric_attrs["kcal"] == 165.0

    def test_macros(self):
        g = Purchase(
            name="Rolled Oats",
            quantity=2,
            unit="lb",
            price=Decimal("3.49"),
            numeric_attrs={
                "protein_g": 13.5,
                "carbs_g": 66.3,
                "fat_g": 6.5,
                "kcal": 375,
            },
        )
        assert g.numeric_attrs["carbs_g"] == 66.3


class TestAssemblyNumericAttrs:
    def test_size_up_preserves(self):
        asm = Assembly(
            name="Brew",
            components=[
                Component(
                    name="Ingredients",
                    materials=[Material(name="Barley", quantity=10, unit="lb")],
                )
            ],
            numeric_attrs={"shelf_life_days": 30},
        )
        scaled = asm.size_up(2)
        assert scaled.numeric_attrs == {"shelf_life_days": 30}

    def test_size_up_scales_materials_keeps_attrs(self):
        asm = Assembly(
            name="Brew",
            components=[
                Component(
                    name="Ingredients",
                    materials=[
                        Material(
                            name="Barley",
                            quantity=10,
                            unit="lb",
                            numeric_attrs={"protein_g": 12.0},
                        )
                    ],
                )
            ],
            numeric_attrs={"shelf_life_days": 30},
        )
        scaled = asm.size_up(2)
        assert scaled.numeric_attrs == {"shelf_life_days": 30}
        assert scaled.components[0].materials[0].quantity == 20
        assert scaled.components[0].materials[0].numeric_attrs == {"protein_g": 12.0}

    def test_recipe_size_up_preserves(self):
        recipe = Recipe(
            name="Cake",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[Ingredient(name="Flour", quantity=300, unit="g")],
                )
            ],
            prep_time=5,
            cook_time=5,
            numeric_attrs={"shelf_life_days": 7},
        )
        scaled = recipe.size_up(2)
        assert scaled.numeric_attrs == {"shelf_life_days": 7}
        assert scaled.components[0].ingredients[0].quantity == 600

    def test_recipe_double_preserves(self):
        recipe = Recipe(
            name="Cake",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[Ingredient(name="Flour", quantity=300, unit="g")],
                )
            ],
            prep_time=5,
            cook_time=5,
            numeric_attrs={"shelf_life_days": 7},
        )
        doubled = recipe.double()
        assert doubled.numeric_attrs == {"shelf_life_days": 7}


class TestPurchase:
    def test_create(self):
        g = Purchase(name="Sugar", quantity=1000, unit="g", price=Decimal("2.49"))
        assert g.name == "Sugar"
        assert g.quantity == 1000
        assert g.price == Decimal("2.49")

    def test_tag_set_empty(self):
        g = Purchase(name="Sugar", quantity=1000, unit="g", price=Decimal("2.49"))
        assert g.tag_set == set()

    def test_tag_set(self):
        g = Purchase(
            name="Butter",
            tags="unsalted, organic",
            quantity=500,
            unit="g",
            price=Decimal("5.99"),
        )
        assert g.tag_set == {"unsalted", "organic"}

    def test_matches_requirements_empty(self):
        g = Purchase(name="Butter", quantity=500, unit="g", price=Decimal("5.99"))
        assert g.matches_requirements([]) is True

    def test_matches_requirements_match(self):
        g = Purchase(
            name="Butter",
            tags="unsalted, organic",
            quantity=500,
            unit="g",
            price=Decimal("5.99"),
        )
        assert g.matches_requirements(["unsalted"]) is True
        assert g.matches_requirements(["organic", "unsalted"]) is True

    def test_matches_requirements_no_match(self):
        g = Purchase(
            name="Butter",
            tags="unsalted",
            quantity=500,
            unit="g",
            price=Decimal("5.99"),
        )
        assert g.matches_requirements(["salted"]) is False

    def test_purchased_date(self):
        from datetime import date

        g = Purchase(
            name="Eggs",
            quantity=12,
            unit="each",
            price=Decimal("3.99"),
            purchased_date=date(2026, 1, 15),
        )
        assert g.purchased_date == date(2026, 1, 15)


class TestPriceRange:
    def test_create(self):
        pr = PriceRange(min_price=Decimal("1.00"), max_price=Decimal("2.00"))
        assert pr.min_price == Decimal("1.00")
        assert pr.max_price == Decimal("2.00")

    def test_midpoint(self):
        pr = PriceRange(min_price=Decimal("1.00"), max_price=Decimal("3.00"))
        assert pr.midpoint == Decimal("2.00")

    def test_add(self):
        p1 = PriceRange(min_price=Decimal("1.00"), max_price=Decimal("2.00"))
        p2 = PriceRange(min_price=Decimal("3.00"), max_price=Decimal("4.00"))
        total = p1 + p2
        assert total.min_price == Decimal("4.00")
        assert total.max_price == Decimal("6.00")


class TestIngredientCost:
    def test_create(self):
        ing = Ingredient(name="Sugar", quantity=200, unit="g")
        pr = PriceRange(min_price=Decimal("0.50"), max_price=Decimal("0.80"))
        ic = IngredientCost(ingredient=ing, price_range=pr, sources=["Store Brand"])
        assert ic.ingredient.name == "Sugar"
        assert ic.price_range.min_price == Decimal("0.50")


class TestRecipeCost:
    def test_create(self):
        pr = PriceRange(min_price=Decimal("2.00"), max_price=Decimal("3.00"))
        rc = RecipeCost(
            recipe_name="Cake",
            ingredient_costs=[],
            total_cost_range=pr,
            cost_per_serving_range=pr,
        )
        assert rc.recipe_name == "Cake"
        assert rc.total_cost_range.min_price == Decimal("2.00")


class TestCategorizeItem:
    def test_no_rules(self):
        assert categorize_item("Spinach") is None

    def test_empty_rules(self):
        assert categorize_item("Spinach", rules=[]) is None

    def test_match(self):
        rules = [CategoryRule(category="Produce", priority=0, keywords=["spinach"])]
        assert categorize_item("Spinach", rules=rules) == "Produce"

    def test_case_insensitive(self):
        rules = [CategoryRule(category="Produce", priority=0, keywords=["spinach"])]
        assert categorize_item("SPINACH", rules=rules) == "Produce"

    def test_substring_match(self):
        rules = [CategoryRule(category="Produce", priority=0, keywords=["blueberr"])]
        assert categorize_item("Blueberries", rules=rules) == "Produce"

    def test_priority_order(self):
        rules = [
            CategoryRule(category="Produce", priority=2, keywords=["spinach"]),
            CategoryRule(category="Frozen", priority=1, keywords=["frozen"]),
        ]
        # "Frozen Spinach" should match Frozen (priority 1) before Produce (priority 2)
        assert categorize_item("Frozen Spinach", rules=rules) == "Frozen"

    def test_first_priority_wins(self):
        rules = [
            CategoryRule(category="A", priority=0, keywords=["spinach"]),
            CategoryRule(category="B", priority=0, keywords=["spinach"]),
        ]
        # Both priority 0, first match wins
        assert categorize_item("Spinach", rules=rules) == "A"

    def test_default_rules(self):
        from wright.models import DEFAULT_CATEGORY_RULES

        assert categorize_item("Spinach", rules=DEFAULT_CATEGORY_RULES) == "Produce"
        assert (
            categorize_item("Greek Yogurt", rules=DEFAULT_CATEGORY_RULES)
            == "Dairy & Eggs"
        )
        assert (
            categorize_item("Olive Oil", rules=DEFAULT_CATEGORY_RULES) == "Fats & Oils"
        )
        assert categorize_item("Canned Pears", rules=DEFAULT_CATEGORY_RULES) == "Pantry"


class TestRecipeDescriptionTags:
    def test_description(self):
        r = Recipe(
            name="Cake",
            components=[],
            prep_time=10,
            cook_time=30,
            description="A rich chocolate cake",
        )
        assert r.description == "A rich chocolate cake"

    def test_description_defaults_to_none(self):
        r = Recipe(name="Cake", components=[], prep_time=10, cook_time=30)
        assert r.description is None

    def test_tags(self):
        r = Recipe(
            name="Cake",
            components=[],
            prep_time=10,
            cook_time=30,
            tags=["dessert", "holiday", "chocolate"],
        )
        assert r.tags == ["dessert", "holiday", "chocolate"]

    def test_tags_defaults_to_empty(self):
        r = Recipe(name="Cake", components=[], prep_time=10, cook_time=30)
        assert r.tags == []

    def test_size_up_preserves_description_and_tags(self):
        r = Recipe(
            name="Cake",
            components=[],
            prep_time=10,
            cook_time=30,
            description="A test cake",
            tags=["dessert"],
        )
        doubled = r.size_up(2)
        assert doubled.description == "A test cake"
        assert doubled.tags == ["dessert"]

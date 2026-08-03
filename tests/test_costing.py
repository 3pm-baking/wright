"""Tests for wright costing."""

from __future__ import annotations

from decimal import Decimal

import pytest

from wright.costing import (
    calculate_ingredient_cost,
    calculate_ingredient_cost_range,
    calculate_recipe_cost,
    convert_with_density,
    get_top_cost_drivers,
)
from wright.errors import RecipeCostErrors, UnitConversionError
from wright.matching import find_matching_purchases
from wright.models import (
    Ingredient,
    IngredientCost,
    Purchase,
    Recipe,
    RecipeComponent,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def density_data():
    return {
        "liquids": {
            "Lemon Juice": 1.03,
            "Olive Oil": 0.91,
            "Honey": 1.42,
        },
        "volume_weights": {
            "Chia Seeds": {"tbsp": 12.0},
            "Tahini": {"tbsp": 15.0},
            "Salt": {"tsp": 6.0},
            "Cinnamon": {"tsp": 2.6},
        },
    }


@pytest.fixture
def simple_purchases():
    return [
        Purchase(name="Rolled Oats", quantity=1000, unit="g", price=Decimal("3.49")),
        Purchase(name="Greek Yogurt", quantity=500, unit="g", price=Decimal("4.49")),
        Purchase(name="Honey", quantity=340, unit="g", price=Decimal("5.99")),
        Purchase(name="Chia Seeds", quantity=200, unit="g", price=Decimal("4.99")),
        Purchase(name="Salt", quantity=500, unit="g", price=Decimal("2.99")),
        Purchase(name="Cinnamon", quantity=100, unit="g", price=Decimal("3.99")),
        Purchase(name="Flour", quantity=1000, unit="g", price=Decimal("3.99")),
        Purchase(name="Sugar", quantity=1000, unit="g", price=Decimal("2.49")),
        Purchase(name="Egg", quantity=12, unit="each", price=Decimal("4.99")),
    ]


# ── Unit conversion ─────────────────────────────────────────────────────────


class TestConvertWithDensity:
    def test_liquid_g_to_volume(self, density_data):
        result = convert_with_density("Honey", 21.0, "g", "tbsp", density_data)
        assert result is not None
        assert abs(result - 0.99) < 0.1  # ~1 tbsp

    def test_liquid_volume_to_g(self, density_data):
        result = convert_with_density("Honey", 1, "tbsp", "g", density_data)
        assert result is not None
        assert abs(result - 21.0) < 0.5

    def test_volume_weight_g_to_volume(self, density_data):
        result = convert_with_density("Cinnamon", 5.2, "g", "tsp", density_data)
        assert result is not None
        assert abs(result - 2.0) < 0.1

    def test_volume_weight_volume_to_g(self, density_data):
        result = convert_with_density("Cinnamon", 1, "tsp", "g", density_data)
        assert result is not None
        assert abs(result - 2.6) < 0.1

    def test_no_conversion(self, density_data):
        result = convert_with_density("Unknown Spice", 10, "g", "tsp", density_data)
        assert result is None

    def test_case_insensitive(self, density_data):
        result = convert_with_density("honey", 21.0, "g", "tbsp", density_data)
        assert result is not None

    def test_empty_density(self):
        result = convert_with_density("Sugar", 100, "g", "tsp", {})
        assert result is None


# ── Ingredient costing ──────────────────────────────────────────────────────


class TestCalculateIngredientCost:
    def test_simple_weight(self, simple_purchases):
        ing = Ingredient(name="Rolled Oats", quantity=50, unit="g")
        groc = simple_purchases[0]  # 1000g for $3.49
        cost = calculate_ingredient_cost(ing, groc)
        # 50g / 1000g * $3.49 = $0.1745
        assert cost == Decimal("0.1745")

    def test_density_based_conversion(self, simple_purchases, density_data):
        ing = Ingredient(name="Honey", quantity=1, unit="tbsp")
        groc = Purchase(name="Honey", quantity=340, unit="g", price=Decimal("5.99"))
        cost = calculate_ingredient_cost(ing, groc, density_data=density_data)
        # 1 tbsp ≈ 21g, price per g = 5.99/340, cost = 21 * 5.99/340
        expected = Decimal("21") * Decimal("5.99") / Decimal("340")
        assert abs(cost - expected) < Decimal("0.01")

    def test_discrete_units(self, simple_purchases):
        ing = Ingredient(name="Egg", quantity=3, unit="each")
        groc = simple_purchases[8]  # 12 eggs for $4.99
        cost = calculate_ingredient_cost(ing, groc)
        # 3/12 * $4.99 = $1.2475
        assert cost == Decimal("1.2475")

    def test_unit_conversion_raises(self):
        ing = Ingredient(name="Mystery", quantity=100, unit="g")
        groc = Purchase(name="Mystery", quantity=1, unit="each", price=Decimal("5.00"))
        with pytest.raises(UnitConversionError):
            calculate_ingredient_cost(ing, groc)

    def test_pinch_estimation(self):
        ing = Ingredient(name="Salt", quantity=2, unit="pinch")
        groc = Purchase(name="Salt", quantity=500, unit="g", price=Decimal("2.99"))
        cost = calculate_ingredient_cost(ing, groc)
        assert cost > Decimal("0")

    def test_pinch_non_convertible(self):
        ing = Ingredient(name="Salt", quantity=1, unit="pinch")
        groc = Purchase(name="Salt", quantity=1, unit="each", price=Decimal("2.99"))
        cost = calculate_ingredient_cost(ing, groc)
        assert cost == Decimal("0.01")

    def test_equivalent_quantity_packet_to_grams(self):
        """Packet ingredient with equivalent_quantity can be costed against
        a per-gram grocery item.
        """
        ing = Ingredient(
            name="Pudding",
            quantity=1,
            unit="packet",
            equivalent_quantity=37,
            equivalent_unit="g",
        )
        groc = Purchase(name="Pudding", quantity=1000, unit="g", price=Decimal("3.00"))
        cost = calculate_ingredient_cost(ing, groc)
        # 37g / 1000g * $3.00 = $0.111
        assert cost == Decimal("0.111")

    def test_equivalent_quantity_not_used_when_compatible(self):
        """When grocery unit is already packet-compatible, use direct
        packet matching over equivalent_quantity.
        """
        ing = Ingredient(
            name="Pudding",
            quantity=2,
            unit="packet",
            equivalent_quantity=37,
            equivalent_unit="g",
        )
        groc = Purchase(
            name="Pudding", quantity=5, unit="packet", price=Decimal("10.00")
        )
        cost = calculate_ingredient_cost(ing, groc)
        # 2/5 * $10 = $4.00
        assert cost == Decimal("4.00")


class TestCalculateIngredientCostRange:
    def test_single_grocery(self, simple_purchases, density_data):
        ing = Ingredient(name="Rolled Oats", quantity=50, unit="g")
        matching = find_matching_purchases(ing, simple_purchases)
        result = calculate_ingredient_cost_range(
            ing, matching, density_data=density_data
        )
        assert isinstance(result, IngredientCost)
        assert result.ingredient.name == "Rolled Oats"
        assert result.price_range.min_price == result.price_range.max_price
        assert len(result.sources) == 1

    def test_multiple_purchases(self, density_data):
        ing = Ingredient(name="Sugar", quantity=500, unit="g")
        purchases = [
            Purchase(
                name="Sugar",
                quantity=1000,
                unit="g",
                price=Decimal("2.49"),
                store="Budget Mart",
            ),
            Purchase(
                name="Sugar",
                quantity=1000,
                unit="g",
                price=Decimal("3.99"),
                store="Premium",
            ),
        ]
        result = calculate_ingredient_cost_range(
            ing, purchases, density_data=density_data
        )
        assert result.price_range.min_price < result.price_range.max_price
        assert len(result.sources) == 2


# ── Recipe costing ──────────────────────────────────────────────────────────


class TestCalculateRecipeCost:
    def test_simple_recipe(self, simple_purchases, density_data):
        recipe = Recipe(
            name="Overnight Oats",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Rolled Oats", quantity=50, unit="g"),
                        Ingredient(name="Greek Yogurt", quantity=100, unit="g"),
                        Ingredient(name="Honey", quantity=1, unit="tbsp"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=0,
            servings=1,
        )
        result = calculate_recipe_cost(
            recipe, simple_purchases, density_data=density_data
        )
        assert result.recipe_name == "Overnight Oats"
        assert len(result.ingredient_costs) == 3
        assert result.total_cost_range.min_price > Decimal("0")
        assert result.cost_per_serving_range.min_price > Decimal("0")

    def test_byproduct_skipped(self, simple_purchases, density_data):
        recipe = Recipe(
            name="Test",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Flour", quantity=300, unit="g"),
                        Ingredient(
                            name="Water", quantity=100, unit="ml", byproduct=True
                        ),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )
        result = calculate_recipe_cost(
            recipe, simple_purchases, density_data=density_data
        )
        # Only flour should be costed (water is byproduct)
        assert len(result.ingredient_costs) == 1

    def test_zero_quantity_skipped(self, simple_purchases, density_data):
        recipe = Recipe(
            name="Test",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Flour", quantity=300, unit="g"),
                        Ingredient(name="Salt", quantity=0, unit="g"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )
        result = calculate_recipe_cost(
            recipe, simple_purchases, density_data=density_data
        )
        assert len(result.ingredient_costs) == 1

    def test_missing_ingredient_collects_errors(self, simple_purchases, density_data):
        recipe = Recipe(
            name="Test",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Flour", quantity=300, unit="g"),
                        Ingredient(name="Ghost Flour", quantity=100, unit="g"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )
        with pytest.raises(RecipeCostErrors) as exc:
            calculate_recipe_cost(recipe, simple_purchases, density_data=density_data)
        assert "1 ingredient" in str(exc.value)

    def test_per_serving_calculation(self, simple_purchases, density_data):
        recipe = Recipe(
            name="Test",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Rolled Oats", quantity=100, unit="g"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
            servings={"min_servings": 2, "max_servings": 4},
        )
        result = calculate_recipe_cost(
            recipe, simple_purchases, density_data=density_data
        )
        # Cost per serving: cheapest = total/4, priciest = total/2
        total = result.total_cost_range.min_price
        assert result.cost_per_serving_range.min_price == total / Decimal("4")
        assert result.cost_per_serving_range.max_price == total / Decimal("2")

    def test_exact_servings(self, simple_purchases, density_data):
        recipe = Recipe(
            name="Test",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Rolled Oats", quantity=100, unit="g"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
            servings=8,
        )
        result = calculate_recipe_cost(
            recipe, simple_purchases, density_data=density_data
        )
        total = result.total_cost_range.min_price
        assert result.cost_per_serving_range.min_price == total / Decimal("8")
        assert result.cost_per_serving_range.max_price == total / Decimal("8")


# ── Recursive costing ───────────────────────────────────────────────────────


class TestRecursiveCosting:
    def test_product_ref(self, simple_purchases, density_data):
        # Sub-recipe: Vanilla Sugar
        vanilla_sugar = Recipe(
            name="Vanilla Sugar",
            components=[
                RecipeComponent(
                    name="Mix",
                    ingredients=[
                        Ingredient(name="Sugar", quantity=200, unit="g"),
                        Ingredient(name="Egg", quantity=1, unit="each"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=0,
            servings=None,
            net_weight_grams=200,
        )

        # Main recipe uses vanilla sugar via product_ref
        cake = Recipe(
            name="Cake",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Flour", quantity=300, unit="g"),
                        Ingredient(
                            name="Vanilla Sugar",
                            quantity=1,
                            unit="packet",
                            equivalent_quantity=8,
                            equivalent_unit="g",
                            product_ref="vanilla-sugar",
                        ),
                    ],
                )
            ],
            prep_time=15,
            cook_time=30,
            servings=8,
        )

        recipe_index = {
            "vanilla-sugar": vanilla_sugar,
        }

        result = calculate_recipe_cost(
            cake,
            simple_purchases,
            density_data=density_data,
            recipe_index=recipe_index,
        )
        assert result.recipe_name == "Cake"
        assert len(result.ingredient_costs) == 2  # flour + vanilla sugar

        # Vanilla sugar entry should reference the sub-recipe
        vs_entry = next(
            c
            for c in result.ingredient_costs
            if c.ingredient.product_ref == "vanilla-sugar"
        )
        assert "Vanilla Sugar" in vs_entry.sources[0]
        assert "sub-recipe" in vs_entry.sources[0]

    def test_cycle_detection(self, simple_purchases, density_data):
        a = Recipe(
            name="A",
            components=[
                RecipeComponent(
                    name="X",
                    ingredients=[
                        Ingredient(
                            name="Cycle",
                            quantity=1,
                            unit="each",
                            product_ref="b",
                        ),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
            servings=None,
            net_weight_grams=100,
        )
        b = Recipe(
            name="B",
            components=[
                RecipeComponent(
                    name="Y",
                    ingredients=[
                        Ingredient(
                            name="Cycle Back",
                            quantity=1,
                            unit="each",
                            product_ref="a",
                        ),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
            servings=None,
            net_weight_grams=100,
        )

        recipe_index = {"a": a, "b": b}

        with pytest.raises(RecipeCostErrors) as exc:
            calculate_recipe_cost(
                a,
                simple_purchases,
                density_data=density_data,
                recipe_index=recipe_index,
            )
        assert "cycle" in str(exc.value).lower()

    def test_missing_product_ref(self, simple_purchases, density_data):
        cake = Recipe(
            name="Cake",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(
                            name="Vanilla Sugar",
                            quantity=1,
                            unit="packet",
                            equivalent_quantity=8,
                            equivalent_unit="g",
                            product_ref="vanilla-sugar",
                        ),
                    ],
                )
            ],
            prep_time=15,
            cook_time=30,
            servings=8,
        )

        with pytest.raises(RecipeCostErrors) as exc:
            calculate_recipe_cost(
                cake,
                simple_purchases,
                density_data=density_data,
            )
        assert "vanilla-sugar" in str(exc.value)


class TestGetTopCostDrivers:
    def test_top_drivers(self, simple_purchases, density_data):
        recipe = Recipe(
            name="Multi",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Rolled Oats", quantity=500, unit="g"),
                        Ingredient(name="Flour", quantity=100, unit="g"),
                        Ingredient(name="Greek Yogurt", quantity=50, unit="g"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )
        result = calculate_recipe_cost(
            recipe, simple_purchases, density_data=density_data
        )
        top = get_top_cost_drivers(result, n=2)
        assert len(top) == 2
        # Top should be the most expensive (descending order)
        assert top[0].price_range.midpoint >= top[1].price_range.midpoint


class TestCustomMatcherCosting:
    """Tests that calculate_recipe_cost uses a custom matcher when provided."""

    def test_custom_matcher_successful(self, simple_purchases):
        """A fuzzy matcher that matches by substring works in costing."""
        recipe = Recipe(
            name="Cake",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Organic Rolled Oats", quantity=50, unit="g"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )

        def fuzzy_matcher(ingredient, purchases):
            return [g for g in purchases if "oats" in g.name.lower()]

        result = calculate_recipe_cost(recipe, simple_purchases, matcher=fuzzy_matcher)
        assert result.total_cost_range.midpoint > Decimal("0")

    def test_custom_matcher_no_match(self, simple_purchases):
        """When custom matcher raises IngredientNotFoundError, cost
        function reports it as a RecipeCostErrors.
        """
        from wright.errors import IngredientNotFoundError

        def failing_matcher(ingredient, purchases):
            raise IngredientNotFoundError(ingredient.name)

        recipe = Recipe(
            name="Cake",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Flour", quantity=300, unit="g"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )

        with pytest.raises(RecipeCostErrors):
            calculate_recipe_cost(recipe, simple_purchases, matcher=failing_matcher)


class TestConvertIngredientToGrams:
    def test_grams_direct(self):
        from wright.costing import convert_ingredient_to_grams

        ing = Ingredient(name="Sugar", quantity=500, unit="g")
        assert convert_ingredient_to_grams(ing) == 500.0

    def test_kg_to_grams(self):
        from wright.costing import convert_ingredient_to_grams

        ing = Ingredient(name="Sugar", quantity=2, unit="kg")
        assert convert_ingredient_to_grams(ing) == 2000.0

    def test_oz_to_grams(self):
        from wright.costing import convert_ingredient_to_grams

        ing = Ingredient(name="Chicken", quantity=16, unit="oz")
        result = convert_ingredient_to_grams(ing)
        assert abs(result - 453.6) < 1.0

    def test_packet_uses_equivalent(self):
        from wright.costing import convert_ingredient_to_grams

        ing = Ingredient(
            name="Vanilla Sugar",
            quantity=1,
            unit="packet",
            equivalent_quantity=8,
            equivalent_unit="g",
        )
        assert convert_ingredient_to_grams(ing) == 8.0

    def test_density_fallback_ml_to_grams_with_data(self, density_data):
        """Milk in ml should convert to grams via density data."""
        from wright.costing import convert_ingredient_to_grams

        ing = Ingredient(name="Whole Milk", quantity=200, unit="ml")
        # Without density data, this should raise
        with pytest.raises(UnitConversionError):
            convert_ingredient_to_grams(ing)

        # With density data containing milk, it should work
        milk_density = {"liquids": {"Whole Milk": 1.03}}
        result = convert_ingredient_to_grams(
            ing, density_data=milk_density, raise_on_error=False
        )
        assert abs(result - 206.0) < 1.0  # 200ml * 1.03 g/ml

    def test_density_fallback_tbsp_to_grams(self, density_data):
        """Volume units like tbsp should convert to grams via volume_weights."""
        from wright.costing import convert_ingredient_to_grams

        ing = Ingredient(name="Chia Seeds", quantity=2, unit="tbsp")
        result = convert_ingredient_to_grams(
            ing, density_data=density_data, raise_on_error=False
        )
        assert abs(result - 24.0) < 0.1  # 2 tbsp * 12 g/tbsp

    def test_unresolvable_returns_zero_with_raise_false(self):
        from wright.costing import convert_ingredient_to_grams

        ing = Ingredient(name="Mystery Liquid", quantity=200, unit="ml")
        result = convert_ingredient_to_grams(ing, raise_on_error=False)
        assert result == 0.0

    def test_unresolvable_raises_with_raise_true(self):
        from wright.costing import convert_ingredient_to_grams

        ing = Ingredient(name="Mystery Liquid", quantity=200, unit="ml")
        with pytest.raises(UnitConversionError):
            convert_ingredient_to_grams(ing)

    def test_density_data_empty_dict_behaves_like_none(self):
        """density_data={} is falsy — no density fallback is attempted."""
        from wright.costing import convert_ingredient_to_grams

        ing = Ingredient(name="Whole Milk", quantity=200, unit="ml")
        with pytest.raises(UnitConversionError):
            convert_ingredient_to_grams(ing, density_data={})

        result = convert_ingredient_to_grams(ing, density_data={}, raise_on_error=False)
        assert result == 0.0

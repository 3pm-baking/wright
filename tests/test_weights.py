"""Tests for wright.weights — ingredient-to-grams conversion."""

from __future__ import annotations

import pytest

from wright.errors import UnitConversionError
from wright.models import ConversionData, Ingredient, Recipe, RecipeComponent
from wright.weights import ingredient_grams

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def conversion_data():
    return ConversionData(
        liquids={"Milk": 1.03},
        volume_weights={
            "Sugar": {"tsp": 4.2, "tbsp": 12.5},
            "Salt": {"tsp": 6.0},
        },
        unit_weights={"Egg": 50.0, "Onion": 125.0},
        special={"pinch": 1.0},
    )


def make_recipe(*ingredients: Ingredient) -> Recipe:
    return Recipe(
        name="Test Recipe",
        components=[RecipeComponent(name="All", materials=list(ingredients))],
        prep_time=1,
        cook_time=1,
    )


# ── ingredient_grams ───────────────────────────────────────────────────────


class TestIngredientGrams:
    @pytest.mark.parametrize(
        ("material", "expected"),
        [
            # Weight units via pint
            (Ingredient(name="Flour", quantity=500, unit="g"), 500.0),
            (Ingredient(name="Flour", quantity=1, unit="kg"), 1000.0),
            (Ingredient(name="Butter", quantity=16, unit="oz"), 453.59),
            # Liquids via density
            (Ingredient(name="Milk", quantity=310, unit="ml"), 319.3),
            # Volume weights
            (Ingredient(name="Sugar", quantity=2, unit="tsp"), 8.4),
            (Ingredient(name="Salt", quantity=2, unit="tsp"), 12.0),
            # Packets via equivalent_quantity
            (
                Ingredient(
                    name="Vanilla Sugar",
                    quantity=1,
                    unit="packet",
                    equivalent_quantity=8,
                ),
                8.0,
            ),
            # Discrete via unit_weights table
            (Ingredient(name="Egg", quantity=4, unit="each"), 200.0),
            (Ingredient(name="Onion", quantity=8, unit="each"), 1000.0),
            # Discrete via approx_weight_grams field (overrides table)
            (
                Ingredient(
                    name="Egg",
                    quantity=2,
                    unit="each",
                    approx_weight_grams=60.0,
                ),
                120.0,
            ),
            # Pinch via special
            (Ingredient(name="Salt", quantity=2, unit="pinch"), 2.0),
            # Zero quantity short-circuits
            (Ingredient(name="Egg", quantity=0, unit="each"), 0.0),
        ],
    )
    def test_resolution_strategies(self, conversion_data, material, expected):
        result = ingredient_grams(material, conversion_data=conversion_data)
        assert result == pytest.approx(expected, rel=0.01)

    def test_case_insensitive_unit_weight_lookup(self, conversion_data):
        result = ingredient_grams(
            Ingredient(name="egg", quantity=3, unit="each"),
            conversion_data=conversion_data,
        )
        assert result == pytest.approx(150.0)

    def test_unresolvable_raises(self, conversion_data):
        with pytest.raises(UnitConversionError):
            ingredient_grams(
                Ingredient(name="Mystery", quantity=1, unit="each"),
                conversion_data=conversion_data,
            )

    def test_unresolvable_returns_zero_when_not_raising(self, conversion_data):
        result = ingredient_grams(
            Ingredient(name="Mystery", quantity=1, unit="each"),
            conversion_data=conversion_data,
            raise_on_error=False,
        )
        assert result == 0.0

    def test_no_conversion_data_weight_units_still_work(self):
        result = ingredient_grams(Ingredient(name="Flour", quantity=500, unit="g"))
        assert result == 500.0

    def test_no_conversion_data_discrete_raises(self):
        with pytest.raises(UnitConversionError):
            ingredient_grams(Ingredient(name="Egg", quantity=1, unit="each"))


# ── Recipe methods ─────────────────────────────────────────────────────────


class TestRecipeWeights:
    def test_ingredient_weights_sorted_desc(self, conversion_data):
        recipe = make_recipe(
            Ingredient(name="Flour", quantity=500, unit="g"),
            Ingredient(name="Egg", quantity=4, unit="each"),
            Ingredient(name="Milk", quantity=310, unit="ml"),
        )
        pairs = recipe.ingredient_weights_grams(conversion_data=conversion_data)
        grams = [g for _, g in pairs]
        assert grams == sorted(grams, reverse=True)
        assert {ing.name: g for ing, g in pairs}["Egg"] == 200.0

    def test_duplicate_names_aggregate(self, conversion_data):
        recipe = Recipe(
            name="Two Components",
            components=[
                RecipeComponent(
                    name="Dough",
                    materials=[Ingredient(name="Butter", quantity=100, unit="g")],
                ),
                RecipeComponent(
                    name="Topping",
                    materials=[Ingredient(name="Butter", quantity=50, unit="g")],
                ),
            ],
            prep_time=1,
            cook_time=1,
        )
        pairs = recipe.ingredient_weights_grams(conversion_data=conversion_data)
        assert len(pairs) == 1
        assert pairs[0][1] == pytest.approx(150.0)

    def test_byproducts_excluded(self, conversion_data):
        recipe = make_recipe(
            Ingredient(name="Flour", quantity=500, unit="g"),
            Ingredient(
                name="Vanilla Pod",
                quantity=1,
                unit="each",
                byproduct=True,
                approx_weight_grams=2.0,
            ),
        )
        pairs = recipe.ingredient_weights_grams(conversion_data=conversion_data)
        assert [ing.name for ing, _ in pairs] == ["Flour"]

    def test_total_weight(self, conversion_data):
        recipe = make_recipe(
            Ingredient(name="Flour", quantity=500, unit="g"),
            Ingredient(name="Egg", quantity=4, unit="each"),
            Ingredient(name="Milk", quantity=310, unit="ml"),
        )
        total = recipe.total_weight_grams(conversion_data=conversion_data)
        assert total == pytest.approx(500 + 200 + 319.3)

    def test_composition_fractions_sum_to_one(self, conversion_data):
        recipe = make_recipe(
            Ingredient(name="Flour", quantity=500, unit="g"),
            Ingredient(name="Egg", quantity=4, unit="each"),
            Ingredient(name="Milk", quantity=310, unit="ml"),
        )
        comp = recipe.composition(conversion_data=conversion_data)
        assert sum(comp.values()) == pytest.approx(1.0)
        assert comp["Flour"] == pytest.approx(500 / 1019.3)

    def test_composition_empty_recipe(self, conversion_data):
        recipe = make_recipe()
        assert recipe.composition(conversion_data=conversion_data) == {}

    def test_raise_on_error_false_gives_zero(self):
        recipe = make_recipe(
            Ingredient(name="Flour", quantity=500, unit="g"),
            Ingredient(name="Mystery", quantity=1, unit="each"),
        )
        total = recipe.total_weight_grams(
            conversion_data=ConversionData(), raise_on_error=False
        )
        assert total == pytest.approx(500.0)

    def test_raise_on_error_true_raises(self):
        recipe = make_recipe(Ingredient(name="Mystery", quantity=1, unit="each"))
        with pytest.raises(UnitConversionError):
            recipe.total_weight_grams(conversion_data=ConversionData())

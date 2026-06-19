"""Tests for wright allergens and dietary properties."""

from __future__ import annotations

import pytest

from wright.allergens import (
    BADGE_DISPLAY,
    detect_allergens,
    detect_allergens_from_names,
    detect_dietary_properties,
)
from wright.models import Ingredient, Recipe, RecipeComponent


@pytest.fixture
def allergy_map():
    return {
        "milk": "Milk",
        "butter": "Milk",
        "cheese": "Milk",
        "cream": "Milk",
        "yogurt": "Milk",
        "sour cream": "Milk",
        "flour": "Wheat",
        "wheat": "Wheat",
        "egg": "Eggs",
        "almond": "Tree Nuts",
        "honey": "Bee Products",
    }


def _recipe(*ingredients: Ingredient) -> Recipe:
    """Build a minimal Recipe from ingredients for allergen/badge testing."""
    return Recipe(
        name="Test",
        components=[RecipeComponent(name="Base", ingredients=list(ingredients))],
        prep_time=5,
        cook_time=5,
    )


# ── Allergen detection ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("ingredients", "expected"),
    [
        pytest.param(
            [Ingredient(name="Butter", quantity=100, unit="g")],
            ["Milk"],
            id="dairy_detected",
        ),
        pytest.param(
            [Ingredient(name="Flour", quantity=300, unit="g")],
            ["Wheat"],
            id="gluten_detected",
        ),
        pytest.param(
            [
                Ingredient(name="Butter", quantity=100, unit="g"),
                Ingredient(name="Flour", quantity=300, unit="g"),
                Ingredient(name="Egg", quantity=3, unit="each"),
            ],
            ["Eggs", "Milk", "Wheat"],
            id="multiple_allergens",
        ),
        pytest.param(
            [
                Ingredient(name="Sugar", quantity=200, unit="g"),
                Ingredient(name="Salt", quantity=5, unit="g"),
            ],
            [],
            id="no_allergens",
        ),
        pytest.param(
            [
                Ingredient(name="Butter", quantity=100, unit="g", byproduct=True),
                Ingredient(name="Flour", quantity=300, unit="g"),
            ],
            ["Wheat"],
            id="byproduct_skipped",
        ),
        pytest.param(
            [Ingredient(name="GF Flour", quantity=300, unit="g")],
            [],
            id="gf_ingredient_suppresses_gluten",
        ),
        pytest.param(
            [Ingredient(name="Cream of Tartar", quantity=5, unit="g")],
            [],
            id="cream_of_tartar_not_dairy",
        ),
        pytest.param(
            [Ingredient(name="Vegan Butter", quantity=100, unit="g")],
            [],
            id="vegan_ingredient_suppresses_dairy",
        ),
    ],
)
def test_detect_allergens(ingredients, expected, allergy_map):
    recipe = _recipe(*ingredients)
    assert detect_allergens(recipe, allergy_map) == expected


class TestDetectAllergensFromNames:
    def test_plain_names(self, allergy_map):
        result = detect_allergens_from_names(["Butter", "Flour", "Sugar"], allergy_map)
        assert result == ["Milk", "Wheat"]


# ── Badge detection ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("ingredients", "expected"),
    [
        pytest.param(
            [
                Ingredient(name="Almond Flour", quantity=300, unit="g"),
                Ingredient(name="Sugar", quantity=100, unit="g"),
            ],
            ["VEGAN", "GLUTEN-FREE"],
            id="gluten_free_badge",
        ),
        pytest.param(
            [
                Ingredient(name="Flour", quantity=300, unit="g"),
                Ingredient(name="Sugar", quantity=100, unit="g"),
                Ingredient(name="Vegan Butter", quantity=50, unit="g"),
                Ingredient(name="Almond Milk", quantity=200, unit="ml"),
            ],
            ["VEGAN"],
            id="vegan_badge",
        ),
        pytest.param(
            [
                Ingredient(name="Flour", quantity=300, unit="g"),
                Ingredient(name="Egg", quantity=3, unit="each"),
            ],
            ["DAIRY-FREE"],
            id="not_vegan_with_egg",
        ),
        pytest.param(
            [Ingredient(name="Flour", quantity=300, unit="g")],
            ["VEGAN"],
            id="not_gluten_free_with_flour",
        ),
    ],
)
def test_detect_dietary_properties(ingredients, expected):
    recipe = _recipe(*ingredients)
    assert detect_dietary_properties(recipe) == expected


class TestBadgeDisplay:
    def test_known_badges(self):
        assert BADGE_DISPLAY["vegan"] == "VEGAN"
        assert BADGE_DISPLAY["gluten-free"] == "GLUTEN-FREE"

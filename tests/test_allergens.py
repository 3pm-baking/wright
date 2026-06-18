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


# ── Allergen detection ──────────────────────────────────────────────────────


class TestDetectAllergens:
    def test_dairy_detected(self, allergy_map):
        recipe = Recipe(
            name="Test",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Butter", quantity=100, unit="g"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )
        result = detect_allergens(recipe, allergy_map)
        assert "Milk" in result

    def test_gluten_detected(self, allergy_map):
        recipe = Recipe(
            name="Test",
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
        result = detect_allergens(recipe, allergy_map)
        assert "Wheat" in result

    def test_multiple_allergens(self, allergy_map):
        recipe = Recipe(
            name="Test",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Butter", quantity=100, unit="g"),
                        Ingredient(name="Flour", quantity=300, unit="g"),
                        Ingredient(name="Egg", quantity=3, unit="each"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )
        result = detect_allergens(recipe, allergy_map)
        assert "Milk" in result
        assert "Wheat" in result
        assert "Eggs" in result

    def test_no_allergens(self, allergy_map):
        recipe = Recipe(
            name="Test",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Sugar", quantity=200, unit="g"),
                        Ingredient(name="Salt", quantity=5, unit="g"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )
        result = detect_allergens(recipe, allergy_map)
        assert result == []

    def test_byproduct_skipped(self, allergy_map):
        recipe = Recipe(
            name="Test",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(
                            name="Butter", quantity=100, unit="g", byproduct=True
                        ),
                        Ingredient(name="Flour", quantity=300, unit="g"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )
        result = detect_allergens(recipe, allergy_map)
        # Butter (byproduct) skipped, only Wheat from Flour
        assert "Milk" not in result
        assert "Wheat" in result

    def test_gf_ingredient_suppresses_gluten(self, allergy_map):
        recipe = Recipe(
            name="Test",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="GF Flour", quantity=300, unit="g"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )
        result = detect_allergens(recipe, allergy_map)
        # "GF Flour" starts with "gf " → gluten-free indicator → suppresses wheat
        assert "Wheat" not in result

    def test_cream_of_tartar_not_dairy(self, allergy_map):
        recipe = Recipe(
            name="Test",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Cream of Tartar", quantity=5, unit="g"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )
        result = detect_allergens(recipe, allergy_map)
        assert "Milk" not in result

    def test_vegan_ingredient_suppresses_dairy(self, allergy_map):
        recipe = Recipe(
            name="Test",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Vegan Butter", quantity=100, unit="g"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )
        result = detect_allergens(recipe, allergy_map)
        assert "Milk" not in result


class TestDetectAllergensFromNames:
    def test_plain_names(self, allergy_map):
        result = detect_allergens_from_names(["Butter", "Flour", "Sugar"], allergy_map)
        assert "Milk" in result
        assert "Wheat" in result


# ── Badge detection ─────────────────────────────────────────────────────────


class TestDetectBadges:
    def test_gluten_free_badge(self):
        recipe = Recipe(
            name="GF Cake",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Almond Flour", quantity=300, unit="g"),
                        Ingredient(name="Sugar", quantity=100, unit="g"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )
        badges = detect_dietary_properties(recipe)
        assert "GLUTEN-FREE" in badges

    def test_vegan_badge(self):
        recipe = Recipe(
            name="Vegan Cake",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Flour", quantity=300, unit="g"),
                        Ingredient(name="Sugar", quantity=100, unit="g"),
                        Ingredient(name="Vegan Butter", quantity=50, unit="g"),
                        Ingredient(name="Almond Milk", quantity=200, unit="ml"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )
        badges = detect_dietary_properties(recipe)
        assert "VEGAN" in badges
        assert "DAIRY-FREE" not in badges  # suppressed by VEGAN

    def test_not_vegan_with_egg(self):
        recipe = Recipe(
            name="Cake",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Flour", quantity=300, unit="g"),
                        Ingredient(name="Egg", quantity=3, unit="each"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )
        badges = detect_dietary_properties(recipe)
        assert "VEGAN" not in badges

    def test_not_gluten_free_with_flour(self):
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
        badges = detect_dietary_properties(recipe)
        assert "GLUTEN-FREE" not in badges


class TestBadgeDisplay:
    def test_known_badges(self):
        assert BADGE_DISPLAY["vegan"] == "VEGAN"
        assert BADGE_DISPLAY["gluten-free"] == "GLUTEN-FREE"

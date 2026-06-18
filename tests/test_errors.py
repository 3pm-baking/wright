"""Tests for wright errors."""

from __future__ import annotations

from wright.errors import (
    IngredientNotFoundError,
    PurchaseLoadError,
    RecipeCoreError,
    RecipeCostErrors,
    RecipeLoadError,
    UnitConversionError,
)


class TestErrorHierarchy:
    def test_base(self):
        assert issubclass(RecipeCoreError, Exception)

    def test_ingredient_not_found(self):
        assert issubclass(IngredientNotFoundError, RecipeCoreError)

    def test_unit_conversion(self):
        assert issubclass(UnitConversionError, RecipeCoreError)

    def test_recipe_cost_errors(self):
        assert issubclass(RecipeCostErrors, RecipeCoreError)

    def test_recipe_load(self):
        assert issubclass(RecipeLoadError, RecipeCoreError)

    def test_grocery_load(self):
        assert issubclass(PurchaseLoadError, RecipeCoreError)


class TestIngredientNotFoundError:
    def test_simple(self):
        e = IngredientNotFoundError("Ghost Flour")
        assert "Ghost Flour" in str(e)

    def test_with_tags(self):
        e = IngredientNotFoundError("Butter", require_tags=["unsalted"])
        assert "Butter" in str(e)
        assert "unsalted" in str(e)


class TestUnitConversionError:
    def test_message(self):
        e = UnitConversionError("g", "tsp", "Cinnamon")
        assert "g" in str(e)
        assert "tsp" in str(e)
        assert "Cinnamon" in str(e)


class TestRecipeCostErrors:
    def test_collects_errors(self):
        e1 = IngredientNotFoundError("A")
        e2 = UnitConversionError("g", "tsp", "B")
        err = RecipeCostErrors([e1, e2])
        assert len(err.errors) == 2
        assert "2 ingredient" in str(err)

    def test_nested(self):
        inner = RecipeCostErrors([IngredientNotFoundError("A")])
        outer = RecipeCostErrors([inner])
        assert len(outer.errors) == 1
        assert "1 ingredient" in str(outer)


class TestRecipeLoadError:
    def test_message(self):
        e = RecipeLoadError("/tmp/cake.yaml", "Invalid YAML")
        assert "/tmp/cake.yaml" in str(e)
        assert "Invalid YAML" in str(e)


class TestPurchaseLoadError:
    def test_message(self):
        e = PurchaseLoadError("/tmp/groceries.yaml", "File not found")
        assert "/tmp/groceries.yaml" in str(e)
        assert "File not found" in str(e)

"""Tests for wright YAML loader."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from wright.errors import PurchaseLoadError, RecipeLoadError
from wright.loader import (
    list_recipe_files,
    load_base_recipe,
    load_purchases,
)
from wright.models import ServingRange


class TestLoadRecipe:
    def test_load_quinoa_bowl(self, tmp_path: Path):
        yaml_content = """name: Quinoa Power Bowl
prep_time: 15
cook_time: 20
servings:
  min_servings: 2
  max_servings: 4
components:
  - name: Grain Base
    ingredients:
      - name: Quinoa
        quantity: 200
        unit: g
"""
        recipe_path = tmp_path / "quinoa.yaml"
        recipe_path.write_text(yaml_content)

        recipe = load_base_recipe(recipe_path)
        assert recipe.name == "Quinoa Power Bowl"
        assert recipe.prep_time == 15
        assert recipe.cook_time == 20
        assert isinstance(recipe.servings, ServingRange)
        assert recipe.servings.min_servings == 2
        assert len(recipe.all_ingredients) == 1

    def test_load_exact_servings(self, tmp_path: Path):
        yaml_content = """name: Overnight Oats
prep_time: 5
cook_time: 0
servings: 1
components: []
"""
        recipe_path = tmp_path / "oats.yaml"
        recipe_path.write_text(yaml_content)

        recipe = load_base_recipe(recipe_path)
        assert recipe.servings == 1

    def test_load_no_servings(self, tmp_path: Path):
        yaml_content = """name: Vanilla Sugar
prep_time: 5
cook_time: 0
net_weight_grams: 200
components: []
"""
        recipe_path = tmp_path / "product.yaml"
        recipe_path.write_text(yaml_content)

        recipe = load_base_recipe(recipe_path)
        assert recipe.servings is None
        assert recipe.net_weight_grams == 200

    def test_file_not_found(self, tmp_path: Path):
        with pytest.raises(RecipeLoadError, match="File not found"):
            load_base_recipe(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml(self, tmp_path: Path):
        recipe_path = tmp_path / "bad.yaml"
        recipe_path.write_text("invalid: [unclosed")

        with pytest.raises(RecipeLoadError, match="Invalid YAML"):
            load_base_recipe(recipe_path)


class TestLoadPurchasedItems:
    def test_load(self, tmp_path: Path):
        yaml_content = """store: Test Store
purchases:
  - name: Sugar
    quantity: 1000
    unit: g
    price: 2.49
"""
        path = tmp_path / "groceries.yaml"
        path.write_text(yaml_content)

        items = load_purchases(path)
        assert len(items) == 1
        assert items[0].name == "Sugar"
        assert items[0].quantity == 1000
        assert items[0].price == Decimal("2.49")

    def test_with_purchased_date(self, tmp_path: Path):
        from datetime import date as DateType

        yaml_content = """store: Test Store
purchases:
  - name: Butter
    quantity: 500
    unit: g
    price: 5.99
    purchased_date: 2026-01-15
"""
        path = tmp_path / "groceries.yaml"
        path.write_text(yaml_content)

        items = load_purchases(path)
        assert items[0].purchased_date == DateType(2026, 1, 15)

    def test_file_not_found(self, tmp_path: Path):
        with pytest.raises(PurchaseLoadError, match="File not found"):
            load_purchases(tmp_path / "nonexistent.yaml")


class TestListRecipeFiles:
    def test_lists_yaml_files(self, tmp_path: Path):
        (tmp_path / "a.yaml").write_text(
            "name: A\nprep_time: 5\ncook_time: 5\ncomponents: []\n"
        )
        (tmp_path / "b.yaml").write_text(
            "name: B\nprep_time: 5\ncook_time: 5\ncomponents: []\n"
        )
        (tmp_path / "not-recipe.txt").write_text("hello")

        files = list_recipe_files(tmp_path)
        assert len(files) == 2
        names = {f.stem for f in files}
        assert names == {"a", "b"}

    def test_empty_directory(self, tmp_path: Path):
        files = list_recipe_files(tmp_path)
        assert files == []

    def test_nonexistent_directory(self, tmp_path: Path):
        files = list_recipe_files(tmp_path / "nonexistent")
        assert files == []

"""Tests for wright session models."""

from __future__ import annotations

from datetime import date

import pytest

from wright.session import (
    ProductionItem,
    ProductionRun,
    convert_recipe_name_to_filename,
)


class TestProductionItem:
    def test_create(self):
        item = ProductionItem(assembly="Cake", quantity=2)
        assert item.assembly == "Cake"
        assert item.quantity == 2

    def test_recipe_backward_compat_access(self):
        """Recipe property still works as an alias for assembly."""
        item = ProductionItem(assembly="Cake", quantity=2)
        assert item.recipe == "Cake"

    def test_recipe_constructor_backward_compat(self):
        """recipe= in constructor still works via validator."""
        item = ProductionItem(recipe="Cake", quantity=2)  # ty: ignore
        assert item.assembly == "Cake"
        assert item.recipe == "Cake"

    def test_fractional_quantity(self):
        item = ProductionItem(assembly="Cake", quantity=0.5)
        assert item.quantity == 0.5

    def test_zero_quantity_raises(self):
        with pytest.raises(ValueError):
            ProductionItem(assembly="Cake", quantity=0)

    def test_negative_quantity_raises(self):
        with pytest.raises(ValueError):
            ProductionItem(assembly="Cake", quantity=-1)


class TestProductionRun:
    def test_create(self):
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(assembly="Cake", quantity=2)],
            target_dates=[date(2026, 6, 1), date(2026, 6, 2)],
        )
        assert session.date == date(2026, 6, 1)
        assert len(session.production) == 1
        assert len(session.target_dates) == 2


class TestRecipeNameToFilename:
    def test_simple(self):
        assert convert_recipe_name_to_filename("Cake") == "cake"

    def test_spaces_to_hyphens(self):
        assert (
            convert_recipe_name_to_filename("German Cheese Cake")
            == "german-cheese-cake"
        )

    def test_special_chars_removed(self):
        result = convert_recipe_name_to_filename("Oma Christa's Spiced Cake")
        assert result == "oma-christas-spiced-cake"

    def test_multiple_spaces(self):
        assert (
            convert_recipe_name_to_filename("Double  Chocolate") == "double-chocolate"
        )

    def test_leading_trailing_hyphens(self):
        assert convert_recipe_name_to_filename(" - Cake - ") == "cake"

    def test_umlauts_removed(self):
        assert convert_recipe_name_to_filename("Käsekuchen") == "ksekuchen"


class TestCombineProductionRuns:
    def test_combines_production_items(self):
        a = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(assembly="Cake", quantity=2)],
            target_dates=[date(2026, 6, 3)],
        )
        b = ProductionRun(
            date=date(2026, 6, 2),
            production=[ProductionItem(assembly="Cake", quantity=3)],
            target_dates=[date(2026, 6, 4)],
        )
        merged = a + b
        assert merged.date == date(2026, 6, 1)  # earliest
        assert len(merged.production) == 1
        assert merged.production[0].quantity == 5  # 2 + 3

    def test_unions_target_dates(self):
        a = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(assembly="Cake", quantity=1)],
            target_dates=[date(2026, 6, 3), date(2026, 6, 4)],
        )
        b = ProductionRun(
            date=date(2026, 6, 2),
            production=[ProductionItem(assembly="Cake", quantity=1)],
            target_dates=[date(2026, 6, 4), date(2026, 6, 5)],
        )
        merged = a + b
        assert sorted(merged.target_dates) == [
            date(2026, 6, 3),
            date(2026, 6, 4),
            date(2026, 6, 5),
        ]

    def test_different_recipes(self):
        a = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(assembly="Cake", quantity=2)],
            target_dates=[],
        )
        b = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(assembly="Pie", quantity=1)],
            target_dates=[],
        )
        merged = a + b
        names = {i.assembly for i in merged.production}
        assert names == {"Cake", "Pie"}

    def test_chaining(self):
        a = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(assembly="Cake", quantity=2)],
            target_dates=[date(2026, 6, 3)],
        )
        b = ProductionRun(
            date=date(2026, 6, 2),
            production=[ProductionItem(assembly="Cake", quantity=3)],
            target_dates=[],
        )
        c = ProductionRun(
            date=date(2026, 6, 3),
            production=[ProductionItem(assembly="Cake", quantity=1)],
            target_dates=[],
        )
        merged = a + b + c
        assert merged.date == date(2026, 6, 1)
        assert merged.production[0].quantity == 6

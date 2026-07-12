"""Tests for wright pricing."""

from __future__ import annotations

from decimal import Decimal

import pytest

from wright.models import PriceRange, RecipeCost
from wright.pricing import margin_price, multiplier_price, per_serving_price


class TestMarginPrice:
    def test_standard_margin(self):
        cost = Decimal("2.00")
        price = margin_price(cost, Decimal("0.67"))
        # 2.00 / (1 - 0.67) = 2.00 / 0.33 = 6.0606...
        expected = Decimal("2.00") / Decimal("0.33")
        assert abs(price - expected) < Decimal("0.01")

    def test_margin_as_decimal(self):
        cost = Decimal("0.99")
        price = margin_price(cost, Decimal("0.75"))
        expected = Decimal("0.99") / Decimal("0.25")
        assert price == expected

    def test_margin_as_float(self):
        cost = Decimal("2.00")
        price = margin_price(cost, 0.67)
        expected = Decimal("2.00") / Decimal("0.33")
        assert abs(price - expected) < Decimal("0.01")

    def test_50_percent_margin(self):
        cost = Decimal("3.00")
        price = margin_price(cost, 0.50)
        assert price == Decimal("6.00")  # 3.00 / 0.50

    def test_margin_zero_raises(self):
        with pytest.raises(ValueError, match="Margin must be"):
            margin_price(Decimal("2.00"), 0.0)

    def test_margin_one_raises(self):
        with pytest.raises(ValueError, match="Margin must be"):
            margin_price(Decimal("2.00"), 1.0)

    def test_margin_negative_raises(self):
        with pytest.raises(ValueError, match="Margin must be"):
            margin_price(Decimal("2.00"), -0.5)

    def test_margin_above_one_raises(self):
        with pytest.raises(ValueError, match="Margin must be"):
            margin_price(Decimal("2.00"), 1.5)


class TestMultiplierPrice:
    def test_triple_multiplier(self):
        cost = Decimal("2.00")
        price = multiplier_price(cost, 3)
        assert price == Decimal("6.00")

    def test_fractional_multiplier(self):
        cost = Decimal("2.00")
        price = multiplier_price(cost, 1.5)
        assert price == Decimal("3.00")

    def test_zero_raises(self):
        with pytest.raises(ValueError, match="Multiplier must be"):
            multiplier_price(Decimal("2.00"), 0)

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="Multiplier must be"):
            multiplier_price(Decimal("2.00"), -1)


class TestPerServingPrice:
    def test_simple(self):
        total = PriceRange(min_price=Decimal("4.00"), max_price=Decimal("4.00"))
        rc = RecipeCost(
            recipe_name="Test",
            ingredient_costs=[],
            total_cost_range=total,
            cost_per_serving_range=total,
        )
        result = per_serving_price(rc, servings=4)
        assert result.min_price == Decimal("1.00")
        assert result.max_price == Decimal("1.00")

    def test_servings_zero_raises(self):
        total = PriceRange(min_price=Decimal("4.00"), max_price=Decimal("4.00"))
        rc = RecipeCost(
            recipe_name="Test",
            ingredient_costs=[],
            total_cost_range=total,
            cost_per_serving_range=total,
        )
        with pytest.raises(ValueError, match="Servings must be"):
            per_serving_price(rc, servings=0)

    def test_range_cost(self):
        total = PriceRange(min_price=Decimal("3.00"), max_price=Decimal("6.00"))
        rc = RecipeCost(
            recipe_name="Test",
            ingredient_costs=[],
            total_cost_range=total,
            cost_per_serving_range=total,
        )
        result = per_serving_price(rc, servings=3)
        assert result.min_price == Decimal("1.00")
        assert result.max_price == Decimal("2.00")

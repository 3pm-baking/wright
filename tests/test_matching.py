"""Tests for wright matching."""

from __future__ import annotations

from decimal import Decimal

import pytest

from wright.errors import IngredientNotFoundError
from wright.matching import (
    chain,
    cheapest_picker,
    find_matching_purchases,
    first_picker,
    match_all_ingredients,
    pinned_picker,
    recent_picker,
)
from wright.models import Ingredient, Purchase


@pytest.fixture
def purchases():
    return [
        Purchase(name="Sugar", quantity=1000, unit="g", price=Decimal("2.49")),
        Purchase(
            name="Sugar",
            tags="organic",
            quantity=500,
            unit="g",
            price=Decimal("3.99"),
            store="Organic Mart",
        ),
        Purchase(
            name="Butter",
            tags="unsalted",
            quantity=500,
            unit="g",
            price=Decimal("5.99"),
        ),
        Purchase(
            name="Butter",
            tags="salted",
            quantity=500,
            unit="g",
            price=Decimal("4.99"),
        ),
        Purchase(name="Flour", quantity=2000, unit="g", price=Decimal("3.99")),
    ]


class TestFindMatchingGroceries:
    def test_exact_name_match(self, purchases):
        ing = Ingredient(name="Sugar", quantity=200, unit="g")
        result = find_matching_purchases(ing, purchases)
        assert len(result) == 2
        assert all(g.name == "Sugar" for g in result)

    def test_with_require_tags(self, purchases):
        ing = Ingredient(
            name="Sugar", quantity=200, unit="g", require_tags=["organic"]
        )
        result = find_matching_purchases(ing, purchases)
        assert len(result) == 1
        assert result[0].tag_set == {"organic"}

    def test_no_match_raises(self, purchases):
        ing = Ingredient(name="Ghost Flour", quantity=100, unit="g")
        with pytest.raises(IngredientNotFoundError) as exc:
            find_matching_purchases(ing, purchases)
        assert "Ghost Flour" in str(exc.value)

    def test_tag_mismatch_raises(self, purchases):
        ing = Ingredient(
            name="Sugar", quantity=200, unit="g", require_tags=["vegan"]
        )
        with pytest.raises(IngredientNotFoundError) as exc:
            find_matching_purchases(ing, purchases)
        assert "Sugar" in str(exc.value)

    def test_works_with_protocol_compliant_objects(self):
        """Any object satisfying PurchasedItem protocol should work."""

        class MyPurchasedItem:
            def __init__(self, name, qty, unit, price):
                self.name = name
                self.tags = ""
                self.quantity = qty
                self.unit = unit
                self.price = price
                self.store = None

            @property
            def tag_set(self):
                return set()

            def matches_requirements(self, require_tags):
                return not require_tags

        g = MyPurchasedItem("Sugar", 1000, "g", Decimal("2.49"))
        ing = Ingredient(name="Sugar", quantity=200, unit="g")
        result = find_matching_purchases(ing, [g])
        assert len(result) == 1


class TestMatchAllIngredients:
    def test_multiple_ingredients(self, purchases):
        ingredients = [
            Ingredient(name="Sugar", quantity=200, unit="g"),
            Ingredient(name="Flour", quantity=300, unit="g"),
        ]
        result = match_all_ingredients(ingredients, purchases)
        assert "Sugar" in result
        assert "Flour" in result

    def test_tag_differentiation(self, purchases):
        ingredients = [
            Ingredient(
                name="Butter", quantity=100, unit="g", require_tags=["unsalted"]
            ),
            Ingredient(
                name="Butter", quantity=100, unit="g", require_tags=["salted"]
            ),
        ]
        result = match_all_ingredients(ingredients, purchases)
        # Two different keys for same name with different tags
        assert len(result) == 2
        keys = list(result.keys())
        assert any("unsalted" in k for k in keys)
        assert any("salted" in k for k in keys)

    def test_missing_raises(self, purchases):
        ingredients = [
            Ingredient(name="Sugar", quantity=200, unit="g"),
            Ingredient(name="Ghost Flour", quantity=300, unit="g"),
        ]
        with pytest.raises(IngredientNotFoundError):
            match_all_ingredients(ingredients, purchases)

    def test_empty_iterables(self):
        result = match_all_ingredients([], [])
        assert result == {}

    def test_custom_matcher(self):
        """A custom matcher is used instead of the default."""

        def fuzzy_matcher(ingredient, purchases):
            return [g for g in purchases if g.name.lower() in ingredient.name.lower()]

        ingredients = [
            Ingredient(name="organic rolled oats", quantity=50, unit="g"),
        ]
        purchases = [
            Purchase(
                name="Rolled Oats",
                quantity=1000,
                unit="g",
                price=Decimal("3.49"),
            ),
        ]
        result = match_all_ingredients(ingredients, purchases, matcher=fuzzy_matcher)
        assert len(result) == 1
        assert result["organic rolled oats"][0].name == "Rolled Oats"

    def test_custom_matcher_still_raises(self):
        """A custom matcher that raises still propagates the error."""

        def strict_matcher(ingredient, purchases):
            raise IngredientNotFoundError(ingredient.name)

        ingredients = [Ingredient(name="Ghost Flour", quantity=300, unit="g")]
        with pytest.raises(IngredientNotFoundError):
            match_all_ingredients(ingredients, [], matcher=strict_matcher)


# ── Grocery pickers ────────────────────────────────────────────────────────


class TestFirstPicker:
    def test_returns_first(self):
        a = Purchase(name="Flour", quantity=1000, unit="g", price=Decimal("3"))
        b = Purchase(name="Flour", quantity=500, unit="g", price=Decimal("2"))
        ing = Ingredient(name="Flour", quantity=300, unit="g")
        result = first_picker(ing, [a, b])
        assert result is a

    def test_empty_returns_none(self):
        ing = Ingredient(name="Flour", quantity=300, unit="g")
        assert first_picker(ing, []) is None


class TestCheapestPicker:
    def test_picks_lowest_price_per_unit(self):
        a = Purchase(name="Flour", quantity=1000, unit="g", price=Decimal("5"))
        b = Purchase(name="Flour", quantity=500, unit="g", price=Decimal("2"))
        ing = Ingredient(name="Flour", quantity=300, unit="g")
        result = cheapest_picker(ing, [a, b])
        assert result is b  # $0.004/g vs $0.005/g

    def test_empty_returns_none(self):
        ing = Ingredient(name="Flour", quantity=300, unit="g")
        assert cheapest_picker(ing, []) is None


class TestRecentPicker:
    def test_picks_most_recent_date(self):
        from datetime import date

        a = Purchase(
            name="Flour",
            quantity=1000,
            unit="g",
            price=Decimal("3"),
            purchased_date=date(2026, 1, 1),
        )
        b = Purchase(
            name="Flour",
            quantity=1000,
            unit="g",
            price=Decimal("3"),
            purchased_date=date(2026, 6, 1),
        )
        ing = Ingredient(name="Flour", quantity=300, unit="g")
        result = recent_picker(ing, [a, b])
        assert result is b

    def test_no_dates_falls_back_to_first(self):
        a = Purchase(name="Flour", quantity=1000, unit="g", price=Decimal("3"))
        b = Purchase(name="Flour", quantity=500, unit="g", price=Decimal("2"))
        ing = Ingredient(name="Flour", quantity=300, unit="g")
        result = recent_picker(ing, [a, b])
        assert result is a


class TestPinnedPicker:
    def test_pinned_item_returned(self):
        pinned_item = Purchase(
            name="Flour", quantity=1000, unit="g", price=Decimal("5")
        )
        picker = pinned_picker({"Flour": pinned_item})
        ing = Ingredient(name="Flour", quantity=300, unit="g")
        result = picker(ing, [])
        assert result is pinned_item

    def test_not_pinned_returns_none(self):
        picker = pinned_picker({})
        ing = Ingredient(name="Flour", quantity=300, unit="g")
        result = picker(ing, [])
        assert result is None


class TestChain:
    def test_returns_first_non_none(self):
        pinned = Purchase(
            name="Flour", quantity=1000, unit="g", price=Decimal("5")
        )
        cheap = Purchase(name="Flour", quantity=500, unit="g", price=Decimal("2"))
        ing = Ingredient(name="Flour", quantity=300, unit="g")

        p = chain(pinned_picker({"Flour": pinned}), cheapest_picker)
        result = p(ing, [cheap])
        assert result is pinned  # pinned wins over cheapest

    def test_falls_through(self):
        cheap = Purchase(name="Flour", quantity=500, unit="g", price=Decimal("2"))
        ing = Ingredient(name="Flour", quantity=300, unit="g")

        p = chain(pinned_picker({}), cheapest_picker)
        result = p(ing, [cheap])
        assert result is cheap  # no pinned, cheapest wins

    def test_all_none_returns_none(self):
        ing = Ingredient(name="Flour", quantity=300, unit="g")
        p = chain(pinned_picker({}), first_picker)
        result = p(ing, [])
        assert result is None

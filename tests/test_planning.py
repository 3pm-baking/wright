"""Tests for wright planning (shopping lists, cost enrichment, menu analysis)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from wright.errors import IngredientNotFoundError
from wright.models import (
    BaseIngredient,
    BaseRecipe,
    DEFAULT_CATEGORY_RULES,
    RecipeComponent,
    ServingRange,
    SimplePurchase,
)
from wright.matching import chain, cheapest_picker
from wright.planning import (
    ShoppingItem,
    ShoppingList,
    add_costs_to_shopping_list,
    analyze_menu,
    estimate_total_items,
    format_quantity,
    generate_shopping_list,
    group_shopping_items,
    normalize_volume_for_grocery,
)
from wright.session import ProductionItem, ProductionRun


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_recipes():
    return {
        "Oats": BaseRecipe(
            name="Oats",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        BaseIngredient(name="Rolled Oats", quantity=50, unit="g"),
                        BaseIngredient(name="Honey", quantity=1, unit="tbsp"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=0,
            servings=1,
        ),
        "Smoothie": BaseRecipe(
            name="Smoothie",
            components=[
                RecipeComponent(
                    name="Blend",
                    ingredients=[
                        BaseIngredient(name="Banana", quantity=1, unit="each"),
                        BaseIngredient(name="Honey", quantity=1, unit="tbsp"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=0,
            servings=1,
        ),
    }


@pytest.fixture
def sample_session():
    return ProductionRun(
        date=date(2026, 6, 1),
        production=[
            ProductionItem(recipe="Oats", quantity=1),
            ProductionItem(recipe="Smoothie", quantity=1),
        ],
        target_dates=[date(2026, 6, 2)],
    )


@pytest.fixture
def sample_groceries():
    return [
        SimplePurchase(
            name="Rolled Oats",
            quantity=1000,
            unit="g",
            price=Decimal("3.49"),
            store="Market",
        ),
        SimplePurchase(
            name="Honey",
            quantity=340,
            unit="g",
            price=Decimal("5.99"),
            store="Market",
        ),
        SimplePurchase(
            name="Banana",
            quantity=1,
            unit="each",
            price=Decimal("0.29"),
            store="Market",
        ),
    ]


@pytest.fixture
def density_data():
    return {"volume_weights": {"Honey": {"tbsp": 21.0}}}


# ── Format quantity ─────────────────────────────────────────────────────────


class TestFormatQuantity:
    def test_whole_number(self):
        assert format_quantity(5) == "5"
        assert format_quantity(5.0) == "5"

    def test_fractional(self):
        assert format_quantity(1.5) == "1.5"

    def test_many_decimals(self):
        assert format_quantity(1.33333333) == "1.3"


# ── Volume normalization ────────────────────────────────────────────────────


class TestNormalizeVolumeForGrocery:
    def test_large_volume_to_gallons(self):
        qty, unit = normalize_volume_for_grocery(4000, "ml")
        assert unit == "gallon"

    def test_non_volume_passthrough(self):
        qty, unit = normalize_volume_for_grocery(500, "g")
        assert unit == "g"

    def test_tbsp_small_amount(self):
        qty, unit = normalize_volume_for_grocery(3, "tbsp")
        assert unit in ("tbsp", "ml")


# ── Shopping list generation ────────────────────────────────────────────────


class TestGenerateShoppingList:
    def test_aggregates_ingredients(self, sample_session, sample_recipes):
        result = generate_shopping_list(sample_session, sample_recipes)
        assert isinstance(result, ShoppingList)
        assert result.date == date(2026, 6, 1)

        # Honey appears in both recipes (1 tbsp each = 2 tbsp total)
        items = result.all_items
        honey = next(i for i in items if i.name == "Honey")
        assert honey.total_quantity > 0

    def test_production_summary(self, sample_session, sample_recipes):
        result = generate_shopping_list(sample_session, sample_recipes)
        assert len(result.production_summary) == 2
        assert "Oats" in result.production_summary[0]
        assert "Smoothie" in result.production_summary[1]

    def test_target_dates(self, sample_session, sample_recipes):
        result = generate_shopping_list(sample_session, sample_recipes)
        assert result.target_dates == [date(2026, 6, 2)]

    def test_missing_recipe_raises(self, sample_recipes):
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(recipe="Ghost Cake", quantity=1)],
            target_dates=[date(2026, 6, 2)],
        )
        with pytest.raises(KeyError):
            generate_shopping_list(session, sample_recipes)

    def test_scaled_production(self, sample_recipes):
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(recipe="Oats", quantity=3)],
            target_dates=[date(2026, 6, 2)],
        )
        result = generate_shopping_list(session, sample_recipes)
        oats = next(i for i in result.all_items if i.name == "Rolled Oats")
        assert oats.total_quantity == 150  # 50 * 3


class TestEstimateTotalItems:
    def test_range_servings(self):
        recipes = {
            "Cake": BaseRecipe(
                name="Cake",
                components=[
                    RecipeComponent(
                        name="Base",
                        ingredients=[
                            BaseIngredient(name="Flour", quantity=300, unit="g"),
                        ],
                    )
                ],
                prep_time=5,
                cook_time=5,
                servings=ServingRange(min_servings=4, max_servings=8),
            ),
        }
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(recipe="Cake", quantity=2)],
            target_dates=[],
        )
        # midpoint = 6, * 2 batches = 12
        assert estimate_total_items(session, recipes) == 12

    def test_exact_servings(self):
        recipes = {
            "Cake": BaseRecipe(
                name="Cake",
                components=[
                    RecipeComponent(
                        name="Base",
                        ingredients=[
                            BaseIngredient(name="Flour", quantity=300, unit="g"),
                        ],
                    )
                ],
                prep_time=5,
                cook_time=5,
                servings=10,
            ),
        }
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(recipe="Cake", quantity=1)],
            target_dates=[],
        )
        assert estimate_total_items(session, recipes) == 10


class TestGroupShoppingItems:
    def test_categorizes(self):
        items = [
            ShoppingItem(name="Spinach", total_quantity=200, unit="g"),
            ShoppingItem(name="Butter", total_quantity=100, unit="g"),
        ]
        groups = group_shopping_items(items, category_rules=DEFAULT_CATEGORY_RULES)
        assert len(groups) == 2

    def test_kitchen_items_excluded(self):
        items = [
            ShoppingItem(name="Water", total_quantity=500, unit="ml"),
            ShoppingItem(name="Flour", total_quantity=300, unit="g"),
        ]
        groups = group_shopping_items(
            items,
            kitchen_items=frozenset({"water"}),
            category_rules=DEFAULT_CATEGORY_RULES,
        )
        all_names = [i.name for g in groups for i in g.items]
        assert "Water" not in all_names
        assert "Flour" in all_names


# ── Cost enrichment ─────────────────────────────────────────────────────────


class TestAddCostsToShoppingList:
    def test_enriches_costs(
        self, sample_session, sample_recipes, sample_groceries, density_data
    ):
        shopping = generate_shopping_list(sample_session, sample_recipes)
        enriched = add_costs_to_shopping_list(
            shopping, sample_groceries, density_data=density_data
        )
        assert len(enriched) == len(shopping.all_items)

        # Items with known grocery data should have costs
        known = [e for e in enriched if not e.missing_price]
        assert len(known) > 0
        for e in known:
            assert e.total_cost is not None
            assert e.total_cost > Decimal("0")

    def test_missing_price_flagged(
        self, sample_session, sample_recipes, sample_groceries, density_data
    ):
        # Add an ingredient with no matching grocery
        recipes_with_unknown = dict(sample_recipes)
        recipes_with_unknown["Mystery"] = BaseRecipe(
            name="Mystery",
            components=[
                RecipeComponent(
                    name="X",
                    ingredients=[
                        BaseIngredient(name="Unobtainium", quantity=1, unit="g"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=5,
        )
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[
                ProductionItem(recipe="Oats", quantity=1),
                ProductionItem(recipe="Mystery", quantity=1),
            ],
            target_dates=[],
        )
        shopping = generate_shopping_list(session, recipes_with_unknown)
        enriched = add_costs_to_shopping_list(
            shopping, sample_groceries, density_data=density_data
        )
        missing = [e for e in enriched if e.missing_price]
        assert len(missing) >= 1
        assert any("Unobtainium" in e.item.name for e in missing)


# ── Menu analysis ───────────────────────────────────────────────────────────


class TestAnalyzeMenu:
    def test_basic_analysis(self, sample_recipes, sample_groceries, density_data):
        result = analyze_menu(
            production=[ProductionItem(recipe="Oats", quantity=1)],
            recipes=sample_recipes,
            groceries=sample_groceries,
            density_data=density_data,
        )
        assert result.total_cost is not None
        assert result.total_cost > Decimal("0")
        assert len(result.missing_ingredients) == 0

    def test_missing_ingredients(self, sample_groceries):
        recipes = {
            "Mystery": BaseRecipe(
                name="Mystery",
                components=[
                    RecipeComponent(
                        name="X",
                        ingredients=[
                            BaseIngredient(name="Unobtainium", quantity=1, unit="g"),
                        ],
                    )
                ],
                prep_time=5,
                cook_time=5,
            ),
        }
        result = analyze_menu(
            production=[ProductionItem(recipe="Mystery", quantity=1)],
            recipes=recipes,
            groceries=sample_groceries,
        )
        assert result.total_cost is None
        assert "Unobtainium" in result.missing_ingredients


# ── Product reference expansion ────────────────────────────────────────────


class TestProductRefExpansion:
    """Tests that generate_shopping_list expands product_ref ingredients."""

    def test_simple_product_ref_expanded(self):
        """A recipe referencing a sub-recipe via product_ref should include
        the sub-recipe's ingredients, not the product_ref ingredient itself."""
        sub = BaseRecipe(
            name="Vanilla Sugar",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        BaseIngredient(name="Sugar", quantity=200, unit="g"),
                        BaseIngredient(name="Vanilla Bean", quantity=1, unit="each"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=0,
            net_weight_grams=200,
        )
        main = BaseRecipe(
            name="Cake",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        BaseIngredient(
                            name="Vanilla Sugar",
                            product_ref="Vanilla Sugar",
                            quantity=20,
                            unit="g",
                        ),
                        BaseIngredient(name="Flour", quantity=300, unit="g"),
                    ],
                )
            ],
            prep_time=30,
            cook_time=60,
        )
        recipes = {"Cake": main, "Vanilla Sugar": sub}
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(recipe="Cake", quantity=1)],
            target_dates=[],
        )
        result = generate_shopping_list(session, recipes)
        items = {i.name: i for i in result.all_items}

        # Sub-recipe ingredients appear, product_ref ingredient does not
        assert "Sugar" in items
        assert "Vanilla Bean" in items
        assert "Flour" in items
        assert "Vanilla Sugar" not in items

        # Quantities are scaled: 20g out of 200g yield = 0.1x scale
        assert items["Sugar"].total_quantity == pytest.approx(20.0, abs=0.1)
        assert items["Vanilla Bean"].total_quantity == pytest.approx(0.1, abs=0.01)

    def test_product_ref_missing_recipe_kept_as_is(self):
        """If the product_ref recipe is not in the index, keep the ingredient."""
        main = BaseRecipe(
            name="Cake",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        BaseIngredient(
                            name="Ghost Sugar",
                            product_ref="Ghost Sugar",
                            quantity=20,
                            unit="g",
                        ),
                    ],
                )
            ],
            prep_time=30,
            cook_time=60,
        )
        recipes = {"Cake": main}
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(recipe="Cake", quantity=1)],
            target_dates=[],
        )
        result = generate_shopping_list(session, recipes)
        items = {i.name: i for i in result.all_items}
        assert "Ghost Sugar" in items

    def test_product_ref_cycle_detected(self):
        """A → B → A cycle should not infinite loop."""
        a = BaseRecipe(
            name="A",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        BaseIngredient(
                            name="B-ref", product_ref="B", quantity=100, unit="g"
                        ),
                    ],
                )
            ],
            prep_time=5,
            cook_time=0,
            net_weight_grams=100,
        )
        b = BaseRecipe(
            name="B",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        BaseIngredient(
                            name="A-ref", product_ref="A", quantity=50, unit="g"
                        ),
                    ],
                )
            ],
            prep_time=5,
            cook_time=0,
            net_weight_grams=100,
        )
        recipes = {"A": a, "B": b}
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(recipe="A", quantity=1)],
            target_dates=[],
        )
        result = generate_shopping_list(session, recipes)
        # Should not loop infinitely — B-ref is kept as-is because visited
        items = {i.name: i for i in result.all_items}
        assert "B-ref" in items or "A-ref" in items


# ── Equivalent quantity aggregation ────────────────────────────────────────


class TestEquivalentQuantityAggregation:
    """Tests that equivalent_quantity merges packet and gram entries."""

    def test_packet_and_gram_merged(self):
        """1 packet (37g) + 74g should merge into 111g."""
        recipes = {
            "Cake": BaseRecipe(
                name="Cake",
                components=[
                    RecipeComponent(
                        name="Base",
                        ingredients=[
                            BaseIngredient(
                                name="Pudding",
                                quantity=1,
                                unit="packet",
                                equivalent_quantity=37,
                                equivalent_unit="g",
                            ),
                            BaseIngredient(
                                name="Pudding",
                                quantity=74,
                                unit="g",
                            ),
                        ],
                    )
                ],
                prep_time=5,
                cook_time=0,
            ),
        }
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(recipe="Cake", quantity=1)],
            target_dates=[],
        )
        result = generate_shopping_list(session, recipes)
        pudding = next(i for i in result.all_items if i.name == "Pudding")
        assert pudding.unit in ("g", "gram")
        assert pudding.total_quantity == pytest.approx(111.0, abs=0.1)


# ── Custom grocery matcher ─────────────────────────────────────────────────


class TestCustomMatcher:
    """Tests that custom matcher functions are injected correctly."""

    def test_add_costs_uses_custom_matcher(self, sample_session, sample_recipes):
        """A custom matcher function is used instead of the default."""
        grocery = SimplePurchase(
            name="Rolled Oats", quantity=1000, unit="g", price=Decimal("3.49")
        )

        def fuzzy_matcher(ingredient, groceries):
            """Matches if grocery name is a substring of ingredient name."""
            return [g for g in groceries if g.name.lower() in ingredient.name.lower()]

        shopping = generate_shopping_list(sample_session, sample_recipes)

        # Default matcher finds exact matches
        enriched_default = add_costs_to_shopping_list(
            shopping, [grocery], density_data={}
        )
        # Custom matcher should find at least as many matches
        enriched_custom = add_costs_to_shopping_list(
            shopping, [grocery], density_data={}, matcher=fuzzy_matcher
        )

        known_default = len([e for e in enriched_default if not e.missing_price])
        known_custom = len([e for e in enriched_custom if not e.missing_price])
        assert known_custom >= known_default

    def test_analyze_menu_passes_matcher_through(self, sample_recipes, density_data):
        """analyze_menu passes the custom matcher to add_costs_to_shopping_list."""

        def strict_matcher(ingredient, groceries):
            """Only matches exact name."""
            return [g for g in groceries if g.name == ingredient.name]

        grocery = SimplePurchase(
            name="Rolled Oats", quantity=1000, unit="g", price=Decimal("3.49")
        )
        groceries = [
            grocery,
            SimplePurchase(name="Honey", quantity=340, unit="g", price=Decimal("5.99")),
        ]

        result = analyze_menu(
            production=[ProductionItem(recipe="Oats", quantity=1)],
            recipes=sample_recipes,
            groceries=groceries,
            density_data=density_data,
            matcher=strict_matcher,
        )
        assert result.total_cost is not None
        assert result.total_cost > Decimal("0")
        assert len(result.missing_ingredients) == 0

    def test_custom_matcher_handles_no_match(self):
        """A custom matcher that raises IngredientNotFoundError propagates."""

        def picky_matcher(ingredient, groceries):
            raise IngredientNotFoundError(ingredient.name)

        recipes = {
            "Cake": BaseRecipe(
                name="Cake",
                components=[
                    RecipeComponent(
                        name="Base",
                        ingredients=[
                            BaseIngredient(name="Flour", quantity=300, unit="g"),
                        ],
                    )
                ],
                prep_time=5,
                cook_time=0,
            ),
        }
        shopping = generate_shopping_list(
            ProductionRun(
                date=date(2026, 6, 1),
                production=[ProductionItem(recipe="Cake", quantity=1)],
                target_dates=[],
            ),
            recipes,
        )
        enriched = add_costs_to_shopping_list(
            shopping, [], density_data={}, matcher=picky_matcher
        )
        assert all(e.missing_price for e in enriched)


# ── Custom grocery picker ──────────────────────────────────────────────────


class TestCustomPicker:
    def test_picker_selects_grocery(self, sample_session, sample_recipes):
        """A custom picker chooses a specific grocery from matches."""
        a = SimplePurchase(
            name="Rolled Oats",
            quantity=1000,
            unit="g",
            price=Decimal("5.00"),
            store="Fancy Store",
        )
        b = SimplePurchase(
            name="Rolled Oats",
            quantity=500,
            unit="g",
            price=Decimal("2.00"),
            store="Budget Mart",
        )

        def pick_cheapest(ingredient, groceries):
            return cheapest_picker(ingredient, groceries)

        shopping = generate_shopping_list(sample_session, sample_recipes)
        enriched = add_costs_to_shopping_list(
            shopping,
            [a, b],
            picker=pick_cheapest,
        )
        oats = next(e for e in enriched if e.item.name == "Rolled Oats")
        assert oats.store == "Budget Mart"
        assert not oats.missing_price

    def test_picker_with_chain(self, sample_session, sample_recipes):
        """Chain composes pickers that fall through."""

        def pick_nothing(ingredient, groceries):
            return None

        b = SimplePurchase(
            name="Rolled Oats",
            quantity=500,
            unit="g",
            price=Decimal("2.00"),
            store="Budget Mart",
        )
        shopping = generate_shopping_list(sample_session, sample_recipes)
        enriched = add_costs_to_shopping_list(
            shopping,
            [b],
            picker=chain(pick_nothing, cheapest_picker),
        )
        oats = next(e for e in enriched if e.item.name == "Rolled Oats")
        assert oats.store == "Budget Mart"

    def test_pinned_picker_with_analyze_menu(self, sample_recipes, density_data):
        """analyze_menu passes picker through to add_costs_to_shopping_list."""
        from wright.matching import chain, pinned_picker

        pinned = SimplePurchase(
            name="Rolled Oats",
            quantity=1000,
            unit="g",
            price=Decimal("5.00"),
            store="Pinned Store",
        )
        groceries = [
            pinned,
            SimplePurchase(name="Honey", quantity=340, unit="g", price=Decimal("5.99")),
        ]
        result = analyze_menu(
            production=[ProductionItem(recipe="Oats", quantity=1)],
            recipes=sample_recipes,
            groceries=groceries,
            density_data=density_data,
            picker=chain(pinned_picker({"Rolled Oats": pinned}), cheapest_picker),
        )
        assert result.total_cost is not None


# ── cost_items (standalone item costing) ─────────────────────────────


class TestCostIngredients:
    def test_costs_simple_items(self):
        items = [
            BaseIngredient(name="Toothpicks", quantity=1, unit="box"),
            BaseIngredient(name="Flour", quantity=500, unit="g"),
        ]
        purchases = [
            SimplePurchase(
                name="Toothpicks", quantity=5, unit="box", price=Decimal("10.00")
            ),
            SimplePurchase(
                name="Flour", quantity=1000, unit="g", price=Decimal("3.00")
            ),
        ]
        from wright.planning import cost_items

        result = cost_items(items, purchases)
        assert len(result) == 2
        tp = next(r for r in result if r.item.name == "Toothpicks")
        fl = next(r for r in result if r.item.name == "Flour")
        assert tp.total_cost == Decimal("2.00")
        assert fl.total_cost == Decimal("1.50")

    def test_missing_flagged(self):
        from wright.planning import cost_items

        items = [BaseIngredient(name="Ghost", quantity=1, unit="each")]
        result = cost_items(items, [])
        assert result[0].missing_price

    def test_with_picker(self):
        from wright.planning import cost_items

        items = [BaseIngredient(name="Flour", quantity=500, unit="g")]
        purchases = [
            SimplePurchase(
                name="Flour",
                quantity=1000,
                unit="g",
                price=Decimal("5.00"),
                store="Expensive",
            ),
            SimplePurchase(
                name="Flour",
                quantity=500,
                unit="g",
                price=Decimal("2.00"),
                store="Cheap",
            ),
        ]
        result = cost_items(items, purchases, picker=cheapest_picker)
        assert result[0].store == "Cheap"

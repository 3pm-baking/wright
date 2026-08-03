"""Tests for wright planning (shopping lists, cost enrichment, menu analysis)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from wright.errors import IngredientNotFoundError
from wright.matching import chain, cheapest_picker
from wright.models import (
    DEFAULT_CATEGORY_RULES,
    Assembly,
    Component,
    Ingredient,
    Material,
    Purchase,
    Recipe,
    RecipeComponent,
    ServingRange,
)
from wright.planning import (
    MaterialCost,
    ShoppingItemWithCost,
    ShoppingList,
    analyze_menu,
    calculate_item_costs,
    calculate_shopping_list_cost,
    cost_by_component,
    estimate_total_items,
    format_quantity,
    generate_shopping_list,
    group_shopping_items,
    normalize_metric,
    normalize_volume_us,
)
from wright.session import ProductionItem, ProductionRun
from wright.supply import SupplyItem

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_recipes():
    return [
        Recipe(
            name="Oats",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Rolled Oats", quantity=50, unit="g"),
                        Ingredient(name="Honey", quantity=1, unit="tbsp"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=0,
            servings=1,
        ),
        Recipe(
            name="Smoothie",
            components=[
                RecipeComponent(
                    name="Blend",
                    ingredients=[
                        Ingredient(name="Banana", quantity=1, unit="each"),
                        Ingredient(name="Honey", quantity=1, unit="tbsp"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=0,
            servings=1,
        ),
    ]


@pytest.fixture
def sample_session():
    return ProductionRun(
        date=date(2026, 6, 1),
        production=[
            ProductionItem(assembly="Oats", quantity=1),
            ProductionItem(assembly="Smoothie", quantity=1),
        ],
        target_dates=[date(2026, 6, 2)],
    )


@pytest.fixture
def sample_purchases():
    return [
        Purchase(
            name="Rolled Oats",
            quantity=1000,
            unit="g",
            price=Decimal("3.49"),
            store="Market",
        ),
        Purchase(
            name="Honey",
            quantity=340,
            unit="g",
            price=Decimal("5.99"),
            store="Market",
        ),
        Purchase(
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
        qty, unit = normalize_volume_us(4000, "ml")
        assert unit == "gallon"

    def test_non_volume_passthrough(self):
        qty, unit = normalize_volume_us(500, "g")
        assert unit == "g"

    def test_tbsp_small_amount(self):
        qty, unit = normalize_volume_us(3, "tbsp")
        assert unit in ("tbsp", "ml")


# ── Metric normalization (volume + weight) ─────────────────────────────────


class TestNormalizeMetric:
    @pytest.mark.parametrize(
        "quantity,unit,expected_qty,expected_unit",
        [
            # Volume: >= 1 L → L (rounded to 2 decimals)
            (2000, "ml", 2.0, "L"),
            (2, "liter", 2.0, "L"),
            (1.5, "L", 1.5, "L"),
            (1000, "ml", 1.0, "L"),
            # Volume: < 1 L → ml (rounded to 1 decimal)
            (500, "ml", 500.0, "ml"),
            (50, "ml", 50.0, "ml"),
            (999, "ml", 999.0, "ml"),
            (0.75, "L", 750.0, "ml"),
            # Weight: >= 1 kg → kg (rounded to 2 decimals)
            (2000, "g", 2.0, "kg"),
            (1500, "g", 1.5, "kg"),
            (1000, "g", 1.0, "kg"),
            # Weight: < 1 kg → g (rounded to 1 decimal)
            (500, "g", 500.0, "g"),
            (999, "g", 999.0, "g"),
            (0.3, "kg", 300.0, "g"),
            # Pass-through (non-volume, non-weight)
            (10, "each", 10, "each"),
            (3, "box", 3, "box"),
        ],
    )
    def test_normalize_metric(self, quantity, unit, expected_qty, expected_unit):
        qty, u = normalize_metric(quantity, unit)
        assert u == expected_unit
        assert qty == pytest.approx(expected_qty)


# ── Shopping list generation ────────────────────────────────────────────────


class TestGenerateShoppingList:
    def test_aggregates_ingredients(self, sample_session, sample_recipes):
        result = generate_shopping_list(sample_session, sample_recipes)
        assert isinstance(result, ShoppingList)
        assert result.date == date(2026, 6, 1)

        # Honey appears in both recipes (1 tbsp each = 2 tbsp total)
        items = result.all_items
        honey = next(i for i in items if i.name == "Honey")
        assert honey.quantity > 0

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
            production=[ProductionItem(assembly="Ghost Cake", quantity=1)],
            target_dates=[date(2026, 6, 2)],
        )
        with pytest.raises(KeyError):
            generate_shopping_list(session, sample_recipes)

    def test_scaled_production(self, sample_recipes):
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(assembly="Oats", quantity=3)],
            target_dates=[date(2026, 6, 2)],
        )
        result = generate_shopping_list(session, sample_recipes)
        oats = next(i for i in result.all_items if i.name == "Rolled Oats")
        assert oats.quantity == 150  # 50 * 3

    def test_numeric_attrs_default_empty_on_supply_item(
        self, sample_session, sample_recipes
    ):
        result = generate_shopping_list(sample_session, sample_recipes)
        for item in result.all_items:
            assert item.numeric_attrs == {}

    def test_numeric_attrs_propagates_from_material(self, sample_recipes):
        recipes = [
            Recipe(
                name="Oats",
                components=[
                    RecipeComponent(
                        name="Base",
                        ingredients=[
                            Ingredient(
                                name="Rolled Oats",
                                quantity=50,
                                unit="g",
                                numeric_attrs={"protein_g": 6.75},
                            ),
                        ],
                    )
                ],
                prep_time=5,
                cook_time=0,
                servings=1,
            ),
        ]
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(assembly="Oats", quantity=1)],
            target_dates=[date(2026, 6, 2)],
        )
        result = generate_shopping_list(session, recipes)
        oats = next(i for i in result.all_items if i.name == "Rolled Oats")
        assert oats.numeric_attrs == {"protein_g": 6.75}

    def test_numeric_attrs_merge_sum(self, sample_recipes):
        recipes = [
            Recipe(
                name="Oats",
                components=[
                    RecipeComponent(
                        name="Base",
                        ingredients=[
                            Ingredient(
                                name="Rolled Oats",
                                quantity=50,
                                unit="g",
                                numeric_attrs={"protein_g": 6.75},
                            ),
                        ],
                    )
                ],
                prep_time=5,
                cook_time=0,
                servings=1,
            ),
            Recipe(
                name="MoreOats",
                components=[
                    RecipeComponent(
                        name="Base",
                        ingredients=[
                            Ingredient(
                                name="Rolled Oats",
                                quantity=100,
                                unit="g",
                                numeric_attrs={"protein_g": 13.5},
                            ),
                        ],
                    )
                ],
                prep_time=5,
                cook_time=0,
                servings=1,
            ),
        ]
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[
                ProductionItem(assembly="Oats", quantity=1),
                ProductionItem(assembly="MoreOats", quantity=1),
            ],
            target_dates=[date(2026, 6, 2)],
        )

        def merge_sum(acc, inc):
            return {k: acc.get(k, 0) + v for k, v in inc.items()}

        result = generate_shopping_list(session, recipes, merge_numeric=merge_sum)
        oats = next(i for i in result.all_items if i.name == "Rolled Oats")
        assert oats.numeric_attrs["protein_g"] == 20.25  # 6.75 + 13.5

    def test_numeric_attrs_merge_default_first_wins(self, sample_recipes):
        recipes = [
            Recipe(
                name="Oats",
                components=[
                    RecipeComponent(
                        name="Base",
                        ingredients=[
                            Ingredient(
                                name="Rolled Oats",
                                quantity=50,
                                unit="g",
                                numeric_attrs={"shelf_life_days": 60},
                            ),
                        ],
                    )
                ],
                prep_time=5,
                cook_time=0,
                servings=1,
            ),
            Recipe(
                name="MoreOats",
                components=[
                    RecipeComponent(
                        name="Base",
                        ingredients=[
                            Ingredient(
                                name="Rolled Oats",
                                quantity=100,
                                unit="g",
                                numeric_attrs={"shelf_life_days": 30},
                            ),
                        ],
                    )
                ],
                prep_time=5,
                cook_time=0,
                servings=1,
            ),
        ]
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[
                ProductionItem(assembly="Oats", quantity=1),
                ProductionItem(assembly="MoreOats", quantity=1),
            ],
            target_dates=[date(2026, 6, 2)],
        )
        result = generate_shopping_list(session, recipes)
        oats = next(i for i in result.all_items if i.name == "Rolled Oats")
        assert oats.numeric_attrs["shelf_life_days"] == 60  # first wins


class TestEstimateTotalItems:
    def test_range_servings(self):
        recipes = [
            Recipe(
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
                servings=ServingRange(min_servings=4, max_servings=8),
            ),
        ]
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(assembly="Cake", quantity=2)],
            target_dates=[],
        )
        # midpoint = 6, * 2 batches = 12
        assert estimate_total_items(session, recipes) == 12

    def test_exact_servings(self):
        recipes = [
            Recipe(
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
                servings=10,
            ),
        ]
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(assembly="Cake", quantity=1)],
            target_dates=[],
        )
        assert estimate_total_items(session, recipes) == 10


class TestGroupShoppingItems:
    def test_categorizes(self):
        items = [
            SupplyItem(name="Spinach", quantity=200, unit="g"),
            SupplyItem(name="Butter", quantity=100, unit="g"),
        ]
        groups = group_shopping_items(items, category_rules=DEFAULT_CATEGORY_RULES)
        assert len(groups) == 2

    def test_kitchen_items_excluded(self):
        items = [
            SupplyItem(name="Water", quantity=500, unit="ml"),
            SupplyItem(name="Flour", quantity=300, unit="g"),
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
        self, sample_session, sample_recipes, sample_purchases, density_data
    ):
        shopping = generate_shopping_list(sample_session, sample_recipes)
        enriched = calculate_shopping_list_cost(
            shopping, sample_purchases, density_data=density_data
        )
        assert len(enriched) == len(shopping.all_items)

        # Items with known grocery data should have costs
        known = [e for e in enriched if not e.missing_price]
        assert len(known) > 0
        for e in known:
            assert e.total_cost is not None
            assert e.total_cost > Decimal("0")

    def test_missing_price_flagged(
        self, sample_session, sample_recipes, sample_purchases, density_data
    ):
        # Add an ingredient with no matching grocery
        recipes_with_unknown = list(sample_recipes)
        recipes_with_unknown.append(
            Recipe(
                name="Mystery",
                components=[
                    RecipeComponent(
                        name="X",
                        ingredients=[
                            Ingredient(name="Unobtainium", quantity=1, unit="g"),
                        ],
                    )
                ],
                prep_time=5,
                cook_time=5,
            )
        )
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[
                ProductionItem(assembly="Oats", quantity=1),
                ProductionItem(assembly="Mystery", quantity=1),
            ],
            target_dates=[],
        )
        shopping = generate_shopping_list(session, recipes_with_unknown)
        enriched = calculate_shopping_list_cost(
            shopping, sample_purchases, density_data=density_data
        )
        missing = [e for e in enriched if e.missing_price]
        assert len(missing) >= 1
        assert any("Unobtainium" in e.name for e in missing)


# ── Menu analysis ───────────────────────────────────────────────────────────


class TestAnalyzeMenu:
    def test_basic_analysis(self, sample_recipes, sample_purchases, density_data):
        result = analyze_menu(
            production=[ProductionItem(assembly="Oats", quantity=1)],
            assemblies=sample_recipes,
            purchases=sample_purchases,
            density_data=density_data,
        )
        assert result.total_cost is not None
        assert result.total_cost > Decimal("0")
        assert len(result.missing_ingredients) == 0

    def test_missing_ingredients(self, sample_purchases):
        recipes = [
            Recipe(
                name="Mystery",
                components=[
                    RecipeComponent(
                        name="X",
                        ingredients=[
                            Ingredient(name="Unobtainium", quantity=1, unit="g"),
                        ],
                    )
                ],
                prep_time=5,
                cook_time=5,
            ),
        ]
        result = analyze_menu(
            production=[ProductionItem(assembly="Mystery", quantity=1)],
            assemblies=recipes,
            purchases=sample_purchases,
        )
        assert result.total_cost is None
        assert "Unobtainium" in result.missing_ingredients


# ── Product reference expansion ────────────────────────────────────────────


class TestProductRefExpansion:
    """Tests that generate_shopping_list expands product_ref ingredients."""

    def test_simple_product_ref_expanded(self):
        """A recipe referencing a sub-recipe via product_ref should include
        the sub-recipe's ingredients, not the product_ref ingredient itself.
        """
        sub = Recipe(
            name="Vanilla Sugar",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Sugar", quantity=200, unit="g"),
                        Ingredient(name="Vanilla Bean", quantity=1, unit="each"),
                    ],
                )
            ],
            prep_time=5,
            cook_time=0,
            net_weight_grams=200,
        )
        main = Recipe(
            name="Cake",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(
                            name="Vanilla Sugar",
                            product_ref="Vanilla Sugar",
                            quantity=20,
                            unit="g",
                        ),
                        Ingredient(name="Flour", quantity=300, unit="g"),
                    ],
                )
            ],
            prep_time=30,
            cook_time=60,
        )
        recipes = [main, sub]
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(assembly="Cake", quantity=1)],
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
        assert items["Sugar"].quantity == pytest.approx(20.0, abs=0.1)
        assert items["Vanilla Bean"].quantity == pytest.approx(0.1, abs=0.01)

    def test_product_ref_missing_recipe_kept_as_is(self):
        """If the product_ref recipe is not in the index, keep the ingredient."""
        main = Recipe(
            name="Cake",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(
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
        recipes = [main]
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(assembly="Cake", quantity=1)],
            target_dates=[],
        )
        result = generate_shopping_list(session, recipes)
        items = {i.name: i for i in result.all_items}
        assert "Ghost Sugar" in items

    def test_product_ref_cycle_detected(self):
        """A → B → A cycle should not infinite loop."""
        a = Recipe(
            name="A",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(
                            name="B-ref", product_ref="B", quantity=100, unit="g"
                        ),
                    ],
                )
            ],
            prep_time=5,
            cook_time=0,
            net_weight_grams=100,
        )
        b = Recipe(
            name="B",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(
                            name="A-ref", product_ref="A", quantity=50, unit="g"
                        ),
                    ],
                )
            ],
            prep_time=5,
            cook_time=0,
            net_weight_grams=100,
        )
        recipes = [a, b]
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(assembly="A", quantity=1)],
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
        recipes = [
            Recipe(
                name="Cake",
                components=[
                    RecipeComponent(
                        name="Base",
                        ingredients=[
                            Ingredient(
                                name="Pudding",
                                quantity=1,
                                unit="packet",
                                equivalent_quantity=37,
                                equivalent_unit="g",
                            ),
                            Ingredient(
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
        ]
        session = ProductionRun(
            date=date(2026, 6, 1),
            production=[ProductionItem(assembly="Cake", quantity=1)],
            target_dates=[],
        )
        result = generate_shopping_list(session, recipes)
        pudding = next(i for i in result.all_items if i.name == "Pudding")
        assert pudding.unit in ("g", "gram")
        assert pudding.quantity == pytest.approx(111.0, abs=0.1)


# ── Custom grocery matcher ─────────────────────────────────────────────────


class TestCustomMatcher:
    """Tests that custom matcher functions are injected correctly."""

    def test_add_costs_uses_custom_matcher(self, sample_session, sample_recipes):
        """A custom matcher function is used instead of the default."""
        grocery = Purchase(
            name="Rolled Oats", quantity=1000, unit="g", price=Decimal("3.49")
        )

        def fuzzy_matcher(ingredient, purchases):
            """Matches if grocery name is a substring of ingredient name."""
            return [g for g in purchases if g.name.lower() in ingredient.name.lower()]

        shopping = generate_shopping_list(sample_session, sample_recipes)

        # Default matcher finds exact matches
        enriched_default = calculate_shopping_list_cost(
            shopping, [grocery], density_data={}
        )
        # Custom matcher should find at least as many matches
        enriched_custom = calculate_shopping_list_cost(
            shopping, [grocery], density_data={}, matcher=fuzzy_matcher
        )

        known_default = len([e for e in enriched_default if not e.missing_price])
        known_custom = len([e for e in enriched_custom if not e.missing_price])
        assert known_custom >= known_default

    def test_analyze_menu_passes_matcher_through(self, sample_recipes, density_data):
        """analyze_menu passes the custom matcher to calculate_shopping_list_cost."""

        def strict_matcher(ingredient, purchases):
            """Only matches exact name."""
            return [g for g in purchases if g.name == ingredient.name]

        grocery = Purchase(
            name="Rolled Oats", quantity=1000, unit="g", price=Decimal("3.49")
        )
        purchases = [
            grocery,
            Purchase(name="Honey", quantity=340, unit="g", price=Decimal("5.99")),
        ]

        result = analyze_menu(
            production=[ProductionItem(assembly="Oats", quantity=1)],
            assemblies=sample_recipes,
            purchases=purchases,
            density_data=density_data,
            matcher=strict_matcher,
        )
        assert result.total_cost is not None
        assert result.total_cost > Decimal("0")
        assert len(result.missing_ingredients) == 0

    def test_custom_matcher_handles_no_match(self):
        """A custom matcher that raises IngredientNotFoundError propagates."""

        def picky_matcher(ingredient, purchases):
            raise IngredientNotFoundError(ingredient.name)

        recipes = [
            Recipe(
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
                cook_time=0,
            ),
        ]
        shopping = generate_shopping_list(
            ProductionRun(
                date=date(2026, 6, 1),
                production=[ProductionItem(assembly="Cake", quantity=1)],
                target_dates=[],
            ),
            recipes,
        )
        enriched = calculate_shopping_list_cost(
            shopping, [], density_data={}, matcher=picky_matcher
        )
        assert all(e.missing_price for e in enriched)


# ── Custom grocery picker ──────────────────────────────────────────────────


class TestCustomPicker:
    def test_picker_selects_grocery(self, sample_session, sample_recipes):
        """A custom picker chooses a specific grocery from matches."""
        a = Purchase(
            name="Rolled Oats",
            quantity=1000,
            unit="g",
            price=Decimal("5.00"),
            store="Fancy Store",
        )
        b = Purchase(
            name="Rolled Oats",
            quantity=500,
            unit="g",
            price=Decimal("2.00"),
            store="Budget Mart",
        )

        def pick_cheapest(ingredient, purchases):
            return cheapest_picker(ingredient, purchases)

        shopping = generate_shopping_list(sample_session, sample_recipes)
        enriched = calculate_shopping_list_cost(
            shopping,
            [a, b],
            picker=pick_cheapest,
        )
        oats = next(e for e in enriched if e.name == "Rolled Oats")
        assert oats.store == "Budget Mart"
        assert not oats.missing_price

    def test_picker_with_chain(self, sample_session, sample_recipes):
        """Chain composes pickers that fall through."""

        def pick_nothing(ingredient, purchases):
            return None

        b = Purchase(
            name="Rolled Oats",
            quantity=500,
            unit="g",
            price=Decimal("2.00"),
            store="Budget Mart",
        )
        shopping = generate_shopping_list(sample_session, sample_recipes)
        enriched = calculate_shopping_list_cost(
            shopping,
            [b],
            picker=chain(pick_nothing, cheapest_picker),
        )
        oats = next(e for e in enriched if e.name == "Rolled Oats")
        assert oats.store == "Budget Mart"

    def test_pinned_picker_with_analyze_menu(self, sample_recipes, density_data):
        """analyze_menu passes picker through to calculate_shopping_list_cost."""
        from wright.matching import chain, pinned_picker

        pinned = Purchase(
            name="Rolled Oats",
            quantity=1000,
            unit="g",
            price=Decimal("5.00"),
            store="Pinned Store",
        )
        purchases = [
            pinned,
            Purchase(name="Honey", quantity=340, unit="g", price=Decimal("5.99")),
        ]
        result = analyze_menu(
            production=[ProductionItem(assembly="Oats", quantity=1)],
            assemblies=sample_recipes,
            purchases=purchases,
            density_data=density_data,
            picker=chain(pinned_picker({"Rolled Oats": pinned}), cheapest_picker),
        )
        assert result.total_cost is not None


# ── calculate_item_costs (standalone item costing) ─────────────────────────────


class TestCostIngredients:
    def test_costs_simple_items(self):
        items = [
            Ingredient(name="Toothpicks", quantity=1, unit="box"),
            Ingredient(name="Flour", quantity=500, unit="g"),
        ]
        purchases = [
            Purchase(name="Toothpicks", quantity=5, unit="box", price=Decimal("10.00")),
            Purchase(name="Flour", quantity=1000, unit="g", price=Decimal("3.00")),
        ]
        from wright.planning import calculate_item_costs

        result = calculate_item_costs(items, purchases)
        assert len(result) == 2
        tp = next(r for r in result if r.name == "Toothpicks")
        fl = next(r for r in result if r.name == "Flour")
        assert tp.total_cost == Decimal("2.00")
        assert fl.total_cost == Decimal("1.50")

    def test_missing_flagged(self):
        items = [Ingredient(name="Ghost", quantity=1, unit="each")]
        result = calculate_item_costs(items, [])
        assert result[0].missing_price

    def test_with_picker(self):
        items = [Ingredient(name="Flour", quantity=500, unit="g")]
        purchases = [
            Purchase(
                name="Flour",
                quantity=1000,
                unit="g",
                price=Decimal("5.00"),
                store="Expensive",
            ),
            Purchase(
                name="Flour",
                quantity=500,
                unit="g",
                price=Decimal("2.00"),
                store="Cheap",
            ),
        ]
        result = calculate_item_costs(items, purchases, picker=cheapest_picker)
        assert result[0].store == "Cheap"


# ── MaterialCost properties and alias ───────────────────────────────────────


class TestMaterialCost:
    @pytest.mark.parametrize(
        "attr,expected",
        [
            ("name", "Barley"),
            ("quantity", 10.0),
            ("unit", "lb"),
            ("tags", ["organic"]),
        ],
    )
    def test_delegating_properties(self, attr, expected):
        item = SupplyItem(name="Barley", quantity=10.0, unit="lb", tags=["organic"])
        cost = MaterialCost(
            item=item,
            price_per_unit=Decimal("2.00"),
            price_unit="lb",
            total_cost=Decimal("20.00"),
            store="Market",
            purchase_date=date(2026, 6, 1),
            missing_price=False,
        )
        assert getattr(cost, attr) == expected

    def test_backward_compat_alias(self):
        assert ShoppingItemWithCost is MaterialCost


# ── per_unit scaling in calculate_item_costs ────────────────────────────────


class TestCalculateItemCostsPerUnit:
    @pytest.mark.parametrize(
        "mat_qty,mat_unit,per_qty,per_unit_str,expected",
        [
            (10, "lb", 1, "lb", Decimal("2.00")),
            (10, "lb", 12, "oz", Decimal("1.50")),
        ],
    )
    def test_per_unit_scaling(self, mat_qty, mat_unit, per_qty, per_unit_str, expected):
        items = [Ingredient(name="Barley", quantity=mat_qty, unit=mat_unit)]
        purchases = [
            Purchase(
                name="Barley", quantity=mat_qty, unit=mat_unit, price=Decimal("20.00")
            ),
        ]
        result = calculate_item_costs(
            items, purchases, per_unit=(per_qty, per_unit_str)
        )
        assert len(result) == 1
        assert result[0].total_cost == expected

    @pytest.mark.parametrize(
        "scenario,items,purchases,per_unit",
        [
            (
                "missing_price",
                [Ingredient(name="Ghost", quantity=10, unit="lb")],
                [],
                (1, "lb"),
            ),
            (
                "incompatible_units",
                [Ingredient(name="Cement", quantity=10, unit="lb")],
                [
                    Purchase(
                        name="Cement", quantity=10, unit="lb", price=Decimal("20.00")
                    )
                ],
                (1, "each"),
            ),
        ],
    )
    def test_per_unit_edge_cases(self, scenario, items, purchases, per_unit):
        result = calculate_item_costs(items, purchases, per_unit=per_unit)
        assert len(result) == 1

    def test_per_unit_not_provided(self):
        items = [Ingredient(name="Barley", quantity=10, unit="lb")]
        purchases = [
            Purchase(name="Barley", quantity=10, unit="lb", price=Decimal("20.00")),
        ]
        without = calculate_item_costs(items, purchases)
        with_none = calculate_item_costs(items, purchases, per_unit=None)
        assert without[0].total_cost == with_none[0].total_cost

    def test_per_unit_preserves_fields(self):
        items = [Ingredient(name="Barley", quantity=10, unit="lb")]
        purchases = [
            Purchase(
                name="Barley",
                quantity=10,
                unit="lb",
                price=Decimal("20.00"),
                store="Grain Co",
            ),
        ]
        without = calculate_item_costs(items, purchases)
        with_per = calculate_item_costs(items, purchases, per_unit=(1, "lb"))
        assert with_per[0].store == without[0].store
        assert with_per[0].price_per_unit == without[0].price_per_unit
        assert with_per[0].price_unit == without[0].price_unit


# ── Component-level cost rollup ─────────────────────────────────────────────


class TestCostByComponent:
    @pytest.mark.parametrize(
        "assembly,expected",
        [
            (
                Assembly(
                    name="Beverage",
                    components=[
                        Component(
                            name="Ingredients",
                            materials=[
                                Material(name="Barley", quantity=10, unit="lb"),
                                Material(name="Hops", quantity=4, unit="oz"),
                            ],
                        ),
                        Component(
                            name="Packaging",
                            materials=[
                                Material(name="Bottle", quantity=24, unit="each"),
                            ],
                        ),
                    ],
                ),
                {"Ingredients": Decimal("25.00"), "Packaging": Decimal("12.00")},
            ),
            (
                Assembly(
                    name="Single",
                    components=[
                        Component(
                            name="Solo",
                            materials=[
                                Material(name="Barley", quantity=10, unit="lb"),
                            ],
                        ),
                    ],
                ),
                {"Solo": Decimal("20.00")},
            ),
        ],
    )
    def test_cost_breakdown(self, assembly, expected):
        purchases = [
            Purchase(name="Barley", quantity=10, unit="lb", price=Decimal("20.00")),
            Purchase(name="Hops", quantity=4, unit="oz", price=Decimal("5.00")),
            Purchase(name="Bottle", quantity=24, unit="each", price=Decimal("12.00")),
        ]
        result = cost_by_component(assembly, purchases)
        assert result == expected

    @pytest.mark.parametrize(
        "assembly,expected",
        [
            (Assembly(name="Empty"), {}),
            (
                Assembly(
                    name="WithComponents",
                    components=[Component(name="Dry", materials=[])],
                ),
                {"Dry": Decimal("0")},
            ),
        ],
    )
    def test_empty_edge_cases(self, assembly, expected):
        result = cost_by_component(assembly, [])
        assert result == expected

    def test_mixed_priced_and_missing(self):
        assembly = Assembly(
            name="Brew",
            components=[
                Component(
                    name="Ingredients",
                    materials=[
                        Material(name="Barley", quantity=10, unit="lb"),
                        Material(name="Ghost", quantity=1, unit="each"),
                    ],
                ),
            ],
        )
        purchases = [
            Purchase(name="Barley", quantity=10, unit="lb", price=Decimal("20.00")),
        ]
        result = cost_by_component(assembly, purchases)
        assert result["Ingredients"] == Decimal("20.00")

    def test_picker_passes_through(self):
        assembly = Assembly(
            name="Brew",
            components=[
                Component(
                    name="Ingredients",
                    materials=[
                        Material(name="Barley", quantity=10, unit="lb"),
                    ],
                ),
            ],
        )
        purchases = [
            Purchase(
                name="Barley",
                quantity=10,
                unit="lb",
                price=Decimal("20.00"),
                store="Cheap",
            ),
            Purchase(
                name="Barley",
                quantity=10,
                unit="lb",
                price=Decimal("30.00"),
                store="Pricey",
            ),
        ]
        result = cost_by_component(assembly, purchases, picker=cheapest_picker)
        assert result["Ingredients"] == Decimal("20.00")

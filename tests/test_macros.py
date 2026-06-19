"""Tests for wright macro calculation."""

from __future__ import annotations

import pytest

from wright.macros import calculate_recipe_macros
from wright.models import (
    Ingredient,
    MacroPerServing,
    NutritionInfo,
    NutritionRegistry,
    Recipe,
    RecipeComponent,
    ServingRange,
)

# ── NutritionInfo tests ──────────────────────────────────────────────────────


class TestNutritionInfo:
    def test_computed_kcal_from_macros(self):
        n = NutritionInfo(protein_g=10, carbs_g=20, fat_g=5, fiber_g=2)
        # 10*4 + 20*4 + 5*9 + 2*2 = 40 + 80 + 45 + 4 = 169
        assert n.computed_kcal == 169.0
        assert n.effective_kcal == 169.0

    def test_explicit_kcal_overrides_computed(self):
        n = NutritionInfo(protein_g=10, carbs_g=20, fat_g=5, fiber_g=2, kcal=200)
        assert n.computed_kcal == 169.0
        assert n.effective_kcal == 200.0

    def test_zero_macros(self):
        n = NutritionInfo()
        assert n.computed_kcal == 0.0
        assert n.effective_kcal == 0.0

    def test_fiber_contributes_at_2kcal_per_gram(self):
        n = NutritionInfo(fiber_g=10)
        assert n.computed_kcal == 20.0  # 10 * 2


# ── NutritionRegistry ────────────────────────────────────────────────────────


@pytest.fixture
def oats_nutrition():
    return NutritionInfo(
        protein_g=13.5, carbs_g=66.3, fat_g=6.5, fiber_g=10.6, kcal=389
    )


@pytest.fixture
def yogurt_nutrition():
    return NutritionInfo(protein_g=10.0, carbs_g=3.6, fat_g=0.7, fiber_g=0, kcal=59)


@pytest.fixture
def honey_nutrition():
    return NutritionInfo(protein_g=0.3, carbs_g=82.4, fat_g=0, fiber_g=0, kcal=304)


@pytest.fixture
def chia_nutrition():
    return NutritionInfo(
        protein_g=16.5, carbs_g=42.1, fat_g=30.7, fiber_g=34.4, kcal=486
    )


@pytest.fixture
def overnight_registry(
    oats_nutrition, yogurt_nutrition, honey_nutrition, chia_nutrition
) -> NutritionRegistry:
    return {
        "Rolled Oats": oats_nutrition,
        "Greek Yogurt": yogurt_nutrition,
        "Honey": honey_nutrition,
        "Chia Seeds": chia_nutrition,
    }


@pytest.fixture
def simple_recipe():
    """Overnight Oats — 1 serving, 50g oats, 100g yogurt, 1tbsp honey, 1tbsp chia."""
    return Recipe(
        name="Overnight Oats",
        components=[
            RecipeComponent(
                name="Base",
                ingredients=[
                    Ingredient(name="Rolled Oats", quantity=50, unit="g"),
                    Ingredient(name="Greek Yogurt", quantity=100, unit="g"),
                    Ingredient(name="Honey", quantity=1, unit="tbsp"),
                    Ingredient(name="Chia Seeds", quantity=1, unit="tbsp"),
                ],
            ),
        ],
        prep_time=5,
        cook_time=0,
        servings=1,
    )


@pytest.fixture
def pie_crust_registry() -> NutritionRegistry:
    return {
        "Flour": NutritionInfo(
            protein_g=10.0, carbs_g=76.0, fat_g=1.0, fiber_g=2.7, kcal=364
        ),
        "Butter": NutritionInfo(
            protein_g=0.9, carbs_g=0.1, fat_g=81.0, fiber_g=0, kcal=717
        ),
    }


@pytest.fixture
def pie_crust_recipe():
    """A sub-recipe used via product_ref."""
    return Recipe(
        name="Pie Crust",
        components=[
            RecipeComponent(
                name="Crust",
                ingredients=[
                    Ingredient(name="Flour", quantity=250, unit="g"),
                    Ingredient(name="Butter", quantity=100, unit="g"),
                    Ingredient(name="Salt", quantity=2, unit="g"),
                ],
            ),
        ],
        prep_time=15,
        cook_time=0,
        servings=None,
        net_weight_grams=352,
    )


@pytest.fixture
def pie_apple_registry() -> NutritionRegistry:
    return {
        "Apple": NutritionInfo(
            protein_g=0.3, carbs_g=13.8, fat_g=0.2, fiber_g=2.4, kcal=52
        ),
    }


@pytest.fixture
def pie_recipe(pie_crust_recipe):
    """A recipe that references Pie Crust via product_ref (50g of crust filling)."""
    return Recipe(
        name="Mini Pie",
        components=[
            RecipeComponent(
                name="Filling",
                ingredients=[
                    Ingredient(
                        name="Pie Filling",
                        quantity=50,
                        unit="g",
                        product_ref="Pie Crust",
                    ),
                    Ingredient(name="Apple", quantity=200, unit="g"),
                ],
            ),
        ],
        prep_time=10,
        cook_time=30,
        servings=2,
    )


# ── calculate_recipe_macros tests ────────────────────────────────────────────


class TestCalculateRecipeMacros:
    def test_simple_recipe(self, simple_recipe, overnight_registry):
        density_data = {
            "volume_weights": {
                "Honey": {"tbsp": 21.0},
                "Chia Seeds": {"tbsp": 12.0},
            },
        }
        result = calculate_recipe_macros(
            simple_recipe,
            nutrition_registry=overnight_registry,
            density_data=density_data,
        )

        assert result.recipe_name == "Overnight Oats"
        assert result.servings_used == 1
        assert result.per_serving is not None

        # Rolled Oats: 50g, per 100g: 13.5p, 66.3c, 6.5f, 10.6fib, 389kcal
        #   → 0.5 * each = 6.75p, 33.15c, 3.25f, 5.3fib, 194.5kcal
        # Greek Yogurt: 100g, per 100g: 10.0p, 3.6c, 0.7f, 0fib, 59kcal
        #   → 1.0 * each = 10.0p, 3.6c, 0.7f, 0fib, 59kcal
        # Honey: 1 tbsp ~= 21g, per 100g: 0.3p, 82.4c, 0f, 0fib, 304kcal
        #   → 0.21 * each ≈ 0.06p, 17.30c, 0f, 0fib, 63.84kcal
        # Chia: 1 tbsp ~= 12g (from density), per 100g: 16.5p, 42.1c, 30.7f, 34.4fib, 486kcal
        #   → 0.12 * each ≈ 1.98p, 5.05c, 3.68f, 4.13fib, 58.32kcal

        # Totals (approximate):
        # protein: 6.75 + 10.0 + 0.06 + 1.98 ≈ 18.79 → 18.79
        # carbs:   33.15 + 3.6 + 17.30 + 5.05 ≈ 59.10
        # fat:     3.25 + 0.7 + 0 + 3.68 ≈ 7.63
        # fiber:   5.3 + 0 + 0 + 4.13 ≈ 9.43
        # kcal:    194.5 + 59 + 63.84 + 58.32 ≈ 375.66

        assert result.total.protein_g == pytest.approx(18.79, abs=0.2)
        assert result.total.carbs_g == pytest.approx(59.10, abs=0.2)
        assert result.total.fat_g == pytest.approx(7.63, abs=0.2)
        assert result.total.fiber_g == pytest.approx(9.43, abs=0.2)
        assert result.total.kcal == pytest.approx(375.7, abs=0.5)

        # Per-serving is same as total for 1 serving
        assert result.per_serving.protein_g == result.total.protein_g
        assert result.per_serving.kcal == result.total.kcal

    def test_recipe_with_product_ref(
        self, pie_recipe, pie_crust_recipe, pie_crust_registry, pie_apple_registry
    ):
        """Test recursive macro calculation via product_ref."""
        combined_registry: NutritionRegistry = {
            **pie_crust_registry,
            **pie_apple_registry,
        }
        result = calculate_recipe_macros(
            pie_recipe,
            nutrition_registry=combined_registry,
            recipe_index={"Pie Crust": pie_crust_recipe},
        )

        assert result.recipe_name == "Mini Pie"
        assert result.servings_used == 2

        # Pie Crust total for 352g net_weight_grams:
        #   Flour 250g: per 100g 10p, 76c, 1f, 2.7fib, 364kcal
        #     → 2.5 * each = 25p, 190c, 2.5f, 6.75fib, 910kcal
        #   Butter 100g: per 100g 0.9p, 0.1c, 81f, 0fib, 717kcal
        #     → 1.0 * each = 0.9p, 0.1c, 81f, 0fib, 717kcal
        #   Salt 2g: no nutrition, skipped
        #   Crust total: 25.9p, 190.1c, 83.5f, 6.75fib, 1627kcal
        #
        # Per gram of crust: 25.9/352 ≈ 0.0736p, 190.1/352 ≈ 0.5401c, etc.
        #
        # Ingredient: Pie Filling 50g of crust → scale by 50/352 = 0.1420
        #   protein: 25.9 * 0.1420 ≈ 3.68
        #   carbs:   190.1 * 0.1420 ≈ 26.99
        #   fat:     83.5 * 0.1420 ≈ 11.86
        #   fiber:   6.75 * 0.1420 ≈ 0.96
        #   kcal:    1627 * 0.1420 ≈ 231.03
        #
        # Apple 200g: per 100g 0.3p, 13.8c, 0.2f, 2.4fib, 52kcal
        #   → 2.0 * each = 0.6p, 27.6c, 0.4f, 4.8fib, 104kcal
        #
        # Total: 4.28p, 54.59c, 12.26f, 5.76fib, 335.0kcal
        # Per serving (/2): 2.14p, 27.30c, 6.13f, 2.88fib, 167.5kcal

        assert result.total.protein_g == pytest.approx(4.28, abs=0.3)
        assert result.total.carbs_g == pytest.approx(54.59, abs=0.3)
        assert result.total.fat_g == pytest.approx(12.26, abs=0.3)
        assert result.total.kcal == pytest.approx(335.0, abs=1.0)

        assert result.per_serving.protein_g == pytest.approx(2.14, abs=0.2)
        assert result.per_serving.kcal == pytest.approx(167.5, abs=0.5)

    def test_with_nutrition_lookup(self):
        """Test callback-based nutrition lookup (secondary fallback)."""
        recipe = Recipe(
            name="Simple Bowl",
            components=[
                RecipeComponent(
                    name="Base",
                    ingredients=[
                        Ingredient(name="Quinoa", quantity=200, unit="g"),
                        Ingredient(name="Chicken", quantity=150, unit="g"),
                    ],
                ),
            ],
            prep_time=5,
            cook_time=15,
            servings=2,
        )

        def lookup(name: str) -> NutritionInfo | None:
            data = {
                "Quinoa": NutritionInfo(
                    protein_g=14.1, carbs_g=64.2, fat_g=6.1, fiber_g=7.0, kcal=368
                ),
                "Chicken": NutritionInfo(
                    protein_g=31.0, carbs_g=0, fat_g=3.6, fiber_g=0, kcal=165
                ),
            }
            return data.get(name)

        result = calculate_recipe_macros(recipe, ingredient_nutrition_lookup=lookup)

        # Quinoa 200g = 2 * 100g: 28.2p, 128.4c, 12.2f, 14.0fib, 736kcal
        # Chicken 150g = 1.5 * 100g: 46.5p, 0c, 5.4f, 0fib, 247.5kcal
        # Total: 74.7p, 128.4c, 17.6f, 14.0fib, 983.5kcal

        assert result.total.protein_g == pytest.approx(74.7, abs=0.2)
        assert result.total.carbs_g == pytest.approx(128.4, abs=0.2)
        assert result.total.fat_g == pytest.approx(17.6, abs=0.2)
        assert result.total.kcal == pytest.approx(983.5, abs=0.5)

        # Per serving (/2): 37.35p, 64.2c, 8.8f, 7.0fib, 491.8kcal
        assert result.per_serving.protein_g == pytest.approx(37.35, abs=0.2)
        assert result.per_serving.fiber_g == pytest.approx(7.0, abs=0.1)
        assert result.per_serving.kcal == pytest.approx(491.8, abs=0.5)

    def test_registry_takes_priority_over_callback(self, oats_nutrition):
        """Registry entry wins when both registry and callback have data."""
        registry: NutritionRegistry = {
            "HasRegistry": oats_nutrition,
        }

        def lookup(name: str) -> NutritionInfo | None:
            return NutritionInfo(
                protein_g=99, carbs_g=99, fat_g=99, fiber_g=99, kcal=999
            )

        recipe = Recipe(
            name="Priority Test",
            components=[
                RecipeComponent(
                    name="A",
                    ingredients=[
                        Ingredient(name="HasRegistry", quantity=100, unit="g"),
                        Ingredient(name="FromCallback", quantity=100, unit="g"),
                    ],
                ),
            ],
            prep_time=1,
            cook_time=1,
            servings=1,
        )

        result = calculate_recipe_macros(
            recipe,
            nutrition_registry=registry,
            ingredient_nutrition_lookup=lookup,
        )

        # HasRegistry uses oats_nutrition (13.5p) from registry
        # FromCallback uses 99p from callback (no registry entry)
        assert result.total.protein_g == pytest.approx(13.5 + 99, abs=0.1)

    def test_byproduct_and_zero_quantity_skipped(self, oats_nutrition):
        """Byproduct and zero-quantity ingredients contribute zero macros."""
        registry: NutritionRegistry = {
            "Active": oats_nutrition,
            "Skipped": oats_nutrition,
            "Zero": oats_nutrition,
        }
        recipe = Recipe(
            name="Test",
            components=[
                RecipeComponent(
                    name="A",
                    ingredients=[
                        Ingredient(name="Active", quantity=100, unit="g"),
                        Ingredient(
                            name="Skipped",
                            quantity=50,
                            unit="g",
                            byproduct=True,
                        ),
                        Ingredient(name="Zero", quantity=0, unit="g"),
                    ],
                ),
            ],
            prep_time=1,
            cook_time=1,
            servings=1,
        )

        result = calculate_recipe_macros(recipe, nutrition_registry=registry)
        # Only Active contributes: 100g = 1 * 100g portion of oats nutrition
        assert result.total.protein_g == pytest.approx(13.5, abs=0.1)
        assert result.total.carbs_g == pytest.approx(66.3, abs=0.1)

    def test_no_serving_info(self):
        """Recipe with servings=None — per_serving is None."""
        registry: NutritionRegistry = {
            "Oats": NutritionInfo(
                protein_g=13.5,
                carbs_g=66.3,
                fat_g=6.5,
                fiber_g=10.6,
                kcal=389,
            ),
        }
        recipe = Recipe(
            name="Bulk Batch",
            components=[
                RecipeComponent(
                    name="Mix",
                    ingredients=[
                        Ingredient(name="Oats", quantity=500, unit="g"),
                    ],
                ),
            ],
            prep_time=1,
            cook_time=1,
            servings=None,
        )

        result = calculate_recipe_macros(recipe, nutrition_registry=registry)
        assert result.per_serving is None
        assert result.servings_used is None
        assert result.total.protein_g == pytest.approx(67.5, abs=0.1)  # 500g * 13.5/100

    def test_missing_recipe_in_product_ref_skipped(self):
        """Missing recipe_index entry — recipe is silently skipped."""
        recipe = Recipe(
            name="Test",
            components=[
                RecipeComponent(
                    name="A",
                    ingredients=[
                        Ingredient(
                            name="Unknown Sub",
                            quantity=100,
                            unit="g",
                            product_ref="Nonexistent Recipe",
                        ),
                    ],
                ),
            ],
            prep_time=1,
            cook_time=1,
            servings=1,
        )

        result = calculate_recipe_macros(recipe)
        assert result.total.protein_g == 0.0

    def test_product_ref_missing_net_weight_skipped(self):
        """Sub-recipe without net_weight_grams — skip gracefully."""
        registry: NutritionRegistry = {
            "Flour": NutritionInfo(
                protein_g=10, carbs_g=76, fat_g=1, fiber_g=2.7, kcal=364
            ),
        }
        sub = Recipe(
            name="Sub",
            components=[
                RecipeComponent(
                    name="A",
                    ingredients=[
                        Ingredient(name="Flour", quantity=100, unit="g"),
                    ],
                ),
            ],
            prep_time=1,
            cook_time=1,
            servings=None,
            net_weight_grams=None,
        )

        recipe = Recipe(
            name="Main",
            components=[
                RecipeComponent(
                    name="A",
                    ingredients=[
                        Ingredient(
                            name="Sub Filling",
                            quantity=30,
                            unit="g",
                            product_ref="Sub",
                        ),
                    ],
                ),
            ],
            prep_time=1,
            cook_time=1,
            servings=1,
        )

        result = calculate_recipe_macros(
            recipe,
            nutrition_registry=registry,
            recipe_index={"Sub": sub},
        )
        assert result.total.protein_g == 0.0

    def test_serving_range_uses_midpoint(self):
        """ServingRange uses midpoint for per-serving calculation."""
        registry: NutritionRegistry = {
            "Oats": NutritionInfo(protein_g=10, carbs_g=0, fat_g=0, fiber_g=0, kcal=40),
        }
        recipe = Recipe(
            name="Batch",
            components=[
                RecipeComponent(
                    name="A",
                    ingredients=[
                        Ingredient(name="Oats", quantity=100, unit="g"),
                    ],
                ),
            ],
            prep_time=1,
            cook_time=1,
            servings=ServingRange(min_servings=4, max_servings=6),
        )

        result = calculate_recipe_macros(recipe, nutrition_registry=registry)
        # Midpoint = 5 servings
        assert result.servings_used == 5
        # Total protein = 100g * (10/100) = 10g
        assert result.total.protein_g == 10.0
        # Per serving = 10g / 5 = 2g
        assert result.per_serving.protein_g == 2.0


# ── MacroPerServing arithmetic tests ─────────────────────────────────────────


class TestMacroPerServingArithmetic:
    def test_add(self):
        a = MacroPerServing(protein_g=10, carbs_g=20, fat_g=5, fiber_g=3, kcal=200)
        b = MacroPerServing(protein_g=5, carbs_g=10, fat_g=2, fiber_g=1, kcal=100)
        c = a + b
        assert c.protein_g == 15
        assert c.carbs_g == 30
        assert c.fat_g == 7
        assert c.fiber_g == 4
        assert c.kcal == 300

    def test_mul(self):
        a = MacroPerServing(protein_g=10, carbs_g=20, fat_g=5, fiber_g=3, kcal=200)
        b = a * 3
        assert b.protein_g == 30
        assert b.carbs_g == 60
        assert b.fat_g == 15
        assert b.fiber_g == 9
        assert b.kcal == 600

    def test_rmul(self):
        a = MacroPerServing(protein_g=10, carbs_g=20, fat_g=5, fiber_g=3, kcal=200)
        b = 0.5 * a
        assert b.protein_g == 5
        assert b.carbs_g == 10
        assert b.fat_g == 2.5
        assert b.fiber_g == 1.5
        assert b.kcal == 100

    def test_zero(self):
        z = MacroPerServing.zero()
        assert z.protein_g == 0
        assert z.carbs_g == 0
        assert z.fat_g == 0
        assert z.fiber_g == 0
        assert z.kcal == 0

    def test_sum_with_zero(self):
        items = [
            MacroPerServing(protein_g=10, carbs_g=20, fat_g=5, fiber_g=3, kcal=200),
            MacroPerServing(protein_g=5, carbs_g=10, fat_g=2, fiber_g=1, kcal=100),
            MacroPerServing(protein_g=2, carbs_g=0, fat_g=1, fiber_g=0, kcal=20),
        ]
        total = sum(items, start=MacroPerServing.zero())
        assert total.protein_g == 17
        assert total.carbs_g == 30
        assert total.fat_g == 8
        assert total.fiber_g == 4
        assert total.kcal == 320

    def test_chained_scale_and_add(self):
        a = MacroPerServing(protein_g=20, carbs_g=30, fat_g=10, fiber_g=5, kcal=300)
        total = a * 3 + a * 2
        # 3 * a + 2 * a = 5 * a
        assert total.protein_g == 100
        assert total.carbs_g == 150
        assert total.fat_g == 50
        assert total.fiber_g == 25
        assert total.kcal == 1500

    def test_truediv(self):
        a = MacroPerServing(protein_g=30, carbs_g=60, fat_g=15, fiber_g=9, kcal=600)
        b = a / 3
        assert b.protein_g == 10
        assert b.carbs_g == 20
        assert b.fat_g == 5
        assert b.fiber_g == 3
        assert b.kcal == 200

    def test_truediv_fractional(self):
        a = MacroPerServing(protein_g=10, carbs_g=20, fat_g=5, fiber_g=3, kcal=200)
        b = a / 3
        assert b.protein_g == pytest.approx(3.333, abs=0.01)
        assert b.kcal == pytest.approx(66.667, abs=0.01)


# ── RecipeMacros arithmetic tests ────────────────────────────────────────────


class TestRecipeMacrosArithmetic:
    def test_mul_scales_total(self):
        from wright.models import RecipeMacros

        rm = RecipeMacros(
            recipe_name="Test",
            total=MacroPerServing(protein_g=10, carbs_g=20, fat_g=5, fiber_g=3, kcal=200),
            servings_used=2,
        )
        scaled = rm * 3
        assert scaled.recipe_name == "Test"
        assert scaled.total.protein_g == 30
        assert scaled.total.carbs_g == 60
        assert scaled.total.fat_g == 15
        assert scaled.total.kcal == 600
        # per_serving is derived: 30/2=15, 600/2=300
        assert scaled.per_serving.protein_g == 15
        assert scaled.per_serving.kcal == 300
        assert scaled.servings_used == 2

    def test_mul_preserves_none_per_serving(self):
        from wright.models import RecipeMacros

        rm = RecipeMacros(
            recipe_name="Bulk",
            total=MacroPerServing(protein_g=50, carbs_g=100, fat_g=20, fiber_g=8, kcal=800),
            servings_used=None,
        )
        scaled = rm * 0.5
        assert scaled.total.protein_g == 25
        assert scaled.per_serving is None
        assert scaled.servings_used is None

    def test_per_serving_derived(self):
        """per_serving is computed from total / servings_used."""
        from wright.models import RecipeMacros

        rm = RecipeMacros(
            recipe_name="Derived",
            total=MacroPerServing(protein_g=30, carbs_g=90, fat_g=15, fiber_g=9, kcal=600),
            servings_used=3,
        )
        assert rm.per_serving.protein_g == 10
        assert rm.per_serving.carbs_g == 30
        assert rm.per_serving.fat_g == 5
        assert rm.per_serving.fiber_g == 3
        assert rm.per_serving.kcal == 200

"""Macro calculation logic — pure functions, no file I/O.

Recursive ``product_ref`` support mirrors the costing module.
"""

from __future__ import annotations

from typing import Callable, Mapping

from wright.costing import convert_with_density, ingredient_to_grams
from wright.models import (
    BaseIngredient,
    BaseRecipe,
    MacroPerServing,
    NutritionInfo,
    NutritionRegistry,
    RecipeMacros,
    Servings,
)

# ---------------------------------------------------------------------------
# Gram conversion (delegates to costing.ingredient_to_grams, adds density)
# ---------------------------------------------------------------------------


def _ingredient_grams(
    ingredient: BaseIngredient,
    density_data: dict | None = None,
) -> float:
    """Return gram quantity for an ingredient, or ``0.0`` if not determinable.

    Delegates packet-unit and weight-unit resolution to
    :func:`~wright.costing.ingredient_to_grams`, then falls back to
    density-based volume → weight conversion.
    """
    density_data = density_data or {}

    # Let costing handle packets and direct weight conversion
    grams = ingredient_to_grams(ingredient, raise_on_error=False)
    if grams > 0:
        return grams

    # Try volume → weight via density
    converted = convert_with_density(
        ingredient.name,
        ingredient.quantity,
        ingredient.unit,
        "g",
        density_data,
    )
    if converted is not None:
        return converted

    return 0.0


# ---------------------------------------------------------------------------
# Recursive macro calculation
# ---------------------------------------------------------------------------


def calculate_recipe_macros(
    recipe: BaseRecipe,
    *,
    nutrition_registry: NutritionRegistry | None = None,
    ingredient_nutrition_lookup: Callable[[str], NutritionInfo | None] | None = None,
    recipe_index: Mapping[str, BaseRecipe] | None = None,
    density_data: dict | None = None,
) -> RecipeMacros:
    """Calculate total and per-serving macros for a recipe.

    For each ingredient, macros are computed from (in priority order):

    1. **product_ref** — recurse into the referenced sub-recipe (resolved
       via *recipe_index*) and scale its total macros by the ingredient's
       gram quantity relative to the sub-recipe's ``net_weight_grams``.
    2. **nutrition_registry** — lookup the ingredient's name in the
       provided registry (a ``NutritionRegistry`` mapping).
    3. **ingredient_nutrition_lookup** — call the provided callback with
       the ingredient name; if it returns ``NutritionInfo``, use it.
    4. **fallback** — skip the ingredient (zero contribution).

    Args:
        recipe: The recipe to analyze.
        nutrition_registry: Optional mapping of ingredient name →
            ``NutritionInfo`` per 100g.  The primary data source
            (loaded from YAML, USDA, etc.).
        ingredient_nutrition_lookup: Optional callback ``(name) -> NutritionInfo | None``
            for looking up nutrition data by ingredient name from an external
            source (e.g., USDA API, local database).  Acts as a secondary
            fallback when the registry has no entry.
        recipe_index: Optional mapping of recipe name → ``BaseRecipe`` for
            resolving ``product_ref`` references.

    Returns:
        ``RecipeMacros`` with total and per-serving breakdown.

    Raises:
        RecipeCycleError: If a cycle is detected in ``product_ref`` references.
    """
    nutrition_registry = nutrition_registry or {}
    recipe_index = recipe_index or {}
    density_data = density_data or {}

    total_protein, total_carbs, total_fat, total_fiber, total_kcal = (
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    )

    for ingredient in recipe.all_ingredients:
        if ingredient.byproduct:
            continue
        if ingredient.quantity == 0:
            continue

        protein, carbs, fat, fiber, kcal = _macro_contribution(
            ingredient,
            nutrition_registry=nutrition_registry,
            recipe_index=recipe_index,
            ingredient_nutrition_lookup=ingredient_nutrition_lookup,
            density_data=density_data,
            visited=frozenset(),
        )

        total_protein += protein
        total_carbs += carbs
        total_fat += fat
        total_fiber += fiber
        total_kcal += kcal

    total = MacroPerServing(
        protein_g=round(total_protein, 2),
        carbs_g=round(total_carbs, 2),
        fat_g=round(total_fat, 2),
        fiber_g=round(total_fiber, 2),
        kcal=round(total_kcal, 1),
    )

    servings_used = _pick_servings(recipe.servings)

    per_serving: MacroPerServing | None = None
    if servings_used is not None and servings_used > 0:
        per_serving = MacroPerServing(
            protein_g=round(total_protein / servings_used, 2),
            carbs_g=round(total_carbs / servings_used, 2),
            fat_g=round(total_fat / servings_used, 2),
            fiber_g=round(total_fiber / servings_used, 2),
            kcal=round(total_kcal / servings_used, 1),
        )

    return RecipeMacros(
        recipe_name=recipe.name,
        total=total,
        per_serving=per_serving,
        servings_used=servings_used,
    )


def _pick_servings(servings: Servings | None) -> int | None:
    """Pick a single integer serving count from a recipe's serving info.

    Uses the midpoint for ``ServingRange``, the exact value for ``int``,
    and returns ``None`` if not set.
    """
    if servings is None:
        return None
    if isinstance(servings, int):
        return servings
    return servings.midpoint


# ---------------------------------------------------------------------------
# Per-ingredient calculation
# ---------------------------------------------------------------------------


def _macro_contribution(
    ingredient: BaseIngredient,
    *,
    nutrition_registry: NutritionRegistry,
    recipe_index: Mapping[str, BaseRecipe],
    ingredient_nutrition_lookup: Callable[[str], NutritionInfo | None] | None,
    density_data: dict,
    visited: frozenset[str],
) -> tuple[float, float, float, float, float]:
    """Compute (protein, carbs, fat, fiber, kcal) for one ingredient."""
    # ── product_ref: recurse into sub-recipe ────────────────────────────
    if ingredient.product_ref is not None:
        sub_recipe = recipe_index.get(ingredient.product_ref)
        if sub_recipe is None:
            return 0.0, 0.0, 0.0, 0.0, 0.0

        if sub_recipe.name in visited:
            return 0.0, 0.0, 0.0, 0.0, 0.0

        sub_macros = calculate_recipe_macros(
            sub_recipe,
            nutrition_registry=nutrition_registry,
            recipe_index=recipe_index,
            ingredient_nutrition_lookup=ingredient_nutrition_lookup,
            density_data=density_data,
        )

        if sub_recipe.net_weight_grams is None or sub_recipe.net_weight_grams <= 0:
            return 0.0, 0.0, 0.0, 0.0, 0.0

        grams_used = _ingredient_grams(ingredient, density_data=density_data)
        if grams_used <= 0:
            return 0.0, 0.0, 0.0, 0.0, 0.0

        ratio = grams_used / sub_recipe.net_weight_grams
        return (
            sub_macros.total.protein_g * ratio,
            sub_macros.total.carbs_g * ratio,
            sub_macros.total.fat_g * ratio,
            sub_macros.total.fiber_g * ratio,
            sub_macros.total.kcal * ratio,
        )

    # ── Try nutrition_registry → callback → skip ───────────────────────
    nutrition: NutritionInfo | None = nutrition_registry.get(ingredient.name)

    if nutrition is None and ingredient_nutrition_lookup is not None:
        nutrition = ingredient_nutrition_lookup(ingredient.name)

    if nutrition is None:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    grams_used = _ingredient_grams(ingredient, density_data=density_data)
    if grams_used is None or grams_used <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    factor = grams_used / 100.0
    return (
        nutrition.protein_g * factor,
        nutrition.carbs_g * factor,
        nutrition.fat_g * factor,
        nutrition.fiber_g * factor,
        nutrition.effective_kcal * factor,
    )

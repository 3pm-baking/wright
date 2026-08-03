"""Cost calculation logic — pure functions, no file I/O."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal

import pint

from wright.errors import (
    IngredientNotFoundError,
    RecipeCostErrors,
    UnitConversionError,
)
from wright.matching import ItemMatcher, find_matching_purchases
from wright.models import (
    DensityData,
    Ingredient,
    IngredientCost,
    Material,
    PriceRange,
    PurchasedItem,
    Recipe,
    RecipeCost,
)
from wright.units import (
    DISCRETE_UNITS,
    PINCH_UNITS,
    WEIGHT_UNITS,
    are_compatible,
    parse_quantity,
)

# ---------------------------------------------------------------------------
# Unit conversion helpers
# ---------------------------------------------------------------------------

# Standard volume constants
_ML_PER_TSP = 4.92892
_ML_PER_TBSP = 14.7868
_ML_PER_CUP = 236.588
_ML_PER_FLOZ = 29.5735


def convert_with_density(
    ingredient_name: str,
    quantity: float,
    from_unit: str,
    to_unit: str,
    density_data: DensityData,
) -> float | None:
    """Try to convert quantity using density data.

    Supports two types of conversions:
    1. *liquids*: density in g/ml (e.g., lemon juice: 1.03 g/ml).
    2. *volume_weights*: direct g per volume unit (e.g., cinnamon: 2.6 g/tsp).

    Args:
        ingredient_name: Name of the ingredient (case-insensitive lookup).
        quantity: Amount to convert.
        from_unit: Source unit (e.g., ``"g"``).
        to_unit: Target unit (e.g., ``"tsp"``).
        density_data: Dictionary with optional ``"liquids"`` and
            ``"volume_weights"`` sections.

    Returns:
        Converted quantity, or ``None`` if no conversion is available.
    """
    volume_weights = density_data.get("volume_weights", {})
    liquids = density_data.get("liquids", {})

    from_unit_lower = from_unit.lower()
    to_unit_lower = to_unit.lower()

    # ── Liquids (g/ml density) ─────────────────────────────────────────────

    density = liquids.get(ingredient_name)
    if density is None:
        # Case-insensitive fallback
        for key, value in liquids.items():
            if key.lower() == ingredient_name.lower():
                density = value
                break

    if density is not None:
        # g → volume via density
        if from_unit_lower in {"g", "gram", "grams"}:
            ml = quantity / density
            if to_unit_lower in {"tsp", "teaspoon"}:
                return ml / _ML_PER_TSP
            if to_unit_lower in {"tbsp", "tablespoon"}:
                return ml / _ML_PER_TBSP
            if to_unit_lower in {"cup", "cups"}:
                return ml / _ML_PER_CUP
            if to_unit_lower in {"ml", "milliliter", "milliliters"}:
                return ml
            if to_unit_lower in {"floz", "fl oz", "fluid ounce", "fluid ounces"}:
                return ml / _ML_PER_FLOZ

        # volume → g via density
        elif to_unit_lower in {"g", "gram", "grams"}:
            ml: float | None = None
            if from_unit_lower in {"tsp", "teaspoon"}:
                ml = quantity * _ML_PER_TSP
            elif from_unit_lower in {"tbsp", "tablespoon"}:
                ml = quantity * _ML_PER_TBSP
            elif from_unit_lower in {"cup", "cups"}:
                ml = quantity * _ML_PER_CUP
            elif from_unit_lower in {"ml", "milliliter", "milliliters"}:
                ml = quantity
            elif from_unit_lower in {"floz", "fl oz", "fluid ounce", "fluid ounces"}:
                ml = quantity * _ML_PER_FLOZ

            if ml is not None:
                return ml * density

    # ── Volume weights (direct g per volume unit) ──────────────────────────

    conversions = volume_weights.get(ingredient_name)
    if conversions is None:
        for key in volume_weights:
            if key.lower() == ingredient_name.lower():
                conversions = volume_weights[key]
                break

    if conversions is None:
        return None

    # g → volume
    if from_unit_lower in {"g", "gram", "grams"}:
        if to_unit_lower in {"tsp", "teaspoon"}:
            g_per = conversions.get("tsp")
            if g_per:
                return quantity / g_per
        elif to_unit_lower in {"tbsp", "tablespoon"}:
            g_per = conversions.get("tbsp")
            if g_per:
                return quantity / g_per
        elif to_unit_lower in {"cup", "cups"}:
            g_per = conversions.get("cup")
            if g_per:
                return quantity / g_per

    # volume → weight
    volume_from: float | None = None
    if from_unit_lower in {"tsp", "teaspoon"}:
        g_per = conversions.get("tsp")
        if g_per:
            volume_from = quantity * g_per
    elif from_unit_lower in {"tbsp", "tablespoon"}:
        g_per = conversions.get("tbsp")
        if g_per:
            volume_from = quantity * g_per
    elif from_unit_lower in {"cup", "cups"}:
        g_per = conversions.get("cup")
        if g_per:
            volume_from = quantity * g_per

    if volume_from is not None and to_unit_lower in WEIGHT_UNITS:
        if to_unit_lower in {"g", "gram", "grams"}:
            return volume_from
        try:
            return float(parse_quantity(volume_from, "g").to(to_unit_lower).magnitude)
        except Exception:
            pass

    return None


# ---------------------------------------------------------------------------
# Ingredient costing
# ---------------------------------------------------------------------------


def calculate_ingredient_cost(
    material: Material,
    purchase: PurchasedItem,
    *,
    density_data: DensityData | None = None,
    converter: Callable[[Material, PurchasedItem, DensityData], Decimal | None]
    | None = None,
    ureg: pint.UnitRegistry | None = None,
) -> Decimal:
    """Calculate the cost of a BOM item based on a purchase item's price.

    Handles unit conversion between BOM units and purchase units.
    For discrete units (each, packet), uses direct multiplication.
    For pinch units with non-discrete purchase units, estimates ~0.25 tsp.

    Args:
        material: The BOM item to cost.
        purchase: The purchase item to use for pricing.
        density_data: Optional density data for unit conversion.
        converter: Optional custom cost function
            ``(material, purchase, density_data) -> Decimal | None``.
            Called first; if it returns a ``Decimal``, that value is used.
            If it returns ``None``, falls through to the built-in cascade.

    Returns:
        The cost of the material amount.

    Raises:
        UnitConversionError: If units cannot be converted.
    """
    density_data = density_data or {}

    # Allow a custom converter to intercept before the built-in cascade
    if converter is not None:
        result = converter(material, purchase, density_data)
        if result is not None:
            return result

    ing_unit_lower = material.unit.lower()
    groc_unit_lower = purchase.unit.lower()

    # Both are discrete — direct count multiplication
    if ing_unit_lower in DISCRETE_UNITS and groc_unit_lower in DISCRETE_UNITS:
        cost_per_item = purchase.price / Decimal(str(purchase.quantity))
        return cost_per_item * Decimal(str(material.quantity))

    # Pinch — estimate as ~0.25 tsp
    if ing_unit_lower in PINCH_UNITS:
        if are_compatible("tsp", purchase.unit, ureg=ureg):
            groc_in_tsp = (
                parse_quantity(purchase.quantity, purchase.unit, ureg=ureg)
                .to("tsp")
                .magnitude
            )
            price_per_tsp = purchase.price / Decimal(str(groc_in_tsp))
            pinch_in_tsp = Decimal("0.25") * Decimal(str(material.quantity))
            return price_per_tsp * pinch_in_tsp
        else:
            return Decimal("0.01") * Decimal(str(material.quantity))

    # Same unit string — simple ratio (handles unregistered units like "box", "jar")
    if ing_unit_lower == groc_unit_lower:
        price_per_unit = purchase.price / Decimal(str(purchase.quantity))
        return price_per_unit * Decimal(str(material.quantity))

    # Unit-compatible — pint handles it
    if are_compatible(material.unit, purchase.unit, ureg=ureg):
        try:
            ing_qty = parse_quantity(material.quantity, material.unit, ureg=ureg)
            ing_in_groc_units = ing_qty.to(purchase.unit).magnitude
            price_per_unit = purchase.price / Decimal(str(purchase.quantity))
            return price_per_unit * Decimal(str(ing_in_groc_units))
        except pint.DimensionalityError as err:
            raise UnitConversionError(
                material.unit, purchase.unit, material.name
            ) from err

    # Incompatible but material has an equivalent — try that
    equiv_qty = material.equivalent_quantity
    equiv_unit = material.equivalent_unit
    if (
        equiv_qty is not None
        and equiv_unit is not None
        and are_compatible(equiv_unit, purchase.unit, ureg=ureg)
    ):
        try:
            Material(
                name=material.name,
                quantity=equiv_qty,
                unit=equiv_unit,
            )
            e_qty = parse_quantity(equiv_qty, equiv_unit, ureg=ureg)
            in_groc = e_qty.to(purchase.unit).magnitude
            price_per_unit = purchase.price / Decimal(str(purchase.quantity))
            return price_per_unit * Decimal(str(in_groc))
        except Exception:
            pass

    # Not directly compatible — try density conversion
    converted = convert_with_density(
        material.name,
        material.quantity,
        material.unit,
        purchase.unit,
        density_data,
    )

    if converted is not None:
        price_per_unit = purchase.price / Decimal(str(purchase.quantity))
        return price_per_unit * Decimal(str(converted))

    raise UnitConversionError(material.unit, purchase.unit, material.name)


def calculate_ingredient_cost_range(
    material: Material,
    purchases: Iterable[PurchasedItem],
    *,
    density_data: DensityData | None = None,
) -> IngredientCost:
    """Calculate the cost range for a material across multiple purchase sources.

    Args:
        material: The BOM item to cost.
        purchases: Matching purchase items (output of
            :func:`find_matching_purchases`).
        density_data: Optional density data for unit conversion.

    Returns:
        ``IngredientCost`` with price range and source information.

    Raises:
        UnitConversionError: If *none* of the purchase items can be converted
            to the material's unit.
    """
    density_data = density_data or {}

    costs: list[Decimal] = []
    sources: list[str] = []

    for g in purchases:
        try:
            cost = calculate_ingredient_cost(material, g, density_data=density_data)
            costs.append(cost)
            source = g.store or "unknown"
            if hasattr(g, "brand") and getattr(g, "brand", None):
                source = f"{source} {g.brand}"
            sources.append(source)
        except UnitConversionError:
            continue

    if not costs:
        # All unit conversions failed — pick the first purchase for the error
        first = next(iter(purchases), None)
        raise UnitConversionError(
            material.unit,
            first.unit if first else "unknown",
            material.name,
        )

    return IngredientCost(
        ingredient=Ingredient(
            name=material.name,
            quantity=material.quantity,
            unit=material.unit,
            require_tags=material.require_tags,
            equivalent_quantity=material.equivalent_quantity,
            equivalent_unit=material.equivalent_unit,
            byproduct=material.byproduct,
            product_ref=material.product_ref,
        ),
        price_range=PriceRange(min_price=min(costs), max_price=max(costs)),
        sources=sources,
    )


# ---------------------------------------------------------------------------
# Gram conversion
# ---------------------------------------------------------------------------


def convert_ingredient_to_grams(
    material: Material,
    *,
    raise_on_error: bool = True,
    ureg: pint.UnitRegistry | None = None,
    density_data: DensityData | None = None,
) -> float:
    """Return the gram quantity for a material.

    For packet units, uses ``equivalent_quantity`` (e.g. 1 packet = 8 g).
    For gram units, uses quantity directly.
    For other weight units, converts via pint.
    Falls back to density-based conversion when pint cannot convert
    (e.g. volume units like ml → g for liquids).

    Args:
        material: The BOM item to resolve to grams.
        raise_on_error: If ``True`` (default), raises ``UnitConversionError``
            on failure.  If ``False``, returns ``0.0`` silently.
        ureg: Optional pint unit registry.
        density_data: Optional density data for volume→weight conversion.

    Returns:
        Gram quantity, or ``0.0`` when unresolvable and *raise_on_error* is ``False``.

    Raises:
        UnitConversionError: If the unit cannot be resolved to grams and
            *raise_on_error* is ``True``.
    """
    unit_lower = material.unit.lower()

    if unit_lower in {"packet", "packets"}:
        if material.equivalent_quantity is None:
            if raise_on_error:
                raise UnitConversionError(material.unit, "g", material.name)
            return 0.0
        return material.equivalent_quantity

    # Try pint direct conversion first
    try:
        return float(parse_quantity(material.quantity, unit_lower).to("g").magnitude)
    except Exception:
        pass

    # Fall back to density conversion (handles volume → weight)
    if density_data:
        converted = convert_with_density(
            material.name, material.quantity, material.unit, "g", density_data
        )
        if converted is not None:
            return converted

    if raise_on_error:
        raise UnitConversionError(material.unit, "g", material.name)
    return 0.0


# ---------------------------------------------------------------------------
# Recipe costing (with recursive product_ref support)
# ---------------------------------------------------------------------------


def _cost_recipe_inner(
    recipe: Recipe,
    purchases: Iterable[PurchasedItem],
    density_data: DensityData,
    recipe_index: Mapping[str, Recipe],
    visited: frozenset[str],
    *,
    matcher: ItemMatcher,
) -> tuple[list[IngredientCost], PriceRange]:
    """Cost a recipe's ingredients, resolving ``product_ref`` recursively.

    Returns ``(ingredient_costs, total_price_range)``.

    Raises:
        RecipeCostErrors: If any ingredients cannot be matched, converted,
            or if a cycle is detected among ``product_ref`` references.
    """
    if recipe.name in visited:
        cycle = " → ".join([*visited, recipe.name])
        raise RecipeCostErrors([ValueError(f"Recipe cycle detected: {cycle}")])

    ingredient_costs: list[IngredientCost] = []
    errors: list[
        IngredientNotFoundError | UnitConversionError | RecipeCostErrors | ValueError
    ] = []
    total_min = Decimal("0")
    total_max = Decimal("0")

    for ingredient in recipe.all_ingredients:
        if ingredient.byproduct:
            continue
        if ingredient.quantity == 0:
            continue

        try:
            if ingredient.product_ref is not None:
                # ── Recursive: cost the referenced sub-recipe per gram ──
                ref_name = ingredient.product_ref
                sub_recipe = recipe_index.get(ref_name)
                if sub_recipe is None:
                    raise IngredientNotFoundError(ref_name)

                _sub_costs, sub_total = _cost_recipe_inner(
                    sub_recipe,
                    purchases,
                    density_data,
                    recipe_index,
                    visited | {recipe.name},
                    matcher=matcher,
                )

                if (
                    sub_recipe.net_weight_grams is None
                    or sub_recipe.net_weight_grams <= 0
                ):
                    raise RecipeCostErrors([
                        ValueError(
                            f"Sub-recipe '{ref_name}' has no "
                            "net_weight_grams — cannot compute "
                            "per-gram cost for product_ref."
                        )
                    ])

                yield_dec = Decimal(str(sub_recipe.net_weight_grams))
                per_gram = PriceRange(
                    min_price=sub_total.min_price / yield_dec,
                    max_price=sub_total.max_price / yield_dec,
                )

                grams_used = convert_ingredient_to_grams(ingredient)
                grams_dec = Decimal(str(grams_used))

                cost = IngredientCost(
                    ingredient=ingredient,
                    price_range=PriceRange(
                        min_price=per_gram.min_price * grams_dec,
                        max_price=per_gram.max_price * grams_dec,
                    ),
                    sources=[f"{sub_recipe.name} (sub-recipe, {grams_used:.1f}g)"],
                )
            else:
                # ── Standard: match to purchase ──────────────────────────
                matching = matcher(ingredient, purchases)
                cost = calculate_ingredient_cost_range(
                    ingredient, matching, density_data=density_data
                )

        except (
            IngredientNotFoundError,
            UnitConversionError,
            RecipeCostErrors,
        ) as e:
            errors.append(e)
            continue

        ingredient_costs.append(cost)
        total_min += cost.price_range.min_price
        total_max += cost.price_range.max_price

    if errors:
        raise RecipeCostErrors(errors)

    return ingredient_costs, PriceRange(min_price=total_min, max_price=total_max)


def calculate_recipe_cost(
    recipe: Recipe,
    purchases: Iterable[PurchasedItem],
    *,
    density_data: DensityData | None = None,
    recipe_index: Mapping[str, Recipe] | None = None,
    matcher: ItemMatcher | None = None,
) -> RecipeCost:
    """Calculate the full cost breakdown for a recipe.

    Resolves ingredients to purchase items.  When an ingredient has
    ``product_ref`` set, the function looks up the referenced recipe in
    *recipe_index* and recursively costs it — supporting arbitrary nesting
    depths with cycle detection.

    Args:
        recipe: The recipe to cost.
        purchases: Available purchase price data (any ``PurchasedItem``).
        density_data: Optional density data for unit conversion.
        recipe_index: Optional mapping of recipe name → ``Recipe`` for
            resolving ``product_ref`` references.
        matcher: Optional custom matching function.  Defaults to
            :func:`find_matching_purchases` (exact name + tag filter).

    Returns:
        ``RecipeCost`` with ingredient-level breakdown and totals.

    Raises:
        RecipeCostErrors: If any ingredients cannot be matched, converted,
            or if a cycle is detected.

    See Also:
        :func:`calculate_item_costs` — for per-item costing of arbitrary
        materials (non-recipe BOM items).
    """
    density_data = density_data or {}
    recipe_index = recipe_index or {}

    ingredient_costs, total_range = _cost_recipe_inner(
        recipe,
        purchases,
        density_data,
        recipe_index,
        frozenset(),
        matcher=matcher or find_matching_purchases,
    )

    # Per-serving costs
    min_s, max_s = recipe._servings_bounds()
    min_per_serving = total_range.min_price / Decimal(str(max_s))
    max_per_serving = total_range.max_price / Decimal(str(min_s))

    return RecipeCost(
        recipe_name=recipe.name,
        ingredient_costs=ingredient_costs,
        total_cost_range=total_range,
        cost_per_serving_range=PriceRange(
            min_price=min_per_serving, max_price=max_per_serving
        ),
    )


def get_top_cost_drivers(
    recipe_cost: RecipeCost,
    n: int = 5,
) -> list[IngredientCost]:
    """Return the top N ingredients by cost midpoint, descending.

    Args:
        recipe_cost: A fully calculated ``RecipeCost``.
        n: How many top drivers to return (default 5).

    Returns:
        List of ``IngredientCost`` sorted by price midpoint descending,
        capped at *n*.
    """
    sorted_costs = sorted(
        recipe_cost.ingredient_costs,
        key=lambda ic: ic.price_range.midpoint,
        reverse=True,
    )
    return sorted_costs[:n]

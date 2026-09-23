"""Ingredient-to-grams conversion — pure functions, no file I/O.

Centralizes every strategy for resolving a material's weight in grams:

1. ``packet`` units via ``equivalent_quantity``.
2. Weight units via pint (g, kg, oz, lb, ...).
3. Volume units via ``ConversionData.liquids`` (density g/ml).
4. Volume units via ``ConversionData.volume_weights`` (g per tsp/tbsp/cup).
5. Pinch units via ``ConversionData.special["pinch"]``.
6. Discrete units via ``ConversionData.unit_weights`` (g per item) or the
   material's own ``approx_weight_grams`` override.
"""

from __future__ import annotations

from wright.errors import UnitConversionError
from wright.models import ConversionData, Material

DISCRETE_UNITS = frozenset({
    "each",
    "ea",
    "piece",
    "pieces",
    "item",
    "items",
    "unit",
    "units",
})

_DEFAULT_PINCH_GRAMS = 0.5


def ingredient_grams(
    material: Material,
    *,
    conversion_data: ConversionData | None = None,
    raise_on_error: bool = True,
) -> float:
    """Return the gram weight for a material, trying every strategy.

    Resolution order:

    1. ``packet`` units — ``equivalent_quantity`` (e.g. 1 packet = 8 g).
    2. Weight units — pint conversion (g, kg, oz, lb, ...).
    3. Volume units — ``liquids`` density (g/ml) from *conversion_data*.
    4. Volume units — ``volume_weights`` (g per tsp/tbsp/cup).
    5. ``pinch`` units — ``special["pinch"]`` grams per pinch.
    6. Discrete units — ``approx_weight_grams`` field first, then the
       ``unit_weights`` table (both grams-per-item, case-insensitive).

    Args:
        material: The BOM item to resolve to grams.
        conversion_data: Conversion factors (density, volume weights,
            unit weights).  ``None`` skips strategies 3-6.
        raise_on_error: If ``True`` (default), raise ``UnitConversionError``
            when no strategy resolves.  If ``False``, return ``0.0``.

    Returns:
        Gram quantity, or ``0.0`` when unresolvable and *raise_on_error*
        is ``False``.

    Raises:
        UnitConversionError: If the unit cannot be resolved to grams and
            *raise_on_error* is ``True``.
    """
    from wright.costing import convert_ingredient_to_grams

    data = conversion_data or {}

    if material.quantity == 0:
        return 0.0

    # 1-4. Packets, pint weight units, density and volume-weight fallbacks
    grams = convert_ingredient_to_grams(
        material, raise_on_error=False, density_data=data
    )
    if grams:
        return grams

    unit_lower = material.unit.lower()

    # 5. Pinch
    if unit_lower in {"pinch", "pinches"}:
        pinch_grams = (data.get("special") or {}).get("pinch", _DEFAULT_PINCH_GRAMS)
        return float(material.quantity * pinch_grams)

    # 6. Discrete units — approx_weight_grams field, then unit_weights table
    if unit_lower in DISCRETE_UNITS:
        if material.approx_weight_grams is not None:
            return float(material.quantity * material.approx_weight_grams)
        unit_weights = data.get("unit_weights") or {}
        for key, grams_per_item in unit_weights.items():
            if key.lower() == material.name.lower():
                return float(material.quantity * grams_per_item)

    if raise_on_error:
        raise UnitConversionError(material.unit, "g", material.name)
    return 0.0

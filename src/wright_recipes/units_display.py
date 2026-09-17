"""Name-aware display normalizers for the CLI's shopping list.

Wright's built-in ``normalize_metric`` is unit-only: dry goods that
accumulate in ml display as ml, which reads wrong for things like salt
("12.3 ml" instead of "15 g").  This module adds a name-aware metric
display normalizer with a small built-in density table for common
kitchen ingredients.  Liquids stay in ml/L; dry goods with a known
density display in g/kg.

The table is intentionally small and overridable — pass your own
``display_normalizer`` to the planning functions for full control.
"""

from __future__ import annotations

from wright import VOLUME_UNITS, normalize_metric

# Approximate grams per milliliter for common dry/semi-solid ingredients.
# Liquids are excluded — they display in ml/L naturally.
DENSITY_G_PER_ML: dict[str, float] = {
    "flour": 0.53,
    "almond flour": 0.55,
    "hazelnut meal": 0.55,
    "meal": 0.55,
    "sugar": 0.85,
    "brown sugar": 0.9,
    "salt": 1.22,
    "baking powder": 0.97,
    "baking soda": 0.91,
    "yeast": 0.67,
    "cocoa": 0.6,
    "cinnamon": 0.53,
    "mustard seed": 0.9,
    "celery seed": 0.9,
    "pepper": 0.55,
    "spice": 0.6,
    "oats": 0.4,
    "rice": 0.85,
    "quinoa": 0.75,
    "butter": 0.96,
    "margarine": 0.96,
    "shortening": 0.95,
    "chocolate": 1.1,
    "chopped": 0.7,
    "nuts": 0.62,
    "hazelnuts": 0.62,
    "walnuts": 0.62,
    "almonds": 0.62,
    "honey": 1.42,
    "jam": 1.33,
    "syrup": 1.35,
    "peanut butter": 1.13,
    "tahini": 1.13,
    "yogurt": 1.03,
    "sour cream": 1.0,
    "mascarpone": 1.0,
    "cheese": 1.0,
    "ground": 1.0,
    "meat": 1.05,
    "chicken": 1.05,
    "beef": 1.06,
    "pancetta": 1.0,
    "bacon": 1.0,
}

# Name fragments that indicate a liquid — keep in ml/L.
_LIQUID_FRAGMENTS = (
    "water",
    "milk",
    "oil",
    "vinegar",
    "juice",
    "cream",
    "wine",
    "broth",
    "stock",
    "rum",
    "whiskey",
    "vodka",
    "brandy",
    "extract",
    "syrup",
    "sauce",
    "milk",
    "buttermilk",
    "buttermilk",
)


def _is_liquid(name: str) -> bool:
    lowered = name.lower()
    return any(frag in lowered for frag in _LIQUID_FRAGMENTS)


def _lookup_density(name: str) -> float | None:
    lowered = name.lower()
    for frag, density in DENSITY_G_PER_ML.items():
        if frag in lowered:
            return density
    return None


def metric_display(
    quantity: float,
    unit: str,
    name: str = "",
) -> tuple[float, str]:
    """Name-aware metric display normalizer.

    Dry goods with a known density convert ml -> g/kg; liquids and
    unknowns keep wright's default metric behavior (ml/L).  Weight and
    count units pass through ``normalize_metric`` unchanged.
    """
    if unit.lower() in VOLUME_UNITS and not _is_liquid(name):
        density = _lookup_density(name)
        if density is not None:
            # Accumulated volume is already in ml at this point.
            ml = quantity if unit.lower() == "ml" else None
            if ml is None:
                from wright.units import ureg

                try:
                    ml = float(ureg.Quantity(quantity, unit).to("ml").magnitude)
                except Exception:
                    ml = None
            if ml is not None:
                grams = ml * density
                if grams >= 1000:
                    return round(grams / 1000, 2), "kg"
                return round(grams, 1), "g"
    return normalize_metric(quantity, unit, name)

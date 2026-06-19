"""Pint unit registry with common unit classification sets.

Wright ships a ``pint.UnitRegistry`` with pre-defined custom units and
exposes it as :data:`ureg`.  All helper functions accept an optional
``ureg=`` parameter so you can inject your own registry.

**Add a custom unit to wright's registry**::

    >>> from wright.units import ureg, parse_quantity
    >>> ureg.define("loaf = 1 * count")
    >>> ureg.define("@alias loaf = loaves")
    >>> parse_quantity(2, "loaves").magnitude
    2.0

**Inject a separate registry** (required when two registries must not share
state)::

    >>> import pint
    >>> from wright.units import parse_quantity
    >>> my_ureg = pint.UnitRegistry()
    >>> my_ureg.define("each = 1 * count")
    >>> my_ureg.define("crate = 24 * each")
    >>> parse_quantity(3, "crate", ureg=my_ureg).to("each").magnitude
    72.0

Pre-defined units: ``each``, ``packet``, ``pinch``, ``can``, ``clove``,
``vial`` (all ``= 1 * count``) with common aliases.
"""

from __future__ import annotations

from typing import Any

import pint

# ── Unit classification sets (reusable across the package) ──────────────────

DISCRETE_UNITS: frozenset[str] = frozenset({
    "each",
    "packet",
    "packets",
    "ea",
    "piece",
    "pieces",
})
"""Units that represent countable items, not measurable quantities."""

PINCH_UNITS: frozenset[str] = frozenset({"pinch", "pinches"})
"""Approximate units handled specially in cost calculation."""

WEIGHT_UNITS: frozenset[str] = frozenset(
    {
        "g",
        "gram",
        "grams",
        "oz",
        "ounce",
        "ounces",
        "lb",
        "lbs",
        "pound",
        "pounds",
        "kg",
        "kilogram",
        "kilograms",
    },
)
"""All recognized weight units."""

VOLUME_UNITS: frozenset[str] = frozenset(
    {
        "tsp",
        "teaspoon",
        "tbsp",
        "tablespoon",
        "cup",
        "floz",
        "fluid_ounce",
        "ml",
        "milliliter",
        "millilitre",
        "liter",
        "litre",
        "l",
    },
)
"""All recognized volume units (used for normalization to canonical volume unit)."""

# ── Pint registry ───────────────────────────────────────────────────────────

_ureg = pint.UnitRegistry()

_ureg.define("each = 1 * count")
_ureg.define("packet = 1 * count")
_ureg.define("pinch = 1 * count")
_ureg.define("can = 1 * count")
_ureg.define("clove = 1 * count")
_ureg.define("vial = 1 * count")

_ureg.define("@alias each = ea = piece = pieces")
_ureg.define("@alias packet = packets = pkt")
_ureg.define("@alias pinch = pinches")
_ureg.define("@alias can = cans")
_ureg.define("@alias vial = vials")

_ureg.define("@alias teaspoon = tsp")
_ureg.define("@alias tablespoon = tbsp = Tbsp")

ureg = _ureg  # public alias for backward compat


def parse_quantity(
    value: float, unit: str, *, ureg: pint.UnitRegistry | None = None
) -> Any:
    """Parse a value and unit string into a pint Quantity.

    Args:
        value: The numeric quantity.
        unit: The unit string (e.g., "g", "oz", "cups", "each").
        ureg: Optional unit registry.  Defaults to the module-level registry.

    Returns:
        A pint Quantity object.
    """
    return (ureg or _ureg).Quantity(value, unit)


def convert_quantity(
    qty: Any, to_unit: str, *, ureg: pint.UnitRegistry | None = None
) -> Any:
    """Convert a quantity to a different unit.

    Args:
        qty: The quantity to convert.
        to_unit: The target unit string.
        ureg: Optional unit registry.  Defaults to the module-level registry.

    Returns:
        The converted quantity.

    Raises:
        pint.DimensionalityError: If units are incompatible.
    """
    return qty.to(to_unit)


def are_compatible(
    unit_a: str, unit_b: str, *, ureg: pint.UnitRegistry | None = None
) -> bool:
    """Check whether two units are dimensionally compatible.

    Args:
        unit_a: First unit string.
        unit_b: Second unit string.
        ureg: Optional unit registry.  Defaults to the module-level registry.

    Returns:
        True if the units share the same dimensionality.
    """
    try:
        (ureg or _ureg).Quantity(1.0, unit_a).to(unit_b)
        return True
    except (pint.DimensionalityError, pint.UndefinedUnitError):
        return False

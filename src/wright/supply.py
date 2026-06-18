"""Supply tracking — pure functions, no I/O.

Models and operations for managing ingredient stock, including
pre-shopping subtraction (deduct what's on hand before buying).
"""

from __future__ import annotations

from typing import Sequence

from pydantic import BaseModel, Field

from wright.costing import convert_with_density
from wright.units import are_compatible, parse_quantity

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

SupplyItemSource = Sequence["SupplyItem"]


class SupplyItem(BaseModel):
    """An item tracked in stock."""

    name: str = Field(..., description="Item name (exact match)")
    quantity: float = Field(..., ge=0, description="Amount on hand")
    unit: str = Field(..., description="Unit of measurement")

    def to_qty(self):
        """Return this item as a pint Quantity."""
        return parse_quantity(self.quantity, self.unit)


Supply = dict[str, SupplyItem]
"""Stock keyed by item name."""


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


def subtract_supply(
    needed: SupplyItemSource,
    supply: Supply,
    *,
    density_data: dict | None = None,
) -> list[SupplyItem]:
    """Deduct stock from a list of needed items.

    Returns only items with a remaining deficit — items fully covered
    by stock are omitted.

    Handles unit conversion when stock and needed units differ:
    pint-compatible units are converted directly; incompatible units
    (e.g. grams vs tablespoons) fall back to *density_data*.

    Args:
        needed: Ingredients required (from recipes / production plan).
        supply: Current stock.
        density_data: Optional density data for cross-unit conversion.

    Returns:
        List of ``SupplyItem`` with remaining deficits.  Items where
        stock ≥ needed quantity are dropped entirely.
    """
    result: list[SupplyItem] = []

    for item in needed:
        stock = supply.get(item.name, None)
        if stock is None:
            result.append(item)
            continue

        deficit = _subtract_one(item, stock, density_data=density_data)
        if deficit is not None:
            result.append(deficit)

    return result


def supply_add(supply: Supply, items: SupplyItemSource) -> Supply:
    """Return updated stock with *items* added.

    Same-name entries have their quantities summed (with unit
    conversion when units differ).
    """
    result = {k: v.model_copy(deep=True) for k, v in supply.items()}

    for item in items:
        existing = result.get(item.name)
        if existing is None:
            result[item.name] = item.model_copy(deep=True)
        else:
            merged = _sum_quantities(existing, item)
            result[item.name] = merged

    return result


def supply_deduct(supply: Supply, items: SupplyItemSource) -> Supply:
    """Return updated stock with *items* removed.

    Quantities are floored at 0; zero-quantity entries are dropped.
    Unknown item names are silently ignored.
    """
    result = {k: v.model_copy(deep=True) for k, v in supply.items()}

    for item in items:
        existing = result.get(item.name)
        if existing is None:
            continue
        remaining = _subtract_quantity(existing, item)
        if remaining.quantity == 0:
            del result[item.name]
        else:
            result[item.name] = remaining

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _subtract_one(
    needed: SupplyItem,
    stock: SupplyItem,
    *,
    density_data: dict | None = None,
) -> SupplyItem | None:
    """Subtract *stock* from *needed*.  Returns the deficit (``None`` if
    fully covered).
    """
    density_data = density_data or {}

    # Same unit — simple subtraction
    if needed.unit.lower() == stock.unit.lower():
        if stock.quantity >= needed.quantity:
            return None
        return SupplyItem(
            name=needed.name,
            quantity=round(needed.quantity - stock.quantity, 4),
            unit=needed.unit,
        )

    # Pint-compatible units — convert stock → needed unit
    if are_compatible(stock.unit, needed.unit):
        try:
            stock_in_needed_units = float(
                parse_quantity(stock.quantity, stock.unit).to(needed.unit).magnitude
            )
            if stock_in_needed_units >= needed.quantity:
                return None
            return SupplyItem(
                name=needed.name,
                quantity=round(needed.quantity - stock_in_needed_units, 4),
                unit=needed.unit,
            )
        except Exception:
            pass

    # Try density-based conversion
    converted = convert_with_density(
        needed.name, stock.quantity, stock.unit, needed.unit, density_data
    )
    if converted is not None:
        if converted >= needed.quantity:
            return None
        return SupplyItem(
            name=needed.name,
            quantity=round(needed.quantity - converted, 4),
            unit=needed.unit,
        )

    # Cannot convert — keep full needed quantity
    return needed


def _sum_quantities(existing: SupplyItem, addition: SupplyItem) -> SupplyItem:
    """Add *addition* quantity to *existing*, handling unit conversion."""
    if existing.unit.lower() == addition.unit.lower():
        return SupplyItem(
            name=existing.name,
            quantity=round(existing.quantity + addition.quantity, 4),
            unit=existing.unit,
        )

    if are_compatible(addition.unit, existing.unit):
        try:
            addition_in_existing = float(
                parse_quantity(addition.quantity, addition.unit)
                .to(existing.unit)
                .magnitude
            )
            return SupplyItem(
                name=existing.name,
                quantity=round(existing.quantity + addition_in_existing, 4),
                unit=existing.unit,
            )
        except Exception:
            pass

    # Incompatible — store as-is
    return SupplyItem(
        name=existing.name,
        quantity=round(existing.quantity + addition.quantity, 4),
        unit=existing.unit,
    )


def _subtract_quantity(existing: SupplyItem, deduction: SupplyItem) -> SupplyItem:
    """Subtract *deduction* from *existing*, flooring at 0."""
    if existing.unit.lower() == deduction.unit.lower():
        return SupplyItem(
            name=existing.name,
            quantity=max(0.0, round(existing.quantity - deduction.quantity, 4)),
            unit=existing.unit,
        )

    if are_compatible(deduction.unit, existing.unit):
        try:
            ded_in_existing = float(
                parse_quantity(deduction.quantity, deduction.unit)
                .to(existing.unit)
                .magnitude
            )
            return SupplyItem(
                name=existing.name,
                quantity=max(0.0, round(existing.quantity - ded_in_existing, 4)),
                unit=existing.unit,
            )
        except Exception:
            pass

    return SupplyItem(
        name=existing.name,
        quantity=max(0.0, round(existing.quantity - deduction.quantity, 4)),
        unit=existing.unit,
    )

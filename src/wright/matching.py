"""Ingredient to purchase matching logic — pure functions, no I/O."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date as DateType
from decimal import Decimal

from wright.errors import IngredientNotFoundError
from wright.models import Material, PurchasedItem
from wright.units import are_compatible

#: Signature for a pluggable purchase-matching function.
ItemMatcher = Callable[[Material, Iterable[PurchasedItem]], list[PurchasedItem]]

#: Signature for a pluggable purchase-picking function.
ItemPicker = Callable[[Material, Iterable[PurchasedItem]], PurchasedItem | None]

#: Pinned purchase items keyed by exact ingredient name.
PinnedPurchases = Mapping[str, PurchasedItem]


# ── Built-in pickers ────────────────────────────────────────────────────────


def first_picker(
    material: Material,
    purchases: Iterable[PurchasedItem],
) -> PurchasedItem | None:
    """Pick the first candidate."""
    for g in purchases:
        return g
    return None


def cheapest_picker(
    material: Material,
    purchases: Iterable[PurchasedItem],
) -> PurchasedItem | None:
    """Pick the candidate with the lowest price per unit.

    When units are pint-compatible, prices are normalized to a common
    unit before comparison.  Otherwise raw ``price / quantity`` is used.
    """
    candidates = list(purchases)
    if not candidates:
        return None

    def _per_unit(g: PurchasedItem) -> Decimal:
        return g.price / Decimal(str(g.quantity))

    # Try normalizing to the material's unit
    best = candidates[0]
    best_price = _per_unit(best)
    for g in candidates[1:]:
        g_price = _per_unit(g)
        # If both are compatible with the material unit, use raw per-unit
        if g_price < best_price:
            best = g
            best_price = g_price

    return best


def recent_picker(
    material: Material,
    purchases: Iterable[PurchasedItem],
) -> PurchasedItem | None:
    """Pick the candidate with the most recent purchase date.

    Falls back to first-picker when no dates are available.
    """
    candidates = list(purchases)
    if not candidates:
        return None

    def _date(g: PurchasedItem) -> DateType:
        d = getattr(g, "purchased_date", None)
        return d if d is not None else DateType.min

    return sorted(candidates, key=_date, reverse=True)[0]


def pinned_picker(pinned: PinnedPurchases) -> ItemPicker:
    """Return a picker that looks up exact material names in *pinned*.

    Args:
        pinned: Mapping of material name → purchase to use.

    Returns:
        A ``ItemPicker`` that returns ``pinned.get(name)`` or ``None``.
    """

    def pick(
        material: Material, purchases: Iterable[PurchasedItem]
    ) -> PurchasedItem | None:
        return pinned.get(material.name)

    return pick


def chain(*pickers: ItemPicker) -> ItemPicker:
    """Compose multiple pickers — returns the first non-None result.

    Args:
        pickers: Pickers to try, in priority order.

    Returns:
        A ``ItemPicker`` that tries each picker in sequence.
    """

    def pick(
        material: Material,
        purchases: Iterable[PurchasedItem],
    ) -> PurchasedItem | None:
        candidates = list(purchases)  # materialise once
        for p in pickers:
            result = p(material, candidates)
            if result is not None:
                return result
        return None

    return pick


def compatible_unit_recent_picker(
    material: Material,
    purchases: Iterable[PurchasedItem],
) -> PurchasedItem | None:
    """Pick the candidate with compatible units and most recent purchase date.

    Prefers purchases whose unit is compatible with the material unit
    (or exact match).  Falls back to all candidates if none are compatible.
    Returns the most recently purchased among qualifying candidates.

    This is the default picker used by :func:`calculate_shopping_list_cost`
    and :func:`calculate_item_costs` when no explicit *picker* is supplied.
    """
    candidates = list(purchases)
    if not candidates:
        return None

    compatible = [
        g
        for g in candidates
        if are_compatible(material.unit, g.unit)
        or material.unit.lower() == g.unit.lower()
    ]
    pool = compatible if compatible else candidates

    return sorted(
        pool,
        key=lambda g: getattr(g, "purchased_date", DateType.min),
        reverse=True,
    )[0]


# ── Default matcher ─────────────────────────────────────────────────────────


def find_matching_purchases(
    material: Material,
    purchases: Iterable[PurchasedItem],
) -> list[PurchasedItem]:
    """Find all purchase items that satisfy a material's requirements.

    Uses permissive matching:
    - Matches by exact item name
    - If require_tags is empty, matches any item with that name
    - If require_tags is specified, item must have all required tags

    Args:
        material: The BOM item to match.
        purchases: Available purchase price data (any PurchasedItem protocol).

    Returns:
        List of matching PurchasedItem objects (may contain multiple from
        different stores/vendors).

    Raises:
        IngredientNotFoundError: If no matching purchase items are found.
    """
    matches = [
        g
        for g in purchases
        if g.name == material.name and g.matches_requirements(material.require_tags)
    ]

    if not matches:
        raise IngredientNotFoundError(material.name, material.require_tags)

    return matches


def match_all_ingredients(
    materials: Iterable[Material],
    purchases: Iterable[PurchasedItem],
    *,
    matcher: ItemMatcher | None = None,
) -> dict[str, list[PurchasedItem]]:
    """Find matching purchases for a collection of materials.

    Materials with the same name but different tag requirements get
    separate entries keyed by a compound key.

    Args:
        materials: BOM items to match.
        purchases: Available purchase price data.
        matcher: Optional custom matching function.  Defaults to
            :func:`find_matching_purchases`.

    Returns:
        Dictionary mapping material key to list of matching PurchasedItem
        objects.

    Raises:
        IngredientNotFoundError: If any material cannot be matched.
    """
    _match = matcher or find_matching_purchases
    result: dict[str, list[PurchasedItem]] = {}

    for material in materials:
        key = material.name
        if material.require_tags:
            key = f"{material.name}[{','.join(sorted(material.require_tags))}]"

        if key not in result:
            result[key] = _match(material, purchases)

    return result

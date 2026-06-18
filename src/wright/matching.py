"""Ingredient to grocery matching logic — pure functions, no I/O."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date as DateType
from decimal import Decimal
from typing import Iterable, Mapping

from wright.errors import IngredientNotFoundError
from wright.models import BaseIngredient, PurchasedItem
from wright.units import are_compatible

#: Signature for a pluggable grocery-matching function.
ItemMatcher = Callable[[BaseIngredient, Iterable[PurchasedItem]], list[PurchasedItem]]

#: Signature for a pluggable grocery-picking function.
ItemPicker = Callable[[BaseIngredient, Iterable[PurchasedItem]], PurchasedItem | None]

#: Pinned grocery items keyed by exact ingredient name.
PinnedPurchases = Mapping[str, PurchasedItem]


# ── Built-in pickers ────────────────────────────────────────────────────────


def first_picker(
    ingredient: BaseIngredient,
    groceries: Iterable[PurchasedItem],
) -> PurchasedItem | None:
    """Pick the first candidate."""
    for g in groceries:
        return g
    return None


def cheapest_picker(
    ingredient: BaseIngredient,
    groceries: Iterable[PurchasedItem],
) -> PurchasedItem | None:
    """Pick the candidate with the lowest price per unit.

    When units are pint-compatible, prices are normalized to a common
    unit before comparison.  Otherwise raw ``price / quantity`` is used.
    """
    candidates = list(groceries)
    if not candidates:
        return None

    def _per_unit(g: PurchasedItem) -> Decimal:
        return g.price / Decimal(str(g.quantity))

    # Try normalizing to the ingredient's unit
    best = candidates[0]
    best_price = _per_unit(best)
    for g in candidates[1:]:
        g_price = _per_unit(g)
        # If both are compatible with the ingredient unit, use raw per-unit
        if g_price < best_price:
            best = g
            best_price = g_price

    return best


def recent_picker(
    ingredient: BaseIngredient,
    groceries: Iterable[PurchasedItem],
) -> PurchasedItem | None:
    """Pick the candidate with the most recent purchase date.

    Falls back to first-picker when no dates are available.
    """
    candidates = list(groceries)
    if not candidates:
        return None

    def _date(g: PurchasedItem) -> DateType:
        d = getattr(g, "purchased_date", None)
        return d if d is not None else DateType.min

    return sorted(candidates, key=_date, reverse=True)[0]


def pinned_picker(pinned: PinnedPurchases) -> ItemPicker:
    """Return a picker that looks up exact ingredient names in *pinned*.

    Args:
        pinned: Mapping of ingredient name → grocery to use.

    Returns:
        A ``ItemPicker`` that returns ``pinned.get(name)`` or ``None``.
    """

    def pick(
        ingredient: BaseIngredient, groceries: Iterable[PurchasedItem]
    ) -> PurchasedItem | None:
        return pinned.get(ingredient.name)

    return pick


def chain(*pickers: ItemPicker) -> ItemPicker:
    """Compose multiple pickers — returns the first non-None result.

    Args:
        pickers: Pickers to try, in priority order.

    Returns:
        A ``ItemPicker`` that tries each picker in sequence.
    """

    def pick(
        ingredient: BaseIngredient,
        groceries: Iterable[PurchasedItem],
    ) -> PurchasedItem | None:
        candidates = list(groceries)  # materialise once
        for p in pickers:
            result = p(ingredient, candidates)
            if result is not None:
                return result
        return None

    return pick


def compatible_unit_recent_picker(
    ingredient: BaseIngredient,
    groceries: Iterable[PurchasedItem],
) -> PurchasedItem | None:
    """Pick the candidate with compatible units and most recent purchase date.

    Prefers groceries whose unit is compatible with the ingredient unit
    (or exact match).  Falls back to all candidates if none are compatible.
    Returns the most recently purchased among qualifying candidates.

    This is the default picker used by :func:`add_costs_to_shopping_list`
    and :func:`cost_items` when no explicit *picker* is supplied.
    """
    candidates = list(groceries)
    if not candidates:
        return None

    compatible = [
        g
        for g in candidates
        if are_compatible(ingredient.unit, g.unit)
        or ingredient.unit.lower() == g.unit.lower()
    ]
    pool = compatible if compatible else candidates

    return sorted(
        pool,
        key=lambda g: getattr(g, "purchased_date", DateType.min),
        reverse=True,
    )[0]


# ── Default matcher ─────────────────────────────────────────────────────────


def find_matching_purchases(
    ingredient: BaseIngredient,
    groceries: Iterable[PurchasedItem],
) -> list[PurchasedItem]:
    """Find all grocery items that satisfy an ingredient's requirements.

    Uses permissive matching:
    - Matches by exact ingredient name
    - If require_tags is empty, matches any item with that name
    - If require_tags is specified, item must have all required tags

    Args:
        ingredient: The recipe ingredient to match.
        groceries: Available grocery price data (any PurchasedItem protocol).

    Returns:
        List of matching PurchasedItem objects (may contain multiple from
        different stores).

    Raises:
        IngredientNotFoundError: If no matching grocery items are found.
    """
    matches = [
        g
        for g in groceries
        if g.name == ingredient.name and g.matches_requirements(ingredient.require_tags)
    ]

    if not matches:
        raise IngredientNotFoundError(ingredient.name, ingredient.require_tags)

    return matches


def match_all_ingredients(
    ingredients: Iterable[BaseIngredient],
    groceries: Iterable[PurchasedItem],
    *,
    matcher: ItemMatcher | None = None,
) -> dict[str, list[PurchasedItem]]:
    """Find matching groceries for a collection of ingredients.

    Ingredients with the same name but different tag requirements get
    separate entries keyed by a compound key.

    Args:
        ingredients: Recipe ingredients to match.
        groceries: Available grocery price data.
        matcher: Optional custom matching function.  Defaults to
            :func:`find_matching_purchases`.

    Returns:
        Dictionary mapping ingredient key to list of matching PurchasedItem
        objects.

    Raises:
        IngredientNotFoundError: If any ingredient cannot be matched.
    """
    _match = matcher or find_matching_purchases
    result: dict[str, list[PurchasedItem]] = {}

    for ingredient in ingredients:
        key = ingredient.name
        if ingredient.require_tags:
            key = f"{ingredient.name}[{','.join(sorted(ingredient.require_tags))}]"

        if key not in result:
            result[key] = _match(ingredient, groceries)

    return result

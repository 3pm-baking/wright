"""Shopping list generation and cost enrichment — pure functions, no I/O."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date as DateType
from decimal import Decimal

from pydantic import BaseModel, Field

from wright.costing import (
    calculate_ingredient_cost,
    convert_ingredient_to_grams,
)
from wright.errors import UnitConversionError
from wright.matching import (
    ItemMatcher,
    ItemPicker,
    compatible_unit_recent_picker,
    find_matching_purchases,
)
from wright.models import (
    Assembly,
    Ingredient,
    Material,
    PurchasedItem,
    Recipe,
    categorize_ingredient,
)
from wright.session import ProductionItem, ProductionRun
from wright.supply import SupplyItem
from wright.units import VOLUME_UNITS, are_compatible, parse_quantity, ureg

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _ensure_mapping(
    assemblies: Iterable[Assembly],
) -> Mapping[str, Assembly]:
    """Build a ``{name: assembly}`` map keyed by ``.name``.

    Handles ``Mapping`` inputs transparently (iterates values, not keys).
    """
    if isinstance(assemblies, Mapping):
        assemblies = list(assemblies.values())  # type: ignore[assignment]  # ty:ignore[invalid-assignment]
    return {a.name: a for a in assemblies}


def _apply_equivalent(material: Material) -> tuple[float, str]:
    """Return ``(quantity, unit)``, applying equivalent conversion if set.

    A material like ``{quantity: 1, unit: "box", equivalent_quantity: 500,
    equivalent_unit: "each"}`` becomes ``(500, "each")`` so it can be
    aggregated with other each-quantity entries of the same item.
    """
    if (
        material.equivalent_quantity is not None
        and material.equivalent_unit is not None
    ):
        return material.equivalent_quantity, material.equivalent_unit
    return material.quantity, material.unit


def format_quantity(quantity: float) -> str:
    """Format a quantity as int if whole, else one decimal place."""
    if quantity == int(quantity):
        return str(int(quantity))
    return f"{quantity:.1f}"


# Volume units normalized to ml before aggregation.


def normalize_volume_to_ml(
    quantity: float,
    unit: str,
) -> tuple[float, str]:
    """Convert volume units to ml for consistent accumulation.

    Non-volume units are returned unchanged.
    """
    if unit.lower() not in VOLUME_UNITS:
        return quantity, unit
    try:
        ml = ureg.Quantity(quantity, unit).to("ml")
        return float(ml.magnitude), "ml"
    except Exception:
        return quantity, unit


# ---------------------------------------------------------------------------
# Shopping list models
# ---------------------------------------------------------------------------


class IngredientGroup(BaseModel):
    """A group of related shopping items."""

    group_name: str = Field(..., description="Display name for the group")
    items: list[SupplyItem] = Field(..., description="Items in this group")


class ShoppingList(BaseModel):
    """Generated shopping list from a production run."""

    date: DateType = Field(..., description="Production date")
    production_summary: list[str] = Field(..., description="What is being made")
    target_dates: list[DateType] = Field(
        ..., description="Dates this shopping list supplies"
    )
    groups: list[IngredientGroup] = Field(..., description="Grouped ingredients")

    @property
    def all_items(self) -> list[SupplyItem]:
        """Get all items across all groups."""
        return [item for group in self.groups for item in group.items]


# ---------------------------------------------------------------------------
# Shopping list generation
# ---------------------------------------------------------------------------


def estimate_total_items(
    session: ProductionRun,
    assemblies: Iterable[Assembly],
) -> int:
    """Estimate the total number of items a production run will produce.

    Uses the midpoint of each assembly's serving range multiplied by batch
    quantity.  Assemblies without servings contribute 0.

    Args:
        session: The production run.
        assemblies: Assemblies keyed by ``.name`` (list, tuple, etc.).

    Returns:
        Estimated total item count (rounded to nearest integer).
    """
    asm_map = _ensure_mapping(assemblies)
    total: float = 0.0
    for item in session.production:
        assembly = asm_map.get(item.assembly)
        if assembly is None:
            continue
        if isinstance(assembly, Recipe):
            if assembly.servings is None:
                continue
            min_s, max_s = assembly._servings_bounds()
            midpoint = (min_s + max_s) / 2.0
            total += midpoint * item.quantity

    return round(total)


# ---------------------------------------------------------------------------
# Product reference expansion
# ---------------------------------------------------------------------------


def _expand_ingredient(
    material: Material,
    assemblies: Mapping[str, Assembly],
    visited: frozenset[str],
) -> list[Material]:
    """Recursively expand a product_ref item into its sub-materials.

    Scales sub-assembly materials by ``grams_used / yield`` when the
    referenced assembly is a :class:`Recipe` with ``net_weight_grams``.
    For non-``Recipe`` assemblies, product_ref expansion is skipped
    (returned as-is).

    Cycle detection via *visited* prevents infinite recursion.
    """
    if material.product_ref is None:
        return [material]

    ref_name = material.product_ref
    if ref_name in visited:
        return [material]

    sub_assembly = assemblies.get(ref_name)
    if sub_assembly is None:
        return [material]

    # Only Recipes have net_weight_grams for proportional scaling
    if not isinstance(sub_assembly, Recipe):
        return [material]

    if sub_assembly.net_weight_grams is None or sub_assembly.net_weight_grams <= 0:
        return [material]

    try:
        grams_used = convert_ingredient_to_grams(material)
    except UnitConversionError:
        return [material]

    ratio = grams_used / sub_assembly.net_weight_grams

    result: list[Material] = []
    for sub_ing in sub_assembly.all_ingredients:
        if sub_ing.byproduct or sub_ing.quantity == 0:
            continue
        scaled = sub_ing.scale(ratio)
        result.extend(_expand_ingredient(scaled, assemblies, visited | {ref_name}))

    return result


def _expand_all_ingredients(
    materials: list[Material],
    assemblies: Mapping[str, Assembly],
    visited: frozenset[str],
) -> list[Material]:
    """Expand all product_ref items in a flat list."""
    result: list[Material] = []
    for mat in materials:
        result.extend(_expand_ingredient(mat, assemblies, visited))
    return result


# ---------------------------------------------------------------------------
# Shopping list generation
# ---------------------------------------------------------------------------


def generate_shopping_list(
    session: ProductionRun,
    assemblies: Iterable[Assembly],
    *,
    volume_normalizer: Callable[[float, str], tuple[float, str]] | None = None,
    display_normalizer: Callable[[float, str], tuple[float, str]] | None = None,
) -> ShoppingList:
    """Generate a consolidated shopping list from a production run.

    Aggregates materials across all assemblies, normalizing volume units
    to ml for consistent accumulation.  Byproduct and zero-quantity
    items are excluded.

    Args:
        session: The production run to generate a list for.
        assemblies: Assemblies keyed by ``.name`` (list, tuple, etc.).
            Must contain every assembly referenced by the session's
            production items.
        volume_normalizer: Optional function ``(quantity, unit) -> (quantity, unit)``
            called on each material to normalize units for accumulation.
            Defaults to :func:`normalize_volume_to_ml` (converts volume
            units to ml).
        display_normalizer: Optional function ``(quantity, unit) -> (quantity, unit)``
            called to format accumulated quantities for display.
            Defaults to :func:`normalize_volume_us` (gallons,
            quarts, floz, tbsp, tsp hierarchy).

    Returns:
        ``ShoppingList`` with grouped items.

    Raises:
        KeyError: If a production item references an assembly name not in
            the *assemblies* (wrapped as ``RecipeLoadError`` in the full
            application).
    """
    asm_map = _ensure_mapping(assemblies)

    # (name, tags_tuple) → accumulated data
    ingredient_totals: dict[
        tuple[str, tuple[str, ...]],
        dict,
    ] = defaultdict(lambda: {"quantity": 0.0, "unit": None, "tags": set()})

    production_summary: list[str] = []

    for production_item in session.production:
        assembly = asm_map[production_item.assembly]
        scaled = assembly.size_up(production_item.quantity)
        production_summary.append(
            f"{format_quantity(production_item.quantity)}× {assembly.name}"
        )

        for material in _expand_all_ingredients(
            scaled.all_materials, asm_map, visited=frozenset()
        ):
            if material.byproduct:
                continue

            key = (
                material.name,
                tuple(sorted(material.require_tags)),
            )

            raw_qty, raw_unit = _apply_equivalent(material)
            qty_in, unit_in = (volume_normalizer or normalize_volume_to_ml)(
                raw_qty, raw_unit
            )

            if ingredient_totals[key]["unit"] is None:
                ingredient_totals[key]["unit"] = unit_in
                ingredient_totals[key]["quantity"] = qty_in
            else:
                existing_unit = ingredient_totals[key]["unit"]
                existing_quantity = ingredient_totals[key]["quantity"]

                if unit_in == existing_unit:
                    ingredient_totals[key]["quantity"] = existing_quantity + qty_in
                elif are_compatible(unit_in, existing_unit):
                    try:
                        new_qty = ureg.Quantity(qty_in, unit_in)
                        existing_qty = ureg.Quantity(existing_quantity, existing_unit)
                        total_qty = existing_qty + new_qty
                        ingredient_totals[key]["quantity"] = float(total_qty.magnitude)
                        ingredient_totals[key]["unit"] = str(total_qty.units)
                    except Exception:
                        ingredient_totals[key]["quantity"] = existing_quantity + qty_in
                else:
                    ingredient_totals[key]["quantity"] = existing_quantity + qty_in

            ingredient_totals[key]["tags"].update(material.require_tags)

    shopping_items: list[SupplyItem] = []
    for (name, _tag_tuple), details in ingredient_totals.items():
        display_qty, display_unit = (display_normalizer or normalize_volume_us)(
            details["quantity"], details["unit"]
        )

        shopping_items.append(
            SupplyItem(
                name=name,
                quantity=round(display_qty, 2),
                unit=display_unit,
                tags=list(details["tags"]),
            )
        )

    grouped_items = group_shopping_items(shopping_items)

    return ShoppingList(
        date=session.date,
        production_summary=production_summary,
        target_dates=session.target_dates,
        groups=grouped_items,
    )


def group_shopping_items(
    items: list[SupplyItem],
    *,
    kitchen_items: frozenset[str] | None = None,
    category_rules: list | None = None,
) -> list[IngredientGroup]:
    """Group items by ingredient category.

    Args:
        items: Items to group.
        kitchen_items: Item names to exclude (e.g. ``{"water"}``).
            Defaults to an empty set.
        category_rules: Optional categorization rules for
            :func:`categorize_ingredient`.  If not provided, items are
            placed in ``"Other"``.

    Returns:
        List of ``IngredientGroup`` sorted alphabetically.
    """
    if kitchen_items is None:
        kitchen_items = frozenset()

    groups: dict[str, list[SupplyItem]] = defaultdict(list)

    for item in items:
        if item.name.lower() in kitchen_items:
            continue
        group_name = categorize_ingredient(item.name, rules=category_rules) or "Other"
        groups[group_name].append(item)

    sorted_groups: list[IngredientGroup] = []
    for group_name, group_items in groups.items():
        sorted_items = sorted(group_items, key=lambda x: (x.name, str(x.tags)))
        sorted_groups.append(IngredientGroup(group_name=group_name, items=sorted_items))

    return sorted(sorted_groups, key=lambda x: x.group_name)


def normalize_volume_us(
    quantity: float,
    unit: str,
) -> tuple[float, str]:
    """Convert volume units to grocery store formats.

    Rules:
        - >= 1 gallon → gallons
        - >= 1 quart (but < 1 gallon) → quarts
        - >= 8 floz (but < 1 quart) → fluid ounces
        - < 8 floz → keep original unit (tsp/tbsp for small amounts)
    """
    if unit.lower() not in VOLUME_UNITS:
        return quantity, unit

    try:
        qty = ureg.Quantity(quantity, unit)

        gallons = qty.to("gallon")
        if gallons.magnitude >= 1.0:
            return round(gallons.magnitude, 2), "gallon"

        quarts = qty.to("quart")
        if quarts.magnitude >= 1.0:
            return round(quarts.magnitude, 2), "quart"

        floz = qty.to("floz")
        if floz.magnitude >= 8.0:
            return round(floz.magnitude, 1), "floz"

        # Small volumes — keep in tbsp/tsp for grocery matching accuracy
        tbsp = qty.to("tablespoon")
        if tbsp.magnitude >= 1.0:
            return round(float(tbsp.magnitude), 2), "tbsp"

        tsp = qty.to("teaspoon")
        return round(float(tsp.magnitude), 2), "tsp"

    except Exception:
        return quantity, unit


# ---------------------------------------------------------------------------
# Cost enrichment
# ---------------------------------------------------------------------------


@dataclass
class ShoppingItemWithCost:
    """Item enriched with pricing information."""

    item: SupplyItem
    price_per_unit: Decimal | None
    """Price per display unit (e.g. per 100g, per each)."""

    price_unit: str
    """Display unit for the price (e.g. ``'100g'``, ``'each'``)."""

    total_cost: Decimal | None
    """Total cost for this item."""

    store: str | None
    """Store with the best / most recent price."""

    purchase_date: DateType | None
    """Date of the grocery purchase used for pricing."""

    missing_price: bool
    """``True`` if no grocery data was found for this item."""


def _default_price_display(
    item: SupplyItem, purchase: PurchasedItem
) -> tuple[Decimal, str]:
    """Return ``(price_per_unit, display_unit)`` for a shopping item.

    Per-100g for metric weight units, per-100ml for metric volume units,
    per-package-price otherwise.
    """
    if item.unit.lower() in {"g", "gram", "grams", "ml", "milliliter", "milliliters"}:
        try:
            purchase_in_item = (
                parse_quantity(purchase.quantity, purchase.unit).to(item.unit).magnitude
            )
            price_per_base = purchase.price / Decimal(str(purchase_in_item))
            display_unit = (
                "100g" if item.unit.lower() in {"g", "gram", "grams"} else "100ml"
            )
            return (price_per_base * Decimal("100"), display_unit)
        except Exception:
            pass
    return (purchase.price / Decimal(str(purchase.quantity)), item.unit)


def _cost_one_item(
    material: Material,
    purchases: Iterable[PurchasedItem],
    *,
    density_data: dict,
    matcher: ItemMatcher,
    picker: ItemPicker | None,
    price_display_fn: Callable[[SupplyItem, PurchasedItem], tuple[Decimal, str]],
) -> ShoppingItemWithCost:
    """Cost a single material against purchases — shared by both cost functions."""
    supply_item = SupplyItem(
        name=material.name,
        quantity=material.quantity,
        unit=material.unit,
        tags=material.require_tags,
    )

    try:
        matching = matcher(material, purchases)
        selected: PurchasedItem | None = None

        if matching:
            if picker is not None:
                selected = picker(material, matching)
            else:
                selected = compatible_unit_recent_picker(material, matching)

        if selected is None:
            return ShoppingItemWithCost(
                item=supply_item,
                price_per_unit=None,
                price_unit=material.unit,
                total_cost=None,
                store=None,
                purchase_date=None,
                missing_price=True,
            )

        cost = calculate_ingredient_cost(
            material, selected, density_data=density_data
        )

        price_per_unit, display_unit = price_display_fn(supply_item, selected)

        return ShoppingItemWithCost(
            item=supply_item,
            price_per_unit=price_per_unit,
            price_unit=display_unit,
            total_cost=cost,
            store=selected.store,
            purchase_date=getattr(selected, "purchased_date", None),
            missing_price=False,
        )

    except Exception:
        return ShoppingItemWithCost(
            item=supply_item,
            price_per_unit=None,
            price_unit=material.unit,
            total_cost=None,
            store=None,
            purchase_date=None,
            missing_price=True,
        )


def calculate_shopping_list_cost(
    shopping_list: ShoppingList,
    purchases: Iterable[PurchasedItem],
    *,
    density_data: dict | None = None,
    matcher: ItemMatcher | None = None,
    picker: ItemPicker | None = None,
    price_display_fn: Callable[[SupplyItem, PurchasedItem], tuple[Decimal, str]]
    | None = None,
) -> list[ShoppingItemWithCost]:
    """Enrich each item with cost information.

    For each item:
    1. Convert to an ingredient for matching.
    2. Find matching purchase items via *matcher*.
    3. Select one purchase via *picker*
       (default: :func:`compatible_unit_recent_picker`).
    4. Calculate cost using unit conversion.
    5. Compute a readable price per display unit via *price_display_fn*.

    Args:
        shopping_list: Generated shopping list.
        purchases: Available purchase price data.
        density_data: Optional density data for unit conversion.
        matcher: Optional custom matching function.  Defaults to
            :func:`find_matching_purchases`.
        picker: Optional custom picking function.  Defaults to
            :func:`compatible_unit_recent_picker`.  Use :func:`chain`
            to compose.
        price_display_fn: Optional callback
            ``(item, purchase) -> (price_per_unit, display_unit)``
            for customizing unit price display.  Defaults to per-100g for
            metric weight units, per-100ml for metric volume units,
            per-package otherwise.

    Returns:
        List of ``ShoppingItemWithCost``, one per item.
    """
    return [
        _cost_one_item(
            Ingredient(
                name=si.name,
                quantity=si.quantity,
                unit=si.unit,
                require_tags=si.tags,
            ),
            purchases,
            density_data=density_data or {},
            matcher=matcher or find_matching_purchases,
            picker=picker,
            price_display_fn=price_display_fn or _default_price_display,
        )
        for si in shopping_list.all_items
    ]


def calculate_item_costs(
    items: Sequence[Material],
    purchases: Iterable[PurchasedItem],
    *,
    density_data: dict | None = None,
    matcher: ItemMatcher | None = None,
    picker: ItemPicker | None = None,
) -> list[ShoppingItemWithCost]:
    """Cost arbitrary items — food, construction materials, tools, etc.

    Reuses the same matching, picking, and costing pipeline as
    :func:`calculate_shopping_list_cost`, but works on a flat list of
    ``Material`` instead of a ``ShoppingList``.

    Args:
        items: Items to cost (recipe ingredients, lumber, hardware, etc.).
        purchases: Available purchase price data.
        density_data: Optional density data for unit conversion.
        matcher: Optional custom matching function.
        picker: Optional custom picking function.

    Returns:
        List of ``ShoppingItemWithCost``, one per input item.
    """
    return [
        _cost_one_item(
            item,
            purchases,
            density_data=density_data or {},
            matcher=matcher or find_matching_purchases,
            picker=picker,
            price_display_fn=_default_price_display,
        )
        for item in items
    ]


# ---------------------------------------------------------------------------
# Menu analysis
# ---------------------------------------------------------------------------


@dataclass
class MenuAnalysis:
    """Cost analysis for an arbitrary menu (a set of recipes with quantities).

    Attributes:
        production: The recipe/quantity pairs that were analyzed.
        items: All aggregated ingredients with cost data, sorted by
            total_cost descending (missing-price items last).
        total_cost: Grand total of all ingredient costs (``None`` if any
            prices are missing).
        missing_ingredients: Names of ingredients whose price could not
            be found.
    """

    production: list[ProductionItem]
    items: list[ShoppingItemWithCost]
    total_cost: Decimal | None
    missing_ingredients: list[str]

    @property
    def top_drivers(self) -> list[ShoppingItemWithCost]:
        """Items with known costs, sorted by total_cost descending."""
        return [i for i in self.items if not i.missing_price]

    @property
    def known_total(self) -> Decimal:
        """Sum of costs for all items that have a price."""
        return sum(
            (i.total_cost for i in self.items if i.total_cost is not None),
            Decimal("0"),
        )

    def cost_share(self, item: ShoppingItemWithCost) -> float:
        """Return this item's share of total cost as a fraction 0–1."""
        base = self.total_cost if self.total_cost is not None else self.known_total
        if not base or item.total_cost is None:
            return 0.0
        return float(item.total_cost / base)


def analyze_menu(
    production: list[ProductionItem],
    assemblies: Iterable[Assembly],
    purchases: Iterable[PurchasedItem],
    *,
    density_data: dict | None = None,
    matcher: ItemMatcher | None = None,
    picker: ItemPicker | None = None,
    date: DateType | None = None,
) -> MenuAnalysis:
    """Analyze the ingredient costs for an arbitrary menu or project.

    Builds a virtual production run from *production*, generates the
    aggregated shopping list, then enriches every line with the selected
    purchase price.

    Args:
        production: List of ``ProductionItem`` (assembly name + quantity).
        assemblies: Assemblies keyed by ``.name`` (list, tuple, etc.).
        purchases: Available purchase price data.
        density_data: Optional density data for unit conversion.
        matcher: Optional custom matching function.  Defaults to
            :func:`find_matching_purchases`.
        picker: Optional custom picking function.  Defaults to
            compatible-unit most-recent selection.
        date: Optional date for the virtual production run.
            Defaults to ``date.today()``.

    Returns:
        A ``MenuAnalysis`` with aggregated items, total cost, and
        convenience helpers.
    """
    from datetime import date as _date

    virtual_date = date or _date.today()

    virtual_session = ProductionRun(
        date=virtual_date,
        production=production,
        target_dates=[virtual_date],
    )

    shopping_list = generate_shopping_list(virtual_session, assemblies)
    items_with_cost = calculate_shopping_list_cost(
        shopping_list,
        purchases,
        density_data=density_data,
        matcher=matcher,
        picker=picker,
    )

    # Sort: known costs descending, then missing-price items
    known = sorted(
        [i for i in items_with_cost if not i.missing_price],
        key=lambda i: i.total_cost or Decimal("0"),
        reverse=True,
    )
    missing = [i for i in items_with_cost if i.missing_price]
    sorted_items = known + missing

    total_cost: Decimal | None = None
    if not missing:
        total_cost = sum(
            (i.total_cost for i in known if i.total_cost is not None),
            Decimal("0"),
        )

    missing_names = [i.item.name for i in missing]

    return MenuAnalysis(
        production=production,
        items=sorted_items,
        total_cost=total_cost,
        missing_ingredients=missing_names,
    )

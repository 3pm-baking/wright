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
    DensityData,
    Ingredient,
    Material,
    PurchasedItem,
    Recipe,
    categorize_item,
)
from wright.session import ProductionItem, ProductionRun
from wright.supply import SupplyItem
from wright.units import (
    VOLUME_UNITS,
    WEIGHT_UNITS,
    are_compatible,
    parse_quantity,
    ureg,
)

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _ensure_mapping(
    assemblies: Iterable[Assembly],
) -> Mapping[str, Assembly]:
    """Build a ``{name: assembly}`` map keyed by ``.name``."""
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


def _default_key(material: Material) -> tuple:
    """Default grouping key: ``(name, tuple(sorted(tags)))``."""
    return (material.name, tuple(sorted(material.require_tags)))


def _default_item_factory(
    key: tuple,
    quantity: float,
    unit: str,
    tags: set[str],
) -> SupplyItem:
    """Default item factory: ``SupplyItem(name=key[0], ...)``."""
    return SupplyItem(
        name=key[0],
        quantity=quantity,
        unit=unit,
        tags=list(tags),
    )


def _default_merge_numeric(
    accumulated: dict[str, float],
    incoming: dict[str, float],
) -> dict[str, float]:
    """Default merge strategy: keep the first (accumulated) values.

    Override with a callback that sums, averages, takes the min, etc.
    """
    return accumulated


def generate_shopping_list(
    session: ProductionRun,
    assemblies: Iterable[Assembly],
    *,
    volume_normalizer: Callable[[float, str], tuple[float, str]] | None = None,
    display_normalizer: Callable[..., tuple[float, str]] | None = None,
    category_rules: list | None = None,
    key_fn: Callable[[Material], tuple] | None = None,
    item_factory: Callable[[tuple, float, str, set[str]], SupplyItem] | None = None,
    merge_numeric: Callable[[dict[str, float], dict[str, float]], dict[str, float]]
    | None = None,
) -> ShoppingList:
    """Generate a consolidated shopping list from a production run.

    Aggregates materials across all assemblies, normalizing volume units
    to ml for consistent accumulation.  Byproduct and zero-quantity
    items are excluded.

    Args:
        session: The production run to generate a list for.
        assemblies: Assemblies referenced by production items (list or
            tuple). Must contain every assembly referenced by the
            session's production items.
        volume_normalizer: Optional function ``(quantity, unit) -> (quantity, unit)``
            called on each material to normalize units for accumulation.
            Defaults to :func:`normalize_volume_to_ml` (converts volume
            units to ml).
        display_normalizer: Optional function
            ``(quantity, unit, *, name="") -> (quantity, unit)`` called to
            format accumulated quantities for display.
            Receives the ingredient ``name`` (from the grouping key) for
            name-aware display decisions.  Defaults to
            :func:`normalize_volume_us`.
        category_rules: Optional list of :class:`CategoryRule` for
            grouping items by department.  Pass
            ``DEFAULT_CATEGORY_RULES`` for store layout grouping.
            If None, all items go to ``"Other"``.
        key_fn: Optional function ``(material) -> tuple`` that produces a
            grouping key.  Defaults to ``(name, tuple(sorted(tags)))``.
            Use a custom key to group by vendor, department, or any
            other material attribute.
        item_factory: Optional function ``(key, quantity, unit, tags) -> SupplyItem``
            that creates a display item from the accumulated data.  The
            *key* argument is the grouping tuple produced by *key_fn*.
            Defaults to ``SupplyItem(name=key[0], ...)``.  Use a custom
            factory to produce subclass instances (e.g. ``ShoppingItem``
            with a ``vendor`` field).

    Returns:
        ``ShoppingList`` with grouped items.

    Raises:
        KeyError: If a production item references an assembly name not in
            the *assemblies* (wrapped as ``RecipeLoadError`` in the full
            application).
    """
    _key = key_fn or _default_key
    _build = item_factory or _default_item_factory
    _merge = merge_numeric or _default_merge_numeric
    asm_map = _ensure_mapping(assemblies)

    def _blank_total() -> dict:
        return {"quantity": 0.0, "unit": None, "tags": set(), "numeric_attrs": {}}

    ingredient_totals: dict[tuple, dict] = defaultdict(_blank_total)

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

            key = _key(material)

            raw_qty, raw_unit = _apply_equivalent(material)
            qty_in, unit_in = (volume_normalizer or normalize_volume_to_ml)(
                raw_qty, raw_unit
            )

            if ingredient_totals[key]["unit"] is None:
                ingredient_totals[key]["unit"] = unit_in
                ingredient_totals[key]["quantity"] = qty_in
                ingredient_totals[key]["numeric_attrs"] = dict(material.numeric_attrs)
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

                ingredient_totals[key]["numeric_attrs"] = _merge(
                    ingredient_totals[key]["numeric_attrs"],
                    material.numeric_attrs,
                )

            ingredient_totals[key]["tags"].update(material.require_tags)

    shopping_items: list[SupplyItem] = []
    for key, details in ingredient_totals.items():
        normalizer = display_normalizer or normalize_volume_us
        display_qty, display_unit = normalizer(
            details["quantity"], details["unit"], name=key[0]
        )

        item = _build(
            key,
            round(display_qty, 2),
            display_unit,
            details["tags"],
        )
        if isinstance(item, SupplyItem):
            item.numeric_attrs = details.get("numeric_attrs", {})
        shopping_items.append(item)

    grouped_items = group_shopping_items(shopping_items, category_rules=category_rules)

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
        items: Shopping items to group.
        kitchen_items: Item names to exclude (e.g. ``{"water"}``).
            Defaults to an empty set.
        category_rules: Optional categorization rules for
            :func:`categorize_item`.  If not provided, items are
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
        group_name = categorize_item(item.name, rules=category_rules) or "Other"
        groups[group_name].append(item)

    sorted_groups: list[IngredientGroup] = []
    for group_name, group_items in groups.items():
        sorted_items = sorted(group_items, key=lambda x: (x.name, str(x.tags)))
        sorted_groups.append(IngredientGroup(group_name=group_name, items=sorted_items))

    return sorted(sorted_groups, key=lambda x: x.group_name)


def normalize_volume_us(
    quantity: float,
    unit: str,
    name: str = "",
) -> tuple[float, str]:
    """Convert volume units to grocery store formats.

    Rules:
        - >= 1 gallon → gallons
        - >= 1 quart (but < 1 gallon) → quarts
        - >= 8 floz (but < 1 quart) → fluid ounces
        - < 8 floz → keep original unit (tsp/tbsp for small amounts)

    Args:
        quantity: The quantity to normalize.
        unit: The unit to normalize.
        name: Ingredient name (ignored by this normalizer; accepted for
            compatibility with name-aware display normalizers).
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


def normalize_metric(
    quantity: float,
    unit: str,
    name: str = "",
) -> tuple[float, str]:
    """Convert metric units to display-friendly forms (volume and weight).

    Volume rules:
        - >= 1 L → L
        - >= 100 ml (but < 1 L) → ml
        - < 100 ml → keep original unit (tsp/tbsp often better for small)

    Weight rules:
        - >= 1 kg → kg
        - < 1 kg → g

    Args:
        quantity: The quantity to normalize.
        unit: The unit to normalize.
        name: Ingredient name (ignored by this normalizer; accepted for
            compatibility with name-aware display normalizers).
    """
    unit_lower = unit.lower()

    if unit_lower in VOLUME_UNITS:
        try:
            qty = ureg.Quantity(quantity, unit)
            liters = qty.to("liter")
            if liters.magnitude >= 1.0:
                return round(liters.magnitude, 2), "L"
            ml = qty.to("ml")
            return round(float(ml.magnitude), 1), "ml"
        except Exception:
            return quantity, unit

    if unit_lower in WEIGHT_UNITS:
        try:
            qty = ureg.Quantity(quantity, unit)
            kg = qty.to("kg")
            if kg.magnitude >= 1.0:
                return round(kg.magnitude, 2), "kg"
            g = qty.to("g")
            return round(float(g.magnitude), 1), "g"
        except Exception:
            return quantity, unit

    return quantity, unit


# ---------------------------------------------------------------------------
# Cost enrichment
# ---------------------------------------------------------------------------


@dataclass
class MaterialCost:
    """Item enriched with pricing information.

    Used for costing bill-of-materials items and shopping list items alike.
    The underlying :class:`SupplyItem` is accessible via ``.item``, and
    common fields (``name``, ``quantity``, ``unit``, ``tags``) are
    exposed directly as properties for convenience.
    """

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

    # -- delegating properties -------------------------------------------------

    @property
    def name(self) -> str:
        """Item name (delegates to :attr:`item.name`)."""
        return self.item.name

    @property
    def quantity(self) -> float:
        """Item quantity (delegates to :attr:`item.quantity`)."""
        return self.item.quantity

    @property
    def unit(self) -> str:
        """Item unit (delegates to :attr:`item.unit`)."""
        return self.item.unit

    @property
    def tags(self) -> list[str]:
        """Item tags (delegates to :attr:`item.tags`)."""
        return self.item.tags


ShoppingItemWithCost = MaterialCost
"""Backward-compatibility alias for :class:`MaterialCost`."""


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
    density_data: DensityData,
    matcher: ItemMatcher,
    picker: ItemPicker | None,
    price_display_fn: Callable[[SupplyItem, PurchasedItem], tuple[Decimal, str]],
) -> MaterialCost:
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
            return MaterialCost(
                item=supply_item,
                price_per_unit=None,
                price_unit=material.unit,
                total_cost=None,
                store=None,
                purchase_date=None,
                missing_price=True,
            )

        cost = calculate_ingredient_cost(material, selected, density_data=density_data)

        price_per_unit, display_unit = price_display_fn(supply_item, selected)

        return MaterialCost(
            item=supply_item,
            price_per_unit=price_per_unit,
            price_unit=display_unit,
            total_cost=cost,
            store=selected.store,
            purchase_date=getattr(selected, "purchased_date", None),
            missing_price=False,
        )

    except Exception:
        return MaterialCost(
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
    density_data: DensityData | None = None,
    matcher: ItemMatcher | None = None,
    picker: ItemPicker | None = None,
    price_display_fn: Callable[[SupplyItem, PurchasedItem], tuple[Decimal, str]]
    | None = None,
) -> list[MaterialCost]:
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
        List of ``MaterialCost``, one per item.

    See Also:
        :func:`calculate_item_costs` — for costing a flat list of
        :class:`Material` items directly.
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
    density_data: DensityData | None = None,
    matcher: ItemMatcher | None = None,
    picker: ItemPicker | None = None,
    price_display_fn: Callable[[SupplyItem, PurchasedItem], tuple[Decimal, str]]
    | None = None,
    per_unit: tuple[float, str] | None = None,
) -> list[MaterialCost]:
    """Cost arbitrary items — food, construction materials, tools, etc.

    Reuses the same matching, picking, and costing pipeline as
    :func:`calculate_shopping_list_cost`, but works on a flat list of
    ``Material`` instead of a ``ShoppingList``.

    When ``per_unit`` is provided, each item's ``total_cost`` is scaled
    to represent the cost for that unit quantity instead of the full
    material quantity.  For example, if a BOM lists "10 lb Barley" with
    ``total_cost=$20`` and ``per_unit=(12, "oz")``, the result will show
    ``total_cost=$1.50`` (cost per 12 oz).

    Args:
        items: Items to cost (recipe ingredients, lumber, hardware, etc.).
        purchases: Available purchase price data.
        density_data: Optional density data for unit conversion.
        matcher: Optional custom matching function.
        picker: Optional custom picking function.
        price_display_fn: Optional callback
            ``(item, purchase) -> (price_per_unit, display_unit)``
            for customizing unit price display.  Defaults to per-100g for
            metric weight units, per-100ml for metric volume units,
            per-package otherwise.
        per_unit: Optional ``(quantity, unit)`` pair to scale costs to a
            per-unit basis (e.g. ``(12, "oz")`` for cost per 12 oz).

    Returns:
        List of ``MaterialCost``, one per input item.

    See Also:
        :func:`calculate_recipe_cost` — for full recipe costing with
        serving breakdown and per-ingredient cost ranges.
    """
    results = [
        _cost_one_item(
            item,
            purchases,
            density_data=density_data or {},
            matcher=matcher or find_matching_purchases,
            picker=picker,
            price_display_fn=price_display_fn or _default_price_display,
        )
        for item in items
    ]

    if per_unit is not None:
        per_qty, per_unit_str = per_unit
        results = _scale_to_per_unit(results, items, per_qty, per_unit_str)

    return results


def _scale_to_per_unit(
    costs: list[MaterialCost],
    materials: Sequence[Material],
    per_qty: float,
    per_unit_str: str,
) -> list[MaterialCost]:
    """Scale costs proportionally from material quantity to ``per_qty``.

    For each pair ``(cost, material)``, scales ``total_cost`` by
    ``per_qty_in_material_units / material.quantity`` using pint unit
    conversion.  Items with incompatible units are left as-is.
    """
    scaled: list[MaterialCost] = []
    for cost, material in zip(costs, materials, strict=False):
        if cost.total_cost is None:
            scaled.append(cost)
            continue
        try:
            per_qty_pint = parse_quantity(per_qty, per_unit_str)
            per_in_mat_units = float(per_qty_pint.to(material.unit).magnitude)
            ratio = per_in_mat_units / material.quantity
            new_total = cost.total_cost * Decimal(str(ratio))
            scaled.append(
                MaterialCost(
                    item=cost.item,
                    price_per_unit=cost.price_per_unit,
                    price_unit=cost.price_unit,
                    total_cost=new_total,
                    store=cost.store,
                    purchase_date=cost.purchase_date,
                    missing_price=cost.missing_price,
                )
            )
        except Exception:
            scaled.append(cost)
    return scaled


# ---------------------------------------------------------------------------
# Component-level cost rollup
# ---------------------------------------------------------------------------


def cost_by_component(
    assembly: Assembly,
    purchases: Iterable[PurchasedItem],
    *,
    density_data: DensityData | None = None,
    matcher: ItemMatcher | None = None,
    picker: ItemPicker | None = None,
) -> dict[str, Decimal]:
    """Calculate total cost per component for an assembly.

    For each component, costs all materials using the same matching,
    picking, and costing pipeline as :func:`calculate_item_costs`.

    Args:
        assembly: The assembly to analyze.
        purchases: Available purchase price data.
        density_data: Optional density data for unit conversion.
        matcher: Optional custom matching function.
        picker: Optional custom picking function.

    Returns:
        Dictionary mapping component name to its total cost (using
        the midpoint of available price ranges when multiple sources
        exist).  Components with no cost data contribute ``Decimal("0")``.
    """
    result: dict[str, Decimal] = {}
    for component in assembly.components:
        costs = calculate_item_costs(
            component.materials,
            purchases,
            density_data=density_data,
            matcher=matcher,
            picker=picker,
        )
        total = sum(
            (c.total_cost for c in costs if c.total_cost is not None),
            Decimal("0"),
        )
        result[component.name] = total
    return result


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
    items: list[MaterialCost]
    total_cost: Decimal | None
    missing_ingredients: list[str]

    @property
    def top_drivers(self) -> list[MaterialCost]:
        """Items with known costs, sorted by total_cost descending."""
        return [i for i in self.items if not i.missing_price]

    @property
    def known_total(self) -> Decimal:
        """Sum of costs for all items that have a price."""
        return sum(
            (i.total_cost for i in self.items if i.total_cost is not None),
            Decimal("0"),
        )

    def cost_share(self, item: MaterialCost) -> float:
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
    density_data: DensityData | None = None,
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

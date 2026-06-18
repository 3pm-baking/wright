"""Shopping list generation and cost enrichment — pure functions, no I/O."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date as DateType
from decimal import Decimal
from typing import Callable, Iterable, Mapping

from pydantic import BaseModel, Field

from wright.costing import (
    calculate_ingredient_cost,
    ingredient_to_grams,
)
from wright.errors import UnitConversionError
from wright.matching import (
    ItemMatcher,
    ItemPicker,
    compatible_unit_recent_picker,
    find_matching_purchases,
)
from wright.models import (
    BaseIngredient,
    BaseRecipe,
    PurchasedItem,
    categorize_ingredient,
)
from wright.session import ProductionItem, ProductionRun
from wright.units import VOLUME_UNITS, are_compatible, parse_quantity, ureg


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _apply_equivalent(ingredient: BaseIngredient) -> tuple[float, str]:
    """Return ``(quantity, unit)``, applying equivalent conversion if set.

    An ingredient like ``{quantity: 1, unit: "packet", equivalent_quantity: 37,
    equivalent_unit: "g"}`` becomes ``(37, "g")`` so it can be aggregated with
    other gram-quantity entries of the same ingredient.
    """
    if (
        ingredient.equivalent_quantity is not None
        and ingredient.equivalent_unit is not None
    ):
        return ingredient.equivalent_quantity, ingredient.equivalent_unit
    return ingredient.quantity, ingredient.unit


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


class ShoppingItem(BaseModel):
    """A consolidated ingredient needed for shopping."""

    name: str = Field(..., description="Ingredient name")
    total_quantity: float = Field(..., description="Total quantity needed")
    unit: str = Field(..., description="Unit of measurement")
    tags: list[str] = Field(default_factory=list, description="Required tags")


class IngredientGroup(BaseModel):
    """A group of related shopping items."""

    group_name: str = Field(..., description="Display name for the group")
    items: list[ShoppingItem] = Field(..., description="Shopping items in this group")


class ShoppingList(BaseModel):
    """Generated shopping list from a production run."""

    date: DateType = Field(..., description="Production date")
    production_summary: list[str] = Field(..., description="What is being made")
    target_dates: list[DateType] = Field(
        ..., description="Dates this shopping list supplies"
    )
    groups: list[IngredientGroup] = Field(..., description="Grouped ingredients")

    @property
    def all_items(self) -> list[ShoppingItem]:
        """Get all shopping items across all groups."""
        return [item for group in self.groups for item in group.items]


# ---------------------------------------------------------------------------
# Shopping list generation
# ---------------------------------------------------------------------------


def estimate_total_items(
    session: ProductionRun,
    recipes: Mapping[str, BaseRecipe],
) -> int:
    """Estimate the total number of items a production run will produce.

    Uses the midpoint of each recipe's serving range multiplied by batch
    quantity.  Recipes without servings contribute 0.

    Args:
        session: The production run.
        recipes: Mapping of recipe name → ``BaseRecipe``.

    Returns:
        Estimated total item count (rounded to nearest integer).
    """
    total: float = 0.0
    for item in session.production:
        recipe = recipes.get(item.recipe)
        if recipe is None:
            continue
        if recipe.servings is None:
            continue
        min_s, max_s = recipe._servings_bounds()
        midpoint = (min_s + max_s) / 2.0
        total += midpoint * item.quantity

    return round(total)


# ---------------------------------------------------------------------------
# Product reference expansion
# ---------------------------------------------------------------------------


def _expand_ingredient(
    ingredient: BaseIngredient,
    recipes: Mapping[str, BaseRecipe],
    visited: frozenset[str],
) -> list[BaseIngredient]:
    """Recursively expand a product_ref ingredient into its sub-ingredients.

    Scales sub-recipe ingredients by ``grams_used / yield`` so the
    shopping list reflects the actual quantities needed.
    Cycle detection via *visited* prevents infinite recursion.
    """
    if ingredient.product_ref is None:
        return [ingredient]

    ref_name = ingredient.product_ref
    if ref_name in visited:
        return [ingredient]

    sub_recipe = recipes.get(ref_name)
    if sub_recipe is None:
        return [ingredient]

    if sub_recipe.net_weight_grams is None or sub_recipe.net_weight_grams <= 0:
        return [ingredient]

    try:
        grams_used = ingredient_to_grams(ingredient)
    except UnitConversionError:
        return [ingredient]

    ratio = grams_used / sub_recipe.net_weight_grams

    result: list[BaseIngredient] = []
    for sub_ing in sub_recipe.all_ingredients:
        if sub_ing.byproduct or sub_ing.quantity == 0:
            continue
        scaled = sub_ing.scale(ratio)
        result.extend(_expand_ingredient(scaled, recipes, visited | {ref_name}))

    return result


def _expand_all_ingredients(
    ingredients: list[BaseIngredient],
    recipes: Mapping[str, BaseRecipe],
    visited: frozenset[str],
) -> list[BaseIngredient]:
    """Expand all product_ref ingredients in a flat list."""
    result: list[BaseIngredient] = []
    for ing in ingredients:
        result.extend(_expand_ingredient(ing, recipes, visited))
    return result


# ---------------------------------------------------------------------------
# Shopping list generation
# ---------------------------------------------------------------------------


def generate_shopping_list(
    session: ProductionRun,
    recipes: Mapping[str, BaseRecipe],
    *,
    volume_normalizer: Callable[[float, str], tuple[float, str]] | None = None,
    display_normalizer: Callable[[float, str], tuple[float, str]] | None = None,
) -> ShoppingList:
    """Generate a consolidated shopping list from a production run.

    Aggregates ingredients across all recipes, normalizing volume units
    to ml for consistent accumulation.  Byproduct and zero-quantity
    ingredients are excluded.

    Args:
        session: The production run to generate a list for.
        recipes: Mapping of recipe name → ``BaseRecipe``.  Must contain
            every recipe referenced by the session's production items.
        volume_normalizer: Optional function ``(quantity, unit) -> (quantity, unit)``
            called on each ingredient to normalize units for accumulation.
            Defaults to :func:`normalize_volume_to_ml` (converts volume
            units to ml).
        display_normalizer: Optional function ``(quantity, unit) -> (quantity, unit)``
            called to format accumulated quantities for display.
            Defaults to :func:`normalize_volume_for_grocery` (gallons,
            quarts, floz, tbsp, tsp hierarchy).

    Returns:
        ``ShoppingList`` with grouped ingredients.

    Raises:
        KeyError: If a production item references a recipe name not in
            the *recipes* mapping (wrapped as ``RecipeLoadError`` in the
            full application).
    """
    # (name, tags_tuple) → accumulated data
    ingredient_totals: dict[
        tuple[str, tuple[str, ...]],
        dict,
    ] = defaultdict(lambda: {"quantity": 0.0, "unit": None, "tags": set()})

    production_summary: list[str] = []

    for production_item in session.production:
        recipe = recipes[production_item.recipe]
        scaled_recipe = recipe.size_up(production_item.quantity)
        production_summary.append(
            f"{format_quantity(production_item.quantity)}× {recipe.name}"
        )

        for ingredient in _expand_all_ingredients(
            scaled_recipe.all_ingredients, recipes, visited=frozenset()
        ):
            if ingredient.byproduct:
                continue

            key = (
                ingredient.name,
                tuple(sorted(ingredient.require_tags)),
            )

            raw_qty, raw_unit = _apply_equivalent(ingredient)
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

            ingredient_totals[key]["tags"].update(ingredient.require_tags)

    shopping_items: list[ShoppingItem] = []
    for (name, tag_tuple), details in ingredient_totals.items():
        display_qty, display_unit = (
            display_normalizer or normalize_volume_for_grocery
        )(details["quantity"], details["unit"])

        shopping_items.append(
            ShoppingItem(
                name=name,
                total_quantity=round(display_qty, 2),
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
    items: list[ShoppingItem],
    *,
    kitchen_items: frozenset[str] | None = None,
    category_rules: list | None = None,
) -> list[IngredientGroup]:
    """Group shopping items by ingredient category.

    Args:
        items: Shopping items to group.
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

    groups: dict[str, list[ShoppingItem]] = defaultdict(list)

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


def normalize_volume_for_grocery(
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
    """Shopping item enriched with pricing information."""

    item: ShoppingItem
    price_per_unit: Decimal | None
    """Price per display unit (e.g. per 100g, per each)."""

    price_unit: str
    """Display unit for the price (e.g. ``'100g'``, ``'each'``)."""

    total_cost: Decimal | None
    """Total cost for this shopping item."""

    store: str | None
    """Store with the best / most recent price."""

    purchase_date: DateType | None
    """Date of the grocery purchase used for pricing."""

    missing_price: bool
    """``True`` if no grocery data was found for this item."""


def _default_price_display(
    item: ShoppingItem, grocery: PurchasedItem
) -> tuple[Decimal, str]:
    """Return ``(price_per_unit, display_unit)`` for a shopping item.

    Per-100g for metric weight units, per-100ml for metric volume units,
    per-package-price otherwise.
    """
    if item.unit.lower() in {"g", "gram", "grams", "ml", "milliliter", "milliliters"}:
        try:
            groc_qty_in_item_unit = (
                parse_quantity(grocery.quantity, grocery.unit).to(item.unit).magnitude
            )
            price_per_base = grocery.price / Decimal(str(groc_qty_in_item_unit))
            display_unit = (
                "100g" if item.unit.lower() in {"g", "gram", "grams"} else "100ml"
            )
            return (price_per_base * Decimal("100"), display_unit)
        except Exception:
            pass
    return (grocery.price / Decimal(str(grocery.quantity)), item.unit)


def add_costs_to_shopping_list(
    shopping_list: ShoppingList,
    groceries: Iterable[PurchasedItem],
    *,
    density_data: dict | None = None,
    matcher: ItemMatcher | None = None,
    picker: ItemPicker | None = None,
    price_display_fn: Callable[[ShoppingItem, PurchasedItem], tuple[Decimal, str]]
    | None = None,
) -> list[ShoppingItemWithCost]:
    """Enrich each shopping item with cost information.

    For each item:
    1. Convert to an ingredient for matching.
    2. Find matching grocery items via *matcher*.
    3. Select one grocery via *picker* (default: :func:`compatible_unit_recent_picker`).
    4. Calculate cost using unit conversion.
    5. Compute a readable price per display unit via *price_display_fn*.

    Args:
        shopping_list: Generated shopping list.
        groceries: Available grocery price data.
        density_data: Optional density data for unit conversion.
        matcher: Optional custom matching function.  Defaults to
            :func:`find_matching_purchases`.
        picker: Optional custom picking function.  Defaults to
            :func:`compatible_unit_recent_picker`.  Use :func:`chain`
            to compose.
        price_display_fn: Optional callback
            ``(item, grocery) -> (price_per_unit, display_unit)``
            for customizing unit price display.  Defaults to per-100g for
            metric weight units, per-100ml for metric volume units,
            per-package otherwise.

    Returns:
        List of ``ShoppingItemWithCost``, one per shopping item.
    """
    density_data = density_data or {}
    _match = matcher or find_matching_purchases
    items_with_costs: list[ShoppingItemWithCost] = []

    for shopping_item in shopping_list.all_items:
        ingredient = BaseIngredient(
            name=shopping_item.name,
            quantity=shopping_item.total_quantity,
            unit=shopping_item.unit,
            require_tags=shopping_item.tags,
        )

        try:
            matching = _match(ingredient, groceries)
            latest_grocery: PurchasedItem | None = None

            if matching:
                if picker is not None:
                    latest_grocery = picker(ingredient, matching)
                else:
                    latest_grocery = compatible_unit_recent_picker(ingredient, matching)

            if latest_grocery is None:
                items_with_costs.append(
                    ShoppingItemWithCost(
                        item=shopping_item,
                        price_per_unit=None,
                        price_unit=shopping_item.unit,
                        total_cost=None,
                        store=None,
                        purchase_date=None,
                        missing_price=True,
                    )
                )
                continue

            cost = calculate_ingredient_cost(
                ingredient, latest_grocery, density_data=density_data
            )

            price_per_unit, display_unit = (price_display_fn or _default_price_display)(
                shopping_item, latest_grocery
            )

            items_with_costs.append(
                ShoppingItemWithCost(
                    item=shopping_item,
                    price_per_unit=price_per_unit,
                    price_unit=display_unit,
                    total_cost=cost,
                    store=latest_grocery.store,
                    purchase_date=getattr(latest_grocery, "purchased_date", None),
                    missing_price=False,
                )
            )

        except Exception:
            items_with_costs.append(
                ShoppingItemWithCost(
                    item=shopping_item,
                    price_per_unit=None,
                    price_unit=shopping_item.unit,
                    total_cost=None,
                    store=None,
                    purchase_date=None,
                    missing_price=True,
                )
            )

    return items_with_costs


# ---------------------------------------------------------------------------
# Standalone item costing (supplies, tools, etc.)
# ---------------------------------------------------------------------------


def cost_items(
    items: list[BaseIngredient],
    purchases: Iterable[PurchasedItem],
    *,
    density_data: dict | None = None,
    matcher: ItemMatcher | None = None,
    picker: ItemPicker | None = None,
) -> list[ShoppingItemWithCost]:
    """Cost arbitrary items — food, supplies, tools, etc.

    Reuses the same matching, picking, and costing pipeline as
    :func:`add_costs_to_shopping_list`, but works on a flat list of
    ``BaseIngredient`` instead of a ``ShoppingList``.

    Args:
        items: Items to cost (recipe ingredients, supplies, etc.).
        purchases: Available purchase price data.
        density_data: Optional density data for unit conversion.
        matcher: Optional custom matching function.
        picker: Optional custom picking function.

    Returns:
        List of ``ShoppingItemWithCost``, one per input item.
    """
    density_data = density_data or {}
    _match = matcher or find_matching_purchases
    result: list[ShoppingItemWithCost] = []

    for item in items:
        try:
            matching = _match(item, purchases)
            latest: PurchasedItem | None = None

            if matching:
                if picker is not None:
                    latest = picker(item, matching)
                else:
                    latest = compatible_unit_recent_picker(item, matching)

            if latest is None:
                result.append(
                    ShoppingItemWithCost(
                        item=ShoppingItem(
                            name=item.name,
                            total_quantity=item.quantity,
                            unit=item.unit,
                            tags=item.require_tags,
                        ),
                        price_per_unit=None,
                        price_unit=item.unit,
                        total_cost=None,
                        store=None,
                        purchase_date=None,
                        missing_price=True,
                    )
                )
                continue

            cost = calculate_ingredient_cost(item, latest, density_data=density_data)

            # Price per display unit
            if item.unit.lower() in {
                "g",
                "gram",
                "grams",
                "ml",
                "milliliter",
                "milliliters",
            }:
                try:
                    qty_in_item_units = (
                        parse_quantity(latest.quantity, latest.unit)
                        .to(item.unit)
                        .magnitude
                    )
                    price_per_base = latest.price / Decimal(str(qty_in_item_units))
                    ppu = price_per_base * Decimal("100")
                    du = (
                        "100g"
                        if item.unit.lower() in {"g", "gram", "grams"}
                        else "100ml"
                    )
                except Exception:
                    ppu = latest.price / Decimal(str(latest.quantity))
                    du = latest.unit
            else:
                ppu = latest.price / Decimal(str(latest.quantity))
                du = item.unit

            result.append(
                ShoppingItemWithCost(
                    item=ShoppingItem(
                        name=item.name,
                        total_quantity=item.quantity,
                        unit=item.unit,
                        tags=item.require_tags,
                    ),
                    price_per_unit=ppu,
                    price_unit=du,
                    total_cost=cost,
                    store=latest.store,
                    purchase_date=getattr(latest, "purchased_date", None),
                    missing_price=False,
                )
            )

        except Exception:
            result.append(
                ShoppingItemWithCost(
                    item=ShoppingItem(
                        name=item.name,
                        total_quantity=item.quantity,
                        unit=item.unit,
                        tags=item.require_tags,
                    ),
                    price_per_unit=None,
                    price_unit=item.unit,
                    total_cost=None,
                    store=None,
                    purchase_date=None,
                    missing_price=True,
                )
            )

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
    recipes: Mapping[str, BaseRecipe],
    groceries: Iterable[PurchasedItem],
    *,
    density_data: dict | None = None,
    matcher: ItemMatcher | None = None,
    picker: ItemPicker | None = None,
    date: DateType | None = None,
) -> MenuAnalysis:
    """Analyze the ingredient costs for an arbitrary menu.

    Builds a virtual production run from *production*, generates the
    aggregated shopping list, then enriches every line with the latest
    grocery price.

    Args:
        production: List of ``ProductionItem`` (recipe name + quantity).
        recipes: Mapping of recipe name → ``BaseRecipe``.
        groceries: Available grocery price data.
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

    shopping_list = generate_shopping_list(virtual_session, recipes)
    items_with_cost = add_costs_to_shopping_list(
        shopping_list,
        groceries,
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

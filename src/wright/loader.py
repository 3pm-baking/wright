"""YAML convenience loaders — optional helpers for file-based workflows.

These are thin wrappers around PyYAML.  They are NOT required — the core
library works with any data source.  Use these only if your recipes
and groceries live in YAML files.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

from wright.errors import PurchaseLoadError, RecipeLoadError
from wright.models import (
    BaseIngredient,
    BaseRecipe,
    NutritionInfo,
    RecipeComponent,
    SimplePurchase,
)
from wright.supply import SupplyItem


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


def load_yaml_file(path: Path) -> dict:
    """Load a YAML file and return its contents as a dictionary.

    Args:
        path: Path to the YAML file.

    Returns:
        Parsed YAML content.

    Raises:
        FileNotFoundError: If the file does not exist.
        yaml.YAMLError: If the YAML is invalid.
    """
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Recipe loading
# ---------------------------------------------------------------------------


def load_base_recipe(path: Path) -> BaseRecipe:
    """Load a ``BaseRecipe`` from a YAML file.

    Expects the standard recipe YAML format with ``components``,
    ``prep_time``, ``cook_time``, and optional ``servings``.

    Args:
        path: Path to a recipe YAML file.

    Returns:
        Parsed ``BaseRecipe``.

    Raises:
        RecipeLoadError: If the file cannot be loaded or parsed.
    """
    try:
        data = load_yaml_file(path)
    except FileNotFoundError:
        raise RecipeLoadError(str(path), "File not found")
    except yaml.YAMLError as e:
        raise RecipeLoadError(str(path), f"Invalid YAML: {e}")

    try:
        recipe = BaseRecipe(
            name=data["name"],
            components=[
                RecipeComponent(
                    name=comp["name"],
                    ingredients=[
                        BaseIngredient(
                            name=ing["name"],
                            quantity=ing["quantity"],
                            unit=ing["unit"],
                            require_tags=ing.get("require_tags", []),
                            equivalent_quantity=ing.get("equivalent_quantity"),
                            equivalent_unit=ing.get("equivalent_unit"),
                            byproduct=ing.get("byproduct", False),
                            product_ref=ing.get("product_ref"),
                        )
                        for ing in comp.get("ingredients", [])
                    ],
                )
                for comp in data.get("components", [])
            ],
            instructions=data.get("instructions", []),
            prep_time=data["prep_time"],
            cook_time=data["cook_time"],
            servings=data.get("servings"),
            net_weight_grams=data.get("net_weight_grams"),
            description=data.get("description"),
            tags=data.get("tags", []),
        )
        return recipe

    except KeyError as e:
        raise RecipeLoadError(str(path), f"Missing required field: {e}")
    except (TypeError, ValueError) as e:
        raise RecipeLoadError(str(path), f"Invalid data: {e}")


def list_recipe_files(directory: Path | str) -> list[Path]:
    """List all recipe YAML files in a directory.

    Args:
        directory: Path to a directory containing recipe files.

    Returns:
        Sorted list of ``Path`` objects.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    files = list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))
    return sorted(files)


# ---------------------------------------------------------------------------
# Grocery loading
# ---------------------------------------------------------------------------


def load_purchases(path: Path) -> list[SimplePurchase]:
    """Load grocery items from a YAML file.

    Expects a top-level ``purchases`` key with a list of purchase entries.

    Args:
        path: Path to a grocery YAML file.

    Returns:
        List of ``SimplePurchase`` objects.

    Raises:
        PurchaseLoadError: If the file cannot be loaded or parsed.
    """
    try:
        data = load_yaml_file(path)
    except FileNotFoundError:
        raise PurchaseLoadError(str(path), "File not found")
    except yaml.YAMLError as e:
        raise PurchaseLoadError(str(path), f"Invalid YAML: {e}")

    purchases = data.get("purchases", [])
    if not isinstance(purchases, list):
        raise PurchaseLoadError(str(path), "Expected a 'purchases' list")

    items: list[SimplePurchase] = []

    for entry in purchases:
        try:
            item = SimplePurchase(
                name=entry["name"],
                brand=entry.get("brand"),
                tags=entry.get("tags", ""),
                quantity=float(entry["quantity"]),
                unit=entry["unit"],
                price=_parse_price(entry["price"]),
                store=entry.get("store"),
                purchased_date=_parse_date(entry.get("purchased_date")),
            )
            items.append(item)
        except KeyError as e:
            raise PurchaseLoadError(
                str(path), f"Missing required field in purchase: {e}"
            )
        except (TypeError, ValueError) as e:
            raise PurchaseLoadError(str(path), f"Invalid purchase data: {e}")

    return items


def load_density_data(path: Path) -> dict:
    """Load density conversion data from a YAML file.

    The file should have optional ``liquids`` and ``volume_weights``
    sections.

    Args:
        path: Path to a density YAML file.

    Returns:
        Dictionary suitable for passing to ``calculate_recipe_cost()``
        and other costing functions.
    """
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_price(price_str: str | None) -> Decimal:
    """Parse a price string like '$5.50' into a Decimal."""
    if not price_str:
        raise ValueError("Price is required")
    cleaned = str(price_str).strip().lstrip("$")
    if not cleaned:
        raise ValueError("Price string is empty")
    return Decimal(cleaned)


def _parse_date(date_str: str | None) -> date | None:
    """Parse an ISO date string, returning None for empty/missing."""
    if not date_str:
        return None
    return date.fromisoformat(str(date_str))


def load_nutrition_registry(path: Path) -> dict[str, NutritionInfo]:
    """Load a nutrition registry from a YAML file.

    Expects a top-level ``nutrients`` key with a list of entries, each
    containing ``ingredient`` (name), ``nutrition`` (block), and optional
    ``source``.

    The returned dict maps ingredient names → ``NutritionInfo`` for use
    with ``calculate_recipe_macros()``.

    Args:
        path: Path to a nutrition registry YAML file.

    Returns:
        Dict of ``{ingredient_name: NutritionInfo}``.

    Raises:
        PurchaseLoadError: If the file cannot be loaded or parsed.
    """
    if not path.exists():
        return {}

    try:
        data = load_yaml_file(path)
    except yaml.YAMLError as e:
        raise PurchaseLoadError(str(path), f"Invalid YAML: {e}")

    records = data.get("nutrients", [])
    if not isinstance(records, list):
        return {}

    registry: dict[str, NutritionInfo] = {}
    for entry in records:
        try:
            name = entry["ingredient"]
            nutrition_data = entry["nutrition"]
            nutrition = NutritionInfo(
                protein_g=nutrition_data.get("protein_g", 0),
                carbs_g=nutrition_data.get("carbs_g", 0),
                fat_g=nutrition_data.get("fat_g", 0),
                fiber_g=nutrition_data.get("fiber_g", 0),
                kcal=nutrition_data.get("kcal"),
            )
            registry[name] = nutrition
        except (KeyError, TypeError, ValueError):
            continue

    return registry


def load_supplies(path: Path) -> dict[str, SupplyItem]:
    """Load pantry stock from a YAML file.

    Expects a top-level ``pantry`` key with a list of entries, each
    containing ``name``, ``quantity``, and ``unit``.

    Example:

    .. code-block:: yaml

        pantry:
          - name: Wheat flour
            quantity: 25
            unit: lb
          - name: Sugar
            quantity: 5
            unit: kg

    Args:
        path: Path to the pantry YAML file.

    Returns:
        ``dict[str, SupplyItem]`` keyed by ingredient name.
    """
    if not path.exists():
        return {}

    data = load_yaml_file(path)

    items_list = data.get("pantry", data.get("items", []))

    if not isinstance(items_list, list):
        return {}

    supply: dict[str, SupplyItem] = {}
    for entry in items_list:
        try:
            item = SupplyItem(
                name=entry["name"],
                quantity=float(entry["quantity"]),
                unit=entry["unit"],
            )
            supply[item.name] = item
        except (KeyError, TypeError, ValueError):
            continue

    return supply

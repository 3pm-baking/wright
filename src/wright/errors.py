"""Custom exceptions for the wright package."""

from __future__ import annotations


class RecipeCoreError(Exception):
    """Base exception for all wright errors."""


class IngredientNotFoundError(RecipeCoreError):
    """Raised when an ingredient cannot be matched to any grocery item."""

    def __init__(self, ingredient_name: str, require_tags: list[str] | None = None):
        self.ingredient_name = ingredient_name
        self.require_tags = require_tags or []

        tags_msg = ""
        if self.require_tags:
            tags_msg = f" with tags {self.require_tags}"

        message = f"No grocery item found for '{ingredient_name}'{tags_msg}."
        super().__init__(message)


class RecipeLoadError(RecipeCoreError):
    """Raised when a recipe file cannot be loaded or parsed."""

    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        message = f"Failed to load recipe from '{path}': {reason}"
        super().__init__(message)


class PurchaseLoadError(RecipeCoreError):
    """Raised when a grocery file cannot be loaded or parsed."""

    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        message = f"Failed to load grocery data from '{path}': {reason}"
        super().__init__(message)


class UnitConversionError(RecipeCoreError):
    """Raised when unit conversion between ingredient and grocery units fails."""

    def __init__(self, from_unit: str, to_unit: str, ingredient_name: str):
        self.from_unit = from_unit
        self.to_unit = to_unit
        self.ingredient_name = ingredient_name
        message = (
            f"Cannot convert '{from_unit}' to '{to_unit}' for ingredient "
            f"'{ingredient_name}'. Units are incompatible."
        )
        super().__init__(message)


class RecipeCostErrors(RecipeCoreError):
    """Raised when one or more ingredients in a recipe could not be costed.

    Collects all ingredient errors instead of stopping at the first failure,
    so the user can see everything that needs to be fixed in one run.
    """

    def __init__(
        self,
        errors: list[
            IngredientNotFoundError
            | UnitConversionError
            | RecipeCostErrors
            | ValueError
        ],
    ):
        self.errors = errors
        count = len(errors)
        header = f"{count} ingredient(s) could not be resolved:"
        lines = [f"  - {e}" for e in errors]
        super().__init__("\n".join([header, *lines]))

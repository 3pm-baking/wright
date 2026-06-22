"""Production run models for batch planning.

Data-source agnostic — assemblies are referenced by name, not loaded here.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date as DateType

from pydantic import BaseModel, Field, model_validator


class ProductionItem(BaseModel):
    """An assembly (or recipe) to be produced in a specific quantity.

    Uses ``assembly=`` as the canonical constructor argument.
    ``recipe=`` is accepted for backward compatibility (mapped to ``assembly``).
    """

    assembly: str = Field(
        ...,
        description=(
            "Assembly name (matches keys in the assemblies mapping). "
            "Also called 'recipe' in food domains."
        ),
    )
    quantity: float = Field(
        ...,
        gt=0,
        description=(
            "Number of batches to make. Supports fractional "
            "quantities (e.g., 0.5 for a half batch)."
        ),
    )

    @property
    def recipe(self) -> str:
        """Backward-compatible alias for :attr:`assembly`."""
        return self.assembly

    @model_validator(mode="before")
    @classmethod
    def _accept_recipe_key(cls, data: object) -> object:
        """Accept ``recipe=`` as an alias for ``assembly=`` in the constructor."""
        if isinstance(data, dict) and "recipe" in data and "assembly" not in data:
            data = {**data, "assembly": data.pop("recipe")}  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
        return data

    def __mul__(self, factor: float) -> ProductionItem:
        if not isinstance(factor, int | float):
            return NotImplemented
        return ProductionItem(assembly=self.assembly, quantity=self.quantity * factor)

    def __rmul__(self, factor: float) -> ProductionItem:
        return self * factor


class ProductionRun(BaseModel):
    """A production run producing multiple assemblies for one or more target dates."""

    date: DateType = Field(..., description="Production date")
    production: list[ProductionItem] = Field(
        ..., description="What to produce and in what quantities"
    )
    target_dates: list[DateType] = Field(..., description="Dates this run supplies")

    def __add__(self, other: ProductionRun) -> ProductionRun:
        """Merge two production runs.

        Production items are combined by assembly name (summing quantities).
        Target dates are unioned and deduplicated. The earliest date is kept.
        """
        merged: dict[str, float] = {}
        for item in self.production:
            merged[item.assembly] = merged.get(item.assembly, 0) + item.quantity
        for item in other.production:
            merged[item.assembly] = merged.get(item.assembly, 0) + item.quantity

        return ProductionRun(
            date=min(self.date, other.date),
            production=[
                ProductionItem(assembly=n, quantity=q) for n, q in merged.items()
            ],
            target_dates=sorted(set(self.target_dates) | set(other.target_dates)),
        )


# Default German umlaut transliterations (ä → ae, ö → oe, ü → ue, ß → ss).
_DEFAULT_TRANSLITERATIONS: dict[str, str] = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
}


def convert_name_to_filename(
    name: str,
    *,
    transliterations: dict[str, str] | None = _DEFAULT_TRANSLITERATIONS,
) -> str:
    """Convert an assembly name to kebab-case filename.

    Accented characters are decomposed via Unicode NFKD normalization
    (``é → e``, ``ñ → n``).  German umlauts are transliterated to their
    digraph equivalents (``ä → ae``, ``ö → oe``, ``ü → ue``, ``ß → ss``)
    by default.  Pass ``transliterations={}`` to skip, or provide your own
    mappings for other scripts.

    Examples:
        ``'Chocolate Chip Cookie'`` → ``'chocolate-chip-cookie'``
        ``'Käsekuchen'`` → ``'kaesekuchen'``

    Args:
        name: The assembly name.
        transliterations: Optional mapping of character → replacement
            string.  Applied before NFKD normalization.  Defaults to
            German umlaut digraphs.

    Returns:
        Kebab-case filename without extension.
    """
    filename = name.lower()
    if transliterations:
        for char, replacement in transliterations.items():
            filename = filename.replace(char, replacement)
    filename = (
        unicodedata
        .normalize("NFKD", filename)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    filename = re.sub(r"['']", "", filename)
    filename = re.sub(r"[^a-z0-9\s-]", "", filename)
    filename = re.sub(r"\s+", "-", filename)
    filename = re.sub(r"-+", "-", filename)
    filename = filename.strip("-")
    return filename

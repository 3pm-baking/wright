"""Production run models for batch planning.

Data-source agnostic — recipes are referenced by name, not loaded here.
"""

from __future__ import annotations

import re
from datetime import date as DateType

from pydantic import BaseModel, Field


class ProductionItem(BaseModel):
    """A recipe to be produced in a specific quantity."""

    recipe: str = Field(
        ..., description="Recipe name (matches keys in the recipes mapping)"
    )
    quantity: float = Field(
        ...,
        gt=0,
        description=(
            "Number of recipe batches to make. Supports fractional "
            "quantities (e.g., 0.5 for a half batch)."
        ),
    )


class ProductionRun(BaseModel):
    """A production run producing multiple recipes for one or more target dates."""

    date: DateType = Field(..., description="Production date")
    production: list[ProductionItem] = Field(
        ..., description="What to produce and in what quantities"
    )
    target_dates: list[DateType] = Field(..., description="Dates this run supplies")


def combine_production_runs(runs: list[ProductionRun]) -> ProductionRun:
    """Merge multiple production runs into one.

    Combines production items by recipe name (summing quantities) and
    unions target dates (deduplicated).  Uses the earliest date from
    all runs as the combined date.

    Args:
        runs: List of ``ProductionRun`` to combine.

    Returns:
        A single ``ProductionRun`` covering all input runs.

    Raises:
        ValueError: If *runs* is empty.
    """
    if not runs:
        raise ValueError("Cannot combine an empty list of runs")

    # Sum production quantities by recipe name
    merged_production: dict[str, float] = {}
    for run in runs:
        for item in run.production:
            merged_production[item.recipe] = (
                merged_production.get(item.recipe, 0) + item.quantity
            )

    production = [
        ProductionItem(recipe=name, quantity=qty)
        for name, qty in merged_production.items()
    ]

    # Union target dates and pick earliest date
    all_targets: set[DateType] = set()
    earliest = runs[0].date
    for run in runs:
        all_targets.update(run.target_dates)
        if run.date < earliest:
            earliest = run.date

    return ProductionRun(
        date=earliest,
        production=production,
        target_dates=sorted(all_targets),
    )


def recipe_name_to_filename(recipe_name: str) -> str:
    """Convert recipe name to kebab-case filename.

    Examples:
        ``'German Cheese Cake'`` → ``'german-cheese-cake'``
        ``'Russischer Zupfkuchen'`` → ``'russischer-zupfkuchen'``

    Args:
        recipe_name: The recipe name.

    Returns:
        Kebab-case filename without extension.
    """
    filename = recipe_name.lower()
    filename = re.sub(r"['']", "", filename)
    filename = re.sub(r"[^a-z0-9\s-]", "", filename)
    filename = re.sub(r"\s+", "-", filename)
    filename = re.sub(r"-+", "-", filename)
    filename = filename.strip("-")
    return filename

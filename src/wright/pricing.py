"""Pricing calculations — pure functions, no I/O."""

from __future__ import annotations

from decimal import Decimal

from wright.models import PriceRange, RecipeCost


def margin_price(cost: Decimal, margin: Decimal | float) -> Decimal:
    """Calculate a sale price from cost using a target margin.

    Uses the standard margin formula:
        price = cost / (1 - margin)

    For example, a 67% margin on a $2.00 cost gives:
        2.00 / (1 - 0.67) = $6.06

    Args:
        cost: The ingredient (or total) cost.
        margin: Target profit margin as a ``Decimal`` or ``float``
            (0 < margin < 1).

    Returns:
        Suggested sale price.

    Raises:
        ValueError: If margin is not strictly between 0 and 1.
    """
    m = Decimal(str(margin))
    if not (Decimal("0") < m < Decimal("1")):
        raise ValueError(f"Margin must be strictly between 0 and 1, got {margin}")
    return cost / (Decimal("1") - m)


def multiplier_price(cost: Decimal, multiplier: float) -> Decimal:
    """Calculate a sale price from cost using a simple multiplier.

    For example, 3× cost on a $2.00 cost gives $6.00.

    Args:
        cost: The ingredient (or total) cost.
        multiplier: Price multiplier (must be > 0).

    Returns:
        Suggested sale price.

    Raises:
        ValueError: If multiplier is not positive.
    """
    if multiplier <= 0:
        raise ValueError(f"Multiplier must be positive, got {multiplier}")
    return cost * Decimal(str(multiplier))


def per_serving_price(
    recipe_cost: RecipeCost,
    servings: int,
) -> PriceRange:
    """Calculate the per-serving price range for a given number of servings.

    Args:
        recipe_cost: A fully calculated ``RecipeCost``.
        servings: The number of servings to spread the cost across.

    Returns:
        ``PriceRange`` with min and max cost per serving.

    Raises:
        ValueError: If servings is less than 1.
    """
    if servings < 1:
        raise ValueError(f"Servings must be at least 1, got {servings}")

    s = Decimal(str(servings))
    return PriceRange(
        min_price=recipe_cost.total_cost_range.min_price / s,
        max_price=recipe_cost.total_cost_range.max_price / s,
    )

"""Supply tracking — Stock class for pantry/shopping list stock management."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

from pydantic import BaseModel, Field

from wright.costing import convert_with_density
from wright.units import are_compatible, parse_quantity

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SupplyItem(BaseModel):
    """A named item with a quantity — used for stock, needs, and deficits."""

    name: str = Field(..., description="Item name (exact match)")
    quantity: float = Field(..., ge=0, description="Amount on hand or needed")
    unit: str = Field(..., description="Unit of measurement")
    tags: list[str] = Field(
        default_factory=list, description="Required tags for matching"
    )

    def to_qty(self):
        """Return this item as a pint Quantity."""
        return parse_quantity(self.quantity, self.unit)


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------


class Stock:
    """Immutable named-quantity collection (pantry, inventory, or consolidated needs).

    All methods return new instances; the original is never mutated.

    >>> stock = Stock()
    >>> stock = stock.add([SupplyItem(name="Flour", quantity=2000, unit="g")])
    >>> stock, deficit = stock.use([SupplyItem(name="Flour", quantity=900, unit="g")])
    >>> deficit
    []
    """

    def __init__(self, items: Iterable[SupplyItem] = ()):
        self._items: dict[str, SupplyItem] = {}
        for item in items:
            existing = self._items.get(item.name)
            if existing is None:
                self._items[item.name] = item.model_copy(deep=True)
            else:
                self._items[item.name] = _sum_quantities(existing, item)

    # -- mutating operations (return new Stock) --------------------------------

    def add(self, items: Iterable[SupplyItem]) -> Stock:
        """Return a new ``Stock`` with *items* merged in.

        Same-name entries have their quantities summed (with unit conversion).
        """
        new = Stock()
        new._items = {
            name: item.model_copy(deep=True) for name, item in self._items.items()
        }
        for item in items:
            existing = new._items.get(item.name)
            if existing is None:
                new._items[item.name] = item.model_copy(deep=True)
            else:
                new._items[item.name] = _sum_quantities(existing, item)
        return new

    def use(
        self,
        needed: Iterable[SupplyItem],
        *,
        density_data: dict | None = None,
    ) -> tuple[Stock, list[SupplyItem]]:
        """Deduct *needed* from stock where possible.

        Returns ``(reduced_stock, deficit)`` where *deficit* contains only
        items with a remaining shortfall (empty if everything was covered).
        The original stock is not modified.
        """
        new_items = {
            name: item.model_copy(deep=True) for name, item in self._items.items()
        }
        deficit: list[SupplyItem] = []

        for item in needed:
            stock = new_items.get(item.name)
            if stock is None:
                deficit.append(item)
                continue

            d = _use_item(item, stock, new_items, density_data)
            if d is not None:
                deficit.append(d)

        new = Stock()
        new._items = new_items
        return new, deficit

    def remove(self, items: Iterable[SupplyItem]) -> Stock:
        """Return a new ``Stock`` with *items* unconditionally removed.

        Quantities are floored at 0; zero-quantity entries are dropped.
        Unknown item names are silently ignored.
        """
        new = Stock()
        new._items = {
            name: item.model_copy(deep=True) for name, item in self._items.items()
        }
        for item in items:
            existing = new._items.get(item.name)
            if existing is None:
                continue
            remaining = _subtract_quantity(existing, item)
            if remaining.quantity == 0:
                del new._items[item.name]
            else:
                new._items[item.name] = remaining
        return new

    # -- I/O ----------------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: str | Path) -> Stock:
        """Load pantry stock from a YAML file.

        Expects a top-level ``pantry`` key with a list of entries, each
        containing ``name``, ``quantity``, and ``unit``:

        .. code-block:: yaml

            pantry:
              - name: Wheat flour
                quantity: 25
                unit: lb
              - name: Sugar
                quantity: 5
                unit: kg
        """
        from wright.loader import load_yaml_file

        path = Path(path)
        if not path.exists():
            return cls()

        data = load_yaml_file(path)
        items_list = data.get("pantry", data.get("items", []))
        if not isinstance(items_list, list):
            return cls()

        items: list[SupplyItem] = []
        for entry in items_list:
            try:
                items.append(
                    SupplyItem(
                        name=entry["name"],
                        quantity=float(entry["quantity"]),
                        unit=entry["unit"],
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

        return cls(items)

    def to_yaml(self, path: str | Path) -> None:
        """Write stock to a YAML file under a ``pantry`` key."""
        import yaml

        data = {
            "pantry": [
                {"name": item.name, "quantity": item.quantity, "unit": item.unit}
                for item in self._items.values()
            ]
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(yaml.dump(data, default_flow_style=False))

    # -- dict-like read access ----------------------------------------------

    def __getitem__(self, name: str) -> SupplyItem:
        return self._items[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, name: str) -> bool:
        return name in self._items

    def __bool__(self) -> bool:
        return bool(self._items)

    def items(self) -> Iterator[tuple[str, SupplyItem]]:
        """Iterate over ``(name, item)`` pairs in the stock."""
        return iter(self._items.items())

    def values(self) -> Iterator[SupplyItem]:
        """Iterate over item values in the stock."""
        return iter(self._items.values())

    def __repr__(self) -> str:
        items = ", ".join(
            f"{v.name}={v.quantity}{v.unit}" for v in self._items.values()
        )
        return f"Stock({{{items}}})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Stock):
            return NotImplemented
        return self._items == other._items


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _use_item(
    needed: SupplyItem,
    stock: SupplyItem,
    items_dict: dict[str, SupplyItem],
    density_data: dict | None = None,
) -> SupplyItem | None:
    """Deduct *needed* from *stock*, mutate *items_dict*, return deficit or None."""
    density_data = density_data or {}

    # -- same unit ----------------------------------------------------------
    if needed.unit.lower() == stock.unit.lower():
        if stock.quantity >= needed.quantity:
            _update_stock(items_dict, stock, needed.quantity, stock.unit)
            return None
        deficit_qty = round(needed.quantity - stock.quantity, 4)
        _remove_stock(items_dict, needed.name)
        return SupplyItem(
            name=needed.name,
            quantity=deficit_qty,
            unit=needed.unit,
            tags=needed.tags,
        )

    # -- pint-compatible ----------------------------------------------------
    if are_compatible(stock.unit, needed.unit):
        try:
            stock_in_needed = float(
                parse_quantity(stock.quantity, stock.unit).to(needed.unit).magnitude
            )
            if stock_in_needed >= needed.quantity:
                consumed_in_stock = float(
                    parse_quantity(needed.quantity, needed.unit)
                    .to(stock.unit)
                    .magnitude
                )
                _update_stock(
                    items_dict, stock, round(consumed_in_stock, 4), stock.unit
                )
                return None
            deficit_qty = round(needed.quantity - stock_in_needed, 4)
            _remove_stock(items_dict, needed.name)
            return SupplyItem(
                name=needed.name,
                quantity=deficit_qty,
                unit=needed.unit,
                tags=needed.tags,
            )
        except Exception:
            pass

    # -- density-based ------------------------------------------------------
    converted = convert_with_density(
        needed.name, stock.quantity, stock.unit, needed.unit, density_data
    )
    if converted is not None:
        if converted >= needed.quantity:
            ratio = stock.quantity / converted if converted != 0 else 1
            consumed_in_stock = round(needed.quantity * ratio, 4)
            _update_stock(items_dict, stock, consumed_in_stock, stock.unit)
            return None
        _remove_stock(items_dict, needed.name)
        deficit_qty = round(needed.quantity - converted, 4)
        return SupplyItem(
            name=needed.name,
            quantity=deficit_qty,
            unit=needed.unit,
            tags=needed.tags,
        )

    # -- can't convert ------------------------------------------------------
    return needed


def _update_stock(
    items_dict: dict[str, SupplyItem],
    stock: SupplyItem,
    consumed: float,
    stock_unit: str,
) -> None:
    """Subtract *consumed* from stock quantity in *items_dict*."""
    new_qty = round(stock.quantity - consumed, 4)
    if new_qty <= 0:
        del items_dict[stock.name]
    else:
        items_dict[stock.name] = SupplyItem(
            name=stock.name,
            quantity=new_qty,
            unit=stock_unit,
            tags=stock.tags,
        )


def _remove_stock(items_dict: dict[str, SupplyItem], name: str) -> None:
    """Remove an entry from the items dict."""
    items_dict.pop(name, None)


def _sum_quantities(existing: SupplyItem, addition: SupplyItem) -> SupplyItem:
    """Add *addition* quantity to *existing*, handling unit conversion."""
    if existing.unit.lower() == addition.unit.lower():
        return SupplyItem(
            name=existing.name,
            quantity=round(existing.quantity + addition.quantity, 4),
            unit=existing.unit,
            tags=existing.tags or addition.tags,
        )

    if are_compatible(addition.unit, existing.unit):
        try:
            addition_in_existing = float(
                parse_quantity(addition.quantity, addition.unit)
                .to(existing.unit)
                .magnitude
            )
            return SupplyItem(
                name=existing.name,
                quantity=round(existing.quantity + addition_in_existing, 4),
                unit=existing.unit,
                tags=existing.tags or addition.tags,
            )
        except Exception:
            pass

    return SupplyItem(
        name=existing.name,
        quantity=round(existing.quantity + addition.quantity, 4),
        unit=existing.unit,
        tags=existing.tags or addition.tags,
    )


def _subtract_quantity(existing: SupplyItem, deduction: SupplyItem) -> SupplyItem:
    """Subtract *deduction* from *existing*, flooring at 0."""
    if existing.unit.lower() == deduction.unit.lower():
        return SupplyItem(
            name=existing.name,
            quantity=max(0.0, round(existing.quantity - deduction.quantity, 4)),
            unit=existing.unit,
            tags=existing.tags,
        )

    if are_compatible(deduction.unit, existing.unit):
        try:
            ded_in_existing = float(
                parse_quantity(deduction.quantity, deduction.unit)
                .to(existing.unit)
                .magnitude
            )
            return SupplyItem(
                name=existing.name,
                quantity=max(0.0, round(existing.quantity - ded_in_existing, 4)),
                unit=existing.unit,
                tags=existing.tags,
            )
        except Exception:
            pass

    return SupplyItem(
        name=existing.name,
        quantity=max(0.0, round(existing.quantity - deduction.quantity, 4)),
        unit=existing.unit,
        tags=existing.tags,
    )

"""Tests for wright supply module."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from wright.supply import (
    SupplyItem,
    subtract_supply,
    supply_add,
    supply_deduct,
)


# ---------------------------------------------------------------------------
# SupplyItem
# ---------------------------------------------------------------------------


class TestSupplyItem:
    def test_create(self):
        item = SupplyItem(name="Flour", quantity=500, unit="g")
        assert item.name == "Flour"
        assert item.quantity == 500
        assert item.unit == "g"

    def test_negative_quantity_allowed(self):
        """Negative quantities are blocked by ge=0 validator."""
        with pytest.raises(ValueError):
            SupplyItem(name="Flour", quantity=-1, unit="g")

    def test_to_qty(self):
        item = SupplyItem(name="Flour", quantity=500, unit="g")
        qty = item.to_qty()
        assert qty.magnitude == 500
        assert str(qty.units) == "gram"


# ---------------------------------------------------------------------------
# subtract_supply
# ---------------------------------------------------------------------------


class TestSubtractSupply:
    def test_item_not_in_supply_passes_through(self):
        needed = [SupplyItem(name="Flour", quantity=500, unit="g")]
        supply: dict[str, SupplyItem] = {}
        result = subtract_supply(needed, supply)
        assert len(result) == 1
        assert result[0].quantity == 500

    def test_item_fully_covered_dropped(self):
        needed = [SupplyItem(name="Flour", quantity=500, unit="g")]
        supply = {"Flour": SupplyItem(name="Flour", quantity=1000, unit="g")}
        result = subtract_supply(needed, supply)
        assert len(result) == 0

    def test_item_partially_covered_returns_deficit(self):
        needed = [SupplyItem(name="Flour", quantity=500, unit="g")]
        supply = {"Flour": SupplyItem(name="Flour", quantity=300, unit="g")}
        result = subtract_supply(needed, supply)
        assert len(result) == 1
        assert result[0].quantity == 200
        assert result[0].unit == "g"

    def test_same_quantity_fully_covered(self):
        needed = [SupplyItem(name="Flour", quantity=500, unit="g")]
        supply = {"Flour": SupplyItem(name="Flour", quantity=500, unit="g")}
        result = subtract_supply(needed, supply)
        assert len(result) == 0

    def test_unit_conversion_oz_to_g(self):
        needed = [SupplyItem(name="Flour", quantity=500, unit="g")]
        supply = {"Flour": SupplyItem(name="Flour", quantity=16, unit="oz")}  # 453.6g
        result = subtract_supply(needed, supply)
        assert len(result) == 1
        assert result[0].unit == "g"
        assert result[0].quantity == pytest.approx(46.4, abs=0.1)

    def test_unit_conversion_lb_to_g(self):
        needed = [SupplyItem(name="Flour", quantity=1000, unit="g")]
        supply = {"Flour": SupplyItem(name="Flour", quantity=2, unit="lb")}  # ~907g
        result = subtract_supply(needed, supply)
        assert len(result) == 1
        assert result[0].unit == "g"
        assert result[0].quantity == pytest.approx(93, abs=5)

    def test_unit_conversion_fully_covered(self):
        needed = [SupplyItem(name="Sugar", quantity=500, unit="g")]
        supply = {"Sugar": SupplyItem(name="Sugar", quantity=2, unit="kg")}
        result = subtract_supply(needed, supply)
        assert len(result) == 0

    def test_incompatible_units_no_density_keeps_original(self):
        needed = [SupplyItem(name="Honey", quantity=2, unit="tbsp")]
        supply = {"Honey": SupplyItem(name="Honey", quantity=340, unit="g")}
        result = subtract_supply(needed, supply)
        assert len(result) == 1
        assert result[0].quantity == 2
        assert result[0].unit == "tbsp"

    def test_incompatible_units_with_density(self):
        density = {"volume_weights": {"Honey": {"tbsp": 21.0}}}
        needed = [SupplyItem(name="Honey", quantity=4, unit="tbsp")]
        supply = {
            "Honey": SupplyItem(name="Honey", quantity=21, unit="g")
        }  # 1 tbsp worth
        result = subtract_supply(needed, supply, density_data=density)
        assert len(result) == 1
        assert result[0].unit == "tbsp"
        assert result[0].quantity == pytest.approx(3.0, abs=0.1)

    def test_incompatible_with_density_fully_covered(self):
        density = {"volume_weights": {"Honey": {"tbsp": 21.0}}}
        needed = [SupplyItem(name="Honey", quantity=2, unit="tbsp")]
        supply = {"Honey": SupplyItem(name="Honey", quantity=100, unit="g")}
        result = subtract_supply(needed, supply, density_data=density)
        assert len(result) == 0

    def test_multiple_items(self):
        needed = [
            SupplyItem(name="Flour", quantity=500, unit="g"),
            SupplyItem(name="Sugar", quantity=200, unit="g"),
            SupplyItem(name="Eggs", quantity=6, unit="each"),
        ]
        supply = {
            "Flour": SupplyItem(name="Flour", quantity=1000, unit="g"),
            "Sugar": SupplyItem(name="Sugar", quantity=100, unit="g"),
        }
        result = subtract_supply(needed, supply)
        assert len(result) == 2
        names = {r.name for r in result}
        assert names == {"Sugar", "Eggs"}
        sugar = next(r for r in result if r.name == "Sugar")
        assert sugar.quantity == 100

    def test_ml_to_ml(self):
        needed = [SupplyItem(name="Milk", quantity=500, unit="ml")]
        supply = {"Milk": SupplyItem(name="Milk", quantity=1, unit="liter")}
        result = subtract_supply(needed, supply)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# supply_add
# ---------------------------------------------------------------------------


class TestSupplyAdd:
    def test_add_new_item(self):
        supply: dict[str, SupplyItem] = {}
        result = supply_add(supply, [SupplyItem(name="Flour", quantity=500, unit="g")])
        assert len(result) == 1
        assert result["Flour"].quantity == 500

    def test_add_to_existing_same_unit(self):
        supply = {"Flour": SupplyItem(name="Flour", quantity=500, unit="g")}
        result = supply_add(supply, [SupplyItem(name="Flour", quantity=300, unit="g")])
        assert result["Flour"].quantity == 800

    def test_add_to_existing_different_weight_unit(self):
        supply = {"Flour": SupplyItem(name="Flour", quantity=500, unit="g")}
        result = supply_add(supply, [SupplyItem(name="Flour", quantity=1, unit="kg")])
        assert result["Flour"].unit == "g"
        assert result["Flour"].quantity == 1500

    def test_original_supply_not_mutated(self):
        supply = {"Flour": SupplyItem(name="Flour", quantity=500, unit="g")}
        supply_add(supply, [SupplyItem(name="Flour", quantity=300, unit="g")])
        assert supply["Flour"].quantity == 500  # unchanged

    def test_multiple_items(self):
        supply: dict[str, SupplyItem] = {
            "Flour": SupplyItem(name="Flour", quantity=500, unit="g"),
        }
        result = supply_add(
            supply,
            [
                SupplyItem(name="Flour", quantity=300, unit="g"),
                SupplyItem(name="Sugar", quantity=200, unit="g"),
            ],
        )
        assert result["Flour"].quantity == 800
        assert result["Sugar"].quantity == 200


# ---------------------------------------------------------------------------
# supply_deduct
# ---------------------------------------------------------------------------


class TestSupplyDeduct:
    def test_deduct_existing(self):
        supply = {"Flour": SupplyItem(name="Flour", quantity=500, unit="g")}
        result = supply_deduct(
            supply, [SupplyItem(name="Flour", quantity=300, unit="g")]
        )
        assert result["Flour"].quantity == 200

    def test_deduct_to_zero_removes_entry(self):
        supply = {"Flour": SupplyItem(name="Flour", quantity=500, unit="g")}
        result = supply_deduct(
            supply, [SupplyItem(name="Flour", quantity=500, unit="g")]
        )
        assert "Flour" not in result

    def test_deduct_below_zero_floors(self):
        supply = {"Flour": SupplyItem(name="Flour", quantity=300, unit="g")}
        result = supply_deduct(
            supply, [SupplyItem(name="Flour", quantity=500, unit="g")]
        )
        assert "Flour" not in result

    def test_deduct_unknown_ignored(self):
        supply = {"Flour": SupplyItem(name="Flour", quantity=500, unit="g")}
        result = supply_deduct(
            supply, [SupplyItem(name="Ghost Flour", quantity=100, unit="g")]
        )
        assert len(result) == 1
        assert result["Flour"].quantity == 500

    def test_deduct_with_unit_conversion(self):
        supply = {"Flour": SupplyItem(name="Flour", quantity=1000, unit="g")}
        result = supply_deduct(
            supply, [SupplyItem(name="Flour", quantity=1, unit="kg")]
        )
        assert "Flour" not in result

    def test_original_supply_not_mutated(self):
        supply = {"Flour": SupplyItem(name="Flour", quantity=500, unit="g")}
        supply_deduct(supply, [SupplyItem(name="Flour", quantity=300, unit="g")])
        assert supply["Flour"].quantity == 500  # unchanged


# ---------------------------------------------------------------------------
# load_supplies (loader)
# ---------------------------------------------------------------------------


class TestLoadSupplies:
    def test_loads_from_yaml(self, tmp_path: Path):
        data = {
            "pantry": [
                {"name": "Flour", "quantity": 500, "unit": "g"},
                {"name": "Sugar", "quantity": 200, "unit": "g"},
            ]
        }
        path = tmp_path / "pantry.yaml"
        path.write_text(yaml.dump(data))

        from wright.loader import load_supplies

        result = load_supplies(path)
        assert len(result) == 2
        assert result["Flour"].quantity == 500
        assert result["Sugar"].quantity == 200

    def test_empty_file_returns_empty_dict(self, tmp_path: Path):
        path = tmp_path / "nonexistent.yaml"
        from wright.loader import load_supplies

        result = load_supplies(path)
        assert result == {}

    def test_missing_fields_skipped(self, tmp_path: Path):
        data = {
            "pantry": [
                {"name": "Flour", "quantity": 500, "unit": "g"},
                {"name": "Broken"},  # missing quantity and unit
            ]
        }
        path = tmp_path / "pantry.yaml"
        path.write_text(yaml.dump(data))

        from wright.loader import load_supplies

        result = load_supplies(path)
        assert len(result) == 1
        assert "Flour" in result

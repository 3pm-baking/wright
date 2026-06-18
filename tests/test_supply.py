"""Tests for wright supply module."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from wright.supply import Stock, SupplyItem

# ---------------------------------------------------------------------------
# SupplyItem
# ---------------------------------------------------------------------------


class TestSupplyItem:
    def test_create(self):
        item = SupplyItem(name="Flour", quantity=500, unit="g")
        assert item.name == "Flour"
        assert item.quantity == 500
        assert item.unit == "g"
        assert item.tags == []

    def test_with_tags(self):
        item = SupplyItem(name="Butter", quantity=200, unit="g", tags=["unsalted"])
        assert item.tags == ["unsalted"]

    def test_negative_quantity_blocked(self):
        with pytest.raises(ValueError):
            SupplyItem(name="Flour", quantity=-1, unit="g")

    def test_to_qty(self):
        item = SupplyItem(name="Flour", quantity=500, unit="g")
        qty = item.to_qty()
        assert qty.magnitude == 500
        assert str(qty.units) == "gram"


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------


class TestStockInit:
    def test_empty(self):
        s = Stock()
        assert len(s) == 0
        assert not s

    def test_from_items(self):
        s = Stock(
            [
                SupplyItem(name="Flour", quantity=500, unit="g"),
                SupplyItem(name="Sugar", quantity=200, unit="g"),
            ]
        )
        assert len(s) == 2
        assert s["Flour"].quantity == 500

    def test_merges_same_name(self):
        s = Stock(
            [
                SupplyItem(name="Flour", quantity=500, unit="g"),
                SupplyItem(name="Flour", quantity=300, unit="g"),
            ]
        )
        assert len(s) == 1
        assert s["Flour"].quantity == 800

    def test_dict_access(self):
        s = Stock([SupplyItem(name="Eggs", quantity=6, unit="each")])
        assert "Eggs" in s
        assert "Butter" not in s
        assert list(s) == ["Eggs"]
        assert list(s.values())[0].quantity == 6


class TestStockAdd:
    def test_add_new_item(self):
        s = Stock()
        s2 = s.add([SupplyItem(name="Flour", quantity=500, unit="g")])
        assert len(s2) == 1
        assert s2["Flour"].quantity == 500
        assert len(s) == 0  # original untouched

    def test_add_to_existing_same_unit(self):
        s = Stock([SupplyItem(name="Flour", quantity=500, unit="g")])
        s2 = s.add([SupplyItem(name="Flour", quantity=300, unit="g")])
        assert s2["Flour"].quantity == 800
        assert s["Flour"].quantity == 500  # original untouched

    def test_add_different_weight_unit(self):
        s = Stock([SupplyItem(name="Flour", quantity=500, unit="g")])
        s2 = s.add([SupplyItem(name="Flour", quantity=1, unit="kg")])
        assert s2["Flour"].unit == "g"
        assert s2["Flour"].quantity == 1500

    def test_add_merges_tags(self):
        s = Stock([SupplyItem(name="Butter", quantity=200, unit="g", tags=["unsalted"])])
        s2 = s.add([SupplyItem(name="Butter", quantity=100, unit="g")])
        assert s2["Butter"].tags == ["unsalted"]


class TestStockUse:
    def test_item_not_in_stock(self):
        s = Stock()
        s2, deficit = s.use([SupplyItem(name="Flour", quantity=500, unit="g")])
        assert len(deficit) == 1
        assert deficit[0].quantity == 500
        assert len(s2) == 0

    def test_fully_covered(self):
        s = Stock([SupplyItem(name="Flour", quantity=1000, unit="g")])
        s2, deficit = s.use([SupplyItem(name="Flour", quantity=500, unit="g")])
        assert len(deficit) == 0
        assert s2["Flour"].quantity == 500
        assert s["Flour"].quantity == 1000  # original untouched

    def test_partially_covered(self):
        s = Stock([SupplyItem(name="Flour", quantity=300, unit="g")])
        s2, deficit = s.use([SupplyItem(name="Flour", quantity=500, unit="g")])
        assert len(deficit) == 1
        assert deficit[0].quantity == 200
        assert "Flour" not in s2

    def test_fully_covered_removes_zero(self):
        s = Stock([SupplyItem(name="Flour", quantity=500, unit="g")])
        s2, deficit = s.use([SupplyItem(name="Flour", quantity=500, unit="g")])
        assert len(deficit) == 0
        assert "Flour" not in s2

    def test_unit_conversion_oz_to_g(self):
        s = Stock([SupplyItem(name="Flour", quantity=16, unit="oz")])
        s2, deficit = s.use([SupplyItem(name="Flour", quantity=500, unit="g")])
        assert len(deficit) == 1
        assert deficit[0].unit == "g"
        assert deficit[0].quantity == pytest.approx(46.4, abs=0.2)
        assert "Flour" not in s2

    def test_unit_conversion_fully_covered(self):
        s = Stock([SupplyItem(name="Sugar", quantity=2, unit="kg")])
        s2, deficit = s.use([SupplyItem(name="Sugar", quantity=500, unit="g")])
        assert len(deficit) == 0

    def test_incompatible_units_with_density(self):
        density = {"volume_weights": {"Honey": {"tbsp": 21.0}}}
        s = Stock([SupplyItem(name="Honey", quantity=21, unit="g")])
        s2, deficit = s.use(
            [SupplyItem(name="Honey", quantity=4, unit="tbsp")],
            density_data=density,
        )
        assert len(deficit) == 1
        assert deficit[0].unit == "tbsp"
        assert deficit[0].quantity == pytest.approx(3.0, abs=0.1)

    def test_density_fully_covered(self):
        density = {"volume_weights": {"Honey": {"tbsp": 21.0}}}
        s = Stock([SupplyItem(name="Honey", quantity=100, unit="g")])
        s2, deficit = s.use(
            [SupplyItem(name="Honey", quantity=2, unit="tbsp")],
            density_data=density,
        )
        assert len(deficit) == 0

    def test_multiple_items(self):
        s = Stock(
            [
                SupplyItem(name="Flour", quantity=1000, unit="g"),
                SupplyItem(name="Sugar", quantity=100, unit="g"),
            ]
        )
        s2, deficit = s.use(
            [
                SupplyItem(name="Flour", quantity=500, unit="g"),
                SupplyItem(name="Sugar", quantity=200, unit="g"),
                SupplyItem(name="Eggs", quantity=6, unit="each"),
            ]
        )
        names = {r.name for r in deficit}
        assert names == {"Sugar", "Eggs"}
        sugar = next(r for r in deficit if r.name == "Sugar")
        assert sugar.quantity == 100
        assert s2["Flour"].quantity == 500
        assert "Sugar" not in s2

    def test_ml_to_liter(self):
        s = Stock([SupplyItem(name="Milk", quantity=1, unit="liter")])
        s2, deficit = s.use([SupplyItem(name="Milk", quantity=500, unit="ml")])
        assert len(deficit) == 0


class TestStockRemove:
    def test_remove_existing(self):
        s = Stock([SupplyItem(name="Flour", quantity=500, unit="g")])
        s2 = s.remove([SupplyItem(name="Flour", quantity=300, unit="g")])
        assert s2["Flour"].quantity == 200
        assert s["Flour"].quantity == 500

    def test_remove_to_zero_drops_entry(self):
        s = Stock([SupplyItem(name="Flour", quantity=500, unit="g")])
        s2 = s.remove([SupplyItem(name="Flour", quantity=500, unit="g")])
        assert "Flour" not in s2

    def test_remove_below_zero_floors(self):
        s = Stock([SupplyItem(name="Flour", quantity=300, unit="g")])
        s2 = s.remove([SupplyItem(name="Flour", quantity=500, unit="g")])
        assert "Flour" not in s2

    def test_remove_unknown_ignored(self):
        s = Stock([SupplyItem(name="Flour", quantity=500, unit="g")])
        s2 = s.remove([SupplyItem(name="Ghost Flour", quantity=100, unit="g")])
        assert s2["Flour"].quantity == 500

    def test_remove_with_unit_conversion(self):
        s = Stock([SupplyItem(name="Flour", quantity=1000, unit="g")])
        s2 = s.remove([SupplyItem(name="Flour", quantity=1, unit="kg")])
        assert "Flour" not in s2


class TestStockYAML:
    def test_from_yaml(self, tmp_path: Path):
        data = {
            "pantry": [
                {"name": "Flour", "quantity": 500, "unit": "g"},
                {"name": "Sugar", "quantity": 200, "unit": "g"},
            ]
        }
        path = tmp_path / "pantry.yaml"
        path.write_text(yaml.dump(data))
        s = Stock.from_yaml(path)
        assert len(s) == 2
        assert s["Flour"].quantity == 500

    def test_from_yaml_missing_file(self, tmp_path: Path):
        s = Stock.from_yaml(tmp_path / "nonexistent.yaml")
        assert len(s) == 0

    def test_from_yaml_missing_fields_skipped(self, tmp_path: Path):
        data = {
            "pantry": [
                {"name": "Flour", "quantity": 500, "unit": "g"},
                {"name": "Broken"},
            ]
        }
        path = tmp_path / "pantry.yaml"
        path.write_text(yaml.dump(data))
        s = Stock.from_yaml(path)
        assert len(s) == 1
        assert "Flour" in s

    def test_to_yaml(self, tmp_path: Path):
        s = Stock(
            [
                SupplyItem(name="Flour", quantity=500, unit="g"),
                SupplyItem(name="Sugar", quantity=200, unit="g"),
            ]
        )
        path = tmp_path / "out.yaml"
        s.to_yaml(path)
        s2 = Stock.from_yaml(path)
        assert len(s2) == 2
        assert s2["Flour"].quantity == 500

    def test_roundtrip(self, tmp_path: Path):
        s = Stock([SupplyItem(name="Flour", quantity=500, unit="g")])
        path = tmp_path / "roundtrip.yaml"
        s.to_yaml(path)
        s2 = Stock.from_yaml(path)
        assert s == s2


class TestStockEquality:
    def test_equal(self):
        a = Stock([SupplyItem(name="Flour", quantity=500, unit="g")])
        b = Stock([SupplyItem(name="Flour", quantity=500, unit="g")])
        assert a == b

    def test_not_equal(self):
        a = Stock([SupplyItem(name="Flour", quantity=500, unit="g")])
        b = Stock([SupplyItem(name="Flour", quantity=300, unit="g")])
        assert a != b

    def test_not_equal_different_items(self):
        a = Stock([SupplyItem(name="Flour", quantity=500, unit="g")])
        b = Stock([SupplyItem(name="Sugar", quantity=500, unit="g")])
        assert a != b


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
                {"name": "Broken"},
            ]
        }
        path = tmp_path / "pantry.yaml"
        path.write_text(yaml.dump(data))

        from wright.loader import load_supplies

        result = load_supplies(path)
        assert len(result) == 1
        assert "Flour" in result

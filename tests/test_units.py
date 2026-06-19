"""Tests for wright units."""

from __future__ import annotations

from wright.units import are_compatible, parse_quantity, ureg


class TestUnitRegistry:
    def test_custom_units_defined(self):
        q = ureg.Quantity(1, "each")
        assert q.magnitude == 1

    def test_packet(self):
        q = ureg.Quantity(1, "packet")
        assert q.magnitude == 1

    def test_pinch(self):
        q = ureg.Quantity(1, "pinch")
        assert q.magnitude == 1

    def test_clove(self):
        q = ureg.Quantity(1, "clove")
        assert q.magnitude == 1

    def test_aliases(self):
        q1 = ureg.Quantity(1, "each")
        q2 = ureg.Quantity(1, "ea")
        q3 = ureg.Quantity(1, "piece")
        q4 = ureg.Quantity(1, "pieces")
        assert q1.magnitude == q2.magnitude == q3.magnitude == q4.magnitude

    def test_teaspoon_tablespoon_aliases(self):
        tsp = ureg.Quantity(1, "teaspoon")
        ureg.Quantity(1, "tablespoon")
        result = tsp.to("tsp")
        assert abs(float(result.magnitude) - 1.0) < 0.01


class TestParseQuantity:
    def test_grams(self):
        q = parse_quantity(500, "g")
        assert abs(float(q.to("g").magnitude) - 500) < 0.01

    def test_ounces_to_grams(self):
        q = parse_quantity(16, "oz")
        grams = float(q.to("g").magnitude)
        assert abs(grams - 453.59) < 1

    def test_cups_to_ml(self):
        q = parse_quantity(2, "cup")
        ml = float(q.to("ml").magnitude)
        assert abs(ml - 473.18) < 5


class TestAreCompatible:
    def test_compatible(self):
        assert are_compatible("g", "oz") is True
        assert are_compatible("ml", "cup") is True

    def test_incompatible(self):
        assert are_compatible("g", "ml") is False
        assert are_compatible("each", "g") is False

    def test_same_unit(self):
        assert are_compatible("g", "g") is True

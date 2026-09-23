"""Tests for ingredient substitution — Assembly.substitute() and swap()."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from wright.models import (
    Assembly,
    Component,
    Ingredient,
    Material,
    Recipe,
    RecipeComponent,
    Replacement,
    ServingRange,
    Substitution,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def assembly() -> Assembly:
    return Assembly(
        name="Test",
        components=[
            Component(
                name="Frame",
                materials=[
                    Material(name="Wheat Flour", quantity=100, unit="g"),
                    Material(name="Butter", quantity=50, unit="g"),
                ],
            ),
            Component(
                name="Topping",
                materials=[Material(name="Wheat Flour", quantity=10, unit="g")],
            ),
        ],
    )


def make_recipe(*ingredients: Ingredient) -> Recipe:
    return Recipe(
        name="Test Recipe",
        components=[RecipeComponent(name="All", ingredients=list(ingredients))],
        prep_time=1,
        cook_time=1,
        servings=ServingRange(min_servings=8, max_servings=8),
    )


def material_pairs(assembly: Assembly) -> list[tuple[str, str, float]]:
    return [
        (comp.name, m.name, m.quantity)
        for comp in assembly.components
        for m in comp.materials
    ]


# ── Construction validation ────────────────────────────────────────────────


class TestSubstitutionValidation:
    def test_shares_must_sum_to_total(self) -> None:
        with pytest.raises(ValidationError, match="sum to 0.75"):
            Substitution(
                from_name="Wheat Flour",
                replacements=[
                    Replacement(name="Almond Flour", share=0.5),
                    Replacement(name="Cornmeal", share=0.25),
                ],
            )

    def test_shares_above_total_rejected(self) -> None:
        with pytest.raises(ValidationError, match="sum to 1.2"):
            Substitution(
                from_name="Wheat Flour",
                replacements=[Replacement(name="Almond Flour", share=1.2)],
            )

    def test_empty_replacements_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Substitution(from_name="Wheat Flour", replacements=[])

    def test_nonpositive_share_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Replacement(name="Almond Flour", share=0)

    def test_mass_changing_conversion_allowed_with_total(self) -> None:
        sub = Substitution(
            from_name="Fresh Yeast",
            replacements=[Replacement(name="Instant Dry Yeast", share=0.33)],
            total=0.33,
        )
        assert sub.total == 0.33

    def test_single_replacement_defaults_to_full_share(self) -> None:
        sub = Substitution(
            from_name="Wheat Flour", replacements=[Replacement(name="Almond Flour")]
        )
        assert sub.replacements[0].share == 1.0


# ── swap() input forms ──────────────────────────────────────────────────────


class TestSwapForms:
    def test_one_to_one(self, assembly: Assembly) -> None:
        result = assembly.swap("Wheat Flour", "Almond Flour")
        assert ("Topping", "Almond Flour", 10.0) in material_pairs(result)
        assert ("Frame", "Almond Flour", 100.0) in material_pairs(result)

    def test_split_by_share_dict(self, assembly: Assembly) -> None:
        result = assembly.swap(
            "Wheat Flour", {"Almond Flour": 0.5, "Cornmeal": 0.5}, only_in="Frame"
        )
        assert ("Frame", "Almond Flour", 50.0) in material_pairs(result)
        assert ("Frame", "Cornmeal", 50.0) in material_pairs(result)
        assert ("Topping", "Wheat Flour", 10.0) in material_pairs(result)

    def test_even_split_list(self, assembly: Assembly) -> None:
        result = assembly.swap("Wheat Flour", ["Almond Flour", "Cornmeal"])
        frame = [m for m in result.components[0].materials if m.name != "Butter"]
        assert [(m.name, m.quantity) for m in frame] == [
            ("Almond Flour", 50.0),
            ("Cornmeal", 50.0),
        ]

    def test_multi_rename_dict(self, assembly: Assembly) -> None:
        result = assembly.swap({
            "Wheat Flour": "Almond Flour",
            "Butter": "Vegan Butter",
        })
        names = {m.name for comp in result.components for m in comp.materials}
        assert names == {"Almond Flour", "Vegan Butter"}

    def test_substitution_model(self, assembly: Assembly) -> None:
        result = assembly.swap(
            Substitution(
                from_name="Wheat Flour",
                replacements=[Replacement(name="Almond Flour")],
            )
        )
        assert all(
            m.name != "Wheat Flour"
            for comp in result.components
            for m in comp.materials
        )

    def test_substitution_list(self, assembly: Assembly) -> None:
        result = assembly.swap([
            Substitution(
                from_name="Wheat Flour",
                replacements=[Replacement(name="Almond Flour")],
            ),
            Substitution(
                from_name="Butter",
                replacements=[Replacement(name="Vegan Butter")],
            ),
        ])
        names = {m.name for comp in result.components for m in comp.materials}
        assert names == {"Almond Flour", "Vegan Butter"}

    def test_total_kwarg_for_conversions(self, assembly: Assembly) -> None:
        result = assembly.swap(
            "Wheat Flour", {"Instant Dry Yeast": 0.33}, total=0.33, only_in="Frame"
        )
        assert ("Frame", "Instant Dry Yeast", pytest.approx(33.0)) in material_pairs(
            result
        )

    def test_swap_requires_target_for_string_source(self, assembly: Assembly) -> None:
        with pytest.raises(ValueError, match="requires a target"):
            assembly.swap("Wheat Flour")

    def test_unsupported_forms_raise(self, assembly: Assembly) -> None:
        with pytest.raises(ValueError):
            assembly.swap(123, "X")  # ty:ignore[invalid-argument-type]
        with pytest.raises(ValueError):
            assembly.swap("Wheat Flour", 123)  # ty:ignore[invalid-argument-type]


# ── Matching semantics ──────────────────────────────────────────────────────


class TestMatching:
    def test_case_insensitive(self, assembly: Assembly) -> None:
        result = assembly.swap("wheat flour", "Almond Flour")
        assert all(
            m.name != "Wheat Flour"
            for comp in result.components
            for m in comp.materials
        )

    def test_unmatched_passes_through(self, assembly: Assembly) -> None:
        result = assembly.swap({"Mystery Item": "Something Else"})
        assert material_pairs(result) == material_pairs(assembly)

    def test_strict_raises_listing_all_unmatched(self, assembly: Assembly) -> None:
        with pytest.raises(ValueError) as excinfo:
            assembly.swap(
                [
                    Substitution(
                        from_name="Wheat Flower",
                        replacements=[Replacement(name="X")],
                    ),
                    Substitution(
                        from_name="Salt",
                        replacements=[Replacement(name="Kosher Salt")],
                    ),
                ],
                strict=True,
            )
        message = str(excinfo.value)
        assert "'Wheat Flower'" in message
        assert "'Salt'" in message

    def test_strict_component_typo_includes_context(self, assembly: Assembly) -> None:
        with pytest.raises(ValueError, match="component 'Dough'"):
            assembly.swap(
                Substitution(
                    from_name="Wheat Flour",
                    component="Dough",
                    replacements=[Replacement(name="X")],
                ),
                strict=True,
            )

    def test_component_scoping(self, assembly: Assembly) -> None:
        result = assembly.swap(
            "Wheat Flour", "Almond Flour", only_in="topping"
        )  # case-insensitive component
        assert ("Topping", "Almond Flour", 10.0) in material_pairs(result)
        assert ("Frame", "Wheat Flour", 100.0) in material_pairs(result)

    def test_first_rule_wins_on_duplicate_from_name(self, assembly: Assembly) -> None:
        result = assembly.swap([
            Substitution(
                from_name="Wheat Flour", replacements=[Replacement(name="First")]
            ),
            Substitution(
                from_name="Wheat Flour", replacements=[Replacement(name="Second")]
            ),
        ])
        names = {m.name for comp in result.components for m in comp.materials}
        assert "First" in names
        assert "Second" not in names

    def test_replacement_names_not_rematched(self, assembly: Assembly) -> None:
        result = assembly.swap([
            Substitution(
                from_name="Wheat Flour", replacements=[Replacement(name="Butter")]
            ),
            Substitution(
                from_name="Butter", replacements=[Replacement(name="Margarine")]
            ),
        ])
        # Original Butter (50 g) became Margarine; the NEW Butter (from
        # Wheat Flour, 100 g) is NOT re-matched by the second rule.
        frame = {m.name: m.quantity for m in result.components[0].materials}
        assert frame == {"Butter": 100.0, "Margarine": 50.0}


# ── Replacement semantics ───────────────────────────────────────────────────


class TestReplacementSemantics:
    def test_partial_keep(self, assembly: Assembly) -> None:
        result = assembly.swap(
            "Wheat Flour",
            {"Wheat Flour": 0.5, "Almond Flour": 0.5},
            only_in="Frame",
        )
        frame = {m.name: m.quantity for m in result.components[0].materials}
        assert frame["Wheat Flour"] == 50.0
        assert frame["Almond Flour"] == 50.0

    def test_unit_override(self, assembly: Assembly) -> None:
        result = assembly.swap(
            "Wheat Flour",
            Replacement(name="Almond Flour", unit="oz"),
        )
        swapped = [
            m
            for comp in result.components
            for m in comp.materials
            if m.name == "Almond Flour"
        ]
        assert all(m.unit == "oz" for m in swapped)

    def test_require_tags_fresh_start(self) -> None:
        recipe = make_recipe(
            Ingredient(name="Butter", quantity=100, unit="g", require_tags=["unsalted"])
        )
        result = recipe.swap("Butter", "Vegan Butter")
        swapped = result.components[0].materials[0]
        assert swapped.name == "Vegan Butter"
        assert swapped.require_tags == []

    def test_require_tags_on_replacement(self) -> None:
        recipe = make_recipe(Ingredient(name="Butter", quantity=100, unit="g"))
        result = recipe.swap(
            "Butter", Replacement(name="Butter", require_tags=["unsalted"])
        )
        assert result.components[0].materials[0].require_tags == ["unsalted"]

    def test_equivalences_dropped_on_rename(self) -> None:
        recipe = make_recipe(
            Ingredient(
                name="Onion",
                quantity=1000,
                unit="g",
                equivalent_quantity=8,
                equivalent_unit="each",
                approx_weight_grams=125,
            )
        )
        result = recipe.swap("Onion", "Leek")
        m = result.components[0].materials[0]
        assert m.equivalent_quantity is None
        assert m.equivalent_unit is None
        assert m.approx_weight_grams is None

    def test_equivalences_kept_on_partial_keep(self) -> None:
        recipe = make_recipe(
            Ingredient(
                name="Onion",
                quantity=1000,
                unit="g",
                equivalent_quantity=8,
                equivalent_unit="each",
                approx_weight_grams=125,
            )
        )
        result = recipe.swap("Onion", {"Onion": 0.5, "Leek": 0.5})
        kept = next(m for m in result.components[0].materials if m.name == "Onion")
        assert kept.equivalent_quantity == 8
        assert kept.approx_weight_grams == 125
        leek = next(m for m in result.components[0].materials if m.name == "Leek")
        assert leek.equivalent_quantity is None
        assert leek.approx_weight_grams is None

    def test_product_ref_replaced_wholesale(self) -> None:
        """Documented v1 behavior: substituting a product_ref line replaces
        the reference itself (no recursion into the referenced assembly)."""
        recipe = make_recipe(
            Ingredient(
                name="Vanilla Sugar",
                quantity=1,
                unit="packet",
                equivalent_quantity=8,
                product_ref="vanilla-sugar",
            )
        )
        result = recipe.swap("Vanilla Sugar", "Powdered Sugar")
        m = result.components[0].materials[0]
        assert m.name == "Powdered Sugar"
        assert m.product_ref is None


# ── Composition ─────────────────────────────────────────────────────────────


class TestComposition:
    def test_chainable(self, assembly: Assembly) -> None:
        result = assembly.swap("Wheat Flour", "Almond Flour").swap(
            "Butter", "Vegan Butter"
        )
        names = {m.name for comp in result.components for m in comp.materials}
        assert names == {"Almond Flour", "Vegan Butter"}

    def test_scale_composition(self, assembly: Assembly) -> None:
        a = assembly.swap("Wheat Flour", "Almond Flour").size_up(2)
        b = assembly.size_up(2).swap("Wheat Flour", "Almond Flour")
        assert material_pairs(a) == material_pairs(b)

    def test_original_untouched(self, assembly: Assembly) -> None:
        before = material_pairs(assembly)
        assembly.swap("Wheat Flour", "Almond Flour")
        assembly.swap("Butter", "Vegan Butter", strict=True)
        assert material_pairs(assembly) == before

    def test_recipe_type_preserved(self) -> None:
        recipe = make_recipe(Ingredient(name="Wheat Flour", quantity=100, unit="g"))
        result = recipe.swap("Wheat Flour", "Almond Flour")
        assert isinstance(result, Recipe)
        assert result.prep_time == 1
        assert result.servings == ServingRange(min_servings=8, max_servings=8)

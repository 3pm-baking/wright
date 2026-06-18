"""Allergen and dietary badge detection — pure functions, no I/O."""

from __future__ import annotations

from collections.abc import Callable

from wright.models import Ingredient, Recipe

# ---------------------------------------------------------------------------
# Badge configuration
# ---------------------------------------------------------------------------

BADGE_DISPLAY: dict[str, str] = {
    "vegan": "VEGAN",
    "gluten-free": "GLUTEN-FREE",
    "dairy-free": "DAIRY-FREE",
    "nut-free": "NUT-FREE",
    "soy-free": "SOY-FREE",
    "organic": "ORGANIC",
    "local": "LOCAL",
    "no-refined-sugar": "NO REFINED SUGAR",
}

BADGE_IMPLIES: dict[str, set[str]] = {
    "vegan": {"dairy-free"},
}


# ── Default dietary keyword sets (English food vocabulary) ──────────────────

DEFAULT_NON_VEGAN_KEYS: frozenset[str] = frozenset(
    {
        "egg",
        "honey",
        "gelatin",
        "lard",
        "meat",
        "chicken",
        "beef",
        "pork",
        "fish",
        "shrimp",
        "anchovy",
        "milk",
        "cream",
        "butter",
        "cheese",
        "yogurt",
        "sour cream",
        "cream cheese",
        "whey",
        "casein",
    }
)
"""Default ingredient-name keywords that disqualify vegan."""

DEFAULT_DAIRY_KEYS: frozenset[str] = frozenset(
    {
        "milk",
        "cream",
        "butter",
        "cheese",
        "yogurt",
        "sour cream",
        "cream cheese",
        "whey",
        "casein",
    }
)
"""Default ingredient-name keywords that disqualify dairy-free."""

DEFAULT_GLUTEN_KEYS: frozenset[str] = frozenset(
    {"flour", "wheat", "barley", "rye", "spelt", "semolina"}
)
"""Default ingredient-name keywords that disqualify gluten-free."""


# ---------------------------------------------------------------------------
# Ingredient-level helpers
# ---------------------------------------------------------------------------


def _is_gluten_free(name_lower: str) -> bool:
    """Return True if the ingredient name indicates a gluten-free product."""
    return (
        name_lower.startswith("gf ")
        or name_lower.endswith(", gf")
        or "gluten free" in name_lower
        or "gluten-free" in name_lower
        or "glutenfree" in name_lower
        or "almond flour" in name_lower
        or "(gf)" in name_lower
        or " gf " in name_lower
    )


def _is_vegan(name_lower: str) -> bool:
    """Return True if the ingredient name indicates a vegan/plant-based product."""
    return (
        name_lower.startswith("vegan ")
        or "vegan " in name_lower
        or "plant-based" in name_lower
        or "plant based" in name_lower
        or "dairy-free" in name_lower
        or "dairy free" in name_lower
        or "non-dairy" in name_lower
        or "non dairy" in name_lower
        or "almond milk" in name_lower
        or "oat milk" in name_lower
        or "soy milk" in name_lower
        or "coconut milk" in name_lower
        or "coconut cream" in name_lower
        or "rice milk" in name_lower
    )


# ---------------------------------------------------------------------------
# Allergen detection
# ---------------------------------------------------------------------------


def detect_allergens(
    recipe: Recipe,
    allergy_map: dict[str, str],
    *,
    ingredient_properties: Callable[[Ingredient], frozenset[str]] | None = None,
) -> list[str]:
    """Detect allergens present in a recipe's ingredients.

    Consult the *ingredient_properties* callback (if provided) per
    ingredient to suppress wheat/dairy keyword matches when the
    ingredient is known to be gluten-free or vegan.

    Args:
        recipe: The recipe to scan.
        allergy_map: Mapping of lowercase keyword → display name
            (e.g. ``{"milk": "Milk", "wheat": "Wheat"}``).
        ingredient_properties: Optional callback
            ``(ingredient) -> frozenset[str]`` for authoritative dietary
            properties (e.g. ``{"vegan", "gluten-free"}``).

    Returns:
        Sorted list of allergen display names.
    """
    dairy_keys = frozenset(
        {"butter", "cream", "cheese", "milk", "yogurt", "cream cheese", "sour cream"}
    )
    wheat_keys = frozenset({"flour", "wheat"})

    found: set[str] = set()

    for ingredient in recipe.all_ingredients:
        if ingredient.byproduct:
            continue

        name_lower = ingredient.name.lower()

        # Determine GF / vegan status
        callback_props: frozenset[str] = frozenset()
        if ingredient_properties is not None:
            callback_props = ingredient_properties(ingredient)

        gf = "gluten-free" in callback_props or _is_gluten_free(name_lower)
        vegan = "vegan" in callback_props or _is_vegan(name_lower)

        for key, allergy in allergy_map.items():
            if allergy in found:
                continue

            if key in wheat_keys and gf and key != "wheat":
                continue
            if key == "wheat" and gf and "wheat" not in name_lower:
                continue

            if key in dairy_keys and vegan:
                continue

            if key == "cream" and "cream of tartar" in name_lower:
                continue

            if key in name_lower:
                found.add(allergy)

    return sorted(found)


def detect_allergens_from_names(
    ingredient_names: list[str],
    allergy_map: dict[str, str],
    *,
    ingredient_properties_for_name: Callable[[str], frozenset[str]] | None = None,
) -> list[str]:
    """Detect allergens from a plain list of ingredient name strings.

    Useful when working with flat ingredient lists rather than structured
    ``Recipe`` objects.

    Args:
        ingredient_names: List of ingredient name strings.
        allergy_map: Mapping of lowercase keyword → display name.
        ingredient_properties_for_name: Optional callback
            ``(name) -> frozenset[str]`` for authoritative dietary properties.

    Returns:
        Sorted list of allergen display names.
    """
    dairy_keys = frozenset(
        {"butter", "cream", "cheese", "milk", "yogurt", "cream cheese", "sour cream"}
    )
    wheat_keys = frozenset({"flour", "wheat"})

    found: set[str] = set()

    for name in ingredient_names:
        name_lower = name.lower()

        callback_props: frozenset[str] = frozenset()
        if ingredient_properties_for_name is not None:
            callback_props = ingredient_properties_for_name(name)

        gf = "gluten-free" in callback_props or _is_gluten_free(name_lower)
        vegan = "vegan" in callback_props or _is_vegan(name_lower)

        for key, allergy in allergy_map.items():
            if allergy in found:
                continue

            if key in wheat_keys and gf and key != "wheat":
                continue
            if key == "wheat" and gf and "wheat" not in name_lower:
                continue

            if key in dairy_keys and vegan:
                continue

            if key == "cream" and "cream of tartar" in name_lower:
                continue

            if key in name_lower:
                found.add(allergy)

    return sorted(found)


# ---------------------------------------------------------------------------
# Badge detection
# ---------------------------------------------------------------------------


def _resolve_badges(
    raw_badges: list[str],
    badge_display: dict[str, str] | None = None,
    badge_implies: dict[str, set[str]] | None = None,
) -> list[str]:
    """Normalize badge slugs, suppress redundant ones, return display labels."""
    _display = badge_display or BADGE_DISPLAY
    _implies = badge_implies or BADGE_IMPLIES
    normalized = [b.lower().strip() for b in raw_badges]
    suppressed: set[str] = set()
    for badge in normalized:
        for redundant in _implies.get(badge, set()):
            suppressed.add(redundant)

    result: list[str] = []
    for badge in normalized:
        if badge not in suppressed:
            result.append(_display.get(badge, badge.upper()))
    return result


def detect_dietary_properties(
    recipe: Recipe,
    *,
    ingredient_properties: Callable[[Ingredient], frozenset[str]] | None = None,
    non_vegan_keys: frozenset[str] | None = None,
    dairy_keys: frozenset[str] | None = None,
    gluten_keys: frozenset[str] | None = None,
    badge_display: dict[str, str] | None = None,
    badge_implies: dict[str, set[str]] | None = None,
) -> list[str]:
    """Derive dietary/quality display badges from a recipe's ingredients.

    A badge is awarded only when ALL non-byproduct ingredients qualify.

    Supported built-in badges (in display order):
        - ``VEGAN`` -- no animal products detected.
        - ``DAIRY-FREE`` -- no dairy detected (suppressed when VEGAN present).
        - ``GLUTEN-FREE`` -- no gluten/wheat detected.

    Additional badges (e.g. ``keto``, ``paleo``) are supported via the
    *ingredient_properties* callback -- any property key returned by the
    callback is tracked the same way.

    **Detection priority per ingredient**:

    1. If *ingredient_properties* returns a frozenset containing the property
       name, that is authoritative (``True``).
    2. If *ingredient_properties* returns ``frozenset()`` (or the callback
       is ``None``), fall through to keyword matching on the ingredient name.

    Args:
        recipe: The recipe to scan.
        ingredient_properties: Optional callback ``(ingredient) -> frozenset[str]``
            that returns dietary properties for an ingredient from an
            external data source (e.g. purchase tags, brand database).
            If the resulting frozenset does not contain a property, keyword
            matching is used as a fallback.
        non_vegan_keys: Ingredient-name keywords that disqualify vegan.
            Defaults to the built-in English food vocabulary.
        dairy_keys: Ingredient-name keywords that disqualify dairy-free.
            Defaults to the built-in set.
        gluten_keys: Ingredient-name keywords that disqualify gluten-free.
            Defaults to the built-in set.
        badge_display: Mapping of badge slug → display label.
            Defaults to :data:`BADGE_DISPLAY`.
        badge_implies: Mapping of badge slug → set of redundant badges.
            Defaults to :data:`BADGE_IMPLIES`.

    Returns:
        List of display strings (e.g. ``["VEGAN", "GLUTEN-FREE"]``).
    """
    _non_vegan = non_vegan_keys or DEFAULT_NON_VEGAN_KEYS
    _dairy = dairy_keys or DEFAULT_DAIRY_KEYS
    _gluten = gluten_keys or DEFAULT_GLUTEN_KEYS
    _badge_display = badge_display or BADGE_DISPLAY
    _badge_implies = badge_implies or BADGE_IMPLIES

    # Collect all property keys that appear from the callback
    all_callback_keys: set[str] = set()

    # Track per-property: all-ingredients-must-be-True
    props: dict[str, bool] = {"vegan": True, "dairy-free": True, "gluten-free": True}

    for ing in recipe.all_ingredients:
        if ing.byproduct:
            continue
        name_lower = ing.name.lower()

        # Consult the callback
        callback_props: frozenset[str] = frozenset()
        if ingredient_properties is not None:
            callback_props = ingredient_properties(ing)
            all_callback_keys.update(callback_props)

        # Vegan
        if callback_props and "vegan" in callback_props:
            pass  # authoritative yes
        elif callback_props:
            pass  # callback answered other properties but not this one
        elif _is_vegan(name_lower):
            pass  # keyword fallback
        else:
            for key in _non_vegan:
                if key in name_lower:
                    props["vegan"] = False
                    break

        # Dairy-free
        if (
            callback_props
            and "dairy-free" in callback_props
            or callback_props
            or _is_vegan(name_lower)
        ):
            pass
        else:
            for key in _dairy:
                if key in name_lower:
                    props["dairy-free"] = False
                    break

        # Gluten-free
        if (
            callback_props
            and "gluten-free" in callback_props
            or callback_props
            or _is_gluten_free(name_lower)
        ):
            pass
        else:
            for key in _gluten:
                if key in name_lower:
                    props["gluten-free"] = False
                    break

        # Additional properties from callback only (no keyword fallback)
        for extra_key in all_callback_keys - {"vegan", "dairy-free", "gluten-free"}:
            if extra_key not in props:
                props[extra_key] = True
            if not (callback_props and extra_key in callback_props):
                props[extra_key] = False

    # Build result
    raw_badges: list[str] = []
    for prop_name in [
        "vegan",
        "dairy-free",
        "gluten-free",
        *sorted(all_callback_keys - {"vegan", "dairy-free", "gluten-free"}),
    ]:
        if props.get(prop_name, False):
            raw_badges.append(prop_name)

    return _resolve_badges(raw_badges, _badge_display, _badge_implies)

---
title: Customization
description: Inject custom unit converters, dietary property callbacks, nutrition data sources, volume display normalizers, and Pint unit registries into wright.
---

# Customization

Every decision point in wright is injectable. Replace the default behavior
at any level below the public API surface.

## Cost conversion: custom unit handling

Insert a custom converter before the built-in cascade:

```python
from wright import calculate_ingredient_cost


def my_converter(ingredient, grocery, density_data):
    if ingredient.unit == "box" and grocery.unit == "box":
        return grocery.price / Decimal(grocery.quantity) * Decimal(ingredient.quantity)
    return None  # fall through to built-in cascade


cost = calculate_ingredient_cost(ingredient, grocery, converter=my_converter)
```

## Dietary detection: authoritative properties

Override keyword-based detection with a callback backed by your own data:

```python
from wright import detect_dietary_properties


def my_properties(ingredient):
    """Read dietary properties from our purchase database."""
    purchase = my_db.lookup(ingredient.name)
    if purchase is None:
        return frozenset()  # fall through to keyword matching
    props = set()
    if "vegan" in purchase.tags:
        props.update({"vegan", "dairy-free"})
    if "gluten-free" in purchase.tags:
        props.add("gluten-free")
    return frozenset(props)


badges = detect_dietary_properties(recipe, ingredient_properties=my_properties)
```

The same callback works with `detect_allergens`:

```python
from wright import detect_allergens

allergens = detect_allergens(recipe, allergy_map, ingredient_properties=my_properties)
```

## Volume display: metric vs imperial

Swap how accumulated volumes are displayed:

```python
from wright import generate_shopping_list


def metric_display(qty, unit):
    """Always display in ml or liters, never gallons/quarts."""
    from wright.units import ureg

    ml = ureg.Quantity(qty, unit).to("ml")
    if ml.magnitude >= 1000:
        return (round(ml.to("liter").magnitude, 2), "liter")
    return (round(ml.magnitude, 0), "ml")


shopping = generate_shopping_list(
    session,
    recipes,
    display_normalizer=metric_display,
)
```

## Accumulation units: density-aware volume_normalizer

While `display_normalizer` controls what the shopper *sees*,
`volume_normalizer` controls how quantities are *accumulated*.  It
receives the ingredient name, so you can convert volume → weight per
ingredient — the recommended way to let a recipe measuring flour in
cups merge correctly with one measuring it in grams:

```python
from wright import generate_shopping_list


def density_normalizer(quantity, unit, *, name=""):
    """Convert volume units to grams using per-ingredient density data."""
    grams = my_density_lookup(name, quantity, unit)  # your data source
    if grams is not None:
        return grams, "g"
    return quantity, unit  # non-volume units pass through


shopping = generate_shopping_list(
    session,
    recipes,
    volume_normalizer=density_normalizer,
    on_incompatible="raise",  # refuse ml+g sums instead of guessing
)
```

The default (`on_incompatible="add"`) sums incompatible units numerically
for backward compatibility — prefer `"raise"` plus a density-aware
normalizer so bad data fails loudly instead of producing plausible-looking
wrong totals.

## Nutrition: custom data source

Pass your own registry or a callback for live lookups:

```python
from wright import calculate_recipe_macros, NutritionInfo

registry = {
    "Rolled Oats": NutritionInfo(protein_g=13.5, carbs_g=66.3, fat_g=6.5, kcal=389),
}


# Or a live lookup fallback
def usda_lookup(name: str) -> NutritionInfo | None:
    result = fetch_from_usda(name)
    return NutritionInfo(**result) if result else None


macros = calculate_recipe_macros(
    recipe,
    nutrition_registry=registry,
    ingredient_nutrition_lookup=usda_lookup,
)
```

## Unit registry: custom units

Use a custom Pint registry with additional unit definitions:

```python
import pint
from wright.units import parse_quantity

my_ureg = pint.UnitRegistry()
my_ureg.define("crate = 24 * each")

qty = parse_quantity(3, "crate", ureg=my_ureg)
```

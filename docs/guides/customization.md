# Customization

Every decision point in wright is injectable.  Replace the default behavior
at any level — from name matching to cost calculation to dietary detection.

## Subclassing models

Add domain-specific fields without losing library compatibility:

```python
from wright import Material, Ingredient, Recipe

class Lumber(Material):
    """Construction material with building-specific fields."""
    grade: str | None = None
    waste_factor: float = 0.10

class MyIngredient(Ingredient):
    origin: str = "local"

class MyRecipe(Recipe):
    sale_price: Decimal | None = None
```

``Material`` subclasses work everywhere the base classes are accepted —
matching, costing, planning functions all accept ``Material``.

## Matching: custom name resolution

The default matcher does exact name matching.  Inject a fuzzy matcher:

```python
from wright import calculate_recipe_cost, find_matching_purchases

def fuzzy_matcher(ingredient, groceries):
    # Try exact match first, then substring fallback
    exact = [g for g in groceries if g.name == ingredient.name]
    if exact:
        return [g for g in exact if g.matches_requirements(ingredient.require_tags)]
    return [
        g for g in groceries
        if ingredient.name.lower() in g.name.lower()
        and g.matches_requirements(ingredient.require_tags)
    ]

cost = calculate_recipe_cost(recipe, groceries, matcher=fuzzy_matcher)
```

## Picking: which purchase price to use

Compose multiple pickers with `chain()`.  See the
[Examples guide](examples.md#custom-pickers) for the built-in picker catalog.

```python
from wright import chain, pinned_picker, cheapest_picker, calculate_shopping_list_cost

pinned = {"Rolled Oats": my_preferred_oats}
picker = chain(pinned_picker(pinned), cheapest_picker)

items = calculate_shopping_list_cost(shopping, groceries, picker=picker)
```

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
    session, recipes,
    display_normalizer=metric_display,
)
```

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

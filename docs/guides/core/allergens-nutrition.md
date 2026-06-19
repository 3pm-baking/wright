---
title: Allergens & Nutrition
description: Detect allergens and dietary badges from recipes, calculate per-serving macronutrients, and inject custom ingredient property callbacks.
---

# Allergens & Nutrition

## Allergen detection

Provide an allergy keyword map and call `detect_allergens`:

```python
from wright import detect_allergens

allergy_map = {
    "milk": "Dairy",
    "cheese": "Dairy",
    "butter": "Dairy",
    "wheat": "Gluten",
    "flour": "Gluten",
    "egg": "Eggs",
    "fish": "Fish",
}

allergens = detect_allergens(recipe, allergy_map)
print(f"Contains: {', '.join(allergens)}")
# → "Contains: Dairy, Eggs, Gluten"
```

Allergens are returned as sorted display names. Only the ones actually present
in the recipe appear. If an ingredient isn't in the map, it doesn't trigger
anything — wc_right won't guess.

## Dietary badges

Keyword-based detection for vegan, dairy-free, and gluten-free labeling:

```python
from wright import detect_dietary_properties

badges = detect_dietary_properties(recipe)
# → ["VEGAN", "GLUTEN-FREE"]
```

Customize by injecting an `ingredient_properties` callback. The same callback
works for both `detect_allergens` and `detect_dietary_properties`:

```python
def my_properties(ingredient):
    """Read properties from our database."""
    purchase = my_db.lookup(ingredient.name)
    if purchase is None:
        return frozenset()
    props = set()
    if "vegan" in purchase.tags:
        props.update({"vegan", "dairy-free"})
    if "gluten-free" in purchase.tags:
        props.add("gluten-free")
    return frozenset(props)

badges = detect_dietary_properties(recipe, ingredient_properties=my_properties)
```

## Nutrition

Calculate per-serving macronutrients from your own ingredient database:

```python
from wright import calculate_recipe_macros, NutritionInfo

registry = {
    "Rolled Oats": NutritionInfo(protein_g=13.5, carbs_g=66.3, fat_g=6.5, kcal=389),
    "Greek Yogurt": NutritionInfo(protein_g=10.0, carbs_g=3.6, fat_g=0.7, kcal=59),
}

macros = calculate_recipe_macros(recipe, nutrition_registry=registry)
# → RecipeMacros(.recipe_name, .total, .per_serving)

print(f"Per serving: {macros.per_serving.kcal:.0f} kcal, "
      f"{macros.per_serving.protein_g:.0f}g protein")
```

For live lookups (USDA API, etc.), pass `ingredient_nutrition_lookup`:

```python
def usda_lookup(name: str) -> NutritionInfo | None:
    result = fetch_from_usda(name)
    return NutritionInfo(**result) if result else None

macros = calculate_recipe_macros(
    recipe,
    nutrition_registry=registry,
    ingredient_nutrition_lookup=usda_lookup,
)
```

`MacroPerServing` supports `+` and `*` for clean aggregation across meals:

```python
from wright import MacroPerServing

daily = sum(
    (recipe_macros[name].total * qty for name, qty in meals.items()),
    start=MacroPerServing.zero(),
)
```

---
title: Models
description: Material, Component, Ingredient, Recipe, and the domain-agnostic type system. Subclass for construction lumber, food ingredients, brewing grain bills, or manufacturing assemblies.
---

# Models

The domain-agnostic base classes are `Material` and `Component`. For food,
`Ingredient` and `RecipeComponent` add no extra fields — they're aliases that
keep recipes readable. For construction, brewing, or manufacturing, use
`Material` directly.

## Defining a recipe

```python
from wright import Recipe, Ingredient, RecipeComponent, ServingRange

cake = Recipe(
    name="Lemon Cake",
    components=[
        RecipeComponent(
            name="Batter",
            ingredients=[
                Ingredient(name="Flour", quantity=300, unit="g"),
                Ingredient(name="Butter", quantity=200, unit="g"),
            ],
        )
    ],
    prep_time=30,
    cook_time=45,
    servings=ServingRange(min_servings=8, max_servings=12),
)
```

`Recipe` exposes:

- `.all_ingredients` — flat list of every `Ingredient` across all components
- `.servings.midpoint` — average of min/max (e.g., 10)
- `.net_weight_grams` — total weight of all ingredients in grams
- `recipe * 2` — scale the recipe (delegates to `.size_up()`)

```python
double = cake * 2  # every ingredient doubled
half = cake * 0.5
```

## Material and Component (non-food domains)

`Ingredient` and `RecipeComponent` inherit from `Material` and `Component`.
Use the base classes directly for construction, brewing, or manufacturing:

```python
from wright import Material, Component

framing = Component(
    name="Deck Framing",
    materials=[
        Material(
            name="2x6 Pressure-Treated", quantity=24, unit="ft", require_tags=["#2"]
        ),
        Material(name='3" Deck Screws', quantity=200, unit="each"),
    ],
)

big_framing = framing * 1.5  # every material scaled 1.5x
```

## Subclassing for domain data

Add fields without losing library compatibility. `Material` subclasses work
everywhere — matching, costing, and planning functions all accept `Material`.

```python
from wright import Material, Ingredient, Recipe


class Lumber(Material):
    grade: str | None = None
    waste_factor: float = 0.10
    species: str | None = None


stud = Lumber(
    name="2x4 Stud",
    quantity=12,
    unit="ft",
    grade="#2",
    species="Douglas Fir",
    waste_factor=0.05,
)


class MyIngredient(Ingredient):
    origin: str = "local"


class MyRecipe(Recipe):
    sale_price: Decimal | None = None
```

## Key types

| Type | Description |
|------|-------------|
| `Material` | A named item with quantity, unit, optional tags |
| `Component` | A group of `Material` items with a name |
| `Ingredient` | Alias for `Material` (used in recipes) |
| `RecipeComponent` | Alias for `Component` (used in recipes) |
| `Recipe` | A named assembly with components, prep/cook time, servings |
| `ServingRange` | `min_servings` and `max_servings` range |
| `Purchase` | A purchase record with name, quantity, unit, price |
| `PurchasedItem` | Protocol — any object with `.name`, `.quantity`, `.unit`, `.price` works |

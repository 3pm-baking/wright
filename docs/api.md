---
title: API Reference
description: Complete API reference for wright — models, costing, matching, planning, pricing, allergens, nutrition, session, supply, errors, and units modules.
---

# API Reference

## `wright.models`

::: wright.models
    options:
      members:
        - Assembly
        - Material
        - Component
        - Ingredient
        - Recipe
        - RecipeComponent
        - ServingRange
        - Servings
        - PurchasedItem
        - Purchase
        - NutritionInfo
        - MacroPerServing
        - RecipeMacros
        - FoodRecord
        - PriceRange
        - IngredientCost
        - RecipeCost
        - CategoryRule
        - categorize_item
        - DEFAULT_CATEGORY_RULES
        - BaseIngredient
        - BaseRecipe

## `wright.costing`

::: wright.costing
    options:
      members:
        - calculate_recipe_cost
        - calculate_ingredient_cost
        - calculate_ingredient_cost_range
        - convert_with_density
        - get_top_cost_drivers
        - convert_ingredient_to_grams

## `wright.matching`

::: wright.matching
    options:
      members:
        - ItemMatcher
        - ItemPicker
        - PinnedPurchases
        - find_matching_purchases
        - match_all_ingredients
        - cheapest_picker
        - first_picker
        - recent_picker
        - pinned_picker
        - compatible_unit_recent_picker
        - chain

## `wright.planning`

::: wright.planning
    options:
      members:
        - IngredientGroup
        - ShoppingList
        - ShoppingItemWithCost
        - MenuAnalysis
        - generate_shopping_list
        - calculate_shopping_list_cost
        - analyze_menu
        - group_shopping_items
        - normalize_volume_us
        - normalize_volume_to_ml
        - calculate_item_costs
        - estimate_total_items
        - format_quantity

## `wright.pricing`

::: wright.pricing
    options:
      members:
        - margin_price
        - multiplier_price
        - per_serving_price

## `wright.allergens`

::: wright.allergens
    options:
      members:
        - detect_allergens
        - detect_allergens_from_names
        - detect_dietary_properties
        - BADGE_DISPLAY
        - BADGE_IMPLIES
        - DEFAULT_NON_VEGAN_KEYS
        - DEFAULT_DAIRY_KEYS
        - DEFAULT_GLUTEN_KEYS

## `wright.macros`

::: wright.macros
    options:
      members:
        - calculate_recipe_macros

## `wright.supply`

::: wright.supply
    options:
      members:
        - SupplyItem
        - Stock

## `wright.session`

::: wright.session
    options:
      members:
        - ProductionItem
        - ProductionRun
        - convert_recipe_name_to_filename

## `wright.errors`

::: wright.errors
    options:
      members:
        - RecipeCoreError
        - IngredientNotFoundError
        - RecipeLoadError
        - PurchaseLoadError
        - UnitConversionError
        - RecipeCostErrors

## `wright.units`

::: wright.units
    options:
      members:
        - ureg
        - parse_quantity
        - are_compatible
        - DISCRETE_UNITS
        - PINCH_UNITS
        - WEIGHT_UNITS
        - VOLUME_UNITS

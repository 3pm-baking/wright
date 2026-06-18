# API Reference

## `wright.models`

::: wright.models
    options:
      members:
        - BaseIngredient
        - BaseRecipe
        - RecipeComponent
        - ServingRange
        - PurchasedItem
        - SimplePurchase
        - NutritionInfo
        - MacroPerServing
        - RecipeMacros
        - NutritionRegistry
        - FoodRecord
        - PriceRange
        - IngredientCost
        - RecipeCost
        - CategoryRule
        - categorize_ingredient
        - DEFAULT_CATEGORY_RULES
        - Servings

## `wright.costing`

::: wright.costing
    options:
      members:
        - calculate_recipe_cost
        - calculate_ingredient_cost
        - calculate_ingredient_cost_range
        - convert_with_density
        - get_top_cost_drivers
        - ingredient_to_grams

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
        - ShoppingItem
        - IngredientGroup
        - ShoppingList
        - ShoppingItemWithCost
        - MenuAnalysis
        - generate_shopping_list
        - add_costs_to_shopping_list
        - analyze_menu
        - group_shopping_items
        - normalize_volume_for_grocery
        - normalize_volume_to_ml
        - cost_items
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
        - Supply
        - subtract_supply
        - supply_add
        - supply_deduct

## `wright.session`

::: wright.session
    options:
      members:
        - ProductionItem
        - ProductionRun
        - combine_production_runs
        - recipe_name_to_filename

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
        - convert_quantity
        - are_compatible
        - DISCRETE_UNITS
        - PINCH_UNITS
        - WEIGHT_UNITS
        - VOLUME_UNITS

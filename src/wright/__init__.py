"""wright — Pure library for recipe modeling, cost calculation, and planning.

Data-source agnostic.  Populate models from YAML, JSON, a database, or pure Python.
Subclass to add domain-specific metadata (pricing, translations, etc.).
"""

from wright.allergens import (
    DEFAULT_DAIRY_KEYS,
    DEFAULT_GLUTEN_KEYS,
    DEFAULT_NON_VEGAN_KEYS,
    detect_allergens,
    detect_allergens_from_names,
    detect_dietary_properties,
)
from wright.costing import (
    calculate_ingredient_cost,
    calculate_ingredient_cost_range,
    calculate_recipe_cost,
    convert_with_density,
    get_top_cost_drivers,
    ingredient_to_grams,
)
from wright.errors import (
    PurchaseLoadError,
    IngredientNotFoundError,
    RecipeCoreError,
    RecipeCostErrors,
    RecipeLoadError,
    UnitConversionError,
)
from wright.macros import calculate_recipe_macros
from wright.loader import (
    list_recipe_files,
    load_base_recipe,
    load_density_data,
    load_purchases,
    load_nutrition_registry,
    load_supplies,
    load_yaml_file,
)
from wright.matching import (
    ItemMatcher,
    ItemPicker,
    PinnedPurchases,
    chain,
    cheapest_picker,
    compatible_unit_recent_picker,
    find_matching_purchases,
    first_picker,
    match_all_ingredients,
    pinned_picker,
    recent_picker,
)
from wright.models import (
    DEFAULT_CATEGORY_RULES,
    BaseIngredient,
    BaseRecipe,
    CategoryRule,
    FoodRecord,
    PurchasedItem,
    IngredientCost,
    MacroPerServing,
    NutritionInfo,
    PriceRange,
    RecipeComponent,
    RecipeCost,
    RecipeMacros,
    ServingRange,
    Servings,
    SimplePurchase,
    categorize_ingredient,
)
from wright.supply import (
    Supply,
    SupplyItem,
    subtract_supply,
    supply_add,
    supply_deduct,
)
from wright.planning import (
    IngredientGroup,
    MenuAnalysis,
    ShoppingItem,
    ShoppingItemWithCost,
    ShoppingList,
    add_costs_to_shopping_list,
    analyze_menu,
    cost_items,
    estimate_total_items,
    format_quantity,
    generate_shopping_list,
    group_shopping_items,
    normalize_volume_for_grocery,
    normalize_volume_to_ml,
)
from wright.pricing import (
    margin_price,
    multiplier_price,
    per_serving_price,
)
from wright.session import (
    ProductionItem,
    ProductionRun,
    combine_production_runs,
    recipe_name_to_filename,
)
from wright.units import (
    DISCRETE_UNITS,
    PINCH_UNITS,
    VOLUME_UNITS,
    WEIGHT_UNITS,
    are_compatible,
    convert_quantity,
    parse_quantity,
    ureg,
)

__all__ = [
    # Models
    "BaseIngredient",
    "BaseRecipe",
    "CategoryRule",
    "DEFAULT_CATEGORY_RULES",
    "FoodRecord",
    "PurchasedItem",
    "IngredientCost",
    "PriceRange",
    "RecipeComponent",
    "RecipeCost",
    "ServingRange",
    "Servings",
    "SimplePurchase",
    "categorize_ingredient",
    # Errors
    "PurchaseLoadError",
    "IngredientNotFoundError",
    "RecipeCoreError",
    "RecipeCostErrors",
    "RecipeLoadError",
    "UnitConversionError",
    # Units
    "DISCRETE_UNITS",
    "PINCH_UNITS",
    "VOLUME_UNITS",
    "WEIGHT_UNITS",
    "are_compatible",
    "convert_quantity",
    "parse_quantity",
    "ureg",
    # Matching
    "chain",
    "cheapest_picker",
    "compatible_unit_recent_picker",
    "find_matching_purchases",
    "first_picker",
    "ItemMatcher",
    "ItemPicker",
    "match_all_ingredients",
    "pinned_picker",
    "PinnedPurchases",
    "recent_picker",
    # Costing
    "calculate_ingredient_cost",
    "calculate_ingredient_cost_range",
    "calculate_recipe_cost",
    "convert_with_density",
    "get_top_cost_drivers",
    "ingredient_to_grams",
    # Pricing
    "margin_price",
    "multiplier_price",
    "per_serving_price",
    # Macros
    "calculate_recipe_macros",
    # Models
    "MacroPerServing",
    "NutritionInfo",
    "RecipeMacros",
    # Allergens
    "DEFAULT_DAIRY_KEYS",
    "DEFAULT_GLUTEN_KEYS",
    "DEFAULT_NON_VEGAN_KEYS",
    "detect_allergens",
    "detect_allergens_from_names",
    "detect_dietary_properties",
    # Session
    "ProductionItem",
    "ProductionRun",
    "combine_production_runs",
    "recipe_name_to_filename",
    # Planning
    "IngredientGroup",
    "MenuAnalysis",
    "ShoppingItem",
    "ShoppingItemWithCost",
    "ShoppingList",
    "add_costs_to_shopping_list",
    "analyze_menu",
    "cost_items",
    "estimate_total_items",
    "format_quantity",
    "generate_shopping_list",
    "group_shopping_items",
    "normalize_volume_for_grocery",
    "normalize_volume_to_ml",
    # Loader (optional YAML convenience)
    "list_recipe_files",
    "load_base_recipe",
    "load_density_data",
    "load_purchases",
    "load_nutrition_registry",
    "load_supplies",
    "load_yaml_file",
    # Supply
    "Supply",
    "SupplyItem",
    "supply_add",
    "supply_deduct",
    "subtract_supply",
]

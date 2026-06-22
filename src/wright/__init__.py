"""wright — Pure library for recipe modeling, cost calculation, and planning.

Data-source agnostic.  Populate models from YAML, JSON, a database, or pure Python.
Subclass to add domain-specific metadata (pricing, translations, etc.).
"""

from importlib.metadata import version as _version

try:
    __version__ = _version("wright-core")
except Exception:
    __version__ = "0.0.0"

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
    convert_ingredient_to_grams,
    convert_with_density,
    get_top_cost_drivers,
)
from wright.errors import (
    IngredientNotFoundError,
    PurchaseLoadError,
    RecipeCoreError,
    RecipeCostErrors,
    RecipeLoadError,
    UnitConversionError,
)
from wright.loader import (
    list_recipe_files,
    load_base_recipe,
    load_density_data,
    load_nutrition_registry,
    load_purchases,
    load_supplies,
    load_yaml_file,
)
from wright.macros import calculate_recipe_macros
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
    Assembly,
    BaseIngredient,
    BaseRecipe,
    CategoryRule,
    Component,
    DensityData,
    FoodRecord,
    Ingredient,
    IngredientCost,
    MacroPerServing,
    Material,
    NutritionInfo,
    NutritionRegistry,
    PriceRange,
    Purchase,
    PurchasedItem,
    Recipe,
    RecipeComponent,
    RecipeCost,
    RecipeMacros,
    ServingRange,
    Servings,
    VolumeWeightConversions,
    categorize_item,
)
from wright.planning import (
    IngredientGroup,
    MenuAnalysis,
    ShoppingItemWithCost,
    ShoppingList,
    analyze_menu,
    calculate_item_costs,
    calculate_shopping_list_cost,
    estimate_total_items,
    format_quantity,
    generate_shopping_list,
    group_shopping_items,
    normalize_metric,
    normalize_volume_to_ml,
    normalize_volume_us,
)
from wright.pricing import (
    margin_price,
    multiplier_price,
    per_serving_price,
)
from wright.session import (
    ProductionItem,
    ProductionRun,
    convert_name_to_filename,
)
from wright.supply import (
    Stock,
    SupplyItem,
)
from wright.units import (
    DISCRETE_UNITS,
    PINCH_UNITS,
    VOLUME_UNITS,
    WEIGHT_UNITS,
    are_compatible,
    parse_quantity,
    ureg,
)

__all__ = [
    # Version
    "__version__",
    # Models
    "Assembly",
    "BaseIngredient",
    "BaseRecipe",
    "CategoryRule",
    "Component",
    "DEFAULT_CATEGORY_RULES",
    "DensityData",
    "FoodRecord",
    "Ingredient",
    "IngredientCost",
    "MacroPerServing",
    "Material",
    "NutritionInfo",
    "NutritionRegistry",
    "PriceRange",
    "Purchase",
    "PurchasedItem",
    "Recipe",
    "RecipeComponent",
    "RecipeCost",
    "RecipeMacros",
    "ServingRange",
    "Servings",
    "VolumeWeightConversions",
    "categorize_item",
    # Errors
    "IngredientNotFoundError",
    "PurchaseLoadError",
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
    "convert_ingredient_to_grams",
    "convert_with_density",
    "get_top_cost_drivers",
    # Pricing
    "margin_price",
    "multiplier_price",
    "per_serving_price",
    # Nutrition & Macros
    "calculate_recipe_macros",
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
    "convert_name_to_filename",
    # Planning
    "analyze_menu",
    "calculate_item_costs",
    "calculate_shopping_list_cost",
    "estimate_total_items",
    "format_quantity",
    "generate_shopping_list",
    "group_shopping_items",
    "IngredientGroup",
    "MenuAnalysis",
    "ShoppingItemWithCost",
    "ShoppingList",
    "normalize_metric",
    "normalize_volume_to_ml",
    "normalize_volume_us",
    # Loader
    "list_recipe_files",
    "load_base_recipe",
    "load_density_data",
    "load_nutrition_registry",
    "load_purchases",
    "load_supplies",
    "load_yaml_file",
    # Supply
    "Stock",
    "SupplyItem",
]

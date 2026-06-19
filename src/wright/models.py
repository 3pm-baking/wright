"""Pydantic data models for recipe definition, costing, and categorization.

All models are data-source agnostic — no file I/O, no database assumptions.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, Field, field_validator, model_validator

# Lazy import for type annotation only
# (actual import occurs when models are used, not at module level)


# ---------------------------------------------------------------------------
# PurchasedItem protocol — any object with these attributes satisfies it
# ---------------------------------------------------------------------------


class PurchasedItem(Protocol):
    """Protocol for grocery price data used in cost calculations.

    Any object with these attributes and methods satisfies the protocol.
    This allows the library to work with SQLModel ORM objects, plain
    dataclasses, namedtuples, or Pydantic models — no adapter needed.
    """

    name: str
    tags: str
    quantity: float
    unit: str
    price: Decimal
    store: str | None
    purchased_date: date | None

    @property
    def tag_set(self) -> set[str]:
        """Parse comma-separated tags into a set (lowercase)."""
        ...

    def matches_requirements(self, require_tags: list[str]) -> bool:
        """Check if this item satisfies all required tags.

        If require_tags is empty, returns True (matches any item).
        """
        ...


class Purchase(BaseModel):
    """Concrete item for getting started without writing custom classes."""

    name: str = Field(..., description="Ingredient name (e.g. 'Rolled Oats')")
    brand: str | None = Field(default=None, description="Brand name")
    tags: str = Field(
        default="",
        description="Comma-separated tags (e.g. 'organic,gluten-free')",
    )
    quantity: float = Field(..., description="Package quantity")
    unit: str = Field(..., description="Package unit (g, lb, each, etc.)")
    price: Decimal = Field(..., description="Price in local currency")
    store: str | None = Field(default=None, description="Store name")
    purchased_date: date | None = Field(default=None, description="Date of purchase")

    @property
    def tag_set(self) -> set[str]:
        """Parse tags into a set of lowercase strings."""
        if not self.tags:
            return set()
        return {t.strip().lower() for t in self.tags.split(",") if t.strip()}

    def matches_requirements(self, require_tags: list[str]) -> bool:
        """Check if this item satisfies all required tags."""
        if not require_tags:
            return True
        item_tags = self.tag_set
        return all(tag.lower() in item_tags for tag in require_tags)


# ---------------------------------------------------------------------------
# Core BOM models — domain-agnostic
# ---------------------------------------------------------------------------


class Material(BaseModel):
    """A bill-of-materials item for any domain (food, construction, etc.).

    Use :class:`Ingredient` for food-specific contexts, or subclass
    ``Material`` directly for non-food domains (e.g., ``Lumber``,
    ``Hardware``, ``Paint``).
    """

    name: str = Field(..., description="Item name (exact match to purchase data)")
    quantity: float = Field(..., description="Amount needed")
    unit: str = Field(..., description="Unit of measurement (g, lb, ft, each, etc.)")
    require_tags: list[str] = Field(
        default_factory=list,
        description="Required variant tags (e.g., ['organic', 'pressure-treated'])",
    )
    equivalent_quantity: float | None = Field(
        default=None,
        description=(
            "Equivalent quantity in base units "
            "(e.g., 500 for '1 box = 500 each')"
        ),
    )
    equivalent_unit: str | None = Field(
        default=None,
        description="Base unit for equivalence (e.g., 'each')",
    )
    byproduct: bool = Field(
        default=False,
        description=(
            "If True, this item is a byproduct/partial use of another "
            "item already listed elsewhere. Excluded from shopping lists "
            "and cost calculation."
        ),
    )
    product_ref: str | None = Field(
        default=None,
        description=(
            "Reference to another assembly/recipe used for recursive expansion. "
            "When set, this item's quantity is expanded into the referenced "
            "assembly's materials instead of being looked up directly."
        ),
    )

    def scale(self, factor: float) -> Material:
        """Return a new Material with quantity scaled by the given factor."""
        return Material(
            name=self.name,
            quantity=self.quantity * factor,
            unit=self.unit,
            require_tags=self.require_tags,
            equivalent_quantity=self.equivalent_quantity,
            equivalent_unit=self.equivalent_unit,
            byproduct=self.byproduct,
            product_ref=self.product_ref,
        )

    def __mul__(self, factor: float) -> Material:
        if not isinstance(factor, int | float):
            return NotImplemented
        return self.scale(factor)

    def __rmul__(self, factor: float) -> Material:
        return self * factor


class Ingredient(Material):
    """A food ingredient used in a recipe.

    Inherits all fields from :class:`Material`.  Subclass in your
    application layer to add domain-specific metadata (vendor,
    nutrition, etc.).
    """

    def scale(self, factor: float) -> Ingredient:
        """Return a new Ingredient with quantity scaled by the given factor."""
        return Ingredient(
            name=self.name,
            quantity=self.quantity * factor,
            unit=self.unit,
            require_tags=self.require_tags,
            equivalent_quantity=self.equivalent_quantity,
            equivalent_unit=self.equivalent_unit,
            byproduct=self.byproduct,
            product_ref=self.product_ref,
        )


class Component(BaseModel):
    """A domain-agnostic named group of materials.

    For food domains, use :class:`RecipeComponent` (which adds an
    ``ingredients`` alias).  For non-food domains, use ``Component``
    directly or subclass it (e.g., ``WallAssembly``, ``BatchStage``).
    """

    name: str = Field(..., description="Name of this component")
    materials: list[Material] = Field(
        default_factory=list, description="Materials in this component"
    )

    def scale(self, factor: float) -> Component:
        """Return a new Component with all materials scaled."""
        return Component(
            name=self.name,
            materials=[m.scale(factor) for m in self.materials],
        )

    def __mul__(self, factor: float) -> Component:
        if not isinstance(factor, int | float):
            return NotImplemented
        return self.scale(factor)

    def __rmul__(self, factor: float) -> Component:
        return self * factor


class RecipeComponent(Component):
    """A named component or sub-recipe (e.g., 'Chocolate Shortcrust Dough').

    Inherits from :class:`Component`.  The ``ingredients`` property is an
    alias for ``materials``, typed as ``list[Ingredient]`` for food domains.

    Backward-compatible: accepts ``ingredients=`` in the constructor (mapped
    to ``materials=``).
    """

    @model_validator(mode="before")
    @classmethod
    def _map_ingredients_to_materials(cls, data: object) -> object:
        """Accept ``ingredients=`` in the constructor, mapping to ``materials=``."""
        if isinstance(data, dict) and "ingredients" in data:
            data = {**data, "materials": data.pop("ingredients")}  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
        return data

    @property
    def ingredients(self) -> list[Ingredient]:
        """Food-domain alias for :attr:`Component.materials`."""
        return self.materials  # ty:ignore[invalid-return-type]

    @ingredients.setter
    def ingredients(self, value: list[Ingredient]) -> None:
        self.materials = value  # ty:ignore[invalid-assignment]

    def scale(self, factor: float) -> RecipeComponent:
        """Return a new RecipeComponent with all ingredients scaled."""
        return RecipeComponent(
            name=self.name,
            materials=[m.scale(factor) for m in self.materials],
        )


class ServingRange(BaseModel):
    """A range of servings a recipe yields."""

    min_servings: int = Field(..., ge=1, description="Minimum number of servings")
    max_servings: int = Field(..., ge=1, description="Maximum number of servings")

    @property
    def midpoint(self) -> float:
        """Return the midpoint of the serving range."""
        return (self.min_servings + self.max_servings) / 2

    def scale(self, factor: float) -> ServingRange:
        """Return a new ServingRange scaled by the given factor."""
        return ServingRange(
            min_servings=int(self.min_servings * factor),
            max_servings=int(self.max_servings * factor),
        )

    def __mul__(self, factor: float) -> ServingRange:
        if not isinstance(factor, int | float):
            return NotImplemented
        return self.scale(factor)

    def __rmul__(self, factor: float) -> ServingRange:
        return self * factor


Servings = int | ServingRange
"""A recipe yields either an exact number of servings or a range."""


class Assembly(BaseModel):
    """A domain-agnostic collection of components.

    Use ``Assembly`` directly for construction, brewing, manufacturing,
    or any non-food domain.  ``Recipe`` subclasses it with food-specific
    fields like ``prep_time``, ``cook_time``, and ``servings``.

    All planning functions (:func:`~wright.planning.generate_shopping_list`,
    :func:`~wright.planning.analyze_menu`) accept ``Assembly`` — so you can
    use the full pipeline without dummy food fields.
    """

    name: str = Field(..., description="Assembly name (e.g., 'Backyard Deck')")
    components: list[Component] = Field(
        default_factory=list,
        description="Named groups of materials (e.g., framing, surface, footings)",
    )
    description: str | None = Field(
        default=None,
        description="What this assembly is (e.g., '10x12 freestanding deck')",
    )
    tags: list[str] = Field(
        default_factory=list,
        description=(
            "Author-assigned classifications (e.g., 'outdoor', 'weekend-project')."
        ),
    )

    @property
    def all_materials(self) -> list[Material]:
        """Flatten all materials across all components."""
        return [m for comp in self.components for m in comp.materials]

    def size_up(self, factor: float) -> Assembly:
        """Return a new Assembly with all material quantities scaled."""
        return Assembly(
            name=self.name,
            components=[comp.scale(factor) for comp in self.components],
            description=self.description,
            tags=self.tags,
        )

    def __mul__(self, factor: float) -> Assembly:
        if not isinstance(factor, int | float):
            return NotImplemented
        return self.size_up(factor)

    def __rmul__(self, factor: float) -> Assembly:
        return self * factor


class Recipe(Assembly):
    """A complete recipe with components and optional serving information.

    Subclasses :class:`Assembly` with food-specific fields.  Recipes are
    data-source agnostic — populate from YAML, JSON, a database, or pure
    Python.  Subclass to add domain-specific metadata (pricing,
    translations, etc.).
    """

    instructions: list[str] = Field(
        default_factory=list,
        description="Step-by-step preparation instructions",
    )
    prep_time: int = Field(..., description="Preparation time in minutes")
    cook_time: int = Field(..., description="Cooking/baking time in minutes")
    servings: Servings | None = Field(
        default=None,
        description=(
            "Number of servings: an exact int, a ServingRange, or None for "
            "unportioned recipes (products/sub-recipes with only a gram yield)."
        ),
    )
    net_weight_grams: float | None = Field(
        default=None,
        description="Net weight of finished product in grams",
    )

    @property
    def all_ingredients(self) -> list[Ingredient]:
        """Flatten all ingredients across all components."""
        ingredients: list[Ingredient] = []
        for comp in self.components:
            if isinstance(comp, RecipeComponent):
                ingredients.extend(comp.ingredients)
            else:
                ingredients.extend(
                    Ingredient(name=m.name, quantity=m.quantity, unit=m.unit,
                               require_tags=m.require_tags,
                               equivalent_quantity=m.equivalent_quantity,
                               equivalent_unit=m.equivalent_unit,
                               byproduct=m.byproduct,
                               product_ref=m.product_ref)
                    for m in comp.materials
                )
        return ingredients

    @field_validator("servings", mode="before")
    @classmethod
    def _parse_servings(cls, v: object) -> Servings | None:
        """Accept both int and dict (ServingRange) for the servings field."""
        if v is None:
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, dict):
            return ServingRange(**v)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
        return v  # type: ignore[return-value]  # ty:ignore[invalid-return-type]

    def size_up(self, factor: float) -> Recipe:
        """Return a new Recipe with all ingredient quantities scaled."""
        return Recipe(
            name=self.name,
            components=[comp.scale(factor) for comp in self.components],
            instructions=self.instructions,
            prep_time=self.prep_time,
            cook_time=self.cook_time,
            servings=ServingRange(
                min_servings=int(self._servings_bounds()[0] * factor),
                max_servings=int(self._servings_bounds()[1] * factor),
            )
            if isinstance(self.servings, ServingRange)
            else int(self._servings_bounds()[0] * factor)
            if isinstance(self.servings, int)
            else None,
            net_weight_grams=self.net_weight_grams * factor
            if self.net_weight_grams is not None
            else None,
            description=self.description,
            tags=self.tags,
        )

    def double(self) -> Recipe:
        """Return a new Recipe with all ingredient quantities doubled."""
        return self * 2  # type: ignore[return-value]  # ty:ignore[invalid-return-type]

    def _servings_bounds(self) -> tuple[int, int]:
        """Return (min, max) servings for cost calculations."""
        if self.servings is None:
            return 1, 1
        if isinstance(self.servings, int):
            return self.servings, self.servings
        return self.servings.min_servings, self.servings.max_servings


# ---------------------------------------------------------------------------
# Nutrition models
# ---------------------------------------------------------------------------


class NutritionInfo(BaseModel):
    """Nutritional values per 100 grams of an ingredient.

    All nutrient amounts are in grams per 100g of the ingredient,
    except *kcal* which is total energy per 100g.

    If *kcal* is not explicitly provided, it is approximated using
    the Atwater general factor system::

        kcal ≈ protein_g * 4 + carbs_g * 4 + fat_g * 9 + fiber_g * 2
    """

    protein_g: float = Field(default=0, description="Protein in grams per 100g")
    carbs_g: float = Field(default=0, description="Carbohydrates in grams per 100g")
    fat_g: float = Field(default=0, description="Total fat in grams per 100g")
    fiber_g: float = Field(default=0, description="Dietary fiber in grams per 100g")
    kcal: float | None = Field(
        default=None,
        description=(
            "Energy in kilocalories per 100g.  If omitted, approximated "
            "from macros using Atwater factors."
        ),
    )

    @property
    def computed_kcal(self) -> float:
        """Approximate kcal from macros using Atwater general factors."""
        return self.protein_g * 4 + self.carbs_g * 4 + self.fat_g * 9 + self.fiber_g * 2

    @property
    def effective_kcal(self) -> float:
        """Return explicit *kcal* if set, otherwise compute from macros."""
        if self.kcal is not None:
            return self.kcal
        return self.computed_kcal


class MacroPerServing(BaseModel):
    """Macro breakdown for a single serving.

    Supports ``+`` (add), ``*`` (scale), and ``sum()`` via ``.zero()``.
    """

    protein_g: float = Field(..., description="Protein in grams")
    carbs_g: float = Field(..., description="Carbohydrates in grams")
    fat_g: float = Field(..., description="Total fat in grams")
    fiber_g: float = Field(..., description="Dietary fiber in grams")
    kcal: float = Field(..., description="Energy in kilocalories")

    def __add__(self, other: "MacroPerServing") -> "MacroPerServing":
        if not isinstance(other, MacroPerServing):
            return NotImplemented
        return MacroPerServing(
            protein_g=self.protein_g + other.protein_g,
            carbs_g=self.carbs_g + other.carbs_g,
            fat_g=self.fat_g + other.fat_g,
            fiber_g=self.fiber_g + other.fiber_g,
            kcal=self.kcal + other.kcal,
        )

    def __mul__(self, factor: float) -> "MacroPerServing":
        if not isinstance(factor, int | float):
            return NotImplemented
        return MacroPerServing(
            protein_g=self.protein_g * factor,
            carbs_g=self.carbs_g * factor,
            fat_g=self.fat_g * factor,
            fiber_g=self.fiber_g * factor,
            kcal=self.kcal * factor,
        )

    __rmul__ = __mul__

    @classmethod
    def zero(cls) -> "MacroPerServing":
        """Return a zero-valued instance for ``sum(..., start=MacroPerServing.zero())``."""
        return cls(protein_g=0, carbs_g=0, fat_g=0, fiber_g=0, kcal=0)


class RecipeMacros(BaseModel):
    """Total and per-serving macro breakdown for a recipe.

    Supports ``*`` to scale macros by batch quantity.
    """

    recipe_name: str = Field(..., description="Name of the recipe")
    total: MacroPerServing = Field(..., description="Total macros for the full recipe")
    per_serving: MacroPerServing | None = Field(
        default=None,
        description="Macros per serving (None if recipe has no serving info)",
    )
    servings_used: int | None = Field(
        default=None,
        description="Number of servings used for per-serving calculation",
    )

    def __mul__(self, factor: float) -> "RecipeMacros":
        if not isinstance(factor, int | float):
            return NotImplemented
        return RecipeMacros(
            recipe_name=self.recipe_name,
            total=self.total * factor,
            per_serving=self.per_serving * factor if self.per_serving else None,
            servings_used=self.servings_used,
        )

    __rmul__ = __mul__


class FoodRecord(BaseModel):
    """Nutritional data for a single food item, keyed by ingredient name.

    Maps an ingredient name (e.g. ``"Rolled Oats"``) to its per-100g
    nutritional profile.  Designed to be loaded from YAML or populated
    from an external source (USDA, etc.).

    The ``source`` field documents where the data came from (e.g.
    ``"usda-fdc"``, ``"nutritiondata.self.com"``) for auditing.
    """

    ingredient: str = Field(
        ..., description="Ingredient name (exact match to recipe ingredient names)"
    )
    nutrition: NutritionInfo = Field(..., description="Nutritional values per 100g")
    source: str | None = Field(
        default=None,
        description="Data source for traceability (e.g. 'usda-fdc: 123456')",
    )


NutritionRegistry = Mapping[str, NutritionInfo]
"""A mapping of ingredient name → ``NutritionInfo`` per 100g.

The primary source for macro calculation — should cover common ingredients
loaded from YAML, USDA, or other databases.  Passed to
``calculate_recipe_macros()`` as the ``nutrition_registry`` parameter.

Example::

    registry: NutritionRegistry = {
        "Rolled Oats": NutritionInfo(protein_g=13.5, ...),
        "Greek Yogurt": NutritionInfo(protein_g=10.0, ...),
    }
"""


class PriceRange(BaseModel):
    """A price range representing minimum and maximum costs."""

    min_price: Decimal = Field(..., description="Minimum price")
    max_price: Decimal = Field(..., description="Maximum price")

    @property
    def midpoint(self) -> Decimal:
        """Return the midpoint of the price range."""
        return (self.min_price + self.max_price) / 2

    def __add__(self, other: PriceRange) -> PriceRange:
        """Add two price ranges together."""
        return PriceRange(
            min_price=self.min_price + other.min_price,
            max_price=self.max_price + other.max_price,
        )

    def __mul__(self, factor: float) -> PriceRange:
        if not isinstance(factor, int | float):
            return NotImplemented
        return PriceRange(
            min_price=self.min_price * Decimal(str(factor)),
            max_price=self.max_price * Decimal(str(factor)),
        )

    def __rmul__(self, factor: float) -> PriceRange:
        return self * factor


class IngredientCost(BaseModel):
    """Cost breakdown for a single ingredient."""

    ingredient: Ingredient = Field(..., description="The ingredient being costed")
    price_range: PriceRange = Field(
        ..., description="Price range from all matching groceries"
    )
    sources: list[str] = Field(
        ..., description="Source descriptions (e.g., 'Costco Kirkland')"
    )


class RecipeCost(BaseModel):
    """Full cost breakdown for a recipe."""

    recipe_name: str = Field(..., description="Name of the recipe")
    ingredient_costs: list[IngredientCost] = Field(
        ..., description="Cost breakdown per ingredient"
    )
    total_cost_range: PriceRange = Field(..., description="Total recipe cost range")
    cost_per_serving_range: PriceRange = Field(
        ...,
        description="Cost per serving (accounting for serving range)",
    )


# ---------------------------------------------------------------------------
# Backward-compatibility aliases
# ---------------------------------------------------------------------------

BaseIngredient = Ingredient
"""Alias for :class:`Ingredient`.  Provided for subclassing in applications
that import ``from wright.models import BaseIngredient``."""

BaseRecipe = Recipe
"""Alias for :class:`Recipe`.  Provided for subclassing in applications
that import ``from wright.models import BaseRecipe``."""


# ---------------------------------------------------------------------------
# Categorization models
# ---------------------------------------------------------------------------


class CategoryRule(BaseModel):
    """One categorization rule: keywords that map to a store aisle category.

    Rules are evaluated in priority order (lowest first).  When an ingredient
    name contains any keyword from a rule, it is assigned that category.
    """

    category: str = Field(..., description="Category name (e.g., 'Produce')")
    priority: int = Field(
        default=0, description="Evaluation order (lower = checked first)"
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Case-insensitive substring matches",
    )


def categorize_item(
    item_name: str,
    *,
    rules: list[CategoryRule] | None = None,
) -> str | None:
    """Categorize a BOM item based on keyword rules.

    Rules are evaluated in priority order (lowest first).  The first rule
    whose keywords match the item name (case-insensitive substring)
    determines the category.

    Args:
        item_name: Name of the item to categorize (ingredient, material, etc.).
        rules: Optional list of CategoryRule objects.  If None or empty,
            returns None (uncategorized).

    Returns:
        Category name string, or None if no rules matched.
    """
    if not rules:
        return None

    name_lower = item_name.lower()

    for rule in sorted(rules, key=lambda r: r.priority):
        if any(keyword in name_lower for keyword in rule.keywords):
            return rule.category

    return None


categorize_ingredient = categorize_item
""".. deprecated::
    Use :func:`categorize_item` instead.  This alias will be removed in a
    future version.
"""


DEFAULT_CATEGORY_RULES: list[CategoryRule] = [
    CategoryRule(
        category="Pantry",
        priority=0,
        keywords=[
            "brandy",
            "candied",
            "canned",
            "compote",
            "garlic powder",
            "jam",
            "jello",
            "juice",
            "liqueur",
            "nut butter",
            "onion powder",
            "peanut butter",
        ],
    ),
    CategoryRule(
        category="Fats & Oils",
        priority=1,
        keywords=["oil"],
    ),
    CategoryRule(
        category="Produce",
        priority=2,
        keywords=[
            "apple",
            "apricot",
            "avocado",
            "banana",
            "bell pepper",
            "blueberr",
            "carrot",
            "cherr",
            "cucumber",
            "eggplant",
            "fruit",
            "garlic",
            "gooseberr",
            "herb",
            "lemon",
            "mushroom",
            "onion",
            "orange",
            "peach",
            "pear",
            "plum",
            "raspberr",
            "rhubarb",
            "spinach",
            "spring onion",
            "strawberr",
            "vegetable",
            "zucchini",
        ],
    ),
    CategoryRule(
        category="Specialty Items",
        priority=3,
        keywords=["essence"],
    ),
    CategoryRule(
        category="Dairy & Eggs",
        priority=4,
        keywords=[
            "butter",
            "cheese",
            "cream",
            "egg",
            "milk",
            "parmesan",
            "quark",
            "ricotta",
            "sour cream",
            "yogurt",
        ],
    ),
    CategoryRule(
        category="Meat",
        priority=5,
        keywords=["pork", "beef", "chicken", "meat"],
    ),
    CategoryRule(
        category="Dry Goods",
        priority=6,
        keywords=[
            "almond flour",
            "baking powder",
            "baking soda",
            "bread crumbs",
            "cocoa",
            "coconut flake",
            "corn starch",
            "flour",
            "sliced almond",
            "powder",
            "psyllium",
            "salt",
            "semolina",
            "starch",
            "sugar",
            "yeast",
        ],
    ),
    CategoryRule(
        category="Specialty Items",
        priority=7,
        keywords=[
            "almond",
            "bay leaf",
            "cake glaze",
            "chia",
            "chocolate",
            "cinnamon",
            "clove",
            "extract",
            "gelatin",
            "ginger",
            "hazelnut",
            "nutmeg",
            "nuts",
            "pepper",
            "poppy",
            "raisin",
            "spice",
            "vanilla",
            "walnut",
        ],
    ),
    CategoryRule(
        category="Pantry",
        priority=8,
        keywords=["cookie", "honey", "rum", "sauerkraut", "wine"],
    ),
]
"""Default categorization rules based on a US grocery store layout.

Pass your own list to ``categorize_ingredient()`` to match a different
store layout or language.
"""

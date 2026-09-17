"""Application layer for wright: recipe extraction CLI and Python surface.

This package depends on wright; wright must never import it.  The CLI
(``wright_recipes.cli``, exposed as the ``wright-core`` console script)
is the primary interface.  The functions below are the Python surface
for agents and harnesses.

Conventions: machine-readable output (JSON, YAML) goes to stdout,
human-readable output and diagnostics go to stderr, and exit codes are
0 (success), 1 (failure), 2 (bad flags).

Consolidation merges ingredient-name variants ("Kosher salt" and
"table salt" become one "Salt" line) via
:func:`wright_recipes.normalize_ingredient_name` — see
``wright_recipes.names`` for the curated alias map.
"""

from .extract import (
    ExtractionError,
    build_prompt,
    extract_json,
    extract_recipe,
    recipe_to_json,
    recipe_to_yaml,
)
from .fetch import FetchError, fetch_html, fetch_page, page_to_text
from .jsonld import extract_jsonld_recipe, structured_block
from .names import NAME_ALIASES, normalize_ingredient_name, variant_key
from .providers import (
    DEFAULT_MODELS,
    ENV_VARS,
    Provider,
    ProviderError,
    detect_provider,
    make_provider,
    resolve_provider,
)
from .units_display import metric_display

__all__ = [
    # extraction
    "ExtractionError",
    "build_prompt",
    "extract_json",
    "extract_recipe",
    "recipe_to_json",
    "recipe_to_yaml",
    # fetching
    "FetchError",
    "fetch_html",
    "fetch_page",
    "page_to_text",
    # structured data
    "extract_jsonld_recipe",
    "structured_block",
    # name normalization
    "NAME_ALIASES",
    "normalize_ingredient_name",
    "variant_key",
    # providers
    "DEFAULT_MODELS",
    "ENV_VARS",
    "Provider",
    "ProviderError",
    "detect_provider",
    "make_provider",
    "resolve_provider",
    # display
    "metric_display",
]

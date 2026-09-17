"""wright-core CLI: chainable recipe extraction and shopping-list planning.

Three commands, composable with pipes:

    parse  — fetch a recipe web page, extract a validated Recipe (LLM).
             Machine-readable output (JSON, YAML) on stdout.
    scale  — scale a single Recipe deterministically (servings, batches).
             Pure transformation: recipe in, scaled recipe out.
    shop   — turn one or more Recipes into a consolidated shopping list
             (deterministic).  Reads files or stdin; human-readable list
             on stderr, machine-readable plan on stdout.

The seam between parse and shop is deliberate: extraction is
probabilistic, planning is deterministic, and the boundary is where
humans and agents review, tweak, or transform the recipe.

Typical chains:

    # one pipe: URL in, shopping list out
    wright-core parse URL | wright-core shop

    # per-recipe scaling, then consolidation
    wright-core parse URL_A | wright-core scale --servings 24 > a.json
    wright-core parse URL_B | wright-core scale --batches 2 > b.json
    wright-core shop a.json b.json

Errors and diagnostics always go to stderr; stdout is clean data.
Exit codes: 0 success, 1 failure, 2 bad flags.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import typer
import yaml

from wright import (
    DEFAULT_CATEGORY_RULES,
    ProductionItem,
    ProductionRun,
    Recipe,
    ServingRange,
    generate_shopping_list,
    group_shopping_items,
)

from . import fetch
from .extract import ExtractionError, extract_recipe, recipe_to_json, recipe_to_yaml
from .fetch import FetchError, fetch_html, page_to_text
from .jsonld import extract_jsonld_recipe, structured_block
from .names import variant_key
from .providers import ProviderError, resolve_provider
from .units_display import metric_display

app = typer.Typer(
    name="wright-core",
    help="Chainable recipe tools: parse a web page into a Recipe, shop for it.",
    no_args_is_help=True,
)


def _err(msg: str) -> None:
    typer.echo(msg, err=True)


def _split_json_objects(text: str) -> list[str]:
    """Split a stream of concatenated JSON objects into individual texts."""
    decoder = json.JSONDecoder()
    objects: list[str] = []
    idx = 0
    text = text.strip()
    while idx < len(text):
        while idx < len(text) and text[idx] in " \t\r\n":
            idx += 1
        if idx >= len(text):
            break
        _, end = decoder.raw_decode(text, idx)
        objects.append(text[idx:end])
        idx = end
    return objects


def _load_recipe_text(text: str, source: str) -> Recipe:
    """Parse Recipe JSON or YAML from text, with a clear error on failure."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            _err(f"Error: {source} is neither valid JSON nor YAML: {exc}")
            raise typer.Exit(1) from exc
    if not isinstance(data, dict):
        _err(f"Error: {source} does not contain a recipe object.")
        raise typer.Exit(1)
    try:
        return Recipe.model_validate(data)
    except Exception as exc:
        _err(f"Error: {source} is not a valid wright Recipe: {exc}")
        raise typer.Exit(1) from exc


def _load_recipes_from_text(text: str, source: str) -> list[Recipe]:
    """Load one or more recipes from a text blob.

    Accepts a single JSON/YAML recipe, a JSON array of recipes, or
    concatenated JSON objects (e.g. several `parse` runs joined).
    """
    stripped = text.strip()
    if not stripped:
        _err(f"Error: {source} is empty.")
        raise typer.Exit(1)
    if stripped.startswith("["):
        try:
            data = json.loads(stripped)
            if isinstance(data, list):
                return [Recipe.model_validate(item) for item in data]
        except Exception as exc:
            _err(f"Error: {source} is not a valid recipe array: {exc}")
            raise typer.Exit(1) from exc
    chunks = _split_json_objects(stripped) if stripped.startswith("{") else []
    if len(chunks) > 1:
        return [_load_recipe_text(chunk, source) for chunk in chunks]
    return [_load_recipe_text(stripped, source)]


def _read_recipes(paths: tuple[str, ...]) -> list[Recipe]:
    """Load recipes from files, stdin ('-' or no args), or inline JSON."""
    if not paths or paths == ("-",):
        return _load_recipes_from_text(sys.stdin.read(), "stdin")
    recipes = []
    for raw in paths:
        if raw == "-":
            recipes.extend(_load_recipes_from_text(sys.stdin.read(), "stdin"))
            continue
        path = Path(raw)
        if not path.exists():
            _err(f"Error: file not found: {path}")
            raise typer.Exit(1)
        recipes.extend(_load_recipes_from_text(path.read_text(), str(path)))
    return recipes


def _scale_factor(recipe: Recipe, servings: int | None) -> float:
    """Factor to scale *recipe* so it yields *servings* (1.0 if no scaling)."""
    if servings is None:
        return 1.0
    recipe_servings = recipe.servings
    if recipe_servings is None:
        _err(f"Warning: recipe has no serving count; ignoring --servings ({servings}).")
        return 1.0
    base = (
        float(recipe_servings.midpoint)
        if isinstance(recipe_servings, ServingRange)
        else float(recipe_servings)
    )
    return servings / base if base > 0 else 1.0


def _build_plan(
    recipes: list[Recipe],
    servings: int | None,
    units: str,
    batches: int = 1,
):
    """Scale recipes and generate the consolidated shopping list."""
    scaled = []
    for recipe in recipes:
        factor = _scale_factor(recipe, servings)
        scaled.append(recipe.size_up(factor) if factor != 1.0 else recipe)
    session = ProductionRun(
        date=date.today(),
        production=[ProductionItem(assembly=r.name, quantity=batches) for r in scaled],
        target_dates=[date.today()],
    )
    return generate_shopping_list(
        session,
        scaled,
        key_fn=variant_key,
        display_normalizer=metric_display if units == "metric" else None,
    )


def _print_list(shopping) -> None:
    """Human-readable grouped shopping list, on stderr."""
    grouped = group_shopping_items(
        shopping.all_items,
        category_rules=DEFAULT_CATEGORY_RULES,
    )
    width = 62
    divider = "-" * width
    _err("")
    _err("Shopping List".center(width))
    _err(divider)
    _err(f"  Making: {', '.join(shopping.production_summary)}")
    _err("")
    for group in grouped:
        _err(f"  {group.group_name}  ".ljust(width, "-"))
        for item in group.items:
            _err(f"  {item.name:<24s} {item.quantity:>10g} {item.unit}")
        _err("")
    _err(divider)


@app.callback()
def _root() -> None:
    """wright-core CLI (subcommands: parse, scale, shop)."""


@app.command()
def parse(
    url: str = typer.Argument(..., help="URL of the recipe web page."),
    key: str | None = typer.Option(
        None,
        "--key",
        help=(
            "API key. Defaults to OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY."
        ),
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="openai, anthropic, or gemini. Auto-detected from the key or environment.",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Model name. Defaults to a cheap extraction model per provider.",
    ),
    output_format: str = typer.Option(
        "json",
        "--format",
        help="Output format: json (default) or yaml. Recipe goes to stdout.",
    ),
    user_agent: str | None = typer.Option(
        None,
        "--user-agent",
        help=(
            "User-Agent header for fetching. Defaults to a generic browser "
            "UA; override if a site blocks it."
        ),
    ),
    context: str | None = typer.Option(
        None,
        "--context",
        help=(
            "Extra instructions appended to the extraction prompt "
            "(e.g. dietary preferences, ingredient substitutions)."
        ),
    ),
) -> None:
    """Extract a validated Recipe from a recipe web page (stdout).

    This is the probabilistic stage.  Pipe the result into
    'wright-core shop' for the deterministic shopping list, or save it
    to review and tweak first.
    """
    try:
        _, llm = resolve_provider(provider, key, model)
    except ProviderError as exc:
        _err(f"Error: {exc}")
        raise typer.Exit(1) from exc

    try:
        html = fetch_html(url, user_agent=user_agent or fetch.DEFAULT_USER_AGENT)
    except FetchError as exc:
        _err(f"Error: {exc}")
        raise typer.Exit(1) from exc

    page_text = page_to_text(html)
    jsonld_recipe = extract_jsonld_recipe(html)
    structured = structured_block(jsonld_recipe) if jsonld_recipe else None

    try:
        recipe = extract_recipe(
            page_text, llm, structured=structured, extra_context=context
        )
    except ExtractionError as exc:
        _err(f"Error: {exc}")
        raise typer.Exit(1) from exc
    except ProviderError as exc:
        _err(f"Error: {exc}")
        raise typer.Exit(1) from exc

    if output_format == "json":
        typer.echo(recipe_to_json(recipe))
    elif output_format == "yaml":
        typer.echo(recipe_to_yaml(recipe))
    else:
        _err(f"Error: unknown format {output_format!r} (use json or yaml)")
        raise typer.Exit(2)


@app.command()
def shop(
    paths: list[str] = typer.Argument(  # noqa: B008 - typer's declared pattern
        None,
        help=(
            "Recipe files (JSON or YAML), '-' for stdin, or nothing to read "
            "stdin. Multiple files are consolidated into one list."
        ),
    ),
    servings: int | None = typer.Option(
        None,
        "--servings",
        help="Scale every recipe to this many servings.",
    ),
    batches: int = typer.Option(
        1,
        "--batches",
        help="Make every recipe this many times (e.g. --batches 2 doubles it).",
    ),
    units: str = typer.Option(
        "us",
        "--units",
        help="Display units: us (cups/tbsp) or metric (g/ml/kg).",
    ),
    output_format: str = typer.Option(
        "list",
        "--format",
        help="list (human, stderr), json or yaml (plan, stdout).",
    ),
) -> None:
    """Build a consolidated shopping list from one or more Recipes.

    Deterministic: no LLM, no network.  Reads Recipe JSON/YAML from
    files or stdin.  With --format list (default) the grouped list is
    printed to stderr; with json or yaml the consolidated plan goes to
    stdout for further chaining.
    """
    recipes = _read_recipes(tuple(paths) if paths else ())
    if not recipes:
        _err("Error: no recipes provided.")
        raise typer.Exit(1)

    shopping = _build_plan(recipes, servings, units, batches)

    if output_format == "list":
        _print_list(shopping)
    elif output_format == "json":
        typer.echo(
            json.dumps(
                [
                    {
                        "name": item.name,
                        "quantity": item.quantity,
                        "unit": item.unit,
                        "tags": item.tags,
                    }
                    for item in shopping.all_items
                ],
                indent=2,
            )
        )
    elif output_format == "yaml":
        typer.echo(
            yaml.safe_dump(
                [
                    {
                        "name": item.name,
                        "quantity": item.quantity,
                        "unit": item.unit,
                        "tags": item.tags,
                    }
                    for item in shopping.all_items
                ],
                sort_keys=False,
                allow_unicode=True,
            )
        )
    else:
        _err(f"Error: unknown format {output_format!r} (use list, json, or yaml)")
        raise typer.Exit(2)


@app.command()
def scale(
    paths: list[str] = typer.Argument(  # noqa: B008 - typer's declared pattern
        None,
        help=(
            "Recipe files (JSON or YAML), '-' for stdin, or nothing to read "
            "stdin. One scaled recipe per input, on stdout."
        ),
    ),
    servings: int | None = typer.Option(
        None,
        "--servings",
        help="Scale the recipe to this many servings.",
    ),
    batches: int = typer.Option(
        1,
        "--batches",
        help="Multiply the recipe this many times.",
    ),
    output_format: str = typer.Option(
        "json",
        "--format",
        help="Output format: json (default) or yaml.",
    ),
) -> None:
    """Scale a Recipe deterministically (stdout).

    Pure transformation: no LLM, no network.  Use it before 'shop' when
    different recipes need different scaling — scale each one, then
    consolidate:

        parse URL_A | wright-core scale --servings 24 > a.json
        parse URL_B | wright-core scale --batches 2 > b.json
        wright-core shop a.json b.json
    """
    recipes = _read_recipes(tuple(paths) if paths else ())
    if len(recipes) != 1:
        _err("Error: scale takes exactly one recipe (use shop to consolidate).")
        raise typer.Exit(2)
    recipe = recipes[0]

    factor = _scale_factor(recipe, servings) * batches
    scaled = recipe.size_up(factor) if factor != 1.0 else recipe

    if output_format == "json":
        typer.echo(recipe_to_json(scaled))
    elif output_format == "yaml":
        typer.echo(recipe_to_yaml(scaled))
    else:
        _err(f"Error: unknown format {output_format!r} (use json or yaml)")
        raise typer.Exit(2)


def main() -> None:
    """Entry point for the wright-core console script."""
    app()


if __name__ == "__main__":
    main()

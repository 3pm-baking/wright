"""Extract a validated wright Recipe from page text via an LLM provider.

The extraction contract: the provider is any callable that turns a
prompt into text; wright never imports an LLM SDK.  The model's JSON
is validated against wright's own ``Recipe`` model, with one retry
that feeds the validation error back to the model.

Public surface:

    build_prompt(page, structured, extra_context) — the exact prompt
        the CLI sends; exposed so agents can reuse it.
    extract_recipe(page, provider, structured, extra_context) —
        prompt → validated Recipe, with one retry on validation failure.
    extract_json(text) — pull a JSON object out of model output
        (handles code fences and surrounding prose).
    recipe_to_json / recipe_to_yaml — machine-readable output.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from wright import Recipe

from .providers import Provider

EXTRACTION_PROMPT = """\
Extract the recipe from the following web page into structured JSON.

Rules:
- Keep the units exactly as the recipe writes them (cup, tbsp, tsp,
  each, g, ml, quart, ...). Do not convert, normalize, or force units —
  the downstream library handles unit handling.
- One component per logical section of the recipe (batter, topping, ...).
  If the recipe has no sections, use a single component named "Main".
- Omit optional garnishes and serving suggestions. But an ingredient
  with an alternative ("5 Tbsp rum (or water)") is NOT optional:
  include it under its primary name ("Rum") with the stated quantity.
- Quantities must be numbers, never strings.
- Seasonings with only a vague amount are real ingredients — keep them
  with a sensible assumed quantity and unit, never null:
  "a pinch of nutmeg" -> quantity 1, unit "pinch".
  "Kosher salt" or "salt to taste" -> quantity 1, unit "tsp".
  "a handful of chives" -> quantity 1, unit "each".
  "2 oz. grated Parmesan, plus more for serving" -> quantity 2, unit
  "oz" (ignore the "plus more for serving").
- Use clean, generic ingredient names. Strip qualifiers and purpose
  phrases: "sugar for boiling" is just "Sugar"; "white vinegar for
  boiling" is just "White vinegar". Do not create separate items for
  the same ingredient used in different steps — list it once with the
  total quantity.
- Mixed fractions like "2 1/2 teaspoons" mean 2.5. Read each quantity
  carefully and attach it to the right ingredient, especially in dense
  blocks like "Boil together: 4 cups sugar 4 cups white vinegar 2 cups
  water" where several quantities appear in a row.
- If the same base ingredient appears with and without a variety
  qualifier ("vinegar" and "white vinegar"), merge them under the more
  specific name and sum the quantities.
- Do not include water used for boiling unless it is an ingredient of
  the dish itself.
- If prep or cook time is not stated on the page, omit the field
  (null is fine). Do not guess times.

Shape (components is a LIST of objects, each with name + ingredients):
{{
  "name": "...",
  "components": [
    {{"name": "Main", "ingredients": [
      {{"name": "Flour", "quantity": 2, "unit": "cup"}}
    ]}}
  ],
  "prep_time": 15,
  "cook_time": 60,
  "servings": 8,
  "instructions": ["..."]
}}

{structured_header}
{structured}

Page text:
{page}
{extra_section}
"""

STRUCTURED_HEADER = (
    "Structured recipe data from the page (schema.org JSON-LD) — treat "
    "these ingredient lines as authoritative:"
)

EXTRA_HEADER = "Additional instructions from the caller:"


class ExtractionError(Exception):
    """Raised when the LLM output cannot be validated as a Recipe."""


def extract_json(text: str) -> str:
    """Pull the first JSON object out of model output (handles code fences)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    if fenced:
        return fenced.group(1)
    bare = re.search(r"\{.*\}", text, flags=re.S)
    if bare:
        return bare.group(0)
    raise ExtractionError("No JSON object found in model output.")


def extract_recipe(
    page_text: str,
    provider: Provider,
    structured: str | None = None,
    extra_context: str | None = None,
) -> Recipe:
    """Ask the provider for a Recipe, validating with one retry on failure.

    The retry feeds the pydantic validation error back to the model —
    the agent-in-the-loop pattern.  *structured* is optional JSON-LD
    text (schema.org Recipe) treated as authoritative input.
    *extra_context* is appended to the prompt as caller instructions.
    """
    prompt = build_prompt(page_text, structured, extra_context)
    complete_parsed = getattr(provider, "complete_parsed", None)
    if complete_parsed is not None:
        # Native structured output: the client validates against the
        # schema server-side.  One retry on failure, same as manual.
        try:
            parsed = complete_parsed(prompt, Recipe)
            return (
                parsed
                if isinstance(parsed, Recipe)
                else Recipe.model_validate(parsed.model_dump())
            )
        except Exception as exc:
            retry = (
                f"{prompt}\n\nYour previous attempt failed:\n{exc}\n"
                "Return corrected JSON matching the shape exactly."
            )
            return _validate_manual(provider.complete(retry))
    raw = extract_json(provider.complete(prompt))
    try:
        return Recipe.model_validate_json(raw)
    except ValidationError as exc:
        retry = (
            f"{prompt}\n\nYour previous JSON failed validation:\n{exc}\n"
            "Return corrected JSON matching the shape exactly."
        )
        return _validate_manual(extract_json(provider.complete(retry)))


def _validate_manual(raw: str) -> Recipe:
    """Validate raw JSON text into a Recipe (no retry here)."""
    try:
        return Recipe.model_validate_json(raw)
    except ValidationError as exc:
        raise ExtractionError(
            f"Model output did not validate as a Recipe: {exc}"
        ) from exc


def recipe_to_json(recipe: Recipe) -> str:
    """Machine-readable output for agents."""
    return recipe.model_dump_json(indent=2)


def recipe_to_yaml(recipe: Recipe) -> str:
    """Wright Recipe YAML, drop-in for load_base_recipe users."""
    import yaml

    return yaml.safe_dump(
        json.loads(recipe.model_dump_json()),
        sort_keys=False,
        allow_unicode=True,
    )


def build_prompt(
    page_text: str,
    structured: str | None = None,
    extra_context: str | None = None,
) -> str:
    """Build the extraction prompt (exposed for testing and agents).

    *extra_context* is appended as caller instructions, after the page.
    """
    extra_section = f"\n{EXTRA_HEADER}\n{extra_context}\n" if extra_context else ""
    return EXTRACTION_PROMPT.format(
        page=page_text,
        structured_header=STRUCTURED_HEADER if structured else "",
        structured=structured or "",
        extra_section=extra_section,
    )

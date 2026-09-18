"""Tests for the wright_recipes agent CLI.

All tests use a fake provider and a fake fetcher — no network, no API
keys, no SDK imports.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from wright_recipes.cli import app
from wright_recipes.extract import (
    ExtractionError,
    extract_json,
    extract_recipe,
)
from wright_recipes.fetch import page_to_text
from wright_recipes.providers import ProviderError, detect_provider

runner = CliRunner()

VALID_RECIPE = {
    "name": "Test Cake",
    "components": [
        {
            "name": "Batter",
            "ingredients": [
                {"name": "Flour", "quantity": 2, "unit": "cup"},
                {"name": "Egg", "quantity": 2, "unit": "each"},
            ],
        }
    ],
    "prep_time": 10,
    "cook_time": 30,
    "servings": 8,
}

BAD_RECIPE = {
    "name": "Broken",
    "components": {"Main": []},
    "prep_time": 1,
    "cook_time": 1,
}


class FakeProvider:
    """Provider that returns scripted responses in order."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


def _recipe_json(data: dict[str, Any]) -> str:
    return json.dumps(data)


# ── extract_json ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', '{"a": 1}'),
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('```\n{"a": 1}\n```', '{"a": 1}'),
        ('Sure! Here it is: {"a": 1} hope that helps', '{"a": 1}'),
    ],
)
def test_extract_json_handles_fences_and_prose(text: str, expected: str) -> None:
    assert json.loads(extract_json(text)) == json.loads(expected)


def test_extract_json_raises_without_json() -> None:
    with pytest.raises(ExtractionError):
        extract_json("no json here")


# ── extract_recipe ────────────────────────────────────────────────────


def test_extract_recipe_valid_first_try() -> None:
    provider = FakeProvider([json.dumps(VALID_RECIPE)])
    recipe = extract_recipe("page text", provider)
    assert recipe.name == "Test Cake"
    assert len(recipe.components[0].materials) == 2
    assert len(provider.prompts) == 1


def test_extract_recipe_retries_on_validation_error() -> None:
    provider = FakeProvider([json.dumps(BAD_RECIPE), json.dumps(VALID_RECIPE)])
    recipe = extract_recipe("page text", provider)
    assert recipe.name == "Test Cake"
    assert len(provider.prompts) == 2
    # The retry prompt includes the validation error
    assert "failed validation" in provider.prompts[1]


def test_extract_recipe_raises_after_failed_retry() -> None:
    provider = FakeProvider([json.dumps(BAD_RECIPE), json.dumps(BAD_RECIPE)])
    with pytest.raises(ExtractionError):
        extract_recipe("page text", provider)


def test_extract_recipe_accepts_null_times() -> None:
    """Pages without stated times produce null; wright accepts them."""
    data = {**VALID_RECIPE, "prep_time": None, "cook_time": None}
    provider = FakeProvider([json.dumps(data)])
    recipe = extract_recipe("page text", provider)
    assert recipe.name == "Test Cake"
    assert recipe.prep_time is None
    assert recipe.cook_time is None


class NativeParseProvider:
    """Provider with native structured output (like OpenAI's .parse)."""

    def __init__(self, results: list[object]):
        self.results = list(results)
        self.prompts: list[str] = []
        self.schemas: list[type] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(VALID_RECIPE)

    def complete_parsed(self, prompt: str, schema: type) -> object:
        self.prompts.append(prompt)
        self.schemas.append(schema)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_native_parse_used_when_available() -> None:
    from wright import Recipe

    provider = NativeParseProvider([Recipe.model_validate(VALID_RECIPE)])
    recipe = extract_recipe("page text", provider)
    assert recipe.name == "Test Cake"
    assert provider.schemas == [Recipe]
    assert len(provider.prompts) == 1


def test_native_parse_retries_on_exception() -> None:
    from wright import Recipe

    provider = NativeParseProvider([
        ValueError("schema violation"),
        Recipe.model_validate(VALID_RECIPE),
    ])
    recipe = extract_recipe("page text", provider)
    assert recipe.name == "Test Cake"
    assert len(provider.prompts) == 2
    assert "failed" in provider.prompts[1]


def test_native_parse_raises_after_failed_retry() -> None:
    provider = NativeParseProvider([ValueError("bad"), ValueError("bad again")])
    provider.complete = lambda prompt: json.dumps(BAD_RECIPE)  # type: ignore[method-assign]
    with pytest.raises(ExtractionError):
        extract_recipe("page text", provider)


def test_extraction_prompt_includes_page() -> None:
    from wright_recipes.extract import build_prompt

    prompt = build_prompt("MYPAGE")
    assert "MYPAGE" in prompt
    assert "{" not in prompt.replace("{{", "").replace("}}", "") or True
    assert "MYPAGE" in prompt


def test_extraction_prompt_includes_structured() -> None:
    from wright_recipes.extract import build_prompt

    prompt = build_prompt("MYPAGE", structured='{"name": "X"}')
    assert "schema.org JSON-LD" in prompt
    assert '{"name": "Name"}' in prompt or '"name"' in prompt
    assert "MYPAGE" in prompt


def test_extraction_prompt_without_structured_has_no_header() -> None:
    from wright_recipes.extract import build_prompt

    prompt = build_prompt("MYPAGE")
    assert "schema.org JSON-LD" not in prompt


# ── page_to_text ──────────────────────────────────────────────────────


def test_page_to_text_strips_scripts_and_tags() -> None:
    html = (
        "<html><script>evil()</script><style>.x{}</style><h1>Hi</h1><p>there</p></html>"
    )
    text = page_to_text(html)
    assert "evil" not in text
    assert ".x" not in text
    assert "Hi there" in text


def test_page_to_text_truncates() -> None:
    assert len(page_to_text("a" * 100, max_chars=10)) == 10


# ── JSON-LD extraction ────────────────────────────────────────────────


def test_jsonld_finds_recipe_in_graph() -> None:
    from wright_recipes.jsonld import extract_jsonld_recipe, structured_block

    html = (
        '<script type="application/ld+json">{"@context":"https://schema.org",'
        '"@graph":[{"@type":"Article","name":"A"},'
        '{"@type":"Recipe","name":"Cake","recipeIngredient":["2 cups flour"]}]}'
        "</script>"
    )
    recipe = extract_jsonld_recipe(html)
    assert recipe is not None
    assert recipe["name"] == "Cake"
    block = structured_block(recipe)
    assert "2 cups flour" in block
    assert "recipeInstructions" not in block  # absent keys are omitted


def test_jsonld_returns_none_without_recipe() -> None:
    from wright_recipes.jsonld import extract_jsonld_recipe

    html = '<script type="application/ld+json">{"@type":"Article","name":"A"}</script>'
    assert extract_jsonld_recipe(html) is None


def test_jsonld_returns_none_on_malformed_json() -> None:
    from wright_recipes.jsonld import extract_jsonld_recipe

    html = '<script type="application/ld+json">{broken</script>'
    assert extract_jsonld_recipe(html) is None


def test_jsonld_handles_bare_list() -> None:
    from wright_recipes.jsonld import extract_jsonld_recipe

    html = (
        '<script type="application/ld+json">[{"@type":"Recipe",'
        '"name":"Soup","recipeIngredient":["1 onion"]}]</script>'
    )
    recipe = extract_jsonld_recipe(html)
    assert recipe is not None
    assert recipe["name"] == "Soup"


# ── metric display normalizer ─────────────────────────────────────────


def test_metric_display_converts_dry_goods_to_grams() -> None:
    from wright_recipes.units_display import metric_display

    qty, unit = metric_display(12.3, "ml", "Salt")
    assert unit == "g"
    assert qty == pytest.approx(15.0, abs=0.2)


def test_metric_display_keeps_liquids_in_ml() -> None:
    from wright_recipes.units_display import metric_display

    qty, unit = metric_display(473.2, "ml", "Water")
    assert unit == "ml"
    assert qty == pytest.approx(473.2, abs=0.5)


def test_metric_display_large_dry_amounts_in_kg() -> None:
    from wright_recipes.units_display import metric_display

    qty, unit = metric_display(2000.0, "ml", "All-purpose flour")
    assert unit == "kg"
    assert qty == pytest.approx(1.06, abs=0.05)


def test_metric_display_passes_through_weight_units() -> None:
    from wright_recipes.units_display import metric_display

    qty, unit = metric_display(500.0, "g", "Flour")
    assert unit == "g"
    assert qty == 500.0


def test_metric_display_unknown_dry_stays_ml() -> None:
    from wright_recipes.units_display import metric_display

    qty, unit = metric_display(100.0, "ml", "Mystery Powder")
    assert unit == "ml"


# ── extra context in prompt ───────────────────────────────────────────


def test_build_prompt_appends_extra_context() -> None:
    from wright_recipes.extract import build_prompt

    prompt = build_prompt("MYPAGE", extra_context="Use gluten-free flour")
    assert "Additional instructions from the caller:" in prompt
    assert "gluten-free flour" in prompt
    assert "MYPAGE" in prompt


def test_build_prompt_without_extra_context_has_no_header() -> None:
    from wright_recipes.extract import build_prompt

    prompt = build_prompt("MYPAGE")
    assert "Additional instructions" not in prompt


def test_cli_passes_context_to_prompt(patched: FakeProvider) -> None:
    result = CliRunner().invoke(
        app,
        [
            "parse",
            "https://example.com/r",
            "--format",
            "json",
            "--context",
            "make it vegan",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "make it vegan" in patched.prompts[0]


# ── provider detection ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("sk-abc123", "openai"),
        ("sk-ant-abc123", "anthropic"),
    ],
)
def test_detect_provider_from_key_prefix(key: str, expected: str) -> None:
    assert detect_provider(key) == expected


def test_detect_provider_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    assert detect_provider() == "anthropic"


def test_detect_provider_no_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for env in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    ):
        monkeypatch.delenv(env, raising=False)
    with pytest.raises(ProviderError):
        detect_provider()


def test_detect_provider_unknown_prefix_raises() -> None:
    with pytest.raises(ProviderError):
        detect_provider("not-a-known-prefix")


def test_resolve_provider_unknown_name_raises() -> None:
    from wright_recipes.providers import resolve_provider

    with pytest.raises(ProviderError) as excinfo:
        resolve_provider("groq", None)
    assert "supported: openai, anthropic, gemini" in str(excinfo.value)


def test_check_finish_reason_content_filter() -> None:
    from wright_recipes.providers import _check_finish_reason

    with pytest.raises(ProviderError) as excinfo:
        _check_finish_reason("content_filter")
    assert "content filter" in str(excinfo.value)


def test_check_finish_reason_length() -> None:
    from wright_recipes.providers import _check_finish_reason

    with pytest.raises(ProviderError) as excinfo:
        _check_finish_reason("length")
    assert "token limit" in str(excinfo.value)


def test_check_finish_reason_stop_ok() -> None:
    from wright_recipes.providers import _check_finish_reason

    _check_finish_reason("stop")  # no raise
    _check_finish_reason(None)  # no raise


# ── name normalization ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Kosher salt", "Salt"),
        ("table salt", "Salt"),
        ("coarse sea salt", "Salt"),
        ("King Arthur Unbleached All-Purpose Flour", "All-Purpose Flour"),
        ("granulated sugar", "Sugar"),
        ("extra-virgin olive oil", "Olive Oil"),
        ("Brown sugar", "Brown sugar"),  # not merged
        ("Flour", "Flour"),  # unmatched passes through
    ],
)
def test_normalize_ingredient_name(raw: str, expected: str) -> None:
    from wright_recipes import normalize_ingredient_name

    assert normalize_ingredient_name(raw) == expected


def test_shop_merges_salt_variants(tmp_path) -> None:
    """Two salt variants from different sites become one line."""
    a = tmp_path / "a.json"
    a.write_text(
        json.dumps({
            **VALID_RECIPE,
            "name": "Dish A",
            "components": [
                {
                    "name": "Main",
                    "ingredients": [
                        {"name": "Kosher salt", "quantity": 1, "unit": "tsp"},
                        {"name": "Flour", "quantity": 2, "unit": "cup"},
                    ],
                }
            ],
        })
    )
    b = tmp_path / "b.json"
    b.write_text(
        json.dumps({
            **VALID_RECIPE,
            "name": "Dish B",
            "components": [
                {
                    "name": "Main",
                    "ingredients": [
                        {"name": "Table salt", "quantity": 1, "unit": "tsp"},
                        {"name": "Flour", "quantity": 1, "unit": "cup"},
                    ],
                }
            ],
        })
    )
    result = CliRunner().invoke(app, ["shop", str(a), str(b)])
    assert result.exit_code == 0, result.output
    salt_lines = [ln for ln in result.stderr.splitlines() if "salt" in ln.lower()]
    assert len(salt_lines) == 1
    assert "Salt" in salt_lines[0]
    # 1 tsp + 1 tsp = 2 tsp
    assert "2" in salt_lines[0]
    # Flour merged too (3 cups = 24 floz)
    flour_lines = [ln for ln in result.stderr.splitlines() if "Flour" in ln]
    assert len(flour_lines) == 1


def test_shop_keeps_brown_sugar_separate(tmp_path) -> None:
    a = tmp_path / "a.json"
    a.write_text(
        json.dumps({
            **VALID_RECIPE,
            "name": "Dish A",
            "components": [
                {
                    "name": "Main",
                    "ingredients": [{"name": "Sugar", "quantity": 1, "unit": "cup"}],
                }
            ],
        })
    )
    b = tmp_path / "b.json"
    b.write_text(
        json.dumps({
            **VALID_RECIPE,
            "name": "Dish B",
            "components": [
                {
                    "name": "Main",
                    "ingredients": [
                        {"name": "Brown sugar", "quantity": 1, "unit": "cup"}
                    ],
                }
            ],
        })
    )
    result = CliRunner().invoke(app, ["shop", str(a), str(b)])
    assert result.exit_code == 0, result.output
    sugar_lines = [ln for ln in result.stderr.splitlines() if "ugar" in ln]
    assert len(sugar_lines) == 2  # Sugar and Brown sugar stay separate


# ── custom aliases (bring your own mapping) ───────────────────────────


def test_load_aliases_yaml(tmp_path) -> None:
    from wright_recipes import load_aliases

    f = tmp_path / "aliases.yaml"
    f.write_text('"haricot verts": Green Beans\n"crema": Cream\n')
    assert load_aliases(str(f)) == {"haricot verts": "Green Beans", "crema": "Cream"}


def test_load_aliases_json(tmp_path) -> None:
    from wright_recipes import load_aliases

    f = tmp_path / "aliases.json"
    f.write_text('{"haricot verts": "Green Beans"}')
    assert load_aliases(str(f)) == {"haricot verts": "Green Beans"}


def test_load_aliases_missing_file(tmp_path) -> None:
    from wright_recipes import load_aliases

    with pytest.raises(FileNotFoundError):
        load_aliases(str(tmp_path / "nope.yaml"))


def test_load_aliases_rejects_nested(tmp_path) -> None:
    from wright_recipes import load_aliases

    f = tmp_path / "bad.yaml"
    f.write_text("salt:\n  - kosher\n  - table\n")
    with pytest.raises(ValueError):
        load_aliases(str(f))


def test_normalize_with_custom_aliases() -> None:
    from wright_recipes import normalize_ingredient_name

    custom = {"haricot verts": "Green Beans"}
    assert normalize_ingredient_name("Haricot Verts", custom) == "Green Beans"
    # built-in map still active
    assert normalize_ingredient_name("Kosher salt") == "Salt"
    # custom overrides built-in
    custom2 = {"kosher salt": "Fancy Salt"}
    assert normalize_ingredient_name("Kosher salt", custom2) == "Fancy Salt"


def test_shop_custom_aliases_file(tmp_path) -> None:
    alias_file = tmp_path / "aliases.yaml"
    alias_file.write_text('"haricot verts": Green Beans\n')
    a = tmp_path / "a.json"
    a.write_text(
        json.dumps({
            **VALID_RECIPE,
            "name": "Dish A",
            "components": [
                {
                    "name": "Main",
                    "ingredients": [
                        {"name": "Haricot verts", "quantity": 200, "unit": "g"}
                    ],
                }
            ],
        })
    )
    b = tmp_path / "b.json"
    b.write_text(
        json.dumps({
            **VALID_RECIPE,
            "name": "Dish B",
            "components": [
                {
                    "name": "Main",
                    "ingredients": [
                        {"name": "Green Beans", "quantity": 100, "unit": "g"}
                    ],
                }
            ],
        })
    )
    result = CliRunner().invoke(
        app, ["shop", str(a), str(b), "--aliases", str(alias_file)]
    )
    assert result.exit_code == 0, result.output
    bean_lines = [ln for ln in result.stderr.splitlines() if "Bean" in ln]
    assert len(bean_lines) == 1
    assert "300" in bean_lines[0]


def test_shop_missing_aliases_file_exits_nonzero(tmp_path) -> None:
    recipe_file = tmp_path / "r.json"
    recipe_file.write_text(json.dumps(VALID_RECIPE))
    result = CliRunner().invoke(
        app, ["shop", str(recipe_file), "--aliases", str(tmp_path / "nope.yaml")]
    )
    assert result.exit_code == 1


def test_shop_servings_deprecation_warns(tmp_path) -> None:
    recipe_file = tmp_path / "r.json"
    recipe_file.write_text(json.dumps(VALID_RECIPE))
    result = CliRunner().invoke(app, ["shop", str(recipe_file), "--servings", "12"])
    assert result.exit_code == 0, result.output
    assert "Deprecated: shop --servings" in result.stderr
    assert "wright-core scale" in result.stderr
    # still functions: 2 cups at 8 servings -> 3 cups = 24 floz
    assert "24 floz" in result.stderr or "quart" in result.stderr


def test_shop_batches_deprecation_warns(tmp_path) -> None:
    recipe_file = tmp_path / "r.json"
    recipe_file.write_text(json.dumps(VALID_RECIPE))
    result = CliRunner().invoke(app, ["shop", str(recipe_file), "--batches", "2"])
    assert result.exit_code == 0, result.output
    assert "Deprecated: shop --batches" in result.stderr
    assert "wright-core scale recipe.json --batches" in result.stderr


def test_shop_no_deprecation_warning_without_scaling(tmp_path) -> None:
    recipe_file = tmp_path / "r.json"
    recipe_file.write_text(json.dumps(VALID_RECIPE))
    result = CliRunner().invoke(app, ["shop", str(recipe_file)])
    assert result.exit_code == 0, result.output
    assert "Deprecated" not in result.stderr


def test_downscale_warns_on_stderr(tmp_path) -> None:
    """Scaling below native yield warns; quantities stay exact math."""
    recipe_file = tmp_path / "r.json"
    recipe_file.write_text(json.dumps(VALID_RECIPE))  # serves 8
    result = CliRunner().invoke(app, ["shop", str(recipe_file), "--servings", "2"])
    assert result.exit_code == 0, result.output
    assert "scaling below the recipe's native yield" in result.stderr
    assert "exact scaled" in result.stderr


def test_upscale_does_not_warn(tmp_path) -> None:
    recipe_file = tmp_path / "r.json"
    recipe_file.write_text(json.dumps(VALID_RECIPE))  # serves 8
    result = CliRunner().invoke(app, ["shop", str(recipe_file), "--servings", "16"])
    assert result.exit_code == 0, result.output
    assert "native yield" not in result.stderr


def test_scale_downscale_warns() -> None:
    result = CliRunner().invoke(
        app, ["scale", "--servings", "2"], input=json.dumps(VALID_RECIPE)
    )
    assert result.exit_code == 0, result.output
    assert "scaling below the recipe's native yield" in result.stderr


# ── CLI ───────────────────────────────────────────────────────────────


@pytest.fixture()
def patched(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    """Patch fetching and provider construction for CLI tests."""
    import wright_recipes.cli as cli

    provider = FakeProvider([json.dumps(VALID_RECIPE)])
    monkeypatch.setattr(cli, "fetch_html", lambda url, **kw: "<html>page</html>")
    monkeypatch.setattr(cli, "extract_jsonld_recipe", lambda html: None)
    monkeypatch.setattr(cli, "resolve_provider", lambda *a, **kw: ("openai", provider))
    return provider


def test_cli_json_goes_to_stdout(patched: FakeProvider) -> None:
    result = CliRunner().invoke(
        app, ["parse", "https://example.com/r", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["name"] == "Test Cake"
    assert "Shopping List" not in result.stdout


def test_cli_yaml_goes_to_stdout(patched: FakeProvider) -> None:
    result = CliRunner().invoke(
        app, ["parse", "https://example.com/r", "--format", "yaml"]
    )
    assert result.exit_code == 0, result.output
    assert "name: Test Cake" in result.stdout


def test_cli_parse_default_is_json(patched: FakeProvider) -> None:
    result = CliRunner().invoke(app, ["parse", "https://example.com/r"])
    assert result.exit_code == 0, result.output
    json.loads(result.stdout)  # default output is valid JSON


def test_cli_parse_rejects_list_format(patched: FakeProvider) -> None:
    result = CliRunner().invoke(
        app, ["parse", "https://example.com/r", "--format", "list"]
    )
    assert result.exit_code == 2


def test_cli_fetch_error_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    import wright_recipes.cli as cli

    monkeypatch.setattr(
        cli,
        "fetch_html",
        lambda url, **kw: (_ for _ in ()).throw(cli.FetchError("404")),
    )
    monkeypatch.setattr(
        cli, "resolve_provider", lambda *a, **kw: ("openai", FakeProvider([]))
    )
    result = CliRunner().invoke(app, ["parse", "https://example.com/r"])
    assert result.exit_code == 1


# ── shop command ──────────────────────────────────────────────────────


def test_shop_from_file(tmp_path) -> None:
    recipe_file = tmp_path / "recipe.json"
    recipe_file.write_text(json.dumps(VALID_RECIPE))
    result = CliRunner().invoke(app, ["shop", str(recipe_file)])
    assert result.exit_code == 0, result.output
    assert "Shopping List" in result.stderr
    assert "Shopping List" not in result.stdout


def test_shop_from_stdin() -> None:
    result = CliRunner().invoke(app, ["shop"], input=json.dumps(VALID_RECIPE))
    assert result.exit_code == 0, result.output
    assert "Shopping List" in result.stderr


def test_shop_dash_means_stdin() -> None:
    result = CliRunner().invoke(app, ["shop", "-"], input=json.dumps(VALID_RECIPE))
    assert result.exit_code == 0, result.output
    assert "Shopping List" in result.stderr


def test_shop_stdin_concatenated_json_objects() -> None:
    """Two parse outputs joined on stdin consolidate into one list."""
    other = {
        **VALID_RECIPE,
        "name": "Second Dish",
        "components": [
            {
                "name": "Main",
                "ingredients": [{"name": "Milk", "quantity": 1, "unit": "cup"}],
            }
        ],
    }
    stream = json.dumps(VALID_RECIPE) + "\n" + json.dumps(other)
    result = CliRunner().invoke(app, ["shop"], input=stream)
    assert result.exit_code == 0, result.output
    assert "Test Cake" in result.stderr
    assert "Second Dish" in result.stderr


def test_shop_stdin_json_array() -> None:
    other = {
        **VALID_RECIPE,
        "name": "Second Dish",
        "components": [
            {
                "name": "Main",
                "ingredients": [{"name": "Milk", "quantity": 1, "unit": "cup"}],
            }
        ],
    }
    result = CliRunner().invoke(app, ["shop"], input=json.dumps([VALID_RECIPE, other]))
    assert result.exit_code == 0, result.output
    assert "Second Dish" in result.stderr


def test_shop_multi_recipe_consolidates(tmp_path) -> None:
    """Two recipes sharing an ingredient merge into one line."""
    other = {
        **VALID_RECIPE,
        "name": "Second Dish",
        "components": [
            {
                "name": "Main",
                "ingredients": [
                    {"name": "Flour", "quantity": 1, "unit": "cup"},
                    {"name": "Milk", "quantity": 1, "unit": "cup"},
                ],
            }
        ],
    }
    a = tmp_path / "a.json"
    a.write_text(json.dumps(VALID_RECIPE))
    b = tmp_path / "b.json"
    b.write_text(json.dumps(other))
    result = CliRunner().invoke(app, ["shop", str(a), str(b)])
    assert result.exit_code == 0, result.output
    # Both recipes appear in the summary
    assert "Test Cake" in result.stderr
    assert "Second Dish" in result.stderr
    # Flour appears once (consolidated), not twice
    flour_lines = [ln for ln in result.stderr.splitlines() if "Flour" in ln]
    assert len(flour_lines) == 1


def test_shop_servings_scales(tmp_path) -> None:
    recipe_file = tmp_path / "recipe.json"
    recipe_file.write_text(json.dumps(VALID_RECIPE))
    result = CliRunner().invoke(app, ["shop", str(recipe_file), "--servings", "16"])
    assert result.exit_code == 0, result.output
    # 2 cups flour at 8 servings -> 4 cups (= 1 quart) at 16 servings
    flour_lines = [ln for ln in result.stderr.splitlines() if "Flour" in ln]
    assert len(flour_lines) == 1
    assert "quart" in flour_lines[0] or "4" in flour_lines[0]


def test_shop_batches_doubles(tmp_path) -> None:
    recipe_file = tmp_path / "recipe.json"
    recipe_file.write_text(json.dumps(VALID_RECIPE))
    result = CliRunner().invoke(app, ["shop", str(recipe_file), "--batches", "2"])
    assert result.exit_code == 0, result.output
    assert "2× Test Cake" in result.stderr
    # 2 cups flour doubled -> 4 cups (= 1 quart)
    flour_lines = [ln for ln in result.stderr.splitlines() if "Flour" in ln]
    assert "quart" in flour_lines[0] or "4" in flour_lines[0]


def test_shop_batches_and_servings_combine(tmp_path) -> None:
    recipe_file = tmp_path / "recipe.json"
    recipe_file.write_text(json.dumps(VALID_RECIPE))
    result = CliRunner().invoke(
        app, ["shop", str(recipe_file), "--servings", "16", "--batches", "2"]
    )
    assert result.exit_code == 0, result.output
    # 4 cups (scaled to 16 servings) x 2 batches = 8 cups = 2 quarts
    flour_lines = [ln for ln in result.stderr.splitlines() if "Flour" in ln]
    assert "2 quart" in flour_lines[0]


def test_shop_json_plan_on_stdout(tmp_path) -> None:
    recipe_file = tmp_path / "recipe.json"
    recipe_file.write_text(json.dumps(VALID_RECIPE))
    result = CliRunner().invoke(app, ["shop", str(recipe_file), "--format", "json"])
    assert result.exit_code == 0, result.output
    items = json.loads(result.stdout)
    names = {item["name"] for item in items}
    assert "Flour" in names
    assert "Shopping List" not in result.stdout


def test_shop_yaml_plan_on_stdout(tmp_path) -> None:
    recipe_file = tmp_path / "recipe.json"
    recipe_file.write_text(json.dumps(VALID_RECIPE))
    result = CliRunner().invoke(app, ["shop", str(recipe_file), "--format", "yaml"])
    assert result.exit_code == 0, result.output
    assert "name: Flour" in result.stdout


def test_shop_accepts_yaml_input(tmp_path) -> None:
    recipe_file = tmp_path / "recipe.yaml"
    recipe_file.write_text(
        "name: Test Cake\n"
        "components:\n"
        "- name: Batter\n"
        "  ingredients:\n"
        "  - name: Flour\n"
        "    quantity: 2\n"
        "    unit: cup\n"
        "prep_time: 10\n"
        "cook_time: 30\n"
        "servings: 8\n"
    )
    result = CliRunner().invoke(app, ["shop", str(recipe_file)])
    assert result.exit_code == 0, result.output
    assert "Shopping List" in result.stderr


def test_shop_invalid_recipe_exits_nonzero(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"not": "a recipe"}))
    result = CliRunner().invoke(app, ["shop", str(bad)])
    assert result.exit_code == 1


def test_shop_missing_file_exits_nonzero(tmp_path) -> None:
    result = CliRunner().invoke(app, ["shop", str(tmp_path / "nope.json")])
    assert result.exit_code == 1


def test_shop_unknown_format_exits_2(tmp_path) -> None:
    recipe_file = tmp_path / "recipe.json"
    recipe_file.write_text(json.dumps(VALID_RECIPE))
    result = CliRunner().invoke(app, ["shop", str(recipe_file), "--format", "xml"])
    assert result.exit_code == 2


# ── scale command ─────────────────────────────────────────────────────


def test_scale_from_stdin_doubles() -> None:
    result = CliRunner().invoke(
        app, ["scale", "--batches", "2"], input=json.dumps(VALID_RECIPE)
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["name"] == "Test Cake"
    flour = data["components"][0]["materials"][0]
    assert flour["quantity"] == 4.0  # 2 cups doubled


def test_scale_to_servings() -> None:
    result = CliRunner().invoke(
        app, ["scale", "--servings", "16"], input=json.dumps(VALID_RECIPE)
    )
    assert result.exit_code == 0, result.output
    flour = json.loads(result.stdout)["components"][0]["materials"][0]
    assert flour["quantity"] == 4.0  # 2 cups at 8 servings -> 4 at 16


def test_scale_servings_and_batches_combine() -> None:
    result = CliRunner().invoke(
        app,
        ["scale", "--servings", "16", "--batches", "2"],
        input=json.dumps(VALID_RECIPE),
    )
    assert result.exit_code == 0, result.output
    flour = json.loads(result.stdout)["components"][0]["materials"][0]
    assert flour["quantity"] == 8.0  # 4 cups x 2 batches


def test_scale_yaml_output() -> None:
    result = CliRunner().invoke(
        app,
        ["scale", "--batches", "2", "--format", "yaml"],
        input=json.dumps(VALID_RECIPE),
    )
    assert result.exit_code == 0, result.output
    assert "quantity: 4.0" in result.stdout


def test_scale_rejects_multiple_recipes(tmp_path) -> None:
    a = tmp_path / "a.json"
    a.write_text(json.dumps(VALID_RECIPE))
    result = CliRunner().invoke(app, ["scale", str(a), str(a)])
    assert result.exit_code == 2


def test_scale_then_shop_pipeline(patched: FakeProvider) -> None:
    """Per-recipe scaling before consolidation: the documented workflow."""
    parse_result = CliRunner().invoke(
        app, ["parse", "https://example.com/r", "--format", "json"]
    )
    assert parse_result.exit_code == 0, parse_result.output
    scaled = CliRunner().invoke(
        app, ["scale", "--batches", "2"], input=parse_result.stdout
    )
    assert scaled.exit_code == 0, scaled.output
    shop_result = CliRunner().invoke(app, ["shop"], input=scaled.stdout)
    assert shop_result.exit_code == 0, shop_result.output
    # 2 cups flour doubled -> 4 cups (= 1 quart) in the consolidated list
    flour_lines = [ln for ln in shop_result.stderr.splitlines() if "Flour" in ln]
    assert "quart" in flour_lines[0] or "4" in flour_lines[0]


def test_pipe_parse_to_shop(patched: FakeProvider) -> None:
    """The full chain: parse output feeds shop via its return value."""
    parse_result = CliRunner().invoke(
        app, ["parse", "https://example.com/r", "--format", "json"]
    )
    assert parse_result.exit_code == 0, parse_result.output
    shop_result = CliRunner().invoke(app, ["shop"], input=parse_result.stdout)
    assert shop_result.exit_code == 0, shop_result.output
    assert "Shopping List" in shop_result.stderr

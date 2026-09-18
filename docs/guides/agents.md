---
description: Turn any recipe web page into a validated shopping list with an AI agent. Wright parses recipes (LLM) and plans the grocery list (deterministic, testable) as two chainable steps.
---

# Recipe to Shopping List: Automated Grocery Lists with AI Agents

Automated grocery list generation is one of the most natural agent workflows for wright: point the CLI at any recipe web page, and get back a validated, unit-normalized shopping list.

The key design idea: **the LLM is just another data source.** Wright is a pure library with no LLM dependency. The agent produces a structured `Recipe`, and everything downstream (validation, unit conversion, aggregation, grouping) is deterministic library code.

And the pipeline is deliberately split in two:

> **Extraction is probabilistic; planning is deterministic. Wright makes the boundary explicit** — so you (or an agent) can review, tweak, or transform the recipe between the two steps.

## Quick start

The CLI ships in the `wright-core` distribution with zero LLM dependencies. You bring your own provider SDK and key:

```bash
# One pipe: extract a recipe from any URL, get a shopping list
uvx --with openai wright-core parse https://example.com/recipe | uvx wright-core shop

# Or in two steps, with a human (or agent) in the middle
uvx --with openai wright-core parse https://example.com/recipe > recipe.yaml
$EDITOR recipe.yaml            # tweak names, drop items, fix quantities
uvx wright-core scale recipe.yaml --servings 12 | uvx wright-core shop --units metric
```

Prefer your agent to do it? Install the skills (`wright-recipes` for any food & recipe task, `weekly-meal-plan` for a week of recipes → one consolidated list):

```bash
npx skills add 3pm-baking/wright
```

Real output from a live run (German Nussecken, extracted from platedcravings.com):

```
  Making: 1× Nut Corners Recipe

  Dairy & Eggs ----------------------------------------------
  Eggs                              2 each
  Unsalted butter                  12 floz

  Dry Goods  -------------------------------------------------
  All-purpose flour                20 floz
  Baking powder                     1 tsp
  Brown sugar                       8 floz
  Salt                              1 pinch
  Sugar                             8 tbsp

  Pantry  ----------------------------------------------------
  Apricot jam                       6 tbsp
  Rum                               5 tbsp
```

## The three commands

### `parse` — extraction (probabilistic)

```bash
uvx --with openai wright-core parse https://example.com/recipe            # Recipe JSON on stdout
uvx --with openai wright-core parse URL --format yaml                     # or YAML
```

| Flag | Purpose |
|---|---|
| `--key` | API key. Defaults to `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` (or `GOOGLE_API_KEY`). |
| `--provider` | `openai`, `anthropic`, or `gemini`. Auto-detected from the key prefix (`sk-`, `sk-ant-`, `AIza`) or environment. |
| `--model` | Model name. Defaults to a cheap extraction model per provider. |
| `--context` | Extra instructions appended to the prompt (dietary preferences, substitutions). |
| `--user-agent` | Override the fetch User-Agent if a site blocks the default. |

### `scale` — per-recipe transformation (deterministic, no LLM, no network)

```bash
wright-core scale recipe.yaml --servings 24        # rescale to 24 servings
echo '<recipe-json>' | wright-core scale --batches 2   # double it (stdin)
wright-core scale recipe.yaml --servings 16 --batches 2  # both combine
```

A pure stream transformation: one recipe in, scaled recipe out (JSON by
default, `--format yaml` available). Use it when different recipes need
different scaling; use `shop --servings/--batches` when every recipe
scales the same way.

### `shop` — planning (deterministic, no LLM, no network)

```bash
wright-core shop recipe.yaml                       # grouped list on stderr
wright-core scale recipe.yaml --servings 12 | wright-core shop   # scale, then plan
wright-core shop recipe.yaml --batches 2           # make every recipe twice
wright-core shop a.yaml b.yaml                     # consolidate multiple recipes
wright-core shop - --format json < recipe.json     # machine-readable plan on stdout
```

| Flag | Purpose |
|---|---|
| `--servings` | Scale every recipe to this many servings (uniform — use `scale` for per-recipe control). |
| `--batches` | Make every recipe this many times (`--batches 2` doubles it). Combines with `--servings`. |
| `--units` | Display units: `us` (default, cups/tbsp) or `metric` (g/ml/kg). |
| `--format` | `list` (default, human-readable on stderr), `json` or `yaml` (plan on stdout). |
| `--aliases` | YAML or JSON file with extra ingredient-name mappings (variant -> canonical), merged over the built-in map. |

Reads Recipe JSON/YAML from files or stdin (`-` or no argument). Multiple
inputs are consolidated into one list — two recipes needing flour become
one flour line. Stdin also accepts concatenated JSON objects (several
`parse` runs joined) or a JSON array of recipes.

Scaling below a recipe's native yield produces exact fractional math —
"0.5 can" or "0.57 each" is correct scaled math, not a rounding error.
Interpret in context: some items split fine (half a can), others do
not (a fraction of an egg means "at least one"). The CLI notes this on
stderr when it happens. Prefer `--batches` (whole-recipe multiples)
over fractional serving scaling when a recipe does not halve cleanly.

Consolidation also merges ingredient-name variants ("Kosher salt" and
"table salt" become one `Salt` line) using a built-in alias map. Bring
your own mapping for ingredients wright does not know:

```yaml
# my-aliases.yaml — variant -> canonical
"haricot verts": Green Beans
"prawns": Shrimp
```

```bash
wright-core shop a.yaml b.yaml --aliases my-aliases.yaml
```

Custom entries extend and override the built-in map. In Python, the
same knobs are exposed: `normalize_ingredient_name(name, aliases)`,
`variant_key(material, aliases)`, and `load_aliases(path)`.

### The seam is the point

```bash
# Agent pipeline: extract → transform → plan
uvx --with openai wright-core parse URL | jq '...' | wright-core shop -

# Per-recipe scaling: scale each recipe differently, then consolidate
uvx --with openai wright-core parse URL_A | uvx wright-core scale --servings 24 > a.json
uvx --with openai wright-core parse URL_B | uvx wright-core scale --batches 2 > b.json
uvx wright-core shop a.json b.json

# Weekly planning: consolidate a week of recipes
cat monday.yaml tuesday.yaml wednesday.yaml | wright-core shop
```

Output streams follow the standard convention: machine-readable output (JSON, YAML) goes to stdout, human-readable output and diagnostics go to stderr. Exit codes: 0 success, 1 failure, 2 bad flags. Agents can rely on stdout being clean, parseable data.

## Structured data (JSON-LD) when available

Most recipe sites embed a schema.org `Recipe` object as JSON-LD — clean, machine-readable ingredient lines. When `parse` finds one, it includes it in the prompt as **authoritative** input, which noticeably improves accuracy over stripped page text. Sites without JSON-LD fall back to page text automatically; no flag needed.

## The pipeline

```
recipe web page
      │  fetch + strip to text (+ JSON-LD if present)
      ▼
LLM (structured output, constrained by wright's Recipe schema)
      │  JSON
      ▼
Recipe.model_validate()          ← pydantic validation
      │  (on failure: feed the error back to the model, retry once)
      ▼
── the seam: review, tweak, transform ──
      ▼
generate_shopping_list()         ← pure, deterministic
      ▼
grouped shopping list
```

## Why pydantic validation matters here

Wright's models are pydantic models, and every major LLM client accepts pydantic models as structured-output schemas. That means the same `Recipe` model serves three roles:

1. **Schema**: the LLM's JSON is constrained to wright's shape.
2. **Validation**: malformed output fails loudly, not silently.
3. **Input**: the validated object goes straight into `generate_shopping_list()`.

No parallel "extraction schema" to keep in sync. The validation-retry loop (show the model its own validation error, ask it to fix) is the agent-in-the-loop pattern in about ten lines.

## The core loop, in ~20 lines

The whole pattern is lightweight. Here is the essence of the CLI, stripped of I/O and fallbacks:

```python
from pydantic import ValidationError
from wright import Recipe, generate_shopping_list, ProductionRun, ProductionItem
from wright_recipes.extract import build_prompt, extract_json


def extract_recipe(page: str, llm) -> Recipe:
    """llm(prompt) -> str is any client; wright never imports it."""
    prompt = build_prompt(page)  # rules + shape + optional JSON-LD + context
    raw = extract_json(llm(prompt))  # handles code fences and prose
    try:
        return Recipe.model_validate_json(raw)
    except ValidationError as exc:
        raw = extract_json(
            llm(f"{prompt}\n\nYour JSON failed validation:\n{exc}\nFix it.")
        )
        return Recipe.model_validate_json(raw)


recipe = extract_recipe(page_text, my_llm_client)
session = ProductionRun(
    date=today,
    production=[ProductionItem(assembly=recipe.name, quantity=1)],
    target_dates=[today],
)
shopping = generate_shopping_list(session, [recipe])
```

`build_prompt()` is exposed as a public function so agents can reuse the exact prompt the CLI sends, including the JSON-LD block and caller context. Everything after the LLM call is deterministic: unit normalization, aggregation, grouping. The agent's only job is turning prose into a validated `Recipe`.

## Native structured output

Many clients validate against the pydantic schema server-side, so malformed output never reaches your code. The CLI uses this automatically when the provider offers it:

```python
# OpenAI's native pydantic structured output
completion = client.beta.chat.completions.parse(
    model="gpt-4o",
    response_format=Recipe,  # wright's model IS the schema
    messages=[{"role": "user", "content": prompt}],
)
recipe = completion.choices[0].message.parsed
```

The provider protocol reflects this: a provider may implement `complete_parsed(prompt, schema) -> object` alongside `complete(prompt) -> str`. When it does, extraction uses the native path (with the same one-retry loop on failure); otherwise it falls back to plain completion plus `Recipe.model_validate_json()`. Anthropic and Gemini-compatible endpoints use the fallback path today.

## How this compares

The recipe-to-list space has three kinds of tools. The question that separates them: **where does the unit conversion happen?**

| | Consumer apps (Chomp Shopper, ListAIse, Recipe Genius) | Hobby agents (GitHub) | Paste into ChatGPT | Wright |
|---|---|---|---|---|
| Parsing | Closed, hosted | LLM | LLM | LLM, schema-constrained |
| Unit conversion | Opaque | Inside the LLM | Inside the LLM | **Deterministic library code** |
| Validation | "Review before adding" | Rarely | None | Pydantic + retry loop |
| Scaling | App feature | Ad hoc | Ad hoc | Pure `size_up()` |
| Costing | Store-scraped | Hardcoded | None | Your purchase history |
| Access | Their UI only | Varies | Chat window | Pipe, files, library calls |
| Domains | Food only | Food only | Food only | Food, BOMs, brewing, construction |

Wright is infrastructure, not a product: no meal-planning UI, no grocery-cart automation, no photo parsing. What it gives you is the deterministic core those tools hide — extraction is the only probabilistic step, and everything after it is testable code you can audit, extend, and compose. If you want a pure-parser complement without any LLM, [`recipe-scrapers`](https://github.com/hhursev/recipe-scrapers) is a good companion project.

## FAQ

### How do I convert a recipe website to a grocery list?

```bash
uvx --with openai wright-core parse <recipe-url> | uvx wright-core shop
```

The first call extracts a validated recipe from the page; the second turns it into a consolidated, unit-normalized shopping list.

### Can an LLM parse recipe ingredients reliably?

Not on its own — quantities get misattributed, fractions get mangled, and there is no way to test prose output. Wright's answer is to constrain the LLM to a pydantic schema, validate the result, retry once on failure, and then hand everything after that to deterministic code. Extraction quality still varies by page (pages with schema.org JSON-LD are markedly better), but the planning stage is exact.

### Does this work with schema.org recipe data?

Yes, automatically. When a page embeds JSON-LD `Recipe` data, the CLI feeds those clean ingredient lines to the model as authoritative input. No flag needed.

### Which AI providers are supported?

OpenAI, Anthropic, and Gemini (via its OpenAI-compatible endpoint). You bring your own SDK (`uvx --with openai` or `--with anthropic`) and key. For anything else, implement the one-method `Provider` protocol (`complete(prompt) -> str`).

### How do I double a recipe or scale it to more servings?

`--servings N` rescales the recipe to a serving count (a recipe serving 8, scaled to 16, doubles every quantity). `--batches N` makes the recipe N times as a unit of production ("cook it twice"). They combine: `--servings 16 --batches 2` is "the 16-serving version, made twice".

### Can I use this from an agent?

That is the design. `parse --format json` emits validated JSON on stdout with meaningful exit codes and stderr-only diagnostics, so an agent can chain it: extract, inspect or transform the recipe, then plan. The provider is injectable, and `build_prompt()` / `extract_recipe()` are importable for direct use in an agent harness.

## Extending it

- **Costs**: wire in your purchase history like [`examples/grocery_list.py`](https://github.com/3pm-baking/wright/blob/main/examples/grocery_list.py) (`calculate_shopping_list_cost`).
- **Any LLM client**: the provider protocol is one method (`complete(prompt) -> str`). OpenAI, Anthropic, and Gemini are built in; anything else (Groq, Ollama, a local model) is a few lines away. Wright never sees the client.
- **Other domains**: the same pattern works for any `Assembly`, such as a bill of materials from a parts list page, a brewing grain bill, or a construction materials takeoff.
- **Harness/skill packaging**: the extraction and validation loop is a natural fit for packaging as an agent skill or tool. The LLM call is one function with a pydantic schema, so it drops into any agent harness unchanged.

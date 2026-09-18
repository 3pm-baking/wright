---
name: weekly-meal-plan
description: Build a weekly meal plan and one consolidated shopping list from recipes the user already has, using the wright-core CLI. Parse each recipe URL, scale per day, consolidate into a single grocery list. Does not discover recipes — if the user has not supplied recipe URLs, ask for them or propose candidates and confirm before extracting.
license: MIT
metadata:
  author: 3pm-baking
  version: "0.3.0"
---

# Weekly meal plan with a consolidated shopping list

Turn a set of recipes the user already has into a week plan plus one
consolidated grocery list. Uses the `wright-core` CLI (see the
`wright-recipes` skill for the full library surface).

## Inputs needed

- One or more recipes — as URLs, as JSON/YAML files, or as text the
  agent structures per the Recipe schema (see the `wright-recipes`
  skill; the schema is the contract, the CLI's `parse` is optional)
- Optional: which day each recipe is for, servings per day, batches

## Missing inputs protocol

This skill does not discover recipes. If the user says "plan my week,
I want to make pizza and stir fry" without URLs:

1. Say what is needed: "I need recipe URLs for each dish."
2. Optionally propose candidate URLs from well-known recipe sites
   using your own web-search capability.
3. Confirm the picks with the user before extracting anything.

## Step-by-step

### 1. Extract each recipe

```bash
mkdir -p week && cd week
uvx --with openai wright-core parse URL_MON > mon.json
uvx --with openai wright-core parse URL_TUE > tue.json
```

One `parse` per recipe. Failures are per-recipe — see the playbook
below; skip and substitute rather than blocking the whole plan.

### 2. Scale per day (before consolidation)

Scaling is per-recipe, so do it before `shop`:

```bash
# double the pizza for a party night
uvx wright-core scale tue.json --batches 2 > tue-x2.json
# pancakes for a crowd
uvx wright-core scale sat.json --servings 24 > sat-x24.json
```

When a recipe yields more than you need, prefer whole-batch strategies
(`--batches 1` with planned leftovers) over fractional downscaling.
Downscaled quantities are exact math — some items split fine (half a
can), others do not (a fraction of an egg means "at least one"); the
CLI notes this on stderr. Leftovers are usually the honest answer for
2-person households.

### 3. Consolidate into one shopping list

```bash
uvx wright-core shop mon.json tue-x2.json wed.json sat-x24.json sun.json
```

One list comes out: shared ingredients merge (two recipes needing
flour become one flour line), ingredient-name variants collapse
("Kosher salt" + "table salt" → one `Salt` line). Bring custom
mappings with `--aliases my-aliases.yaml` and metric display with
`--units metric`.

### 4. Present the plan

Show the user:

- The day-by-day plan (dish, source URL, servings/batches)
- The consolidated shopping list, grouped by store section
- Any recipes that failed extraction and the proposed substitutes

## Validation

- Every `parse` and `shop` exits 0; diagnostics are on stderr, data on
  stdout.
- The `shop` summary line lists every recipe included
  ("Making: 1× Bolognese, 2× Pizza Crust, ...") — check it matches the
  plan.
- Spot-check quantities: scaled recipes should show proportionally
  larger amounts.

## Failure playbook

| Symptom | Fix |
|---|---|
| One recipe fails extraction (content filter, 404) | Skip it, tell the user, propose a substitute URL — do not block the plan |
| "No API key found" | Set `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`, or pass `--key` |
| "The 'openai' package is not installed" | Run with `uvx --with openai` |
| Same ingredient on multiple lines | `--aliases FILE` with variant → canonical mappings |
| User wants different servings per day | `scale` each recipe individually before `shop` (uniform `shop --servings` applies to everything) |

## Going further

The CLI is a sliver of wright-core. Cost the week's list against a
purchase history, check allergens across the plan, or analyze
nutrition — all from the library. See the `wright-recipes` skill for
the capability map and PEP 723 script patterns.

## When not to use this skill

- **Finding recipes** — the user provides them; propose candidates only
  with confirmation.
- **Single-recipe tasks** — use `wright-recipes` directly.
- **Photo recipes, cart automation, meal-planning apps** — out of scope.

# Skill style guide

Every SKU plugin's skills follow these rules. `pluginkit validate` enforces the
ones marked **(checked)**.

## Frontmatter

- `name` equals the skill's folder name, kebab-case. **(checked)**
- `description` says *when* to use the skill, starting with "Use when ...". Under 1024 characters. **(checked)**

## Body

- Lead with the rules an agent must never break (for example: never delete a
  Trilio custom resource without the user's confirmation).
- Prefer the SKU's MCP server over raw `kubectl`. Name the MCP tool to call.
- Keep `SKILL.md` under 500 lines; move long reference material into
  `references/*.md` next to it and link to it. **(warned)**
- Show exact commands and resource kinds; don't paraphrase product names.
- No customer names, cluster names or credentials in examples.

## Naming

- Plugin: `trilio-<sku>-<purpose>`, e.g. `trilio-tsr-guide`. **(warned)**
- Skill: `<sku>-<topic>`, e.g. `tsr-guide`, `tsr-failover`.
- MCP server key: `trilio-<sku>`.

## Evals

Each plugin keeps its eval cases in `evals/*.yaml` at the repo root: a prompt
and the behaviours a correct answer must show. Phase 1 gate: all 5 TSR cases pass.

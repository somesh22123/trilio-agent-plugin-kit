# trilio-agent-plugin-kit

Owned by the **platform group**. Part of **Option A (three-repo model)** in the
*Agent Plugins: Repository Structure Proposal*.

| Repo | Owner | Role |
| --- | --- | --- |
| [site-recovery-kubernetes](https://github.com/somesh22123/site-recovery-kubernetes) (one per SKU) | SKU team | The SKU's plugins, MCP server, tests, evals, release |
| **trilio-agent-plugin-kit** (this repo) | Platform group | Generator, shared CI, new-SKU template, skill style guide |
| [trilio-agent-marketplace](https://github.com/somesh22123/trilio-agent-marketplace) | Platform group | One catalog listing every SKU plugin at a released tag |

## What's here

| Path | What it is |
| --- | --- |
| `pluginkit.py` | The generator and CLI (Python 3.9+, PyYAML) |
| `.github/workflows/plugin-ci.yml` | Reusable CI every SKU repo calls: validate, `generate --check`, tests, package |
| `.github/workflows/plugin-release.yml` | Reusable release on a `<plugin>/v<semver>` tag: zip + GitHub release |
| `template/sku-repo/` | What `pluginkit new-sku` copies |
| `docs/skill-style-guide.md` | Rules for writing skills |

## One source in, every agent tool out

A SKU team writes `plugins/<name>/plugin.yaml` (manifest + MCP config) and
`skills/`. `pluginkit generate` writes:

| Target | Files |
| --- | --- |
| `claude-code` | `.claude-plugin/plugin.json`, `.mcp.json` (hooks come from `hooks/hooks.json`) |
| `codex` | `.codex-plugin/plugin.json`, `.mcp.json` |
| `cursor` | `.cursor-plugin/plugin.json`, `mcp.json` |
| `junie` (Phase 3) | `.junie/guidelines.md`, `.junie/mcp/mcp.json` |
| generic agents | `pluginkit package` → `<name>-<version>.zip` with `install.sh` |

`.generated.json` records each generated file's hash. `generate --check` fails
CI if a generated file was edited by hand or `plugin.yaml` changed without
regenerating.

## Commands

```sh
python pluginkit.py new-sku trilio-for-kubernetes --sku t4k --title 'Trilio for Kubernetes' \
    --out ../trilio-for-kubernetes-ai-plugin            # new SKU repo in one command
python pluginkit.py validate <sku-repo>
python pluginkit.py generate [--check] <sku-repo>
python pluginkit.py package <sku-repo>/plugins/<name> --out dist
python pluginkit.py catalog [--check] [--verify] <marketplace-repo>
python pluginkit.py pin <marketplace-repo> <name> <name>/v<version>
```

## Naming rule

A plugin's name is its repo name without `-ai-plugin`. `validate` fails otherwise.

| SKU | Repo | Plugin |
| --- | --- | --- |
| TSR-K | `site-recovery-kubernetes-ai-plugin` | `site-recovery-kubernetes` |
| TSR-O | `site-recovery-openstack-ai-plugin` | `site-recovery-openstack` |
| T4K | `trilio-for-kubernetes-ai-plugin` | `trilio-for-kubernetes` |
| T4O | `trilio-for-openstack-ai-plugin` | `trilio-for-openstack` |

The name is what customers install (`<name>@trilio`) and the prefix of every
skill (`/<name>:<skill>`), so it should not change after launch.

## Versioning

The kit is released as `vX.Y.Z` tags. SKU repos pin an exact tag in their CI
workflow, so a kit change never reaches a SKU until that SKU bumps its pin.
`plugin-ci` warns when the pin is two or more releases behind.

## Tests

```sh
pip install pyyaml
python -m unittest discover -s tests -v
```

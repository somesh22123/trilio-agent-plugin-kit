# {{repo}}

The {{plugin_name}} agent plugin for {{title}}, owned by the {{SKU}} team. Built with
[trilio-agent-plugin-kit](https://github.com/{{owner}}/trilio-agent-plugin-kit) {{kit_version}}.

## Layout

| Path | What it is |
| --- | --- |
| `plugins/{{plugin_name}}/plugin.yaml` | Portable source: manifest and MCP config. **Edit this.** |
| `plugins/{{plugin_name}}/skills/` | Skills, shared by every agent tool |
| `plugins/{{plugin_name}}/.claude-plugin/`, `.codex-plugin/`, `.cursor-plugin/`, `.mcp.json`, `mcp.json` | Generated. CI fails if edited by hand |
| `mcp-server/` | The {{SKU}} MCP server |
| `evals/` | Eval cases |
| `tests/` | Unit tests, run by CI |

## Workflow

```sh
git clone https://github.com/{{owner}}/trilio-agent-plugin-kit .pluginkit -b {{kit_version}}
python .pluginkit/pluginkit.py validate .
python .pluginkit/pluginkit.py generate .        # after editing plugin.yaml or skills
```

Release by bumping `version` in `plugin.yaml` and tagging `{{plugin_name}}/v<version>`.
The release workflow builds the zip and GitHub release; then the platform group
pins the tag in [trilio-agent-marketplace](https://github.com/{{owner}}/trilio-agent-marketplace).

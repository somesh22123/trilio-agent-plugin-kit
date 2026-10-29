#!/usr/bin/env python3
"""trilio-agent-plugin-kit: one portable plugin source in, every agent tool's files out.

Subcommands:
  generate  [--check] ROOT          write (or verify) per-tool files for every plugin under ROOT/plugins
  validate  ROOT                    lint plugin sources, skills, hooks and evals
  package   PLUGIN_DIR --out DIR    build the generic-agent zip (plugin + install.sh)
  catalog   [--check] [--verify] ROOT   build (or verify) marketplace files from ROOT/catalog.yaml
  pin       ROOT NAME REF           point a catalog entry at REF and record the commit sha
  new-sku   NAME --sku CODE --title T --out DIR   scaffold a new SKU repo from template/sku-repo

Requires Python 3.9+ and PyYAML.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import yaml

KIT_DIR = Path(__file__).resolve().parent
KIT_VERSION = (KIT_DIR / "VERSION").read_text().strip()

TARGETS = ("claude-code", "codex", "cursor", "junie")
GENERATED_INDEX = ".generated.json"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# Naming rule: plugin name = its repo name without this suffix,
# e.g. trilio-for-kubernetes in trilio-for-kubernetes-agent-plugin.
REPO_SUFFIX = "-agent-plugin"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
REQUIRED_FIELDS = ("name", "version", "description", "author", "targets")


class KitError(Exception):
    pass


# ---------------------------------------------------------------------------
# Plugin source
# ---------------------------------------------------------------------------

def load_plugin(plugin_dir):
    src = plugin_dir / "plugin.yaml"
    with src.open() as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("targets", list(TARGETS[:3]))
    data.setdefault("mcpServers", {})
    return data


def find_plugins(root):
    plugins_dir = Path(root) / "plugins"
    if not plugins_dir.is_dir():
        raise KitError(f"{plugins_dir} not found")
    found = sorted(p.parent for p in plugins_dir.glob("*/plugin.yaml"))
    if not found:
        raise KitError(f"no plugins/*/plugin.yaml under {root}")
    return found


def _common_manifest(p):
    out = {
        "name": p["name"],
        "version": p["version"],
        "description": p["description"],
        "author": p["author"],
    }
    for key in ("homepage", "repository", "license", "keywords"):
        if key in p:
            out[key] = p[key]
    return out


def _json(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def render(plugin_dir, p):
    """Return {relative path: file content} for every generated file of one plugin."""
    files = {}
    mcp = {"mcpServers": p["mcpServers"]}
    has_mcp = bool(p["mcpServers"])
    has_hooks = (plugin_dir / "hooks" / "hooks.json").is_file()

    if "claude-code" in p["targets"]:
        m = _common_manifest(p)
        if "displayName" in p:
            m["displayName"] = p["displayName"]
        files[".claude-plugin/plugin.json"] = _json(m)
        if has_mcp:
            files[".mcp.json"] = _json(mcp)

    if "codex" in p["targets"]:
        m = _common_manifest(p)
        m["skills"] = "./skills/"
        if has_mcp:
            m["mcpServers"] = "./.mcp.json"
            files[".mcp.json"] = _json(mcp)
        codex = p.get("codex", {})
        m["interface"] = {
            "displayName": p.get("displayName", p["name"]),
            "shortDescription": p["description"],
            "developerName": p["author"].get("name", ""),
            "category": p.get("category", "Developer Tools"),
            "capabilities": codex.get("capabilities", ["Interactive"]),
            "defaultPrompt": codex.get("defaultPrompt", [])[:3],
        }
        files[".codex-plugin/plugin.json"] = _json(m)

    if "cursor" in p["targets"]:
        m = _common_manifest(p)
        if "displayName" in p:
            m["displayName"] = p["displayName"]
        m["skills"] = "./skills/"
        if (plugin_dir / "agents").is_dir():
            m["agents"] = "./agents/"
        files[".cursor-plugin/plugin.json"] = _json(m)
        if has_mcp:
            files["mcp.json"] = _json(mcp)

    if "junie" in p["targets"]:
        # Junie reads project-level guidelines and MCP config; the IDE plugin lands in Phase 3.
        lines = [f"# {p.get('displayName', p['name'])}", "", p["description"], ""]
        for skill in sorted((plugin_dir / "skills").glob("*/SKILL.md")):
            fm, _ = read_frontmatter(skill)
            lines.append(f"- **{fm.get('name', skill.parent.name)}**: {fm.get('description', '')}")
            lines.append(f"  See skills/{skill.parent.name}/SKILL.md")
        files[".junie/guidelines.md"] = "\n".join(lines) + "\n"
        if has_mcp:
            files[".junie/mcp/mcp.json"] = _json(mcp)

    index = {
        "generator": f"trilio-agent-plugin-kit {KIT_VERSION}",
        "note": "Generated from plugin.yaml. Do not edit these files by hand; run pluginkit generate.",
        "files": {path: hashlib.sha256(body.encode()).hexdigest() for path, body in sorted(files.items())},
    }
    files[GENERATED_INDEX] = _json(index)
    return files


def cmd_generate(args):
    drift = []
    for plugin_dir in find_plugins(args.root):
        p = load_plugin(plugin_dir)
        files = render(plugin_dir, p)

        # Files listed in the previous index but no longer produced are stale.
        stale = []
        old_index = plugin_dir / GENERATED_INDEX
        if old_index.is_file():
            old = json.loads(old_index.read_text()).get("files", {})
            stale = [f for f in old if f not in files]

        for rel, body in files.items():
            path = plugin_dir / rel
            current = path.read_text() if path.is_file() else None
            if current == body:
                continue
            if args.check:
                drift.append(str(path))
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body)
                print(f"wrote {path}")
        for rel in stale:
            path = plugin_dir / rel
            if path.exists():
                if args.check:
                    drift.append(f"{path} (stale)")
                else:
                    path.unlink()
                    print(f"removed {path}")

    if drift:
        print("Generated files are out of date or were edited by hand:", file=sys.stderr)
        for d in drift:
            print(f"  {d}", file=sys.stderr)
        print("Run: python pluginkit.py generate <repo-root>", file=sys.stderr)
        return 1
    if args.check:
        print("generated files are up to date")
    return 0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def read_frontmatter(path):
    text = path.read_text()
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    return yaml.safe_load(text[4:end]) or {}, text[end + 4:]


def validate_plugin(plugin_dir):
    errors, warnings = [], []
    try:
        p = load_plugin(plugin_dir)
    except yaml.YAMLError as e:
        return [f"plugin.yaml: {e}"], []

    for field in REQUIRED_FIELDS:
        if not p.get(field):
            errors.append(f"plugin.yaml: missing '{field}'")
    if errors:
        return errors, warnings

    if not NAME_RE.match(p["name"]):
        errors.append(f"plugin.yaml: name '{p['name']}' must be lowercase kebab-case")
    repo = str(p.get("repository", "")).rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]
    if not repo:
        errors.append("plugin.yaml: repository is required")
    elif not repo.endswith(REPO_SUFFIX):
        errors.append(f"plugin.yaml: repo '{repo}' must be named '{p['name']}{REPO_SUFFIX}'")
    elif repo != p["name"] + REPO_SUFFIX:
        errors.append(
            f"plugin.yaml: name '{p['name']}' must be the repo name without '{REPO_SUFFIX}': "
            f"'{repo.removesuffix(REPO_SUFFIX)}'"
        )
    if p["name"] != plugin_dir.name:
        errors.append(f"plugin.yaml: name '{p['name']}' must match folder '{plugin_dir.name}'")
    if not SEMVER_RE.match(str(p["version"])):
        errors.append(f"plugin.yaml: version '{p['version']}' is not semver")
    if not isinstance(p["author"], dict) or not p["author"].get("name"):
        errors.append("plugin.yaml: author.name is required")
    for t in p["targets"]:
        if t not in TARGETS:
            errors.append(f"plugin.yaml: unknown target '{t}' (known: {', '.join(TARGETS)})")
    if not isinstance(p["mcpServers"], dict) or not p["mcpServers"]:
        errors.append("plugin.yaml: at least one entry under mcpServers is required")
    else:
        for name, server in p["mcpServers"].items():
            if not ("command" in server or "url" in server):
                errors.append(f"mcpServers.{name}: needs 'command' or 'url'")

    skills = sorted((plugin_dir / "skills").glob("*/SKILL.md"))
    if not skills:
        errors.append("skills/: at least one skills/<name>/SKILL.md is required")
    for skill in skills:
        fm, body = read_frontmatter(skill)
        rel = skill.relative_to(plugin_dir)
        if fm.get("name") != skill.parent.name:
            errors.append(f"{rel}: frontmatter name must equal folder name '{skill.parent.name}'")
        desc = fm.get("description", "")
        if not desc:
            errors.append(f"{rel}: frontmatter description is required")
        elif len(desc) > 1024:
            errors.append(f"{rel}: description is over 1024 characters")
        if len(body.splitlines()) > 500:
            warnings.append(f"{rel}: over 500 lines; move detail into references/")

    for agent in sorted((plugin_dir / "agents").glob("*.md")):
        fm, _ = read_frontmatter(agent)
        if not fm.get("name") or not fm.get("description"):
            errors.append(f"{agent.relative_to(plugin_dir)}: agent needs name and description frontmatter")

    hooks = plugin_dir / "hooks" / "hooks.json"
    if hooks.is_file():
        try:
            json.loads(hooks.read_text())
        except json.JSONDecodeError as e:
            errors.append(f"hooks/hooks.json: {e}")
    return errors, warnings


def cmd_validate(args):
    failed = False
    for plugin_dir in find_plugins(args.root):
        errors, warnings = validate_plugin(plugin_dir)
        for w in warnings:
            print(f"warning: {plugin_dir.name}: {w}")
        for e in errors:
            print(f"error: {plugin_dir.name}: {e}", file=sys.stderr)
        failed = failed or bool(errors)
        if not errors:
            print(f"ok: {plugin_dir.name}")
    evals = Path(args.root) / "evals"
    if not any(evals.glob("*.yaml")):
        print("warning: no evals/*.yaml found")
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# Packaging for generic agents
# ---------------------------------------------------------------------------

INSTALL_SH = """#!/usr/bin/env sh
# Installs {name} {version} for agents that read skills from a directory.
# Usage: ./install.sh [skills-dir]   (default: ~/.agents/skills)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
dest=${{1:-$HOME/.agents/skills}}
mkdir -p "$dest"
for skill in "$here"/skills/*/; do
  name=$(basename "$skill")
  rm -rf "$dest/$name"
  cp -R "$skill" "$dest/$name"
  echo "installed skill $name -> $dest/$name"
done
echo
echo "Add this MCP server config to your agent:"
cat "$here/mcp.json"
"""


def cmd_package(args):
    plugin_dir = Path(args.plugin_dir).resolve()
    p = load_plugin(plugin_dir)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    zip_path = out / f"{p['name']}-{p['version']}.zip"
    top = f"{p['name']}-{p['version']}"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(plugin_dir.rglob("*")):
            if path.is_file():
                z.write(path, f"{top}/{path.relative_to(plugin_dir)}")
        if not (plugin_dir / "mcp.json").is_file():
            z.writestr(f"{top}/mcp.json", _json({"mcpServers": p["mcpServers"]}))
        info = zipfile.ZipInfo(f"{top}/install.sh")
        info.external_attr = 0o755 << 16
        z.writestr(info, INSTALL_SH.format(name=p["name"], version=p["version"]))
    print(zip_path)
    return 0


# ---------------------------------------------------------------------------
# Catalog (used by trilio-agent-marketplace)
# ---------------------------------------------------------------------------

def load_catalog(root):
    with (Path(root) / "catalog.yaml").open() as f:
        return yaml.safe_load(f)


def _git_url(repo):
    return repo if "://" in repo else f"https://github.com/{repo}.git"


def render_catalog(cat):
    owner = cat["owner"]
    claude_plugins, codex_plugins = [], []
    for e in cat["plugins"]:
        source = {"source": "git-subdir", "url": _git_url(e["repo"]), "path": e["path"], "ref": e["ref"]}
        if e.get("sha"):
            source["sha"] = e["sha"]
        claude_plugins.append({
            "name": e["name"],
            "source": source,
            "description": e["description"],
            "version": e["ref"].rsplit("/v", 1)[-1],
            "category": e.get("category", "Developer Tools"),
        })
        codex_plugins.append({
            "name": e["name"],
            "source": source,
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": e.get("category", "Developer Tools"),
        })
    return {
        ".claude-plugin/marketplace.json": _json({
            "name": cat["name"],
            "description": cat["description"],
            "owner": owner,
            "plugins": claude_plugins,
        }),
        ".agents/plugins/marketplace.json": _json({
            "name": cat["name"],
            "interface": {"displayName": cat.get("displayName", cat["name"])},
            "plugins": codex_plugins,
        }),
    }


def _ls_remote(repo, ref):
    out = subprocess.run(
        ["git", "ls-remote", _git_url(repo), f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}"],
        capture_output=True, text=True, check=True,
    ).stdout
    shas = dict(reversed(line.split("\t")) for line in out.splitlines() if line)
    # Annotated tags list the peeled commit under ^{}.
    return shas.get(f"refs/tags/{ref}^{{}}") or shas.get(f"refs/tags/{ref}")


def _fetch_json(repo, sha, path):
    if "://" in repo:
        raise KitError(f"verify only supports GitHub repos, got {repo}")
    url = f"https://raw.githubusercontent.com/{repo}/{sha}/{path}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def verify_catalog(cat):
    errors = []
    names = [e["name"] for e in cat["plugins"]]
    for dup in {n for n in names if names.count(n) > 1}:
        errors.append(f"{dup}: listed more than once")
    for e in cat["plugins"]:
        label = f"{e['name']}@{e['ref']}"
        if not e["ref"].startswith(f"{e['name']}/v"):
            errors.append(f"{label}: ref must be a release tag '<plugin>/v<semver>'")
            continue
        try:
            sha = _ls_remote(e["repo"], e["ref"])
        except subprocess.CalledProcessError as err:
            errors.append(f"{label}: git ls-remote failed: {err.stderr.strip()}")
            continue
        if not sha:
            errors.append(f"{label}: tag not found in {e['repo']}")
            continue
        if e.get("sha") and e["sha"] != sha:
            errors.append(f"{label}: tag now points at {sha}, catalog pins {e['sha']} (tag was moved)")
            continue
        version = e["ref"].rsplit("/v", 1)[-1]
        for manifest in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
            try:
                m = _fetch_json(e["repo"], sha, f"{e['path']}/{manifest}")
            except Exception as err:  # noqa: BLE001 - report any fetch failure
                errors.append(f"{label}: cannot read {manifest}: {err}")
                continue
            if m.get("name") != e["name"] or m.get("version") != version:
                errors.append(f"{label}: {manifest} says {m.get('name')}@{m.get('version')}")
        if not any(err.startswith(label) for err in errors):
            print(f"ok: {label} ({sha[:12]})")
    return errors


def cmd_catalog(args):
    cat = load_catalog(args.root)
    files = render_catalog(cat)
    drift = []
    for rel, body in files.items():
        path = Path(args.root) / rel
        current = path.read_text() if path.is_file() else None
        if current == body:
            continue
        if args.check:
            drift.append(str(path))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
            print(f"wrote {path}")
    if drift:
        print("Marketplace files are out of date with catalog.yaml:", file=sys.stderr)
        for d in drift:
            print(f"  {d}", file=sys.stderr)
        return 1
    if args.verify:
        errors = verify_catalog(cat)
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        if errors:
            return 1
    return 0


def cmd_pin(args):
    path = Path(args.root) / "catalog.yaml"
    cat = load_catalog(args.root)
    entry = next((e for e in cat["plugins"] if e["name"] == args.name), None)
    if entry is None:
        raise KitError(f"{args.name} is not in catalog.yaml; add an entry first")
    sha = _ls_remote(entry["repo"], args.ref)
    if not sha:
        raise KitError(f"tag {args.ref} not found in {entry['repo']}")
    # Rewrite only this entry's ref/sha lines so comments in catalog.yaml survive.
    lines = path.read_text().splitlines(keepends=True)
    in_entry = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("- name:"):
            in_entry = stripped.split(":", 1)[1].strip() == args.name
        elif in_entry and stripped.startswith("ref:"):
            lines[i] = line[: line.index("ref:")] + f"ref: {args.ref}\n"
        elif in_entry and stripped.startswith("sha:"):
            lines[i] = line[: line.index("sha:")] + f"sha: {sha}\n"
    path.write_text("".join(lines))
    print(f"pinned {args.name} to {args.ref} ({sha})")
    return cmd_catalog(argparse.Namespace(root=args.root, check=False, verify=False))


# ---------------------------------------------------------------------------
# New SKU from template
# ---------------------------------------------------------------------------

def cmd_new_sku(args):
    plugin_name, sku = args.plugin_name, args.sku.lower()
    if not NAME_RE.match(plugin_name) or not NAME_RE.match(sku):
        raise KitError("plugin name and SKU must be lowercase letters, digits and dashes")
    values = {
        "sku": sku,
        "SKU": args.sku.upper(),
        "title": args.title,
        "plugin_name": plugin_name,
        "repo": plugin_name + REPO_SUFFIX,
        "owner": args.owner,
        "kit_version": f"v{KIT_VERSION}",
    }
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise KitError(f"{out} exists and is not empty")
    template = KIT_DIR / "template" / "sku-repo"

    def fill(text):
        for k, v in values.items():
            text = text.replace("{{" + k + "}}", v)
        return text

    for src in sorted(template.rglob("*")):
        if src.is_dir():
            continue
        dest = out / fill(str(src.relative_to(template)))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(fill(src.read_text()))
        shutil.copymode(src, dest)
    cmd_generate(argparse.Namespace(root=str(out), check=False))
    print(f"\nCreated {out}. Next: git init, push to GitHub, then add the plugin to catalog.yaml.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pluginkit", description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", action="version", version=f"pluginkit {KIT_VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="write per-tool files from plugin.yaml")
    g.add_argument("root", nargs="?", default=".")
    g.add_argument("--check", action="store_true", help="fail instead of writing when files differ")
    g.set_defaults(func=cmd_generate)

    v = sub.add_parser("validate", help="lint plugin sources")
    v.add_argument("root", nargs="?", default=".")
    v.set_defaults(func=cmd_validate)

    pk = sub.add_parser("package", help="build the generic-agent zip")
    pk.add_argument("plugin_dir")
    pk.add_argument("--out", default="dist")
    pk.set_defaults(func=cmd_package)

    c = sub.add_parser("catalog", help="build marketplace files from catalog.yaml")
    c.add_argument("root", nargs="?", default=".")
    c.add_argument("--check", action="store_true", help="fail instead of writing when files differ")
    c.add_argument("--verify", action="store_true", help="check every entry against its release tag")
    c.set_defaults(func=cmd_catalog)

    pn = sub.add_parser("pin", help="point a catalog entry at a release tag")
    pn.add_argument("root")
    pn.add_argument("name")
    pn.add_argument("ref")
    pn.set_defaults(func=cmd_pin)

    n = sub.add_parser("new-sku", help="scaffold a SKU plugin repo")
    n.add_argument("plugin_name", help="e.g. trilio-for-kubernetes; the repo is <plugin_name>-agent-plugin")
    n.add_argument("--sku", required=True, help="short SKU code, e.g. t4k")
    n.add_argument("--title", required=True, help="product name, e.g. 'Trilio for Kubernetes'")
    n.add_argument("--owner", default="somesh22123")
    n.add_argument("--out", required=True)
    n.set_defaults(func=cmd_new_sku)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except KitError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

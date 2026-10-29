import io
import json
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pluginkit  # noqa: E402


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = pluginkit.main(list(argv))
    return code, out.getvalue() + err.getvalue()


class NewSkuTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "trilio-for-kubernetes-agent-plugin"
        code, out = run("new-sku", "trilio-for-kubernetes", "--sku", "t4k",
                        "--title", "Trilio for Kubernetes", "--out", str(self.repo))
        self.assertEqual(code, 0, out)
        self.plugin = self.repo / "plugins" / "trilio-for-kubernetes"

    def tearDown(self):
        self.tmp.cleanup()

    def test_template_validates_and_is_generated(self):
        self.assertEqual(run("validate", str(self.repo))[0], 0)
        self.assertEqual(run("generate", "--check", str(self.repo))[0], 0)
        self.assertNotIn("{{", (self.repo / ".github/workflows/ci.yml").read_text())

    def test_generates_each_tool_manifest(self):
        claude = json.loads((self.plugin / ".claude-plugin/plugin.json").read_text())
        codex = json.loads((self.plugin / ".codex-plugin/plugin.json").read_text())
        cursor = json.loads((self.plugin / ".cursor-plugin/plugin.json").read_text())
        for m in (claude, codex, cursor):
            self.assertEqual(m["name"], "trilio-for-kubernetes")
            self.assertEqual(m["version"], "0.1.0")
        self.assertEqual(codex["mcpServers"], "./.mcp.json")
        self.assertIn("trilio-t4k", json.loads((self.plugin / ".mcp.json").read_text())["mcpServers"])
        self.assertTrue((self.plugin / "mcp.json").is_file())
        self.assertFalse((self.plugin / ".junie").exists())

    def test_check_fails_on_hand_edit(self):
        manifest = self.plugin / ".claude-plugin/plugin.json"
        manifest.write_text(manifest.read_text().replace("0.1.0", "9.9.9"))
        code, out = run("generate", "--check", str(self.repo))
        self.assertEqual(code, 1)
        self.assertIn("plugin.json", out)

    def test_check_fails_when_source_changes(self):
        src = self.plugin / "plugin.yaml"
        src.write_text(src.read_text().replace("version: 0.1.0", "version: 0.2.0"))
        self.assertEqual(run("generate", "--check", str(self.repo))[0], 1)
        self.assertEqual(run("generate", str(self.repo))[0], 0)
        self.assertEqual(run("generate", "--check", str(self.repo))[0], 0)

    def test_dropping_a_target_removes_its_files(self):
        src = self.plugin / "plugin.yaml"
        src.write_text(src.read_text().replace("targets: [claude-code, codex, cursor]", "targets: [claude-code, codex]"))
        self.assertEqual(run("generate", str(self.repo))[0], 0)
        self.assertFalse((self.plugin / ".cursor-plugin/plugin.json").exists())
        self.assertFalse((self.plugin / "mcp.json").exists())

    def test_validate_enforces_naming_rule(self):
        src = self.plugin / "plugin.yaml"
        src.write_text(src.read_text().replace(
            "trilio-for-kubernetes-agent-plugin", "t4k-k8s-skill"))
        code, out = run("validate", str(self.repo))
        self.assertEqual(code, 1)
        self.assertIn("must be named 'trilio-for-kubernetes-agent-plugin'", out)

    def test_validate_catches_bad_skill(self):
        skill = self.plugin / "skills/t4k-guide/SKILL.md"
        skill.write_text("---\nname: wrong\n---\nbody\n")
        code, out = run("validate", str(self.repo))
        self.assertEqual(code, 1)
        self.assertIn("frontmatter name", out)
        self.assertIn("description is required", out)

    def test_package_contains_installer(self):
        dist = Path(self.tmp.name) / "dist"
        self.assertEqual(run("package", str(self.plugin), "--out", str(dist))[0], 0)
        with zipfile.ZipFile(dist / "trilio-for-kubernetes-0.1.0.zip") as z:
            names = z.namelist()
        self.assertIn("trilio-for-kubernetes-0.1.0/install.sh", names)
        self.assertIn("trilio-for-kubernetes-0.1.0/skills/t4k-guide/SKILL.md", names)


class CatalogTest(unittest.TestCase):
    def test_render_and_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "catalog.yaml").write_text(
                "name: trilio\ndescription: d\nowner: {name: Trilio}\nplugins:\n"
                "  - name: site-recovery-kubernetes\n    repo: acme/site-recovery-kubernetes-agent-plugin\n"
                "    path: plugins/site-recovery-kubernetes\n    ref: site-recovery-kubernetes/v0.1.0\n"
                "    description: TSR\n"
            )
            self.assertEqual(run("catalog", "--check", tmp)[0], 1)
            self.assertEqual(run("catalog", tmp)[0], 0)
            self.assertEqual(run("catalog", "--check", tmp)[0], 0)
            claude = json.loads((root / ".claude-plugin/marketplace.json").read_text())
            src = claude["plugins"][0]["source"]
            self.assertEqual(src["source"], "git-subdir")
            self.assertEqual(src["url"], "https://github.com/acme/site-recovery-kubernetes-agent-plugin.git")
            self.assertEqual(claude["plugins"][0]["version"], "0.1.0")
            codex = json.loads((root / ".agents/plugins/marketplace.json").read_text())
            self.assertEqual(codex["plugins"][0]["policy"]["installation"], "AVAILABLE")


if __name__ == "__main__":
    unittest.main()

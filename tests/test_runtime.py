import json
import tempfile
import unittest
from pathlib import Path

from hybrid_harness import FixtureProvider, HybridRuntime, Ledger, check_candidate, validate_tool_call


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hybrid-runtime-test-")
        self.root = Path(self.temp.name)
        (self.root / "public").mkdir()
        (self.root / "skills").mkdir()
        (self.root / "data").mkdir()
        (self.root / "public/index.html").write_text('<html lang="zh-Hant-TW"><head><meta name="viewport" content="width=device-width"></head><body><main><h1>示範頁</h1><a href="https://example.org/source">來源</a><p>不提供投資建議</p></main></body></html>', encoding="utf-8")
        (self.root / "public/styles.css").write_text(':focus-visible{outline:2px solid blue}@media(prefers-reduced-motion:reduce){}', encoding="utf-8")
        (self.root / "public/app.js").write_text('const ready = true;', encoding="utf-8")
        (self.root / "skills/build.md").write_text('Build a clear page.', encoding="utf-8")
        (self.root / "skills/review.md").write_text('Review the page.', encoding="utf-8")
        (self.root / "data/context.json").write_text(json.dumps({"topic": "example"}), encoding="utf-8")
        manifest = {
            "context_file": "data/context.json", "fixture_dir": "public",
            "stage": {"skill": "skills/build.md", "review_skill": "skills/review.md", "write_set": ["index.html", "styles.css", "app.js"], "max_asset_bytes": 100000, "max_tool_calls": 9, "review_asset": "index.html"},
            "checks": {"assets": ["index.html", "styles.css", "app.js"], "content_asset": "index.html", "profile": "web_page", "language": "zh-Hant-TW", "required_text": ["示範頁"], "required_links": ["https://example.org/source"], "required_patterns": ["不提供投資建議"]},
        }
        (self.root / "harness.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.state = self.root / "state"
        self.ledger = Ledger(self.state / "ledger.sqlite", self.state / "blobs")
        self.runtime = HybridRuntime(self.root, self.state, self.ledger)

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def test_hard_gate_and_new_slice(self):
        run = self.runtime.start("Build a useful introductory page with verified sources.", FixtureProvider(self.root / "public"))
        self.assertEqual(run["status"], "awaiting_approval")
        self.assertEqual(len(self.ledger.list_runs()), 1)
        child = self.runtime.approve(run["id"])
        self.assertEqual(child["status"], "complete")
        self.assertEqual(child["parent_id"], run["id"])
        self.assertEqual(self.runtime.approve(run["id"])["id"], child["id"])

    def test_tool_escape_is_held(self):
        run = self.runtime.start("Build a useful introductory page with verified sources.", FixtureProvider(self.root / "public", "escape"))
        self.assertEqual(run["status"], "held")
        self.assertIn("Write outside", run["error"])
        with self.assertRaisesRegex(ValueError, "not awaiting approval"):
            self.runtime.approve(run["id"])

    def test_merge_requires_gate_and_is_deduplicated(self):
        run = self.runtime.start("Build a useful introductory page with verified sources.", FixtureProvider(self.root / "public"))
        with self.assertRaisesRegex(ValueError, "gate is still open"):
            self.runtime.on_pr_merged("delivery-12345678", run["id"], "a" * 40)
        self.runtime.approve(run["id"])
        continued = self.runtime.on_pr_merged("delivery-12345678", run["id"], "a" * 40)
        self.assertEqual(continued["stage"], "post_merge_check")
        self.assertEqual(self.runtime.on_pr_merged("delivery-12345678", run["id"], "a" * 40)["id"], continued["id"])

    def test_policy_checks_are_independent_of_agent_text(self):
        assets = {name: (self.root / "public" / name).read_text(encoding="utf-8") for name in ("index.html", "styles.css", "app.js")}
        self.assertTrue(check_candidate(assets, self.runtime.checks)["pass"])
        assets["index.html"] = assets["index.html"].replace("https://example.org/source", "")
        self.assertFalse(check_candidate(assets, self.runtime.checks)["pass"])
        with self.assertRaisesRegex(ValueError, "Tool denied"):
            validate_tool_call({"name": "approve", "args": {}}, {"tools": ["write_asset"], "write_set": ["index.html"], "max_asset_bytes": 100})

    def test_manifest_cannot_grant_path_traversal(self):
        path = self.root / "harness.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["stage"]["write_set"] = ["../escape.txt"]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unsafe asset name"):
            HybridRuntime(self.root, self.state, self.ledger)


if __name__ == "__main__":
    unittest.main()

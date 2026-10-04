import json
import re
from pathlib import Path

from .agent import run_semantic_review, run_tool_loop
from .policy import check_candidate


class HybridRuntime:
    def __init__(self, project, state_dir, ledger):
        self.project = Path(project).resolve()
        self.state_dir = Path(state_dir).resolve()
        self.ledger = ledger
        self.manifest = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        self.stage = self.manifest["stage"]
        self.checks = self.manifest["checks"]
        self.assets_allowed = self.stage["write_set"]
        if not self.assets_allowed or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) or name.endswith(".") for name in self.assets_allowed):
            raise ValueError("Stage write_set contains an unsafe asset name")
        self.context = json.loads((self.project / self.manifest["context_file"]).read_text(encoding="utf-8"))

    def assets(self, run_id):
        return {name: self.ledger.read_artifact(run_id, name) for name in self.assets_allowed}

    def start(self, prompt, provider, tenant_id="demo", product_id="demo"):
        if not isinstance(prompt, str) or not 20 <= len(prompt.strip()) <= 3000:
            raise ValueError("Prompt must be 20–3000 characters")
        run = self.ledger.create_run("slice_a_build", prompt.strip(), provider.name, tenant_id, product_id)
        try:
            skill = (self.project / self.stage["skill"]).read_text(encoding="utf-8")
            grant = {"tools": ["write_asset"], "write_set": self.assets_allowed, "max_asset_bytes": self.stage.get("max_asset_bytes", 100_000), "max_tool_calls": self.stage.get("max_tool_calls", 9)}
            agent = run_tool_loop(
                provider,
                skill + "\nYou have a bounded tool-call budget. Work only from supplied source data.",
                "Task: %s\nSource data:\n%s" % (prompt, json.dumps(self.context, ensure_ascii=False, indent=2)),
                grant,
                lambda name, content: self.ledger.put_artifact(run, name, content, self.assets_allowed),
            )
            assets = self.assets(run["id"])
            deterministic = check_candidate(assets, self.checks)
            self.ledger.event(run["id"], "checks.deterministic", deterministic)
            if not deterministic["pass"]:
                return self.ledger.transition(run["id"], "running", "held", {"deterministic": deterministic, "agent": agent}, "Deterministic checks failed")
            review_skill = (self.project / self.stage["review_skill"]).read_text(encoding="utf-8")
            review_asset = self.stage.get("review_asset", self.assets_allowed[0])
            semantic = run_semantic_review(provider, review_skill, "Source data:\n%s\nCandidate artifact:\n%s" % (json.dumps(self.context, ensure_ascii=False), (assets.get(review_asset) or "")[:60_000]))
            self.ledger.event(run["id"], "checks.semantic", semantic)
            if semantic["verdict"] == "fail":
                return self.ledger.transition(run["id"], "running", "held", {"deterministic": deterministic, "semantic": semantic, "agent": agent}, "Semantic check failed")
            return self.ledger.transition(run["id"], "running", "awaiting_approval", {"deterministic": deterministic, "semantic": semantic, "agent": agent})
        except Exception as error:
            return self.ledger.transition(run["id"], "running", "held", error=str(error))

    def approve(self, parent_id, actor="owner"):
        parent = self.ledger.get_run(parent_id)
        if not parent or parent["stage"] != "slice_a_build":
            raise ValueError("Unknown Slice A run")
        existing = self.ledger.child(parent_id, "slice_b_verify")
        if existing:
            return existing
        if parent["status"] != "awaiting_approval":
            raise ValueError("Run is %s, not awaiting approval" % parent["status"])
        self.ledger.transition(parent_id, "awaiting_approval", "approved")
        self.ledger.event(parent_id, "approval.granted", {"actor": actor})
        child = self.ledger.create_run("slice_b_verify", "Verify approved candidate", "deterministic", parent["tenant_id"], parent["product_id"], parent_id)
        try:
            assets = self.assets(parent_id)
            deterministic = check_candidate(assets, self.checks)
            if not deterministic["pass"]:
                return self.ledger.transition(child["id"], "running", "held", {"deterministic": deterministic}, "Slice B verification failed")
            published = self.state_dir / "published" / child["id"]
            published.mkdir(parents=True, exist_ok=True)
            for name in self.assets_allowed:
                (published / name).write_text(assets[name], encoding="utf-8")
            self.ledger.event(child["id"], "artifact.published", {"parentId": parent_id, "path": str(published)})
            return self.ledger.transition(child["id"], "running", "complete", {"deterministic": deterministic})
        except Exception as error:
            return self.ledger.transition(child["id"], "running", "held", error=str(error))

    def reject(self, parent_id, actor="owner"):
        parent = self.ledger.get_run(parent_id)
        if not parent or parent["status"] != "awaiting_approval":
            raise ValueError("Run is not awaiting approval")
        self.ledger.event(parent_id, "approval.rejected", {"actor": actor})
        return self.ledger.transition(parent_id, "awaiting_approval", "rejected")

    def on_pr_merged(self, delivery_id, run_id, commit_sha):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{8,120}", delivery_id or "") or not re.fullmatch(r"[a-f0-9]{40}", commit_sha or ""):
            raise ValueError("Invalid merge event")
        existing = self.ledger.merge_event(delivery_id, run_id, commit_sha)
        if existing:
            return self.ledger.get_run(existing["continuation_id"])
        parent = self.ledger.get_run(run_id)
        if not parent or parent["stage"] != "slice_a_build" or parent["status"] != "approved":
            raise ValueError("Owner gate is still open")
        slice_b = self.ledger.child(run_id, "slice_b_verify")
        if not slice_b or slice_b["status"] != "complete":
            raise ValueError("Slice B is not complete")
        continuation = self.ledger.create_run("post_merge_check", "Verify merged commit " + commit_sha, "deterministic", parent["tenant_id"], parent["product_id"], slice_b["id"])
        deterministic = check_candidate(self.assets(run_id), self.checks)
        self.ledger.record_merge(delivery_id, run_id, commit_sha, continuation["id"])
        return self.ledger.transition(continuation["id"], "running", "complete" if deterministic["pass"] else "held", {"deterministic": deterministic}, None if deterministic["pass"] else "Post-merge check failed")

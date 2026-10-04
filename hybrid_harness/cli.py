import argparse
import json
import sys
from pathlib import Path

from .ledger import Ledger
from .provider import ChatCompletionsProvider, FixtureProvider
from .runtime import HybridRuntime


def main(argv=None):
    parser = argparse.ArgumentParser(description="Hybrid harness runtime JSON CLI")
    parser.add_argument("--project", required=True)
    parser.add_argument("--state-dir")
    parser.add_argument("command", choices=("start", "approve", "reject", "merge", "status", "list", "artifact"))
    args = parser.parse_args(argv)
    project = Path(args.project).resolve()
    state = Path(args.state_dir).resolve() if args.state_dir else project / "storage"
    payload = json.load(sys.stdin) if args.command != "list" else {}
    ledger = Ledger(state / "harness.sqlite", state / "blobs")
    try:
        runtime = HybridRuntime(project, state, ledger)
        if args.command == "start":
            provider = ChatCompletionsProvider() if payload.get("provider") == "live" else FixtureProvider(project / runtime.manifest["fixture_dir"], payload.get("variant", "pass"), runtime.assets_allowed)
            result = runtime.start(payload.get("prompt"), provider)
        elif args.command == "approve":
            result = runtime.approve(payload["runId"])
        elif args.command == "reject":
            result = runtime.reject(payload["runId"])
        elif args.command == "merge":
            result = runtime.on_pr_merged(payload["deliveryId"], payload["runId"], payload["commitSha"])
        elif args.command == "status":
            run = ledger.get_run(payload["runId"])
            if not run:
                raise ValueError("Run not found")
            result = {**run, "events": ledger.events(run["id"]), "artifacts": ledger.artifacts(run["id"])}
        elif args.command == "artifact":
            content = ledger.read_artifact(payload["runId"], payload["name"])
            if content is None:
                raise ValueError("Artifact not found")
            result = {"content": content}
        else:
            result = ledger.list_runs()
        print(json.dumps(result, ensure_ascii=False))
    finally:
        ledger.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

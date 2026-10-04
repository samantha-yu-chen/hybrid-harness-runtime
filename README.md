# hybrid-harness-runtime
hybrid harness runtime

## Python runtime

這個 repo 現在包含可重用的 Python harness 核心：

- [`hybrid_harness/runtime.py`](hybrid_harness/runtime.py)：Slice A、owner gate、Slice B 與 PR merge 後續工作。
- [`hybrid_harness/agent.py`](hybrid_harness/agent.py)：受限的 LLM tool-call loop 與獨立 semantic review。
- [`hybrid_harness/policy.py`](hybrid_harness/policy.py)：write-set、工具參數與候選成果的確定性檢查。
- [`hybrid_harness/ledger.py`](hybrid_harness/ledger.py)：SQLite 狀態、事件與本機 blob manifest。
- [`hybrid_harness/provider.py`](hybrid_harness/provider.py)：OpenAI-compatible Chat Completions API 與可重現 fixture provider。

專案內容由各 eval/app repo 的 `harness.json`、skill 檔與資料檔提供；核心不包含 TSMC 公司資料或頁面程式碼。可用 `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests` 測試核心。CLI 入口為 `python3 -m hybrid_harness.cli --project <project-path> <command>`，命令與 payload 詳見 [TSMC eval 專案](https://github.com/samantha-yu-chen/TSMC-supply-chain)；兩個 repo 需放在同一個父目錄，或由 web app 設定 `HARNESS_RUNTIME_DIR`。

## Architecture docs

- [AI-First Product Operating System architecture and workflow v0.8](docs/ai_first_pos_architecture_v0_8.md) — Markdown source for review and future implementation work. The linked figures are in `docs/figures/`.
- [Hybrid Harness V1 runtime and agent boundary](docs/v1_runtime_decisions.md) — proposed rollout design and acceptance proof for deterministic control over agent work.
- [TSMC supply-chain eval project](https://github.com/samantha-yu-chen/TSMC-supply-chain) — JavaScript web app and runnable harness tests. The repository is private.
- The original DOCX and full-size architecture/workflow diagrams remain in `docs/`.

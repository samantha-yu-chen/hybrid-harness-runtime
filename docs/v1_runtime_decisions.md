# Hybrid Harness V1 Runtime and Agent Boundary

Status: proposed for owner approval. This refines the [v0.8 architecture](ai_first_pos_architecture_v0_8.md) for a rollout-quality V1. The central claim to prove is that deterministic runtime decisions can govern useful agent work without giving the agent control over authority, state or quality gates.

## 1. Boundary

The Harness Surface is the user's entry point. The left panel is the ordered workflow: Strategy, Discovery, handoff and Build stages run from top to bottom. Selecting a stage loads its versioned definition, the current session and artifacts. A user message or an authorized event starts a run. The right panel shows the current task and its artifact/evidence. The LLM is a remote service called through the Model Gateway; it is not embedded in the UI or runtime as a plugin.

| Runtime owns | Agent may do |
| --- | --- |
| Identity, tenant/product scope, workflow state and event ordering | Understand the bounded task and ask clarifying questions |
| Stage selection, version pinning, context assembly and model route | Propose a plan, draft artifacts and write code in its granted workspace |
| Tool grants, command policy, write-set and spend limits | Request permitted tools through the broker |
| Schema validation, checks, risk-from-diff and evidence | Explain its work and propose a semantic assessment |
| Approval gates, merge/release decisions and retries | Return candidate outputs and uncertainty |
| Durable records, recovery and audit | Hold no authority or durable private state |

An agent output is always a **candidate**. A typed model decision may recommend an answer and confidence, but only a versioned runtime rule changes workflow state. A model cannot approve itself, alter its grant, mark a check passed or release to production. The owner is the sole human approver when a human gate is necessary. Normal low-risk transitions proceed by code after their checks pass. Approval timeouts hold and notify; they never auto-approve.

## 2. Stage and run contract

Each stage definition pins: its left-panel order, eligible entry types, prerequisites, instruction/skill version, context sources and size limit, model route and sensitivity ceiling, tool allowlist, read/write boundary, output schema, deterministic checks, semantic check, risk floor, budgets, human gates and completion rule. A running job keeps its pinned version even if the definition changes. A stage may be skipped only by an explicit rule that records why; the UI shows completed, skipped, active and held stages.

The runtime creates a run with an idempotency key and a short-lived signed grant. `open` returns a scoped, source-linked context package and its immutable ID. The agent invokes the external LLM and any brokered tools, then calls `emit` with a schema-valid candidate. The runtime runs checks and calls `close` with the authoritative outcome. Every model call records the route, served model version, context ID, tool calls, cost and result. The runner process may disappear after each dispatch; session continuity is reconstructed from durable records.

The usual context is the current request, the relevant signed contract or ticket, selected repo files and diffs, applicable folder rules, recent durable session summary, and tool descriptions needed for this stage. Full chat history and whole repositories are not sent by default. Further reads go through the scoped broker. Tool calls are checked individually against the grant, tenant/product scope, workspace, file write-set, command and network policy, and budget. Build writes are limited to an isolated branch. The agent receives no direct SQL, blob, merge, approval or production credentials.

## 3. Deterministic decision path

The runtime evaluates transitions in this order:

1. **Admission:** authenticate identity, resolve tenant/product, validate input and stage prerequisites.
2. **Grant:** pin stage/policy versions, select an allowed model route, claim the ticket/write-set and issue a scoped grant.
3. **Candidate:** accept typed agent output through `emit`; reject malformed or out-of-scope output.
4. **Evidence:** run deterministic checks first, then an independent semantic check that does not read the builder's reasoning.
5. **Risk:** take the higher of declared risk, diff-derived risk and uncertainty floor. Never let a model lower the floor.
6. **Gate:** apply the stage's deterministic completion rule. Low-risk work with complete evidence may merge under the approved policy. Necessary human gates freeze the dependent workflow until the owner acts.
7. **Continue:** an approval or verified merged-PR event updates state, triggers due drift checks, computes the next eligible stage or ready ticket, and creates a new task in the right panel.

Rules are versioned data or code. A rule records its inputs, version, result and reason. Unknown, inconsistent or missing evidence takes the hold/review path. No free-form agent text is parsed to choose a branch. The left-panel sequence is authoritative; the model cannot jump ahead to another stage.

### Human gate as a slice barrier

Treat each human gate as a hard boundary between work slices. Slice A finishes its work and tests, seals an evidence packet, and enters `awaiting_approval`. At that point, all dependent model calls, tool calls, test runs and next-stage jobs stop. The runtime may only record the approval/denial, send reminders and perform operational recovery. Unrelated independent workflows can continue. Approval never revives the old runner. It creates a new right-panel task and a new run/grant for Slice B, using the approved Slice A artifact as immutable input. Rejection creates a revision task for Slice A; it does not start Slice B. The UI must make the barrier visible in the left-panel stage and right-panel task.

Keep human gates only where authority or irreversibility requires them: signing product intent or an amended contract, resolving a material ambiguity the system cannot safely infer, approving medium/high-risk or uncertain PRs, allowing a policy/route exception, and approving production release. Low-risk PRs may merge automatically only after all required checks pass and the owner has enabled that policy. Routine stage transitions, retries within budget and deterministic drift insertion do not ask a person.

## 4. Durable state and serverless execution

Application handlers, schedulers and runners are disposable. PostgreSQL is the local SQL system of record for structured metadata: tenant/product, stage versions, contracts, tickets, runs, grants, state transitions, events, approvals, artifact manifests and audit. Blob storage holds screenshots, documents, context snapshots, logs and evidence bytes. SQL holds each blob's scoped manifest, hash, sensitivity and retention. A blob object without a committed manifest is not an authorized artifact.

For rollout, local PostgreSQL must run as a dedicated durable service with failover or a tested recovery path, continuous backup and monitored capacity. Blob storage must have durable replication and a tested restore path. A SQL file or blob emulator inside an ephemeral worker is only a development arrangement. Tenant/product isolation is enforced in SQL, blob access, grants, workspaces and release gates; it is tested with negative cross-tenant cases. The serverless property applies to compute, not to durable storage.

The SQL event inbox/outbox, idempotency keys, expected-state transitions and expiring worker leases provide recovery. A webhook handler verifies the PR source, branch, merge commit and ticket marker, records the event and returns promptly. The scheduler processes it outside the webhook request. Duplicate deliveries are harmless; a reconciliation job finds missed merge events by comparing repository state with the ledger. A merged PR starts the next eligible job only when no slice barrier or other required gate is open.

## 5. Quality boundary

A ticket cannot enter Build until it has a goal, intent link, acceptance criteria, evaluation method, scope and write-set, blockers, risk and sensitivity. A generated light-route ticket or plan advances by code when its schema, coverage and risk rules pass; a human is asked only for unresolved intent or a required authority gate. Contract changes create a new signed version; merged tickets are never silently rewritten.

Before merge, the check service—not the agent—must produce evidence for lint, types, build, relevant tests, secrets/security checks, write-set and change-class checks, applicable Design System rules and executable acceptance evaluations. A separate semantic checker compares the diff and evidence with intent and acceptance criteria. A failure blocks progress; an uncertain verdict raises risk and requires explicit owner review. The PR presents the contract/ticket links, diff, checks, semantic verdict, risk reason, model/stage/context IDs and rollback notes. Main-branch CI must pass before continuation. Non-git side effects, such as migrations, require a reviewed recovery plan.

The system holds rather than guessing when required context, evidence, credentials, permitted model route or owner approval is unavailable. Model and tool failures use bounded retries with recorded reasons. A crashed worker resumes from the last committed state; a stale branch is rebased and rechecked. SQL or blob outages stop affected state changes. A production health failure stops rollout and executes the approved mitigation. No failure path silently relaxes security, quality or approval policy.

## 6. V1 acceptance proof

The runtime, transition rules, grant enforcement, event handling and quality gates must be tested by code. Use deterministic model fixtures to exercise pass, fail, uncertainty, malformed output and malicious tool requests; property tests for allowed state transitions; integration tests for SQL/blob and repository events; and fault-injection tests for crashes and duplicates. Keep separate live-model evaluations for semantic quality, because deterministic tests prove control behavior but cannot prove that every generated feature is correct.

Before a tenant rollout, demonstrate the left-panel workflow in order. Slice A completes its checks and stops at a necessary human gate; no dependent job or test starts while approval is pending. Approval creates a distinct right-panel task for Slice B, which gets a fresh grant and its own checks. A low-risk path crosses routine stages without a human gate. A merged PR starts the next eligible job only if no barrier is open. Repeat with parallel non-overlapping tickets and a conflicting write-set. Show that a model recommendation cannot branch around a rule or a failed gate.

Run failure exercises for a worker crash, duplicate and missed merge webhooks, stale base, malformed model output, model outage, SQL outage and missing blob. Each must end in exactly one valid transition or an owner-visible hold, with enough audit evidence to explain why. Verify cross-tenant denial and permitted-region model routing. Restore SQL and blob backups before rollout. Monitor queue age, held jobs, retries, gate latency, check failures, model spend, drift and audit completeness after launch.

The remaining rollout parameters are the exact PostgreSQL failover setup, blob provider and region, model route table, recovery targets and operating thresholds. They require explicit owner approval and an operational test before production use; the agent does not choose them.

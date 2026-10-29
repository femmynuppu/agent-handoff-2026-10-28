# PROMETHEUS

Project-local teacher/student experiment controller, Python standard library core, installed MemPalace adapter, and optional OMP extension. No installs, global configuration changes, Hermes listener starts, or live inference were performed. Workspace mode is 0700.

## Current result

**BLOCKED / INSUFFICIENT_DATA** for learning: no quantified inference budget, unresolved selected teacher label versus live catalog, unverified effective student High reasoning, refused real A2A endpoint, and unverified tool isolation. `artifacts/baseline-missing-data.json` contains ten null metric observations, not invented zeros or improvement. Synthetic transport/memory checks demonstrate infrastructure only.

Teacher is the **current OMP session**, not a second request sent to the student Hermes endpoint. Teacher lessons enter with explicit OMP session provenance. Registry-selected labels are not upstream model attestation.

## Commands

Run from this directory:

```sh
python3 -m prometheus status
python3 -m prometheus sandbox-probe
python3 -m prometheus memory-discover
python3 -m prometheus baseline-report
python3 -m prometheus.evaluation validate-curriculum
python3 -m prometheus create L01
python3 -m prometheus show RUN_ID
```

The created run explicitly binds B01 baseline, P01 practice and H01 fresh holdout through `references/private/lesson-map.json`. All ten lessons have distinct mappings. `export-task` emits student-only material. Private references and exact solutions are never included in live student payloads. A run is not an autonomous background process; each action is explicit and durable.

Creation may plan a dependency-blocked lesson, but execution and advancement enforce curriculum prerequisites. `review-prerequisite LESSON_ID --review review.json` records durable independently reviewed evidence only when it binds an actual controlled-holdout-pass run and its `lesson_validation` hash. Required review fields: `lesson_id`, `run_id`, `independent_review:true`, named `reviewer`, substantive `rationale`, `evidence_sha256`. Self-ratings/imports cannot satisfy this gate. Tool-workflow L08 live execution is explicitly blocked until trusted constrained execution receipts are integrated into Hermes; the local arithmetic evaluator is not that integration. Phase cursors require a new artifact each practice/remediation cycle, never reuse prior outputs. Failed/ambiguous runs refuse further live submissions; inspect known task status/cancel and explicitly review duplication risk before creating a separately reviewed run.

### Offline real-output review

`ingest RUN_ID response.json` retains supplied output with raw JSON hash, revision, phase and **SELF_REPORTED_UNVERIFIED** provenance. `grade RUN_ID` computes descriptive deterministic checks but cannot mint execution receipts. `advance RUN_ID` grades baseline, progresses teaching/practice/evaluation, allows initial practice plus at most three corrective cycles, and terminates failure separately from transport failure. Imported deterministic passes may reach the review phase but cannot authorize lesson persistence or controlled holdout claims.

Teacher artifacts use:

```sh
python3 -m prometheus teacher-lesson RUN_ID --content lesson.txt --session-id OMP_SESSION_ID --reviewer OPERATOR
python3 -m prometheus advance RUN_ID
```

Only use this during teach/remediate. Provenance is operator-attested, not independent upstream identity verification. Teach a procedure, not the answer. Remediation follows evaluation, never before baseline/practice grading; blinded human review must not copy hidden solutions into lesson text.

### Live cycle after prerequisites are genuinely resolved

Do not toggle booleans to pretend verification. Obtain and retain routing metadata resolving the teacher selection discrepancy, effective exact Gemini High configuration evidence, deployed Agent Card/auth evidence, actual student tool policy/isolation evidence, quantified total/call/token/currency authorization and provider-enforced token/cost limits. A2A itself has no supported request token cap in the inspected Hermes protocol: reservations are **not** backend enforcement. Until provider-enforced limits are proven, `live-step` remains blocked. Starting an isolated Hermes/A2A listener or changing network exposure requires separate approval; this project never does so.

Supply bearer credential only through `PROMETHEUS_A2A_TOKEN`. `discover` is metadata-only; it validates literal loopback same-origin JSON-RPC card interface, version and bearer requirements, including installed Hermes interface-level protocol version and tenant. `task-get`, `task-poll`, `task-cancel` operate explicit known tasks. Cancel is attempted once, and unsupported cancellation is reported, never assumed to succeed.

For an authorized run: `live-step` baseline -> `advance` -> current OMP `teacher-lesson` -> `advance` -> `live-step` practice -> `advance` -> `advance` evaluation -> remediation or persistence review. Each actual request reserves worst-case money/tokens/call under a global file lock before network I/O. Unknown receipt cost blocks the next call. Explicit `settle-cost SEQUENCE --cost AMOUNT --tokens COUNT --receipt provider.json --reviewer OPERATOR` binds an independently reviewed provider receipt (`provider_receipt_id`, `run_id`, `sequence`) and rejects nonfinite/negative/boolean values or costs above reservation. Serialized external receipts stay operator-reviewed, not cryptographically provider-attested.

After deterministic pass **and** controlled actual HTTP evidence plus explicit human review, `approve-lesson RUN_ID --content lesson.txt --reviewer OPERATOR --review review.json` writes a NEW **practice-reviewed candidate**, not validated improvement. Review JSON requires `reviewer`, `run_id`, `approved:true`, substantive `rationale`, and `content_sha256` equal to the canonical JSON string SHA256 from `prometheus.core.digest(content)`. It records teacher-artifact provenance even if the operator approves revised content. Candidate provenance is `validation_stage:practice_reviewed_candidate, holdout_pending:true`. Fresh holdout gets a distinct task and new A2A context; memory retrieval records exact lesson ID/hash. Run `lesson_validation` records observed holdout pass or candidate-not-validated without overwriting memory; failure leaves the lesson quarantined as candidate. Completion never asserts broad mastery or statistical improvement. Interrupted/ambiguous execution is not a competency failure and must be reviewed before a new submission; no automatic SendMessage replay.

## Memory

`memory-selftest` performs explicitly synthetic approved infrastructure storage. Installed MemPalace KG `add/query` index NEW project entities pointing to immutable local lesson JSON and its SHA256. Retrieval hydrates only a matching project-local filename and verifies the complete content hash. This is genuine **MemPalace KG indexing plus local hydration**, not native drawer semantic search, embedding preload, or learning proof. KG object max128 makes pointers appropriate; no new embedding abstraction is invented. Before tools/call, installed `_apply_server_flags(palace=...)` and `_resolve_kg_path()` assert the exact project KG location. Child process sockets deny connections, telemetry is disabled, and model download environment is offline. No existing global memory entries are overwritten.

## Optional OMP extension

`omp-extension.ts` uses installed OMP ExtensionAPI, registers a status command and read/control tool, and has no startup hooks or inference action. It is **not globally enabled**. Explicitly load only after source review using OMP's extension flag. CLI is the complete operator interface. Extension can inspect status/memory capabilities/run records; it cannot silently spend.

## Verification and evidence

```sh
python3 -m unittest discover -s tests -v
```

`tests/test_transport.py` uses an ephemeral loopback **scripted HTTP fixture, not Hermes**, constructing the installed Agent Card helper AST verbatim without importing gateway side effects. Covers actual interface-level card contract/tenant, ambiguous send no replay, context mismatch, malformed auth/card, total transfer deadline against byte dripping, cancellation unsupported, unknown task state and failure outcomes. No inference involved. See `artifacts/smoke-evidence.json`, `artifacts/memory-smoke.json`, `artifacts/sandbox-probe.json` and discovery report.

Final integrated verification at 2026-10-25T11:02:19Z: **40 tests passed** (unittest 1.486s), including constrained local calculator recovery/error-event provenance and imported-receipt distrust, durable failure latch surviving imports, cycle cursors and prerequisite gates. `artifacts/final-verification.json` preserves raw commands/stdout/stderr/exit codes/times, actual installed extension invocation, real read-only MemPalace hydration, expected failed metadata discovery and explicitly **FIXTURE_NOT_STUDENT** CLI control flow. Throwaway fixture inputs/run were removed after archival. No model call or positive learner baseline was produced. Independent review snapshot `artifacts/evaluation-integration-review.md` predates the final durable-latch repair; the final regression covers that finding.

Detailed metric semantics and limitations: `docs/evaluation.md`. Ten evaluator keys map to factual correctness, source reliability, citation accuracy, mathematical correctness (`math`), tool-call validity, misleading-information detection (`misleading_detection`), error recovery, appropriate uncertainty (`uncertainty`, Brier loss lower is better), procedure generalization (`generalization`), completion reliability (`completion`). Exact citation matching alone proves no source authenticity.

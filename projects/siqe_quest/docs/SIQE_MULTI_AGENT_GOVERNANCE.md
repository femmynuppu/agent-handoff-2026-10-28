# SIQE QUEST multi-agent research governance

## Logical roles, one controlled executor

Roles are logical research competencies and review boundaries, not
automatically spawned processes. The original request explicitly treats them
as such. Production uses a fixed Python allowlist with zero LLM calls, zero
runtime child research events and no autonomous subprocess tree. Human
development orchestration, when separately authorized, can assign a finite
number of scoped subagents; this is not runtime automation and roles never
recursively spawn agents. One workspace-confined durable SQLite queue owns
delivery, leases, attempts, budgets and controls. One `fcntl` lock owns
execution. Resource availability does not justify extra tasks or model
spending.

| Logical role | Responsibility | Required evidence / boundary |
| --- | --- | --- |
| SOURCE_HUNTER | Official catalog/doc discovery and scheduled source freshness | Approved HTTPS origin, actual response, access/robots/license review; four-request freshness cap |
| SOURCE_VERIFIER | Publisher, rights, provenance and timing review | Verifiable immutable descriptors; popularity is not authority |
| KNOWLEDGE_ENGINEER | Supported spans, relations and contradictions | Original evidence hash/span; unsupported claims cannot be promoted |
| CURRICULUM_RESEARCHER | Objectives, practice and independent assessment | Module description is not mastery; retention and applied evidence required |
| QUANT_SCIENTIST | Hypotheses, locked splits, controls and falsification | Retrospective locked research is not prospective preregistration |
| DATA_ENGINEER | Original/normalized vintages and timestamp validation | No fabricated publication time, OHLC, filled holidays or invented observations |
| TRADINGVIEW_ENGINEER | Native Pine artifact and portability review | Actual platform compilation/parity required; generated text alone is NOT_VERIFIED |
| BACKTEST_ENGINEER | Deterministic delayed-fill reference simulation | Costs, baselines, negative results, accounting and execution limitations |
| RISK_AUDITOR | Exposure, leverage, fill assumptions and constraints | Independent tests; indicative references are not executable FX prices |
| SCIENTIFIC_SKEPTIC | Attempt to falsify claimed improvements | Controls, unseen cases, uncertainty and negative transfer; no model-consensus proof |
| RELIABILITY_ENGINEER | Ownership, heartbeat, checkpoints and crash recovery | Current identity plus fresh heartbeat; one observed restart is not lifetime or reboot proof |
| EVALUATION_DIRECTOR | Independent capability and promotion judgment | Critical regression gates, transfer/applied/retention evidence; no automatic fine-tuning |

## Authorization and task ownership

`EventQueue.control('STOP'|'PAUSE'|'RESUME')` is persistent. STOP prevents all
new claims until explicit operator RESUME; PAUSE likewise prevents new claims
while preserving pending work. RESUME changes queue authorization and never
launches a process. Lease completion/failure requires the current owner and an
unexpired lease. Crashes may lead to bounded lease reclaim; payload instructions
do not transfer authority. FINISHED runtime checkpoints can be replayed into
queue completion without rerunning the handler, and default per-event review
records are idempotent. A finite queue, explicit authorization and one-worker
ownership keep automation inspectable; they do not amount to autonomous AI
agents.

Each hook plan carries quest identity, objective, gap, hypothesis, source plan,
required tool descriptions, expected cost, evaluation, acceptance conditions,
safety classification, maximum attempts and stop condition. These are inert
structured data. The executor recognizes exactly fifteen fixed hook kinds;
unknown kinds fail closed. At most eight plan actions are processed per cycle;
queue capacity, depth, child budgets and attempts apply independently. The
worker itself emits zero child events; external callers that deliberately emit
children must satisfy parent/depth/idempotency/budget rules. No worker-per-role
deployment or unlimited retry loop exists.

Only the scheduler authorizes periodic network freshness work, once per
configured six-hour-or-longer window; arbitrary payload URLs never trigger
network calls. Reviews preserve evidence or report BLOCKED prerequisites. A
completed queue item means its finite review concluded, not that its scientific
prerequisite was satisfied.

## Separation of concerns and independent review

Immutable source, strategy, experiment, knowledge and audit records preserve original versions; corrections create new records rather than rewriting history or forecasts. Every supported finding must link verified evidence. Independent numerical validation, negative controls and unseen/retention assessments outrank role consensus. The system does not promote a strategy because a trigger is named STRATEGY_PASSED_RESEARCH_GATE, nor turn a paper's claim into a verified result. No trading, account mutation, withdrawals, publication, unrestricted filesystem access, retrieved instruction execution or model fine-tuning is authorized.

The representative first mission is USD/CAD daily indicative Bank of Canada reference research. Other global market/curriculum capabilities remain individually cataloged with honest evaluation states; a role table is not evidence that every domain is implemented or empirically solved. Source checks and daemon uptime establish operational function only, never measured scientific improvement.

Recovery must retain the corrupt original and snapshot, preserve all scientific
records, and keep incomplete queue events quarantined. The reconstructed
database starts STOPPED; an explicit operator-reviewed RESUME is required before
starting a service. Missing queue audit, request hashes and aliases remain
partial/unknown, and no old event is automatically replayed. See the runbook and
`SIQE_RECOVERY.md` for concrete preservation and review steps. At the latest
recorded service check the transient unit was inactive and the CLI's old
heartbeat stale; generated health reports are timestamped snapshots, not a
current liveness guarantee.

## Development coordination and operator handoff

Development file ownership must be explicit, with one integration owner
resolving shared contracts and no concurrent uncoordinated writes to a file.
Logical runtime roles are not separate running agents. The actual handler is a
fixed allowlist; there is no automatic subagent spawning or event-selected
handler/plugin. The package CLI is the operator interface; the runtime module
also has its own `worker|start|status|stop|pause|resume` choices. The runbook
documents exact supported invocations and distinctions.

The public reference benchmark is independent of the six parent arithmetic/time
cases; neither is blind, sealed or model-unseen evidence. Recovery reconstruction
is limited to 264 valid scientific envelopes; three incomplete operational
events remain quarantined, with queue audit/order `PARTIAL_UNKNOWN`. No automatic
replay is allowed. The latest service check was inactive with a stale CLI
heartbeat; historical service reports are dated snapshots. Test/lint and
service-exercise results in project evidence are historical, not results of
this documentation update.


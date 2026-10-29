# SIQE QUEST auto-hook specification

## Scope: durable planning, not automatic scientific success

`siqe_quest.events` implements SQLite-backed event delivery and deterministic research task planning. A generated quest is an evidence checklist, **not proof that its actions ran**. `dispatch` neither executes tools nor imports code, evaluates payloads, invokes models, starts subagents, or emits additional events. The runtime's fixed allowlisted handlers own execution, evidence recording, authorization checks, and explicit blocked outcomes. Missing source permissions, licensed data, platform results or scientific evidence must remain blocked or unverified; plans cannot manufacture them.

The queue has no broker, publication, account, funds, or live-trading actions. A research gate does not authorize live trading. Retrospective locked experiment registration is not prospective preregistration, and ingestion time is not proof of historical data availability.

## Public constructor and submission schema

```python
Event(
    event_type: str,
    idempotency_key: str,
    payload_reference: dict,
    provenance_reference: dict | str,
    event_id: str | None = None,
    emitted_at: str | None = None,
    observed_at: str | None = None,
    source_id: str = "local_research",
    affected_entities: list[str] = [],  # fresh default_factory list per Event
    source_version: str = "1",
    correlation_id: str | None = None,
    priority: int = 0,
    task_budget: int = 8,
    retry_count: int = 0,
    maximum_attempts: int = 3,
    status: str = "PENDING",
    depth: int = 0,
    parent_event_id: str | None = None,
)
```

The first four arguments are required. `EventQueue.emit` also accepts a dictionary with exactly these fields; omitted optional fields receive the same defaults. Unknown fields fail closed. Validation happens at submission, not dataclass instantiation.

- Event types are the 15 uppercase names below; arbitrary handlers are rejected.
- Payload is a nonempty JSON object reference; provenance is a nonempty JSON object or nonblank string reference. References remain untrusted inert data. They do not grant permissions and are not implicitly dereferenced by this module.
- Envelope must be finite JSON and at most 64 KiB UTF-8. Key/source/version strings must be nonblank and at most 512 characters. Supplied identity/correlation/parent strings follow the same bound. Entities must be a list of at most 100 nonblank strings, each at most 256 characters.
- Timestamps must be timezone-aware ISO8601; `Z` is accepted. `observed_at` cannot follow `emitted_at`. Missing emitted time is generated in UTC at initial insertion; missing observed time equals emitted time. No assertion of historical availability follows from either default.
- Missing event ID is a SHA256 identity derived from `idempotency_key`; correlation defaults to event ID. Callers may supply an event ID but cannot reuse it for a different submission.
- Priority is an actual integer in `[-100, 100]`. Higher values claim first, then creation time and event ID.
- Task budget is an actual integer in `[1, config.task_budget]` (default limit 8); attempts in `[1, config.max_attempts]` (default limit 3); depth in `[0, config.max_depth]` (default limit 3). Booleans are not integers for validation. Caller defaults above remain literal 8 and 3: deployments lowering caps must submit explicit lower values.
- New submissions must have `status="PENDING"` and `retry_count=0`; clients cannot inject delivery state or ownership.

## Exact queue API and returned shape

```python
queue = EventQueue(store)
event_id = queue.emit(event_or_dict)  # str
queue.control("STOP" | "PAUSE" | "RESUME")  # new persistent state str
queue.state()  # RUNNING | PAUSED | STOPPED
claimed = queue.claim(worker_id, lease_seconds=30)  # dict | None
queue.complete(event_id, worker_id, result_dict)  # None
queue.fail(event_id, worker_id, error_text)  # None
queue.events()  # list[dict], creation-time/event-id ordered
queue.stats()  # dict
queue.dispatch(normalized_event_dict)  # list[dict], exactly one checklist quest
```

`events()` and a successful `claim()` return all Event fields with generated identity/times and current status, plus:

| Field | Meaning |
| --- | --- |
| `payload` | Alias of the inert `payload_reference` object; not trusted executable instructions |
| `attempt_count` | Claims started, including the initial attempt |
| `retry_count` | Additional attempts started: `max(0, attempt_count - 1)` |
| `lease_owner` | Worker ID during a claim, otherwise null |
| `lease_until` | UTC epoch seconds during a claim, otherwise null |
| `next_attempt_at` | UTC epoch seconds used for readiness/backoff |
| `remaining_budget` | Available follow-up units after reserving this event's one quest |
| `result` | Completed result JSON object, or null |
| `last_error` | Failure digest summary or fixed lease-expiry explanation, or null |
| `created_at`, `updated_at` | Aware UTC ISO8601 persistence timestamps |
| `tasks` | One persisted quest plan with current durable `status`, `owner`, JSON `result` or null, and UTC `updated_at` |
| `promotion_blocked` | True for contradiction events, false otherwise |

Stats contains `state`, `counts` (present statuses mapped to counts), `total`, `active`, `capacity`, `available`, and `monitoring`. Active capacity includes PENDING, RETRY, CLAIMED and QUARANTINED events. Monitoring is true only with no active work in RUNNING state. No hidden job is created to keep resources occupied.

`QueueFullError` is explicit backpressure. `IdempotencyConflict` (a `ValueError`) rejects content conflicts. `LeaseError` rejects stolen, stale, missing or terminal acknowledgements. Invalid input raises `ValueError`.

## Delivery, ownership and crash recovery

All enqueue, claim, completion, failure and control transitions use `BEGIN IMMEDIATE` on the shared WAL SQLite database. Event body, task plan, state, remaining child budget, idempotency identity and audit rows are committed together. Connections are closed after each operation; no in-memory queue is authoritative. Reconstructing `Store` and `EventQueue` reopens the persisted state and does not reset operator control.

```text
PENDING -> CLAIMED -> COMPLETED
              |          (terminal, no automatic child)
              +-> RETRY -> CLAIMED
              +-> DEADLETTER (attempt limit exhausted)
              +-> expired lease -> RETRY or DEADLETTER
SAFETY_VIOLATION -> QUARANTINED (never claimable)
```

Claim requires a nonblank worker ID of at most 256 characters and finite lease duration in `(0, 3600]` seconds. Each claim increments attempts and atomically assigns event and task ownership. Complete/fail require that exact owner and an unexpired lease; expiry comparison is inclusive. Use a distinct worker ID per running process/worker incarnation, not a shared identity. This API has no lease renewal: work must fit the lease or checkpoint through the runtime before expiry.

A later RUNNING claim reclaims expired leases. Expired work loses ownership; attempts are not reset. If attempts are exhausted it deadletters, otherwise it becomes immediately retry-eligible. A worker process crash after commit leaves its lease visible for recovery. This is at-least-once processing: executors must make externally visible evidence writes idempotent using stable event/quest IDs. Queue durability cannot make arbitrary external side effects exactly-once.

Explicit failure uses exponential delays `min(300, 2 ** (attempt_count - 1))` seconds (1, 2, 4, ... capped 300), without sleeping in the queue. Attempt count is capped by event maximum; exhaustion deadletters both event and task. Raw runtime error strings are not persisted because they may contain credentials: failure state and immutable audit retain a content digest; executors must separately preserve appropriately redacted supporting evidence. The queue does not retry a failed tool through another hook, preventing recursive retry loops.

## Idempotency, caps and bounded follow-ups

Idempotency compares a canonical hash of the complete submitted schema **before** generated defaults are filled. Identical submissions return the original event ID, even if the queue is full or the original event is terminal. Reusing a key with any changed submitted content raises a conflict, not silent data loss. Re-submit the original input, not a returned claim dictionary (which contains additional delivery fields). Replacing an omitted timestamp with a generated returned timestamp is a different submission.

Periodic reviews additionally deduplicate by source ID and configured review interval bucket (`review_interval_seconds`, default 21600), using observed/emitted time if supplied or current epoch time otherwise. Changing only the review event/key/correlation/timestamps within the same bucket reuses the quest; other conflicting body content raises a conflict. Every accepted alias key is itself durably registered, so later conflicting reuse is still rejected. Each distinct interval may have one review per source, not an unbounded flood.

Queue-cap counting and insertion occur under the same write transaction. Terminal completion/deadletter frees active capacity; quarantine deliberately occupies capacity rather than providing an unbounded safety-event bypass. Existing event IDs and plans are never duplicated by re-emission.

An explicit child submission must name an existing nonquarantined parent, use `depth=parent.depth+1`, remain under max depth, and fit the parent's remaining follow-up budget. Every event reserves one unit for its own single quest; allocating a child's whole budget subtracts it atomically from the parent. Thus a root of budget 8 can generate at most 8 total one-unit quests in its declared tree, even if parents complete. Duplicate child submission does not spend again; failed submissions roll back budget changes. No handler automatically recursively spawns; an executor may only explicitly request a justified finite child through `emit`.

## STOP, PAUSE and RESUME

- STOP persists STOPPED and forbids all new claims. Event arrival, reopening a queue, session initialization and periodic scheduling **cannot restart** it.
- PAUSE persists PAUSED and forbids new claims; PAUSE while STOPPED leaves STOPPED.
- RESUME is the sole transition back to RUNNING.
- Existing leased work may acknowledge completion/failure while stopped or paused, preserving evidence rather than silently losing it. Runtime execution must honor control at safe checkpoints; this queue cannot interrupt arbitrary already-running code.
- Submission remains permitted while paused/stopped and is still bounded by queue capacity. No claim or lease reclaim runs until explicit RESUME.

## Fixed hook handlers and meaningful research checklists

Each uppercase event maps to exactly one plan kind equal to its lowercase name. Every plan includes `quest_id`, `kind`, `objective`, `knowledge_gap`, `hypothesis`, `source_plan`, `required_tools`, `expected_cost`, `evaluation_method`, `acceptance_criteria`, `safety_classification`, `maximum_attempts`, `stop_condition`, `source_event_id`, `budget`, `actions`, `promotion_blocked`, `execution_authorized`, and initial `status`.

The quest ID hashes event identity plus checklist version. Actions are an ordered acceptance checklist, **not one separately spawned task each**. One quest costs one task unit, with bounded work allowance `budget`; network allowance is at most four and subject to runtime cycle limits. `required_tools` names research/read/knowledge/report policy families, not payload-provided binaries or arguments. Every action needs an evidence-backed result or explicit reason it is blocked. No numerical outcome is asserted by the plan.

1. **SESSION_INITIALIZED** — Verify workspace identity; load configuration; retrieve operational context; load pending tasks; check interrupted experiments; check resource budget; resume only authorized incomplete work (never override STOP).
2. **KNOWLEDGE_GAP_DETECTED** — Register gap; classify importance; select candidate sources; generate acquisition proposal; estimate cost; add only bounded authorized work.
3. **NEW_SOURCE_DISCOVERED** — Validate domain/publisher; inspect access conditions; check relevance; deduplicate; register source; schedule minimal retrieval validation.
4. **SOURCE_UPDATED** — Identify changed content; preserve versions; reevaluate dependencies; mark stale derived conclusions; target verification.
5. **NEW_RESEARCH_PAPER** — Extract question; identify hypothesis; examine methodology; check data availability; analyze limitations; register reproduction proposal. Stated results remain unverified until examined and independently supported.
6. **NEW_MARKET_EVENT** — Independently verify event; identify markets; resolve instruments/entities; check observation/availability timing; form transmission hypotheses; compare forecasts; schedule bounded research update, not an order.
7. **NEW_KNOWLEDGE_VALIDATED** — Verify evidence before versioned knowledge creation; link original sources; add counterexamples and applicability conditions; save verified procedural lessons; mark outdated knowledge.
8. **EXPERIMENT_COMPLETED** — Persist output; compare locked baselines; audit numerical correctness; preserve negative results; decide whether follow-up is justified.
9. **BACKTEST_FAILED** — Classify failure; check integrity; examine costs/fills; audit leakage; test hypothesis falsification; register explanatory lesson without endless optimization.
10. **STRATEGY_PASSED_RESEARCH_GATE** — Freeze specification; pin approved source version; generate Pine v6 where applicable and independent Python reference; schedule actual parity and forward-paper evaluation. Missing platform evidence remains NOT_VERIFIED.
11. **RETRIEVAL_OR_MEMORY_CONTRADICTION** — Compare dates, definitions and versions; identify supersession; prevent unsupported conflicting claims from promotion. Event, plan, audit and final result carry a persistent promotion block; `complete` cannot clear it. Completion is review completion, not promotion authorization. Downstream knowledge promotion must honor this block and require a separately evidenced resolution.
12. **TOOL_FAILURE** — Classify actual runtime failure; use bounded queue retry; choose only authorized appropriate fallback; preserve redacted evidence; disallow recursive retry hooks.
13. **PERIODIC_RESEARCH_REVIEW** — Review unresolved questions, freshness and queue health; identify useful experiments; rebalance only authorized finite budget, with schedule deduplication.
14. **SAFETY_VIOLATION** — Prevent action; preserve redacted audit; quarantine unsafe tasks; require explicit external authorization for protected operations. Emission immediately quarantines event/task, `execution_authorized=False`; normal workers cannot claim it, and RESUME does not unquarantine it. Research plans cannot self-authorize protected operations.
15. **KNOWLEDGE_DECAY_DETECTED** — Revalidate sources; check definition changes; supersede outdated findings; preserve historical knowledge; never rewrite immutable forecasts.

## Immutable audit and integration checks

Queue-local `hook_audit` rows record emission, claim, completion, failure, lease expiry, control, quarantine and contradiction promotion blocks in the same transaction as their state changes. SQLite triggers reject UPDATE and DELETE. Audit contains hashes/controlled metadata rather than payloads or raw error text. `hook_events` holds durable event ownership and `hook_tasks` holds durable quest ownership/state/results. This supplements core immutable evidence records without changing the core schema.

`tests/test_events.py` supplies unittest cases for reopen durability, an actual subprocess exit after claim, lease theft/stale acknowledgement, backoff/exhaustion, persisted control, concurrent cap enforcement, child budget/depth storms, duplicate/conflicting keys and periodic aliases, quarantine/promotion blocks, all 15 complete checklists, immutable audit and malformed schema/time/budget inputs. The repository suite has since run: 201 tests passed with no failures or errors on 2026-10-27 (about 69.4 seconds); Ruff passed. These unit tests exercise local queue behavior, not every external integration or operational deployment.

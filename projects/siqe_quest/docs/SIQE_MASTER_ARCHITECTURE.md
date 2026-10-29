# SIQE QUEST master architecture
- Continue using project-relative paths inside this cloned handoff; historical `/home/...` path examples refer to the original workstation and are not active service paths.

## Purpose and truth boundary

SIQE QUEST is an isolated, research-only scientific laboratory. Its
representative executed lifecycle uses Bank of Canada USD/CAD daily reference
data; this is not proof of global market coverage, executable FX returns,
prospective preregistration, TradingView parity, measured autonomous improvement
or historical alpha. Code presence establishes an implementation artifact, not
an executed acceptance result. The final execution report, release gates and
immutable evidence records establish what actually ran. A final point-in-time
CLI and user-systemd check observed the transient worker active with fresh,
identity-matched heartbeat at PID 4517. This is not boot persistence, user
linger or a guarantee of future liveness.

The runtime contract is Python 3.10 standard library, SQLite and `unittest`.
No GPU, paid feed, broker, public HTTP listener, hosted LLM or fine-tuning is
required for the representative research path. No unrelated project state is
imported. Retrieved source text and event payloads are untrusted data, never
executable code. A scientific negative finding is retained, not hidden.

## System data flow

```text
operator / bounded scheduled review
    → durable EventQueue → fixed allowlisted Worker handlers
    → official source discovery → source validation → actual acquisition
    → immutable raw evidence → validated observations + dataset manifest
    → locked retrospective hypothesis/spec/splits/baselines
    → delayed-reference simulation + temporal audit + negative control
    → immutable experiment and numerical outputs
    → Pine v6 source + explicit external compile/parity boundary
    → traceable knowledge / independent learning evaluation
    → deduplicated follow-up quest → machine exports / gate report
```

The queue is a coordination mechanism, not a license to invent missing source
access or delegate arbitrary executable work. The scientific pipeline and the
operational service have separate success criteria. A surviving daemon proves
process operation, not financial validity or learning improvement.

## Stable module interfaces

All paths below are in `src/siqe_quest/`. Names specify the integration contract;
executed coverage belongs in evidence, not implied by this table.

| Module | Public interface | Contract / responsibility |
| --- | --- | --- |
| `core` | `Store(root)`, `utcnow()`, `canonical_json(value)`, `digest(value)`, `SafetyError` | Confined workspace, canonical finite JSON, content-addressed blobs, immutable records, safe config and redacted audit |
| `sources` | `SourceHunter(store).discover(gap)`, `.validate(source)`, `.acquire_alpha()`, `.check_updates()` | Official-source discovery and recorded validation; actual raw retrieval, original/normalized observations and versioned manifest; bounded update checks |
| `events` | `Event`, `EventQueue(store).emit(event)`, `.control(command)`, `.state()`, `.claim(worker_id, lease_seconds=30)`, `.complete(...)`, `.fail(...)`, `.stats()`, `.events()`, `.dispatch(event)` | Durable deduplication, provenance, budgets, leases, bounded retries and 15 fixed hook routes |
| `markets` | `coverage_matrix()`, `record_coverage(store, dataset_manifest)` | Sparse next-quest catalog; promote only one matching acquisition cell from stored checked evidence, not scientific completion |
| `research` | `alpha_spec(dataset_id)`, `simulate(observations, spec, mode='candidate')`, `audit_temporal(observations, signal_records)`, `run_alpha(store, dataset)` | Locked retrospective research spec, separated partitions, next-observation proxy fills, baselines, metrics, uncertainty and planted-error audit |
| `knowledge` | `KnowledgeEngine(store).extract(text, evidence, source_id, concept='financial_research')`, `.add_lesson(...)`, `.relate(...)`, `.index()`, `.contradictions()` | Exact evidence-supported text spans, evidence-bound lessons and graph relations, versioning and contradiction visibility |
| `learning` | `Curriculum(store).module()`, `.evaluate()`, `.prioritize(gaps, budget)` | Objectives and exercises; independent deterministic scoring, contamination/transfer/retention boundaries and finite quest prioritization |
| `tradingview` | `render_pine(spec)`, `parity_report(python_output, tradingview_output=None)` | Pine v6 artifact bound to spec hash; compilation/parity remain unverified without genuine platform outputs |
| `runtime` | `Worker(store, handler=None, *, schedule=True).run_once()`, `.run(max_cycles=None, idle_seconds=2)`, `start_service(root)`, `service_status(root)`, `stop_service(root)` | Safe fixed research handlers, optional periodic scheduling and bounded source-review network checks, constrained actual subprocess lifecycle, ownership-aware status and shutdown. Use `schedule=False` for offline work; scheduled network-review events are refused as `BLOCKED` without a network request. |
| `mission` | `run_mission(store, refresh=False)`, `reproduce_mission(store)` | Bounded QUEST ALPHA lifecycle, replaying retained data unless explicit refresh is requested; exact offline numerical reproduction |
| `reporting` | `build_reports(store, mission=None)`, `export_bundle(store, mission=None)` | Eleven evidence-backed local JSON reports plus machine-readable registries/exports and immutable snapshot; no publication |
| `recovery` | `recover_store(root, destination, *, write=False, source_database=..., queue_export=...)` | Offline read-only inventory by default; explicit write constructs a new stopped database and quarantines uncertain queue history, never repairs or installs the source database |


The implemented package is `src/siqe_quest/` rather than the prompt's
illustrative `src/core/`, `src/quant/` and other logical directories; the
prompt explicitly treats those as boundaries, not required empty folders.
Implemented source, SQLite state and immutable blobs, Pine artifacts, JSON
reports, tests, configuration and documentation live in their corresponding
`src/siqe_quest/`, `state/`, `evidence/`, `artifacts/pine_v6/`,
`artifacts/reports/`, `tests/`, `config/` and `docs/` locations. Other global,
world-market and large-scale source/asset categories may occur in the coverage
catalog, but are not thereby source adapters, acquired datasets or tested
research flows.

Practical offline workflow: use `siqe-quest alpha` to run the bounded mission
against retained data, `siqe-quest reproduce` for the retained numerical
reproduction, and `siqe-quest report` to regenerate local evidence-backed
exports. `alpha --refresh` explicitly requests data refresh and may make bounded
network requests. Inspect `siqe-quest status` for a fresh runtime view; a
previously generated report is a dated snapshot. Recovery is a separate
read-only inventory by default; `--write` creates a new stopped destination,
never mutating the original database.
The implemented `mission`, `reporting` and `recovery` interfaces are exposed
through `siqe-quest alpha [--refresh]`, `reproduce`, `report`, and
`python -m siqe_quest.recovery --root ... --destination ... [--write]`. Reports
are written under `artifacts/reports/`, including `reports.json` and the
authoritative `release_gates.json`; recovery instructions and recorded recovery
evidence are in `docs/SIQE_RECOVERY.md` and
`artifacts/reports/recovery_verification.json`. The CLI report/status and
recovery paths preserve evidence rather than implying unimplemented scope.
Alert intake is a separate local authenticated boundary; real TradingView
delivery requires actual platform configuration and evidence.

## Roadmap: executed slices and remaining scope

| Stage | Scope | Observed implementation and execution status | Evidence / limitation |
| --- | --- | --- | --- |
| 0 — Discovery & Bootstrap | Isolated root, environment, versioned config | Verified slice: isolated Python/SQLite workspace, config and entry points exercised. | `artifacts/reports/environment.json`; G0–G1 `VERIFIED_BY_EXECUTION`. No implication of complete system capabilities. |
| 1 — Source Hunter MVP | Official discovery, validation, ingestion | Verified representative BoC FXUSDCAD acquisition: 747 daily indicative observations, 2023-01-03–2025-12-31. | G2–G3 `VERIFIED_BY_EXECUTION`; `artifacts/reports/source_registry.json`, `dataset_manifests.json`. Not executable quotes/PIT; historical first availability unknown; license boundary in `docs/SIQE_SOURCE_HUNTER.md`. |
| 2 — Auto-Hook Engine | Durable events, deduplication, bounded follow-up | Verified local queue/worker behaviors including dedup, leases, STOP/PAUSE/RESUME and bounded processing; not unrestricted autonomous delegation. | G4–G5 `VERIFIED_BY_EXECUTION`; `hook_event_log.json`, tests. Three historical operational events quarantined; no automatic replay. |
| 3 — Knowledge Engine | Evidence-linked extraction, relations, lessons, uncertainty | Verified code and local evidence-backed extraction/index behavior; not general knowledge coverage. | G6 `VERIFIED_BY_EXECUTION`; `knowledge_index.json`; exact-span evidence does not establish correctness beyond checked cases. |
| 4 — Curriculum & Training | Objectives, evaluation, retention and improvement | Partial verified slice: deterministic exercises and 21 public reference cases scored correctly; six arithmetic/time cases were separate and not blind. | G7 `VERIFIED_BY_EXECUTION`; G16 `VERIFIED_BY_EXECUTION` for benchmark execution; G17 `VERIFIED_BY_EXECUTION` records no improvement. No LLM identity/mastery, delayed retention, transfer or weight update; broad scorecard dimensions null/unmeasured. |
| 5 — World Market Data | Broad cross-asset coverage and native conventions | Partial: one USD/CAD indicative reference dataset acquired. Broader world/large-scale markets and source entries are cataloged, not implemented/validated as operational coverage. | G8 `VERIFIED_BY_EXECUTION` for representative versioned dataset only; `artifacts/reports/market_coverage.json`, `docs/SIQE_WORLD_MARKET_COVERAGE.md`. FX alone is not cross-asset fulfillment. |
| 6 — Quant Experiment Lab | Hypotheses, splits, baselines, reproducibility | Verified retrospective experiment and exact numeric reproduction on the reference sample. | G9 `VERIFIED_BY_REPRODUCTION`; `strategy_experiment_report.json`, `backtest_results.json`. Candidate PnL: CAD -11.64835 / +24.8065 / -9.01515 (train/validation/sealed historical 2025); fractional returns -0.001164835 / +0.00248065 / -0.000901515. Retrospective nontradable proxy, not alpha/profit; splits not prospective preregistration. |
| 7 — TradingView Pine v6 Lab | Python reference and Pine artifact with platform comparison | Pine artifact generated; external compile/parity unverified. | G11 `VERIFIED_BY_EXECUTION` (artifact generation); G12–G13 `NOT_TESTED`, classification `MET`. `tradingview_parity_report.json`; no external platform account/compiler evidence. |
| 8 — Backtesting & Robustness | Accounting, temporal checks, negative controls and uncertainty | Verified accounting reproduction and planted-error detection for this scoped experiment; claims do not extend to tradable robustness. | G10, G14–G15 `VERIFIED_BY_EXECUTION` / G10 also has `VERIFIED_BY_REPRODUCTION`; `statistical_robustness_report.json`. Unknown availability, indicative prices, absent carry/spreads/capacity and negative/limited results preclude alpha claims. |
| 9 — Cross-Market Expansion | New independently validated source adapters and end-to-end workflows | Not verified: global/world/large-scale markets appear as coverage catalog entries only, not actual acquisition/validated workflows. | `market_coverage.json`, `docs/SIQE_WORLD_MARKET_COVERAGE.md`; no cross-market completion gate inferred from the BoC slice. |
| 10 — Continuous Scientific Evolution | Follow-up research and controlled learning improvement | Partial operational/research mechanisms exist; no demonstrated unseen-case improvement or trained model. | G17 `VERIFIED_BY_EXECUTION` with `improvement_demonstrated=false`; `evaluation_scores.json`, `docs/SIQE_EVOLUTION_SCORECARD.md`. No delayed retention, transfer or weight update. |
| 11 — Long-Running Reliability | Owned service lifecycle, resource limits, recovery | Verified transient worker run, crash auto-restart (NRestarts=1), STOP/PAUSE/RESUME and configured limits. Fresh check: user unit inactive (MainPID=0), CLI heartbeat stale. Recovery reconstructed 264 valid immutable envelopes byte-identically; three uncertain operational events quarantined. | G19 historical service evidence is a dated snapshot, not current liveness; G20 `VERIFIED_BY_EXECUTION` for limits. `operational_health_report.json`, `recovery_verification.json`, `posix_lock_mechanism.json`, `docs/SIQE_RECOVERY.md`. No reboot/user-linger proof; queue audit/order completeness `PARTIAL_UNKNOWN`. POSIX lock hazard reproduced and fixed by SQLite-owned FD/context closes; not every OS root cause conclusively explained. |

Status strings in this roadmap are the exact allowed gate values where a gate
exists; prose labels such as “partial” describe scope, not an invented gate
status. `artifacts/reports/release_gates.json` is the authoritative current
workspace gate view; reports generated earlier are dated snapshots. Module
presence, unit-test coverage, official source/research results and external or
unseen-learning claims are distinct evidence classes. The full post-recovery
suite result (201 tests passed, zero failures/errors; Ruff passed) is historical
test evidence, not proof of broader scientific or service acceptance.

### Core evidence and storage contract

`Store.root` owns `state/siqe.sqlite3` and immutable evidence. `Store.path(relative)`
rejects external absolute paths, traversal and symlink escape. `connection()`
returns a new SQLite connection with row access, foreign keys and busy timeout;
WAL supports controlled concurrent use. Callers must not alter core schemas.
Connections have single-use context semantics: `with store.connection() as conn:`
commits or rolls back and closes on exit. Connections used outside that context
must be explicitly closed. Do not retain cursors or lazy iterators beyond the
connection lifetime.
SQLite alone opens and closes the database file. Never open/close an auxiliary
`open()`/`os.open()` descriptor for the database inode while SQLite connections
exist: POSIX process-owned record locks can be released by closing any descriptor
for that inode. Initialization fails closed unless the complete `PRAGMA
integrity_check` result is exactly `ok`, before journal-mode changes or schema
initialization; it does not repair or clear damaged data.

- `put_blob(bytes, media_type)` returns `sha256`, relative `path`, byte count and
  media type. `read_blob(reference)` rechecks confinement and content hash.
- `record(kind, key, value)` returns `record_id`, `kind`, `key`, `created_at`,
  `value` and `evidence`. Same key/value is idempotent; changed value requires a
  different version key, never a destructive overwrite. `records(kind)` and
  `get(kind, key)` expose retained history.
- `audit(action, details)` creates redacted immutable audit evidence. Credentials
  never belong in configs committed for research, payloads, logs or alerts.
- `authorize(action)` permits research/read/simulate/knowledge/report actions
  and their qualified forms. Trading, funds/account actions, publication and
  external execution remain denied even if untrusted data requests them.

Configuration defaults: `workspace_id=SIQE_QUEST`, `live_trading=false`,
`fine_tuning=false`, approved domains `www.bankofcanada.ca` and
`www.tradingview.com`, `max_queue=128`, `max_depth=3`, `task_budget=8`,
`max_attempts=3`, `memory_mb=256`, `cpu_seconds=120`, `max_tasks_per_cycle=8`,
`max_network_requests_per_cycle=4`, `review_interval_seconds=21600`.
Source requests and worker cycles must respect bounded budgets; no automatic
LLM subprocesses, paid calls or unbounded recursive tasks are authorized.

### Data and point-in-time boundary

Acquisition returns `dataset_id`, `observations` and `manifest`. The manifest
retains raw/normalized blob references, source identity and version, actual
retrieval time, observed/requested coverage, units, timezone, vintage and
limitations. Core record wrappers remain distinct from dataset manifests.

Each observation preserves date, original and normalized value, event time,
publication time, first availability (`available_at`), ingestion time, timezone,
source revision, vintage and completeness. Unknown historical publication and
availability times remain null, never midnight values disguised as knowledge.
Reject nonfinite/nonpositive, duplicate, out-of-order and weekend FX reference
observations. Missing holidays are not filled. A retrieved current vintage is
not historical as-reported data. No fabricated OHLCV, quotes or exchange hours
are derived from one daily reference number. Adjustment history, delisted
universes, derivative rolls and other data classes require their own source
contracts before use; cataloging them is not implementing them.

### Quantitative and TradingView boundary

The first spec identifies `quest-alpha-usdcad-sma` version 1, `USD/CAD`,
`OTC_FX_REFERENCE`, business-daily reference observations, SMA20/60, long-only,
1000 USD fixed units, CAD 10,000 initial capital, 5 bps commission and a study
assumption of one 0.00001 slippage tick. Signal at observation t can execute
only on a subsequent observation. Flat-start disjoint train 2023, validation
2024 and sealed test 2025 partitions prevent overlapping outcome scoring;
warmup uses earlier observations only. No parameter fitting or holdout search
is part of this baseline.

The hypothesis, strategy and split records were written before computation in
this run: that is a **locked retrospective experiment**, not a prospective
preregistration made before historical outcomes existed. Cash and buy/hold
baselines and a deliberately unrealistic fee-only negative control are
preserved. Metrics need explicit annualization and uncertainty assumptions;
undefined quantities are null. Missing FX carry, financing, executable spreads,
capacity and historical first availability prevent live-alpha conclusions.

The recorded 747-observation BoC USD/CAD run produced candidate net PnL of
CAD -11.64835 (train 2023), +24.8065 (validation 2024), and -9.01515 (sealed
test 2025), equivalent to fractional returns -0.001164835, +0.00248065, and
-0.000901515. These are research-engine outputs on indicative reference rates,
Independent numerical cases, planted leakage/accounting errors and transfer
cases support evaluation. The executed public reference evaluation scored 21
cases correctly; this measures Python engine benchmark results, not an LLM,
unseen-case capability or mastery. `VERIFIED_MASTERY` additionally requires
applied experiment, independent review and delayed retention; a module score
alone does not promote mastery. This run demonstrated no unseen-case
improvement; model weights were not updated and fine-tuning remains disabled.
Events retain identity, payload/provenance references, type, recursion depth and
budgets. Deduplication must reject conflicting same-key bodies. Claim leases
require owner and unexpired lease for completion/failure. Crashed claims can
be reclaimed; retries back off and exhausted work enters dead letter. Persistent
STOP/PAUSE prevents claims until explicit RESUME. Dispatch produces bounded,
fixed-kind plans, not executable text from the internet.

`start_service` launches an actual detached package process with a root-local
log, pidfile, singleton lock and explicit import path. Status checks process
identity and heartbeat, not just PID existence. Graceful stop and bounded kill
must target only verified owned processes. Periodic source checks are bounded;
no public listener or live order capability is implied. The optional user-systemd
transient service is `Restart=on-failure`, `RestartSec=3`, with a limit of three
starts per 300 seconds; it does not promise boot persistence or user linger.
The recorded observed process and current CLI/stop/recreate commands are in the
operator runbook.

A local webhook intake must authenticate exact bytes using trusted-gateway HMAC,
timestamp and durable nonce replay protection, validate finite schema, and
classify delayed/out-of-order payloads. That proves local intake only, not direct
TradingView-to-public-internet delivery or broker execution.


## Acceptance and release reporting

SIQE-G0 through G20 address isolation, discovered runtime, registry/retrieval,
queue/dedup, traceable knowledge, independently scored module, versioned dataset,
reproduced experiment, methodology, Pine artifact, honest compilation/parity,
planted-error detection, preserved negative experiment, independent benchmark,
measured unseen-case improvement or its absence, no live trading, actual service
and resource limits. Each gate needs its own evidence; source acquisition cannot
pass quant/learning/service gates by association.

Allowed gate states are `VERIFIED_BY_EXECUTION`, `VERIFIED_BY_REPRODUCTION`,
`PARTIALLY_VERIFIED`, `IMPLEMENTED_NOT_TESTED`, `BLOCKED`, `FAILED`, `NOT_TESTED`.
A blocked external permission is not a successful reproduction. Coverage
`data_status` is a separate descriptive axis, not an invented release status.

The integration output should export the actual source registry, event log,
knowledge index, hypotheses, experiments, dataset manifests, strategy specs,
backtest results, evaluation scores, provenance references and gate states.
Reports must distinguish implemented code, executed local tests, real financial
observations, retrospective simulations, external-platform verification and
operational process evidence. Synthetic unit fixtures never become market data
or mission evidence. Permanent evolution preserves negative results and stable
interfaces rather than accumulating compatibility shims or speculative adapters.

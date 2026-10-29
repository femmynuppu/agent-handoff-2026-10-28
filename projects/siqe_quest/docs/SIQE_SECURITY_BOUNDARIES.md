# SIQE QUEST security boundaries

## Scope and trust

SIQE QUEST is a research, evidence, simulation, and evaluation project, not a
trading controller. Its workspace, SQLite state, evidence blobs, queue and
memory belong to this project alone. There is no migration from or operational
dependency on unrelated projects. Workspace path confinement and hashes are
application controls, not an operating-system sandbox: a process or user with
workspace access can tamper with local files. Restrict permissions and backups.
SQLite and content hashes do not protect against a privileged local attacker
rewriting the database and evidence store.

Retrieved documents, metadata, market alerts, strategy descriptions and
generated text are untrusted data. They cannot authorize tools, change policy,
supply handlers, grant credentials or promote themselves to verified knowledge.
Source statements, hypotheses, measured results and validated lessons remain
distinct. Persisted memory requires evidence links, preserves contradictions
and revisions, and is not an instruction channel. No AUTOGENESIS M7 data,
service, or configuration is inspected or depended upon.

## Fixed permitted actions and external permissions

- Runtime authorization permits bounded research, reads, simulation, knowledge,
  and reports. Fixed handlers route known event types; incoming text cannot
  select arbitrary Python, shell commands, scripts, tools, or URLs.
- Live trading, broker/exchange account mutation, order execution, leverage
  changes, deposits, transfers, withdrawals, and other movement of funds are
  forbidden. A signal label is not an order. Local simulation and Pine strategy
  artifacts do not authorize account access.
- Model fine-tuning/live training and unreviewed policy self-modification are
  disabled. Curriculum execution and numerical benchmarks are research
  evaluations, not weight training. Improvement requires independent evidence.
- No automatic external publication, upload, outbound messaging, paid account
  creation or credential collection. Reports are local. Publication requires
  explicit authorization and source-rights review.
- No execution of code retrieved from papers, websites, memories, alerts or
  strategy source. No copying of restricted proprietary strategy implementations.

These are application-level restrictions, not an OS sandbox. Deploy under a
low-privilege account and use independent network/filesystem controls where a
stronger perimeter is needed.

## Network and source rights

There is no public HTTP listener or webhook endpoint in this implementation. A running research worker is not an internet-facing server. Local alert intake requires an explicit Python call. Do not expose it by adding a reverse proxy or binding a socket without a separately authorized deployment and threat review.

Research acquisition is currently limited to the approved Bank of Canada HTTPS
origin and finite request/resource budgets; configuration is not permission to
bypass robots rules, licenses, rate limits, authentication, or terms. No
arbitrary alert-supplied URL is fetched. Source discovery does not authorize
unrestricted scraping. Preserve retrieval time, raw/normalized evidence hashes,
publisher/version, attribution, and limitations. Respect redistribution and
derived-use rights before sharing data or artifacts.

The acquired dataset consists of 747 Bank of Canada Valet daily FXUSDCAD
reference observations from 2023-01-03 through 2025-12-31: indicative daily
averages, CAD per USD, not executable quotes or OHLC. Historical first
availability is unknown and the data are not point-in-time vintages. Bank of
Canada attribution is required; underlying LSEG-related restrictions and
redistribution rights remain unknown. Public API access is not unrestricted
redistribution permission. A retrospectively locked experiment is not
prospective preregistration. No result from this proxy alone establishes
tradable alpha or live execution capability.

Relevant source documents: [Valet documentation](https://www.bankofcanada.ca/valet/docs), [Bank of Canada terms](https://www.bankofcanada.ca/terms/), and [robots policy](https://www.bankofcanada.ca/robots.txt). Source validation and current permissions must be reviewed at acquisition time.

The current adapter allowlist is only `www.bankofcanada.ca` over HTTPS; it is
not a global provider-access claim. Source retrieval checks robots policy and
the full extracted visible terms content against its recorded SHA256. Missing
required policy evidence or changed terms blocks retrieval for manual review;
it does not create blanket approval of otherwise matching terms. The connector
caps requests at four per cycle including redirects, each response at 2 MB and
the operation at 8 MB/24 seconds; individual request timeout is at most five
seconds. Queue capacity is 128, plan actions at most eight per cycle, attempts
are finite, and configured task/depth/network budgets have hard bounds. The
periodic scheduler owns at most one freshness check per cycle and enforces its
configured six-hour-or-longer window. A recent three-request `UNCHANGED` check
is evidence of that one authorized check only. Bank of Canada attribution is
required; underlying LSEG-related rights and redistribution remain unknown or
unauthorized. No source response or matching terms fingerprint grants general
redistribution permission.

## Optional local alert interface

`siqe_quest.webhooks.AlertIntake(store, secret: bytes).ingest(body: bytes, headers: dict) -> dict` is an optional local-only intake boundary. It has no socket, HTTP server, broker client, or external delivery configuration. The secret must be independently provisioned with at least 32 bytes; a cryptographically random 32-byte or longer key is recommended. Empty, missing, text, or short secrets fail closed. Never put this key, account passwords, API credentials, or tokens in an alert body, command-line argument, report, or log. The implementation does not log supplied bodies, headers, signatures, nonces, or secrets. Its errors are sanitized. Store file permissions remain important because admitted alert labels and provenance are durable local data.

### Gateway authentication protocol

A separately trusted deployment gateway must send exactly one value for each case-insensitive header:

| Header | Format |
| --- | --- |
| `X-SIQE-Timestamp` | Canonical positive Unix seconds, decimal ASCII, no whitespace or leading zeros |
| `X-SIQE-Nonce` | 16–128 URL-safe ASCII letters/digits/underscore/hyphen; unique per signed request |
| `X-SIQE-Signature` | `sha256=` plus 64 lowercase hexadecimal HMAC-SHA256 characters |

The exact signed bytes are `timestamp_ascii + b'\n' + nonce_ascii + b'\n' + raw_body`. Any raw-body change, including JSON whitespace, requires a new signature. Comparison is constant-time. Gateway timestamp must be at most 300 seconds old and at most 30 seconds ahead of local time. Keep gateway and receiver clocks synchronized. HTTPS/network origin validation at a future gateway is separate from this local HMAC protocol. Do not log authorization material at that gateway either.

Authentication and bounded byte-size checks occur **before JSON parsing or queue changes**. A fresh nonce hash is durably consumed only on valid admission. Nonces are retained rather than expired, so an admitted nonce remains rejected across restarts and clock movement. Operational disk retention requires planning; never prune unexpired replay state casually. Gateway keys remain outside the database; rotation requires coordinated trusted deployment changes, not an alert instruction. Nonce state is workspace-wide, including after key rotation.

HMAC proves possession of a gateway key, **not actual TradingView origin, chart correctness, source truth, or market prices**. Persisted provenance explicitly says `GATEWAY_AUTHENTICATED_SOURCE_CLAIM_UNVERIFIED`, binds raw body and normalized payload SHA256, records gateway/receipt times, and identifies the transport as `LOCAL_CALL_NO_LISTENER`. No credential is persisted in that provenance.

### Strict inert payload

UTF-8 JSON must be a finite object of at most 16,384 bytes, with exactly these seven keys, each a string:

```json
{
  "eventid": "unique-alert-001",
  "instrument": "USD/CAD",
  "timeframe": "1D",
  "signal": "LONG",
  "observed_at": "2026-10-26T10:00:00+00:00",
  "sent_at": "2026-10-26T10:00:01+00:00",
  "source_version": "pine-sma20-60-v1"
}
```

This is a schema example, not evidence of a real received alert. Identities/source versions are bounded ASCII label tokens; instruments and timeframes have bounded inert label syntax. Signal labels are exactly `LONG`, `SHORT`, `EXIT`, or `FLAT`, and never execute trades. `SHORT` is a research observation, not enablement of a shorting strategy. Timestamps must be timezone-aware ISO8601 with `observed_at <= sent_at <= local_receipt_time`. Duplicate JSON keys, nonfinite values, nested objects, unknown keys, credentials fields, URLs, scripts, order/broker instructions, naive/future/inconsistent timestamps, and oversized bodies are rejected. Do not encode secrets in any of the allowed label fields either; the intake cannot prove an arbitrary label is not sensitive. Upstream payload generation must enforce that rule.

### Replay, duplicates, and crash recovery

- A consumed nonce is always a replay, including an otherwise identical legitimate retry. Replays, forged/invalid authentication, and invalid schemas do not change the event queue.
- A legitimate retry uses a **fresh nonce and signature**. An existing `eventid` with the same canonical seven-field payload returns `DUPLICATE` and the original queue event id. JSON formatting may differ; semantic field changes may not. Reusing `eventid` with different payload, including changed source/send time, is rejected.
- Admission and nonce consumption share a SQLite immediate transaction. A durable inbox stores the exact stable queue request before queue submission. `EventQueue.emit` is idempotent under `webhook:<eventid>`; concurrent deliveries and crash-after-emit retry cannot create another event.
- Queue backpressure returns `queue_status: PENDING`, with `event_id: null`; this is durable admission, **not completed queue delivery**. A later fresh signed identical retry resumes delivery. Constructors and rejected requests never flush an outbox, and there is no autonomous outbox scheduler or promise of eventual delivery without retry. A crash after queue commit but before inbox acknowledgement similarly requires a fresh signed retry to acknowledge the already-existing event.
- Ordering is compared per instrument/timeframe/source-version stream in UTC. Older observation time is flagged `out_of_order`; receipt minus claimed send time greater than 300 seconds is separately flagged `delayed`. Delayed or out-of-order data remains research-only and must not be treated as a fresh executable quote. These classifications depend on authenticated but still unverified claims.
- Missing alerts cannot be inferred from these seven fields without a trusted source sequence or heartbeat; returned metadata explicitly reports that limitation. Lack of a message is not proof that no event happened.

### Research routing, not execution

Admission emits only `NEW_MARKET_EVENT`. Payload metadata requires independent market-data verification and explicitly forbids broker orders. The fixed hook plan independently checks source/timing and affected instruments before bounded research. Intake authentication itself **does not perform or establish that verification**. Return status is `ACCEPTED` or `DUPLICATE`, independent of `queue_status: QUEUED|PENDING`; `independent_market_data_verification` remains `REQUIRED_NOT_PERFORMED`.

No actual TradingView account, webhook URL, trusted gateway deployment, gateway upstream authentication, or broker integration is configured here. This custom HMAC header protocol is **not claimed to be directly generated or supported by TradingView alert delivery**. A future authenticated gateway needs its own authorized upstream identity/access controls and HTTPS deployment; merely signing any public request would not authenticate TradingView. Official TradingView alert/webhook settings and any platform limitations must be checked separately before deployment. Pine compilation, real alert delivery, and Python/platform parity remain unverified until actual platform evidence exists.


## Recovery and local integrity

After the recorded SQLite recovery, the corrupt original and snapshots remain
preserved. Exactly 264 valid immutable scientific envelopes were reconstructed
byte-identically with hash-exact blobs; zero invalid, conflicting or missing
scientific evidence. Three historical operational events remain STOPPED in
quarantine. Queue ordering/delivery audit is `PARTIAL_UNKNOWN` because the
export lacks complete hashes, aliases and audit history. Do not infer exact
order or automatically replay old events. Before any new distinct work,
manually reconcile original identities/aliases/tasks, results/audit transitions,
source-health/runtime-review records and logs, leases/partial effects,
checkpoints and webhook replay state; require explicit operator approval.
`control RESUME` changes authorization but does not start a process. See the
operational runbook and `SIQE_RECOVERY.md`.

Store connection contexts commit or roll back and close their owned connection;
they are single-use. Store initialization runs full `PRAGMA integrity_check`
before schema/WAL changes and fails closed. The reproduced POSIX hazard was
Store auxiliary database open/close: closing a descriptor for the same inode
can release process-owned SQLite locks. The fix leaves descriptor lifecycle to
SQLite; connection context-closes were also fixed. These are concrete
reproduced hazards, not conclusive explanation of every aspect of original
corruption. Application controls do not defend against OS locking defects,
hostile mounted filesystems, privileged local attackers or corrupt storage.
No general hostile-code OS sandbox is assumed.

## Legal content and consent boundary

Where an operator-provided policy or terms document governs access, admission
or publication, preserve and evaluate the complete supplied document (including
HTML structure and semantically meaningful sections); a truncated snippet or
partial text match is not evidence of full compliance. Changed legal clauses,
missing sections, ambiguous interpretation or newly blocked permission must be
surfaced explicitly and block the affected action until separately reviewed.
Approval is specific to the exact content/version and scope: it is not sticky,
does not transfer to changed clauses or future versions, and cannot be inferred
from prior consent, a source response or a successful request. This does not
replace applicable source-rights, license, robots, rate-limit or terms review.

Historical full-suite evidence is 201 tests passed with zero failures or
errors in about 69.4 seconds, with Ruff passing; neither was run for this
documentation update. Pine compilation/parity remain `NOT_VERIFIED`, and G12/G13
remain `NOT_TESTED` with classification `MET`. The public 21-case Python
reference evaluation and six separate parent arithmetic/time cases were not
blind, sealed or model-unseen. No LLM identity, mastery, delayed retention,
transfer or demonstrated improvement was measured; no weight update occurred.

The latest service check found the transient unit inactive (`MainPID=0`) and
CLI heartbeat stale. One actual auto-restart (`NRestarts=1`), STOP/PAUSE/RESUME
and resource limits were exercised; no reboot persistence or user-linger
evidence exists. This transient unit does not imply a persistent deployment.

## Operational and evaluation limits

Queue caps, finite task/depth/retry budgets, ownership leases, persisted pause/stop control, bounded reviews, process ownership checks, and local structured evidence are intended to keep research finite and inspectable. These controls do not create a hostile-code execution sandbox or a financial risk engine. A daemon can demonstrate process operation only; uptime is not scientific improvement. Health status must be distinguished from successful research results.

`tests/test_webhooks.py` defines adversarial coverage for signatures and raw-byte binding, replay across reconstruction, concurrent duplicates, conflicting identities, size/schema/timestamps, delayed/out-of-order classification, credential/command rejection, fixed research routing, missing-secret fail-closed behavior, queue backpressure, crash recovery, broker authorization rejection, and absence of network socket creation. Historical execution evidence is stated above; definitions alone are not evidence of passing tests.

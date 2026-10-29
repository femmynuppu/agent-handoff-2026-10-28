# SIQE QUEST knowledge and evidence ontology

## Scope and scientific layers

`siqe_quest.knowledge.KnowledgeEngine(Store(root))` uses only that workspace's
SQLite records and content-addressed evidence blobs. It has no dependency on an
external Engram, MemPalace, embedding server, or another project's database.
Runtime is Python standard library only. This document describes implemented
interfaces, not a claim that every financial domain has been researched.

- **L1 operational memory**: research state, decisions, errors, checkpoints,
  handoffs, and conventions. `remember` records these as operational context,
  never as scientific proof.
- **L2 semantic and procedural memory**: source quotations, attributed structured
  claims, ontology entities/edges, scoped lessons, and dated lifecycle events.
- **L3 scientific evidence**: original source snapshots, datasets, hypotheses,
  forecasts, strategy specifications, experiments, audits, and rejected research.
  The index references existing Store records; summaries cannot update their
  original bodies or replace their evidence blobs.

Every returned knowledge record uses the shared Store envelope:
`record_id`, `kind`, `key`, `created_at`, `value`, and `evidence`.
`value.version` starts at one; changed inputs append a new version with
`previous_id`. Repeating identical inputs returns the existing version. There
are no mutable latest-record aliases. Consumers must inspect lifecycle state,
conflicts, evidence level, and applicability, not infer validity from recency.
Store creation order is the version ordering for this single-workspace engine.

## Evidence semantics

Evidence arguments accept either an original blob descriptor (`sha256`, `path`,
plus optional media metadata) or the exact existing Store record envelope.
Record envelopes are compared with the stored original. Every referenced blob
is read using Store confinement and hash verification; missing, mismatched,
forged, corrupted, or path-escaping evidence is rejected. The knowledge record's
own envelope `evidence` describes its serialized L2 body;
`record['value']['evidence']` contains the actual source/artifact references.
These two roles must not be confused.

`extract(text, evidence, source_id, concept='financial_research')` requires a
nonempty **exact substring** of the original UTF-8 blob. It does not summarize,
normalize whitespace, change case, parse a JSON field into an invented source
passage, or assert that a quotation is true. It records:

- The original excerpt and source identity supplied by the caller.
- Half-open original Unicode codepoint offsets `span.start:end`.
- Half-open original UTF-8 byte offsets `span.byte_start:byte_end`.
- The first exact occurrence if a passage appears repeatedly.
- Verified original evidence hash, `source_quote` level, and unassessed truth.

A raw Bank of Canada JSON response is suitable evidence: pass a phrase literally
present in the raw response, such as a metadata label, rather than an inferred
summary. A string represented with JSON escape sequences must be quoted in its
actual original serialized form. Source identity is attribution, not automated
publisher authentication; source validation belongs to SourceHunter.

Evidence levels are deliberately distinct:

| Level | Meaning |
| --- | --- |
| `source_quote` | Exact original source assertion, not independently verified truth. |
| `source_linked` | Source-linked entity/graph/lifecycle metadata, not an exact quotation or causal proof. |
| `artifact_observation` | Observation in an actual recorded experiment/audit, including rejected procedures. |
| `scoped_procedure` | A procedural interpretation whose recorded explicit checks pass, within its conditions. |
| `independent_replication` | Reserved; never granted by extraction, an individual experiment, or this promotion API. |

Untrusted source text is always inert data. No extracted instruction is executed,
imported, evaluated, sent to a shell, or granted new privileges. Extracted records
set `untrusted_content=true`; retrieval sets `executable_content=false`.

## Procedural lessons and promotion boundaries

```python
engine = KnowledgeEngine(store)
quote = engine.extract(exact_excerpt, raw_blob, source_id, concept='fx')
lesson = engine.add_lesson(
    statement,
    evidence=[experiment_record],
    conditions=['Business-daily indicative reference-rate proxy only'],
    counterexamples=['Same-observation fills invalidate timing checks'],
)
```

The experiment or audit must already exist in the same Store. Its evidence
wrapper, or a genuine blob descriptor nested in its value, is acceptable.
Merely mentioning a hash as text or creating an unrelated blob is not sufficient.
Every supplied reference must match such an artifact. Both `conditions` and
`counterexamples` must be nonempty lists of nonempty strings.

The engine traverses the matched artifact values and records actual boolean
`passed`/`accepted` checks with artifact IDs and exact field paths. Absence of
checks rejects a procedural lesson. If any explicit check is false, the lesson
is retained as `rejected_procedure` at `artifact_observation` level. If all are
true, its status is `scoped_interpretation`, not a verified general trading law.
The statement is explicitly a researcher interpretation, not an exact quotation
from the experiment. Counterexample descriptions are declared failure conditions,
not claims that independent counterexample experiments were run.

`promote(record_id, evidence)` accepts only an accepted procedural lesson,
retaining its original artifact provenance, with no unresolved conflict and no
stale/superseded lifecycle state. It appends an acceptance record whose scope is
`accepted_within_conditions_only`. Rejected lessons, ordinary source quotes,
unsupported claims, missing checks, and contradictory findings cannot be silently
promoted. A promotion is historical evidence of a decision; later conflicts or
decay must be consulted when deciding present usability. It never grants strategy
research approval, independent replication, learned skill mastery, or permission
to trade.

The initial USD/CAD reference-rate experiment is retrospective locked research,

not prospective preregistration. Its indicative daily values do not establish
historically known intraday availability or executable fills. Successful software
checks do not prove profitability or out-of-sample improvement.
In the recorded USD/CAD research, an exact quotation remains a `source_quote`—it records what the source says, not whether the proposition is true. A lesson about the analysis is separately a researcher interpretation and must reference the actual experiment or audit record, whose checks and evidence can be inspected; a quote alone cannot validate it. The acquired source remains immutable and its evidence is hash-verified. The run reconstructed 264 immutable scientific records byte-identically against a clean database after a reproduced SQLite auxiliary-open/POSIX-lock failure mechanism. The original corrupted database and prior recovery state were preserved. Three old operational events were quarantined; queue audit recovery remains `PARTIAL_UNKNOWN`, so event completeness or replay is not claimed.

## Structured claims, contradictions, and graph

`add_claim(subject, predicate, object_id, *, excerpt, evidence, source_id,
conditions, uncertainty=1.0)` stores an exact supporting quotation and a
researcher-indexed assertion. `uncertainty` is a finite value in `[0,1]`, not a
computed probability or calibrated forecast. Claim objects are attributed index
labels; the engine does not pretend to derive their semantics from natural
language. Every new record remains `attributed_not_promoted`.

`contradictions(as_of=None)` conservatively flags different indexed objects for
the same subject/predicate, even when their applicability conditions differ.
This surfaces the need to compare source dates, definitions, versions, and sample
conditions rather than treating lexical matching as a proof of logical
inconsistency. It also flags the same procedural interpretation receiving
accepted and rejected artifact findings, and explicit `contradicts` or
`counterexample_to` graph edges. Original findings remain immutable. Supersession
never silently erases a contradiction; this engine has no automatic conflict
resolution or authority to declare a source correct.

`entity(entity_id, entity_type, label, evidence)` registers an evidence-linked
ontology node. `relate(subject, predicate, object_id, evidence)` appends an
attributed directed edge. Edges may refer to external domain identifiers or
knowledge record IDs; consumers must not assume every endpoint is a registered
entity. Supported scientific chains are:

| Domain | Node types | Representative relation chain |
| --- | --- | --- |
| Market/fundamental | instrument, market, sector, company, fundamental_metric | instrument `traded_in` market; company `in_sector` sector; instrument `issued_by` company; company `has_metric` metric |
| Macro | macro_event, economic_channel, potential_market_effect | event `affects_channel` channel `may_affect` effect |
| Strategy | strategy, indicator, feature, assumption, backtest, result | strategy `uses_indicator` indicator; strategy `uses_feature` feature; strategy `assumes` assumption; strategy `tested_by` backtest `produced_result` result |
| Research paper | research_paper, hypothesis, method, evidence, reproduction | paper `proposes` hypothesis; hypothesis `uses_method` method; hypothesis `supported_by` evidence; hypothesis `reproduced_by` reproduction |
| Error learning | error, root_cause, corrective_rule, regression_test | error `caused_by` cause; error `corrected_by` rule `guarded_by` regression test |

Additional predicates are `contradicts`, `counterexample_to`, `supersedes`, and
`related_to`. A graph edge named `supersedes` is only an attributed relation;
the dated `supersede` API below is required to change a lifecycle projection.
These are supported ontology vocabularies, not claims that all graph chains
already have empirically validated populated financial findings.

## Decay, revalidation, historical queries

- `decay(record_id, reason, effective_at=None)` appends a stale event supported
  by the target's original evidence. It does not change that evidence.
- `revalidate(record_id, evidence, reason, effective_at=None)` requires an
  existing experiment/audit with explicit successful checks. It appends an
  active-state event, never resurrecting a permanently superseded version.
- `supersede(old_id, new_id, evidence, effective_at, reason)` requires a newer
  version of the same knowledge kind and identity. The replacement must exist
  at the effective time. Dates must be timezone-aware and cannot precede the
  relevant records. It appends a permanent supersession event.

These lifecycle APIs apply only to semantic concepts, claims, lessons and
entities. They cannot modify or replace forecasts, hypotheses, raw observations,
trades, metrics, or experiment outputs. Historical evidence is always preserved.
`index(as_of=timestamp)` and `retrieve(..., as_of=timestamp)` include only
records actually recorded by that timestamp. Lifecycle events must also have
become effective by then. A backdated review cannot rewrite what the engine knew
at an earlier recording cutoff. Decay is explicit review-driven; there is no
invented probabilistic truth-decay model or hidden automatic expiry.

## Retrieval and immutable exports

`retrieve(query, entity=None, limit=10, as_of=None)` returns ranked records,
matched terms, a transparent overlap score, evidence level, contradictions,
`usable_as_current`, and `executable_content=false`. It searches concepts,
claims, lessons, entities and edges. The optional exact entity filter matches
subject, object, entity ID, concept or source ID. Limits are integers 1–100.

Tokenization is case-insensitive with a small explicit financial synonym map
(e.g. FX/foreign exchange, SMA/simple moving average, leakage/lookahead).
No heavyweight embeddings, learned semantic equivalence, automatic causal
inference, or arbitrary code execution are involved. Stale/superseded/conflicting
records remain retrievable for audit but are not marked usable as current.
`usable_as_current` is a lifecycle/conflict flag, not a promotion or truth claim.

`index()` returns JSON-native `layers`, `evidence_levels`, `ontology`, `concepts`,
`claims`, `lessons`, `entities`, `graph`, `operational_memory`, `lifecycle`,
`promotions`, `scientific_evidence` and `contradictions`. Every referenced blob
is reverified during indexing/retrieval. `export()` writes immutable
content-addressed JSON blobs and returns descriptors under `index`, `lessons`,
and `graph`; the graph export includes nodes, relations, and the ontology.
Integration may copy those JSON contents to a human-facing report, but cannot
use that report to replace the original evidence.

## Executable boundary coverage

`tests/test_knowledge.py` provides unittest cases for exact Unicode/byte spans,
raw JSON extraction, evidence mismatch/missing evidence/forged record rejection,
source tampering detected on retrieval, procedural acceptance and rejection,
nested-artifact membership, unsupported promotion, immutable contradictions,
explicit counterexamples, dated decay/revalidation/supersession, frozen forecast
preservation, lexical/entity retrieval, meaningful JSON exports, workspace
isolation, and inert instruction-looking content. The repository suite has since
run: 201 tests passed with no failures or errors on 2026-10-27 (about 69.4 seconds);
Ruff passed. These results cover the exercised local code, not every external
integration or the truth/completeness of all financial-domain knowledge.

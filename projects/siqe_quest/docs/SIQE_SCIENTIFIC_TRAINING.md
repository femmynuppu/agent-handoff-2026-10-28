# SIQE scientific training and evaluation

## What is implemented

`siqe_quest.learning.Curriculum(store)` supplies the stable `module()`, `evaluate()` and `prioritize(gaps, budget)` interfaces. Runtime dependencies are Python's standard library and the project's SQLite evidence Store. No network, model call, GPU work, code downloaded from sources, or weight training occurs in this subsystem.

The complete introductory module `quest-financial-foundations-v1` teaches returns, probability, causality and CAD-per-USD reference-rate research. It includes prerequisites, six objectives, official-source discovery plans and validation requirements, exact-excerpt extraction requirements, explanatory rules and failure examples, four worked practice exercises, separate deterministic assessment cases, applied research linkage, independent-review requirements and delayed retention requirements. Source links are discovery candidates, not assertions that the material was retrieved or validated. NIST is deliberately not in the default source allowlist: discovery does not authorize retrieval.

The full requested mathematics, economics, finance and quantitative-research topic lists appear in `module()['catalog']` and `benchmarks/catalog.json`. Most topics are **catalog-only / not tested**; catalog presence does not mean 61 topics were demonstrated. Introductory Probability, Exchange rates, Financial accounting, Transaction cost analysis, Execution simulation and Applied econometrics have partial coverage in this single module, not complete advanced-domain implementations or mastery. All five logical benchmark families and their requested domains are represented in the catalog with explicit implementation status and case IDs. A catalog row is neither training nor measured performance.

### Module objectives and procedure

The module's six introductory objectives are implemented as a bounded learning sequence: distinguish simple and compounded returns; apply expectation, variance and Bayes' rule; separate observed association from causal identification; interpret USD/CAD quote direction and cross-rates; account for cash, fees and balance-sheet consistency; and detect availability/lookahead and execution-timing errors. For each research gap, the procedure is to discover an official candidate, validate permission and source identity, preserve an exact evidence span, state conditions and counterexamples, run deterministic exercises, then link applied review and delayed retention as separate evidence. The module supplies these plans, practice and tests; it does not establish completion of the wider curriculum.

## Four different learning mechanisms

1. **Knowledge acquisition:** retrieve authorized reliable material, verify it, preserve original evidence and supporting spans, and make it retrievable. This does not change model weights.
2. **Procedural skill learning:** version a reusable procedure with preconditions, tools, data, steps, expected outputs, known failure cases, acceptance tests and provenance. A candidate is not an improvement merely because it exists.
3. **Empirical policy improvement:** compare workflows, retrieval or tool selection under controlled conditions. Promote only with correctly scored independent unseen outputs, positive net correctness gain and no critical correctness regressions.
4. **Model fine-tuning:** disabled. It requires separate explicit authorization, available suitable weights, permissive licensing, training-data rights, sufficient compute, an independent protocol and a justified benefit/cost case. Reading, prompting, memory storage and this evaluator are not fine-tuning.

## Assessment, independence and exposure

`evaluate(responder=None)` executes the frozen 21-case `quest-foundations-reference-v1` suite. The default responder is a real numerical implementation, `reference_answer(operation, input_dict)`. An optional trusted in-process callable with the same signature can be evaluated; retrieved content is never made a callable. Each expected answer is a fixed hand-derived literal independent of the implemented formula and worked practice examples. Numeric answers use `1e-10` relative and absolute tolerance; booleans require actual boolean type; errors require the exact expected exception class. Scores count correct outputs, never agreement between models.

These fixtures are publicly visible in source. They are held apart from practice examples but **not sealed from the model or developer**. The recorded run scored all 21 public reference cases correct (and six additional parent-run cases); this measures the deterministic Python reference engine, not unseen LLM capability. `evaluate()` reports `unseen_to_model=false`, `mastery=NOT_VERIFIED`, `training_performed=false`, `model_weights_updated=false`, and `improvement_demonstrated=false`. No unseen transfer, improvement, verified mastery, delayed retention, or model-weight update was established. Parent-run independent audits retain their own provenance and exposure accounting rather than relabel this public suite unseen.

Before executing answers, the evaluator records an immutable manifest containing version, all exact cases and answers, tolerances and practice IDs. SHA-256 is computed over the core canonical JSON representation. Reusing a benchmark version with changed content raises a Store conflict: changes require a new version. Every attempted evaluation records exposure **before** running answers. Repeated evaluation increments exposure; it is not fresh independent evidence. The static catalog intentionally leaves the actual runtime manifest hash null until evaluation; the immutable record and returned `manifest_hash` supply the real hash rather than an invented run artifact.

These fixtures are publicly visible in source. They are held apart from practice examples but **not sealed from the model or developer**. Passing them measures the reference implementation, not unseen LLM capability. `evaluate()` always reports `unseen_to_model=false`, `mastery=NOT_VERIFIED`, `training_performed=false`, `model_weights_updated=false`, and `improvement_demonstrated=false`. Its transfer statement explicitly says **NO DEMONSTRATED IMPROVEMENT** without a real controlled unseen benefit. Parent-run independent audits must retain their own provenance and exposure accounting rather than relabel this public suite unseen.

Return fields include `benchmark_version`, `manifest_hash`, `exposure_record_id`, `exposure_number`, `previous_exposures`, `case_count`, `correct`, `accuracy`, per-case `results`, `by_domain`, `scorecard`, scientific limitations, and the persisted evaluation's `record_id` and `evidence` descriptor. Per-case error output records exception type, not potentially sensitive exception text. Invalid opaque/nonfinite responder output is counted wrong and described safely.

## Applied learning and retention

The applied task is to audit the independently registered USD/CAD SMA reference-rate experiment: verify units and returns, inspect lagged execution and adverse costs, compare cash and buy-hold, retain both positive and negative results, and review the temporal audit. Registration before calculation is a **retrospective locked research plan**, not a historical prospective preregistration. The observations do not establish historical first availability. Daily reference rates are indicative, nontradable fill proxies, not bid/ask, tick data or real executed alpha.

`mastery(evaluation_id, experiment_id, review_id, retention_id)` accepts only linked Store records. It requires a perfect deterministic assessment, an existing applied `experiment`, and an independent passed `learning_review` with `reviewer`, `module_id`, `evaluation_id` and `experiment_id`. A negative applied strategy result may still support mastery if the procedure and interpretation are correct; profitability is not the learning criterion.

A `learning_retention` must link the initial evaluation and module, identify an independent reviewer, have `passed=true` and `independent=true`, identify fresh disjoint `case_ids`, and provide an actual `tested_at` at least 86,400 seconds after the initial evaluation and not after its record creation. Its `results_evidence` descriptor must resolve to a hash-verified Store blob containing `{"cases":[{"id":"fresh-id","expected":...,"observed":...}]}`. Actual answers are independently re-scored and IDs must match the retention record. A future-dated claim, re-running public cases, a summary, or a fake evidence label fails closed. The method relies on the reviewer's real independent attestation for conceptual and applied quality, and reports this scope. Immediate runs cannot manufacture elapsed retention evidence.

## Skill and policy promotion

`compare(baseline_callable, candidate_callable, candidate_version)` runs a paired comparison on the same public suite, records accuracy delta and every lost previously correct case as a critical regression, and **never** qualifies it as unseen promotion evidence.

`promote(candidate, comparison_id)` accepts only skill/policy specifications with all procedural fields. It requires a `controlled_comparison` record with:

- `candidate_version`, `controlled=true`, `independent_unseen=true`, and actual `cases` containing `id`, `baseline_correct`, `candidate_correct`;
- `frozen_manifest_hash` referencing the digest of an existing immutable `sealed_benchmark_manifest` value with `cases` containing independent `id` and literal `expected` keys;
- `outputs_evidence`, a verified blob containing `cases` with `id`, `baseline_output`, `candidate_output`;
- `review_id` referencing an independent passed `learning_review` with `reviewer`, `verified_unseen=true` and the `comparison_key` of the comparison.

The evaluator re-scores the immutable actual outputs against the frozen key, requires one output for every unique key and exact agreement with the recorded correctness flags, checks freeze time before comparison creation, rejects public-suite IDs and duplicates, requires a positive correctness count delta and rejects any lost baseline-correct case. Independent-review attestation remains necessary to establish that cases were genuinely inaccessible to the candidate: a filename or hash alone cannot prove secrecy. Accepted skill/policy records include the complete candidate and evidence-linked decision. This path does not imply any model-weight update.

## Finite QUEST priorities

`prioritize(gaps, budget)` returns at most the configured queue bound, never exceeds the finite total expected-cost budget, deduplicates objectives/gaps, skips exhausted/stopped/rejected/completed gaps and rejects nonresearch safety classes or invalid/zero/nonfinite costs. Factor inputs are in `[0,1]`: uncertainty, research relevance, information gain, evidence, source quality, reusability, testability and market relevance; error history is a nonnegative count. Quality and testability multiply relevance and expected gain per cost, so cheap unsupported activity does not automatically win. This is an explicit transparent heuristic, not an empirically optimized intelligence metric.

Each selected quest includes all required identity, objective, gap, hypothesis, source plan, tool, cost, evaluation, acceptance, safety, bounded attempt and stop-condition fields. Attempts are capped at three or the lower configured/candidate cap. Stop conditions include exhausted attempts/budget, failed rights checks, no measured gain, critical regression and explicit STOP. Returned plans do not authorize network actions or execute themselves. Costs are bounded estimates in declared work units, not fabricated measured token costs; the worker remains responsible for actual resource enforcement. Priorities do not reward GPU or token consumption.

## Sixteen-dimensional scorecard

A source discovery precision; B source verification accuracy; C relevant retrieval; D mathematical correctness; E financial reasoning correctness; F tool routing effectiveness; G backtest reproducibility; H false approval rate; I strategy robustness; J forecast calibration; K TradingView/Python parity; L skill transfer; M operational reliability; N cost per verified result; O regression rate; P unseen-task performance.

The evaluator returns every dimension. Only D/E receive narrowly scoped actual reference-case correctness after execution. All other values remain **null / UNMEASURED**, including unseen transfer, calibration, TradingView parity and cost per verified result. No arbitrary intelligence percentage or model-consensus metric substitutes for this vector. An improved version requires independently measured benefit and absence of critical regressions.

## Verification boundary

The integration run completed 201 tests with no failures or errors; Ruff reported all checks passed. Its evaluation scored 21/21 public reference cases, plus six additional parent-run cases, correctly on the Python reference engine. No LLM capability, unseen transfer, improvement, mastery, delayed retention, or weight change was measured. Runtime evaluation and immutable run records are the authoritative detailed evidence. For a focused developer run, from project root use `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_learning.py' -v`; that command is a reproducibility instruction, not a separate result claimed here.

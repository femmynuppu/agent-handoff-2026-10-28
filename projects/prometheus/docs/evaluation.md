# Curriculum and deterministic evaluation

## Scope and safety

This is an offline standard-library evaluator and an original ten-domain teaching bank, not a measured learner improvement. No Hermes/model invocation is required or authorized. The prior pilot is preserved in `artifacts/prior-audit.md`: eight exposed financial cases are excluded from the new bank. Its 100/100 ceiling scores do not establish gains.

`curriculum/graph.json` defines ten dependency-aware nodes. `curriculum/lessons.json` provides one actual lesson per domain, stable lesson and competency IDs, objectives, prerequisite IDs, retrieved required sources, a worked example, a different practice exercise, evaluation criteria and remediation. `references/private/lesson-map.json` alone links lessons to baseline and heldout candidates. Each domain has practice P, baseline B and heldout H forms (30 tasks total). Ten new heldout candidates are still same-teacher authored and often near-transfer, not an independent benchmark. All 30 prompts were reviewed to remove prescribed chosen conclusions, countermodels, debugging fixes and derived values. Input facts, available action/label names, units and citation formats are legitimate task specification.

A practice attempt precedes **at most three corrective remediation iterations**, for four total practice attempts. Lesson `evaluation.max_attempts=4`; `remediation.max_corrective_iterations=3`. Do not interpret the cap as three additional remediations after a fourth corrective iteration. Stop for human review after exhaustion. Prerequisites require reviewed evidence; an arithmetic/schema pass does not grant mastery.

### Private is a data boundary, not OS isolation

Teacher tasks and answers live in `references/private/tasks.json` and `solutions.json`. This directory name does not prevent a same-UID terminal from reading them. Before any real learner evaluation, place teacher references and holdout task bank outside the learner filesystem/API namespace; use an actual container/VM/restricted user and mount only exported packets. Do not mount the repository, teacher transcripts, session databases, grader keys or answer-bearing smoke inputs. No directory-only sandbox claim is made here.

`export_task` uses an allowlist. It returns task ID, domain, question, response schema, instructions, required reference IDs, metric applicability, calculator request when applicable, and narrow frozen sources. It excludes solutions, checks, explanations, human answer rubrics, split labels, teacher paths and private linkage IDs. A stable task ID is the sole needed assessment identifier. Lessons include worked answers by design, but the exercise is distinct. Grade reports contain expected values for teacher audit: **never pass a grade report as an unseen-task packet**. Correct smoke/unit responses are evaluator fixtures, not student outcomes.

## Commands

Run from the project root; no installs or paid APIs:

```sh
python -m prometheus.evaluation validate-curriculum
python -m prometheus.evaluation export-task B04 --output /tmp/public-task.json
python -m prometheus.evaluation grade --task-id B04 --response /path/to/response.json
python -m prometheus.evaluation grade --task-id B08 --response /path/to/response.json --receipts /path/to/imported-receipts.json
python -m prometheus.evaluation baseline-report
python -m prometheus.evaluation baseline-report --results /path/to/grade-results-list.json
python -m unittest discover -s tests -p test_evaluation.py -v
```

Optional `--root PATH` precedes the subcommand. Output flags write the requested JSON without silently creating parent directories. Exit 0 means valid curriculum/export/report or deterministic grade pass; exit 1 means invalid curriculum or deterministic grade failure; exit 2 means input/file/unknown-task error. Unknown task IDs fail explicitly. A missing baseline results file is an input error, while omitting `--results` produces an honest NO_REPORTS summary.

`artifacts/evaluation-baseline-tasks.json` is a public prompt-only inventory, not student results. `artifacts/evaluation-empty-baseline.json` is an observed empty report, not a student run. `artifacts/evaluation-smoke.json` records actual evaluator commands/assertions and outcomes. They do not show a model baseline.

## Python contract

- `load_json(path)`: strict finite JSON with duplicate-key rejection. NaN, Infinity, exponent overflow, and non-JSON Python containers are rejected. JSON booleans never count as numeric, including nested exact comparisons and calculator arguments/results.
- `validate_curriculum(root=DEFAULT_ROOT)`: returns `{valid, errors, lesson_count, domains, security_boundary, evidence_status}`; validates prerequisite DAG, ten-domain coverage, lesson contracts, source excerpt hashes and per-domain practice/baseline/heldout availability.
- `export_task(task_id, root=DEFAULT_ROOT)`: returns only the student allowlist packet, raises `ValueError` on unknown task.
- `grade_response(task, reference, response, receipts=None)`: returns deterministic checks and metric slots; no model judge, code evaluation, arbitrary shell execution or memory writes.
- `execute_calculation(task_id, call_id, operation, operands, *, fault=None)`: executes only add/subtract/multiply/divide of two finite JSON numbers using rational internal arithmetic. Optional declared `fault="temporary_unavailable"` returns an actual local service failure event instead of computing; all other injected faults fail input validation. It returns a process-local observed receipt, not a serialized authority token.
- `CalculatorRecoveryScenario(task_id, operation, operands).call(call_id)`: bounded runner, first call returns the declared recoverable service failure, second distinct-ID call performs the calculation, third call is refused. Receipts have process-local event sequence. Caller supplies actual response, diagnosis and claimed calls separately; the runner generates no learner answer.
- `baseline_report(results, expected_domains=None)`: summarizes baseline-only unique task IDs, excluding repeated or invalid records. `descriptive_report_count` counts supplied reports, **not genuine student runs**; `student_run_count` stays null without an authenticated runner manifest. Always `INSUFFICIENT_DATA`; imported grade JSON is not authenticated. Invalid-input reports are separated from competence outcomes. Malformed metric types and invalid numerator/denominator/value invariants are reported and excluded from metric aggregates. It makes no improvement, p-value or reliability claim.

Every grade has `deterministic_pass`, `needs_human_review=true`, `integrity_flags`, `status`, `checks`, `metrics`, `human_review`, `mastery_authorized=false`, and `overall_evidence_status=INSUFFICIENT_DATA`. Status is INVALID_INPUT, DETERMINISTIC_FAIL or DETERMINISTIC_PASS. Per-check evidence identifies the field, observed/expected value where relevant, tolerance or receipt match, and an error class. Unknown/mismatched task/reference cannot yield a pass. Pass threshold is all specified checks (1.0); any missing/invalid schema field fails completion. Nonempty rationale is required but its semantics are **not** auto-graded.

### Receipt trust

A response's `tool_calls` contains claims with `call_id`, `tool`, `operation`, `operands`, `result`. Separate receipt shape is:

```json
{"source":"runner-name","task_id":"opaque-task-id","call":{"id":"opaque-call-id","tool":"calculator","arguments":{"operation":"add","operands":[2,5]}},"result":{"call_id":"opaque-call-id","status":"success","value":7}}
```

This JSON is **not cryptographic evidence**. Importing it via CLI or copying/serializing a local receipt always yields UNVERIFIED_IMPORTED, regardless of claimed source/trusted flags. The evaluator can record structural agreement but tool validity remains null/NOT_MEASURED, the required execution check fails, and no memory/mastery authorization is issued. Boolean receipts, missing call/results, duplicate call IDs, mismatched task/arguments/results and mutated local receipts are rejected as execution proof.

Only the exact unmodified object returned by this process's `execute_calculation`, retained in its private local registry, is OBSERVED_LOCAL. This proves the evaluator's constrained calculator executed that request, **not that Hermes independently chose or used it**. The response must match actual call and result evidence. Serialization deliberately loses trust. This mechanism is not a security boundary against malicious code inside the evaluator process. Both observed and imported receipts leave `mastery_authorized=false`.

P08/B08/H08 include the controlled recovery scenario. The first failed claim has `status="failed"` and its observed `error_code`; the successful retry claim has a numeric `result`. `recovery_diagnosis` must identify the actual error code. Grading requires the matching actual local failed event before a distinct-ID valid successful retry, correct arguments/result and diagnosis. A JSON file saying this transition occurred remains UNVERIFIED_IMPORTED and gives null tool/recovery measurements. A mere successful call without failure, reversed sequence, missing diagnosis, or third retry does not satisfy recovery. This is a deterministic infrastructure fault design, not a report that any learner encountered or recovered from it. Current A2A controller does not supply authenticated tool-event receipts; HTTP response observation alone cannot measure tool execution or recovery.

## Metrics and interpretation

All ten keys always appear. Each metric carries `status`, `value`, `numerator`, `denominator`, `method`, and `evidence`. Missing/unsupported measurements are null/NOT_MEASURED, not zero or pass. The task packet records applicability: deterministic, human-review-only, or NOT_MEASURED. Raw outcomes remain separate from human scores, integrity issues and study design. There is no omnibus percentage.

| Key | What is actually measured |
|---|---|
| `factual_correctness` | Exact finite-fixture answers, type-safe nested structure; human rationale correctness remains NOT_REVIEWED. |
| `source_reliability` | Synthetic conflicting-record selection in research tasks only. No authentic source retrieval, issuer identity verification or broad reliability estimate. |
| `citation_accuracy` | Exact full narrow excerpt and locator against a frozen supplied source; all submitted citations must resolve. This measures citation mechanics, not whether a methodological quote entails a synthetic mass or other unrelated fact. |
| `math` | Numeric comparisons using explicit per-check `abs_tol=1e-9`, `rel_tol=1e-9`; acceptance is absolute error <= max(abs_tol, rel_tol*abs(expected)). Rational-string answers use exact reduced representation. |
| `tool_call_validity` | Actual locally observed constrained-calculator call/result matching only. Unverified imported receipts never produce a tool execution score. |
| `misleading_detection` | Balanced supported/misleading fixture labels with TP/FP/TN/FN, precision/recall where defined; missing labels reported. No robustness guarantee. |
| `error_recovery` | P08/B08/H08 actual constrained-service failure, diagnosis and bounded valid retry transition, only with process-local observed receipts. NOT_MEASURED when unrun or only imported JSON exists. Static debugging alone is not runtime recovery. |
| `uncertainty` | Binary Brier mean squared loss on a submitted finite probability and sealed realized outcome; lower is better. A valid probability passes format, not forecast correctness. One realization is not calibration/reliability evidence. Invalid probabilities have no Brier value. |
| `generalization` | NOT_MEASURED: candidate heldout same-teacher forms are insufficient independent far-transfer evidence. |
| `completion` | Required fields/types, no unknown fields, nonempty rationale. Schema completion is not substantive correctness. |

Error classes include SCHEMA_ERROR, MISSING_FIELD, FACTUAL_MISMATCH, ARITHMETIC_MISMATCH, INVALID_NUMERIC_VALUE, CITATION_MISMATCH, MISLEADING_CLASSIFICATION_ERROR, UNVERIFIED_TOOL_EXECUTION, RECOVERY_TRANSITION_NOT_OBSERVED, and explicit invalid-reference/input integrity flags. Human review is separately blinded to training condition where possible, with criteria and evidence spans; it remains NOT_REVIEWED until an actual independent reviewer performs it. No hidden rubric score is invented by this module.

## References

`references/manifest.json` records requested and resolved URLs, UTC retrieval timestamp, tool, successful/failed/partial status, exact narrow quotation and location, explicit domain mapping, excerpt SHA-256, and access/license limitations. Hash scope is the exact stored UTF-8 excerpt, **not** full remote HTML/PDF bytes. Successful numeric HTTP status is null because `read` did not expose it; a readable response is recorded as RETRIEVED. SEC 403 and IFRS cookie-only content are retained as failures/partial and not counted. Ten useful retrieved references cover all domains, including official Python/Lean documentation, W3C PROV, RFC8259, US Treasury statement/bill guidance, scikit-learn Brier documentation and OWASP maintainer guidance.

Narrow quotations only are frozen in `references/sources.json`; no copyrighted full-copy corpus. Retrieval is not license clearance, and methods documentation is not empirical proof. The W3C response was an API abstract, not the complete specification. Treasury PDF extraction/typography should be checked against the original for publication. Prior-audit candidate URLs remain explicitly unverified in that historical document.

## Actual baseline still required

Before inference is authorized, freeze an isolated learner profile, source snapshots, task/split manifest, model and reasoning identity, tool budgets, independent heldout references and controlled comparison design. Prior learning exposure and existing finance skill must be disclosed. Hide feedback until evaluation completes. Use independently authored task families and a sample size chosen for a predeclared precision/effect target. Until then publish only raw descriptive outcomes and INSUFFICIENT_DATA. Empty results have every metric null, descriptive report count zero, and student-run count null; never manufacture baseline answers or infer capability from evaluator unit tests.

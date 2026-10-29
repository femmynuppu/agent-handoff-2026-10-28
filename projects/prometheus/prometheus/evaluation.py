"""Offline deterministic grading. No inference, arbitrary code execution or memory writes.

Imported receipts are unverified data. Only receipts returned by this process's
constrained calculator carry local observation identity; serialization loses it.
Even local observation does not authorize mastery or persistent memory.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any

METRICS = (
    "factual_correctness", "source_reliability", "citation_accuracy", "math",
    "tool_call_validity", "misleading_detection", "error_recovery", "uncertainty",
    "generalization", "completion",
)
DOMAINS = (
    "epistemology", "research", "math", "statistics", "financial_statements",
    "quant_finance", "software_debugging", "tool_workflows",
    "adversarial_reasoning", "uncertainty_decision_theory",
)
DEFAULT_ROOT = Path(__file__).resolve().parents[1]
GRADER_VERSION = "1.0.0"
_LOCAL_RECEIPTS: dict[int, tuple[dict, str]] = {}


def _json_value(value: Any) -> bool:
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_json_value(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _json_value(item) for key, item in value.items())
    return False


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-JSON numeric constant: {value}")


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: str | Path) -> Any:
    """Read strict JSON, rejecting duplicate keys, NaN, infinity and overflow."""
    value = json.loads(Path(path).read_text(encoding="utf-8"),
                       parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    if not _json_value(value):
        raise ValueError("Input contains non-finite numbers or non-JSON values")
    return value


def _canonical(value: Any) -> str:
    if not _json_value(value):
        raise ValueError("Not a finite JSON value")
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


def _numeric(value: Any) -> bool:
    return type(value) in (int, float) and (type(value) is int or math.isfinite(value))


def _number(value: Any) -> Fraction:
    if not _numeric(value):
        raise ValueError("A finite JSON number is required; booleans are not numbers")
    return Fraction(str(value))


def _equal(left: Any, right: Any) -> bool:
    """JSON structural equality without Python's True == 1 coercion."""
    if _numeric(left) and _numeric(right):
        return _number(left) == _number(right)
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    if type(left) is list:
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    return left == right


def _near(observed: Any, expected: Any, abs_tol: Any, rel_tol: Any) -> bool:
    a, b = _number(observed), _number(expected)
    absolute, relative = _number(abs_tol), _number(rel_tol)
    if absolute < 0 or relative < 0:
        raise ValueError("Numeric tolerances must be non-negative")
    return abs(a - b) <= max(absolute, relative * abs(b))


def _metric() -> dict:
    return {"status": "NOT_MEASURED", "value": None, "numerator": None,
            "denominator": None, "method": "No applicable independent observation",
            "evidence": []}


def execute_calculation(task_id: str, call_id: str, operation: str,
                        operands: list[int | float], *, fault: str | None = None) -> dict:
    """Execute a tiny allowlisted arithmetic tool and retain process-local identity.

    This is not Hermes execution or a general terminal. A caller cannot turn an
    imported receipt into an observed one by setting a JSON 'trusted' flag.
    """
    if type(task_id) is not str or not task_id or type(call_id) is not str or not call_id:
        raise ValueError("Nonempty task and call IDs required")
    if type(operands) is not list or len(operands) != 2:
        raise ValueError("Exactly two finite numeric operands required")
    a, b = map(_number, operands)
    operations = {"add": lambda: a + b, "subtract": lambda: a - b,
                  "multiply": lambda: a * b, "divide": lambda: a / b}
    if operation not in operations:
        raise ValueError("Unsupported calculator operation")
    if fault not in (None, "temporary_unavailable"):
        raise ValueError("Unsupported declared calculator fault")
    if fault:
        outcome = {"call_id": call_id, "status": "failed", "error_code": fault, "recoverable": True}
    else:
        value = operations[operation]()
        result = int(value) if value.denominator == 1 else float(value)
        if not _numeric(result):
            raise ValueError("Non-finite calculator output")
        outcome = {"call_id": call_id, "status": "success", "value": result}
    receipt = {"source": "local_constrained_calculator", "task_id": task_id,
               "event_sequence": len(_LOCAL_RECEIPTS) + 1,
               "call": {"id": call_id, "tool": "calculator",
                        "arguments": {"operation": operation, "operands": list(operands)}},
               "result": outcome}
    _LOCAL_RECEIPTS[id(receipt)] = (receipt, _canonical(receipt))
    return receipt


def _receipt_trust(receipt: Any) -> str:
    entry = _LOCAL_RECEIPTS.get(id(receipt))
    if entry and entry[0] is receipt and entry[1] == _canonical(receipt):
        return "OBSERVED_LOCAL"
    return "UNVERIFIED_IMPORTED"


class CalculatorRecoveryScenario:
    """Bounded local runner: declared transient failure, then one valid retry.

    Calls execute the real constrained service; no learner output is generated.
    The injected failure is deterministic and labeled infrastructure, never a
    fabricated model failure. Caller supplies unique IDs; only two calls allowed.
    """
    def __init__(self, task_id: str, operation: str, operands: list):
        self.task_id, self.operation, self.operands = task_id, operation, list(operands)
        self.receipts: list[dict] = []

    def call(self, call_id: str) -> dict:
        if len(self.receipts) >= 2 or any(r["call"]["id"] == call_id for r in self.receipts):
            raise ValueError("Scenario allows exactly one failed call and one distinct-ID retry")
        receipt = execute_calculation(self.task_id, call_id, self.operation, self.operands,
                                      fault="temporary_unavailable" if not self.receipts else None)
        self.receipts.append(receipt)
        return receipt


def _check_recovery(task: dict, spec: dict, response: dict, receipts: Any) -> tuple[bool, dict]:
    evidence = {"trust": "NOT_OBSERVED", "receipt_source": "none", "transition": None}
    claims = response.get(spec["field"])
    if type(claims) is not list or len(claims) != 2 or type(receipts) is not list:
        return False, evidence
    if any(type(claim) is not dict for claim in claims):
        return False, evidence
    ordered = []
    for claim in claims:
        matches = [r for r in receipts if type(r) is dict and type(r.get("call")) is dict
                   and r["call"].get("id") == claim.get("call_id")]
        if len(matches) != 1:
            return False, evidence
        receipt = matches[0]
        if receipt.get("task_id") != task["id"] or receipt["call"].get("tool") != "calculator" or not _equal(receipt["call"].get("arguments"), {"operation": spec["operation"], "operands": spec["operands"]}):
            return False, evidence
        if claim.get("operation") != spec["operation"] or not _equal(claim.get("operands"), spec["operands"]) or claim.get("tool") != "calculator":
            return False, evidence
        ordered.append(receipt)
    first, second = ordered
    if first["call"]["id"] == second["call"]["id"]:
        return False, evidence
    failure, success = first.get("result", {}), second.get("result", {})
    if type(failure) is not dict or type(success) is not dict:
        return False, evidence
    structurally_valid = (failure.get("status") == "failed" and failure.get("error_code") == "temporary_unavailable"
                          and failure.get("call_id") == first["call"]["id"] and failure.get("recoverable") is True
                          and claims[0].get("error_code") == failure["error_code"]
                          and claims[0].get("status") == "failed"
                          and success.get("status") == "success" and success.get("call_id") == second["call"]["id"]
                          and _numeric(success.get("value")) and _equal(success["value"], spec["result"]))
    local = all(_receipt_trust(r) == "OBSERVED_LOCAL" for r in ordered)
    evidence.update(trust="OBSERVED_LOCAL" if local else "UNVERIFIED_IMPORTED",
                    receipt_source="local_constrained_calculator" if local else "imported_json",
                    structural_match=structurally_valid,
                    call_ids=[r["call"]["id"] for r in ordered])
    sequence_valid = (type(first.get("event_sequence")) is int and type(second.get("event_sequence")) is int
                      and first["event_sequence"] < second["event_sequence"])
    passed = (structurally_valid and local and sequence_valid
              and response.get("recovery_diagnosis") == "temporary_unavailable")
    if passed:
        evidence["transition"] = "observed_recoverable_failure_then_distinct_valid_retry_success"
    return passed, evidence


def _check_receipt(task: dict, spec: dict, response: dict, receipts: Any) -> tuple[bool, dict]:
    claims = response.get(spec["field"])
    evidence = {"receipt_source": "none", "trust": "NOT_OBSERVED",
                "structural_match": False, "matched_call_id": None}
    if type(claims) is not list or not claims:
        return False, evidence
    ids = [claim.get("call_id") for claim in claims if type(claim) is dict]
    if len(ids) != len(claims) or any(type(i) is not str or not i for i in ids) or len(set(ids)) != len(ids):
        evidence["reason"] = "Malformed or duplicate claimed call IDs"
        return False, evidence
    if type(receipts) is not list:
        evidence["reason"] = "Receipt list absent or invalid; self-reports do not prove execution"
        return False, evidence
    for claim in claims:
        if not (claim.get("tool") == spec["tool"] and claim.get("operation") == spec["operation"]
                and _equal(claim.get("operands"), spec["operands"])
                and _numeric(claim.get("result")) and _equal(claim["result"], spec["result"])):
            continue
        matches = [r for r in receipts if type(r) is dict and type(r.get("call")) is dict
                   and r["call"].get("id") == claim["call_id"]]
        if len(matches) != 1:
            continue
        receipt = matches[0]
        call, result = receipt["call"], receipt.get("result", {})
        if type(result) is not dict:
            continue
        match = (receipt.get("task_id") == task["id"] and call.get("tool") == spec["tool"]
                 and _equal(call.get("arguments"), {"operation": spec["operation"], "operands": spec["operands"]})
                 and result.get("call_id") == claim["call_id"] and result.get("status") == "success"
                 and _numeric(result.get("value")) and _equal(result["value"], spec["result"]))
        if match:
            trust = _receipt_trust(receipt)
            evidence.update(receipt_source=receipt.get("source", "unspecified"), trust=trust,
                            structural_match=True, matched_call_id=claim["call_id"])
            return trust == "OBSERVED_LOCAL", evidence
    evidence["reason"] = "No unique matching task/call/arguments/result receipt"
    return False, evidence


def _type_matches(value: Any, name: str) -> bool:
    types = {"string": str, "object": dict, "array": list, "boolean": bool}
    if name == "number":
        return _numeric(value)
    if name == "number_or_null":
        return value is None or _numeric(value)
    if name == "null":
        return value is None
    return name in types and type(value) is types[name]


def grade_response(task: dict, reference: dict, response: dict,
                   receipts: list | None = None) -> dict:
    """Grade public task versus separate teacher reference; never infer mastery.

    Grade outputs are teacher-side: check evidence may contain expected values.
    Do not export this report as an unseen-task packet or persist it as mastery.
    """
    result = {"schema_version": 1, "grader_version": GRADER_VERSION,
              "task_id": task.get("id") if type(task) is dict else None,
              "domain": task.get("domain") if type(task) is dict else None,
              "status": "INVALID_INPUT", "overall_evidence_status": "INSUFFICIENT_DATA",
              "deterministic_pass": False, "needs_human_review": True,
              "mastery_authorized": False, "integrity_flags": [], "checks": [],
              "metrics": {name: _metric() for name in METRICS},
              "human_review": {"status": "NOT_REVIEWED", "mode": "blinded",
                               "score": None, "evidence": []}}
    if (type(task) is not dict or type(reference) is not dict or not task.get("id")
            or reference.get("task_id") != task.get("id") or type(reference.get("checks")) is not list
            or not reference["checks"] or type(task.get("response_schema")) is not dict):
        result["integrity_flags"].append("MISSING_OR_MISMATCHED_TASK_REFERENCE")
        return result
    if not _json_value(task) or not _json_value(reference):
        result["integrity_flags"].append("INVALID_TASK_REFERENCE_JSON")
        return result
    schema = task["response_schema"]
    if (type(schema.get("fields")) is not dict or type(schema.get("required")) is not list
            or any(type(check) is not dict or check.get("kind") not in ("exact", "numeric", "labels", "probability", "citation", "receipt", "recovery")
                   or check.get("metric") not in METRICS for check in reference["checks"])):
        result["integrity_flags"].append("INVALID_REFERENCE_CHECK_OR_SCHEMA")
        return result
    result["split"] = task.get("split")
    result["metric_applicability"] = copy.deepcopy(task.get("metric_applicability", {}))
    result["human_review"]["criteria"] = copy.deepcopy(task.get("human_review", {}).get("criteria", []))
    if type(response) is not dict or not _json_value(response) or not _json_value(receipts):
        result["integrity_flags"].append("INVALID_RESPONSE_OR_RECEIPT_JSON")
        return result
    schema = task["response_schema"]
    fields, required = schema.get("fields", {}), schema.get("required", [])
    schema_errors = [f"missing:{k}" for k in required if k not in response]
    schema_errors += [f"type:{k}:{kind}" for k, kind in fields.items()
                      if k in response and not _type_matches(response[k], kind)]
    if not schema.get("additional_properties", False):
        schema_errors += [f"unknown:{k}" for k in response if k not in fields]
    if "rationale" in required and (type(response.get("rationale")) is not str or not response["rationale"].strip()):
        schema_errors.append("empty:rationale")
    checks = result["checks"]
    checks.append({"id": "completion_schema", "kind": "schema", "metric": "completion",
                   "passed": not schema_errors, "error_class": "SCHEMA_ERROR" if schema_errors else None,
                   "evidence": {"errors": schema_errors, "required": required}})
    probability_losses = []
    confusion = Counter()
    for spec in reference["checks"]:
        kind, field, metric = spec.get("kind"), spec.get("field"), spec.get("metric")
        passed, error, evidence = False, None, {"field": field}
        if metric not in METRICS:
            result["integrity_flags"].append("INVALID_REFERENCE_METRIC")
            return result
        observed = response.get(field)
        evidence["observed"] = observed
        try:
            if field not in response:
                error = "MISSING_FIELD"
            elif kind == "exact":
                passed = _equal(observed, spec["expected"])
                evidence["expected"] = spec["expected"]
                error = None if passed else "FACTUAL_MISMATCH"
            elif kind == "numeric":
                passed = _near(observed, spec["expected"], spec["abs_tol"], spec["rel_tol"])
                evidence.update(expected=spec["expected"], abs_tol=spec["abs_tol"], rel_tol=spec["rel_tol"])
                error = None if passed else "ARITHMETIC_MISMATCH"
            elif kind == "labels":
                expected = spec["expected"]
                passed = type(observed) is dict and _equal(observed, expected)
                for label, truth in expected.items():
                    prediction = observed.get(label) if type(observed) is dict else None
                    if prediction not in ("supported", "misleading"):
                        confusion["invalid_or_missing"] += 1
                    else:
                        confusion[("tp" if prediction == "misleading" else "fn") if truth == "misleading"
                                  else ("fp" if prediction == "misleading" else "tn")] += 1
                evidence["expected"] = expected
                error = None if passed else "MISLEADING_CLASSIFICATION_ERROR"
            elif kind == "probability":
                probability = _number(observed)
                if not 0 <= probability <= 1 or type(spec.get("outcome")) is not int or spec["outcome"] not in (0, 1):
                    raise ValueError("Probability must be in [0,1]; outcome must be binary integer")
                loss = float((probability - spec["outcome"]) ** 2)
                probability_losses.append(loss)
                evidence.update(outcome=spec["outcome"], brier_loss=loss)
                passed = True  # Valid forecast; its loss is not a correctness/mastery pass.
            elif kind == "citation":
                source = task.get("source_packet", {}).get(spec["source_id"])
                if type(source) is not dict:
                    raise ValueError("Frozen citation source missing")
                passed = (type(observed) is list and bool(observed)
                          and all(type(cite) is dict and cite.get("source_id") in task["source_packet"]
                                  and cite.get("locator") == task["source_packet"][cite["source_id"]]["locator"]
                                  and type(cite.get("quote")) is str and bool(cite["quote"])
                                  and cite["quote"] == task["source_packet"][cite["source_id"]]["text"]
                                  for cite in observed)
                          and any(cite.get("source_id") == spec["source_id"] for cite in observed))
                evidence.update(required_source=spec["source_id"], scope="Exact frozen excerpt/locator, not claim entailment")
                error = None if passed else "CITATION_MISMATCH"
            elif kind == "receipt":
                passed, receipt_evidence = _check_receipt(task, spec, response, receipts)
                evidence.update(receipt_evidence)
                if not passed:
                    error = "UNVERIFIED_TOOL_EXECUTION"
                    result["integrity_flags"].append("TOOL_EXECUTION_NOT_INDEPENDENTLY_OBSERVED")
            elif kind == "recovery":
                passed, recovery_evidence = _check_recovery(task, spec, response, receipts)
                evidence.update(recovery_evidence)
                if not passed:
                    error = "RECOVERY_TRANSITION_NOT_OBSERVED"
                    result["integrity_flags"].append("RECOVERY_NOT_INDEPENDENTLY_OBSERVED")
            else:
                error = "UNSUPPORTED_REFERENCE_CHECK"
                result["integrity_flags"].append(error)
        except (ValueError, TypeError, KeyError, OverflowError, ZeroDivisionError) as exc:
            error = "INVALID_NUMERIC_VALUE" if kind in ("numeric", "probability") else "INVALID_CHECK_INPUT"
            evidence["reason"] = str(exc)
        checks.append({"id": spec.get("id"), "kind": kind, "metric": metric,
                       "passed": passed, "error_class": error, "evidence": evidence})
    for name in METRICS:
        applicable = [c for c in checks if c["metric"] == name]
        # Receipt imports cannot produce an execution score, even a claimed perfect one.
        if name in ("tool_call_validity", "error_recovery"):
            applicable = [c for c in applicable if c["evidence"].get("trust") == "OBSERVED_LOCAL"]
        if applicable:
            passed = sum(c["passed"] for c in applicable)
            result["metrics"][name] = {"status": "MEASURED", "value": passed / len(applicable),
                                       "numerator": passed, "denominator": len(applicable),
                                       "method": "Deterministic finite-fixture check; not broad competence",
                                       "evidence": [c["id"] for c in applicable]}
    if probability_losses:
        result["metrics"]["uncertainty"].update(value=sum(probability_losses) / len(probability_losses),
                                                  numerator=None, denominator=len(probability_losses),
                                                  method="Binary Brier mean squared loss; lower is better; not calibration")
    elif any(c["kind"] == "probability" for c in checks):
        result["metrics"]["uncertainty"] = _metric()
    if result["metrics"]["source_reliability"]["status"] == "MEASURED":
        result["metrics"]["source_reliability"]["method"] = "Synthetic conflict-source selection only; authentic source reliability NOT_MEASURED"
    if confusion:
        result["metrics"]["misleading_detection"]["confusion"] = dict(confusion)
        tp, fp, fn = (confusion[k] for k in ("tp", "fp", "fn"))
        result["metrics"]["misleading_detection"].update(
            precision=tp / (tp + fp) if tp + fp else None,
            recall=tp / (tp + fn) if tp + fn else None)
    result["deterministic_pass"] = all(c["passed"] for c in checks)
    result["status"] = "DETERMINISTIC_PASS" if result["deterministic_pass"] else "DETERMINISTIC_FAIL"
    result["errors"] = dict(Counter(c["error_class"] for c in checks if c["error_class"]))
    result["integrity_flags"] = sorted(set(result["integrity_flags"]))
    return result


def baseline_report(results: list[dict], expected_domains: list | None = None) -> dict:
    """Raw descriptive summary only. Repeated task IDs never increase sample size."""
    if type(results) is not list or not _json_value(results):
        raise ValueError("Results must be a finite JSON list")
    expected = list(DOMAINS if expected_domains is None else expected_domains)
    if len(set(expected)) != len(expected) or any(d not in DOMAINS for d in expected):
        raise ValueError("Unknown or duplicate expected domain")
    seen, accepted, excluded, invalid_inputs = set(), [], [], []
    for row in results:
        reason = None
        if type(row) is not dict or type(row.get("task_id")) is not str or not row["task_id"] or row.get("domain") not in expected:
            reason = "INVALID_RESULT_ID_OR_DOMAIN"
        elif row["task_id"] in seen:
            reason = "REPEATED_TASK_NOT_INDEPENDENT"
        elif row.get("split") != "baseline":
            reason = "NOT_BASELINE_SPLIT"
        elif row.get("status") == "INVALID_INPUT":
            invalid_inputs.append(row)
            reason = "INVALID_INPUT_NOT_COMPETENCE_OUTCOME"
        elif row.get("status") not in ("DETERMINISTIC_PASS", "DETERMINISTIC_FAIL"):
            reason = "INVALID_RESULT_STATUS"
        elif type(row.get("metrics")) is not dict or type(row.get("deterministic_pass")) is not bool:
            reason = "INVALID_METRIC_CONTAINER_OR_PASS_FLAG"
        elif (row["status"] == "DETERMINISTIC_PASS") != row["deterministic_pass"]:
            reason = "INCONSISTENT_PASS_STATUS"
        if reason:
            excluded.append({"task_id": row.get("task_id") if type(row) is dict else None, "reason": reason})
        else:
            seen.add(row["task_id"])
            accepted.append(row)
    metrics = {m: _metric() for m in METRICS}
    metric_errors = []
    for name in METRICS:
        measured = []
        for row in accepted:
            metric = row["metrics"].get(name)
            if metric is None:
                continue
            if type(metric) is not dict:
                metric_errors.append({"task_id": row["task_id"], "metric": name, "reason": "METRIC_NOT_OBJECT"})
                continue
            if metric.get("status") == "NOT_MEASURED" and metric.get("value") is None:
                continue
            value, numerator, denominator = (metric.get(k) for k in ("value", "numerator", "denominator"))
            valid = (metric.get("status") == "MEASURED" and _numeric(value) and 0 <= value <= 1
                     and type(denominator) is int and denominator > 0)
            if name == "uncertainty":
                valid = valid and numerator is None
            else:
                valid = (valid and type(numerator) is int and 0 <= numerator <= denominator
                         and _near(value, numerator / denominator, 1e-12, 1e-12))
            if not valid:
                metric_errors.append({"task_id": row["task_id"], "metric": name, "reason": "INVALID_METRIC_INVARIANTS"})
                continue
            measured.append((row["task_id"], metric))
        if measured:
            denominator = sum(m["denominator"] for _, m in measured)
            numerator = None if name == "uncertainty" else sum(m["numerator"] for _, m in measured)
            metrics[name] = {"status": "MEASURED", "value": sum(m["value"] * m["denominator"] for _, m in measured) / denominator,
                             "numerator": numerator, "denominator": denominator,
                             "method": "Imported descriptive Brier loss; lower is better" if name == "uncertainty" else "Imported descriptive check ratio; not authenticated student evidence",
                             "evidence": [tid for tid, _ in measured]}
    return {"schema_version": 1, "status": "INSUFFICIENT_DATA", "student_run_count": None,
            "descriptive_report_count": len(accepted), "report_origin_trust": "UNVERIFIED_IMPORTED",
            "unique_tasks": len(seen), "domain_counts": {d: sum(r["domain"] == d for r in accepted) for d in expected},
            "deterministic_passes": sum(r["deterministic_pass"] for r in accepted),
            "metrics": metrics, "metric_errors": metric_errors, "excluded": excluded,
            "invalid_input_reports": invalid_inputs, "raw_results": accepted,
            "mastery_authorized": False, "improvement": None, "p_value": None,
            "reliability": None, "reason": "No authenticated runner manifest or controlled independent study. Report count is not genuine student-run count.",
            "run_status": "NO_REPORTS" if not accepted else "DESCRIPTIVE_ONLY"}


_TASK_FIELDS = ("id", "domain", "prompt", "response_schema", "required_sources", "instructions",
                "calculator_request", "metric_applicability")
_SOURCE_FIELDS = ("id", "url", "locator", "text", "excerpt_sha256")


def export_task(task_id: str, root: str | Path = DEFAULT_ROOT) -> dict:
    """Allowlist export of one task. Never return teacher checks/solutions/paths."""
    tasks = load_json(Path(root) / "references/private/tasks.json")
    if type(task_id) is not str or task_id not in tasks:
        raise ValueError(f"Unknown task ID: {task_id}")
    task = tasks[task_id]
    packet = {key: copy.deepcopy(task[key]) for key in _TASK_FIELDS if key in task}
    packet["source_packet"] = {
        sid: {key: copy.deepcopy(source[key]) for key in _SOURCE_FIELDS if key in source}
        for sid, source in task.get("source_packet", {}).items()
    }
    return packet


def validate_curriculum(root: str | Path = DEFAULT_ROOT) -> dict:
    """Validate DAG, ten-domain coverage, lesson contracts and sealed task keys."""
    root, errors = Path(root), []
    try:
        graph = load_json(root / "curriculum/graph.json")
        lessons = load_json(root / "curriculum/lessons.json")["lessons"]
        tasks = load_json(root / "references/private/tasks.json")
        solutions = load_json(root / "references/private/solutions.json")
        sources = load_json(root / "references/sources.json")
        manifest = load_json(root / "references/manifest.json")["sources"]
        ids = [lesson["id"] for lesson in lessons]
        if len(ids) != len(set(ids)):
            errors.append("Duplicate lesson ID")
        nodes = {lesson["id"]: lesson for lesson in lessons}
        visiting, visited = set(), set()

        def visit(node: str) -> None:
            if node not in nodes:
                errors.append(f"Unknown prerequisite {node}")
                return
            if node in visiting:
                errors.append(f"Dependency cycle at {node}")
                return
            if node in visited:
                return
            visiting.add(node)
            for prerequisite in nodes[node]["prerequisites"]:
                visit(prerequisite)
            visiting.remove(node)
            visited.add(node)

        for lesson in lessons:
            visit(lesson["id"])
            for key in ("domain", "competency_id", "competency", "objectives", "required_sources", "worked_example", "independent_exercise", "evaluation", "remediation"):
                if not lesson.get(key):
                    errors.append(f"{lesson['id']}: missing {key}")
            if lesson["remediation"].get("max_corrective_iterations") != 3 or lesson["evaluation"].get("max_attempts") != 4 or lesson["evaluation"].get("pass_threshold") != 1.0:
                errors.append(f"{lesson['id']}: invalid pass/remediation policy")
            for sid in lesson["required_sources"]:
                if sid not in sources or not any(r.get("id") == sid and r.get("status") == "RETRIEVED" for r in manifest):
                    errors.append(f"{lesson['id']}: unavailable verified source {sid}")
        observed_domains = sorted({lesson["domain"] for lesson in lessons})
        if set(observed_domains) != set(DOMAINS) or set(graph["domains"]) != set(DOMAINS):
            errors.append("Ten-domain coverage mismatch")
        if graph["nodes"] != [{"id": l["id"], "domain": l["domain"], "prerequisites": l["prerequisites"]} for l in lessons]:
            errors.append("Graph and lesson prerequisites diverge")
        for sid, source in sources.items():
            if hashlib.sha256(source["text"].encode()).hexdigest() != source["excerpt_sha256"]:
                errors.append(f"Source hash mismatch: {sid}")
            records = [record for record in manifest if record.get("id") == sid and record.get("status") == "RETRIEVED"]
            if len(records) != 1 or records[0].get("quote") != source["text"] or records[0].get("content_sha256") != source["excerpt_sha256"] or records[0].get("location") != source["locator"] or records[0].get("retrieved_url") != source["url"]:
                errors.append(f"Manifest/source provenance mismatch: {sid}")
        for tid, task in tasks.items():
            if task.get("id") != tid or tid not in solutions or solutions[tid].get("task_id") != tid or not solutions[tid].get("checks"):
                errors.append(f"Missing/mismatched task solution: {tid}")
            if task.get("split") not in ("practice", "baseline", "heldout") or task.get("domain") not in DOMAINS:
                errors.append(f"Invalid task split/domain: {tid}")
            if set(task.get("metric_applicability", {})) != set(METRICS):
                errors.append(f"Missing metric applicability: {tid}")
            for check in solutions.get(tid, {}).get("checks", []):
                if type(check) is not dict or check.get("kind") not in ("exact", "numeric", "labels", "probability", "citation", "receipt", "recovery") or check.get("metric") not in METRICS or check.get("field") not in task["response_schema"]["fields"]:
                    errors.append(f"Unknown or invalid reference check: {tid}")
                elif check["kind"] == "numeric":
                    try:
                        _near(check["expected"], check["expected"], check["abs_tol"], check["rel_tol"])
                    except (ValueError, KeyError, TypeError):
                        errors.append(f"Invalid numeric reference/tolerance: {tid}")
        for domain in DOMAINS:
            for split in ("practice", "baseline", "heldout"):
                if not any(t["domain"] == domain and t["split"] == split for t in tasks.values()):
                    errors.append(f"Missing {split} task: {domain}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(str(exc))
        lessons, observed_domains = [], []
    return {"valid": not errors, "errors": errors, "lesson_count": len(lessons),
            "domains": observed_domains, "security_boundary": "NONE: directories are logical separation only",
            "evidence_status": "INSUFFICIENT_DATA"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-curriculum")
    validate.add_argument("--output", type=Path)
    export = sub.add_parser("export-task")
    export.add_argument("task_id")
    export.add_argument("--output", type=Path)
    grade = sub.add_parser("grade")
    grade.add_argument("--task-id", required=True)
    grade.add_argument("--response", required=True, type=Path)
    grade.add_argument("--receipts", type=Path)
    grade.add_argument("--output", type=Path)
    baseline = sub.add_parser("baseline-report")
    baseline.add_argument("--results", type=Path)
    baseline.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        code = 0
        if args.command == "validate-curriculum":
            result = validate_curriculum(args.root)
            code = 0 if result["valid"] else 1
        elif args.command == "export-task":
            result = export_task(args.task_id, args.root)
        elif args.command == "grade":
            tasks = load_json(args.root / "references/private/tasks.json")
            references = load_json(args.root / "references/private/solutions.json")
            if args.task_id not in tasks or args.task_id not in references:
                raise ValueError(f"Unknown task ID: {args.task_id}")
            result = grade_response(tasks[args.task_id], references[args.task_id],
                                    load_json(args.response), load_json(args.receipts) if args.receipts else None)
            code = 0 if result["deterministic_pass"] else 1
        else:
            result = baseline_report(load_json(args.results) if args.results else [])
        text = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return code
    except (OSError, ValueError, TypeError, KeyError) as exc:
        sys.stdout.write(json.dumps({"status": "INVALID_INPUT", "error": str(exc),
                                     "deterministic_pass": False, "mastery_authorized": False}) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

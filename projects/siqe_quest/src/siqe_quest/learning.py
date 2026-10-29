"""Evidence-gated curriculum, deterministic reference checks, and finite quests.

These public regression cases measure this implementation, not an LLM's intelligence.
No retrieval, prompting, or procedure update changes model weights.
"""

from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .core import Store, canonical_json, digest, utcnow


MODULE_ID = "quest-financial-foundations-v1"
BENCHMARK_VERSION = "quest-foundations-reference-v1"
TOPICS = {
    "mathematics": [
        "Algebra",
        "Calculus",
        "Linear algebra",
        "Probability",
        "Statistical inference",
        "Optimization",
        "Numerical analysis",
        "Stochastic processes",
        "Time-series mathematics",
        "Convex optimization",
        "Bayesian statistics",
        "Monte Carlo methods",
        "Information theory",
        "Applied econometrics",
        "Stochastic differential equations",
    ],
    "economics": [
        "Microeconomics",
        "Macroeconomics",
        "Monetary policy",
        "International economics",
        "Inflation",
        "Interest rates",
        "Bond markets",
        "Exchange rates",
        "Business cycles",
        "Fiscal policy",
        "Economic shocks",
        "Financial crises",
        "Capital flows",
        "Global trade",
    ],
    "finance": [
        "Financial accounting",
        "Corporate finance",
        "Equity valuation",
        "Fixed-income valuation",
        "Derivatives",
        "Portfolio theory",
        "Risk management",
        "Behavioral finance",
        "Market microstructure",
        "Asset pricing",
        "Factor investing",
        "Event-driven research",
        "Corporate actions",
        "Capital markets regulation",
    ],
    "quantitative_research": [
        "Technical indicators",
        "Trend following",
        "Mean reversion",
        "Momentum",
        "Volatility",
        "Statistical arbitrage",
        "Cross-sectional factors",
        "Time-series forecasting",
        "Regime detection",
        "Portfolio optimization",
        "Risk parity",
        "Liquidity factors",
        "Volatility targeting",
        "Options Greeks",
        "Tail-risk modeling",
        "Transaction cost analysis",
        "Execution simulation",
        "Machine learning for financial time series",
    ],
}
DOMAINS = {
    "financial_knowledge": [
        "Financial statement interpretation",
        "Asset valuation",
        "Economic reasoning",
        "Market rules",
        "Derivative mechanics",
        "Risk measurement",
        "Corporate actions",
    ],
    "mathematical": [
        "Probability",
        "Statistics",
        "Numerical optimization",
        "Linear algebra",
        "Time-series inference",
        "Financial calculations",
    ],
    "tool_use": [
        "Data-source selection",
        "Source verification",
        "Error handling",
        "Provenance preservation",
        "Timestamp interpretation",
        "Dataset normalization",
    ],
    "strategy_engineering": [
        "Indicator numerical correctness",
        "No-repaint behavior",
        "Backtest parity",
        "Trading cost handling",
        "Risk management",
        "Pine v6 syntax compatibility",
        "Conditional strategy logic",
    ],
    "autonomous_learning": [
        "Cross-session continuity",
        "Knowledge retrieval",
        "Lesson retention",
        "Contradiction detection",
        "Unseen problem solving",
        "Negative-transfer detection",
        "Token efficiency",
    ],
}
DIMENSIONS = {
    "A": "source_discovery_precision",
    "B": "source_verification_accuracy",
    "C": "relevant_knowledge_retrieval",
    "D": "mathematical_correctness",
    "E": "financial_reasoning_correctness",
    "F": "tool_routing_effectiveness",
    "G": "backtest_reproducibility",
    "H": "false_strategy_approval_rate",
    "I": "strategy_robustness",
    "J": "forecast_calibration",
    "K": "tradingview_python_parity",
    "L": "new_skill_transfer_performance",
    "M": "operational_reliability",
    "N": "cost_per_verified_research_result",
    "O": "regression_rate",
    "P": "performance_on_unseen_tasks",
}

# Frozen fixtures are independent of the procedure's formulas and practice examples.
# Expected answers are literal hand-derived values, never computed by reference_answer.
_CASES = (
    {
        "id": "FND-001",
        "domain": "Financial calculations",
        "operation": "simple_return",
        "input": {"start": 80, "end": 100},
        "expected": 0.25,
    },
    {
        "id": "FND-002",
        "domain": "Financial calculations",
        "operation": "compound",
        "input": {"returns": [0.1, -0.1]},
        "expected": -0.01,
    },
    {
        "id": "FND-003",
        "domain": "Financial calculations",
        "operation": "log_return",
        "input": {"start": 2, "end": 4},
        "expected": 0.6931471805599453,
    },
    {
        "id": "FND-004",
        "domain": "Probability",
        "operation": "bayes",
        "input": {"prior": 0.2, "sensitivity": 0.75, "false_positive": 0.25},
        "expected": 0.42857142857142855,
    },
    {
        "id": "FND-005",
        "domain": "Probability",
        "operation": "expectation",
        "input": {"values": [-0.2, 0.1, 0.4], "probabilities": [0.25, 0.5, 0.25]},
        "expected": 0.1,
    },
    {
        "id": "FND-006",
        "domain": "Statistics",
        "operation": "variance",
        "input": {"values": [2, 4, 6]},
        "expected": 2.6666666666666665,
    },
    {
        "id": "FND-007",
        "domain": "Financial calculations",
        "operation": "fx_conversion",
        "input": {"usd": 125, "cad_per_usd": 1.36},
        "expected": 170.0,
    },
    {
        "id": "FND-008",
        "domain": "Financial calculations",
        "operation": "fx_inverse",
        "input": {"cad_per_usd": 1.25},
        "expected": 0.8,
    },
    {
        "id": "FND-009",
        "domain": "Financial calculations",
        "operation": "fx_cross",
        "input": {"cad_per_usd": 1.35, "usd_per_eur": 1.2},
        "expected": 1.62,
    },
    {
        "id": "FND-010",
        "domain": "Trading cost handling",
        "operation": "roundtrip_equity",
        "input": {
            "initial_cad": 1000,
            "units_usd": 100,
            "entry": 1.2,
            "exit": 1.3,
            "fee_bps": 10,
        },
        "expected": 1009.75,
    },
    {
        "id": "FND-011",
        "domain": "Financial statement interpretation",
        "operation": "balance_sheet",
        "input": {"assets": 720, "liabilities": 450},
        "expected": 270.0,
    },
    {
        "id": "FND-012",
        "domain": "Economic reasoning",
        "operation": "causal_claim",
        "input": {
            "observational_correlation": 0.92,
            "randomized": False,
            "identification_assumptions_verified": False,
        },
        "expected": "NOT_IDENTIFIED",
    },
    {
        "id": "FND-013",
        "domain": "Timestamp interpretation",
        "operation": "available_before",
        "input": {
            "available_at": "2025-01-02T09:00:00-05:00",
            "decision_at": "2025-01-02T13:59:59+00:00",
        },
        "expected": False,
    },
    {
        "id": "FND-014",
        "domain": "Timestamp interpretation",
        "operation": "available_before",
        "input": {"available_at": None, "decision_at": "2025-01-02T14:00:00+00:00"},
        "expected": False,
    },
    {
        "id": "FND-015",
        "domain": "No-repaint behavior",
        "operation": "leakage_audit",
        "input": {"signal_index": 6, "max_feature_index": 7, "fill_index": 7},
        "expected": "REJECT_FUTURE_FEATURE",
    },
    {
        "id": "FND-016",
        "domain": "No-repaint behavior",
        "operation": "leakage_audit",
        "input": {"signal_index": 6, "max_feature_index": 6, "fill_index": 6},
        "expected": "REJECT_SAME_OBSERVATION_FILL",
    },
    {
        "id": "FND-017",
        "domain": "Error handling",
        "operation": "simple_return",
        "input": {"start": 0, "end": 5},
        "expected_error": "ValueError",
    },
    {
        "id": "FND-018",
        "domain": "Dataset normalization",
        "operation": "validate_observations",
        "input": {
            "rows": [
                {"date": "2025-01-06", "value": 1.4},
                {"date": "2025-01-06", "value": 1.41},
            ]
        },
        "expected_error": "ValueError",
    },
    {
        "id": "FND-019",
        "domain": "Dataset normalization",
        "operation": "validate_observations",
        "input": {"rows": [{"date": "2025-01-06", "value": -1.4}]},
        "expected_error": "ValueError",
    },
    {
        "id": "FND-020",
        "domain": "Timestamp interpretation",
        "operation": "available_before",
        "input": {
            "available_at": "2025-01-02T09:00:00",
            "decision_at": "2025-01-02T14:00:00+00:00",
        },
        "expected_error": "ValueError",
    },
    {
        "id": "FND-021",
        "domain": "Trading cost handling",
        "operation": "roundtrip_equity",
        "input": {
            "initial_cad": 1000,
            "units_usd": 100,
            "entry": 1.2,
            "exit": 1.2,
            "fee_bps": 10,
        },
        "expected": 999.76,
    },
)


def frozen_cases() -> list[dict]:
    """Return a copy: consumers cannot mutate the versioned evaluation fixtures."""
    return copy.deepcopy(list(_CASES))


def _number(value: Any, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("finite numeric value required")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError("invalid numeric range")
    return result


def _instant(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("timezone offset required")
    return stamp.astimezone(timezone.utc)


def reference_answer(operation: str, data: dict) -> Any:
    """Numerical implementation under test; not an answer-key lookup or model vote."""
    if operation in {"simple_return", "log_return"}:
        ratio = _number(data["end"], positive=True) / _number(
            data["start"], positive=True
        )
        return ratio - 1 if operation == "simple_return" else math.log(ratio)
    if operation == "compound":
        growth = 1.0
        for item in data["returns"]:
            rate = _number(item)
            if rate < -1:
                raise ValueError("simple return below total loss")
            growth *= 1 + rate
        return growth - 1
    if operation == "bayes":
        prior, sensitivity, false_positive = (
            _number(data[k]) for k in ("prior", "sensitivity", "false_positive")
        )
        if any(not 0 <= p <= 1 for p in (prior, sensitivity, false_positive)):
            raise ValueError("probability outside unit interval")
        numerator = prior * sensitivity
        denominator = numerator + (1 - prior) * false_positive
        if denominator == 0:
            raise ValueError("conditioning event has zero probability")
        return numerator / denominator
    if operation == "expectation":
        values = [_number(v) for v in data["values"]]
        probabilities = [_number(p) for p in data["probabilities"]]
        if (
            not values
            or len(values) != len(probabilities)
            or any(p < 0 or p > 1 for p in probabilities)
            or not math.isclose(sum(probabilities), 1, abs_tol=1e-12)
        ):
            raise ValueError("invalid probability mass function")
        return math.fsum(v * p for v, p in zip(values, probabilities))
    if operation == "variance":
        values = [_number(v) for v in data["values"]]
        if not values:
            raise ValueError("empty population")
        mean = math.fsum(values) / len(values)
        return math.fsum((v - mean) ** 2 for v in values) / len(values)
    if operation == "fx_conversion":
        return _number(data["usd"]) * _number(data["cad_per_usd"], positive=True)
    if operation == "fx_inverse":
        return 1 / _number(data["cad_per_usd"], positive=True)
    if operation == "fx_cross":
        return _number(data["cad_per_usd"], positive=True) * _number(
            data["usd_per_eur"], positive=True
        )
    if operation == "roundtrip_equity":
        cash = _number(data["initial_cad"], positive=True)
        units = _number(data["units_usd"], positive=True)
        entry, exit_price = (_number(data[k], positive=True) for k in ("entry", "exit"))
        fee = _number(data["fee_bps"]) / 10000
        if not 0 <= fee < 1 or units * entry * (1 + fee) > cash:
            raise ValueError("invalid fee or insufficient unlevered cash")
        cash -= units * entry * (1 + fee)
        cash += units * exit_price * (1 - fee)
        return cash
    if operation == "balance_sheet":
        return _number(data["assets"]) - _number(data["liabilities"])
    if operation == "causal_claim":
        # A randomized flag alone does not establish valid identification either.
        return (
            "IDENTIFIED_UNDER_STATED_ASSUMPTIONS"
            if data.get("identification_assumptions_verified") is True
            else "NOT_IDENTIFIED"
        )
    if operation == "available_before":
        if data["available_at"] is None:
            return False
        return _instant(data["available_at"]) <= _instant(data["decision_at"])
    if operation == "leakage_audit":
        signal, feature, fill = (
            data[k] for k in ("signal_index", "max_feature_index", "fill_index")
        )
        if any(
            isinstance(v, bool) or not isinstance(v, int) or v < 0
            for v in (signal, feature, fill)
        ):
            raise ValueError("nonnegative integer observation indices required")
        if feature > signal:
            return "REJECT_FUTURE_FEATURE"
        if fill <= signal:
            return "REJECT_SAME_OBSERVATION_FILL"
        return "NO_INDEX_LEAKAGE_DETECTED"
    if operation == "validate_observations":
        previous = None
        if not data["rows"]:
            raise ValueError("empty observations")
        for row in data["rows"]:
            date = datetime.strptime(row["date"], "%Y-%m-%d").date()
            if date.weekday() >= 5 or (previous is not None and date <= previous):
                raise ValueError("nonascending, duplicate, or weekend date")
            _number(row["value"], positive=True)
            previous = date
        return True
    raise ValueError("unknown fixed benchmark operation")


def _correct(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return type(actual) is bool and actual is expected
    if isinstance(expected, (int, float)):
        return (
            not isinstance(actual, bool)
            and isinstance(actual, (int, float))
            and math.isfinite(actual)
            and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10)
        )
    return type(actual) is type(expected) and actual == expected


def _execute(cases: list[dict], responder: Callable[[str, dict], Any]) -> list[dict]:
    results = []
    for case in cases:
        try:
            answer = responder(case["operation"], copy.deepcopy(case["input"]))
            passed = "expected_error" not in case and _correct(
                answer, case.get("expected")
            )
            # Never let a nonfinite/opaque candidate answer invalidate persistence.
            try:
                canonical_json(answer)
                observed = answer
            except (ValueError, TypeError):
                observed = {"invalid_output_type": type(answer).__name__}
            results.append(
                {
                    "id": case["id"],
                    "domain": case["domain"],
                    "correct": passed,
                    "observed": observed,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "id": case["id"],
                    "domain": case["domain"],
                    "correct": case.get("expected_error") == type(exc).__name__,
                    "error_type": type(exc).__name__,
                }
            )
    return results


class Curriculum:
    def __init__(self, store: Store):
        self.store = store

    def module(self) -> dict:
        """Complete instructional specification; execution/evidence statuses stay separate."""
        result = {
            "module_id": MODULE_ID,
            "version": 1,
            "title": "Returns, probability, causal inference and FX reference research",
            "status": "IMPLEMENTED_NOT_VERIFIED_MASTERY",
            "prerequisites": ["arithmetic", "fractions", "timezone-aware dates"],
            "learning_layers": {
                "A_knowledge_acquisition": "Validate sources, preserve excerpts and provenance; no weight updates.",
                "B_procedural_skill": "Version preconditions, tools, data, procedure, outputs, failures and acceptance tests.",
                "C_policy_improvement": "Require controlled independent comparison and no critical regressions before promotion.",
                "D_fine_tuning": {
                    "enabled": False,
                    "requirements": [
                        "explicit authorization",
                        "available weights",
                        "permissive license",
                        "data rights",
                        "adequate compute",
                        "independent protocol",
                        "cost justification",
                    ],
                },
            },
            "objectives": [
                "Compute simple, compound and log returns without summing compounded gains.",
                "Compute conditional probabilities, expectation and population variance with explicit assumptions.",
                "Convert CAD-per-USD quotes, reciprocals and dimensional cross rates correctly.",
                "Reconcile cash, holdings and both entry/exit transaction costs without leverage.",
                "Distinguish association from causal identification and state confounding/counterexamples.",
                "Reject future features, same-observation fills and unknown first-availability as PIT evidence.",
            ],
            "source_discovery": [
                {
                    "publisher": "Bank of Canada",
                    "url": "https://www.bankofcanada.ca/valet/docs",
                    "purpose": "Discover FXUSDCAD units, observation conventions and API schema",
                    "validation_status": "REQUIRES_SOURCEHUNTER_EVIDENCE",
                },
                {
                    "publisher": "Bank of Canada",
                    "url": "https://www.bankofcanada.ca/terms/",
                    "purpose": "Verify attribution, indicative-rate restrictions and underlying-data rights",
                    "validation_status": "REQUIRES_SOURCEHUNTER_EVIDENCE",
                },
                {
                    "publisher": "NIST",
                    "url": "https://www.itl.nist.gov/div898/handbook/",
                    "purpose": "Discover independent probability and statistical reference material",
                    "validation_status": "CATALOG_CANDIDATE_NOT_ALLOWLISTED",
                },
            ],
            "source_validation_requirements": [
                "Follow official catalog links rather than trust a search snippet",
                "Verify HTTPS publisher, domain allowlist, terms and robots before retrieval",
                "Store raw immutable bytes, digest, retrieval time, units and vintage",
                "Extract exact supporting spans; preserve conflicts and limitations",
                "Do not retrieve a nonallowlisted candidate until separately authorized",
            ],
            "knowledge_extraction": {
                "required_fields": [
                    "source_id",
                    "evidence_sha256",
                    "exact_excerpt",
                    "span",
                    "claim",
                    "conditions",
                    "counterexamples",
                ],
                "unsupported_summary_is_evidence": False,
            },
            "instruction": [
                {
                    "concept": "returns",
                    "rule": "r=P1/P0-1; cumulative=product(1+r)-1; log return=ln(P1/P0)",
                    "failure": "A +20% then -20% path loses 4%, not zero.",
                },
                {
                    "concept": "probability",
                    "rule": "P(A|B)=P(B|A)P(A)/P(B); E[X]=sum(p*x)",
                    "failure": "Ignore base rates or condition on a zero-probability event.",
                },
                {
                    "concept": "FX",
                    "rule": "USD times CAD/USD yields CAD; reciprocal quote is USD/CAD.",
                    "failure": "Indicative daily averages are not executable bid/ask or intraday OHLC.",
                },
                {
                    "concept": "causality",
                    "rule": "A predictive association does not identify an intervention effect without a defensible design and assumptions.",
                    "failure": "Common macro shocks can cause both exchange rates and an indicator to move.",
                },
            ],
            "practice_exercises": [
                {
                    "id": "PRACTICE-RET",
                    "question": "Price 50 then 60 then 54: compute cumulative return.",
                    "answer": 0.08,
                    "working": "54/50-1; 1.2*0.9-1",
                },
                {
                    "id": "PRACTICE-PROB",
                    "question": "Fair independent coin twice: probability of two heads?",
                    "answer": 0.25,
                    "working": "0.5*0.5",
                },
                {
                    "id": "PRACTICE-FX",
                    "question": "Convert USD 40 at CAD 1.5 per USD.",
                    "answer": 60,
                    "working": "40 USD * 1.5 CAD/USD",
                },
                {
                    "id": "PRACTICE-CAUSE",
                    "question": "Does exchange-rate/indicator correlation prove intervention causality?",
                    "answer": "No; specify identification assumptions and test confounding.",
                },
            ],
            "deterministic_test": {
                "benchmark_version": BENCHMARK_VERSION,
                "case_count": len(_CASES),
                "separate_from_practice": True,
                "public_source_cases": True,
                "not_model_unseen_evidence": True,
                "scoring": "literal independent numeric/typed/error outputs; no consensus",
            },
            "applied_experiment": {
                "required_kind": "experiment",
                "strategy_id": "quest-alpha-usdcad-sma",
                "requirements": [
                    "real provenance-preserving reference dataset",
                    "hypothesis and locked chronological split registered before computation, explicitly retrospective rather than prospective preregistration",
                    "cash and buy-hold baselines",
                    "lagged signal and adverse costs",
                    "positive and negative results",
                    "independent temporal audit",
                    "state that reference fills are nontradable proxies and first historical availability is unknown",
                ],
                "linkage": "Use returns/probability/units and timing checks to audit run_alpha results, not to optimize the sealed test.",
            },
            "independent_review": {
                "required_kind": "learning_review",
                "requirements": [
                    "reviewer independent of candidate",
                    "test evidence",
                    "applied experiment evidence",
                    "limitations",
                    "verified passed decision",
                ],
            },
            "retention": {
                "minimum_delay_seconds": 86400,
                "required_kind": "learning_retention",
                "fresh_disjoint_cases": True,
                "same_case_replay_is_retention": False,
                "requirements": [
                    "initial evaluation reference",
                    "actual later timestamp",
                    "independent reviewer",
                    "passing delayed-case outputs",
                ],
            },
            "mastery_rule": "Independent passed assessment AND linked applied experiment reviewed AND fresh delayed retention. A summary, reference-suite pass or record count alone is insufficient.",
            "catalog": {
                group: [
                    {
                        "topic": topic,
                        "status": "PARTIAL_MODULE_COVERAGE"
                        if topic
                        in {
                            "Probability",
                            "Exchange rates",
                            "Financial accounting",
                            "Transaction cost analysis",
                            "Execution simulation",
                            "Applied econometrics",
                        }
                        else "CATALOG_ONLY",
                        "module_id": MODULE_ID
                        if topic
                        in {
                            "Probability",
                            "Exchange rates",
                            "Financial accounting",
                            "Transaction cost analysis",
                            "Execution simulation",
                            "Applied econometrics",
                        }
                        else None,
                    }
                    for topic in topics
                ]
                for group, topics in TOPICS.items()
            },
        }
        return result

    def evaluate(self, responder: Callable[[str, dict], Any] | None = None) -> dict:
        self.store.authorize("research.learning")
        cases = frozen_cases()
        manifest = {
            "version": BENCHMARK_VERSION,
            "cases": cases,
            "tolerance": {"relative": 1e-10, "absolute": 1e-10},
            "public": True,
            "practice_ids": [
                "PRACTICE-RET",
                "PRACTICE-PROB",
                "PRACTICE-FX",
                "PRACTICE-CAUSE",
            ],
        }
        manifest_hash = digest(manifest)
        self.store.record("benchmark_manifest", BENCHMARK_VERSION, manifest)
        exposures = [
            r
            for r in self.store.records("benchmark_exposure")
            if r["value"].get("manifest_hash") == manifest_hash
        ]
        exposure_number = len(exposures) + 1
        # Exposure is committed before answers run, including failed/interrupted evaluations.
        exposure = self.store.record(
            "benchmark_exposure",
            f"{manifest_hash}:{exposure_number}",
            {
                "manifest_hash": manifest_hash,
                "sequence": exposure_number,
                "exposed_at": utcnow(),
                "case_ids": [c["id"] for c in cases],
                "purpose": "evaluation_not_training",
                "public_in_source": True,
            },
        )
        results = _execute(cases, responder or reference_answer)
        by_domain = {}
        for row in results:
            domain = by_domain.setdefault(row["domain"], {"correct": 0, "total": 0})
            domain["correct"] += int(row["correct"])
            domain["total"] += 1
        for value in by_domain.values():
            value["accuracy"] = value["correct"] / value["total"]
        correct = sum(row["correct"] for row in results)
        math_rows = [
            r
            for r in results
            if r["domain"] in {"Financial calculations", "Probability", "Statistics"}
        ]
        finance_rows = [
            r
            for r in results
            if r["domain"]
            in {
                "Financial statement interpretation",
                "Economic reasoning",
                "Trading cost handling",
            }
        ]
        scorecard = {
            key: {"name": name, "value": None, "status": "UNMEASURED", "scope": None}
            for key, name in DIMENSIONS.items()
        }
        for key, rows in (("D", math_rows), ("E", finance_rows)):
            scorecard[key].update(
                value=sum(r["correct"] for r in rows) / len(rows),
                status="MEASURED_NARROW_REFERENCE_CASES",
                scope="Public deterministic reference implementation only; not general capability",
            )
        result = {
            "benchmark_version": BENCHMARK_VERSION,
            "manifest_hash": manifest_hash,
            "exposure_record_id": exposure["record_id"],
            "exposure_number": exposure_number,
            "previous_exposures": len(exposures),
            "case_count": len(results),
            "correct": correct,
            "accuracy": correct / len(results),
            "results": results,
            "by_domain": by_domain,
            "scorecard": scorecard,
            "evaluated_system": "reference_numerical_implementation"
            if responder is None
            else "provided_responder",
            "held_out_from_practice": True,
            "unseen_to_model": False,
            "training_performed": False,
            "model_weights_updated": False,
            "mastery": "NOT_VERIFIED",
            "improvement_demonstrated": False,
            "unseen_transfer_statement": "NO DEMONSTRATED IMPROVEMENT: no controlled before/after benefit on independently sealed unseen tasks has been measured. Public reference cases are not evidence of unseen model transfer.",
            "coverage_limitations": "Only listed executed cases measured. All other catalog domains remain unimplemented/unmeasured; a passing score is not curriculum mastery.",
            "provenance": {
                "answer_key": "fixed hand-derived literals separate from reference formulas",
                "manifest_record_key": BENCHMARK_VERSION,
                "scoring": "output correctness, not model consensus",
                "evaluated_at": utcnow(),
            },
        }
        record = self.store.record(
            "learning_evaluation", f"{manifest_hash}:{exposure_number}", result
        )
        return {
            **result,
            "record_id": record["record_id"],
            "evidence": record["evidence"],
        }

    def prioritize(self, gaps: list[dict], budget: float) -> list[dict]:
        """Rank bounded research quests; never spend beyond the finite total budget.

        Inputs use 0..1 factors (error_history may be a count), positive cost, and
        explicit research-only safety. Invalid/unsafe/exhausted gaps are rejected.
        Duplicate content collapses to one quest; caller inputs are never changed.
        """
        budget = _number(budget)
        if budget < 0:
            raise ValueError("budget must be nonnegative")
        maximum = min(128, int(self.store.config.get("max_queue", 128)))
        attempts_cap = min(3, int(self.store.config.get("max_attempts", 3)))
        ranked = []
        seen = set()
        for gap in gaps:
            if not isinstance(gap, dict):
                continue
            objective = (
                gap.get("objective") or gap.get("knowledge_gap") or gap.get("gap")
            )
            if (
                not isinstance(objective, str)
                or not objective.strip()
                or gap.get("safety_classification", "research_only") != "research_only"
            ):
                continue
            if gap.get("status") in {"REJECTED", "COMPLETED", "STOPPED"}:
                continue
            try:
                cost = _number(gap.get("expected_cost", 1), positive=True)
                attempts = int(gap.get("attempts", 0))
                cap = min(attempts_cap, int(gap.get("maximum_attempts", attempts_cap)))
                if attempts < 0 or cap < 1 or attempts >= cap:
                    continue
                factors = {}
                for name in (
                    "uncertainty",
                    "research_relevance",
                    "information_gain",
                    "evidence",
                    "source_quality",
                    "reusability",
                    "testability",
                    "market_relevance",
                ):
                    value = _number(gap.get(name, 0.5))
                    if not 0 <= value <= 1:
                        raise ValueError("factor outside 0..1")
                    factors[name] = value
                errors = _number(gap.get("error_history", 0))
                if errors < 0:
                    continue
            except (TypeError, ValueError, OverflowError):
                continue
            # Quality/relevance are multiplicative gates, not rewards for busywork.
            gain = (
                0.3 * factors["information_gain"]
                + 0.25 * factors["uncertainty"]
                + 0.15 * min(1, errors / 3)
                + 0.15 * factors["reusability"]
                + 0.15 * factors["market_relevance"]
            )
            quality = (
                factors["source_quality"]
                * factors["testability"]
                * (0.5 + 0.5 * factors["evidence"])
            )
            utility = factors["research_relevance"] * quality * gain / cost
            if not math.isfinite(utility):
                continue
            if utility <= 0:
                continue
            identity = digest(
                {
                    "objective": objective.strip(),
                    "knowledge_gap": gap.get("knowledge_gap", objective.strip()),
                }
            )
            if identity in seen:
                continue
            seen.add(identity)
            task = {
                "quest_id": "quest-" + identity[:20],
                "objective": objective.strip(),
                "knowledge_gap": gap.get("knowledge_gap", objective.strip()),
                "hypothesis": gap.get(
                    "hypothesis",
                    "Resolving this gap will improve independently scored research correctness.",
                ),
                "source_plan": gap.get(
                    "source_plan",
                    [
                        "Discover official source",
                        "Validate allowlist, terms and provenance before retrieval",
                    ],
                ),
                "required_tools": gap.get(
                    "required_tools",
                    [
                        "SourceHunter.discover",
                        "SourceHunter.validate",
                        "Curriculum.evaluate",
                    ],
                ),
                "expected_cost": cost,
                "cost_unit": gap.get("cost_unit", "bounded_work_units"),
                "evaluation_method": gap.get(
                    "evaluation_method",
                    "Freeze independent expected outputs before running the candidate; compare correctness to baseline.",
                ),
                "acceptance_criteria": gap.get(
                    "acceptance_criteria",
                    [
                        "Verified source provenance",
                        "Measurable correct-output gain on independent tasks",
                        "No critical regression",
                        "Within total budget",
                    ],
                ),
                "safety_classification": "research_only",
                "maximum_attempts": cap,
                "attempts_remaining": cap - attempts,
                "stop_condition": "Stop on exhausted attempts, total cost cap, source-rights failure, no measurable gain, critical regression, or explicit STOP; no recursive retry quests.",
                "priority": utility,
                "priority_factors": factors,
                "error_history": errors,
            }
            ranked.append(task)
        ranked.sort(key=lambda item: (-item["priority"], item["quest_id"]))
        selected = []
        remaining = budget
        for task in ranked:
            if len(selected) >= maximum:
                break
            if task["expected_cost"] <= remaining:
                selected.append(task)
                remaining -= task["expected_cost"]
        return selected

    def mastery(
        self, evaluation_id: str, experiment_id: str, review_id: str, retention_id: str
    ) -> dict:
        """Check linked evidence, not a caller-supplied mastery boolean.

        Independent reviewers must create these records after actual work; this
        method does not manufacture reviews, applied success or retention results.
        """

        def find(kind: str, record_id: str) -> dict | None:
            return next(
                (r for r in self.store.records(kind) if r["record_id"] == record_id),
                None,
            )

        evaluation = find("learning_evaluation", evaluation_id)
        experiment = find("experiment", experiment_id)
        review = find("learning_review", review_id)
        retention = find("learning_retention", retention_id)
        # Hash-verify the actual delayed outputs, not a decorative evidence label.
        retention_outputs_valid = False
        try:
            artifact = (
                json.loads(self.store.read_blob(retention["value"]["results_evidence"]))
                if retention
                else {}
            )
            rows = artifact.get("cases", [])
            retention_outputs_valid = (
                bool(rows)
                and all(
                    isinstance(row, dict)
                    and isinstance(row.get("id"), str)
                    and "expected" in row
                    and "observed" in row
                    and _correct(row["observed"], row["expected"])
                    for row in rows
                )
                and [row["id"] for row in rows] == retention["value"].get("case_ids")
            )
        except (KeyError, TypeError, ValueError, AttributeError, OSError):
            retention_outputs_valid = False
        reasons = []
        if not evaluation or evaluation["value"].get("accuracy") != 1:
            reasons.append("missing or failed deterministic evaluation")
        if not experiment:
            reasons.append("missing applied experiment")
        rv = review["value"] if review else {}
        if not (
            rv.get("independent") is True
            and rv.get("passed") is True
            and rv.get("reviewer")
            and rv.get("evaluation_id") == evaluation_id
            and rv.get("experiment_id") == experiment_id
            and rv.get("module_id") == MODULE_ID
        ):
            reasons.append("missing independent linked applied review")
        rt = retention["value"] if retention else {}
        try:
            baseline_time = _instant(evaluation["created_at"]) if evaluation else None
            tested_time = _instant(rt["tested_at"])
            recorded_time = _instant(retention["created_at"])
            known_ids = {case["id"] for case in _CASES}
            fresh_ids = rt.get("case_ids", [])
            delayed = (
                baseline_time is not None
                and tested_time >= baseline_time + timedelta(days=1)
                and tested_time <= recorded_time
            )
            if not (
                delayed
                and retention_outputs_valid
                and rt.get("passed") is True
                and rt.get("independent") is True
                and rt.get("reviewer")
                and rt.get("evaluation_id") == evaluation_id
                and rt.get("module_id") == MODULE_ID
                and fresh_ids
                and len(set(fresh_ids)) == len(fresh_ids)
                and not known_ids.intersection(fresh_ids)
            ):
                reasons.append(
                    "missing independent delayed fresh-case retention evidence"
                )
        except (KeyError, TypeError, ValueError):
            reasons.append("missing or invalid retention timing")
        return {
            "module_id": MODULE_ID,
            "status": "VERIFIED_MASTERY" if not reasons else "NOT_VERIFIED",
            "reasons": reasons,
            "evidence_ids": [evaluation_id, experiment_id, review_id, retention_id],
            "scope": "This module only, subject to independent reviewer attestations; not general intelligence",
        }

    def compare(
        self,
        baseline: Callable[[str, dict], Any],
        candidate: Callable[[str, dict], Any],
        candidate_version: str,
    ) -> dict:
        """Paired public regression comparison; intentionally insufficient for promotion."""
        before = self.evaluate(baseline)
        after = self.evaluate(candidate)
        critical = [
            new["id"]
            for old, new in zip(before["results"], after["results"])
            if old["correct"] and not new["correct"]
        ]
        value = {
            "candidate_version": candidate_version,
            "baseline_evaluation_id": before["record_id"],
            "candidate_evaluation_id": after["record_id"],
            "accuracy_delta": after["accuracy"] - before["accuracy"],
            "critical_regressions": critical,
            "controlled_same_cases": True,
            "independent_unseen": False,
            "eligible_for_promotion": False,
            "reason": "Public regression cases are exposed; independently sealed controlled unseen comparison is still required.",
        }
        record = self.store.record("learning_comparison", digest(value), value)
        return {**value, "record_id": record["record_id"]}

    def promote(self, candidate: dict, comparison_id: str) -> dict:
        """Gate skill/policy registration on externally reviewed, controlled evidence.

        Public compare() records cannot qualify. An independent evaluator may file
        a controlled_comparison with actual per-case baseline/candidate correctness,
        sealed-manifest provenance and an independently linked learning_review.
        """
        reasons = []
        kind = candidate.get("kind")
        required = (
            "version",
            "preconditions",
            "required_tools",
            "required_data",
            "procedure",
            "expected_outputs",
            "known_failure_cases",
            "acceptance_tests",
            "provenance",
        )
        if kind not in {"skill", "policy"} or any(
            key not in candidate for key in required
        ):
            reasons.append("incomplete skill/policy specification")
        comparison = next(
            (
                r
                for r in self.store.records("controlled_comparison")
                if r["record_id"] == comparison_id
            ),
            None,
        )
        cv = comparison["value"] if comparison else {}
        rows = cv.get("cases", [])
        typed_rows = (
            isinstance(rows, list)
            and bool(rows)
            and all(
                isinstance(r, dict)
                and type(r.get("baseline_correct")) is bool
                and type(r.get("candidate_correct")) is bool
                and isinstance(r.get("id"), str)
                for r in rows
            )
        )
        review = next(
            (
                r
                for r in self.store.records("learning_review")
                if r["record_id"] == cv.get("review_id")
            ),
            None,
        )
        rv = review["value"] if review else {}
        # Independently re-score immutable actual outputs against a frozen key.
        outputs_valid = False
        try:
            frozen = next(
                (
                    r
                    for r in self.store.records("sealed_benchmark_manifest")
                    if digest(r["value"]) == cv.get("frozen_manifest_hash")
                ),
                None,
            )
            outputs = json.loads(self.store.read_blob(cv["outputs_evidence"]))
            keys = (
                {row["id"]: row for row in frozen["value"]["cases"]} if frozen else {}
            )
            actual = outputs.get("cases", [])
            outputs_valid = (
                bool(keys)
                and len(keys) == len(frozen["value"]["cases"])
                and bool(actual)
                and len(actual) == len(keys)
                and len({row["id"] for row in actual}) == len(keys)
            )
            rescored = []
            if outputs_valid:
                for row in actual:
                    key = keys[row["id"]]
                    rescored.append(
                        {
                            "id": row["id"],
                            "baseline_correct": _correct(
                                row["baseline_output"], key["expected"]
                            ),
                            "candidate_correct": _correct(
                                row["candidate_output"], key["expected"]
                            ),
                        }
                    )
                outputs_valid = sorted(rescored, key=lambda r: r["id"]) == sorted(
                    rows, key=lambda r: r["id"]
                ) and _instant(frozen["created_at"]) <= _instant(
                    comparison["created_at"]
                )
        except (KeyError, TypeError, ValueError, AttributeError, OSError):
            outputs_valid = False
        if not (
            cv.get("controlled") is True
            and cv.get("independent_unseen") is True
            and cv.get("candidate_version") == candidate.get("version")
            and outputs_valid
            and typed_rows
        ):
            reasons.append("missing actual controlled independent unseen comparison")
        elif len({r["id"] for r in rows}) != len(rows) or any(
            r["id"] in {c["id"] for c in _CASES} for r in rows
        ):
            reasons.append("duplicate or public exposed comparison cases")
        else:
            delta = sum(r["candidate_correct"] - r["baseline_correct"] for r in rows)
            regressions = [
                r["id"]
                for r in rows
                if r["baseline_correct"] and not r["candidate_correct"]
            ]
            if delta <= 0:
                reasons.append("no measured correct-output improvement")
            if regressions:
                reasons.append("critical correctness regression")
        if not (
            rv.get("independent") is True
            and rv.get("passed") is True
            and rv.get("reviewer")
            and rv.get("comparison_key") == (comparison["key"] if comparison else None)
            and rv.get("verified_unseen") is True
        ):
            reasons.append("missing independently verified unseen comparison review")
        result = {
            "candidate_version": candidate.get("version"),
            "promoted": not reasons,
            "reasons": reasons,
            "comparison_id": comparison_id,
            "fine_tuning": False,
        }
        if not reasons:
            record = self.store.record(
                "promoted_" + kind,
                str(candidate["version"]),
                {"candidate": candidate, "decision": result},
            )
            result["record_id"] = record["record_id"]
        return result

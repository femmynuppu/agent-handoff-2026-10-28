"""Independent arithmetic and evidence-boundary tests; no network or model calls."""

import json
import math
import tempfile
import unittest
from pathlib import Path

from siqe_quest.core import Store, canonical_json, digest
from siqe_quest.learning import (
    Curriculum,
    DIMENSIONS,
    DOMAINS,
    TOPICS,
    frozen_cases,
    reference_answer,
)


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(self.directory.name)
        self.curriculum = Curriculum(self.store)

    def test_reference_numerics_have_independent_hand_calculated_answers(self):
        # Different inputs from the frozen evaluation, not calling the answer key.
        self.assertAlmostEqual(
            reference_answer("simple_return", {"start": 125, "end": 100}), -0.2
        )
        self.assertAlmostEqual(
            reference_answer("compound", {"returns": [0.5, -0.5]}), -0.25
        )
        self.assertAlmostEqual(
            reference_answer("log_return", {"start": 5, "end": 5}), 0
        )
        self.assertAlmostEqual(
            reference_answer(
                "bayes", {"prior": 0.01, "sensitivity": 0.9, "false_positive": 0.1}
            ),
            1 / 12,
        )
        self.assertAlmostEqual(
            reference_answer(
                "expectation", {"values": [0, 10], "probabilities": [0.7, 0.3]}
            ),
            3,
        )
        self.assertAlmostEqual(reference_answer("variance", {"values": [0, 2]}), 1)
        self.assertAlmostEqual(
            reference_answer("fx_conversion", {"usd": 12, "cad_per_usd": 1.5}), 18
        )
        self.assertAlmostEqual(reference_answer("fx_inverse", {"cad_per_usd": 2}), 0.5)
        self.assertAlmostEqual(
            reference_answer("fx_cross", {"cad_per_usd": 2, "usd_per_eur": 1.5}), 3
        )

    def test_cash_ledger_charges_both_notional_legs(self):
        # 200 - 2*30*1.01 + 2*40*.99 = 218.6.
        result = reference_answer(
            "roundtrip_equity",
            {
                "initial_cad": 200,
                "units_usd": 2,
                "entry": 30,
                "exit": 40,
                "fee_bps": 100,
            },
        )
        self.assertAlmostEqual(result, 218.6)
        # A flat-price roundtrip must lose both fees, not break even.
        flat = reference_answer(
            "roundtrip_equity",
            {
                "initial_cad": 200,
                "units_usd": 2,
                "entry": 30,
                "exit": 30,
                "fee_bps": 100,
            },
        )
        self.assertAlmostEqual(flat, 198.8)
        self.assertEqual(
            reference_answer("balance_sheet", {"assets": 900, "liabilities": 1100}),
            -200,
        )

    def test_probability_and_numeric_error_paths(self):
        invalid = [
            ("simple_return", {"start": 0, "end": 1}),
            ("simple_return", {"start": True, "end": 1}),
            ("simple_return", {"start": 1, "end": math.inf}),
            ("compound", {"returns": [-1.1]}),
            ("variance", {"values": []}),
            ("bayes", {"prior": 0, "sensitivity": 0, "false_positive": 0}),
            ("bayes", {"prior": 1.1, "sensitivity": 0.5, "false_positive": 0.5}),
            ("expectation", {"values": [1, 2], "probabilities": [0.1, 0.2]}),
            (
                "roundtrip_equity",
                {
                    "initial_cad": 10,
                    "units_usd": 100,
                    "entry": 1,
                    "exit": 2,
                    "fee_bps": 1,
                },
            ),
            ("unknown_operation", {}),
        ]
        for operation, data in invalid:
            with (
                self.subTest(operation=operation, data=data),
                self.assertRaises(ValueError),
            ):
                reference_answer(operation, data)

    def test_timestamp_offsets_missing_availability_and_naive_rejection(self):
        self.assertTrue(
            reference_answer(
                "available_before",
                {
                    "available_at": "2025-06-03T09:00:00-04:00",
                    "decision_at": "2025-06-03T13:00:00Z",
                },
            )
        )
        self.assertFalse(
            reference_answer(
                "available_before",
                {
                    "available_at": "2025-06-03T09:00:01-04:00",
                    "decision_at": "2025-06-03T13:00:00Z",
                },
            )
        )
        self.assertFalse(
            reference_answer(
                "available_before",
                {"available_at": None, "decision_at": "2025-06-03T13:00:00Z"},
            )
        )
        with self.assertRaises(ValueError):
            reference_answer(
                "available_before",
                {
                    "available_at": "2025-06-03T09:00:00",
                    "decision_at": "2025-06-03T13:00:00Z",
                },
            )

    def test_planted_leakage_causality_and_normalization(self):
        self.assertEqual(
            reference_answer(
                "leakage_audit",
                {"signal_index": 3, "max_feature_index": 4, "fill_index": 5},
            ),
            "REJECT_FUTURE_FEATURE",
        )
        self.assertEqual(
            reference_answer(
                "leakage_audit",
                {"signal_index": 3, "max_feature_index": 3, "fill_index": 3},
            ),
            "REJECT_SAME_OBSERVATION_FILL",
        )
        self.assertEqual(
            reference_answer(
                "leakage_audit",
                {"signal_index": 3, "max_feature_index": 3, "fill_index": 4},
            ),
            "NO_INDEX_LEAKAGE_DETECTED",
        )
        self.assertEqual(
            reference_answer(
                "causal_claim",
                {
                    "observational_correlation": 0.999,
                    "randomized": True,
                    "identification_assumptions_verified": False,
                },
            ),
            "NOT_IDENTIFIED",
        )
        for rows in (
            [{"date": "2025-01-04", "value": 1}],
            [{"date": "2025-01-07", "value": 1}, {"date": "2025-01-06", "value": 1}],
            [{"date": "2025-01-06", "value": float("nan")}],
        ):
            with self.assertRaises(ValueError):
                reference_answer("validate_observations", {"rows": rows})
        self.assertTrue(
            reference_answer(
                "validate_observations",
                {
                    "rows": [
                        {"date": "2025-01-03", "value": 1},
                        {"date": "2025-01-06", "value": 1.1},
                    ]
                },
            )
        )

    def test_evaluation_is_real_scoring_not_echo_or_consensus(self):
        result = self.curriculum.evaluate()
        self.assertEqual(result["correct"], result["case_count"])
        self.assertGreaterEqual(result["case_count"], 20)
        self.assertFalse(result["improvement_demonstrated"])
        self.assertFalse(result["unseen_to_model"])
        self.assertEqual(result["mastery"], "NOT_VERIFIED")
        self.assertEqual(set(result["scorecard"]), set(DIMENSIONS))
        self.assertIsNone(result["scorecard"]["P"]["value"])
        self.assertIn(
            "NO DEMONSTRATED IMPROVEMENT", result["unseen_transfer_statement"]
        )
        failures = self.curriculum.evaluate(lambda operation, data: 0)
        self.assertLess(failures["accuracy"], 1)
        self.assertFalse(
            failures["results"][12]["correct"],
            "numeric zero is not a boolean false answer",
        )
        self.assertEqual(result["manifest_hash"], failures["manifest_hash"])
        self.assertEqual(failures["exposure_number"], 2)
        self.assertEqual(len(self.store.records("benchmark_exposure")), 2)

    def test_buggy_candidate_is_penalized_for_specific_critical_failures(self):
        def buggy(operation, data):
            if operation == "compound":
                return sum(data["returns"])
            if operation == "roundtrip_equity":
                return data["initial_cad"] + data["units_usd"] * (
                    data["exit"] - data["entry"]
                )
            if operation == "leakage_audit":
                return "NO_INDEX_LEAKAGE_DETECTED"
            return reference_answer(operation, data)

        result = self.curriculum.compare(reference_answer, buggy, "bad-v1")
        self.assertIn("FND-002", result["critical_regressions"])
        self.assertIn("FND-010", result["critical_regressions"])
        self.assertIn("FND-015", result["critical_regressions"])
        self.assertLess(result["accuracy_delta"], 0)
        self.assertFalse(result["eligible_for_promotion"])

    def test_manifest_and_cases_cannot_silently_mutate(self):
        first = frozen_cases()
        first[0]["expected"] = 999
        self.assertEqual(frozen_cases()[0]["expected"], 0.25)
        self.curriculum.evaluate()
        frozen = self.store.get("benchmark_manifest", "quest-foundations-reference-v1")
        self.assertEqual(len(frozen["value"]["cases"]), 21)
        with self.assertRaises(ValueError):
            self.store.record(
                "benchmark_manifest", "quest-foundations-reference-v1", {"cases": []}
            )

    def test_curriculum_and_catalog_cover_all_topics_without_mastery_claims(self):
        module = self.curriculum.module()
        self.assertEqual(set(module["catalog"]), set(TOPICS))
        self.assertEqual(sum(map(len, TOPICS.values())), 61)
        self.assertFalse(module["learning_layers"]["D_fine_tuning"]["enabled"])
        self.assertTrue(module["practice_exercises"])
        self.assertGreaterEqual(module["retention"]["minimum_delay_seconds"], 86400)
        catalog_path = (
            Path(__file__).resolve().parents[1] / "benchmarks" / "catalog.json"
        )
        catalog = json.loads(catalog_path.read_text())
        for group, domains in DOMAINS.items():
            self.assertEqual(
                {row["name"] for row in catalog["domains"][group]}, set(domains)
            )
        self.assertFalse(catalog["training_performed"])
        self.assertFalse(catalog["verified_mastery"])
        self.assertEqual(catalog["curriculum_topics"], TOPICS)
        self.assertEqual(
            catalog["freeze_protocol"]["case_ids"], [c["id"] for c in frozen_cases()]
        )

    def test_priority_budget_safety_quality_and_all_quest_fields(self):
        gaps = [
            {
                "objective": "high quality",
                "expected_cost": 2,
                "source_quality": 1,
                "testability": 1,
            },
            {
                "objective": "low quality",
                "expected_cost": 2,
                "source_quality": 0.1,
                "testability": 0.1,
            },
            {
                "objective": "unsafe",
                "expected_cost": 0.1,
                "safety_classification": "live_trade",
            },
            {"objective": "retry exhausted", "attempts": 3},
            {"objective": "zero cost", "expected_cost": 0},
            {"objective": "invalid", "uncertainty": 2},
        ]
        tasks = self.curriculum.prioritize(gaps, 2.5)
        self.assertEqual([t["objective"] for t in tasks], ["high quality"])
        self.assertLessEqual(sum(t["expected_cost"] for t in tasks), 2.5)
        fields = {
            "quest_id",
            "objective",
            "knowledge_gap",
            "hypothesis",
            "source_plan",
            "required_tools",
            "expected_cost",
            "evaluation_method",
            "acceptance_criteria",
            "safety_classification",
            "maximum_attempts",
            "stop_condition",
        }
        self.assertTrue(fields.issubset(tasks[0]))
        self.assertEqual(self.curriculum.prioritize(gaps, 0), [])
        self.assertEqual(len(self.curriculum.prioritize([gaps[0], gaps[0]], 10)), 1)
        self.assertNotIn("quest_id", gaps[0])
        with self.assertRaises(ValueError):
            self.curriculum.prioritize(gaps, float("inf"))

    def test_mastery_requires_applied_review_and_actual_delay(self):
        evaluation = self.curriculum.evaluate()
        result = self.curriculum.mastery(
            evaluation["record_id"], "missing", "missing", "missing"
        )
        self.assertEqual(result["status"], "NOT_VERIFIED")
        experiment = self.store.record("experiment", "applied", {"result": "negative"})
        review = self.store.record(
            "learning_review",
            "review",
            {
                "independent": True,
                "passed": True,
                "reviewer": "independent-auditor",
                "evaluation_id": evaluation["record_id"],
                "experiment_id": experiment["record_id"],
                "module_id": "quest-financial-foundations-v1",
            },
        )
        retention = self.store.record(
            "learning_retention",
            "too-soon",
            {
                "independent": True,
                "passed": True,
                "reviewer": "independent-auditor",
                "evaluation_id": evaluation["record_id"],
                "module_id": "quest-financial-foundations-v1",
                "case_ids": ["fresh-1"],
                "tested_at": "2025-01-01T00:00:00Z",
                "results_evidence": {"sha256": "not-real"},
            },
        )
        result = self.curriculum.mastery(
            evaluation["record_id"],
            experiment["record_id"],
            review["record_id"],
            retention["record_id"],
        )
        self.assertEqual(result["status"], "NOT_VERIFIED")
        self.assertTrue(any("retention" in reason for reason in result["reasons"]))

    def test_public_comparison_cannot_promote_skill_or_claim_weight_training(self):
        comparison = self.curriculum.compare(
            lambda operation, data: None, reference_answer, "candidate-v1"
        )
        self.assertGreater(comparison["accuracy_delta"], 0)
        self.assertFalse(comparison["eligible_for_promotion"])
        candidate = {
            "kind": "skill",
            "version": "candidate-v1",
            "preconditions": [],
            "required_tools": [],
            "required_data": [],
            "procedure": ["compute returns"],
            "expected_outputs": ["correct return"],
            "known_failure_cases": ["zero denominator"],
            "acceptance_tests": ["independent scored cases"],
            "provenance": [comparison["record_id"]],
        }
        decision = self.curriculum.promote(candidate, comparison["record_id"])
        self.assertFalse(decision["promoted"])
        self.assertFalse(decision["fine_tuning"])
        self.assertEqual(self.store.records("promoted_skill"), [])

    def test_controlled_promotion_rescores_outputs_and_blocks_negative_transfer(self):
        candidate = {
            "kind": "policy",
            "version": "sealed-v1",
            "preconditions": [],
            "required_tools": [],
            "required_data": [],
            "procedure": ["Use verified arithmetic"],
            "expected_outputs": ["correct numbers"],
            "known_failure_cases": ["bad units"],
            "acceptance_tests": ["sealed comparison"],
            "provenance": ["independent audit"],
        }
        manifest = {
            "version": "external-v1",
            "cases": [
                {"id": "SECRET-A", "expected": 12},
                {"id": "SECRET-B", "expected": 8},
            ],
        }
        self.store.record("sealed_benchmark_manifest", "external-v1", manifest)
        review = self.store.record(
            "learning_review",
            "external-review",
            {
                "independent": True,
                "passed": True,
                "reviewer": "external-auditor",
                "verified_unseen": True,
                "comparison_key": "external-comparison",
            },
        )
        outputs = self.store.put_blob(
            canonical_json(
                {
                    "cases": [
                        {
                            "id": "SECRET-A",
                            "baseline_output": 0,
                            "candidate_output": 12,
                        },
                        {"id": "SECRET-B", "baseline_output": 8, "candidate_output": 8},
                    ]
                }
            ).encode()
        )
        value = {
            "candidate_version": "sealed-v1",
            "controlled": True,
            "independent_unseen": True,
            "frozen_manifest_hash": digest(manifest),
            "outputs_evidence": outputs,
            "review_id": review["record_id"],
            "cases": [
                {
                    "id": "SECRET-A",
                    "baseline_correct": False,
                    "candidate_correct": True,
                },
                {"id": "SECRET-B", "baseline_correct": True, "candidate_correct": True},
            ],
        }
        comparison = self.store.record(
            "controlled_comparison", "external-comparison", value
        )
        self.assertTrue(
            self.curriculum.promote(candidate, comparison["record_id"])["promoted"]
        )

        # False correctness labels cannot override the actual output artifact.
        bad_outputs = self.store.put_blob(
            canonical_json(
                {
                    "cases": [
                        {
                            "id": "SECRET-A",
                            "baseline_output": 0,
                            "candidate_output": 12,
                        },
                        {"id": "SECRET-B", "baseline_output": 8, "candidate_output": 0},
                    ]
                }
            ).encode()
        )
        value["outputs_evidence"] = bad_outputs
        fake = self.store.record("controlled_comparison", "dishonest-comparison", value)
        decision = self.curriculum.promote(candidate, fake["record_id"])
        self.assertFalse(decision["promoted"])
        self.assertIn(
            "missing actual controlled independent unseen comparison",
            decision["reasons"],
        )

        # Honest labels reveal regression even when another case improves.
        review2 = self.store.record(
            "learning_review",
            "regression-review",
            {
                "independent": True,
                "passed": True,
                "reviewer": "external-auditor",
                "verified_unseen": True,
                "comparison_key": "regression-comparison",
            },
        )
        value["review_id"] = review2["record_id"]
        value["cases"][1]["candidate_correct"] = False
        regression = self.store.record(
            "controlled_comparison", "regression-comparison", value
        )
        decision = self.curriculum.promote(candidate, regression["record_id"])
        self.assertFalse(decision["promoted"])
        self.assertIn("critical correctness regression", decision["reasons"])


if __name__ == "__main__":
    unittest.main()

"""Persisted synthetic consumer scenarios; never presented as provider evidence."""

import hashlib
import json
from datetime import date, timedelta
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from siqe_quest.core import Store, canonical_json, digest, utcnow
from siqe_quest.events import Event, EventQueue
from siqe_quest.knowledge import KnowledgeEngine
from siqe_quest.learning import Curriculum
from siqe_quest.reporting import (
    GATE_STATUSES,
    REPORT_TYPES,
    build_reports,
    export_bundle,
)
from siqe_quest.research import run_alpha
from siqe_quest.tradingview import render_pine


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        # No real service is launched by reporting tests.
        self.service = patch(
            "siqe_quest.reporting.service_status",
            return_value={
                "running": False,
                "process_verified": False,
                "heartbeat_verified": False,
                "heartbeat_fresh": False,
                "singleton_held": False,
            },
        )
        self.service_mock = self.service.start()
        self.addCleanup(self.service.stop)

    def verification(
        self, checks, key="test-verification", status="VERIFIED_BY_EXECUTION"
    ):
        return self.store.record(
            "verification",
            key,
            {
                "phase": "test",
                "observed_at": utcnow(),
                "status": status,
                "checks": checks,
                "limitations": ["Synthetic isolated test workspace."],
            },
        )

    def experiment(self):
        rows = []
        for year in (2023, 2024, 2025):
            day = date(year, 1, 2)
            for index in range(75):
                while day.weekday() > 4:
                    day += timedelta(days=1)
                rows.append(
                    {
                        "date": day.isoformat(),
                        "value": 1.2 + index * 0.001,
                        "available_at": None,
                        "publication_time": None,
                        "complete": True,
                    }
                )
                day += timedelta(days=1)
        raw = self.store.put_blob(b"Synthetic fixture only; not a provider response")
        normalized = self.store.put_blob(
            canonical_json(rows).encode(), "application/json"
        )
        dataset_id = digest(
            {
                "series": "FXUSDCAD",
                "raw": raw["sha256"],
                "normalized": normalized["sha256"],
            }
        )
        manifest = {
            "dataset_id": dataset_id,
            "raw": raw,
            "normalized": normalized,
            "coverage": {"observation_count": len(rows)},
            "source_id": "synthetic-only",
            "source_version": "fixture-v1",
            "limitations": ["Synthetic fixture"],
        }
        dataset = {"dataset_id": dataset_id, "manifest": manifest, "observations": rows}
        self.store.record("dataset", dataset_id, dataset)
        self.store.record("source_snapshot", dataset_id, manifest)
        return run_alpha(self.store, dataset)

    def gates(self, mission=None):
        return build_reports(self.store, mission)["operational_health_report"]["data"][
            "release_gates"
        ]["gates"]

    def test_empty_store_has_all_reports_gates_and_honest_missing_domains(self):
        reports = build_reports(self.store)
        self.assertEqual(set(reports), set(REPORT_TYPES))
        gates = reports["operational_health_report"]["data"]["release_gates"]["gates"]
        self.assertEqual(set(gates), {f"SIQE-G{i}" for i in range(21)})
        self.assertTrue(all(gate["status"] in GATE_STATUSES for gate in gates.values()))
        self.assertEqual(gates["SIQE-G9"]["status"], "NOT_TESTED")
        self.assertEqual(gates["SIQE-G19"]["status"], "FAILED")
        for number in (12, 13):
            self.assertEqual(gates[f"SIQE-G{number}"]["status"], "NOT_TESTED")
            self.assertEqual(gates[f"SIQE-G{number}"]["classification"], "MET")
        self.assertFalse(gates["SIQE-G17"]["improvement_demonstrated"])
        for name in (
            "academic_literature_review",
            "cross_market_performance_comparison",
        ):
            self.assertEqual(reports[name]["status"], "NOT_TESTED")
            self.assertTrue(reports[name]["needed_evidence"])
        self.assertEqual(
            reports["academic_literature_review"]["data"]["reviewed_papers"], []
        )
        for report in reports.values():
            for field in (
                "methodology",
                "dataset_versions",
                "generated_at",
                "market_coverage",
                "limitations",
                "reproduction_commands",
                "statistical_metrics",
                "source_references",
            ):
                self.assertIn(field, report)

    def test_nested_actual_replay_check_required_not_experiment_count_or_mission_claim(
        self,
    ):
        run = self.experiment()
        for index in range(5):
            self.store.record("experiment", f"historical-{index}", run["result"])
        mission = {
            "research": {"reproduced": True},
            "status": "VERIFIED_BY_REPRODUCTION",
        }
        self.assertEqual(self.gates(mission)["SIQE-G9"]["status"], "NOT_TESTED")
        observed = {
            "experiment_id": run["experiment_id"],
            "dataset_id": run["result"]["dataset_id"],
            "result_sha256": run["result"]["reproduction"]["result_sha256"],
            "same_numeric_outputs": True,
        }
        verification = self.verification(
            {"numeric_experiment_reproduction": {"passed": True, "observed": observed}}
        )
        gate = self.gates()["SIQE-G9"]
        self.assertEqual(gate["status"], "VERIFIED_BY_REPRODUCTION")
        self.assertEqual(
            gate["evidence"][0]["verification"]["record_id"], verification["record_id"]
        )
        observed["result_sha256"] = "0" * 64
        self.verification(
            {"numeric_experiment_reproduction": {"passed": True, "observed": observed}},
            "mismatch",
        )
        self.assertEqual(self.gates()["SIQE-G9"]["status"], "NOT_TESTED")

    def test_latest_failed_check_does_not_inherit_earlier_pass(self):
        self.verification(
            {
                "event_reopen_dedup_depth": {
                    "passed": True,
                    "observed": {"duplicate": True},
                }
            },
            "old",
        )
        self.assertEqual(self.gates()["SIQE-G5"]["status"], "VERIFIED_BY_EXECUTION")
        self.verification(
            {
                "event_reopen_dedup_depth": {
                    "passed": False,
                    "observed": {"duplicate": False},
                }
            },
            "new",
            "FAILED",
        )
        self.assertEqual(self.gates()["SIQE-G5"]["status"], "FAILED")

    def test_discovery_validation_history_and_completed_queue_are_not_conflated(self):
        discovered = {
            "source_id": "fixture",
            "version": "v1",
            "verification_outcome": "DISCOVERED_NOT_VALIDATED",
        }
        self.store.record("source", "fixture:v1", discovered)
        validation = dict(
            discovered,
            verification_outcome="VALIDATED_RESEARCH_ONLY",
            last_validated_at=utcnow(),
        )
        self.store.record("source_validation", "fixture-validation", validation)
        queue = EventQueue(self.store)
        event_id = queue.emit(
            Event(
                event_type="EXPERIMENT_COMPLETED",
                idempotency_key="report-event",
                payload_reference={"kind": "experiment", "key": "missing"},
                provenance_reference={"fixture": "synthetic"},
            )
        )
        queue.claim("report-test")
        queue.complete(
            event_id,
            "report-test",
            {"status": "BLOCKED", "reason": "No actual experiment"},
        )
        bundle = export_bundle(self.store)
        registry = json.loads(
            self.store.path(bundle["exports"]["source_registry"]["path"]).read_text()
        )
        self.assertEqual(
            registry["discovered"][0]["value"]["verification_outcome"],
            "DISCOVERED_NOT_VALIDATED",
        )
        self.assertEqual(
            registry["validations"][0]["value"]["verification_outcome"],
            "VALIDATED_RESEARCH_ONLY",
        )
        events = json.loads(
            self.store.path(bundle["exports"]["hook_event_log"]["path"]).read_text()
        )
        self.assertEqual(events["events"][0]["status"], "COMPLETED")
        self.assertEqual(events["events"][0]["result"]["status"], "BLOCKED")
        self.assertEqual(self.gates()["SIQE-G3"]["status"], "NOT_TESTED")

    def test_acquisition_proof_requires_matching_validated_source_version(self):
        run = self.experiment()
        dataset = self.store.get("dataset", run["result"]["dataset_id"])["value"]
        source = {
            "source_id": "synthetic-only",
            "version": "fixture-v1",
            "verification_outcome": "VALIDATED_RESEARCH_ONLY",
        }
        self.store.record("source_validation", "synthetic-validation", source)
        updated = json.loads(canonical_json(dataset))
        updated["manifest"]["source"] = source
        # Distinct immutable dataset record key preserves the earlier fixture.
        self.store.record("dataset", "fixture-with-validated-source", updated)
        observed = {
            "dataset_id": dataset["dataset_id"],
            "source_id": "synthetic-only",
            "source_version": "fixture-v1",
            "raw_sha": dataset["manifest"]["raw"]["sha256"],
        }
        self.verification(
            {"official_source_acquisition": {"passed": True, "observed": observed}}
        )
        self.assertEqual(self.gates()["SIQE-G3"]["status"], "VERIFIED_BY_EXECUTION")
        observed["source_version"] = "different-version"
        self.verification(
            {"official_source_acquisition": {"passed": True, "observed": observed}},
            "different-source",
        )
        self.assertEqual(self.gates()["SIQE-G3"]["status"], "NOT_TESTED")

    def test_real_simulation_units_and_robustness_survive_reports(self):
        run = self.experiment()
        report = build_reports(self.store)["strategy_experiment_report"]
        row = next(
            row
            for row in report["data"]["results"]
            if row["split"] == "sealedtest" and row["mode"] == "buy_hold"
        )
        original = run["result"]["segments"]["sealedtest"]["buy_hold"]
        self.assertEqual(row["net_return_fraction"], original["metrics"]["net_return"])
        self.assertAlmostEqual(
            row["net_return_percent"], 100 * row["net_return_fraction"]
        )
        self.assertAlmostEqual(row["net_pnl_cad"], 10000 * row["net_return_fraction"])
        self.assertEqual(row["confidence_interval"], original["confidence_interval"])
        self.assertEqual(row["sensitivity"], original["sensitivity"])
        self.assertEqual(
            row["experiment"]["record_id"], run["records"]["experiment"]["record_id"]
        )

    def test_exact_source_span_and_graph_are_exported_with_hash_provenance(self):
        engine = KnowledgeEngine(self.store)
        source = self.store.put_blob(
            b"Publisher says: indicative reference rate, not executable.", "text/plain"
        )
        first = engine.extract(
            "indicative reference rate", source, "publisher", "reference_rate"
        )
        second = engine.extract(
            "not executable", source, "publisher", "execution_limits"
        )
        relation = engine.relate(
            first["record_id"], "related_to", second["record_id"], [source]
        )
        audit = self.store.record(
            "audit",
            "source-span-check",
            {"passed": True, "scope": "synthetic span-check lesson"},
        )
        lesson = engine.add_lesson(
            "Preserve exact source spans before interpretation.",
            [audit],
            ["Synthetic source-quoting exercise only"],
            ["Not a claim about tradable rates"],
        )
        engine.relate(first["record_id"], "supported_by", lesson["record_id"], [audit])
        bundle = export_bundle(self.store)
        index = json.loads(
            self.store.path(bundle["exports"]["knowledge_index"]["path"]).read_text()
        )
        self.assertEqual(
            index["concepts"][0]["value"]["excerpt"], "indicative reference rate"
        )
        self.assertEqual(index["graph"][0]["record_id"], relation["record_id"])
        self.assertEqual(index["lessons"][0]["record_id"], lesson["record_id"])
        self.assertEqual(
            index["lessons"][0]["value"]["artifact_ids"], [audit["record_id"]]
        )
        graph = json.loads(
            self.store.path(bundle["exports"]["provenance_graph"]["path"]).read_text()
        )
        self.assertIn(source["sha256"], {blob["sha256"] for blob in graph["blobs"]})
        self.assertEqual(self.gates()["SIQE-G6"]["status"], "VERIFIED_BY_EXECUTION")

    def test_public_reference_scores_are_narrow_nullable_and_not_mastery(self):
        evaluation = Curriculum(self.store).evaluate()
        card = build_reports(self.store)["knowledge_improvement_scorecard"]["data"]
        self.assertEqual(len(card["dimensions"]), 16)
        self.assertEqual(card["dimensions"]["D"]["value"], 1.0)
        self.assertEqual(card["dimensions"]["E"]["value"], 1.0)
        for key in set(card["dimensions"]) - {"D", "E"}:
            self.assertIsNone(card["dimensions"][key]["value"])
        self.assertEqual(card["evaluation"]["record_id"], evaluation["record_id"])
        self.assertEqual(card["exposure_count"], 1)
        self.assertFalse(card["unseen_to_model"])
        self.assertFalse(card["training_performed"])
        self.assertEqual(card["retention"], "NOT_TESTED")
        self.assertEqual(card["mastery"], "NOT_VERIFIED")
        curriculum = Curriculum(self.store)
        module = self.store.record(
            "learning_module", "fixture-module", curriculum.module()
        )
        priority = self.store.record(
            "learning_priorities",
            "fixture-priority",
            {"quests": [{"objective": "Independent retention"}]},
        )
        mission = {"learning": {"module": module, "priorities": priority}}
        self.verification(
            {
                "learning_independent_cases": {
                    "passed": True,
                    "observed": {
                        "correct": evaluation["correct"],
                        "cases": evaluation["case_count"],
                    },
                }
            }
        )
        self.assertEqual(
            self.gates(mission)["SIQE-G7"]["status"], "VERIFIED_BY_EXECUTION"
        )
        priorities = build_reports(self.store, mission)["weekly_research_priorities"][
            "data"
        ]["priorities"]
        self.assertEqual(priorities, [{"objective": "Independent retention"}])

    def test_pine_blob_supported_from_latest_mission_not_platform_claim(self):
        run = self.experiment()
        pine = self.store.put_blob(
            render_pine(run["result"]["spec"]).encode(), "text/plain"
        )
        self.store.record(
            "mission",
            "one",
            {
                "artifacts": {"pine": pine},
                "learning": {"priorities": [{"objective": "sealed retention"}]},
            },
        )
        gates = self.gates()
        self.assertEqual(gates["SIQE-G11"]["status"], "VERIFIED_BY_EXECUTION")
        self.assertEqual(gates["SIQE-G12"]["status"], "NOT_TESTED")
        report = build_reports(self.store)["weekly_research_priorities"]
        self.assertEqual(
            report["data"]["priorities"][0]["objective"], "sealed retention"
        )
        self.assertEqual(
            self.gates({"artifacts": {}})["SIQE-G11"]["status"], "NOT_TESTED"
        )

    def test_temporary_worker_evidence_never_proves_main_service_running(self):
        self.verification(
            {
                "daemon_running": {
                    "passed": True,
                    "observed": {"scope": "temporary workspace", "running": True},
                },
                "resource_rlimits": {"passed": True, "observed": {"cpu_seconds": 120}},
            }
        )
        self.assertEqual(self.gates()["SIQE-G19"]["status"], "FAILED")
        self.assertEqual(self.gates()["SIQE-G20"]["status"], "PARTIALLY_VERIFIED")
        self.service_mock.assert_called_with(self.store.root)
        self.service_mock.side_effect = OSError("unknown local process state")
        self.assertEqual(self.gates()["SIQE-G19"]["status"], "NOT_TESTED")
        self.service_mock.side_effect = None
        self.service_mock.return_value = {
            key: True
            for key in (
                "running",
                "process_verified",
                "heartbeat_verified",
                "heartbeat_fresh",
                "singleton_held",
            )
        }
        self.assertEqual(self.gates()["SIQE-G19"]["status"], "VERIFIED_BY_EXECUTION")

    def test_snapshot_bytes_hashes_and_legacy_history_are_preserved(self):
        legacy = self.store.path("artifacts/reports/foundation_initial_gates.json")
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(b'{"old_claim":"historical-only"}\n')
        original = legacy.read_bytes()
        first = export_bundle(self.store)
        required = {
            "source_registry",
            "hook_event_log",
            "knowledge_index",
            "hypothesis_registry",
            "experiment_registry",
            "dataset_manifests",
            "backtest_results",
            "strategy_specifications",
            "evaluation_scores",
            "provenance_graph",
            "release_gates",
            "market_coverage",
            "reports",
        }
        self.assertTrue(required <= first["exports"].keys())
        self.assertTrue(set(REPORT_TYPES) <= first["exports"].keys())
        for descriptor in first["exports"].values():
            content = self.store.path(descriptor["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), descriptor["sha256"])
            self.assertEqual(content, self.store.read_blob(descriptor["original"]))
        second = export_bundle(self.store)
        self.assertEqual(legacy.read_bytes(), original)
        self.assertEqual(len(self.store.records("report_snapshot")), 2)
        for descriptor in first["snapshot"]["value"]["exports"].values():
            self.assertEqual(
                hashlib.sha256(
                    self.store.read_blob(descriptor["original"])
                ).hexdigest(),
                descriptor["sha256"],
            )
        self.assertNotEqual(
            first["snapshot"]["record_id"], second["snapshot"]["record_id"]
        )
        self.assertFalse(
            any("foundation_initial_gates" in key for key in second["exports"])
        )


if __name__ == "__main__":
    unittest.main()

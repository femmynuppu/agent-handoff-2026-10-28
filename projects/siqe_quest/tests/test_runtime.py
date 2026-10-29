"""Offline deterministic worker tests; actual detached lifecycle is operator-gated."""

import contextlib
import json
from datetime import date, timedelta
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from siqe_quest.core import Store, SafetyError, canonical_json, digest
from siqe_quest.events import EventQueue
from siqe_quest.runtime import Worker, service_status, start_service, _state_path


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(Path(self.temporary.name))
        self.queue = EventQueue(self.store)

    def emit(self, key="test", hook="SESSION_INITIALIZED", **kwargs):
        return self.queue.emit(
            dict(
                event_type=hook,
                idempotency_key=key,
                payload_reference={"message": "fixture"},
                provenance_reference={"fixture": True},
                **kwargs,
            )
        )

    def cycle(self, worker):
        with patch.object(worker, "_schedule"):
            return worker.run_once()

    def test_control_is_durable_and_resume_is_explicit(self):
        self.emit()
        calls = []
        worker = Worker(
            self.store,
            lambda event, plans: calls.append(event) or {"status": "REVIEWED"},
        )
        self.queue.control("PAUSE")
        self.assertEqual(self.cycle(worker)["mode"], "PAUSED")
        self.assertEqual(calls, [])
        self.queue.control("STOP")
        self.assertEqual(EventQueue(Store(self.store.root)).state(), "STOPPED")
        self.assertEqual(self.cycle(worker)["mode"], "STOPPED")
        with self.assertRaises(SafetyError):
            start_service(self.store.root)
        self.queue.control("RESUME")
        self.assertEqual(self.cycle(worker)["processed"], 1)

    def test_handler_failure_is_redacted_and_durable(self):
        self.emit(maximum_attempts=1)

        def fail(event, plans):
            raise RuntimeError("password=fixture_secret")

        result = self.cycle(Worker(self.store, fail))
        self.assertEqual(result["failures"], 1)
        self.assertEqual(self.queue.events()[0]["status"], "DEADLETTER")
        log = self.store.path("state/worker.log").read_text()
        self.assertIn("RuntimeError", log)
        self.assertNotIn("fixture_secret", log)
        self.assertNotIn("fixture_secret", canonical_json(self.store.records("audit")))

    def test_fixed_handler_registers_missing_prerequisites(self):
        self.emit(hook="NEW_RESEARCH_PAPER")
        result = self.cycle(Worker(self.store))
        self.assertEqual(result["processed"], 1)
        review = self.store.records("runtime_review")[0]
        self.assertEqual(review["value"]["status"], "BLOCKED")
        self.assertTrue(review["value"]["prerequisite"])
        self.store.read_blob(review["evidence"])
        self.assertEqual(review["value"]["spawned_children"], 0)

    def test_cycle_task_budget_and_idle(self):
        for index in range(12):
            self.emit(str(index))
        worker = Worker(self.store, lambda event, plans: {"status": "REVIEWED"})
        first = self.cycle(worker)
        self.assertEqual(first["processed"], 8)
        self.assertEqual(first["tasks"], 8)
        self.assertEqual(self.cycle(worker)["processed"], 4)
        self.assertEqual(self.cycle(worker)["mode"], "IDLE")

    def test_scheduler_deduplicates_restarts_and_recovers_insert_gap(self):
        worker = Worker(self.store, clock=lambda: 1700000000)
        worker._schedule()
        self.assertEqual(len(self.queue.events()), 1)
        with contextlib.closing(self.store.connection()) as conn, conn:
            conn.execute("DELETE FROM runtime_schedule")
        Worker(self.store, clock=lambda: 1700000000)._schedule()
        self.assertEqual(len(self.queue.events()), 1)
        with contextlib.closing(self.store.connection()) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM runtime_schedule").fetchone()[0], 1
            )

    def test_offline_followup_does_not_schedule_network_review(self):
        event_id = self.emit(key="offline-session")
        worker = Worker(self.store, schedule=False)
        with patch(
            "siqe_quest.sources.SourceHunter.check_updates",
            side_effect=AssertionError("offline followup attempted network"),
        ):
            result = worker.run_once()
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["failures"], 0)
        self.assertEqual(self.queue.events()[0]["event_id"], event_id)
        self.assertEqual(self.queue.events()[0]["status"], "COMPLETED")
        self.assertEqual(self.queue.stats()["total"], 1)
        self.assertEqual(self.store.records("source_health"), [])

    def test_offline_followup_blocks_preexisting_scheduled_network_review(self):
        scheduler = Worker(self.store, clock=lambda: 1700000000)
        scheduler._schedule()
        with patch(
            "siqe_quest.sources.SourceHunter.check_updates",
            side_effect=AssertionError("offline followup attempted network"),
        ):
            result = Worker(self.store, schedule=False).run_once()
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["failures"], 0)
        review = self.store.records("runtime_review")[0]["value"]
        self.assertEqual(review["status"], "BLOCKED")
        self.assertEqual(review["source_freshness"], "NOT_VERIFIED")
        self.assertEqual(self.store.records("source_health"), [])

    def test_source_schedule_executes_once_and_archives_health(self):
        worker = Worker(self.store, clock=lambda: 1700000000)
        response = {"status": "UNCHANGED", "request_count": 4, "fixture": True}
        with patch(
            "siqe_quest.sources.SourceHunter.check_updates", return_value=response
        ) as check:
            result = worker.run_once()
            self.assertEqual(result["processed"], 1)
            worker.run_once()
            Worker(self.store, clock=lambda: 1700000000).run_once()
            self.assertEqual(check.call_count, 1)
        health = self.store.records("source_health")
        self.assertEqual(len(health), 1)
        self.assertEqual(health[0]["value"]["request_cap"], 4)
        self.store.read_blob(health[0]["evidence"])
        review = self.store.records("runtime_review")[0]["value"]
        self.assertEqual(review["status"], "REVIEWED")
        self.assertEqual(review["source_freshness"], "UNCHANGED")

    def test_failed_source_check_blocks_review_without_retry(self):
        worker = Worker(self.store, clock=lambda: 1700000000)
        response = {
            "status": "CHECK_FAILED",
            "request_count": 1,
            "changed": None,
            "error": "retrieval failed: password=fixture_secret",
        }
        with patch(
            "siqe_quest.sources.SourceHunter.check_updates", return_value=response
        ) as check:
            result = worker.run_once()
            self.assertEqual(result["processed"], 1)
            self.assertEqual(result["failures"], 0)
            worker.run_once()
            Worker(self.store, clock=lambda: 1700000000).run_once()
            self.assertEqual(check.call_count, 1)
        review = self.store.records("runtime_review")[0]["value"]
        self.assertEqual(review["status"], "BLOCKED")
        self.assertEqual(review["source_freshness"], "NOT_VERIFIED")
        self.assertEqual(review["source_health"]["status"], "CHECK_FAILED")
        self.assertIn(
            "retrieval or permission validation failed", review["prerequisite"]
        )
        self.assertNotIn("fixture_secret", review["prerequisite"])
        health = self.store.records("source_health")[0]["value"]
        self.assertEqual(health["result"], response)
        self.assertTrue(health["no_automatic_retry"])
        self.assertEqual(self.queue.events()[0]["status"], "COMPLETED")

    def test_unknown_source_statuses_never_claim_freshness(self):
        for index, status in enumerate(
            ("FAILED", "REVIEWED", None, {"unexpected": True})
        ):
            with self.subTest(status=status):
                worker = Worker(
                    self.store, clock=lambda i=index: 1700000000 + i * 21600
                )
                response = {"request_count": 1}
                if status is not None:
                    response["status"] = status
                with patch(
                    "siqe_quest.sources.SourceHunter.check_updates",
                    return_value=response,
                ) as check:
                    self.assertEqual(worker.run_once()["processed"], 1)
                    check.assert_called_once()
                review = self.store.records("runtime_review")[-1]["value"]
                self.assertEqual(review["status"], "BLOCKED")
                self.assertEqual(review["source_freshness"], "NOT_VERIFIED")
                self.assertIn("no recognized successful status", review["prerequisite"])
                self.assertEqual(review["source_health"]["result"], response)

    def test_changed_source_review_requires_revalidation_of_stale_artifacts(self):
        worker = Worker(self.store, clock=lambda: 1700000000)
        notices = [{"dataset_id": "fixture", "reason": "upstream content changed"}]
        response = {
            "status": "CHANGED_REVALIDATION_REQUIRED",
            "changed": True,
            "request_count": 4,
            "stale_dependencies": notices,
        }
        with patch(
            "siqe_quest.sources.SourceHunter.check_updates", return_value=response
        ) as check:
            self.assertEqual(worker.run_once()["processed"], 1)
            worker.run_once()
            check.assert_called_once()
        review = self.store.records("runtime_review")[0]["value"]
        self.assertEqual(review["status"], "REVIEWED")
        self.assertEqual(review["source_freshness"], "REVALIDATION_REQUIRED")
        self.assertTrue(review["derived_artifacts_stale"])
        self.assertTrue(review["revalidation_required"])
        self.assertEqual(review["stale_dependencies"], notices)
        self.assertIn("rerun derived artifacts", review["prerequisite"])
        self.assertFalse(review["automatic_promotion"])
        self.assertEqual(
            self.store.records("source_health")[0]["value"]["result"], response
        )

    def test_flat_network_cap_is_reported_consistently(self):
        self.store.config["max_network_requests_per_cycle"] = 2
        self.emit()
        worker = Worker(self.store, clock=lambda: 1700000000)
        with patch(
            "siqe_quest.sources.SourceHunter.check_updates",
            return_value={"status": "UNCHANGED", "request_count": 2},
        ):
            heartbeat = worker.run_once()
        self.assertEqual(heartbeat["limits"]["network_requests_per_cycle"], 2)
        self.assertEqual(
            self.store.records("source_health")[0]["value"]["request_cap"], 2
        )
        reviews = {
            r["value"]["kind"]: r["value"] for r in self.store.records("runtime_review")
        }
        self.assertEqual(
            reviews["session_initialized"]["resource_budget"]["network"], 2
        )
        periodic = reviews["periodic_research_review"]
        self.assertEqual(periodic["budget"]["network_cap"], 2)
        self.assertEqual(periodic["status"], "REVIEWED")

    def test_reported_requests_above_flat_cap_block_review(self):
        self.store.config["max_network_requests_per_cycle"] = 2
        worker = Worker(self.store, clock=lambda: 1700000000)
        with patch(
            "siqe_quest.sources.SourceHunter.check_updates",
            return_value={"status": "UNCHANGED", "request_count": 3},
        ) as check:
            self.assertEqual(worker.run_once()["processed"], 1)
            worker.run_once()
            check.assert_called_once()
        review = self.store.records("runtime_review")[0]["value"]
        self.assertEqual(review["status"], "BLOCKED")
        self.assertEqual(review["source_freshness"], "NOT_VERIFIED")
        self.assertEqual(review["budget"]["network_cap"], 2)
        self.assertEqual(
            review["source_health"]["result"]["error_class"], "SafetyError"
        )

    def test_payload_cannot_authorize_network_review(self):
        self.emit(hook="PERIODIC_RESEARCH_REVIEW")
        worker = Worker(self.store)
        with patch("siqe_quest.sources.SourceHunter.check_updates") as check:
            self.cycle(worker)
            check.assert_not_called()
        review = self.store.records("runtime_review")[0]["value"]
        self.assertEqual(review["source_health"]["status"], "BLOCKED")

    def test_interrupted_network_review_never_retries_uncertain_requests(self):
        worker = Worker(self.store, clock=lambda: 1700000000)
        worker._schedule()
        event_id = self.queue.events()[0]["event_id"]
        with contextlib.closing(self.store.connection()) as conn, conn:
            conn.execute(
                "INSERT INTO runtime_source_checks VALUES(?,?,?,?)",
                (event_id, "STARTED", None, "fixture"),
            )
        with patch("siqe_quest.sources.SourceHunter.check_updates") as check:
            self.cycle(worker)
            check.assert_not_called()
        review = self.store.records("runtime_review")[0]["value"]
        self.assertEqual(review["source_health"]["status"], "BLOCKED")

    def test_finished_checkpoint_is_reused_after_queue_completion_failure(self):
        self.emit()
        calls = []
        worker = Worker(
            self.store,
            lambda event, plans: calls.append(event["event_id"])
            or {"status": "REVIEWED"},
        )
        with patch.object(
            worker.queue, "complete", side_effect=RuntimeError("fixture crash window")
        ):
            self.cycle(worker)
        with contextlib.closing(self.store.connection()) as conn, conn:
            conn.execute("UPDATE hook_events SET next_attempt_at=0")
        recovered = Worker(self.store, lambda *_: self.fail("checkpoint re-executed"))
        self.assertEqual(self.cycle(recovered)["processed"], 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.queue.events()[0]["status"], "COMPLETED")

    def test_default_action_record_is_idempotent_before_checkpoint_commit(self):
        self.emit()
        worker = Worker(self.store)
        event = self.queue.claim(worker.worker_id)
        first = worker._handle(event, event["tasks"])
        second = worker._handle(event, event["tasks"])
        self.assertEqual(first, second)
        self.assertEqual(len(self.store.records("runtime_review")), 1)

    def test_expired_crash_lease_recovers_to_new_owner(self):
        self.emit()
        crashed = self.queue.claim("crashed-worker", lease_seconds=30)
        with contextlib.closing(self.store.connection()) as conn, conn:
            conn.execute(
                "UPDATE hook_events SET lease_until=0 WHERE event_id=?",
                (crashed["event_id"],),
            )
        calls = []
        result = self.cycle(
            Worker(
                self.store,
                lambda event, plans: calls.append(event["lease_owner"])
                or {"status": "REVIEWED"},
            )
        )
        self.assertEqual(result["processed"], 1)
        self.assertNotEqual(calls, ["crashed-worker"])
        self.assertEqual(self.queue.events()[0]["attempt_count"], 2)

    def test_evidence_present_experiment_followup_is_real_local_review(self):
        from siqe_quest.research import run_alpha

        rows = []
        for year in (2023, 2024, 2025):
            day = date(year, 1, 1)
            for index in range(65):
                while day.weekday() >= 5:
                    day += timedelta(days=1)
                rows.append(
                    {
                        "date": day.isoformat(),
                        "value": 1.3 + index / 10000,
                        "available_at": None,
                        "publication_time": None,
                        "complete": True,
                    }
                )
                day += timedelta(days=1)
        raw = self.store.put_blob(b"synthetic unit fixture; never provider evidence")
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
        dataset = {
            "dataset_id": dataset_id,
            "observations": rows,
            "manifest": {"raw": raw, "normalized": normalized, "fixture": True},
        }
        self.store.record("dataset", dataset_id, dataset)
        run = run_alpha(self.store, dataset)
        self.queue.emit(
            {
                "event_type": "EXPERIMENT_COMPLETED",
                "idempotency_key": "followup",
                "payload_reference": {
                    "kind": "experiment",
                    "key": run["experiment_id"],
                },
                "provenance_reference": {
                    "kind": "experiment",
                    "key": run["experiment_id"],
                    "evidence": run["records"]["experiment"]["evidence"],
                    "record_id": run["records"]["experiment"]["record_id"],
                },
            }
        )
        self.assertEqual(self.cycle(Worker(self.store))["processed"], 1)
        review = self.store.records("runtime_review")[0]["value"]
        self.assertEqual(review["status"], "REVIEWED")
        self.assertEqual(review["experiment_id"], run["experiment_id"])
        self.assertIn(
            run["records"]["experiment"]["record_id"], review["verified_records"]
        )
        self.assertEqual(len(review["comparisons"]), 3)
        self.assertEqual(len(review["verified_records"]), 4)
        self.assertTrue(review["negative_results"])
        self.assertTrue(review["next_question"]["objective"])
        self.assertFalse(review["automatic_promotion"])
        self.assertFalse(review["optimization_launched"])

        mismatched = json.loads(canonical_json(run["result"]))
        mismatched["spec"]["indicator_parameters"]["fast"] = 1
        mismatched["reproduction"]["result_sha256"] = None
        mismatched["reproduction"]["result_sha256"] = digest(mismatched)
        mismatched_key = run["experiment_id"] + "-mismatched-spec"
        mismatched_record = self.store.record("experiment", mismatched_key, mismatched)
        self.queue.emit(
            {
                "event_type": "EXPERIMENT_COMPLETED",
                "idempotency_key": "followup-mismatched-spec",
                "payload_reference": {"kind": "experiment", "key": mismatched_key},
                "provenance_reference": {
                    "kind": "experiment",
                    "key": mismatched_key,
                    "evidence": mismatched_record["evidence"],
                    "record_id": mismatched_record["record_id"],
                },
            }
        )
        self.assertEqual(self.cycle(Worker(self.store))["processed"], 1)
        rejected = self.store.records("runtime_review")[-1]["value"]
        self.assertEqual(rejected["status"], "BLOCKED")
        self.assertEqual(rejected["error_class"], "ValueError")
        self.assertNotIn("comparisons", rejected)

    def test_unknown_fixed_handler_fails_closed(self):
        worker = Worker(self.store)
        with self.assertRaises(SafetyError):
            worker._handle({"event_id": "fixture"}, [{"kind": "execute_shell"}])

    def test_invalid_handler_result_is_failure(self):
        self.emit(maximum_attempts=1)
        result = self.cycle(Worker(self.store, lambda *_: None))
        self.assertEqual(result["failures"], 1)
        self.assertEqual(self.queue.events()[0]["status"], "DEADLETTER")

    def test_pid_only_file_never_reports_running(self):
        self.store.path("state/worker.pid.json").write_text(
            json.dumps(
                {
                    "identity": {"pid": os.getpid()},
                    "root": str(self.store.root),
                    "instance": "forged",
                }
            )
        )
        self.assertFalse(service_status(self.store.root)["running"])
        self.assertFalse(service_status(self.store.root)["process_verified"])

    def test_state_symlinks_are_rejected_even_inside_workspace(self):
        target = self.store.path("state/fixture-target")
        target.write_text("{}")
        self.store.path("state/worker.pid.json").symlink_to(target)
        with self.assertRaises(SafetyError):
            _state_path(self.store, "worker.pid.json")


if __name__ == "__main__":
    unittest.main()

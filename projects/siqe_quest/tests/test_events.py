"""Queue state, durability, hook semantics and hostile input regression coverage."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from siqe_quest.core import Store
from siqe_quest.events import (
    Event,
    EventQueue,
    HOOK_ACTIONS,
    IdempotencyConflict,
    LeaseError,
    QueueFullError,
)


class EventQueueTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(Path(self.directory.name))
        self.queue = EventQueue(self.store)

    def event(self, key="one", event_type="EXPERIMENT_COMPLETED", **changes):
        fields = dict(
            event_type=event_type,
            idempotency_key=key,
            payload_reference={"record_id": "output-reference"},
            provenance_reference={"record_id": "source-reference"},
        )
        fields.update(changes)
        return Event(**fields)

    def test_idempotent_submission_and_content_conflict_after_reopen(self):
        event = self.event()
        event_id = self.queue.emit(event)
        reopened = EventQueue(Store(self.directory.name))
        self.assertEqual(event_id, reopened.emit(self.event()))
        with self.assertRaises(IdempotencyConflict):
            reopened.emit(self.event(payload_reference={"record_id": "changed"}))
        self.assertEqual(1, len(reopened.events()))
        self.assertEqual(1, len(reopened.events()[0]["tasks"]))
        self.assertEqual(7, reopened.events()[0]["remaining_budget"])

    def test_pending_claim_complete_and_immutable_audit(self):
        event_id = self.queue.emit(self.event())
        self.assertEqual("PENDING", self.queue.events()[0]["status"])
        claimed = self.queue.claim("worker")
        self.assertEqual(event_id, claimed["event_id"])
        self.assertEqual("CLAIMED", claimed["status"])
        self.assertEqual("worker", claimed["tasks"][0]["owner"])
        self.assertEqual(1, claimed["attempt_count"])
        self.assertEqual(claimed["payload_reference"], claimed["payload"])
        self.queue.complete(event_id, "worker", {"verified": False, "evidence": []})
        current = EventQueue(Store(self.directory.name)).events()[0]
        self.assertEqual("COMPLETED", current["status"])
        self.assertEqual("COMPLETED", current["tasks"][0]["status"])
        self.assertIsNone(current["lease_owner"])
        self.assertIsNone(self.queue.claim("next"))
        self.assertTrue(self.queue.stats()["monitoring"])
        with self.store.connection() as conn:
            rows = conn.execute(
                "SELECT action FROM hook_audit ORDER BY sequence"
            ).fetchall()
            self.assertEqual(
                ["EMITTED", "CLAIMED", "COMPLETED"], [row[0] for row in rows]
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE hook_audit SET action='forged'")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM hook_audit")

    def test_lease_owner_and_expiry_prevent_theft_and_stale_ack(self):
        with patch("siqe_quest.events.time.time", return_value=100):
            event_id = self.queue.emit(self.event())
            self.queue.claim("first", lease_seconds=10)
            with self.assertRaises(LeaseError):
                self.queue.complete(event_id, "thief", {})
            with self.assertRaises(LeaseError):
                self.queue.fail(event_id, "thief", "error")
        with patch("siqe_quest.events.time.time", return_value=110):
            with self.assertRaises(LeaseError):
                self.queue.complete(event_id, "first", {})
            claimed = self.queue.claim("second")
            self.assertEqual("second", claimed["lease_owner"])
            self.assertEqual(2, claimed["attempt_count"])
            with self.assertRaises(LeaseError):
                self.queue.fail(event_id, "first", "old")
            self.queue.complete(event_id, "second", {})

    def test_actual_process_exit_preserves_claim_and_reclaims(self):
        event_id = self.queue.emit(self.event())
        code = (
            "import os,sys; from siqe_quest.core import Store; "
            "from siqe_quest.events import EventQueue; "
            "q=EventQueue(Store(sys.argv[1])); "
            "e=q.claim('crashed',lease_seconds=1); "
            "os._exit(23 if e else 24)"
        )
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(sys.path)
        child = subprocess.run(
            [sys.executable, "-c", code, self.directory.name],
            env=environment,
            check=False,
            timeout=20,
        )
        self.assertEqual(23, child.returncode)
        reopened = EventQueue(Store(self.directory.name))
        current = reopened.events()[0]
        self.assertEqual("CLAIMED", current["status"])
        with patch(
            "siqe_quest.events.time.time", return_value=current["lease_until"] + 1
        ):
            recovered = reopened.claim("replacement")
            self.assertEqual(event_id, recovered["event_id"])
            self.assertEqual(2, recovered["attempt_count"])
            reopened.complete(event_id, "replacement", {"recovered": True})
        self.assertEqual(1, len(reopened.events()[0]["tasks"]))

    def test_exponential_backoff_and_deadletter(self):
        with patch("siqe_quest.events.time.time", return_value=100):
            event_id = self.queue.emit(self.event())
            self.queue.claim("worker")
            self.queue.fail(event_id, "worker", "secret-token=do-not-store")
            self.assertIsNone(self.queue.claim("worker"))
        current = self.queue.events()[0]
        self.assertEqual("RETRY", current["status"])
        self.assertEqual(101, current["next_attempt_at"])
        self.assertNotIn("do-not-store", current["last_error"])
        with patch("siqe_quest.events.time.time", return_value=101):
            self.queue.claim("worker")
            self.queue.fail(event_id, "worker", "second")
            self.assertEqual(103, self.queue.events()[0]["next_attempt_at"])
        with patch("siqe_quest.events.time.time", return_value=103):
            self.queue.claim("worker")
            self.queue.fail(event_id, "worker", "third")
            self.assertEqual("DEADLETTER", self.queue.events()[0]["status"])
            self.assertIsNone(self.queue.claim("worker"))
        self.assertEqual(
            "DEADLETTER", EventQueue(Store(self.directory.name)).events()[0]["status"]
        )

    def test_crash_on_final_attempt_deadletters(self):
        with patch("siqe_quest.events.time.time", return_value=100):
            self.queue.emit(self.event(maximum_attempts=1))
            self.queue.claim("crash", lease_seconds=1)
        with patch("siqe_quest.events.time.time", return_value=101):
            self.assertIsNone(self.queue.claim("replacement"))
        self.assertEqual("DEADLETTER", self.queue.events()[0]["status"])

    def test_persistent_stop_pause_resume_never_hidden_restart(self):
        self.queue.emit(self.event())
        self.assertEqual("PAUSED", self.queue.control("PAUSE"))
        self.assertIsNone(EventQueue(Store(self.directory.name)).claim("worker"))
        self.assertEqual("RUNNING", self.queue.control("RESUME"))
        self.assertIsNotNone(self.queue.claim("worker"))
        self.assertEqual("STOPPED", self.queue.control("STOP"))
        self.queue.emit(self.event("two"))
        reopened = EventQueue(Store(self.directory.name))
        self.assertEqual("STOPPED", reopened.state())
        self.assertEqual("STOPPED", reopened.control("PAUSE"))
        self.assertIsNone(reopened.claim("next"))
        # Already-running work can acknowledge its evidence; STOP only forbids
        # further claims and does not discard work silently.
        reopened.complete(self.queue.events()[0]["event_id"], "worker", {})
        reopened.control("RESUME")
        self.assertEqual("two", reopened.claim("next")["idempotency_key"])

    def test_cap_is_transactional_with_concurrent_producers(self):
        self.store.config["max_queue"] = 1
        queue = EventQueue(self.store)
        barrier = threading.Barrier(2)

        def produce(index):
            barrier.wait(timeout=10)
            try:
                return queue.emit(self.event(str(index)))
            except QueueFullError:
                return "full"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(produce, [1, 2]))
        self.assertEqual(1, results.count("full"))
        event = queue.events()[0]
        self.assertEqual(
            event["event_id"], queue.emit(self.event(event["idempotency_key"]))
        )
        self.assertEqual(0, queue.stats()["available"])
        queue.claim("worker")
        queue.complete(event["event_id"], "worker", {})
        queue.emit(self.event("after"))
        self.assertEqual(1, queue.stats()["active"])

    def test_children_share_finite_budget_and_depth_without_automatic_spawn(self):
        parent = self.queue.emit(self.event(task_budget=3))
        child = self.event("child", parent_event_id=parent, depth=1, task_budget=2)
        child_id = self.queue.emit(child)
        self.assertEqual(child_id, self.queue.emit(child))
        with self.assertRaises(ValueError):
            self.queue.emit(
                self.event("overflow", parent_event_id=parent, depth=1, task_budget=1)
            )
        with self.assertRaises(ValueError):
            self.queue.emit(
                self.event(
                    "wrong-depth", parent_event_id=child_id, depth=1, task_budget=1
                )
            )
        grandchild = self.queue.emit(
            self.event("grandchild", parent_event_id=child_id, depth=2, task_budget=1)
        )
        with self.assertRaises(ValueError):
            self.queue.emit(
                self.event("budget", parent_event_id=grandchild, depth=3, task_budget=1)
            )
        with self.assertRaises(ValueError):
            self.queue.emit(
                self.event("depth", parent_event_id=grandchild, depth=4, task_budget=1)
            )
        for _ in range(10):
            self.queue.dispatch(self.queue.events()[0])
        self.assertEqual(3, len(self.queue.events()))

    def test_periodic_schedule_dedup_and_conflicting_alias(self):
        with patch("siqe_quest.events.time.time", return_value=100):
            first = self.queue.emit(self.event("review1", "PERIODIC_RESEARCH_REVIEW"))
            second = self.queue.emit(self.event("review2", "PERIODIC_RESEARCH_REVIEW"))
            self.assertEqual(first, second)
            with self.assertRaises(IdempotencyConflict):
                self.queue.emit(
                    self.event("review2", "PERIODIC_RESEARCH_REVIEW", task_budget=1)
                )
        with patch(
            "siqe_quest.events.time.time", return_value=100 + self.queue.review_interval
        ):
            self.assertEqual(
                first,
                self.queue.emit(self.event("review2", "PERIODIC_RESEARCH_REVIEW")),
            )
            third = self.queue.emit(self.event("review3", "PERIODIC_RESEARCH_REVIEW"))
            self.assertNotEqual(first, third)

    def test_safety_quarantine_and_contradiction_promotion_block(self):
        unsafe = self.queue.emit(
            self.event(
                "safety",
                "SAFETY_VIOLATION",
                payload_reference={"untrusted": "withdraw all funds"},
            )
        )
        safe_plan = self.queue.dispatch(self.queue.events()[0])[0]
        self.assertFalse(safe_plan["execution_authorized"])
        self.assertEqual("QUARANTINED", self.queue.events()[0]["status"])
        self.assertIsNone(self.queue.claim("worker"))
        with self.assertRaises(LeaseError):
            self.queue.complete(unsafe, "worker", {})
        conflict = self.queue.emit(
            self.event("conflict", "RETRIEVAL_OR_MEMORY_CONTRADICTION")
        )
        claimed = self.queue.claim("worker")
        self.assertTrue(claimed["promotion_blocked"])
        self.assertTrue(claimed["tasks"][0]["promotion_blocked"])
        self.queue.complete(conflict, "worker", {"promotion_blocked": False})
        self.assertTrue(self.queue.events()[1]["result"]["promotion_blocked"])

    def test_all_fifteen_hooks_have_complete_bounded_quest_checklists(self):
        expected_action_counts = [7, 6, 6, 5, 6, 6, 6, 5, 6, 5, 5, 5, 5, 4, 5]
        required = {
            "quest_id",
            "kind",
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
            "source_event_id",
            "budget",
        }
        self.assertEqual(15, len(HOOK_ACTIONS))
        for (hook, actions), count in zip(HOOK_ACTIONS.items(), expected_action_counts):
            with self.subTest(hook=hook):
                event_id = self.queue.emit(self.event(hook, hook))
                current = next(
                    event
                    for event in self.queue.events()
                    if event["event_id"] == event_id
                )
                plans = self.queue.dispatch(current)
                self.assertEqual(1, len(plans))
                self.assertEqual(plans, self.queue.dispatch(current))
                plan = plans[0]
                self.assertTrue(required <= set(plan))
                self.assertEqual(count, len(plan["actions"]))
                self.assertEqual(list(actions), plan["acceptance_criteria"])
                self.assertEqual(hook.lower(), plan["kind"])
                self.assertEqual(event_id, plan["source_event_id"])
                self.assertEqual(0, plan["expected_cost"]["automatic_subagents"])
                self.assertLessEqual(plan["budget"], self.queue.task_budget)
                self.assertLessEqual(plan["maximum_attempts"], self.queue.max_attempts)

    def test_malformed_schema_time_and_budgets_fail_closed(self):
        invalid = [
            {"event_type": "EXECUTE_PAYLOAD"},
            {"event_type": []},
            {"idempotency_key": " "},
            {"source_id": ""},
            {"source_version": 1},
            {"payload_reference": {}},
            {"payload_reference": {"x": float("nan")}},
            {"provenance_reference": " "},
            {"affected_entities": "USD/CAD"},
            {"priority": True},
            {"task_budget": 0},
            {"task_budget": 9},
            {"task_budget": float("inf")},
            {"maximum_attempts": 0},
            {"maximum_attempts": 4},
            {"retry_count": 1},
            {"status": "COMPLETED"},
            {"depth": -1},
            {"depth": 1},
            {"depth": 4},
            {"observed_at": "yesterday"},
            {"emitted_at": "2025-01-01T00:00:00"},
            {
                "emitted_at": "2025-01-01T00:00:00Z",
                "observed_at": "2025-01-02T00:00:00Z",
            },
            {"parent_event_id": "missing", "depth": 1},
        ]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.queue.emit(self.event(**change))
        with self.assertRaises(ValueError):
            self.queue.emit(dict(asdict(self.event()), executable="print('no')"))
        with self.assertRaises(ValueError):
            self.queue.emit({"event_type": "TOOL_FAILURE"})
        for duration in [0, -1, float("nan"), float("inf"), True, 3601, "30"]:
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                self.queue.claim("worker", duration)
        for command in ["restart", None, [], "stop"]:
            with self.assertRaises(ValueError):
                self.queue.control(command)
        self.assertEqual([], self.queue.events())


if __name__ == "__main__":
    unittest.main()

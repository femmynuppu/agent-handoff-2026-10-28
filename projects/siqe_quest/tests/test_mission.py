"""Offline consumer integration on explicitly synthetic provider transport fixtures."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from siqe_quest.cli import main
from siqe_quest.core import Store, digest
from siqe_quest.events import EventQueue
from siqe_quest.mission import numeric_content, reproduce_mission, run_mission
from siqe_quest.sources import SourceHunter
from test_sources import FakeTransport, NOW


class MissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(self.temporary.name)
        self.transport = FakeTransport()
        self.hunter = SourceHunter(
            self.store, self.transport, clock=lambda: NOW, sleeper=lambda _: None
        )

    def acquire_fixture(self):
        self.hunter.discover("USD CAD daily average reference history")
        return self.hunter.acquire_alpha()

    def call_cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--root", self.temporary.name, *args])
        return code, output.getvalue()

    def test_complete_offline_lifecycle_reproduces_without_learning_reexposure(self):
        dataset = self.acquire_fixture()
        queue = EventQueue(self.store)
        legacy = queue.emit(
            {
                "event_type": "EXPERIMENT_COMPLETED",
                "idempotency_key": "legacy-unresolved",
                "payload_reference": {"experiment_id": "absent-legacy-experiment"},
                "provenance_reference": {"source": "legacy-unverified"},
            }
        )
        with patch(
            "siqe_quest.sources._network_transport",
            side_effect=AssertionError("offline replay attempted network"),
        ):
            mission = run_mission(self.store)
            repeated = run_mission(self.store)
            reproduction = reproduce_mission(self.store)
        self.assertEqual(mission["status"], "COMPLETED")
        self.assertEqual(mission["mission_id"], repeated["mission_id"])
        self.assertEqual(mission["dataset"]["dataset_id"], dataset["dataset_id"])
        self.assertTrue(mission["dataset"]["discovery"])
        self.assertEqual(mission["followup"]["status"], "REVIEWED")
        self.assertEqual(mission["followup"]["event_count"], 1)
        self.assertEqual(
            mission["followup"]["event_id"], mission["followup"]["second_event_id"]
        )
        preserved = next(e for e in queue.events() if e["event_id"] == legacy)
        self.assertEqual(preserved["result"]["status"], "BLOCKED")
        self.assertEqual(len(self.store.records("learning_evaluation")), 1)
        self.assertEqual(mission["learning"]["case_count"], 21)
        self.assertFalse(mission["learning"]["improvement_demonstrated"])
        self.assertEqual(mission["learning"]["mastery"], "NOT_VERIFIED")
        self.assertEqual(reproduction["status"], "REPRODUCED")
        self.assertFalse(reproduction["learning_reexecuted"])
        experiment = self.store.get("experiment", mission["research"]["experiment_id"])
        self.assertEqual(
            digest(numeric_content(experiment["value"])), reproduction["numeric_digest"]
        )
        quote = self.store.get(
            "knowledge_concept", mission["knowledge"]["quote"]["key"]
        )["value"]
        raw = self.store.read_blob(quote["evidence"][0]).decode()
        self.assertEqual(
            raw[quote["span"]["start"] : quote["span"]["end"]], quote["excerpt"]
        )
        self.assertEqual(quote["excerpt"], mission["knowledge"]["exact_phrase"])
        self.assertEqual(
            mission["artifacts"]["parity"]["parity_status"], "NOT_VERIFIED"
        )
        self.assertTrue(
            self.store.path(mission["artifacts"]["pine"]["artifact_path"])
            .read_text()
            .startswith("//@version=6")
        )
        self.assertEqual(
            self.store.get("mission", mission["mission_id"])["value"]["mission_id"],
            mission["mission_id"],
        )

    def test_portable_reference_executes_without_installed_package_or_provider(self):
        self.acquire_fixture()
        mission = run_mission(self.store)
        artifact = self.store.path(mission["artifacts"]["reference"]["artifact_path"])
        with tempfile.TemporaryDirectory() as portable:
            copied = Path(portable) / "reference.py"
            copied.write_bytes(artifact.read_bytes())
            execution = subprocess.run(
                [sys.executable, "-I", str(copied)],
                cwd=portable,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        self.assertEqual(execution.returncode, 0, execution.stderr)
        result = json.loads(execution.stdout)
        self.assertEqual(
            result["numeric_digest"], mission["research"]["numeric_digest"]
        )
        self.assertTrue(result["offline"])

    def test_fresh_workspace_discovers_then_acquires_and_resumes_without_refetch(self):
        with patch("siqe_quest.mission.SourceHunter", return_value=self.hunter):
            first = run_mission(self.store)
        requests = len(self.transport.calls)
        with patch(
            "siqe_quest.sources._network_transport",
            side_effect=AssertionError("network on replay"),
        ):
            second = run_mission(self.store)
        self.assertEqual(first["status"], "COMPLETED")
        self.assertEqual(first["mission_id"], second["mission_id"])
        self.assertEqual(len(self.transport.calls), requests)
        discovery = self.store.records("discovery_result")
        self.assertEqual(len(discovery), 1)
        self.assertTrue(
            any(
                item["source_type"] == "api_catalog"
                for item in discovery[0]["value"]["sources"]
            )
        )

    def test_pause_blocks_delivery_and_explicit_resume_completes_same_event(self):
        self.acquire_fixture()
        queue = EventQueue(self.store)
        queue.control("PAUSE")
        paused = run_mission(self.store)
        self.assertEqual(paused["status"], "BLOCKED")
        self.assertEqual(paused["followup"]["delivery_status"], "PENDING")
        self.assertEqual(queue.state(), "PAUSED")
        self.assertEqual(len(self.store.records("runtime_review")), 0)
        queue.control("RESUME")
        resumed = run_mission(self.store)
        self.assertEqual(resumed["status"], "COMPLETED")
        self.assertEqual(
            paused["followup"]["event_id"], resumed["followup"]["event_id"]
        )
        self.assertEqual(len(self.store.records("learning_evaluation")), 1)
        self.assertEqual(len(self.store.records("mission")), 2)

    def test_interrupted_lifecycle_uses_checkpointed_learning_and_acquisition(self):
        with (
            patch("siqe_quest.mission.SourceHunter", return_value=self.hunter),
            patch(
                "siqe_quest.mission._reference_source",
                side_effect=OSError("fixture interruption"),
            ),
        ):
            with self.assertRaises(OSError):
                run_mission(self.store)
        self.assertEqual(len(self.store.records("dataset")), 1)
        self.assertEqual(len(self.store.records("learning_evaluation")), 0)
        with patch(
            "siqe_quest.sources._network_transport",
            side_effect=AssertionError("repeated acquisition"),
        ):
            resumed = run_mission(self.store)
        self.assertEqual(resumed["status"], "COMPLETED")
        self.assertEqual(len(self.store.records("learning_evaluation")), 1)

    def test_committed_evaluation_survives_interrupted_mission_checkpoint(self):
        self.acquire_fixture()
        record = self.store.record
        interrupted = False

        def interrupt(kind, key, value):
            nonlocal interrupted
            if (
                kind == "mission_stage"
                and key.endswith(":learning")
                and not interrupted
            ):
                interrupted = True
                raise OSError("fixture process loss after evaluation commit")
            return record(kind, key, value)

        with patch.object(self.store, "record", side_effect=interrupt):
            with self.assertRaises(OSError):
                run_mission(self.store)
        self.assertEqual(len(self.store.records("learning_evaluation")), 1)
        with patch(
            "siqe_quest.sources._network_transport",
            side_effect=AssertionError("network on resume"),
        ):
            resumed = run_mission(self.store)
        self.assertEqual(resumed["status"], "COMPLETED")
        self.assertEqual(len(self.store.records("learning_evaluation")), 1)

    def test_cli_has_explicit_finite_operations_and_sanitized_failures(self):
        code, text = self.call_cli()
        self.assertEqual(code, 0)
        self.assertIn("usage:", text)
        self.assertEqual(len(self.store.records("runtime_review")), 0)
        code, text = self.call_cli("reproduce")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(text)["status"], "ERROR")
        code, text = self.call_cli("control", "STOP")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text)["queue_state"], "STOPPED")
        code, text = self.call_cli("worker", "--max-cycles", "2")
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(text)["cycles"]), 1)
        code, text = self.call_cli("worker", "--max-cycles", "secret=DO-NOT-ECHO")
        self.assertEqual(code, 2)
        self.assertNotIn("DO-NOT-ECHO", text)


if __name__ == "__main__":
    unittest.main()

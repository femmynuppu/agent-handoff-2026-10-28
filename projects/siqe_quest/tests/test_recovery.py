"""Offline recovery preserves scientific identities without authorizing queue work."""

import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from siqe_quest.core import SafetyError, Store, canonical_json, digest
from siqe_quest.events import Event, EventQueue
from siqe_quest.recovery import recover_store


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "quest"
        self.store = Store(self.root)
        self.destination = "state/reconstructed.sqlite3"

    def envelope(self, kind, key, value, stamp="2026-10-26T12:00:00.000000+00:00"):
        body = {"kind": kind, "key": key, "value": value, "created_at": stamp}
        envelope = {"record_id": digest(body), **body}
        self.store.put_blob(canonical_json(envelope).encode(), "application/json")
        return envelope

    def records(self):
        conn = sqlite3.connect(self.root / self.destination)
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        return conn, conn.execute("SELECT * FROM records ORDER BY sequence").fetchall()

    def test_default_inventory_never_writes_and_new_database_keeps_full_history(self):
        first = self.store.record("experiment", "one", {"result": 1})
        second = self.store.record("mission", "QUEST-ALPHA-01", {"experiment": first})
        self.store.record("source_health", "v1", {"status": "previous"})
        self.store.record("source_health", "v2", {"status": "latest"})
        before = {
            p.relative_to(self.root): p.read_bytes()
            for p in self.root.rglob("*")
            if p.is_file()
        }
        preview = recover_store(self.root, self.destination, queue_export=None)
        after = {
            p.relative_to(self.root): p.read_bytes()
            for p in self.root.rglob("*")
            if p.is_file()
        }
        self.assertEqual(before, after)
        self.assertFalse(preview["written"])
        self.assertEqual(preview["manifest"]["counts"]["records_selected"], 4)
        result = recover_store(
            self.root, self.destination, write=True, queue_export=None
        )
        conn, rows = self.records()
        self.assertEqual(
            [r["record_id"] for r in rows[:2]],
            [first["record_id"], second["record_id"]],
        )
        self.assertEqual([r["sequence"] for r in rows], [1, 2, 3, 4])
        for row in rows:
            original = self.store.get(row["kind"], row["record_key"])
            self.assertEqual(
                row["content_json"],
                canonical_json({k: v for k, v in original.items() if k != "evidence"}),
            )
            self.assertEqual(row["evidence_json"], canonical_json(original["evidence"]))
        self.assertTrue(result["written"])
        ref = result["manifest_evidence"]
        self.assertEqual(
            hashlib.sha256((self.root / ref["path"]).read_bytes()).hexdigest(),
            ref["sha256"],
        )
        self.assertEqual(
            (self.root / (self.destination + ".manifest.json")).read_bytes(),
            (self.root / ref["path"]).read_bytes(),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM records")
        for path, raw in before.items():
            self.assertEqual((self.root / path).read_bytes(), raw)

    def test_corrupt_database_reconstructs_every_kind_from_canonical_envelopes(self):
        kinds = [
            "experiment",
            "mission",
            "runtime_review",
            "source_health",
            "unlisted_future_kind",
        ]
        envelopes = [
            self.envelope(kind, "history-v1", {"original": kind}) for kind in kinds
        ]
        corrupt = self.root / "state/corrupt.sqlite3"
        corrupt.write_bytes(b"not a SQLite database")
        result = recover_store(
            self.root,
            self.destination,
            write=True,
            source_database="state/corrupt.sqlite3",
            queue_export=None,
        )
        _, rows = self.records()
        self.assertEqual(
            {r["record_id"] for r in rows}, {e["record_id"] for e in envelopes}
        )
        self.assertEqual(corrupt.read_bytes(), b"not a SQLite database")
        self.assertTrue(
            any("incomplete" in reason for reason in result["manifest"]["missing_data"])
        )
        self.assertTrue(
            all(r["original_sequence"] is None for r in result["manifest"]["records"])
        )

    def test_conflicting_identity_quarantines_both_versions_without_selecting_latest(
        self,
    ):
        one = self.envelope("experiment", "same", {"result": 1})
        two = self.envelope(
            "experiment", "same", {"result": 2}, "2026-10-27T12:00:00+00:00"
        )
        good = self.envelope("experiment", "different", {"result": 3})
        result = recover_store(
            self.root,
            self.destination,
            write=True,
            source_database=None,
            queue_export=None,
        )
        _, rows = self.records()
        self.assertEqual([r["record_id"] for r in rows], [good["record_id"]])
        conflict = result["manifest"]["conflicts"][0]
        self.assertEqual(
            set(conflict["record_ids"]), {one["record_id"], two["record_id"]}
        )
        self.assertEqual(result["manifest"]["counts"]["conflicting_identities"], 1)

    def test_sha_mismatch_invalid_envelopes_and_raw_evidence_are_not_records(self):
        self.store.put_blob(b"ordinary raw text", "text/plain")
        self.store.put_blob(b'{"raw":true}', "application/json")
        body = {"kind": "experiment", "key": "bad", "value": {}, "created_at": "naive"}
        self.store.put_blob(
            canonical_json({"record_id": digest(body), **body}).encode()
        )
        body["created_at"] = "2026-10-27T12:00:00+00:00"
        self.store.put_blob(canonical_json({"record_id": "0" * 64, **body}).encode())
        self.store.put_blob(b'{"record_id":"bad", "record_id":"other"}')
        (self.root / "evidence/blobs" / ("f" * 64)).write_bytes(
            b"wrong filename digest"
        )
        result = recover_store(
            self.root, self.destination, source_database=None, queue_export=None
        )
        self.assertEqual(result["manifest"]["counts"]["records_selected"], 0)
        self.assertEqual(result["manifest"]["counts"]["raw_blobs_ignored"], 2)
        self.assertEqual(result["manifest"]["counts"]["invalid"], 4)

    def test_no_overwrite_traversal_symlink_or_evidence_destination(self):
        original = (self.root / "state/siqe.sqlite3").read_bytes()
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (self.root / "escape").symlink_to(outside, target_is_directory=True)
        for destination in (
            "state/siqe.sqlite3",
            "../outside/new.sqlite3",
            str(outside / "new.sqlite3"),
            "escape/new.sqlite3",
            "evidence/new.sqlite3",
        ):
            with self.subTest(destination=destination), self.assertRaises(SafetyError):
                recover_store(self.root, destination, write=True)
        (self.root / "state/reconstructed.sqlite3-wal").write_bytes(b"retained WAL")
        with self.assertRaises(SafetyError):
            recover_store(self.root, self.destination, write=True)
        self.assertEqual((self.root / "state/siqe.sqlite3").read_bytes(), original)
        self.assertEqual(list(outside.iterdir()), [])

    def test_nonempty_wal_is_explicitly_not_a_complete_readonly_snapshot(self):
        (self.root / "state/siqe.sqlite3-wal").write_bytes(b"uncheckpointed")
        result = recover_store(self.root, self.destination, queue_export=None)
        self.assertTrue(
            any("nonempty -wal" in x for x in result["manifest"]["missing_data"])
        )

    def test_exact_sql_copy_deduplicates_and_can_supply_missing_record_blob(self):
        record = self.store.record("experiment", "retained-db-copy", {"value": 7})
        (self.root / record["evidence"]["path"]).unlink()
        result = recover_store(
            self.root, self.destination, write=True, queue_export=None
        )
        _, rows = self.records()
        self.assertEqual([r["record_id"] for r in rows], [record["record_id"]])
        self.assertEqual(
            self.store.read_blob(record["evidence"]), rows[0]["content_json"].encode()
        )
        self.assertEqual(result["manifest"]["counts"]["records_selected"], 1)
        with self.assertRaises(SafetyError):
            recover_store(self.root, self.destination, write=True)

    def test_queue_audit_and_export_preserved_but_nothing_is_executable(self):
        queue = EventQueue(self.store)
        event_id = queue.emit(
            Event("NEW_SOURCE_DISCOVERED", "recover-event", {"source": "x"}, "fixture")
        )
        export = {"events": queue.events(), "stats": queue.stats()}
        export_raw = canonical_json(export).encode()
        (self.root / "queue-export.json").write_bytes(export_raw)
        conn = self.store.connection()
        try:
            original_audit = [
                tuple(row)
                for row in conn.execute("SELECT * FROM hook_audit ORDER BY sequence")
            ]
        finally:
            conn.close()
        result = recover_store(
            self.root, self.destination, write=True, queue_export="queue-export.json"
        )
        conn, _ = self.records()
        self.assertEqual(
            conn.execute("SELECT state FROM hook_control").fetchone()[0], "STOPPED"
        )
        self.assertEqual(
            conn.execute(
                "SELECT status FROM hook_events WHERE event_id=?", (event_id,)
            ).fetchone()[0],
            "QUARANTINED",
        )
        self.assertEqual(
            conn.execute(
                "SELECT count(*) FROM hook_tasks WHERE status!='QUARANTINED'"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            [
                tuple(row)
                for row in conn.execute(
                    "SELECT * FROM hook_audit WHERE action!='OFFLINE_RECOVERY_STOPPED' ORDER BY sequence"
                )
            ],
            original_audit,
        )
        self.assertEqual(
            conn.execute("SELECT count(*) FROM recovery_queue_quarantine").fetchone()[
                0
            ],
            1,
        )
        self.assertEqual(
            conn.execute(
                "SELECT count(*) FROM hook_idempotency WHERE event_id=?", (event_id,)
            ).fetchone()[0],
            1,
        )
        ref = result["manifest"]["preserved_operational_evidence"][
            "queue_export_original"
        ]
        self.assertEqual((self.root / ref["path"]).read_bytes(), export_raw)
        self.assertFalse(result["manifest"]["queue_policy"]["automatic_replay"])

    def test_export_only_event_does_not_fabricate_queue_hash_or_emit_duplicate(self):
        self.envelope(
            "runtime_review", "review-3", {"event_id": "newer-event", "complete": True}
        )
        export = {
            "events": [{"event_id": "old-completed", "status": "COMPLETED"}],
            "stats": {},
        }
        (self.root / "queue-export.json").write_text(canonical_json(export))
        result = recover_store(
            self.root,
            self.destination,
            write=True,
            source_database=None,
            queue_export="queue-export.json",
        )
        conn, rows = self.records()
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            conn.execute("SELECT count(*) FROM hook_events").fetchone()[0], 0
        )
        self.assertEqual(
            conn.execute("SELECT count(*) FROM hook_idempotency").fetchone()[0], 0
        )
        self.assertEqual(
            conn.execute(
                "SELECT event_id,status FROM recovery_queue_quarantine"
            ).fetchone()[:],
            ("old-completed", "QUARANTINED"),
        )
        self.assertEqual(result["manifest"]["counts"]["export_events_evidence_only"], 1)
        self.assertFalse(
            result["manifest"]["queue_policy"]["export_is_exact_queue_backup"]
        )
        inventory = {
            row["event_id"]: row
            for row in result["manifest"]["operational_event_inventory"]
        }
        self.assertEqual(set(inventory), {"newer-event", "old-completed"})
        self.assertFalse(inventory["newer-event"]["valid_queue_row"])
        self.assertEqual(len(inventory["newer-event"]["scientific_record_ids"]), 1)
        self.assertFalse(inventory["newer-event"]["export_evidence"])

    def test_missing_input_evidence_is_reported_without_discarding_original_record(
        self,
    ):
        missing_sha = "a" * 64
        envelope = self.envelope(
            "experiment",
            "missing-input",
            {
                "input": {
                    "sha256": missing_sha,
                    "path": "evidence/blobs/" + missing_sha,
                    "bytes": 100,
                    "media_type": "application/json",
                }
            },
        )
        result = recover_store(
            self.root, self.destination, source_database=None, queue_export=None
        )
        self.assertEqual(result["manifest"]["counts"]["records_selected"], 1)
        self.assertEqual(
            result["manifest"]["evidence_gaps"],
            [{"record_id": envelope["record_id"], "missing_sha256": missing_sha}],
        )

    def test_truthy_nonboolean_flag_does_not_authorize_writes(self):
        with self.assertRaises(SafetyError):
            recover_store(self.root, self.destination, write="yes")
        self.assertFalse((self.root / self.destination).exists())


if __name__ == "__main__":
    unittest.main()

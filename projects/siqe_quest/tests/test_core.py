"""Deterministic core persistence, concurrency and trust-boundary tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from siqe_quest.core import (
    DEFAULT_CONFIG,
    SafetyError,
    Store,
    canonical_json,
    digest,
    utcnow,
)
from siqe_quest.events import Event, EventQueue


def _database_consumer(root, index, start):
    """Spawned processes use real SQLite transactions and queue leases."""
    if not start.wait(30):
        raise RuntimeError("concurrency test start timed out")
    store = Store(root)
    queue = EventQueue(store)
    for ordinal in range(8):
        key = f"{index}:{ordinal}"
        record = store.record("process-durable", key, {"writer": index, "n": ordinal})
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO process_transactions VALUES (?, ?)", (key, "commit")
            )
        try:
            with store.connection() as conn:
                conn.execute(
                    "INSERT INTO process_transactions VALUES (?, ?)",
                    (key + ":rollback", "no"),
                )
                raise RuntimeError("intentional transaction rollback")
        except RuntimeError:
            pass
        event = queue.claim(f"consumer-{index}", lease_seconds=60)
        if event is not None:
            queue.complete(
                event["event_id"],
                f"consumer-{index}",
                {"record_id": record["record_id"]},
            )
        # Reopen while other processes continue writing, rather than trusting
        # data still visible only to the connection that committed it.
        if Store(root).get("process-durable", key) != record:
            raise AssertionError("committed record changed after reopen")


def _database_reporter(root, start):
    if not start.wait(30):
        raise RuntimeError("concurrency test start timed out")
    for _ in range(24):
        store = Store(root)
        store.records("process-durable")
        EventQueue(store).stats()
        with store.connection() as conn:
            if [row[0] for row in conn.execute("PRAGMA integrity_check")] != ["ok"]:
                raise AssertionError("integrity failed during concurrent reporting")


def _database_exclusive_lock_available(database, result):
    """An independent OS process probes SQLite's main-file shared lock."""
    import fcntl

    with open(database, "r+b") as stream:
        try:
            fcntl.lockf(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            result.send(False)
        else:
            result.send(True)
    result.close()


def _stop_database_process(process):
    if process.is_alive():
        process.terminate()
        process.join(10)


class CanonicalJSONTests(unittest.TestCase):
    def test_utf8_order_and_digest(self):
        value = {"z": [True, None, 1.5], "a": "é"}
        expected = '{"a":"é","z":[true,null,1.5]}'
        self.assertEqual(canonical_json(value), expected)
        self.assertEqual(digest(value), hashlib.sha256(expected.encode()).hexdigest())
        self.assertEqual(digest(value), digest({"a": "é", "z": [True, None, 1.5]}))
        self.assertIsNotNone(datetime.fromisoformat(utcnow()).utcoffset())

    def test_nonfinite_and_lossy_types_rejected(self):
        for value in [
            float("nan"),
            float("inf"),
            -float("inf"),
            {1: "not a JSON string key"},
            {"x": (1, 2)},
            b"bytes",
            {"bad": "\ud800"},
            {"nested": [float("nan")]},
        ]:
            with self.subTest(value=repr(value)), self.assertRaises(SafetyError):
                canonical_json(value)
        cycle = []
        cycle.append(cycle)
        with self.assertRaises(SafetyError):
            canonical_json(cycle)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "quest"
        self.store = Store(self.root)

    def test_new_connections_are_transactional_wal_and_foreign_key_checked(self):
        first = self.store.connection()
        second = self.store.connection()
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        self.assertIsNot(first, second)
        self.assertIs(first.row_factory, sqlite3.Row)
        self.assertEqual(first.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(first.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertGreaterEqual(
            first.execute("PRAGMA busy_timeout").fetchone()[0], 1000
        )
        with first:
            first.execute("CREATE TABLE scratch (value INTEGER)")
        with self.assertRaises(sqlite3.ProgrammingError):
            first.execute("SELECT 1")
        with self.assertRaises(RuntimeError):
            with self.store.connection() as rolled_back:
                rolled_back.execute("INSERT INTO scratch VALUES (1)")
                raise RuntimeError("rollback")
        with self.assertRaises(sqlite3.ProgrammingError):
            rolled_back.execute("SELECT 1")
        self.assertEqual(
            second.execute("SELECT count(*) FROM scratch").fetchone()[0], 0
        )

    @unittest.skipUnless(os.name == "posix", "POSIX advisory-lock regression")
    def test_store_reopen_does_not_release_retained_sqlite_locks(self):
        context = multiprocessing.get_context("spawn")
        with self.store.connection() as reader:
            reader.execute("BEGIN")
            reader.execute("SELECT * FROM records").fetchall()
            Store(self.root)
            receive, send = context.Pipe(duplex=False)
            self.addCleanup(receive.close)
            self.addCleanup(send.close)
            child = context.Process(
                target=_database_exclusive_lock_available,
                args=(self.root / "state/siqe.sqlite3", send),
            )
            child.start()
            self.addCleanup(_stop_database_process, child)
            send.close()
            self.assertTrue(receive.poll(30), "lock probe did not return")
            self.assertFalse(
                receive.recv(), "Store reopening released SQLite's OS lock"
            )
            child.join(30)
            self.assertEqual(child.exitcode, 0)

    def test_multiprocess_consumers_reporter_rollback_and_reopen_are_durable(self):
        queue = EventQueue(self.store)
        for index in range(24):
            queue.emit(
                Event(
                    event_type="EXPERIMENT_COMPLETED",
                    idempotency_key=f"process:{index}",
                    payload_reference={"record_id": "local-research"},
                    provenance_reference={"record_id": "local-evidence"},
                )
            )
        with self.store.connection() as conn:
            conn.execute(
                "CREATE TABLE process_transactions (key TEXT PRIMARY KEY, value TEXT)"
            )
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        children = [
            context.Process(target=_database_consumer, args=(self.root, index, start))
            for index in range(3)
        ]
        children.append(
            context.Process(target=_database_reporter, args=(self.root, start))
        )
        # Keep an independently owned connection in the parent during actual
        # child writes; a reporter must not invalidate its inode locks.
        with self.store.connection() as retained:
            retained.execute("SELECT count(*) FROM records").fetchone()
            for child in children:
                child.start()
                self.addCleanup(_stop_database_process, child)
            start.set()
            for child in children:
                child.join(90)
                self.assertEqual(
                    child.exitcode, 0, "database child failed or timed out"
                )
        reopened = Store(self.root)
        self.assertEqual(len(reopened.records("process-durable")), 24)
        events = EventQueue(reopened).events()
        self.assertEqual(len(events), 24)
        self.assertTrue(all(event["status"] == "COMPLETED" for event in events))
        self.assertTrue(all(event["attempt_count"] == 1 for event in events))
        with reopened.connection() as conn:
            self.assertEqual(
                conn.execute("SELECT count(*) FROM process_transactions").fetchone()[0],
                24,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM process_transactions WHERE key LIKE '%:rollback'"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                [row[0] for row in conn.execute("PRAGMA integrity_check")], ["ok"]
            )

    def test_malformed_database_fails_before_schema_initialization(self):
        for malformed in (False, True):
            with self.subTest(malformed_header=malformed):
                root = Path(self.temporary.name) / f"malformed-{malformed}"
                (root / "state").mkdir(parents=True)
                database = root / "state/siqe.sqlite3"
                if malformed:
                    database.write_bytes(b"not a SQLite database; preserve me")
                else:
                    conn = sqlite3.connect(database)
                    try:
                        conn.execute(
                            "CREATE TABLE broken (value INTEGER CHECK(value > 0))"
                        )
                        conn.execute("PRAGMA ignore_check_constraints=ON")
                        conn.execute("INSERT INTO broken VALUES (-1)")
                        conn.commit()
                    finally:
                        conn.close()
                original = database.read_bytes()
                with self.assertRaises((SafetyError, sqlite3.DatabaseError)):
                    Store(root)
                self.assertEqual(database.read_bytes(), original)
                if not malformed:
                    conn = sqlite3.connect(database)
                    try:
                        self.assertEqual(
                            conn.execute("PRAGMA journal_mode").fetchone()[0], "delete"
                        )
                        self.assertIsNone(
                            conn.execute(
                                "SELECT name FROM sqlite_master WHERE name='records'"
                            ).fetchone()
                        )
                    finally:
                        conn.close()

    def test_content_addressing_reopen_and_record_idempotency(self):
        blob = self.store.put_blob(b"real research evidence", "text/plain")
        self.assertEqual(
            blob, self.store.put_blob(b"real research evidence", "text/plain")
        )
        self.assertEqual(self.store.read_blob(blob), b"real research evidence")
        self.assertEqual(
            self.store.read_blob(blob["sha256"]), b"real research evidence"
        )
        self.assertEqual(self.store.read_blob(blob["path"]), b"real research evidence")
        first = self.store.record("experiment", "v1", {"input": blob, "result": 1.25})
        second = self.store.record("experiment", "v1", {"result": 1.25, "input": blob})
        self.assertEqual(first, second)
        self.assertEqual(
            json.loads(self.store.read_blob(first["evidence"])),
            {key: value for key, value in first.items() if key != "evidence"},
        )
        reopened = Store(self.root)
        self.assertEqual(reopened.get("experiment", "v1"), first)
        self.assertEqual(reopened.records("experiment"), [first])
        self.assertIsNone(reopened.get("experiment", "missing"))
        with self.assertRaises(SafetyError):
            reopened.record("experiment", "v1", {"result": 2})
        third = reopened.record("experiment", "v2", {"result": 2})
        self.assertEqual(reopened.records("experiment"), [first, third])

    def test_caller_cannot_mutate_stored_values(self):
        mutable = {"nested": [{"x": 1}]}
        record = self.store.record("test", "version", mutable)
        mutable["nested"][0]["x"] = 2
        record["value"]["nested"][0]["x"] = 3
        self.assertEqual(
            self.store.get("test", "version")["value"], {"nested": [{"x": 1}]}
        )

    def test_paths_reject_traversal_absolute_and_symlink_escape(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (self.root / "escape").symlink_to(outside, target_is_directory=True)
        (self.root / "cycle").symlink_to(self.root / "cycle")
        for relative in [
            "../outside",
            "/etc/passwd",
            str(outside),
            "escape/file",
            "a/../../outside",
            "cycle/file",
            "",
            "\x00",
        ]:
            with self.subTest(relative=relative), self.assertRaises(SafetyError):
                self.store.path(relative)
        self.assertEqual(
            self.store.path("reports/nested.json"), self.root / "reports/nested.json"
        )
        (self.root / "inside").symlink_to(
            self.root / "evidence", target_is_directory=True
        )
        self.assertEqual(self.store.path("inside/blobs"), self.root / "evidence/blobs")

    def test_managed_symlinks_cannot_redirect_blobs_or_database(self):
        blob = self.store.put_blob(b"payload")
        file = self.store.path(blob["path"])
        backup = self.root / "same-content"
        backup.write_bytes(b"payload")
        file.unlink()
        file.symlink_to(backup)
        with self.assertRaises(SafetyError):
            self.store.read_blob(blob)
        with self.assertRaises(SafetyError):
            self.store.put_blob(b"payload")
        (self.root / "state/siqe.sqlite3-wal").unlink(missing_ok=True)
        (self.root / "state/siqe.sqlite3-wal").symlink_to(backup)
        with self.assertRaises(SafetyError):
            self.store.connection()

    def test_special_file_evidence_is_rejected_without_blocking(self):
        name = "0" * 64
        os.mkfifo(self.root / "evidence/blobs" / name)
        with self.assertRaises(SafetyError):
            self.store.read_blob(name)

    def test_database_symlink_within_workspace_is_rejected_on_reopen(self):
        database = self.root / "state/siqe.sqlite3"
        alternative = self.root / "alternate.sqlite3"
        database.rename(alternative)
        database.symlink_to(alternative)
        with self.assertRaises(SafetyError):
            Store(self.root)

    def test_blob_corruption_descriptor_forgery_and_missing_evidence(self):
        blob = self.store.put_blob(b"original")
        file = self.store.path(blob["path"])
        file.chmod(0o600)
        file.write_bytes(b"tampered")
        with self.assertRaises(SafetyError):
            self.store.read_blob(blob)
        with self.assertRaises(SafetyError):
            self.store.put_blob(b"original")
        valid = self.store.put_blob(b"valid")
        for bad in [
            {**valid, "bytes": 99},
            {**valid, "bytes": True},
            {**valid, "path": "../../etc/passwd"},
            {**valid, "sha256": "0" * 64},
            "../" + valid["path"],
            "/" + valid["path"],
            "0" * 64,
        ]:
            with self.subTest(reference=bad), self.assertRaises(SafetyError):
                self.store.read_blob(bad)

    def test_append_only_database_and_record_metadata_corruption_detection(self):
        record = self.store.record("experiment", "immutable", {"result": 1})
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.connection() as conn:
                conn.execute("UPDATE records SET created_at='changed'")
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.connection() as conn:
                conn.execute("DELETE FROM records")
        # Simulate an out-of-band corruptor with database-owner privileges.
        with self.store.connection() as conn:
            conn.execute("DROP TRIGGER records_no_update")
            conn.execute("UPDATE records SET created_at='changed'")
        with self.assertRaises(SafetyError):
            self.store.get("experiment", "immutable")
        self.assertTrue(record["record_id"])

    def test_record_read_detects_tampered_evidence(self):
        record = self.store.record("experiment", "v1", {"result": 1})
        file = self.store.path(record["evidence"]["path"])
        file.chmod(0o600)
        file.write_bytes(b"{}")
        with self.assertRaises(SafetyError):
            self.store.get("experiment", "v1")
        with self.assertRaises(SafetyError):
            self.store.records("experiment")
        with self.assertRaises(SafetyError):
            self.store.record("experiment", "v1", {"result": 1})

    def test_concurrent_records_and_same_identity_are_atomic(self):
        def write(index):
            own = Store(self.root)
            unique = own.record("parallel", str(index), {"index": index})
            shared = own.record("parallel-shared", "single", {"same": True})
            blob = own.put_blob(b"concurrent identical bytes")
            return unique, shared, blob

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(write, range(12)))
        self.assertEqual(len(self.store.records("parallel")), 12)
        self.assertEqual(len({item[1]["record_id"] for item in results}), 1)
        self.assertEqual(len({item[2]["sha256"] for item in results}), 1)
        self.assertEqual(len(self.store.records("parallel-shared")), 1)

        def conflict(index):
            try:
                self.store.record("race", "single", {"index": index})
                return "written"
            except SafetyError:
                return "conflict"

        with ThreadPoolExecutor(max_workers=6) as pool:
            statuses = list(pool.map(conflict, range(6)))
        self.assertEqual(statuses.count("written"), 1)
        self.assertEqual(statuses.count("conflict"), 5)

    def test_audit_redaction_in_database_and_evidence(self):
        details = {
            "api_key": "alpha-secret",
            "nested": [{"password": "beta-secret"}],
            "headers": {
                "Authorization": "Bearer gamma-secret",
                "Cookie": "delta-secret",
            },
            "url": "https://user:epsilon-secret@example.org/path?token=zeta-secret",
            "error": "password=eta-secret token:theta-secret Bearer iota-secret",
            "safe": "a scientific observation",
            "count": 3,
        }
        record = self.store.audit("research.source", details)
        encoded = canonical_json(record)
        raw = self.store.read_blob(record["evidence"]).decode()
        conn = self.store.connection()
        try:
            persisted = conn.execute("SELECT content_json FROM records").fetchone()[0]
        finally:
            conn.close()
        for secret in [
            "alpha-secret",
            "beta-secret",
            "gamma-secret",
            "delta-secret",
            "epsilon-secret",
            "zeta-secret",
            "eta-secret",
            "theta-secret",
            "iota-secret",
        ]:
            for output in (encoded, raw, persisted):
                self.assertNotIn(secret, output)
        self.assertEqual(record["value"]["details"]["safe"], "a scientific observation")
        self.assertEqual(details["api_key"], "alpha-secret")
        self.assertEqual(self.store.records("audit"), [record])

    def test_direct_audit_record_cannot_bypass_redaction(self):
        record = self.store.record("audit", "direct", {"token": "hidden-value"})
        self.assertEqual(record["value"]["token"], "[REDACTED]")
        self.assertNotIn(
            "hidden-value", self.store.read_blob(record["evidence"]).decode()
        )

    def test_default_deny_cannot_be_overridden_by_mutable_configuration(self):
        for action in [
            "research",
            "read",
            "simulate",
            "knowledge",
            "report",
            "research.sources",
            "knowledge:index",
            "report.export",
        ]:
            self.assertIsNone(self.store.authorize(action))
        self.store.config["live_trading"] = True
        self.store.config["permissions"] = ["*"]
        denied = [
            "trade",
            "withdraw",
            "account",
            "publication",
            "external_exec",
            "research.trade",
            "research:external_exec",
            "report.publish",
            "read.credentials",
            "simulate.live",
            "research;touch /tmp/pwned",
            "RESEARCH",
            "",
            None,
            "trade?token=private-secret",
        ]
        for action in denied:
            with self.subTest(action=action), self.assertRaises(SafetyError):
                self.store.authorize(action)
        self.assertEqual(len(self.store.records("audit")), len(denied))
        self.assertNotIn("private-secret", canonical_json(self.store.records("audit")))

    def test_invalid_record_and_blob_types_are_rejected(self):
        for kind, key, value in [
            ("", "key", {}),
            ("kind", "", {}),
            ("a\n", "key", {}),
            ("kind", "key", []),
            ("kind", "key", {"n": float("inf")}),
        ]:
            with self.subTest(kind=kind, key=key), self.assertRaises(SafetyError):
                self.store.record(kind, key, value)
        for content in ["text", bytearray(b"mutable")]:
            with self.assertRaises(SafetyError):
                self.store.put_blob(content)
        with self.assertRaises(SafetyError):
            self.store.put_blob(b"test", "text/plain\r\nInjected: yes")


class ConfigurationTests(unittest.TestCase):
    def _store_with(self, raw):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "config").mkdir()
        (root / "config/research.json").write_text(raw, encoding="utf-8")
        return Store(root)

    def test_defaults_are_finite_locked_and_independently_owned(self):
        first = self._store_with("{}")
        second = self._store_with("{}")
        self.assertEqual(first.config, DEFAULT_CONFIG)
        first.config["dataset"]["series"] = "changed"
        self.assertEqual(second.config["dataset"]["series"], "FXUSDCAD")
        self.assertFalse(second.config["live_trading"])
        self.assertFalse(second.config["fine_tuning"])
        self.assertFalse(second.config["public_http_listener"])
        self.assertEqual(second.config["dataset"]["start_date"], "2023-01-01")
        self.assertEqual(second.config["dataset"]["end_date"], "2025-12-31")

    def test_security_flags_and_source_permissions_cannot_expand(self):
        cases = [
            {"live_trading": True},
            {"fine_tuning": True},
            {"public_http_listener": True},
            {"live_trading": 0},
            {"fine_tuning": "false"},
            {"workspace_id": "OTHER"},
            {"bind_host": "0.0.0.0"},
            {"allowed_domains": ["evil.example"]},
            {"allowed_domains": []},
            {"allowed_domains": ["www.bankofcanada.ca.evil"]},
            {"dataset": {"series": "OTHER"}},
            {"permissions": ["*"]},
        ]
        for config in cases:
            with self.subTest(config=config), self.assertRaises(SafetyError):
                self._store_with(json.dumps(config))
        restricted = self._store_with('{"allowed_domains":["www.bankofcanada.ca"]}')
        self.assertEqual(restricted.config["allowed_domains"], ["www.bankofcanada.ca"])

    def test_zero_negative_excessive_boolean_and_nonfinite_budgets_rejected(self):
        for key in [
            "max_queue",
            "max_depth",
            "task_budget",
            "max_attempts",
            "memory_mb",
            "cpu_seconds",
            "max_tasks_per_cycle",
            "max_network_requests_per_cycle",
            "review_interval_seconds",
            "max_log_bytes",
            "network_timeout_seconds",
            "max_response_bytes",
            "idle_seconds",
        ]:
            for value in [0, -1, True, 1e99, 1.5]:
                with self.subTest(key=key, value=value), self.assertRaises(SafetyError):
                    self._store_with(json.dumps({key: value}))
        for raw in [
            '{"task_budget":NaN}',
            '{"max_queue":1,"max_queue":2}',
            "[]",
            "{broken",
        ]:
            with self.subTest(raw=raw), self.assertRaises(SafetyError):
                self._store_with(raw)

    def test_symlinked_configuration_is_rejected(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "root"
        (root / "config").mkdir(parents=True)
        outside = Path(temporary.name) / "untrusted.json"
        outside.write_text("{}", encoding="utf-8")
        (root / "config/research.json").symlink_to(outside)
        with self.assertRaises(SafetyError):
            Store(root)


if __name__ == "__main__":
    unittest.main()

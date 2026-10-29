"""Explicit offline reconstruction; never repairs or replaces the damaged database."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import stat
import uuid

from .core import SafetyError, Store, _parse_json, canonical_json, digest, utcnow

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ENVELOPE = {"record_id", "kind", "key", "created_at", "value"}
_TABLES = (
    "records",
    "hook_control",
    "hook_events",
    "hook_idempotency",
    "hook_tasks",
    "hook_audit",
    "runtime_schedule",
    "runtime_checkpoints",
    "runtime_source_checks",
    "webhook_nonces",
    "webhook_intake",
)
_SCHEMA = """
CREATE TABLE records (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, record_id TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL, record_key TEXT NOT NULL, created_at TEXT NOT NULL,
 content_json TEXT NOT NULL, evidence_json TEXT NOT NULL, UNIQUE(kind,record_key));
CREATE TRIGGER records_no_update BEFORE UPDATE ON records BEGIN
 SELECT RAISE(ABORT,'immutable record'); END;
CREATE TRIGGER records_no_delete BEFORE DELETE ON records BEGIN
 SELECT RAISE(ABORT,'immutable record'); END;
CREATE TABLE hook_control (singleton INTEGER PRIMARY KEY CHECK(singleton=1), state TEXT NOT NULL);
INSERT INTO hook_control VALUES(1,'STOPPED');
CREATE TABLE hook_events (
 event_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
 request_hash TEXT NOT NULL, body TEXT NOT NULL, periodic_key TEXT UNIQUE,
 periodic_hash TEXT, status TEXT NOT NULL, priority INTEGER NOT NULL,
 attempt_count INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL,
 lease_owner TEXT, lease_until REAL, remaining_budget INTEGER NOT NULL,
 result TEXT, last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE hook_idempotency (
 idempotency_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
 event_id TEXT NOT NULL REFERENCES hook_events(event_id));
CREATE INDEX hook_ready ON hook_events(status,next_attempt_at,priority);
CREATE TABLE hook_tasks (
 quest_id TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE REFERENCES hook_events(event_id),
 plan TEXT NOT NULL, status TEXT NOT NULL, owner TEXT, result TEXT, updated_at TEXT NOT NULL);
CREATE TABLE hook_audit (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, recorded_at TEXT NOT NULL,
 action TEXT NOT NULL, event_id TEXT, details TEXT NOT NULL);
CREATE TRIGGER hook_audit_no_update BEFORE UPDATE ON hook_audit BEGIN
 SELECT RAISE(ABORT,'hook audit is immutable'); END;
CREATE TRIGGER hook_audit_no_delete BEFORE DELETE ON hook_audit BEGIN
 SELECT RAISE(ABORT,'hook audit is immutable'); END;
CREATE TABLE recovery_queue_quarantine (
 source TEXT NOT NULL, ordinal INTEGER NOT NULL, event_id TEXT,
 status TEXT NOT NULL CHECK(status='QUARANTINED'), original_json TEXT NOT NULL,
 PRIMARY KEY(source,ordinal));
CREATE TABLE recovery_evidence (
 label TEXT PRIMARY KEY, evidence_json TEXT NOT NULL);
CREATE TRIGGER recovery_evidence_no_update BEFORE UPDATE ON recovery_evidence BEGIN
 SELECT RAISE(ABORT,'recovery evidence is immutable'); END;
CREATE TRIGGER recovery_evidence_no_delete BEFORE DELETE ON recovery_evidence BEGIN
 SELECT RAISE(ABORT,'recovery evidence is immutable'); END;
"""


def _path(root: Path, relative: str, *, exists: bool = False) -> Path:
    if type(relative) is not str or not relative or "\x00" in relative:
        raise SafetyError("Expected a nonempty workspace-relative path")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise SafetyError("Recovery paths must be confined relative paths")
    current = root
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise SafetyError("Recovery paths cannot contain symlinks")
    try:
        current.resolve().relative_to(root)
    except (ValueError, OSError, RuntimeError) as exc:
        raise SafetyError("Recovery path escapes workspace") from exc
    if exists and not current.exists():
        raise SafetyError("Recovery input does not exist")
    return current


def _read(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise SafetyError("Recovery inputs must be regular files")
        return stream.read()


def _reference(raw: bytes, media_type: str = "application/json") -> dict:
    sha = hashlib.sha256(raw).hexdigest()
    return {
        "sha256": sha,
        "path": f"evidence/blobs/{sha}",
        "bytes": len(raw),
        "media_type": media_type,
    }


def _envelope(raw: bytes) -> dict | None:
    try:
        value = _parse_json(raw.decode("utf-8"))
    except (SafetyError, UnicodeError):
        # Most evidence is raw text/binary/JSON, not a record envelope.
        # A malformed JSON object advertising record_id is not silently ignored.
        if b'"record_id"' in raw and raw.lstrip().startswith(b"{"):
            raise SafetyError("Malformed advertised record envelope")
        return None
    if type(value) is not dict or "record_id" not in value:
        return None
    if set(value) != _ENVELOPE or type(value["value"]) is not dict:
        raise SafetyError("Invalid record envelope fields")
    Store._identity(value["kind"], value["key"])
    stamp = value["created_at"]
    try:
        if type(stamp) is not str or datetime.fromisoformat(stamp).utcoffset() is None:
            raise ValueError("not aware")
    except (ValueError, TypeError, OverflowError) as exc:
        raise SafetyError("Invalid original record timestamp") from exc
    if type(value["record_id"]) is not str or not _HASH.fullmatch(value["record_id"]):
        raise SafetyError("Invalid record identifier")
    if (
        digest({k: v for k, v in value.items() if k != "record_id"})
        != value["record_id"]
    ):
        raise SafetyError("Record identifier does not match core digest")
    if canonical_json(value).encode("utf-8") != raw:
        raise SafetyError("Envelope is not byte-exact core canonical JSON")
    return value


def _snapshot(root: Path, relative: str | None, missing: list) -> dict:
    if relative is None:
        missing.append(
            "No source database supplied; original sequence and queue audit unknown"
        )
        return {}
    path = _path(root, relative)
    if not path.exists():
        missing.append(f"Source database missing: {relative}")
        return {}
    # immutable=1 avoids SHM creation and all SQLite writes. It ignores WAL, so
    # never pretend the main file is a complete snapshot when WAL is nonempty.
    for suffix in ("-wal", "-journal"):
        sidecar = _path(root, relative + suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            missing.append(
                f"Source database not read: nonempty {suffix}; preserve/checkpoint offline first"
            )
            return {}
    if not stat.S_ISREG(path.stat().st_mode):
        raise SafetyError("Source database must be a regular file")
    tables = {}
    conn = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        for table in _TABLES:
            rows = []
            try:
                for row in conn.execute(f'SELECT * FROM "{table}"'):
                    item = dict(row)
                    canonical_json(item)
                    rows.append(item)
                tables[table] = {"rows": rows, "complete": True}
            except (sqlite3.Error, SafetyError) as exc:
                tables[table] = {"rows": rows, "complete": False, "error": str(exc)}
                missing.append(f"Source table {table} incomplete: {exc}")
    finally:
        conn.close()
    return tables


def _publish(root: Path, raw: bytes) -> dict:
    reference = _reference(raw)
    target = _path(root, reference["path"])
    if target.exists():
        if _read(target) != raw:
            raise SafetyError("Existing immutable recovery evidence conflicts")
        return reference
    directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = ".pending-recovery-" + uuid.uuid4().hex
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o444)
        try:
            os.link(
                temporary,
                target.name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
            os.fsync(directory)
        except FileExistsError:
            if _read(target) != raw:
                raise SafetyError("Existing immutable recovery evidence conflicts")
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)
    return reference


def _queue_rows(snapshot: dict, missing: list) -> tuple[list, list, list, list]:
    """Admit only full rows; uncertain rows remain in immutable snapshot evidence."""
    events, aliases, tasks, audit = [], [], [], []
    event_ids, keys, periodic = set(), set(), set()
    event_fields = {
        "event_id",
        "idempotency_key",
        "request_hash",
        "body",
        "periodic_key",
        "periodic_hash",
        "status",
        "priority",
        "attempt_count",
        "next_attempt_at",
        "lease_owner",
        "lease_until",
        "remaining_budget",
        "result",
        "last_error",
        "created_at",
        "updated_at",
    }
    for row in snapshot.get("hook_events", {}).get("rows", []):
        try:
            if set(row) != event_fields:
                raise SafetyError("Unexpected queue schema")
            body = _parse_json(row["body"])
            if (
                type(body) is not dict
                or body.get("event_id") != row["event_id"]
                or body.get("idempotency_key") != row["idempotency_key"]
                or not all(
                    type(row[k]) is str and row[k]
                    for k in (
                        "event_id",
                        "idempotency_key",
                        "status",
                        "created_at",
                        "updated_at",
                    )
                )
                or type(row["request_hash"]) is not str
                or not _HASH.fullmatch(row["request_hash"])
                or any(
                    type(row[k]) is not int
                    for k in ("priority", "attempt_count", "remaining_budget")
                )
                or type(row["next_attempt_at"]) not in (int, float)
            ):
                raise SafetyError("Invalid queue metadata")
            if row["result"] is not None:
                _parse_json(row["result"])
            if (
                row["event_id"] in event_ids
                or row["idempotency_key"] in keys
                or row["periodic_key"] is not None
                and row["periodic_key"] in periodic
            ):
                raise SafetyError("Conflicting queue identity")
            event_ids.add(row["event_id"])
            keys.add(row["idempotency_key"])
            if row["periodic_key"] is not None:
                periodic.add(row["periodic_key"])
            events.append(row)
        except (SafetyError, KeyError, TypeError) as exc:
            missing.append(f"Queue row quarantined as evidence only: {exc}")
    alias_keys = set()
    for row in snapshot.get("hook_idempotency", {}).get("rows", []):
        if (
            set(row) == {"idempotency_key", "request_hash", "event_id"}
            and row["event_id"] in event_ids
            and type(row["idempotency_key"]) is str
            and row["idempotency_key"]
            and row["idempotency_key"] not in alias_keys
            and type(row["request_hash"]) is str
            and _HASH.fullmatch(row["request_hash"])
        ):
            aliases.append(row)
            alias_keys.add(row["idempotency_key"])
        else:
            missing.append(
                "Invalid/orphan queue idempotency row retained only in snapshot"
            )
    task_ids, task_events = set(), set()
    for row in snapshot.get("hook_tasks", {}).get("rows", []):
        try:
            if (
                set(row)
                != {
                    "quest_id",
                    "event_id",
                    "plan",
                    "status",
                    "owner",
                    "result",
                    "updated_at",
                }
                or row["event_id"] not in event_ids
                or type(row["quest_id"]) is not str
                or not row["quest_id"]
                or row["quest_id"] in task_ids
                or row["event_id"] in task_events
                or type(_parse_json(row["plan"])) is not dict
                or type(row["updated_at"]) is not str
            ):
                raise SafetyError("Invalid/orphan task")
            if row["result"] is not None:
                _parse_json(row["result"])
            tasks.append(row)
            task_ids.add(row["quest_id"])
            task_events.add(row["event_id"])
        except (SafetyError, KeyError, TypeError):
            missing.append("Invalid queue task retained only in snapshot")
    sequences = set()
    for row in snapshot.get("hook_audit", {}).get("rows", []):
        try:
            if (
                set(row) != {"sequence", "recorded_at", "action", "event_id", "details"}
                or type(row["sequence"]) is not int
                or row["sequence"] <= 0
                or row["sequence"] in sequences
                or not all(
                    type(row[k]) is str and row[k] for k in ("recorded_at", "action")
                )
                or type(_parse_json(row["details"])) is not dict
            ):
                raise SafetyError("Invalid audit row")
            audit.append(row)
            sequences.add(row["sequence"])
        except (SafetyError, KeyError, TypeError):
            missing.append("Invalid queue audit row retained only in snapshot")
    return events, aliases, tasks, audit


def recover_store(
    root: Path | str,
    destination: str,
    *,
    write: bool = False,
    source_database: str | None = "state/siqe.sqlite3",
    queue_export: str | None = "artifacts/reports/hook_event_log.json",
) -> dict:
    """Inventory by default. Explicit write creates a NEW, stopped database only.

    Stop all writers and discard retained SQLite connections before calling.
    Inputs are never repaired, deleted, renamed, or opened writable. Source
    database rows are supplementary: verified canonical blobs remain authority.
    """
    if type(write) is not bool:
        raise SafetyError("Recovery write flag must be an explicit boolean")
    requested = Path(root).expanduser()
    if requested.is_symlink() or not requested.is_dir():
        raise SafetyError("Recovery root must be an existing real workspace")
    root = requested.resolve(strict=True)
    if any(part.is_symlink() for part in requested.absolute().parents):
        raise SafetyError("Recovery root ancestors cannot be symlinks")
    blobs = _path(root, "evidence/blobs", exists=True)
    if not blobs.is_dir():
        raise SafetyError("Missing immutable evidence directory")
    target = _path(root, destination)
    if Path(destination).parts[0] == "evidence":
        raise SafetyError("Destination cannot be inside immutable evidence")
    for suffix in ("", "-wal", "-shm", "-journal", ".manifest.json"):
        candidate = _path(root, destination + suffix)
        if candidate.exists():
            raise SafetyError("Destination or sidecar already exists; never overwrite")
    if not target.parent.is_dir():
        raise SafetyError("Destination parent must already exist")
    missing, invalid, ignored, valid_shas = [], [], [], []
    candidates = defaultdict(dict)
    recovered_blobs = {}

    def admit(
        raw: bytes,
        origin: str,
        sequence: int | None = None,
        evidence: dict | None = None,
    ):
        envelope = _envelope(raw)
        if envelope is None:
            return False
        reference = _reference(raw)
        if evidence is not None:
            if (
                type(evidence) is not dict
                or evidence.get("sha256") != reference["sha256"]
                or evidence.get("path") != reference["path"]
                or type(evidence.get("bytes")) is not int
                or evidence["bytes"] != len(raw)
                or type(evidence.get("media_type")) is not str
            ):
                raise SafetyError("Invalid original record evidence descriptor")
            reference = evidence
        identity = (envelope["kind"], envelope["key"])
        prior = candidates[identity].get(envelope["record_id"])
        if prior is not None:
            if prior["raw"] != raw:
                raise SafetyError("Same record identifier has different bytes")
            prior["origins"].append(origin)
            if sequence is not None:
                if prior["sequence"] is not None and prior["sequence"] != sequence:
                    raise SafetyError("Conflicting original record sequence")
                prior["sequence"], prior["evidence"] = sequence, reference
        else:
            candidates[identity][envelope["record_id"]] = {
                "envelope": envelope,
                "raw": raw,
                "evidence": reference,
                "origins": [origin],
                "sequence": sequence,
            }
        recovered_blobs[reference["sha256"]] = raw
        return True

    for entry in sorted(blobs.iterdir(), key=lambda p: p.name):
        origin = f"evidence/blobs/{entry.name}"
        try:
            if not _HASH.fullmatch(entry.name):
                raise SafetyError("Invalid content-addressed filename")
            raw = _read(_path(root, origin))
            if hashlib.sha256(raw).hexdigest() != entry.name:
                raise SafetyError("Filename SHA256 differs from actual bytes")
            valid_shas.append(entry.name)
            if not admit(raw, origin):
                ignored.append(entry.name)
        except (OSError, SafetyError) as exc:
            invalid.append({"source": origin, "reason": str(exc)})

    snapshot = _snapshot(root, source_database, missing)
    for row in snapshot.get("records", {}).get("rows", []):
        try:
            raw = row["content_json"].encode("utf-8")
            envelope = _envelope(raw)
            if (
                envelope is None
                or any(
                    row[column] != envelope[field]
                    for column, field in (
                        ("record_id", "record_id"),
                        ("kind", "kind"),
                        ("record_key", "key"),
                        ("created_at", "created_at"),
                    )
                )
                or type(row["sequence"]) is not int
                or row["sequence"] <= 0
            ):
                raise SafetyError(
                    "Source database metadata differs from canonical record"
                )
            reference = _parse_json(row["evidence_json"])
            blob = _path(root, f"evidence/blobs/{hashlib.sha256(raw).hexdigest()}")
            if blob.exists() and _read(blob) != raw:
                raise SafetyError(
                    "Source database conflicts with existing immutable blob"
                )
            admit(
                raw,
                f"{source_database}:records:{row['sequence']}",
                row["sequence"],
                reference,
            )
        except (OSError, SafetyError, KeyError, TypeError, AttributeError) as exc:
            invalid.append({"source": f"{source_database}:records", "reason": str(exc)})

    conflicts, selected = [], []
    for (kind, key), versions in sorted(candidates.items()):
        if len(versions) > 1:
            conflicts.append(
                {
                    "kind": kind,
                    "key": key,
                    "record_ids": sorted(versions),
                    "policy": "all versions retained as evidence; none inserted",
                }
            )
        else:
            selected.extend(versions.values())
    selected.sort(
        key=lambda r: (
            r["sequence"] is None,
            r["sequence"] or 0,
            r["envelope"]["created_at"],
            r["envelope"]["record_id"],
        )
    )
    sequences = [r["sequence"] for r in selected if r["sequence"] is not None]
    if len(sequences) != len(set(sequences)):
        raise SafetyError("Source records contain conflicting sequence numbers")
    if any(r["sequence"] is None for r in selected):
        missing.append(
            "Original SQLite sequence unavailable for some records; appended in timestamp/ID order, not claimed original order"
        )
    # Retain the original scientific record even if one of its referenced inputs
    # is missing; make that limitation explicit rather than inventing a blob.
    evidence_gaps = []
    verified = set(valid_shas) | set(recovered_blobs)

    def inspect_references(value, record_id):
        if type(value) is dict:
            sha = value.get("sha256")
            if (
                type(sha) is str
                and _HASH.fullmatch(sha)
                and value.get("path") == f"evidence/blobs/{sha}"
                and sha not in verified
            ):
                evidence_gaps.append({"record_id": record_id, "missing_sha256": sha})
            for item in value.values():
                inspect_references(item, record_id)
        elif type(value) is list:
            for item in value:
                inspect_references(item, record_id)

    for record in selected:
        inspect_references(record["envelope"]["value"], record["envelope"]["record_id"])
    if evidence_gaps:
        missing.append(
            "Some preserved records reference missing or corrupt evidence blobs; see evidence_gaps"
        )
    events, aliases, tasks, audit = _queue_rows(snapshot, missing)
    export_raw, export_value = None, None
    if queue_export is not None:
        export_path = _path(root, queue_export)
        if export_path.exists():
            export_raw = _read(export_path)
            try:
                export_value = _parse_json(export_raw.decode("utf-8"))
                if (
                    type(export_value) is not dict
                    or type(export_value.get("events")) is not list
                    or any(type(e) is not dict for e in export_value["events"])
                ):
                    raise SafetyError("Invalid hook event export schema")
            except (SafetyError, UnicodeError) as exc:
                missing.append(f"Queue export uninterpretable; bytes preserved: {exc}")
                export_value = None
        else:
            missing.append(f"Queue export missing: {queue_export}")
    event_provenance = defaultdict(list)
    for record in selected:
        env = record["envelope"]
        if env["kind"] in ("runtime_review", "source_health"):
            event_id = env["value"].get("event_id")
            if type(event_id) is str and event_id:
                event_provenance[event_id].append(env["record_id"])
    queue_ids = {row["event_id"] for row in events}
    export_ids = {
        event["event_id"]
        for event in (export_value["events"] if export_value else [])
        if type(event.get("event_id")) is str
    }
    operational_inventory = [
        {
            "event_id": event_id,
            "scientific_record_ids": sorted(event_provenance.get(event_id, [])),
            "valid_queue_row": event_id in queue_ids,
            "export_evidence": event_id in export_ids,
            "approval": "REQUIRED",
            "execution": "BLOCKED",
        }
        for event_id in sorted(set(event_provenance) | queue_ids | export_ids)
    ]
    missing.extend(
        [
            "Queue exports omit original request hashes, periodic aliases and full hook audit; never synthesized",
            "Operational tables may be incomplete after corruption; reconcile export, snapshot, runtime_review/source_health and external worker logs manually",
            "No execution approval transfers: STOPPED, all imported events/tasks QUARANTINED; no event emitted or replayed",
            "Runtime schedule/checkpoints/source checks and webhook nonce/intake state retained in snapshot evidence only; operator reconciliation required before enabling intake or workers",
        ]
    )
    evidence_payloads = {
        "source_database_snapshot": canonical_json(snapshot).encode("utf-8")
    }
    if export_raw is not None:
        evidence_payloads["queue_export_original"] = export_raw
    references = {name: _reference(raw) for name, raw in evidence_payloads.items()}
    manifest = {
        "schema": "siqe-offline-recovery-1",
        "created_at": utcnow(),
        "destination": destination,
        "write_requested": write,
        "source_database": source_database,
        "queue_export": queue_export,
        "counts": {
            "verified_blobs": len(valid_shas),
            "raw_blobs_ignored": len(ignored),
            "records_selected": len(selected),
            "invalid": len(invalid),
            "conflicting_identities": len(conflicts),
            "queue_events_importable": len(events),
            "queue_audit_rows_importable": len(audit),
            "export_events_evidence_only": len(export_value["events"])
            if export_value
            else 0,
        },
        "records_by_kind": dict(
            sorted(Counter(r["envelope"]["kind"] for r in selected).items())
        ),
        "verified_sha256": valid_shas,
        "raw_blobs_ignored": ignored,
        "records": [
            {
                "record_id": r["envelope"]["record_id"],
                "kind": r["envelope"]["kind"],
                "key": r["envelope"]["key"],
                "created_at": r["envelope"]["created_at"],
                "evidence": r["evidence"],
                "original_sequence": r["sequence"],
                "origins": r["origins"],
            }
            for r in selected
        ],
        "invalid": invalid,
        "conflicts": conflicts,
        "missing_data": missing,
        "evidence_gaps": evidence_gaps,
        "preserved_operational_evidence": references,
        "operational_event_inventory": operational_inventory,
        "queue_policy": {
            "control": "STOPPED",
            "events": "QUARANTINED",
            "tasks": "QUARANTINED",
            "automatic_replay": False,
            "new_operator_approval_required": True,
            "export_is_exact_queue_backup": False,
        },
        "operator_handoff": [
            "Keep original database, WAL/SHM, worker logs, all blobs and exports unchanged",
            "Compare record IDs/bytes/counts and mission/source/experiment histories before installing",
            "Resolve conflicting/invalid records and missing queue audit; do not claim exact recovery",
            "Reconcile every interrupted event and idempotency alias against evidence before explicit approval",
            "Install only in a fresh isolated process after all SQLite connections and writers are closed",
        ],
    }
    manifest_raw = canonical_json(manifest).encode("utf-8")
    manifest_reference = _reference(manifest_raw)
    if write:
        # O_EXCL is the final no-overwrite guard. Never remove this file on error:
        # a failed reconstruction is evidence, not permission to destroy state.
        fd = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        os.close(fd)
        for raw in recovered_blobs.values():
            _publish(root, raw)
        for raw in evidence_payloads.values():
            _publish(root, raw)
        _publish(root, manifest_raw)
        sidecar = _path(root, destination + ".manifest.json")
        fd = os.open(
            sidecar, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(manifest_raw)
            stream.flush()
            os.fsync(stream.fileno())
        conn = sqlite3.connect(target)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=FULL")
            conn.executescript(_SCHEMA)
            next_sequence = max(sequences, default=0)
            with conn:
                for record in selected:
                    env = record["envelope"]
                    sequence = record["sequence"]
                    if sequence is None:
                        next_sequence += 1
                        sequence = next_sequence
                    conn.execute(
                        "INSERT INTO records VALUES(?,?,?,?,?,?,?)",
                        (
                            sequence,
                            env["record_id"],
                            env["kind"],
                            env["key"],
                            env["created_at"],
                            record["raw"].decode("utf-8"),
                            canonical_json(record["evidence"]),
                        ),
                    )
                for table, rows in (
                    ("hook_events", events),
                    ("hook_idempotency", aliases),
                    ("hook_tasks", tasks),
                    ("hook_audit", audit),
                ):
                    for original in rows:
                        row = dict(original)
                        if table in ("hook_events", "hook_tasks"):
                            row["status"] = "QUARANTINED"
                            if table == "hook_events":
                                row["lease_owner"], row["lease_until"] = None, None
                            else:
                                row["owner"] = None
                        columns = ",".join(f'"{name}"' for name in row)
                        placeholders = ",".join("?" for _ in row)
                        conn.execute(
                            f'INSERT INTO "{table}"({columns}) VALUES({placeholders})',
                            tuple(row.values()),
                        )
                for label, ref in {
                    **references,
                    "recovery_manifest": manifest_reference,
                }.items():
                    conn.execute(
                        "INSERT INTO recovery_evidence VALUES(?,?)",
                        (label, canonical_json(ref)),
                    )
                if export_value:
                    for ordinal, event in enumerate(export_value["events"]):
                        event_id = event.get("event_id")
                        conn.execute(
                            "INSERT INTO recovery_queue_quarantine VALUES(?,?,?,'QUARANTINED',?)",
                            (
                                queue_export,
                                ordinal,
                                event_id if type(event_id) is str else None,
                                canonical_json(event),
                            ),
                        )
                conn.execute(
                    "INSERT INTO hook_audit(recorded_at,action,event_id,details) VALUES(?,?,NULL,?)",
                    (
                        manifest["created_at"],
                        "OFFLINE_RECOVERY_STOPPED",
                        canonical_json(
                            {
                                "manifest": manifest_reference,
                                "operator_approval_required": True,
                            }
                        ),
                    ),
                )
        finally:
            conn.close()
    return {
        "written": write,
        "manifest": manifest,
        "manifest_evidence": manifest_reference,
        "manifest_published": write,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--destination", required=True, help="NEW workspace-relative database file"
    )
    parser.add_argument("--source-database", default="state/siqe.sqlite3")
    parser.add_argument(
        "--queue-export", default="artifacts/reports/hook_event_log.json"
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Explicit offline write; default is read-only inventory",
    )
    args = parser.parse_args(argv)
    try:
        result = recover_store(
            args.root,
            args.destination,
            write=args.write,
            source_database=args.source_database,
            queue_export=args.queue_export,
        )
    except (SafetyError, OSError, sqlite3.Error) as exc:
        print(
            canonical_json(
                {
                    "written": False,
                    "error": str(exc),
                    "warning": "Retain any partial destination as evidence; never replace original",
                }
            )
        )
        return 2
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

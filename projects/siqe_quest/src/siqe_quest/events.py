"""Durable, bounded research hook planning. Payloads are data, never programs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import math
import sqlite3
import time
from typing import Any

from .core import Store, canonical_json, digest, utcnow


# A hook is one bounded research quest; actions are its acceptance checklist, not
# recursive child jobs. Executors must use fixed handlers and verify evidence.
HOOK_ACTIONS = {
    "SESSION_INITIALIZED": (
        "Verify workspace identity",
        "Load SIQE operating configuration",
        "Retrieve operational context",
        "Load pending tasks",
        "Check interrupted experiments",
        "Check current resource budget",
        "Resume only authorized incomplete work",
    ),
    "KNOWLEDGE_GAP_DETECTED": (
        "Register the gap",
        "Classify importance",
        "Select candidate sources",
        "Generate an acquisition task",
        "Estimate research cost",
        "Add bounded authorized research work to the queue",
    ),
    "NEW_SOURCE_DISCOVERED": (
        "Validate domain and publisher",
        "Inspect access conditions",
        "Check data relevance",
        "Detect duplicates",
        "Register source",
        "Schedule minimal retrieval validation",
    ),
    "SOURCE_UPDATED": (
        "Identify changed content",
        "Preserve relevant versions",
        "Re-evaluate dependent research",
        "Mark stale derived conclusions",
        "Trigger targeted verification",
    ),
    "NEW_RESEARCH_PAPER": (
        "Extract the research question",
        "Identify the hypothesis",
        "Examine methodology",
        "Check data availability",
        "Analyze limitations",
        "Register a reproduction proposal without assuming the claimed result is verified",
    ),
    "NEW_MARKET_EVENT": (
        "Independently verify event and identify affected markets",
        "Resolve instruments and entities",
        "Check observation and availability timing",
        "Create economic transmission hypotheses",
        "Compare with existing forecasts",
        "Schedule a bounded research update, not an order",
    ),
    "NEW_KNOWLEDGE_VALIDATED": (
        "Create a versioned knowledge record only after evidence verification",
        "Link original sources",
        "Add counterexamples",
        "Add applicability conditions",
        "Save verified procedural lessons",
        "Mark relevant outdated knowledge",
    ),
    "EXPERIMENT_COMPLETED": (
        "Persist experiment output",
        "Compare against locked baselines",
        "Audit numerical correctness",
        "Record negative results",
        "Determine whether bounded follow-up research is justified",
    ),
    "BACKTEST_FAILED": (
        "Classify failure",
        "Check data integrity",
        "Examine costs and fill assumptions",
        "Check temporal leakage",
        "Determine whether original hypothesis is falsified",
        "Register an explanatory lesson; never launch endless parameter optimization",
    ),
    "STRATEGY_PASSED_RESEARCH_GATE": (
        "Freeze strategy specification",
        "Register approved source version",
        "Generate Pine Script v6 where applicable",
        "Generate independently testable Python reference",
        "Schedule parity and forward-paper evaluation; no live promotion",
    ),
    "RETRIEVAL_OR_MEMORY_CONTRADICTION": (
        "Compare source dates",
        "Compare definitions",
        "Check versions",
        "Identify superseded conclusions",
        "Block conflicting unsupported claims from promotion pending evidence resolution",
    ),
    "TOOL_FAILURE": (
        "Classify actual runtime error",
        "Apply bounded retry policy",
        "Select authorized fallback sources only if appropriate",
        "Preserve failure evidence",
        "Prevent recursive retry loops",
    ),
    "PERIODIC_RESEARCH_REVIEW": (
        "Review unresolved questions",
        "Check source freshness",
        "Check queue health",
        "Identify useful experiments",
        "Rebalance authorized research budget",
    ),
    "SAFETY_VIOLATION": (
        "Prevent prohibited action",
        "Preserve redacted audit trace",
        "Quarantine unsafe tasks",
        "Require explicit external authorization for protected operations; never self-authorize",
    ),
    "KNOWLEDGE_DECAY_DETECTED": (
        "Revalidate relevant sources",
        "Check whether definitions changed",
        "Supersede outdated findings",
        "Preserve historical knowledge",
        "Never rewrite immutable forecasts",
    ),
}


@dataclass
class Event:
    """Submission schema; None identity/time fields are generated on first emit.

    payload_reference and provenance_reference are inert JSON references. Mutable
    delivery state (attempt_count, ownership, leases) is assigned by EventQueue.
    """

    event_type: str
    idempotency_key: str
    payload_reference: dict
    provenance_reference: dict | str
    event_id: str | None = None
    emitted_at: str | None = None
    observed_at: str | None = None
    source_id: str = "local_research"
    affected_entities: list[str] = field(default_factory=list)
    source_version: str = "1"
    correlation_id: str | None = None
    priority: int = 0
    task_budget: int = 8
    retry_count: int = 0
    maximum_attempts: int = 3
    status: str = "PENDING"
    depth: int = 0
    parent_event_id: str | None = None


class QueueFullError(RuntimeError):
    """Backpressure: retry submission later with the identical idempotency key."""


class IdempotencyConflict(ValueError):
    """An existing idempotency identity was reused for different content."""


class LeaseError(RuntimeError):
    """Only the current owner of an unexpired lease may finalize work."""


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def _timestamp(value: Any, name: str) -> float:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an aware ISO8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("naive timestamp")
        stamp = parsed.timestamp()
        if not math.isfinite(stamp):
            raise ValueError("nonfinite timestamp")
        return stamp
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{name} must be an aware ISO8601 timestamp") from exc


class EventQueue:
    """SQLite transactional queue with durable plans, leases and operator control."""

    def __init__(self, store: Store):
        self.store = store
        self.max_queue = _integer(
            store.config.get("max_queue", 128), "max_queue", 1, 100000
        )
        self.max_depth = _integer(store.config.get("max_depth", 3), "max_depth", 0, 32)
        self.task_budget = _integer(
            store.config.get("task_budget", 8), "task_budget", 1, 1024
        )
        self.max_attempts = _integer(
            store.config.get("max_attempts", 3), "max_attempts", 1, 100
        )
        self.review_interval = _integer(
            store.config.get("review_interval_seconds", 21600),
            "review_interval_seconds",
            1,
            31536000,
        )
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS hook_control (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), state TEXT NOT NULL);
                INSERT OR IGNORE INTO hook_control VALUES (1, 'RUNNING');
                CREATE TABLE IF NOT EXISTS hook_events (
                    event_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
                    request_hash TEXT NOT NULL, body TEXT NOT NULL,
                    periodic_key TEXT UNIQUE, periodic_hash TEXT,
                    status TEXT NOT NULL, priority INTEGER NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at REAL NOT NULL, lease_owner TEXT, lease_until REAL,
                    remaining_budget INTEGER NOT NULL, result TEXT, last_error TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS hook_idempotency (
                    idempotency_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
                    event_id TEXT NOT NULL REFERENCES hook_events(event_id));
                CREATE INDEX IF NOT EXISTS hook_ready ON hook_events(status,next_attempt_at,priority);
                CREATE TABLE IF NOT EXISTS hook_tasks (
                    quest_id TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE
                        REFERENCES hook_events(event_id),
                    plan TEXT NOT NULL, status TEXT NOT NULL, owner TEXT,
                    result TEXT, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS hook_audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at TEXT NOT NULL, action TEXT NOT NULL,
                    event_id TEXT, details TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS hook_audit_no_update
                    BEFORE UPDATE ON hook_audit BEGIN
                    SELECT RAISE(ABORT, 'hook audit is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS hook_audit_no_delete
                    BEFORE DELETE ON hook_audit BEGIN
                    SELECT RAISE(ABORT, 'hook audit is immutable'); END;
            """)

    def _connection(self):
        from contextlib import contextmanager

        @contextmanager
        def connected():
            conn = self.store.connection()
            try:
                with conn:
                    yield conn
            finally:
                conn.close()

        return connected()

    @staticmethod
    def _audit(conn, action: str, event_id: str | None, details: dict) -> None:
        conn.execute(
            "INSERT INTO hook_audit(recorded_at,action,event_id,details) VALUES(?,?,?,?)",
            (utcnow(), action, event_id, canonical_json(details)),
        )

    def _validate(self, event: Event | dict) -> dict:
        if isinstance(event, Event):
            body = asdict(event)
        elif isinstance(event, dict):
            unknown = set(event) - set(Event.__dataclass_fields__)
            if unknown:
                raise ValueError(f"Unknown event fields: {sorted(unknown)}")
            try:
                body = asdict(Event(**event))
            except TypeError as exc:
                raise ValueError("Missing required event fields") from exc
        else:
            raise ValueError("Event must be Event or dict")
        if (
            not isinstance(body["event_type"], str)
            or body["event_type"] not in HOOK_ACTIONS
        ):
            raise ValueError("Unknown event_type")
        for key in ("idempotency_key", "source_id", "source_version"):
            if (
                not isinstance(body[key], str)
                or not body[key].strip()
                or len(body[key]) > 512
            ):
                raise ValueError(f"{key} must be a nonempty bounded string")
        for key in ("event_id", "correlation_id", "parent_event_id"):
            if body[key] is not None and (
                not isinstance(body[key], str)
                or not body[key].strip()
                or len(body[key]) > 512
            ):
                raise ValueError(f"{key} must be a nonempty bounded string or None")
        if (
            not isinstance(body["payload_reference"], dict)
            or not body["payload_reference"]
        ):
            raise ValueError("payload_reference must be a nonempty JSON object")
        provenance = body["provenance_reference"]
        if (
            not isinstance(provenance, (dict, str))
            or not provenance
            or (isinstance(provenance, str) and not provenance.strip())
        ):
            raise ValueError("provenance_reference must be a nonempty JSON reference")
        entities = body["affected_entities"]
        if (
            not isinstance(entities, list)
            or len(entities) > 100
            or any(
                not isinstance(item, str) or not item.strip() or len(item) > 256
                for item in entities
            )
        ):
            raise ValueError(
                "affected_entities must be a bounded list of nonempty strings"
            )
        _integer(body["priority"], "priority", -100, 100)
        _integer(body["task_budget"], "task_budget", 1, self.task_budget)
        _integer(body["maximum_attempts"], "maximum_attempts", 1, self.max_attempts)
        _integer(body["depth"], "depth", 0, self.max_depth)
        if (
            type(body["retry_count"]) is not int
            or body["retry_count"] != 0
            or body["status"] != "PENDING"
        ):
            raise ValueError("New events must have retry_count=0 and status=PENDING")
        if body["depth"] and not body["parent_event_id"]:
            raise ValueError("Nonzero depth requires a parent_event_id")
        for key in ("emitted_at", "observed_at"):
            if body[key] is not None:
                _timestamp(body[key], key)
        if (
            body["emitted_at"]
            and body["observed_at"]
            and (
                _timestamp(body["observed_at"], "observed_at")
                > _timestamp(body["emitted_at"], "emitted_at")
            )
        ):
            raise ValueError("observed_at cannot be after emitted_at")
        try:
            serialized = canonical_json(body)
        except (ValueError, TypeError) as exc:
            raise ValueError("Event references must contain finite JSON only") from exc
        if len(serialized.encode("utf-8")) > 65536:
            raise ValueError("Event exceeds 64KiB reference envelope")
        return body

    def emit(self, event: Event | dict) -> str:
        request = self._validate(event)
        request_hash = digest(request)
        now = time.time()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM hook_idempotency WHERE idempotency_key=?",
                (request["idempotency_key"],),
            ).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict(
                        "Same idempotency key has conflicting event content"
                    )
                return existing["event_id"]
            periodic_key = periodic_hash = None
            if request["event_type"] == "PERIODIC_RESEARCH_REVIEW":
                when = request["observed_at"] or request["emitted_at"]
                bucket = int(
                    (_timestamp(when, "schedule_time") if when else now)
                    // self.review_interval
                )
                periodic_key = digest([request["source_id"], bucket])
                periodic_body = {
                    key: value
                    for key, value in request.items()
                    if key
                    not in {
                        "event_id",
                        "idempotency_key",
                        "correlation_id",
                        "emitted_at",
                        "observed_at",
                    }
                }
                periodic_hash = digest(periodic_body)
                prior = conn.execute(
                    "SELECT * FROM hook_events WHERE periodic_key=?", (periodic_key,)
                ).fetchone()
                if prior:
                    if prior["periodic_hash"] != periodic_hash:
                        raise IdempotencyConflict(
                            "Conflicting periodic review in the same schedule window"
                        )
                    conn.execute(
                        "INSERT INTO hook_idempotency VALUES(?,?,?)",
                        (request["idempotency_key"], request_hash, prior["event_id"]),
                    )
                    return prior["event_id"]
            count = conn.execute(
                "SELECT COUNT(*) FROM hook_events WHERE status IN ('PENDING','RETRY','CLAIMED','QUARANTINED')"
            ).fetchone()[0]
            if count >= self.max_queue:
                raise QueueFullError(
                    "Research queue is full; backpressure prevents submission"
                )
            if request["parent_event_id"]:
                parent = conn.execute(
                    "SELECT * FROM hook_events WHERE event_id=?",
                    (request["parent_event_id"],),
                ).fetchone()
                if parent is None or parent["status"] == "QUARANTINED":
                    raise ValueError("Parent must exist and must not be quarantined")
                parent_body = json.loads(parent["body"])
                if request["depth"] != parent_body["depth"] + 1:
                    raise ValueError("Child depth must be parent depth plus one")
                if parent["remaining_budget"] < request["task_budget"]:
                    raise ValueError("Parent follow-up budget exhausted")
                conn.execute(
                    "UPDATE hook_events SET remaining_budget=remaining_budget-? WHERE event_id=?",
                    (request["task_budget"], request["parent_event_id"]),
                )
            body = dict(request)
            event_id = body["event_id"] or digest(
                ["siqe-event", body["idempotency_key"]]
            )
            body["event_id"] = event_id
            body["emitted_at"] = body["emitted_at"] or utcnow()
            body["observed_at"] = body["observed_at"] or body["emitted_at"]
            if _timestamp(body["observed_at"], "observed_at") > _timestamp(
                body["emitted_at"], "emitted_at"
            ):
                raise ValueError("observed_at cannot be after emitted_at")
            body["correlation_id"] = body["correlation_id"] or event_id
            status = (
                "QUARANTINED" if body["event_type"] == "SAFETY_VIOLATION" else "PENDING"
            )
            body["status"] = status
            stamp = utcnow()
            try:
                conn.execute(
                    """INSERT INTO hook_events
                    (event_id,idempotency_key,request_hash,body,periodic_key,periodic_hash,status,
                     priority,next_attempt_at,remaining_budget,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        event_id,
                        body["idempotency_key"],
                        request_hash,
                        canonical_json(body),
                        periodic_key,
                        periodic_hash,
                        status,
                        body["priority"],
                        now,
                        body["task_budget"] - 1,
                        stamp,
                        stamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise IdempotencyConflict(
                    "event_id already belongs to another submission"
                ) from exc
            conn.execute(
                "INSERT INTO hook_idempotency VALUES(?,?,?)",
                (body["idempotency_key"], request_hash, event_id),
            )
            for plan in self.dispatch(body):
                conn.execute(
                    "INSERT INTO hook_tasks VALUES(?,?,?,?,?,?,?)",
                    (
                        plan["quest_id"],
                        event_id,
                        canonical_json(plan),
                        status,
                        None,
                        None,
                        stamp,
                    ),
                )
            self._audit(
                conn,
                "EMITTED",
                event_id,
                {
                    "event_type": body["event_type"],
                    "status": status,
                    "request_hash": request_hash,
                },
            )
            if status == "QUARANTINED":
                self._audit(
                    conn,
                    "SAFETY_QUARANTINED",
                    event_id,
                    {"action_prevented": True, "authorization_required": True},
                )
            if body["event_type"] == "RETRIEVAL_OR_MEMORY_CONTRADICTION":
                self._audit(
                    conn, "PROMOTION_BLOCKED", event_id, {"promotion_blocked": True}
                )
            return event_id

    def control(self, command: str) -> str:
        if not isinstance(command, str) or command not in {"STOP", "PAUSE", "RESUME"}:
            raise ValueError("Control command must be STOP, PAUSE or RESUME")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT state FROM hook_control WHERE singleton=1"
            ).fetchone()[0]
            state = {"STOP": "STOPPED", "PAUSE": "PAUSED", "RESUME": "RUNNING"}[command]
            if previous == "STOPPED" and command == "PAUSE":
                state = "STOPPED"
            conn.execute("UPDATE hook_control SET state=? WHERE singleton=1", (state,))
            self._audit(
                conn,
                "CONTROL",
                None,
                {"command": command, "previous": previous, "state": state},
            )
            return state

    def state(self) -> str:
        with self._connection() as conn:
            return conn.execute(
                "SELECT state FROM hook_control WHERE singleton=1"
            ).fetchone()[0]

    def _transition(
        self,
        conn,
        event_id: str,
        status: str,
        now: float,
        *,
        owner=None,
        lease_until=None,
        result=None,
        error=None,
        next_at=None,
    ):
        stamp = utcnow()
        conn.execute(
            """UPDATE hook_events SET status=?,lease_owner=?,lease_until=?,
            result=?,last_error=?,next_attempt_at=?,updated_at=? WHERE event_id=?""",
            (
                status,
                owner,
                lease_until,
                canonical_json(result) if result is not None else None,
                error,
                now if next_at is None else next_at,
                stamp,
                event_id,
            ),
        )
        conn.execute(
            "UPDATE hook_tasks SET status=?,owner=?,result=?,updated_at=? WHERE event_id=?",
            (
                status,
                owner,
                canonical_json(result) if result is not None else None,
                stamp,
                event_id,
            ),
        )

    def _reclaim(self, conn, now: float) -> None:
        expired = conn.execute(
            "SELECT * FROM hook_events WHERE status='CLAIMED' AND lease_until<=?",
            (now,),
        ).fetchall()
        for row in expired:
            body = json.loads(row["body"])
            status = (
                "DEADLETTER"
                if row["attempt_count"] >= body["maximum_attempts"]
                else "RETRY"
            )
            self._transition(
                conn,
                row["event_id"],
                status,
                now,
                error="Lease expired; worker interrupted",
            )
            self._audit(
                conn,
                "LEASE_EXPIRED",
                row["event_id"],
                {
                    "previous_owner": row["lease_owner"],
                    "status": status,
                    "attempt_count": row["attempt_count"],
                },
            )

    def claim(self, worker_id: str, lease_seconds=30) -> dict | None:
        if (
            not isinstance(worker_id, str)
            or not worker_id.strip()
            or len(worker_id) > 256
        ):
            raise ValueError("worker_id must be a nonempty bounded string")
        if (
            type(lease_seconds) not in (int, float)
            or not math.isfinite(lease_seconds)
            or not 0 < lease_seconds <= 3600
        ):
            raise ValueError("lease_seconds must be finite and in (0, 3600]")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now = time.time()
            if (
                conn.execute(
                    "SELECT state FROM hook_control WHERE singleton=1"
                ).fetchone()[0]
                != "RUNNING"
            ):
                return None
            self._reclaim(conn, now)
            row = conn.execute(
                """SELECT * FROM hook_events WHERE status IN ('PENDING','RETRY')
                AND next_attempt_at<=? ORDER BY priority DESC,created_at,event_id LIMIT 1""",
                (now,),
            ).fetchone()
            if row is None:
                return None
            until = now + lease_seconds
            conn.execute(
                "UPDATE hook_events SET attempt_count=attempt_count+1 WHERE event_id=?",
                (row["event_id"],),
            )
            self._transition(
                conn,
                row["event_id"],
                "CLAIMED",
                now,
                owner=worker_id,
                lease_until=until,
            )
            self._audit(
                conn,
                "CLAIMED",
                row["event_id"],
                {
                    "worker_id": worker_id,
                    "lease_until": until,
                    "attempt_count": row["attempt_count"] + 1,
                },
            )
            updated = conn.execute(
                "SELECT * FROM hook_events WHERE event_id=?", (row["event_id"],)
            ).fetchone()
            return self._shape(conn, updated)

    @staticmethod
    def _owned(conn, event_id: str, worker_id: str, now: float):
        row = conn.execute(
            "SELECT * FROM hook_events WHERE event_id=?", (event_id,)
        ).fetchone()
        if (
            row is None
            or row["status"] != "CLAIMED"
            or row["lease_owner"] != worker_id
            or row["lease_until"] <= now
        ):
            raise LeaseError("Event requires an unexpired lease owned by this worker")
        return row

    def complete(self, event_id: str, worker_id: str, result: dict) -> None:
        if not isinstance(result, dict):
            raise ValueError("result must be a JSON object")
        canonical_json(result)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now = time.time()
            row = self._owned(conn, event_id, worker_id, now)
            body = json.loads(row["body"])
            # A completed review is not authority to promote a disputed claim.
            if body["event_type"] == "RETRIEVAL_OR_MEMORY_CONTRADICTION":
                result = dict(result, promotion_blocked=True)
            self._transition(conn, event_id, "COMPLETED", now, result=result)
            self._audit(
                conn,
                "COMPLETED",
                event_id,
                {"worker_id": worker_id, "result_hash": digest(result)},
            )

    def fail(self, event_id: str, worker_id: str, error: str) -> None:
        if not isinstance(error, str) or not error.strip():
            raise ValueError("error must be nonempty text")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now = time.time()
            row = self._owned(conn, event_id, worker_id, now)
            body = json.loads(row["body"])
            exhausted = row["attempt_count"] >= body["maximum_attempts"]
            status = "DEADLETTER" if exhausted else "RETRY"
            delay = 0 if exhausted else min(300, 2 ** min(row["attempt_count"] - 1, 9))
            # Error text can contain credentials/tool payloads. Store its digest
            # instead; callers persist a separately redacted evidence record.
            error_summary = "Runtime failure sha256=" + digest(error)
            self._transition(
                conn, event_id, status, now, error=error_summary, next_at=now + delay
            )
            self._audit(
                conn,
                "FAILED",
                event_id,
                {
                    "worker_id": worker_id,
                    "status": status,
                    "error_hash": digest(error),
                    "backoff_seconds": delay,
                },
            )

    @staticmethod
    def _shape(conn, row) -> dict:
        event = json.loads(row["body"])
        event.update(
            status=row["status"],
            retry_count=max(0, row["attempt_count"] - 1),
            attempt_count=row["attempt_count"],
            lease_owner=row["lease_owner"],
            lease_until=row["lease_until"],
            next_attempt_at=row["next_attempt_at"],
            remaining_budget=row["remaining_budget"],
            result=json.loads(row["result"]) if row["result"] is not None else None,
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        event["payload"] = event["payload_reference"]
        tasks = conn.execute(
            "SELECT * FROM hook_tasks WHERE event_id=? ORDER BY quest_id",
            (row["event_id"],),
        ).fetchall()
        event["tasks"] = [
            dict(
                json.loads(task["plan"]),
                status=task["status"],
                owner=task["owner"],
                result=json.loads(task["result"])
                if task["result"] is not None
                else None,
                updated_at=task["updated_at"],
            )
            for task in tasks
        ]
        event["promotion_blocked"] = (
            event["event_type"] == "RETRIEVAL_OR_MEMORY_CONTRADICTION"
        )
        return event

    def events(self) -> list[dict]:
        with self._connection() as conn:
            return [
                self._shape(conn, row)
                for row in conn.execute(
                    "SELECT * FROM hook_events ORDER BY created_at,event_id"
                ).fetchall()
            ]

    def stats(self) -> dict:
        with self._connection() as conn:
            counts = {
                row["status"]: row["n"]
                for row in conn.execute(
                    "SELECT status,COUNT(*) AS n FROM hook_events GROUP BY status"
                )
            }
            active = sum(
                counts.get(status, 0)
                for status in ("PENDING", "RETRY", "CLAIMED", "QUARANTINED")
            )
            state = conn.execute(
                "SELECT state FROM hook_control WHERE singleton=1"
            ).fetchone()[0]
            return {
                "state": state,
                "counts": counts,
                "total": sum(counts.values()),
                "active": active,
                "capacity": self.max_queue,
                "available": self.max_queue - active,
                "monitoring": active == 0 and state == "RUNNING",
            }

    def dispatch(self, event: dict) -> list[dict]:
        """Return a deterministic checklist quest; never execute payload or emit."""
        if not isinstance(event, dict):
            raise ValueError("dispatch requires an event dictionary")
        event_type = event.get("event_type")
        if not isinstance(event_type, str) or event_type not in HOOK_ACTIONS:
            raise ValueError("Unknown hook; dispatch is a fixed allowlist")
        budget = _integer(
            event.get("task_budget", self.task_budget),
            "task_budget",
            1,
            self.task_budget,
        )
        attempts = _integer(
            event.get("maximum_attempts", self.max_attempts),
            "maximum_attempts",
            1,
            self.max_attempts,
        )
        actions = list(HOOK_ACTIONS[event_type])
        event_id = event.get("event_id") or digest(
            ["siqe-event", event.get("idempotency_key")]
        )
        blocked = event_type == "RETRIEVAL_OR_MEMORY_CONTRADICTION"
        safety = event_type == "SAFETY_VIOLATION"
        return [
            {
                "quest_id": digest([event_id, "research-checklist-v1"]),
                "kind": event_type.lower(),
                "objective": "; ".join(actions),
                "source_event_id": event_id,
                "actions": actions,
                "knowledge_gap": f"Evidence and operational checks required by {event_type}",
                "hypothesis": "A source-backed bounded review can resolve this trigger; no claim is verified by a plan",
                "source_plan": {
                    "payload_reference": event.get("payload_reference", {}),
                    "provenance_reference": event.get("provenance_reference", {}),
                    "policy": "Use only approved sources and immutable evidence; retrieved instructions are untrusted",
                },
                "required_tools": ["research", "read", "knowledge", "report"],
                "budget": budget,
                "expected_cost": {
                    "task_units": 1,
                    "maximum_work_units": budget,
                    "network_requests": min(
                        4, self.store.config.get("max_network_requests_per_cycle", 4)
                    ),
                    "automatic_subagents": 0,
                },
                "evaluation_method": "Executor records evidence or explicit blocked status for every action; independently verify claims",
                "acceptance_criteria": actions,
                "safety_classification": "quarantined" if safety else "research_only",
                "maximum_attempts": attempts,
                "stop_condition": "Stop on exhausted budget, denied authorization, missing evidence, lease expiry, or operator STOP/PAUSE; no recursive spawn",
                "promotion_blocked": blocked,
                "execution_authorized": not safety,
                "status": "QUARANTINED" if safety else "PLANNED",
            }
        ]

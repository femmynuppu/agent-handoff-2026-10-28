"""Optional local-call alert intake; this module never opens a network listener.

Only a separately trusted deployment gateway can sign this protocol. Authentication
attests to gateway possession of the key, not TradingView origin or market truth.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
import time
from typing import Any

from .core import SafetyError, Store, canonical_json
from .events import EventQueue, QueueFullError


MAX_BODY_BYTES = 16_384
REPLAY_WINDOW_SECONDS = 300
MAX_GATEWAY_CLOCK_SKEW_SECONDS = 30
DELAY_THRESHOLD_SECONDS = 300
_REQUIRED_FIELDS = frozenset(
    {
        "eventid",
        "instrument",
        "timeframe",
        "signal",
        "observed_at",
        "sent_at",
        "source_version",
    }
)
_HEADER_NAMES = ("x-siqe-timestamp", "x-siqe-nonce", "x-siqe-signature")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_INSTRUMENT = re.compile(r"[A-Z0-9][A-Z0-9:./_-]{0,63}\Z")
_TIMEFRAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}\Z")
_NONCE = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")


class AlertRejected(SafetyError):
    """A sanitized fail-closed rejection; never includes supplied body or headers."""


def _reject_constant(_: str) -> Any:
    raise AlertRejected("nonfinite JSON is forbidden")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise AlertRejected("duplicate JSON keys are forbidden")
        result[key] = value
    return result


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise AlertRejected("timestamps must be aware ISO8601 strings")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise AlertRejected("timestamps must be aware ISO8601 strings") from None


class AlertIntake:
    """Authenticate and durably enqueue research-only market alerts.

    Required case-insensitive headers are X-SIQE-Timestamp (canonical Unix seconds),
    X-SIQE-Nonce (16..128 URL-safe ASCII characters), and X-SIQE-Signature
    (``sha256=`` followed by 64 lowercase hex digits). Sign exactly
    ``timestamp.encode('ascii') + b'\\n' + nonce.encode('ascii') + b'\\n' + body``.
    Secrets must contain at least 32 bytes, provisioned outside alert bodies.

    A valid fresh nonce is consumed on durable admission, even if queue capacity
    prevents immediate delivery. Retrying with a NEW signature/nonce and identical
    alert id/body resumes pending delivery. Reusing a consumed nonce is rejected.
    No constructor or rejected request drains pending work.
    """

    def __init__(self, store: Store, secret: bytes):
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise AlertRejected(
                "a deployment gateway secret of at least 32 bytes is required"
            )
        self.store = store
        self._secret = secret
        with closing(store.connection()) as conn, conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS webhook_nonces (
                    nonce_sha256 TEXT PRIMARY KEY,
                    authenticated_at TEXT NOT NULL,
                    signature_timestamp INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS webhook_intake (
                    alert_id TEXT PRIMARY KEY,
                    payload_sha256 TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    stream_key TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    timing_json TEXT NOT NULL,
                    queue_event_id TEXT
                );
                CREATE INDEX IF NOT EXISTS webhook_stream_time
                ON webhook_intake(stream_key, observed_at);
            """)

    def _authenticate(self, body: bytes, headers: dict, now: float) -> tuple[str, int]:
        if not isinstance(body, bytes) or not 0 < len(body) <= MAX_BODY_BYTES:
            raise AlertRejected(
                "alert body must be nonempty bytes within the size limit"
            )
        if not isinstance(headers, dict):
            raise AlertRejected("authentication headers are required")
        selected: dict[str, str] = {}
        for name, value in headers.items():
            if not isinstance(name, str):
                raise AlertRejected("invalid authentication headers")
            lowered = name.lower()
            if lowered in _HEADER_NAMES:
                if lowered in selected or not isinstance(value, str):
                    raise AlertRejected("ambiguous authentication headers")
                selected[lowered] = value
        if set(selected) != set(_HEADER_NAMES):
            raise AlertRejected("authentication headers are required")
        stamp = selected["x-siqe-timestamp"]
        nonce = selected["x-siqe-nonce"]
        signature = selected["x-siqe-signature"]
        if not re.fullmatch(r"[1-9][0-9]{0,11}", stamp) or not _NONCE.fullmatch(nonce):
            raise AlertRejected("invalid authentication headers")
        timestamp = int(stamp)
        if (
            now - timestamp > REPLAY_WINDOW_SECONDS
            or timestamp - now > MAX_GATEWAY_CLOCK_SKEW_SECONDS
        ):
            raise AlertRejected("authentication timestamp is outside the replay window")
        if not re.fullmatch(r"sha256=[0-9a-f]{64}", signature):
            raise AlertRejected("invalid signature")
        message = stamp.encode("ascii") + b"\n" + nonce.encode("ascii") + b"\n" + body
        expected = (
            "sha256=" + hmac.new(self._secret, message, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(expected, signature):
            raise AlertRejected("invalid signature")
        return hashlib.sha256(nonce.encode("ascii")).hexdigest(), timestamp

    def _validate(self, body: bytes, now: datetime) -> tuple[dict, datetime, datetime]:
        try:
            payload = json.loads(
                body.decode("utf-8"),
                parse_constant=_reject_constant,
                object_pairs_hook=_unique_object,
            )
        except (UnicodeError, ValueError, RecursionError):
            raise AlertRejected("invalid finite JSON object") from None
        if not isinstance(payload, dict) or set(payload) != _REQUIRED_FIELDS:
            raise AlertRejected(
                "alert schema requires exactly the seven documented fields"
            )
        for field in ("eventid", "source_version"):
            if not isinstance(payload[field], str) or not _TOKEN.fullmatch(
                payload[field]
            ):
                raise AlertRejected("invalid identity or source version")
        if (
            not isinstance(payload["instrument"], str)
            or not _INSTRUMENT.fullmatch(payload["instrument"])
            or "://" in payload["instrument"]
        ):
            raise AlertRejected("invalid research instrument")
        if not isinstance(payload["timeframe"], str) or not _TIMEFRAME.fullmatch(
            payload["timeframe"]
        ):
            raise AlertRejected("invalid research timeframe")
        if not isinstance(payload["signal"], str) or payload["signal"] not in {
            "LONG",
            "SHORT",
            "EXIT",
            "FLAT",
        }:
            raise AlertRejected(
                "signal must be a research label, never an order or command"
            )
        observed = _parse_time(payload["observed_at"])
        sent = _parse_time(payload["sent_at"])
        if observed > sent or sent > now:
            raise AlertRejected(
                "alert observation and send times are inconsistent or future-dated"
            )
        return payload, observed, sent

    def ingest(self, body: bytes, headers: dict) -> dict:
        """Return admission/queue state; raise AlertRejected for unsafe requests.

        There is no network, account, broker, subprocess, or executable URL action.
        Only validated labels enter the fixed NEW_MARKET_EVENT research handler.
        """
        now_seconds = time.time()
        nonce_hash, timestamp = self._authenticate(body, headers, now_seconds)
        received = datetime.fromtimestamp(now_seconds, timezone.utc)
        payload, observed, sent = self._validate(body, received)
        payload_hash = hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest()
        stream_key = canonical_json(
            [payload["instrument"], payload["timeframe"], payload["source_version"]]
        )
        observed_at = observed.isoformat(timespec="microseconds")
        received_at = received.isoformat(timespec="microseconds")
        with closing(self.store.connection()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT 1 FROM webhook_nonces WHERE nonce_sha256=?", (nonce_hash,)
            ).fetchone():
                raise AlertRejected("replayed gateway nonce")
            existing = conn.execute(
                "SELECT * FROM webhook_intake WHERE alert_id=?", (payload["eventid"],)
            ).fetchone()
            if existing is not None and existing["payload_sha256"] != payload_hash:
                raise AlertRejected("alert identity conflicts with admitted payload")
            duplicate = existing is not None
            if existing is None:
                latest = conn.execute(
                    "SELECT MAX(observed_at) FROM webhook_intake WHERE stream_key=?",
                    (stream_key,),
                ).fetchone()[0]
                out_of_order = latest is not None and observed_at < latest
                timing = {
                    "delayed": (received - sent).total_seconds()
                    > DELAY_THRESHOLD_SECONDS,
                    "out_of_order": out_of_order,
                    "transport_delay_seconds": (received - sent).total_seconds(),
                    "observation_to_send_seconds": (sent - observed).total_seconds(),
                    "missing_alerts": "NOT_INFERABLE_WITHOUT_SOURCE_SEQUENCE_OR_HEARTBEAT",
                }
                provenance = {
                    "authentication": "TRUSTED_GATEWAY_HMAC_SHA256",
                    "origin_status": "GATEWAY_AUTHENTICATED_SOURCE_CLAIM_UNVERIFIED",
                    "raw_body_sha256": hashlib.sha256(body).hexdigest(),
                    "payload_sha256": payload_hash,
                    "received_at": received_at,
                    "gateway_timestamp": timestamp,
                    "claimed_source_version": payload["source_version"],
                    "transport": "LOCAL_CALL_NO_LISTENER",
                }
                event = {
                    "event_type": "NEW_MARKET_EVENT",
                    "idempotency_key": "webhook:" + payload["eventid"],
                    "emitted_at": received_at,
                    "observed_at": observed_at,
                    "source_id": "local_authenticated_gateway",
                    "source_version": payload["source_version"],
                    "affected_entities": [payload["instrument"]],
                    "correlation_id": payload["eventid"],
                    "payload_reference": {
                        "storage": "webhook_intake",
                        "alert_id": payload["eventid"],
                        "alert": payload,
                        "timing": timing,
                        "research_only": True,
                        "requires_independent_market_data_verification": True,
                        "broker_orders_allowed": False,
                    },
                    "provenance_reference": provenance,
                    "task_budget": min(8, int(self.store.config.get("task_budget", 8))),
                    "maximum_attempts": min(
                        3, int(self.store.config.get("max_attempts", 3))
                    ),
                }
                event_json = canonical_json(event)
                conn.execute(
                    "INSERT INTO webhook_intake VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                    (
                        payload["eventid"],
                        payload_hash,
                        event_json,
                        received_at,
                        stream_key,
                        observed_at,
                        canonical_json(timing),
                    ),
                )
                queue_event_id = None
            else:
                event_json = existing["event_json"]
                timing = json.loads(existing["timing_json"])
                queue_event_id = existing["queue_event_id"]
            conn.execute(
                "INSERT INTO webhook_nonces VALUES (?, ?, ?)",
                (nonce_hash, received_at, timestamp),
            )
        # A durable outbox boundary: queue.emit is itself idempotent. A crash after
        # emit but before the update below is recovered by a fresh signed retry.
        if queue_event_id is None:
            try:
                queue_event_id = EventQueue(self.store).emit(json.loads(event_json))
            except QueueFullError:
                queue_event_id = None
            if queue_event_id is not None:
                with closing(self.store.connection()) as conn, conn:
                    conn.execute(
                        "UPDATE webhook_intake SET queue_event_id=? WHERE alert_id=?",
                        (queue_event_id, payload["eventid"]),
                    )
        return {
            "status": "DUPLICATE" if duplicate else "ACCEPTED",
            "queue_status": "QUEUED" if queue_event_id is not None else "PENDING",
            "alert_id": payload["eventid"],
            "event_id": queue_event_id,
            "timing": timing,
            "research_only": True,
            "independent_market_data_verification": "REQUIRED_NOT_PERFORMED",
        }

"""Local-only alert boundary and durable replay/idempotency tests."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from siqe_quest.core import SafetyError, Store
from siqe_quest.events import EventQueue, QueueFullError
from siqe_quest.webhooks import AlertIntake, AlertRejected, MAX_BODY_BYTES


NOW = 1_800_000_000
SECRET = b"test-only-gateway-key-32-bytes-long-not-a-live-secret"


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


class AlertIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root)
        self.queue = EventQueue(self.store)
        self.intake = AlertIntake(self.store, SECRET)
        self.counter = 0
        self.clock = patch("siqe_quest.webhooks.time.time", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def payload(self, **changes):
        result = {
            "eventid": "alert-001",
            "instrument": "USD/CAD",
            "timeframe": "1D",
            "signal": "LONG",
            "observed_at": iso(NOW - 20),
            "sent_at": iso(NOW - 10),
            "source_version": "pine-sma20-60-v1",
        }
        result.update(changes)
        return result

    def body(self, **changes):
        return json.dumps(self.payload(**changes), separators=(",", ":")).encode()

    def headers(self, body, timestamp=NOW, nonce=None):
        self.counter += 1
        nonce = nonce or "nonce-for-test-%016d" % self.counter
        stamp = str(timestamp)
        message = stamp.encode() + b"\n" + nonce.encode() + b"\n" + body
        signature = hmac.new(SECRET, message, hashlib.sha256).hexdigest()
        return {
            "X-SIQE-Timestamp": stamp,
            "X-SIQE-Nonce": nonce,
            "X-SIQE-Signature": "sha256=" + signature,
        }

    def ingest(self, **changes):
        body = self.body(**changes)
        return self.intake.ingest(body, self.headers(body))

    def assert_rejected_unchanged(self, body, headers):
        before = self.queue.events()
        with self.assertRaises(AlertRejected) as caught:
            self.intake.ingest(body, headers)
        self.assertEqual(self.queue.events(), before)
        return str(caught.exception)

    def test_authorized_local_alert_routes_research_once_with_provenance(self):
        body = self.body()
        result = self.intake.ingest(body, self.headers(body))
        self.assertEqual(result["status"], "ACCEPTED")
        self.assertEqual(result["queue_status"], "QUEUED")
        self.assertTrue(result["research_only"])
        self.assertEqual(
            result["independent_market_data_verification"], "REQUIRED_NOT_PERFORMED"
        )
        events = self.queue.events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["event_type"], "NEW_MARKET_EVENT")
        payload = event["payload_reference"]
        self.assertTrue(payload["requires_independent_market_data_verification"])
        self.assertFalse(payload["broker_orders_allowed"])
        provenance = event["provenance_reference"]
        self.assertEqual(
            provenance["raw_body_sha256"], hashlib.sha256(body).hexdigest()
        )
        self.assertEqual(
            provenance["origin_status"], "GATEWAY_AUTHENTICATED_SOURCE_CLAIM_UNVERIFIED"
        )
        self.assertEqual(provenance["transport"], "LOCAL_CALL_NO_LISTENER")
        plans = self.queue.dispatch(event)
        self.assertTrue(plans)
        self.assertIn("verif", json.dumps(plans).lower())

    def test_missing_short_or_nonbytes_secret_fails_closed(self):
        for secret in (None, b"", b"short", "not-bytes"):
            with (
                self.subTest(secret_type=type(secret).__name__),
                self.assertRaises(AlertRejected),
            ):
                AlertIntake(self.store, secret)
        self.assertEqual(self.queue.events(), [])

    def test_missing_forged_malformed_or_ambiguous_headers_never_enqueue(self):
        body = self.body()
        bad = [{}, {"Authorization": "Bearer not-an-intake-key"}]
        for replacement in ("sha256=" + "0" * 64, "bad", "sha256=" + "A" * 64):
            headers = self.headers(body)
            headers["X-SIQE-Signature"] = replacement
            bad.append(headers)
        headers = self.headers(body)
        headers["x-siqe-nonce"] = headers["X-SIQE-Nonce"]
        bad.append(headers)
        headers = self.headers(body)
        headers["X-SIQE-Timestamp"] = str(NOW) + " "
        bad.append(headers)
        headers = self.headers(body)
        headers["X-SIQE-Nonce"] = "short"
        bad.append(headers)
        for headers in bad:
            with self.subTest(headers=list(headers)):
                self.assert_rejected_unchanged(body, headers)

    def test_authentication_precedes_json_parsing(self):
        with patch(
            "siqe_quest.webhooks.json.loads",
            side_effect=AssertionError("must not parse"),
        ):
            self.assert_rejected_unchanged(b"not-json", {})

    def test_signature_binds_raw_body_nonce_and_timestamp(self):
        body = self.body()
        headers = self.headers(body)
        self.assert_rejected_unchanged(body + b" ", headers)
        headers = self.headers(body)
        headers["X-SIQE-Nonce"] = "modified-nonce-1234567890"
        self.assert_rejected_unchanged(body, headers)
        headers = self.headers(body)
        headers["X-SIQE-Timestamp"] = str(NOW - 1)
        self.assert_rejected_unchanged(body, headers)

    def test_stale_and_excessively_future_gateway_timestamps_reject(self):
        body = self.body()
        for stamp in (NOW - 301, NOW + 31):
            self.assert_rejected_unchanged(body, self.headers(body, timestamp=stamp))
        self.assertEqual(
            self.intake.ingest(body, self.headers(body, timestamp=NOW - 300))["status"],
            "ACCEPTED",
        )

    def test_replay_durable_across_reconstruction_even_for_another_payload(self):
        body = self.body()
        headers = self.headers(body, nonce="durable-nonce-123456789")
        self.intake.ingest(body, headers)
        self.intake = AlertIntake(Store(self.root), SECRET)
        self.assert_rejected_unchanged(body, headers)
        other = self.body(eventid="different-alert")
        self.assert_rejected_unchanged(
            other, self.headers(other, nonce="durable-nonce-123456789")
        )
        self.assertEqual(len(self.queue.events()), 1)

    def test_fresh_nonce_duplicate_id_is_idempotent_and_conflict_rejected(self):
        first = self.ingest()
        duplicate = self.ingest()
        self.assertEqual(duplicate["status"], "DUPLICATE")
        self.assertEqual(duplicate["event_id"], first["event_id"])
        self.assertEqual(len(self.queue.events()), 1)
        body = self.body(signal="EXIT")
        self.assert_rejected_unchanged(body, self.headers(body))
        # Insignificant JSON formatting does not change the semantic payload.
        body = json.dumps(self.payload(), indent=2, sort_keys=True).encode()
        self.assertEqual(
            self.intake.ingest(body, self.headers(body))["event_id"], first["event_id"]
        )

    def test_body_size_and_type_limits_precede_parsing(self):
        for body in (b"", b"x" * (MAX_BODY_BYTES + 1), "not-bytes", None):
            self.assert_rejected_unchanged(body, {})

    def test_schema_forbids_nonfinite_duplicates_nested_values_and_invalid_times(self):
        invalid = [
            b"[]",
            b"null",
            b"{bad-json",
            b"\xff",
            b'{"eventid":"a","eventid":"b"}',
            self.body().replace(b'"signal":"LONG"', b'"signal":NaN'),
            self.body().replace(b'"signal":"LONG"', b'"signal":Infinity'),
        ]
        invalid.extend(
            self.body(**changes)
            for changes in (
                {"eventid": "../escape"},
                {"instrument": "https://attacker.invalid"},
                {"signal": {"execute": "broker_order"}},
                {"signal": "BUY"},
                {"signal": "LONG; shell-command"},
                {"timeframe": ["1D"]},
                {"source_version": None},
                {"observed_at": iso(NOW + 1)},
                {"sent_at": iso(NOW + 1)},
                {"observed_at": iso(NOW - 5)},
                {"sent_at": "2026-10-01T12:00:00"},
                {"observed_at": "not-a-time"},
            )
        )
        for body in invalid:
            with self.subTest(body_type=type(body).__name__):
                self.assert_rejected_unchanged(body, self.headers(body))

    def test_extra_fields_credentials_urls_and_broker_instructions_reject_without_logging(
        self,
    ):
        marker = "must-never-appear-in-persistence"
        for field in (
            "password",
            "api_key",
            "credentials",
            "order",
            "url",
            "script",
            "broker",
        ):
            payload = self.payload()
            payload[field] = marker
            body = json.dumps(payload).encode()
            error = self.assert_rejected_unchanged(body, self.headers(body))
            self.assertNotIn(marker, error)
        with closing(self.store.connection()) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM webhook_intake").fetchone()[0], 0
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM webhook_nonces").fetchone()[0], 0
            )
        self.assertNotIn(marker, json.dumps(self.store.records("audit")))
        self.assertNotIn(SECRET.decode(), repr(self.intake))
        for action in (
            "trade",
            "account.mutate",
            "withdraw",
            "publication",
            "external_exec",
        ):
            with self.subTest(action=action), self.assertRaises(SafetyError):
                self.store.authorize(action)

    def test_transport_delay_and_observation_order_are_independent(self):
        first = self.ingest()
        self.assertFalse(first["timing"]["delayed"])
        self.assertFalse(first["timing"]["out_of_order"])
        old = self.ingest(
            eventid="old-observation", observed_at=iso(NOW - 900), sent_at=iso(NOW - 5)
        )
        self.assertFalse(old["timing"]["delayed"])
        self.assertTrue(old["timing"]["out_of_order"])
        delayed = self.ingest(
            eventid="delayed-transport",
            observed_at=iso(NOW - 800),
            sent_at=iso(NOW - 700),
        )
        self.assertTrue(delayed["timing"]["delayed"])
        self.assertTrue(delayed["timing"]["out_of_order"])
        independent = self.ingest(
            eventid="other-stream",
            timeframe="4H",
            observed_at=iso(NOW - 800),
            sent_at=iso(NOW - 700),
        )
        self.assertFalse(independent["timing"]["out_of_order"])
        self.assertEqual(
            independent["timing"]["missing_alerts"],
            "NOT_INFERABLE_WITHOUT_SOURCE_SEQUENCE_OR_HEARTBEAT",
        )

    def test_authenticated_queue_backpressure_preserves_recoverable_outbox(self):
        body = self.body()
        headers = self.headers(body)
        with patch.object(EventQueue, "emit", side_effect=QueueFullError("full")):
            result = self.intake.ingest(body, headers)
        self.assertEqual(result["queue_status"], "PENDING")
        self.assertEqual(self.queue.events(), [])
        self.assert_rejected_unchanged(body, headers)
        self.intake = AlertIntake(Store(self.root), SECRET)
        result = self.intake.ingest(body, self.headers(body))
        self.assertEqual(result["status"], "DUPLICATE")
        self.assertEqual(result["queue_status"], "QUEUED")
        self.assertEqual(len(self.queue.events()), 1)

    def test_crash_after_queue_commit_before_inbox_ack_recovers_exactly_once(self):
        emit = EventQueue.emit

        def commit_then_crash(queue, event):
            emit(queue, event)
            raise RuntimeError("simulated crash after durable queue commit")

        with patch.object(EventQueue, "emit", new=commit_then_crash):
            with self.assertRaises(RuntimeError):
                self.ingest()
        self.assertEqual(len(self.queue.events()), 1)
        self.intake = AlertIntake(Store(self.root), SECRET)
        recovered = self.ingest()
        self.assertEqual(recovered["status"], "DUPLICATE")
        self.assertEqual(recovered["queue_status"], "QUEUED")
        self.assertEqual(len(self.queue.events()), 1)

    def test_concurrent_fresh_deliveries_share_one_queue_event(self):
        body = self.body()
        headers = [self.headers(body) for _ in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(
                    lambda item: AlertIntake(Store(self.root), SECRET).ingest(
                        body, item
                    ),
                    headers,
                )
            )
        self.assertEqual(sum(item["status"] == "ACCEPTED" for item in results), 1)
        self.assertEqual(len({item["event_id"] for item in results}), 1)
        self.assertEqual(len(self.queue.events()), 1)

    def test_concurrent_same_nonce_allows_only_one_admission(self):
        body = self.body()
        headers = self.headers(body, nonce="same-nonce-across-workers-12345")

        def deliver(_):
            try:
                return AlertIntake(Store(self.root), SECRET).ingest(body, headers)[
                    "status"
                ]
            except AlertRejected:
                return "REJECTED"

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(deliver, range(4)))
        self.assertEqual(results.count("ACCEPTED"), 1)
        self.assertEqual(results.count("REJECTED"), 3)
        self.assertEqual(len(self.queue.events()), 1)

    def test_ingest_never_connects_or_opens_a_listener(self):
        with patch("socket.socket", side_effect=AssertionError("no network allowed")):
            self.assertEqual(self.ingest()["queue_status"], "QUEUED")


if __name__ == "__main__":
    unittest.main()

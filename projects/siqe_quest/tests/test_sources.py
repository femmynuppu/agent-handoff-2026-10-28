"""Deterministic fixtures only; these tests never retrieve financial data."""

import copy
import json
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from siqe_quest.core import Store, digest
from siqe_quest.sources import (
    DOCS,
    END,
    ORIGIN,
    ROBOTS,
    SERIES,
    START,
    TERMS,
    SourceError,
    SourceHunter,
    _network_transport,
)

NOW = "2026-10-26T12:00:00+00:00"
POLICY = b"User-agent: *\nDisallow: /private\nAllow: /\n"
TERMS_BODY = b"Bank of Canada Terms: Attribution; third-party restrictions. Indicative exchange rates, LSEG. Do not circumvent request limits."
CATALOG = b"""openapi: 3.0.3
servers:
  - url: https://www.bankofcanada.ca/valet
paths:
  /search/series:
    get: {}
  /series/{seriesName}/{format}:
    get: {}
  /observations/{seriesNames}/{format}:
    get: {}
  /fx_rss/{seriesNames}:
    get: {}
"""


def fixture_payload(full=False):
    """Explicitly synthetic data for schema/behavior tests, never mission evidence."""
    days = []
    day = date(2023, 1, 2)
    stop = date(2025, 12, 31) if full else date(2023, 1, 4)
    while day <= stop:
        if day.weekday() < 5:
            days.append(
                {"d": day.isoformat(), SERIES: {"v": str(1.3 + len(days) * 0.00001)}}
            )
        day += timedelta(days=1)
    return {
        "seriesDetail": {
            SERIES: {
                "label": "USD/CAD",
                "description": "US dollar to Canadian dollar daily exchange rate",
            }
        },
        "observations": days,
    }


def fixture_series_metadata():
    """Official series endpoint schema; observations use a different detail map."""
    return {
        "terms": {"url": TERMS},
        "seriesDetails": {
            "name": SERIES,
            "label": "USD/CAD",
            "description": "Daily average exchange rate of the US dollar in Canadian dollars.",
            "dateFormat": "daily",
            "metadata": {
                "frequency": "Business daily",
                "unit": "Canadian dollars per US dollar",
            },
        },
    }


class FakeTransport:
    def __init__(self, payload=None):
        self.calls = []
        self.payload = payload or fixture_payload(full=True)
        self.overrides = {}

    def __call__(self, url, headers, timeout, max_bytes):
        self.calls.append((url, headers, timeout, max_bytes))
        if url in self.overrides:
            result = self.overrides[url]
            if isinstance(result, Exception):
                raise result
            return dict(result, url=result.get("url", url))
        if url == ROBOTS:
            body = POLICY
        elif url == TERMS:
            body = TERMS_BODY
        elif url == DOCS:
            body = (
                b'<script src="/valet/static/swagger/swagger-initializer.js"></script>'
            )
        elif url.endswith("swagger-initializer.js"):
            body = b"const swaggerUrl = new URL(`static/swagger/api-${lang}.yml`, window.location.origin + basePath);"
        elif url.endswith("api-en.yml"):
            body = CATALOG
        elif "/search/series?" in url:
            body = json.dumps(
                {
                    "series": {
                        SERIES: {
                            "label": "USD/CAD",
                            "description": "US dollar to Canadian dollar daily average exchange rate",
                            "link": ORIGIN + "/valet/series/FXUSDCAD",
                        }
                    }
                }
            ).encode()
        elif "/series/FXUSDCAD" in url:
            body = json.dumps(fixture_series_metadata()).encode()
        elif "/fx_rss/" in url:
            body = b"<rss><channel><title>Fixture feed</title></channel></rss>"
        elif "/observations/" in url:
            payload = copy.deepcopy(self.payload)
            if "recent=1" in url:
                payload["observations"] = payload["observations"][-1:]
            body = json.dumps(payload).encode()
        else:
            raise AssertionError("unexpected fixture request: " + url)
        return {
            "status": 200,
            "headers": {"content-type": "application/json", "etag": '"fixture"'},
            "body": body,
            "url": url,
        }


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.transport = FakeTransport()
        self.hunter = SourceHunter(
            self.store, self.transport, clock=lambda: NOW, sleeper=lambda _: None
        )

    def test_gap_plan_and_actual_official_catalog_traversal(self):
        result = self.hunter.discover("USD CAD currency history")
        urls = [call[0] for call in self.transport.calls]
        self.assertEqual(urls[:3], [ROBOTS, TERMS, DOCS])
        self.assertTrue(any(url.endswith("swagger-initializer.js") for url in urls))
        self.assertTrue(any(url.endswith("api-en.yml") for url in urls))
        self.assertTrue(any(source["source_type"] == "dataset" for source in result))
        plan = self.store.records("discovery_plan")[0]["value"]
        self.assertIn("USD", plan["entities"])
        self.assertIn("daily average", plan["topics"])
        self.assertLessEqual(len(urls), 16)
        phases = self.store.records("discovery_result")[-1]["value"]["phases"]
        self.assertEqual(sum(phase["request_count"] for phase in phases), len(urls))
        self.assertTrue(all(phase["request_count"] <= 4 for phase in phases))
        for source in result:
            self.assertEqual(source["legal_publisher"], "Bank of Canada")
            self.assertIsNone(source["original_publication_time"])
            self.assertEqual(source["verification_outcome"], "DISCOVERED_NOT_VALIDATED")

    def test_discovery_query_changes_with_non_fx_gap(self):
        self.hunter.discover("inflation expectations")
        plan = self.store.records("discovery_plan")[0]["value"]
        self.assertEqual(plan["queries"][0], "inflation expectations")
        self.assertIn(
            ORIGIN + "/valet/search/series?search=inflation+expectations",
            [call[0] for call in self.transport.calls],
        )

    def test_exact_catalog_entity_beats_inverse_and_adversarial_metadata(self):
        gap = "USD CAD FXUSDCAD daily average reference rate financial research"
        search_url = ORIGIN + "/valet/search/series?search=FXUSDCAD"
        target_url = ORIGIN + "/valet/series/FXUSDCAD/json"
        spoof_name = "FXUSDCAD_COPY"
        spoof_url = ORIGIN + "/valet/series/" + spoof_name + "/json"
        series = {
            name: {"label": "USD/CAD", "description": gap}
            for name in ["FXCADUSD", "FXAUDCAD"]
            + ["FXNEAR" + str(index) for index in range(12)]
        }
        series[spoof_name] = {
            "label": "USD/CAD",
            "description": gap + " exchange rates",
        }
        # The exact identifier is deliberately last and has little fuzzy overlap.
        series[SERIES] = {"label": "USD/CAD"}
        self.transport.overrides[search_url] = {
            "status": 200,
            "headers": {},
            "body": json.dumps({"series": series}).encode(),
        }
        for name in series:
            if name != SERIES:
                self.transport.overrides[ORIGIN + "/valet/series/" + name + "/json"] = {
                    "status": 200,
                    "headers": {},
                    # Even a misleading exact-target payload cannot change URL identity.
                    "body": json.dumps(fixture_series_metadata()).encode(),
                }
        candidates = self.hunter.discover(gap)
        metadata_urls = [
            call[0] for call in self.transport.calls if "/valet/series/" in call[0]
        ]
        self.assertEqual(metadata_urls, [target_url, spoof_url])
        self.assertTrue(any(source["url"] == target_url for source in candidates))
        target = next(source for source in candidates if source["url"] == target_url)
        self.assertEqual(target["data_coverage"], fixture_series_metadata())
        self.assertTrue(self.hunter._is_alpha_source(target))
        self.assertFalse(
            self.hunter._is_alpha_source(
                next(source for source in candidates if source["url"] == spoof_url)
            )
        )
        plan_record = self.store.records("discovery_plan")[-1]
        persisted = json.loads(self.store.read_blob(plan_record["evidence"]))["value"]
        self.assertEqual(persisted, plan_record["value"])
        self.assertEqual(persisted["queries"][0], SERIES)
        before = len(self.transport.calls)
        data = self.hunter.acquire_alpha()
        self.assertEqual(data["manifest"]["source"]["url"], target_url)
        self.assertEqual(data["manifest"]["series"], SERIES)
        self.assertEqual(data["manifest"]["units"], "CAD per USD")
        self.assertEqual(len(self.transport.calls) - before, 4)
        self.assertEqual(
            json.loads(self.store.read_blob(data["manifest"]["raw"])),
            self.transport.payload,
        )

    def test_wrong_metadata_entity_or_inverse_units_cannot_acquire(self):
        target_url = ORIGIN + "/valet/series/FXUSDCAD/json"
        cases = []
        for name in ("FXCADUSD", "FXUSDCAD_COPY", None):
            payload = fixture_series_metadata()
            payload["seriesDetails"]["name"] = name
            cases.append(payload)
        payload = fixture_series_metadata()
        payload["seriesDetails"]["label"] = "CAD/USD"
        cases.append(payload)
        payload = fixture_series_metadata()
        payload["seriesDetails"]["metadata"]["unit"] = "US dollars per Canadian dollar"
        cases.append(payload)
        payload = fixture_series_metadata()
        payload["seriesDetails"]["metadata"] = {}
        payload["seriesDetails"]["description"] = "unknown units"
        cases.append(payload)
        cases.append({"seriesDetail": self.transport.payload["seriesDetail"]})
        for payload in cases:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as root:
                transport = FakeTransport()
                transport.overrides[target_url] = {
                    "status": 200,
                    "headers": {},
                    "body": json.dumps(payload).encode(),
                }
                hunter = SourceHunter(
                    Store(root), transport, clock=lambda: NOW, sleeper=lambda _: None
                )
                with self.assertRaisesRegex(
                    SourceError, "not found in official catalog"
                ):
                    hunter.acquire_alpha()
                self.assertFalse(
                    any("/observations/" in call[0] for call in transport.calls)
                )

    def test_legacy_observation_shaped_registry_metadata_is_rediscovered(self):
        self.hunter._begin()
        self.hunter._source(
            ORIGIN + "/valet/series/FXUSDCAD/json",
            {
                "raw": self.store.put_blob(b"legacy fixture", "application/json"),
                "retrieved_at": NOW,
                "status": 200,
            },
            "dataset",
            detail={"seriesDetail": self.transport.payload["seriesDetail"]},
        )
        dataset = self.hunter.acquire_alpha()
        self.assertEqual(
            dataset["manifest"]["source"]["data_coverage"], fixture_series_metadata()
        )
        self.assertTrue(any(call[0] == DOCS for call in self.transport.calls))
        self.assertEqual(len(self.store.records("source_snapshot")), 1)

    def test_unchanged_discovery_keeps_versions_and_exposes_fresh_retrievals(self):
        original = self.hunter.discover("USD CAD FXUSDCAD")
        later = "2026-10-27T12:00:00+00:00"
        self.hunter.clock = lambda: later
        rediscovered = self.hunter.discover("USD CAD FXUSDCAD")
        self.assertEqual(rediscovered, original)
        result = self.store.records("discovery_result")[-1]["value"]
        self.assertEqual(len(result["retrievals"]), result["request_count"])
        self.assertTrue(
            all(item["retrieved_at"] == later for item in result["retrievals"])
        )
        target = next(
            source for source in original if source["source_type"] == "dataset"
        )
        retrieval = next(
            item
            for item in result["retrievals"]
            if item["request_url"] == target["url"]
        )
        self.assertEqual(retrieval["raw"], target["evidence"])
        self.assertEqual(target["discovered_at"], NOW)

    def test_missing_catalog_entity_never_uses_fixed_fallback(self):
        search_url = ORIGIN + "/valet/search/series?search=FXUSDCAD"
        inverse_url = ORIGIN + "/valet/series/FXCADUSD/json"
        self.transport.overrides[search_url] = {
            "status": 200,
            "headers": {},
            "body": json.dumps(
                {
                    "series": {
                        "FXCADUSD": {
                            "label": "USD/CAD",
                            "description": "FXUSDCAD USD CAD daily average reference rate",
                        }
                    }
                }
            ).encode(),
        }
        self.transport.overrides[inverse_url] = {
            "status": 200,
            "headers": {},
            "body": json.dumps(
                {
                    "seriesDetails": {
                        "name": "FXCADUSD",
                        "label": "CAD/USD",
                        "metadata": {"unit": "US dollars per Canadian dollar"},
                    }
                }
            ).encode(),
        }
        self.hunter.discover("USD CAD FXUSDCAD daily average reference rate")
        with self.assertRaisesRegex(SourceError, "not found in official catalog"):
            self.hunter.acquire_alpha()
        urls = [call[0] for call in self.transport.calls]
        self.assertNotIn(ORIGIN + "/valet/series/FXUSDCAD/json", urls)
        self.assertFalse(any("/observations/" in url for url in urls))
        self.assertFalse(any("/fx_rss/FXUSDCAD" in url for url in urls))

    def test_exact_entity_requires_discovered_series_route(self):
        self.transport.overrides[ORIGIN + "/valet/static/swagger/api-en.yml"] = {
            "status": 200,
            "headers": {},
            "body": CATALOG.replace(
                b"  /series/{seriesName}/{format}:\n    get: {}\n", b""
            ),
        }
        with self.assertRaisesRegex(SourceError, "not found in official catalog"):
            self.hunter.acquire_alpha()
        self.assertFalse(
            any("/valet/series/" in call[0] for call in self.transport.calls)
        )
        self.assertFalse(
            any("/observations/" in call[0] for call in self.transport.calls)
        )

    def test_acquisition_manifest_and_unknown_historical_availability(self):
        data = self.hunter.acquire_alpha()
        manifest = data["manifest"]
        self.assertEqual(manifest["units"], "CAD per USD")
        self.assertEqual(manifest["coverage"]["requested_start"], START)
        self.assertEqual(manifest["coverage"]["requested_end"], END)
        self.assertEqual(
            manifest["source"]["verification_outcome"], "VALIDATED_RESEARCH_ONLY"
        )
        self.assertEqual(manifest["method"], "GET")
        self.assertEqual(manifest["historical_availability"], "UNKNOWN")
        unsigned = dict(manifest)
        unsigned.pop("manifest_id")
        self.assertEqual(manifest["manifest_id"], digest(unsigned))
        self.assertEqual(
            data["dataset_id"],
            digest(
                {
                    "series": SERIES,
                    "raw": manifest["raw"]["sha256"],
                    "normalized": manifest["normalized"]["sha256"],
                }
            ),
        )
        self.assertEqual(
            json.loads(self.store.read_blob(manifest["normalized"])),
            data["observations"],
        )
        self.assertEqual(
            json.loads(self.store.read_blob(manifest["raw"])), self.transport.payload
        )
        self.assertIsNotNone(self.store.get("dataset", data["dataset_id"]))
        self.assertIsNotNone(self.store.get("source_snapshot", manifest["manifest_id"]))
        for row in data["observations"]:
            self.assertIsNone(row["publication_time"])
            self.assertIsNone(row["available_at"])
            self.assertEqual(row["event_time"], row["date"])
            self.assertNotIn("open", row)
            self.assertLess(date.fromisoformat(row["date"]).weekday(), 5)
        self.assertEqual(self.hunter.request_count, 4)

    def test_robots_denial_and_error_fail_closed(self):
        for result in (
            {"status": 200, "headers": {}, "body": b"User-agent: *\nDisallow: /\n"},
            {"status": 503, "headers": {}, "body": b"unavailable"},
            {"status": 200, "headers": {}, "body": b"<html>error</html>"},
        ):
            with self.subTest(result=result):
                transport = FakeTransport()
                transport.overrides[ROBOTS] = result
                hunter = SourceHunter(self.store, transport, sleeper=lambda _: None)
                with self.assertRaises(SourceError):
                    hunter.discover("USD CAD")
                self.assertFalse(
                    any("/observations/" in call[0] for call in transport.calls)
                )

    def test_changed_or_unrecognized_terms_block_retrieval(self):
        self.hunter._begin()
        self.hunter._permissions()
        self.transport.overrides[TERMS] = {
            "status": 200,
            "headers": {},
            "body": TERMS_BODY + b" changed",
        }
        self.hunter._begin()
        with self.assertRaises(SourceError):
            self.hunter._permissions()
        self.transport.overrides[TERMS]["body"] = b"Terms not established"
        self.hunter._begin()
        with self.assertRaises(SourceError):
            self.hunter._permissions()

    def test_changed_terms_cannot_be_accepted_by_repetition_or_new_hunter(self):
        self.hunter.discover("USD CAD")
        accepted_policy_ids = [
            record["record_id"] for record in self.store.records("source_policy")
        ]
        self.transport.overrides[TERMS] = {
            "status": 200,
            "headers": {},
            "body": TERMS_BODY + b" changed but still recognizable",
        }
        fresh_hunter = SourceHunter(
            self.store, self.transport, clock=lambda: NOW, sleeper=lambda _: None
        )
        for hunter in (self.hunter, self.hunter, fresh_hunter):
            before = len(self.transport.calls)
            with self.assertRaisesRegex(SourceError, "terms content changed"):
                hunter.acquire_alpha()
            self.assertEqual(
                [call[0] for call in self.transport.calls[before:]],
                [ROBOTS, TERMS],
            )
            self.assertEqual(
                [record["record_id"] for record in self.store.records("source_policy")],
                accepted_policy_ids,
            )
        self.assertEqual(self.store.records("dataset"), [])

    def test_cosmetic_terms_revalidate_legacy_raw_without_rewriting_history(self):
        old = (
            b"<html><head><style>.old {color:red}</style></head><body>"
            b'<nav class="current-page-ancestor"><a href="/old">Menu</a></nav>'
            b'<main id="old"><h1>Terms of Use</h1><p>'
            + TERMS_BODY
            + b'</p><p>Review <a href="/rights/?version=1#limits">rights</a>.</p>'
            b'<span id="emailComponent123"></span><script nonce="old">'
            b'createEmailComponent("123"); throw new Error("never execute");'
            b"</script><noscript>Enable JavaScript</noscript></main>"
            b"<footer>Old footer</footer></body></html>"
        )
        current = (
            old.replace(b"current-page-ancestor", b"current-page")
            .replace(b'href="/old"', b'href="/new"')
            .replace(b"color:red", b"color:blue")
            .replace(b'id="old"', b'id="new"')
            .replace(b"Component123", b"Component456")
            .replace(b'nonce="old"', b'nonce="new"')
            .replace(b'("123")', b'("456")')
            .replace(b"Old footer", b"New footer")
            .replace(b"Terms of Use</h1><p>", b"Terms of Use</h1>\n <p>")
        )
        legacy_value = {"terms": {"raw": self.store.put_blob(old, "text/html")}}
        legacy = self.store.record("source_policy", digest(legacy_value), legacy_value)
        legacy_bytes = self.store.read_blob(legacy["evidence"])
        self.transport.overrides[TERMS] = {
            "status": 200,
            "headers": {"content-type": "text/html"},
            "body": current,
        }
        data = self.hunter.acquire_alpha()
        self.assertIn("dataset_id", data)
        accepted = self.store.records("source_policy")[-1]["value"]["terms"]
        self.assertNotEqual(
            accepted["raw"]["sha256"], legacy_value["terms"]["raw"]["sha256"]
        )
        self.assertEqual(self.store.read_blob(accepted["raw"]), current)
        self.assertEqual(self.store.read_blob(legacy_value["terms"]["raw"]), old)
        self.assertEqual(self.store.read_blob(legacy["evidence"]), legacy_bytes)
        self.assertNotIn("policy_content_sha256", legacy_value["terms"])
        self.assertEqual(len(accepted["policy_content_sha256"]), 64)
        self.assertEqual(
            accepted["policy_content_method"], "htmlparser-visible-text-hrefs-v1"
        )
        self.assertEqual(accepted["policy_content_source"], "main")
        self.hunter._begin()
        repeated = self.hunter._permissions()["terms"]
        self.assertEqual(
            repeated["policy_content_sha256"], accepted["policy_content_sha256"]
        )

    def test_full_terms_text_and_restrictive_href_changes_remain_blocked(self):
        original = (
            b"<main><p>" + TERMS_BODY + b"</p><section><p>Additional conditions: "
            b'<a href="/rights/?version=1#limits">usage restrictions</a> apply.'
            b"</p></section></main>"
        )
        self.transport.overrides[TERMS] = {
            "status": 200,
            "headers": {},
            "body": original,
        }
        self.hunter._begin()
        accepted = self.hunter._permissions()
        policy_ids = [
            record["record_id"] for record in self.store.records("source_policy")
        ]
        for changed in (
            original.replace(b" apply.", b" prohibit automated research."),
            original.replace(b"version=1", b"version=2"),
            original.replace(b"#limits", b"#commercial-use"),
            original.replace(b"<p>Additional", b'<p data-note=">">Additional').replace(
                b" apply.", b" now prohibit research."
            ),
            original.replace(b" apply.", b" <strong>not</strong> apply."),
        ):
            with self.subTest(changed=changed):
                self.transport.overrides[TERMS]["body"] = changed
                before = len(self.transport.calls)
                with self.assertRaisesRegex(SourceError, "terms content changed"):
                    self.hunter.acquire_alpha()
                self.assertEqual(
                    [call[0] for call in self.transport.calls[before:]], [ROBOTS, TERMS]
                )
                self.assertEqual(
                    [
                        record["record_id"]
                        for record in self.store.records("source_policy")
                    ],
                    policy_ids,
                )
        self.assertEqual(self.store.read_blob(accepted["terms"]["raw"]), original)

    def test_complete_visible_fallback_is_fingerprinted(self):
        self.hunter._begin()
        accepted = self.hunter._permissions()["terms"]
        self.assertEqual(accepted["policy_content_source"], "full_visible")
        self.transport.overrides[TERMS] = {
            "status": 200,
            "headers": {},
            "body": b"<html><body><p>" + TERMS_BODY + b"</p></body></html>",
        }
        self.hunter._begin()
        current = self.hunter._permissions()["terms"]
        self.assertEqual(
            current["policy_content_sha256"], accepted["policy_content_sha256"]
        )
        self.transport.overrides[TERMS]["body"] += b"<p>No automated use.</p>"
        self.hunter._begin()
        with self.assertRaisesRegex(SourceError, "terms content changed"):
            self.hunter._permissions()

    def test_missing_script_only_or_incomplete_legal_content_fails_closed(self):
        for body in (
            b"",
            b"<main></main><footer>" + TERMS_BODY + b"</footer>",
            b"<script>" + TERMS_BODY + b"</script>",
            b"<main><script>document.write(" + TERMS_BODY + b")</script></main>",
            b"<main><style>" + TERMS_BODY + b"</style></main>",
            b"<main><noscript>" + TERMS_BODY + b"</noscript></main>",
            b"<main><p>" + TERMS_BODY + b"</p>",
            b"<main>" + TERMS_BODY + b"</main><main>More terms</main>",
            b"<main>" + TERMS_BODY + b"<noscript>Unclosed</main>",
            b"<main>" + TERMS_BODY + b"<script>Unclosed</main>",
        ):
            with self.subTest(body=body):
                self.transport.overrides[TERMS] = {
                    "status": 200,
                    "headers": {},
                    "body": body,
                }
                with self.assertRaises(SourceError):
                    self.hunter.acquire_alpha()
                self.assertEqual(self.store.records("source_policy"), [])
                self.assertEqual(self.store.records("dataset"), [])

    def test_main_legal_notices_and_document_base_are_substantive(self):
        original = (
            b'<html><head><base href="https://www.bankofcanada.ca/legal/"></head>'
            b"<body><main><p>"
            + TERMS_BODY
            + b"</p><header>Restrictions apply.</header>"
            b'<aside><a href="rights">Read all restrictions</a></aside>'
            b"</main></body></html>"
        )
        self.transport.overrides[TERMS] = {
            "status": 200,
            "headers": {},
            "body": original,
        }
        self.hunter._begin()
        self.hunter._permissions()
        for changed in (
            original.replace(b"Restrictions apply.", b"Research is prohibited."),
            original.replace(b"/legal/", b"/new-legal/"),
            original.replace(b'href="rights"', b'href="rights-v2"'),
        ):
            with self.subTest(changed=changed):
                self.transport.overrides[TERMS]["body"] = changed
                self.hunter._begin()
                with self.assertRaisesRegex(SourceError, "terms content changed"):
                    self.hunter._permissions()

    def test_character_references_whitespace_and_inline_markup_are_cosmetic(self):
        original = (
            b"<main><p>" + TERMS_BODY + b" Review rights &amp; limits.</p></main>"
        )
        self.transport.overrides[TERMS] = {
            "status": 200,
            "headers": {},
            "body": original,
        }
        self.hunter._begin()
        accepted = self.hunter._permissions()["terms"]
        self.transport.overrides[TERMS]["body"] = (
            original.replace(b"Bank of Canada", b"Bank\n of <b>Canada</b>")
            .replace(b"&amp;", b"&#38;")
            .replace(b" rights ", b"\n rights\t")
        )
        self.hunter._begin()
        current = self.hunter._permissions()["terms"]
        self.assertEqual(
            current["policy_content_sha256"], accepted["policy_content_sha256"]
        )

    def test_malformed_html_cannot_trim_changed_legal_text(self):
        original = b"<main><p>" + TERMS_BODY + b"</p></main>"
        self.transport.overrides[TERMS] = {
            "status": 200,
            "headers": {},
            "body": original,
        }
        self.hunter._begin()
        self.hunter._permissions()
        for suffix in (
            b'<p title="unfinished>No automated research.</p></main>',
            b"<!-- No automated research.</main>",
            b'<p title=">">No automated research.</p></main>',
            b"<script/>No automated research.</main>",
        ):
            with self.subTest(suffix=suffix):
                self.transport.overrides[TERMS]["body"] = original[:-7] + suffix
                self.hunter._begin()
                with self.assertRaises(SourceError):
                    self.hunter._permissions()

    def test_no_private_hosts_credentials_http_or_cross_origin_redirect(self):
        for url in (
            "http://www.bankofcanada.ca/",
            "https://127.0.0.1/",
            "https://localhost/",
            "https://www.bankofcanada.ca.evil.example/",
            "https://user@www.bankofcanada.ca/",
            "https://www.bankofcanada.ca:444/",
            "https://www.tradingview.com/",
        ):
            with self.subTest(url=url), self.assertRaises(SourceError):
                self.hunter._safe_url(url)
        self.transport.overrides[ROBOTS] = {
            "status": 302,
            "headers": {"location": "https://127.0.0.1/robots.txt"},
            "body": b"",
        }
        with self.assertRaises(SourceError):
            self.hunter.discover("FX")
        self.assertEqual(len(self.transport.calls), 1)

    def test_transport_hidden_redirect_is_rejected(self):
        self.transport.overrides[ROBOTS] = {
            "status": 200,
            "headers": {},
            "body": POLICY,
            "url": "https://localhost/",
        }
        with self.assertRaises(SourceError):
            self.hunter.discover("FX")

    def test_dns_nonpublic_is_rejected_before_connection(self):
        with (
            patch(
                "siqe_quest.sources.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
            ),
            patch("siqe_quest.sources._PinnedHTTPS") as conn,
        ):
            with self.assertRaises(SourceError):
                _network_transport(ROBOTS, {}, 1, 1000)
            conn.assert_not_called()

    def test_nonfinite_nonpositive_weekend_duplicate_order_and_units_rejected(self):
        baseline = fixture_payload()
        evidence = {"raw": {"sha256": "fixture"}, "retrieved_at": NOW}
        cases = []
        for invalid in ("NaN", "Infinity", "0", "-1"):
            item = copy.deepcopy(baseline)
            item["observations"][0][SERIES]["v"] = invalid
            cases.append(item)
        for day in ("2023-01-01", "2023-01-02", "2022-12-30"):
            item = copy.deepcopy(baseline)
            item["observations"][1]["d"] = day
            cases.append(item)
        item = copy.deepcopy(baseline)
        item["seriesDetail"][SERIES]["label"] = "CAD/USD"
        cases.append(item)
        item = copy.deepcopy(baseline)
        item["seriesDetail"][SERIES]["description"] = "unknown units"
        cases.append(item)
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(SourceError):
                self.hunter._normalize(payload, evidence, enforce_coverage=False)

    def test_actual_official_description_and_unit_direction(self):
        payload = fixture_payload()
        detail = payload["seriesDetail"][SERIES]
        detail["description"] = (
            "Daily average exchange rate of the US dollar in Canadian dollars."
        )
        detail["metadata"] = {"unit": "Canadian dollars per US dollar"}
        evidence = {"raw": {"sha256": "fixture"}, "retrieved_at": NOW}
        self.assertEqual(
            len(self.hunter._normalize(payload, evidence, enforce_coverage=False)), 3
        )
        detail["metadata"]["unit"] = "US dollars per Canadian dollar"
        with self.assertRaises(SourceError):
            self.hunter._normalize(payload, evidence, enforce_coverage=False)

    def test_unregistered_publisher_cannot_be_marked_validated(self):
        with self.assertRaises(SourceError):
            self.hunter.validate(
                {
                    "url": DOCS,
                    "legal_publisher": "Bank of Canada",
                    "source_id": "invented",
                    "version": "invented",
                }
            )
        self.assertEqual(self.transport.calls, [])

    def test_insufficient_three_year_data_is_not_usable(self):
        evidence = {"raw": {"sha256": "fixture"}, "retrieved_at": NOW}
        with self.assertRaises(SourceError):
            self.hunter._normalize(fixture_payload(), evidence)

    def test_no_fill_of_missing_days(self):
        payload = fixture_payload()
        payload["observations"].pop(1)
        evidence = {"raw": {"sha256": "fixture"}, "retrieved_at": NOW}
        rows = self.hunter._normalize(payload, evidence, enforce_coverage=False)
        self.assertEqual([r["date"] for r in rows], ["2023-01-02", "2023-01-04"])

    def test_byte_and_request_caps(self):
        self.hunter._begin(1)
        self.hunter._request(ROBOTS, bootstrap=True)
        with self.assertRaises(SourceError):
            self.hunter._request(ROBOTS, bootstrap=True)
        self.transport.overrides[ROBOTS] = {
            "status": 200,
            "headers": {},
            "body": b"x" * 2_000_001,
        }
        self.hunter._begin()
        with self.assertRaises(SourceError):
            self.hunter._request(ROBOTS, bootstrap=True)

    def test_freshness_changed_unchanged_and_failed_are_bounded(self):
        data = self.hunter.acquire_alpha()
        before = len(self.transport.calls)
        result = self.hunter.check_updates()
        self.assertEqual(result["status"], "UNCHANGED")
        self.assertLessEqual(len(self.transport.calls) - before, 4)
        self.assertLessEqual(result["request_count"], 4)
        self.transport.payload["observations"][-1][SERIES]["v"] = "1.42"
        result = self.hunter.check_updates()
        self.assertTrue(result["changed"])
        self.assertEqual(
            result["stale_dependencies"][0]["dataset_id"], data["dataset_id"]
        )
        self.assertFalse(result["stale_dependencies"][0]["automatic_promotion"])
        self.transport.overrides[ROBOTS] = OSError("fixture offline")
        result = self.hunter.check_updates()
        self.assertEqual(result["status"], "CHECK_FAILED")
        self.assertIsNone(result["changed"])
        self.assertEqual(result["request_count"], 1)

    def test_304_is_unchanged_without_fabricating_data(self):
        data = self.hunter.acquire_alpha()
        url = data["manifest"]["request_url"]
        self.transport.overrides[url] = {"status": 304, "headers": {}, "body": b""}
        result = self.hunter.check_updates()
        self.assertEqual(result["status"], "UNCHANGED")
        self.assertEqual(self.transport.calls[-1][1]["If-None-Match"], '"fixture"')

    def test_discovery_is_repeatable_without_record_conflict(self):
        first = self.hunter.discover("USD CAD")
        second = self.hunter.discover("USD CAD")
        self.assertEqual(
            [r["source_id"] for r in first], [r["source_id"] for r in second]
        )

    def test_discovered_citation_and_feed_entry_are_retrieved(self):
        paper_url = ORIGIN + "/research/example-paper"
        entry_url = ORIGIN + "/research/feed-entry"
        self.transport.overrides[DOCS] = {
            "status": 200,
            "headers": {},
            "body": (
                '<script src="/valet/static/swagger/swagger-initializer.js"></script>'
                '<a rel="citation" href="/research/example-paper">Paper</a>'
            ).encode(),
        }
        self.transport.overrides[paper_url] = {
            "status": 200,
            "headers": {},
            "body": json.dumps({"citation": entry_url}).encode(),
        }
        self.transport.overrides[ORIGIN + "/valet/fx_rss/FXUSDCAD"] = {
            "status": 200,
            "headers": {},
            "body": b"<rss><channel><item><link>https://www.bankofcanada.ca/research/feed-entry</link></item></channel></rss>",
        }
        self.transport.overrides[entry_url] = {
            "status": 200,
            "headers": {},
            "body": b'<a rel="citation" href="/research/example-paper">Paper</a>',
        }
        candidates = self.hunter.discover("USD CAD")
        urls = [call[0] for call in self.transport.calls]
        self.assertIn(paper_url, urls)
        self.assertIn(entry_url, urls)
        self.assertTrue(
            any(
                source["url"] == paper_url and source["source_type"] == "citation"
                for source in candidates
            )
        )
        self.assertTrue(
            any(
                source["url"] == entry_url and source["source_type"] == "feed_entry"
                for source in candidates
            )
        )
        metadata = self.store.records("discovery_links")
        by_url = {record["value"]["url"]: record["value"] for record in metadata}
        self.assertIn([entry_url, "citation"], by_url[paper_url]["links"])
        self.assertIn(
            [entry_url, "feed_entry"],
            by_url[ORIGIN + "/valet/fx_rss/FXUSDCAD"]["links"],
        )
        self.assertIn([paper_url, "citation"], by_url[entry_url]["links"])
        for record in metadata:
            persisted = json.loads(self.store.read_blob(record["evidence"]))["value"]
            self.assertEqual(persisted, record["value"])
            self.assertTrue(persisted["links"])
            for link in persisted["links"]:
                self.assertIsInstance(link, list)
                self.assertEqual(len(link), 2)
                self.assertTrue(all(isinstance(value, str) for value in link))
        self.assertTrue(
            any(source["source_type"] == "dataset" for source in candidates)
        )
        self.assertLessEqual(len(urls), 16)
        phases = self.store.records("discovery_result")[-1]["value"]["phases"]
        self.assertTrue(all(phase["request_count"] <= 4 for phase in phases))

    def test_document_feed_citation_metadata_are_not_executed(self):
        body = b"""<a rel="citation" href="/research/paper">Paper</a><link type="application/atom+xml" href="/feed/"><meta name="citation_pdf_url" content="/paper.pdf"><a href="https://127.0.0.1/">bad</a>"""
        links = self.hunter._metadata(DOCS, body)
        self.assertIn([ORIGIN + "/research/paper", "citation"], links)
        self.assertIn([ORIGIN + "/feed/", "feed"], links)
        self.assertIn([ORIGIN + "/paper.pdf", "citation"], links)
        self.assertFalse(any("127.0.0.1" in url for url, _ in links))


if __name__ == "__main__":
    unittest.main()

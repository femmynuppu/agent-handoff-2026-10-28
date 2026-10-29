"""Consumer-visible coverage tests; synthetic fixtures are not mission evidence."""

from copy import deepcopy
from tempfile import TemporaryDirectory
import json
import unittest

from siqe_quest.core import Store, canonical_json, digest
from siqe_quest.markets import (
    ALPHA_CELL,
    DIMENSIONS,
    OTHER_ASSET_CLASSES,
    REGIONS,
    SECTORS,
    coverage_matrix,
    record_coverage,
)


class CoverageCatalogTests(unittest.TestCase):
    def test_original_taxonomy_and_dimensions_are_complete(self):
        matrix = coverage_matrix()
        self.assertEqual(
            matrix["catalog"]["regions"],
            [
                "North America",
                "Latin America",
                "Europe",
                "United Kingdom",
                "Middle East",
                "Africa",
                "East Asia",
                "Southeast Asia",
                "South Asia",
                "Australia and Oceania",
            ],
        )
        self.assertEqual(
            matrix["catalog"]["equity_sectors"],
            [
                "Information Technology",
                "Communication Services",
                "Financials",
                "Health Care",
                "Industrials",
                "Consumer Discretionary",
                "Consumer Staples",
                "Energy",
                "Materials",
                "Utilities",
                "Real Estate",
            ],
        )
        self.assertEqual(
            matrix["catalog"]["other_asset_classes"],
            [
                "Equity indices",
                "Government bonds",
                "Corporate bonds",
                "Yield curves",
                "Foreign exchange",
                "Commodity futures",
                "Energy markets",
                "Precious and industrial metals",
                "Agricultural futures",
                "ETF flows",
                "Equity options",
                "Index options",
                "Interest-rate derivatives",
                "Crypto spot",
                "Crypto derivatives",
                "DEX liquidity",
                "Volatility benchmarks",
            ],
        )
        self.assertEqual(len(REGIONS), 10)
        self.assertEqual(len(SECTORS), 11)
        self.assertEqual(len(OTHER_ASSET_CLASSES), 17)
        self.assertEqual(matrix["dimensions"], list(DIMENSIONS))
        self.assertEqual(
            set(DIMENSIONS),
            {
                "region",
                "asset_class",
                "sector",
                "timeframe",
                "research_method",
                "economic_regime",
                "data_provider",
                "evaluation_status",
            },
        )

    def test_sparse_studies_offer_next_quests_without_phantom_completion(self):
        matrix = coverage_matrix()
        self.assertEqual(matrix["representation"], "sparse_study_cells")
        self.assertEqual(len(matrix["cells"]), 10)
        self.assertEqual(len({cell["cell_id"] for cell in matrix["cells"]}), 10)
        self.assertIn(
            "Indonesia × Banks × Daily × Momentum",
            [c["title"] for c in matrix["cells"]],
        )
        for cell in matrix["cells"]:
            self.assertTrue(set(DIMENSIONS).issubset(cell))
            self.assertEqual(cell["evaluation_status"], "NOT_TESTED")
            self.assertEqual(cell["data_status"], "ACCESS_NOT_VALIDATED")
            self.assertEqual(cell["evidence"], [])
            self.assertTrue(cell["next_quest"])
            if cell["asset_class"] != "Equities":
                self.assertIsNone(cell["sector"])
        self.assertEqual(
            matrix["expansion_policy"]["global_coverage_status"], "NOT_TESTED"
        )
        licensed = matrix["provider_access"][1]
        self.assertEqual(licensed["availability"], "UNKNOWN")
        self.assertEqual(licensed["status"], "ACCESS_NOT_VALIDATED")
        self.assertEqual(licensed["probe_evidence"], [])

    def test_each_candidate_owns_unknown_metadata_not_equity_defaults(self):
        matrix = coverage_matrix()
        self.assertEqual(
            {c["region"] for c in matrix["candidate_markets"]}, set(REGIONS)
        )
        for candidate in matrix["candidate_markets"]:
            self.assertFalse(candidate["adapter_installed"])
            self.assertEqual(candidate["status"], "ACCESS_NOT_VALIDATED")
            self.assertTrue(
                all(value is None for value in candidate["metadata"].values())
            )
        matrix["candidate_markets"][0]["metadata"]["currency"] = "TEST_FIXTURE_ONLY"
        self.assertIsNone(matrix["candidate_markets"][1]["metadata"]["currency"])
        self.assertIsNone(
            coverage_matrix()["candidate_markets"][0]["metadata"]["currency"]
        )
        fx = matrix["representative_adapter"]
        self.assertEqual(
            (fx["base_currency"], fx["quote_currency"], fx["units"]),
            ("USD", "CAD", "CAD per USD"),
        )
        self.assertEqual(fx["timezone"], "America/Toronto")
        self.assertIsNone(fx["publication_time"])
        self.assertIsNone(fx["first_available_at"])
        self.assertIsNone(fx["tick_size"])
        self.assertEqual(fx["point_in_time_status"], "UNKNOWN_HISTORICAL_AVAILABILITY")
        self.assertIn("not an exchange session", fx["sessions"])


class CoverageEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)

    def _fixture(
        self,
        *,
        series="FXUSDCAD",
        units="CAD per USD",
        timezone="America/Toronto",
        source_validated=True,
        coverage_count=2,
        raw_value="1.35",
        available_at=None,
        second_day="2024-01-03",
        persist=True,
    ):
        """Small stored source contract fixture, explicitly not financial research."""
        timestamp = "2026-01-01T12:00:00+00:00"
        raw_rows = [
            {"d": "2024-01-02", "FXUSDCAD": {"v": raw_value}},
            {"d": second_day, "FXUSDCAD": {"v": "1.36"}},
        ]
        raw = self.store.put_blob(
            canonical_json({"observations": raw_rows}).encode(), "application/json"
        )
        observations = []
        for row, number in zip(raw_rows, (1.35, 1.36)):
            observations.append(
                {
                    "date": row["d"],
                    "value": number,
                    "event_time": row["d"],
                    "event_time_precision": "date",
                    "publication_time": None,
                    "available_at": available_at,
                    "ingested_at": timestamp,
                    "timezone": "America/Toronto",
                    "source_revision": raw["sha256"],
                    "original_value": row["FXUSDCAD"]["v"],
                    "normalized_value": number,
                    "vintage": raw["sha256"],
                    "complete": True,
                }
            )
        normalized = self.store.put_blob(
            canonical_json(observations).encode(), "application/json"
        )
        validation_raw = self.store.put_blob(
            b"unit fixture validation evidence", "text/plain"
        )
        source = {
            "source_id": "boc:unit-fixture",
            "version": "unit-fixture-version",
            "verification_outcome": "VALIDATED_RESEARCH_ONLY"
            if source_validated
            else "DISCOVERED_NOT_VALIDATED",
            "validation_evidence": {"raw": validation_raw},
            "policy": {"research_only": True},
        }
        dataset_id = digest(
            {
                "series": "FXUSDCAD",
                "raw": raw["sha256"],
                "normalized": normalized["sha256"],
            }
        )
        manifest = {
            "dataset_id": dataset_id,
            "schema_version": 1,
            "source_id": source["source_id"],
            "source_version": source["version"],
            "source": source,
            "series": series,
            "instrument": "USD/CAD",
            "publisher": "Bank of Canada",
            "retrieved_at": timestamp,
            "raw": raw,
            "normalized": normalized,
            "units": units,
            "timezone": timezone,
            "vintage": raw["sha256"],
            "publication_time": None,
            "available_at": None,
            "coverage": {
                "start": "2024-01-02",
                "end": second_day,
                "requested_start": "2024-01-01",
                "requested_end": "2024-12-31",
                "observation_count": coverage_count,
            },
            "limitations": ["Synthetic unit fixture, not genuine research evidence"],
        }
        manifest["manifest_id"] = digest(manifest)
        if persist:
            self.store.record(
                "source", source["source_id"] + ":" + source["version"], source
            )
            self.store.record("source_validation", digest(source), source)
            self.store.record("source_snapshot", manifest["manifest_id"], manifest)
            self.store.record(
                "dataset",
                dataset_id,
                {
                    "dataset_id": dataset_id,
                    "observations": observations,
                    "manifest": manifest,
                },
            )
        return manifest

    def test_checked_manifest_advances_only_matching_data_cell(self):
        baseline = coverage_matrix()
        manifest = self._fixture()
        result = record_coverage(self.store, manifest)
        acquired = [
            c for c in result["cells"] if c["data_status"] == "ACQUIRED_AND_CHECKED"
        ]
        self.assertEqual([cell["cell_id"] for cell in acquired], [ALPHA_CELL])
        self.assertEqual(result["cells"][1:], baseline["cells"][1:])
        self.assertEqual(result["candidate_markets"], baseline["candidate_markets"])
        self.assertEqual(
            result["representative_adapter"], baseline["representative_adapter"]
        )
        self.assertTrue(
            all(c["evaluation_status"] == "NOT_TESTED" for c in result["cells"])
        )
        evidence = acquired[0]["evidence"][0]
        self.assertEqual(evidence["source_version"], manifest["source_version"])
        self.assertEqual(evidence["retrieved_at"], manifest["retrieved_at"])
        self.assertEqual(evidence["vintage"], manifest["vintage"])
        self.assertEqual(evidence["coverage"]["observation_count"], 2)
        self.assertEqual(
            result["provider_access"][0]["status"], "RETRIEVED_FOR_THIS_DATASET"
        )
        self.assertEqual(result["provider_access"][1], baseline["provider_access"][1])
        self.assertEqual(result["expansion_policy"]["end_to_end_status"], "NOT_TESTED")
        self.assertEqual(result["coverage_record"]["kind"], "market_coverage")
        self.assertEqual(len(self.store.records("market_coverage")), 1)
        self.assertEqual(coverage_matrix(), baseline)

    def test_repeated_same_evidence_is_idempotent(self):
        manifest = self._fixture()
        first = record_coverage(self.store, manifest)
        second = record_coverage(self.store, manifest)
        self.assertEqual(
            first["coverage_record"]["record_id"],
            second["coverage_record"]["record_id"],
        )
        self.assertEqual(len(self.store.records("market_coverage")), 1)

    def test_claimed_acquisition_without_existing_manifest_is_rejected(self):
        manifest = self._fixture(persist=False)
        with self.assertRaises(ValueError):
            record_coverage(self.store, manifest)
        self.assertEqual(self.store.records("market_coverage"), [])

    def test_mutated_caller_manifest_cannot_borrow_stored_provenance(self):
        manifest = deepcopy(self._fixture())
        manifest["coverage"]["end"] = "2030-01-01"
        with self.assertRaises(ValueError):
            record_coverage(self.store, manifest)
        self.assertEqual(self.store.records("market_coverage"), [])

    def test_unsupported_or_inconsistent_stored_evidence_never_promotes(self):
        cases = [
            {"series": "FXJPYUSD"},
            {"units": "USD per CAD"},
            {"timezone": "UTC"},
            {"source_validated": False},
            {"coverage_count": 999},
            {"raw_value": "2.00"},
            {"available_at": "2024-01-02T00:00:00Z"},
            {"second_day": "2024-01-02"},
            {"second_day": "2024-01-06"},
        ]
        # Separate stores avoid reusing an immutable fixture source key with
        # intentionally conflicting validation bodies.
        for parameters in cases:
            with self.subTest(parameters=parameters), TemporaryDirectory() as root:
                original_store = self.store
                self.store = Store(root)
                try:
                    manifest = self._fixture(**parameters)
                    with self.assertRaises(ValueError):
                        record_coverage(self.store, manifest)
                    self.assertEqual(self.store.records("market_coverage"), [])
                finally:
                    self.store = original_store

    def test_corrupted_normalized_evidence_cannot_promote(self):
        manifest = self._fixture()
        # Deliberate test corruption of this confined temporary fixture only.
        evidence_path = self.store.path(manifest["normalized"]["path"])
        evidence_path.chmod(0o600)
        evidence_path.write_bytes(b"corrupt unit fixture")
        with self.assertRaises(ValueError):
            record_coverage(self.store, manifest)
        self.assertEqual(self.store.records("market_coverage"), [])

    def test_dataset_record_alone_without_source_snapshot_is_insufficient(self):
        manifest = self._fixture(persist=False)
        observations = json.loads(self.store.read_blob(manifest["normalized"]))
        self.store.record(
            "dataset",
            manifest["dataset_id"],
            {
                "dataset_id": manifest["dataset_id"],
                "observations": observations,
                "manifest": manifest,
            },
        )
        with self.assertRaises(ValueError):
            record_coverage(self.store, manifest)
        self.assertEqual(self.store.records("market_coverage"), [])


if __name__ == "__main__":
    unittest.main()

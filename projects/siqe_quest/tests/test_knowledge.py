"""Consumer-visible knowledge provenance, conflict and historical boundary tests."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from siqe_quest.core import Store, canonical_json, utcnow
from siqe_quest.knowledge import KnowledgeEngine


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.engine = KnowledgeEngine(self.store)
        self.source_text = (
            "Évidence: FX currency rates are indicative.\nNo executable prices.\n"
        )
        self.source = self.store.put_blob(
            self.source_text.encode("utf-8"), "text/plain"
        )

    def experiment(self, passed=True, key="experiment-one"):
        return self.store.record(
            "experiment",
            key,
            {
                "experiment_name": key,
                "specification": {"timing": "next_observation_reference_proxy"},
                "audits": {"temporal": {"passed": passed}},
                "metrics": {"net_return": -0.02},
                "limitations": ["Indicative retrospective reference-rate experiment."],
            },
        )

    def lesson(self, artifact=None):
        artifact = artifact or self.experiment()
        return self.engine.add_lesson(
            "Check delayed reference fills before interpreting FX research.",
            [artifact],
            [
                "Business-daily indicative reference observations",
                "Retrospective fixed SMA20/60",
            ],
            [
                "Same-observation fills invalidate this procedure",
                "Does not prove executable profitability",
            ],
        )

    def test_exact_original_unicode_and_raw_json_span(self):
        quote = "FX currency rates are indicative."
        record = self.engine.extract(quote, self.source, "official-snapshot", "fx")
        value = record["value"]
        span = value["span"]
        self.assertEqual(self.source_text[span["start"] : span["end"]], quote)
        raw = self.store.read_blob(value["evidence"][0])
        self.assertEqual(raw[span["byte_start"] : span["byte_end"]].decode(), quote)
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(), value["evidence"][0]["sha256"]
        )
        self.assertEqual(value["uncertainty"]["truth"], "unassessed")
        self.assertEqual(value["evidence_level"], "source_quote")
        self.assertEqual(
            self.engine.extract(quote, self.source, "official-snapshot", "fx"), record
        )
        raw_json = self.store.put_blob(
            b'{"terms": "Daily average exchange rates"}', "application/json"
        )
        result = self.engine.extract(
            "Daily average exchange rates", raw_json, "boc-json"
        )
        self.assertEqual(result["value"]["excerpt"], "Daily average exchange rates")
        with self.assertRaises(ValueError):
            self.engine.extract(
                "FX rates are tradable", self.source, "unsupported-summary"
            )
        with self.assertRaises(ValueError):
            self.engine.extract(
                "fx currency rates are indicative.",
                self.source,
                "normalization-not-permitted",
            )

    def test_missing_mismatched_and_forged_evidence_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.extract("FX", {}, "source")
        mismatch = dict(self.source, sha256="0" * 64)
        with self.assertRaises(ValueError):
            self.engine.extract("FX", mismatch, "source")
        experiment = self.experiment()
        forged = dict(experiment, value={"passed": True})
        with self.assertRaises(ValueError):
            self.lesson(forged)
        with self.assertRaises(ValueError):
            self.lesson(self.source)
        with self.assertRaises(ValueError):
            self.engine.add_lesson("No applicability", [experiment], [], ["Failure"])
        with self.assertRaises(ValueError):
            self.engine.add_lesson("No failure cases", [experiment], ["Scope"], [])

    def test_tampered_blob_is_rejected_on_extraction_and_retrieval(self):
        self.engine.extract("FX currency", self.source, "source")
        path = self.store.path(self.source["path"])
        path.chmod(0o600)
        path.write_bytes(b"Tampered content")
        with self.assertRaises(ValueError):
            self.engine.extract("Tampered", self.source, "source")
        with self.assertRaises(ValueError):
            self.engine.retrieve("FX")

    def test_lessons_tie_acceptance_conditions_and_failures_to_actual_artifact(self):
        artifact = self.experiment()
        lesson = self.lesson(artifact)
        self.assertEqual(lesson["value"]["artifact_ids"], [artifact["record_id"]])
        self.assertTrue(lesson["value"]["acceptance"]["passed"])
        self.assertEqual(
            lesson["value"]["acceptance"]["checks"][0]["path"], "audits.temporal.passed"
        )
        self.assertEqual(lesson["value"]["evidence_level"], "scoped_procedure")
        self.assertFalse(lesson["value"]["uncertainty"]["independent_replication"])
        self.assertTrue(lesson["value"]["failure_cases"])
        promotion = self.engine.promote(lesson["record_id"], [artifact])
        self.assertEqual(
            promotion["value"]["status"], "accepted_within_conditions_only"
        )
        unrelated = self.experiment(key="unrelated")
        with self.assertRaises(ValueError):
            self.engine.promote(lesson["record_id"], [unrelated])
        no_checks = self.store.record(
            "experiment", "no-checks", {"metrics": {"net_return": 0.2}}
        )
        with self.assertRaises(ValueError):
            self.lesson(no_checks)
        rejected = self.lesson(self.experiment(False, "failed-check"))
        self.assertEqual(rejected["value"]["status"], "rejected_procedure")
        with self.assertRaises(ValueError):
            self.engine.promote(
                rejected["record_id"], [self.experiment(False, "failed-check")]
            )
        self.assertTrue(
            any(
                c["left"] == lesson["record_id"] and c["right"] == rejected["record_id"]
                for c in self.engine.contradictions()
            )
        )
        with self.assertRaisesRegex(ValueError, "contradiction"):
            self.engine.promote(lesson["record_id"], [artifact])

    def test_nested_artifact_is_accepted_but_hash_mentioned_as_text_is_not(self):
        nested = self.store.put_blob(b'{"passed":true}', "application/json")
        self.store.record(
            "experiment", "nested", {"output": nested, "audit": {"passed": True}}
        )
        lesson = self.lesson(nested)
        self.assertTrue(lesson["value"]["acceptance"]["passed"])
        unbound = self.store.put_blob(b'{"a":1}', "application/json")
        self.store.record(
            "experiment",
            "hash-string",
            {"description": unbound["sha256"], "audit": {"passed": True}},
        )
        with self.assertRaises(ValueError):
            self.lesson(unbound)

    def test_conflicts_remain_immutable_and_block_silent_promotion(self):
        positive = self.store.put_blob(b"Rate relation is positive.", "text/plain")
        negative = self.store.put_blob(b"Rate relation is negative.", "text/plain")
        left = self.engine.add_claim(
            "USD/CAD",
            "correlation_sign",
            "positive",
            excerpt="Rate relation is positive.",
            evidence=positive,
            source_id="paper-a",
            conditions=["2023 sample"],
        )
        before = canonical_json(left)
        right = self.engine.add_claim(
            "USD/CAD",
            "correlation_sign",
            "negative",
            excerpt="Rate relation is negative.",
            evidence=negative,
            source_id="paper-b",
            conditions=["2024 sample"],
        )
        conflicts = self.engine.contradictions()
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(
            {conflicts[0]["left"], conflicts[0]["right"]},
            {left["record_id"], right["record_id"]},
        )
        self.assertTrue(conflicts[0]["blocks_promotion"])
        self.assertEqual(
            canonical_json(self.store.get(left["kind"], left["key"])), before
        )
        with self.assertRaisesRegex(ValueError, "contradiction"):
            self.engine.promote(left["record_id"], [self.experiment()])
        hits = self.engine.retrieve("USD CAD correlation")
        claim_hits = [h for h in hits if h["record"]["kind"] == "knowledge_claim"]
        self.assertEqual(len(claim_hits), 2)
        self.assertTrue(
            all(h["contradictions"] and not h["usable_as_current"] for h in claim_hits)
        )
        lesson = self.lesson()
        self.engine.relate(
            lesson["record_id"], "counterexample_to", left["record_id"], [negative]
        )
        with self.assertRaisesRegex(ValueError, "contradiction"):
            self.engine.promote(lesson["record_id"], [self.experiment()])

    def test_decay_revalidation_and_supersession_preserve_history_and_forecasts(self):
        original = self.engine.extract("FX currency", self.source, "source", "fx")
        history_cutoff = utcnow()
        forecast = self.store.record(
            "forecast", "frozen", {"prediction": 1.30, "made_at": history_cutoff}
        )
        before_forecast = canonical_json(forecast)
        self.engine.decay(original["record_id"], "Source requires review")
        current = self.engine.index()
        self.assertEqual(current["concepts"][0]["lifecycle_state"], "stale")
        historical = self.engine.index(as_of=history_cutoff)
        self.assertEqual(historical["concepts"][0]["lifecycle_state"], "active")
        self.assertEqual(historical["lifecycle"], [])
        self.assertEqual(
            self.engine.index(as_of=original["created_at"])["concepts"][0][
                "lifecycle_state"
            ],
            "active",
        )
        with self.assertRaises(ValueError):
            self.engine.revalidate(
                original["record_id"],
                [self.experiment(False, "failed-revalidation")],
                "Failed checks",
            )
        with self.assertRaises(ValueError):
            self.engine.decay(
                original["record_id"], "Predates knowledge", "2000-01-01T00:00:00+00:00"
            )
        self.engine.revalidate(
            original["record_id"],
            [self.experiment()],
            "Recorded audit confirms applicability",
        )
        self.assertEqual(
            self.engine.index()["concepts"][0]["lifecycle_state"], "active"
        )
        revised_source = self.store.put_blob(
            b"FX currency observations are reference only.", "text/plain"
        )
        replacement = self.engine.extract(
            "FX currency observations", revised_source, "source", "fx"
        )
        self.assertEqual(replacement["value"]["version"], 2)
        self.assertEqual(replacement["value"]["previous_id"], original["record_id"])
        self.engine.supersede(
            original["record_id"],
            replacement["record_id"],
            [revised_source],
            utcnow(),
            "New source definition",
        )
        self.assertEqual(
            self.engine.index()["concepts"][0]["lifecycle_state"], "superseded"
        )
        with self.assertRaises(ValueError):
            self.engine.revalidate(
                original["record_id"], [self.experiment()], "Cannot resurrect"
            )
        self.assertEqual(
            canonical_json(self.store.get("forecast", "frozen")), before_forecast
        )
        with self.assertRaises(ValueError):
            self.engine.decay(forecast["record_id"], "Must not rewrite forecast")
        self.assertEqual(self.store.get(original["kind"], original["key"]), original)

    def test_retrieval_graph_export_and_operational_isolation(self):
        self.engine.extract("FX currency", self.source, "official", "fx")
        self.engine.entity(
            "USD/CAD", "instrument", "US dollar Canadian dollar FX", [self.source]
        )
        self.engine.entity(
            "OTC", "market", "Reference foreign exchange market", [self.source]
        )
        self.engine.relate("USD/CAD", "traded_in", "OTC", [self.source])
        self.engine.remember("checkpoint", "Source extraction recorded", [self.source])
        self.lesson()
        hits = self.engine.retrieve("foreign exchange", entity="USD/CAD")
        self.assertTrue(hits)
        self.assertTrue(all(not hit["executable_content"] for hit in hits))
        self.assertTrue(self.engine.retrieve("slippage fees reference"))
        exported = self.engine.export()
        index = json.loads(self.store.read_blob(exported["index"]))
        self.assertEqual(set(index["layers"]), {"L1", "L2", "L3"})
        self.assertTrue(index["lessons"])
        self.assertTrue(index["graph"])
        self.assertTrue(index["scientific_evidence"])
        self.assertEqual(index["operational_memory"][0]["value"]["layer"], "L1")
        graph = json.loads(self.store.read_blob(exported["graph"]))
        self.assertEqual(
            set(graph["ontology"]), {"market", "macro", "strategy", "paper", "error"}
        )
        with TemporaryDirectory() as other:
            empty = KnowledgeEngine(Store(Path(other))).index()
            self.assertEqual(empty["operational_memory"], [])
            self.assertEqual(empty["lessons"], [])
        with self.assertRaises(ValueError):
            self.engine.relate("a", "__import__", "b", [self.source])

    def test_untrusted_instructions_are_only_inert_quoted_data(self):
        marker = Path(self.temp.name) / "should-not-exist"
        instruction = f"__import__('pathlib').Path({str(marker)!r}).touch()"
        reference = self.store.put_blob(instruction.encode(), "text/plain")
        record = self.engine.extract(
            instruction, reference, "untrusted", "instructions"
        )
        self.assertEqual(record["value"]["excerpt"], instruction)
        self.assertTrue(record["value"]["untrusted_content"])
        self.assertTrue(self.engine.retrieve("instructions"))
        self.assertFalse(marker.exists())
        with self.assertRaises(ValueError):
            self.engine.promote(record["record_id"], [self.experiment()])


if __name__ == "__main__":
    unittest.main()

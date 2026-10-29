"""Isolated, evidence-linked scientific memory; retrieved text is always inert data."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
import re
from typing import Any

from .core import Store, canonical_json, digest, utcnow


LAYERS = {
    "L1": "Operational memory: decisions, errors, checkpoints and handoffs",
    "L2": "Semantic concepts, scoped procedural interpretations and counterexamples",
    "L3": "Immutable original sources, datasets, hypotheses, forecasts and experiments",
}
EVIDENCE_LEVELS = {
    "source_quote": "Exact source assertion; not independently verified truth",
    "source_linked": "Attributed graph metadata linked to a source; not an exact extracted quote",
    "artifact_observation": "Observation within a recorded experiment or audit",
    "scoped_procedure": "Procedure supported by explicit recorded checks in stated conditions",
    "independent_replication": "Reserved; not granted by extraction or one experiment",
}
ONTOLOGY = {
    "market": ["instrument", "market", "sector", "company", "fundamental_metric"],
    "macro": ["macro_event", "economic_channel", "potential_market_effect"],
    "strategy": [
        "strategy",
        "indicator",
        "feature",
        "assumption",
        "backtest",
        "result",
    ],
    "paper": ["research_paper", "hypothesis", "method", "evidence", "reproduction"],
    "error": ["error", "root_cause", "corrective_rule", "regression_test"],
}
RELATIONS = {
    "traded_in",
    "in_sector",
    "issued_by",
    "has_metric",
    "affects_channel",
    "may_affect",
    "uses_indicator",
    "uses_feature",
    "assumes",
    "tested_by",
    "produced_result",
    "proposes",
    "uses_method",
    "supported_by",
    "reproduced_by",
    "caused_by",
    "corrected_by",
    "guarded_by",
    "contradicts",
    "counterexample_to",
    "supersedes",
    "related_to",
}
KINDS = (
    "knowledge_concept",
    "knowledge_claim",
    "knowledge_lesson",
    "knowledge_entity",
    "knowledge_relation",
    "knowledge_lifecycle",
    "knowledge_promotion",
    "knowledge_operation",
)
SCIENTIFIC_KINDS = (
    "source",
    "dataset",
    "hypothesis",
    "forecast",
    "strategy",
    "experiment",
    "audit",
    "rejected_research",
)
# Small transparent lexical expansion, not an embedding or a claim of semantic equivalence.
SYNONYMS = {
    "fx": "foreign exchange currency",
    "forex": "foreign exchange currency",
    "sma": "simple moving average",
    "drawdown": "peak trough loss",
    "leakage": "lookahead future temporal",
    "volatility": "variance risk",
    "reproduction": "replication repeat",
    "costs": "fees commission slippage",
}


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")
    return value


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _strings(values: list[str], name: str) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{name} must be a nonempty list")
    return [_text(item, name) for item in values]


def _tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"[\w]+", text.casefold()))
    for token in tuple(tokens):
        tokens.update(SYNONYMS.get(token, "").split())
    return tokens


class KnowledgeEngine:
    """Append-only Store records, with versioned projections instead of in-place updates."""

    def __init__(self, store: Store):
        self.store = store

    def _evidence(self, evidence: dict) -> dict:
        if not isinstance(evidence, dict):
            raise ValueError("evidence must be a blob descriptor or Store record")
        if "record_id" in evidence:
            stored = self.store.get(evidence.get("kind", ""), evidence.get("key", ""))
            if stored is None or canonical_json(stored) != canonical_json(evidence):
                raise ValueError("missing or mismatched evidence record")
            evidence = stored["evidence"]
        if not isinstance(evidence.get("sha256"), str) or not evidence.get("path"):
            raise ValueError("evidence requires a content hash and confined path")
        raw = self.store.read_blob(evidence)
        if hashlib.sha256(raw).hexdigest() != evidence["sha256"]:
            raise ValueError("evidence hash mismatch")
        return dict(evidence)

    def _verify_list(self, evidence: list[dict]) -> list[dict]:
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("at least one supporting evidence artifact is required")
        return [self._evidence(item) for item in evidence]

    def _append(self, kind: str, identity: str, value: dict) -> dict:
        self.store.authorize("knowledge")
        previous = [
            r
            for r in self.store.records(kind)
            if r["value"].get("identity") == identity
        ]
        body = dict(value, identity=identity)
        # Repeating the same scientific input is idempotent, not another version.
        for record in previous:
            old = {
                k: v
                for k, v in record["value"].items()
                if k not in {"version", "previous_id"}
            }
            if canonical_json(old) == canonical_json(body):
                return record
        body["version"] = len(previous) + 1
        body["previous_id"] = previous[-1]["record_id"] if previous else None
        return self.store.record(kind, digest(body), body)

    def _find(self, record_id: str) -> dict:
        for kind in KINDS:
            for record in self.store.records(kind):
                if record["record_id"] == record_id:
                    return record
        raise ValueError("unknown knowledge record")

    def _check_record(self, record: dict) -> None:
        value = record["value"]
        for evidence in value.get("evidence", []):
            self._evidence(evidence)
        span = value.get("span")
        if span:
            source = self.store.read_blob(value["evidence"][0]).decode("utf-8")
            if source[span["start"] : span["end"]] != value["excerpt"]:
                raise ValueError("source span no longer matches evidence")

    def extract(
        self,
        text: str,
        evidence: dict,
        source_id: str,
        concept: str = "financial_research",
    ) -> dict:
        """Quote an exact UTF-8 substring. Offsets refer to original, unnormalized text."""
        _text(text, "excerpt")
        _text(source_id, "source_id")
        _text(concept, "concept")
        reference = self._evidence(evidence)
        original = self.store.read_blob(reference).decode("utf-8")
        start = original.find(text)
        if start < 0:
            raise ValueError("excerpt is not an exact original source span")
        end = start + len(text)
        return self._append(
            "knowledge_concept",
            f"{source_id}:{concept}",
            {
                "layer": "L2",
                "concept": concept,
                "source_id": source_id,
                "excerpt": text,
                "span": {
                    "start": start,
                    "end": end,
                    "unit": "unicode_codepoint",
                    "byte_start": len(original[:start].encode("utf-8")),
                    "byte_end": len(original[:end].encode("utf-8")),
                    "occurrence": "first_exact",
                },
                "evidence": [reference],
                "evidence_level": "source_quote",
                "uncertainty": {"truth": "unassessed", "confidence": None},
                "status": "quoted_not_promoted",
                "untrusted_content": True,
            },
        )

    def add_claim(
        self,
        subject: str,
        predicate: str,
        object_id: str,
        *,
        excerpt: str,
        evidence: dict,
        source_id: str,
        conditions: list[str],
        uncertainty: float = 1.0,
    ) -> dict:
        """Index an attributed assertion; different objects conservatively flag conflict."""
        for name, value in (
            ("subject", subject),
            ("predicate", predicate),
            ("object", object_id),
        ):
            _text(value, name)
        if (
            isinstance(uncertainty, bool)
            or not isinstance(uncertainty, (int, float))
            or not math.isfinite(uncertainty)
            or not 0 <= uncertainty <= 1
        ):
            raise ValueError("uncertainty must be finite in [0, 1]")
        scope = _strings(conditions, "conditions")
        quote = self.extract(excerpt, evidence, source_id, subject)
        return self._append(
            "knowledge_claim",
            f"{subject}:{predicate}",
            {
                "layer": "L2",
                "subject": subject,
                "predicate": predicate,
                "object_id": object_id,
                "statement": excerpt,
                "quote_id": quote["record_id"],
                "source_id": source_id,
                "conditions": scope,
                "uncertainty": float(uncertainty),
                "evidence_level": "source_quote",
                "evidence": quote["value"]["evidence"],
                "status": "attributed_not_promoted",
            },
        )

    def _artifacts(self, evidence: list[dict]) -> tuple[list[dict], list[dict]]:
        references = self._verify_list(evidence)
        # Hash membership in an existing L3 record is necessary; a random blob is not an experiment.
        matches = []
        matched_hashes = set()
        for kind in ("experiment", "audit"):
            for record in self.store.records(kind):
                self._evidence(record)
                valid_hashes = {record["evidence"]["sha256"]}

                def visit(value: Any) -> None:
                    if isinstance(value, dict):
                        if "sha256" in value and "path" in value:
                            valid_hashes.add(self._evidence(value)["sha256"])
                        else:
                            for item in value.values():
                                visit(item)
                    elif isinstance(value, list):
                        for item in value:
                            visit(item)

                visit(record["value"])
                supported = valid_hashes.intersection(r["sha256"] for r in references)
                if supported:
                    matches.append(record)
                    matched_hashes.update(supported)
        if not matches or any(r["sha256"] not in matched_hashes for r in references):
            raise ValueError(
                "lesson evidence must trace to existing experiment/audit artifacts"
            )
        return references, matches

    @staticmethod
    def _checks(artifacts: list[dict]) -> list[dict]:
        checks = []

        def visit(value: Any, path: str, artifact_id: str) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    location = f"{path}.{key}" if path else key
                    if key in {"passed", "accepted"} and type(item) is bool:
                        checks.append(
                            {
                                "artifact_id": artifact_id,
                                "path": location,
                                "passed": item,
                            }
                        )
                    else:
                        visit(item, location, artifact_id)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    visit(item, f"{path}[{index}]", artifact_id)

        for artifact in artifacts:
            visit(artifact["value"], "", artifact["record_id"])
        return checks

    def add_lesson(
        self,
        statement: str,
        evidence: list[dict],
        conditions: list[str],
        counterexamples: list[str],
    ) -> dict:
        """Store a scoped procedural interpretation, not a proof of strategy performance."""
        _text(statement, "statement")
        scope = _strings(conditions, "conditions")
        failures = _strings(counterexamples, "counterexamples")
        references, artifacts = self._artifacts(evidence)
        checks = self._checks(artifacts)
        if not checks:
            raise ValueError(
                "procedural lesson requires explicit passed/accepted experiment or audit checks"
            )
        accepted = all(item["passed"] for item in checks)
        return self._append(
            "knowledge_lesson",
            statement,
            {
                "layer": "L2",
                "statement": statement,
                "conditions": scope,
                "counterexamples": failures,
                "failure_cases": failures,
                "evidence": references,
                "artifact_ids": [r["record_id"] for r in artifacts],
                "acceptance": {
                    "rule": "all recorded explicit checks pass",
                    "checks": checks,
                    "passed": accepted,
                },
                "evidence_level": "scoped_procedure"
                if accepted
                else "artifact_observation",
                "status": "scoped_interpretation" if accepted else "rejected_procedure",
                "uncertainty": {
                    "generalization": "unmeasured",
                    "independent_replication": False,
                },
                "limitations": [
                    "Statement is a researcher interpretation, not an exact source quote.",
                    "Retrospective locked research is not prospective preregistration.",
                    "Passing artifact checks does not establish skill mastery, live profitability or independent replication.",
                ],
            },
        )

    def entity(
        self, entity_id: str, entity_type: str, label: str, evidence: list[dict]
    ) -> dict:
        if entity_type not in {kind for group in ONTOLOGY.values() for kind in group}:
            raise ValueError("unknown ontology entity type")
        return self._append(
            "knowledge_entity",
            _text(entity_id, "entity_id"),
            {
                "layer": "L2",
                "entity_id": entity_id,
                "entity_type": entity_type,
                "label": _text(label, "label"),
                "evidence": self._verify_list(evidence),
                "evidence_level": "source_linked",
                "status": "attributed_not_promoted",
            },
        )

    def relate(
        self, subject: str, predicate: str, object_id: str, evidence: list[dict]
    ) -> dict:
        _text(subject, "subject")
        _text(object_id, "object_id")
        if predicate not in RELATIONS:
            raise ValueError("unsupported graph relation")
        return self._append(
            "knowledge_relation",
            f"{subject}:{predicate}:{object_id}",
            {
                "layer": "L2",
                "subject": subject,
                "predicate": predicate,
                "object_id": object_id,
                "evidence": self._verify_list(evidence),
                "evidence_level": "source_linked",
                "status": "attributed_relation_not_causal_proof",
            },
        )

    def remember(self, category: str, text: str, evidence: list[dict]) -> dict:
        if category not in {
            "research_state",
            "decision",
            "error",
            "checkpoint",
            "handoff",
            "convention",
        }:
            raise ValueError("unsupported operational memory category")
        return self._append(
            "knowledge_operation",
            f"{category}:{text}",
            {
                "layer": "L1",
                "category": category,
                "text": _text(text, "text"),
                "evidence": self._verify_list(evidence),
                "status": "operational_not_scientific",
            },
        )

    def contradictions(self, as_of: str | None = None) -> list[dict]:
        cutoff = _time(as_of) if as_of else None
        claims = [
            r
            for r in self.store.records("knowledge_claim")
            if not cutoff or _time(r["created_at"]) <= cutoff
        ]
        conflicts = []
        for index, left in enumerate(claims):
            self._check_record(left)
            a = left["value"]
            for right in claims[index + 1 :]:
                self._check_record(right)
                b = right["value"]
                if (a["subject"], a["predicate"]) == (
                    b["subject"],
                    b["predicate"],
                ) and a["object_id"] != b["object_id"]:
                    conflicts.append(
                        {
                            "left": left["record_id"],
                            "right": right["record_id"],
                            "subject": a["subject"],
                            "predicate": a["predicate"],
                            "reason": "incompatible indexed objects; compare definitions and applicability before resolution",
                            "source_ids": [a["source_id"], b["source_id"]],
                            "conditions": [a["conditions"], b["conditions"]],
                            "status": "unresolved",
                            "blocks_promotion": True,
                        }
                    )
        lessons = [
            r
            for r in self.store.records("knowledge_lesson")
            if not cutoff or _time(r["created_at"]) <= cutoff
        ]
        for index, left in enumerate(lessons):
            self._check_record(left)
            for right in lessons[index + 1 :]:
                self._check_record(right)
                a, b = left["value"], right["value"]
                if (
                    a["identity"] == b["identity"]
                    and a["acceptance"]["passed"] != b["acceptance"]["passed"]
                ):
                    conflicts.append(
                        {
                            "left": left["record_id"],
                            "right": right["record_id"],
                            "reason": "same procedural interpretation has accepted and rejected artifact findings",
                            "conditions": [a["conditions"], b["conditions"]],
                            "status": "unresolved",
                            "blocks_promotion": True,
                        }
                    )
        for relation in self.store.records("knowledge_relation"):
            if cutoff and _time(relation["created_at"]) > cutoff:
                continue
            if relation["value"]["predicate"] in {"contradicts", "counterexample_to"}:
                self._check_record(relation)
                conflicts.append(
                    {
                        "left": relation["value"]["subject"],
                        "right": relation["value"]["object_id"],
                        "relation_id": relation["record_id"],
                        "reason": relation["value"]["predicate"],
                        "status": "unresolved",
                        "blocks_promotion": True,
                    }
                )
        return conflicts

    def promote(self, record_id: str, evidence: list[dict]) -> dict:
        record = self._find(record_id)
        self._check_record(record)
        if any(
            record_id in {c["left"], c["right"]}
            or record["value"].get("subject") in {c["left"], c["right"]}
            for c in self.contradictions()
        ):
            raise ValueError("unresolved contradiction blocks promotion")
        if self._state(record_id, None) != "active":
            raise ValueError("inactive or superseded knowledge cannot be promoted")
        references, artifacts = self._artifacts(evidence)
        if (
            record["kind"] != "knowledge_lesson"
            or not record["value"]["acceptance"]["passed"]
        ):
            raise ValueError(
                "only an artifact-supported accepted procedural lesson can be promoted"
            )
        if not set(record["value"]["artifact_ids"]).issubset(
            {r["record_id"] for r in artifacts}
        ):
            raise ValueError(
                "promotion must retain original lesson artifact provenance"
            )
        checks = self._checks(artifacts)
        if not checks or not all(check["passed"] for check in checks):
            raise ValueError("failed or absent checks block procedural promotion")
        return self._append(
            "knowledge_promotion",
            record_id,
            {
                "layer": "L2",
                "target_id": record_id,
                "evidence": references,
                "evidence_level": "scoped_procedure",
                "status": "accepted_within_conditions_only",
                "conditions": record["value"]["conditions"],
                "independent_replication": False,
            },
        )

    def _lifecycle(
        self,
        record_id: str,
        action: str,
        reason: str,
        effective_at: str | None,
        evidence: list[dict],
        replacement_id: str | None = None,
    ) -> dict:
        target = self._find(record_id)
        if target["kind"] not in {
            "knowledge_concept",
            "knowledge_claim",
            "knowledge_lesson",
            "knowledge_entity",
        }:
            raise ValueError(
                "lifecycle updates apply only to semantic/procedural records, never forecasts"
            )
        self._check_record(target)
        when = effective_at or utcnow()
        if _time(when) < _time(target["created_at"]):
            raise ValueError("lifecycle date cannot precede original knowledge")
        return self._append(
            "knowledge_lifecycle",
            record_id,
            {
                "layer": "L2",
                "target_id": record_id,
                "action": action,
                "reason": _text(reason, "reason"),
                "effective_at": when,
                "replacement_id": replacement_id,
                "evidence": self._verify_list(evidence),
                "evidence_level": "artifact_observation"
                if action == "revalidated"
                else "source_linked",
            },
        )

    def decay(
        self, record_id: str, reason: str, effective_at: str | None = None
    ) -> dict:
        target = self._find(record_id)
        return self._lifecycle(
            record_id, "stale", reason, effective_at, target["value"]["evidence"]
        )

    def revalidate(
        self,
        record_id: str,
        evidence: list[dict],
        reason: str,
        effective_at: str | None = None,
    ) -> dict:
        _, artifacts = self._artifacts(evidence)
        checks = self._checks(artifacts)
        if not checks or not all(check["passed"] for check in checks):
            raise ValueError(
                "revalidation requires explicit successful artifact checks"
            )
        if self._state(record_id, None) == "superseded":
            raise ValueError("supersession is permanent; create a new version instead")
        return self._lifecycle(record_id, "revalidated", reason, effective_at, evidence)

    def supersede(
        self,
        old_id: str,
        new_id: str,
        evidence: list[dict],
        effective_at: str,
        reason: str,
    ) -> dict:
        old, new = self._find(old_id), self._find(new_id)
        self._check_record(new)
        if (
            old_id == new_id
            or old["kind"] != new["kind"]
            or old["value"]["identity"] != new["value"]["identity"]
        ):
            raise ValueError(
                "supersession requires a distinct version of the same concept/claim/lesson/entity"
            )
        if _time(effective_at) < _time(new["created_at"]):
            raise ValueError("replacement must exist at supersession time")
        if new["value"]["version"] <= old["value"]["version"]:
            raise ValueError("supersession must advance the immutable version")
        if self._state(old_id, None) == "superseded":
            raise ValueError("already superseded")
        return self._lifecycle(
            old_id, "superseded", reason, effective_at, evidence, new_id
        )

    def _state(self, record_id: str, as_of: str | None) -> str:
        cutoff = _time(as_of or utcnow())
        state = "active"
        events = [
            r
            for r in self.store.records("knowledge_lifecycle")
            if r["value"]["target_id"] == record_id
            and _time(r["created_at"]) <= cutoff
            and _time(r["value"]["effective_at"]) <= cutoff
        ]
        events.sort(
            key=lambda r: (
                _time(r["value"]["effective_at"]),
                _time(r["created_at"]),
                r["record_id"],
            )
        )
        for event in events:
            self._check_record(event)
            if state != "superseded":
                state = (
                    "active"
                    if event["value"]["action"] == "revalidated"
                    else event["value"]["action"]
                )
        return state

    def index(self, as_of: str | None = None) -> dict:
        cutoff = _time(as_of) if as_of else None
        records = {}
        for kind in KINDS:
            items = []
            for record in self.store.records(kind):
                if cutoff and _time(record["created_at"]) > cutoff:
                    continue
                self._check_record(record)
                items.append(
                    dict(
                        record, lifecycle_state=self._state(record["record_id"], as_of)
                    )
                )
            records[kind.removeprefix("knowledge_")] = items
        scientific = []
        for kind in SCIENTIFIC_KINDS:
            for record in self.store.records(kind):
                if not cutoff or _time(record["created_at"]) <= cutoff:
                    scientific.append(
                        {
                            "record_id": record["record_id"],
                            "kind": kind,
                            "created_at": record["created_at"],
                            "evidence": self._evidence(record),
                        }
                    )
        return {
            "schema_version": 1,
            "as_of": as_of,
            "layers": LAYERS,
            "evidence_levels": EVIDENCE_LEVELS,
            "ontology": ONTOLOGY,
            "concepts": records["concept"],
            "claims": records["claim"],
            "lessons": records["lesson"],
            "entities": records["entity"],
            "graph": records["relation"],
            "operational_memory": records["operation"],
            "lifecycle": records["lifecycle"],
            "promotions": records["promotion"],
            "scientific_evidence": scientific,
            "contradictions": self.contradictions(as_of),
            "limitations": [
                "Lexical retrieval with transparent synonyms, not learned embeddings.",
                "No automatic causal inference, contradiction resolution or historical forecast rewriting.",
            ],
        }

    def retrieve(
        self,
        query: str,
        entity: str | None = None,
        limit: int = 10,
        as_of: str | None = None,
    ) -> list[dict]:
        _text(query, "query")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer in [1, 100]")
        projection = self.index(as_of)
        wanted = _tokens(query)
        candidates = []
        for group in ("concepts", "claims", "lessons", "entities", "graph"):
            for record in projection[group]:
                value = record["value"]
                if entity and entity not in {
                    value.get("subject"),
                    value.get("object_id"),
                    value.get("entity_id"),
                    value.get("concept"),
                    value.get("source_id"),
                }:
                    continue
                searchable = " ".join(
                    str(value.get(k, ""))
                    for k in (
                        "concept",
                        "excerpt",
                        "statement",
                        "subject",
                        "predicate",
                        "object_id",
                        "label",
                        "entity_type",
                        "conditions",
                        "counterexamples",
                    )
                )
                overlap = wanted & _tokens(searchable)
                if not overlap:
                    continue
                conflicts = [
                    c
                    for c in projection["contradictions"]
                    if record["record_id"] in {c["left"], c["right"]}
                    or value.get("subject") in {c["left"], c["right"]}
                ]
                candidates.append(
                    {
                        "record": record,
                        "score": len(overlap) / len(wanted),
                        "matched_terms": sorted(overlap),
                        "contradictions": conflicts,
                        "usable_as_current": record["lifecycle_state"] == "active"
                        and not conflicts,
                        "evidence_level": value.get("evidence_level"),
                        "executable_content": False,
                    }
                )
        candidates.sort(key=lambda item: (-item["score"], item["record"]["record_id"]))
        return candidates[:limit]

    def export(self) -> dict:
        """Return immutable content-addressed JSON exports; never overwrite evidence."""
        index = self.index()
        return {
            name: self.store.put_blob(
                canonical_json(value).encode("utf-8"), "application/json"
            )
            for name, value in (
                ("index", index),
                ("lessons", index["lessons"]),
                (
                    "graph",
                    {
                        "entities": index["entities"],
                        "relations": index["graph"],
                        "ontology": ONTOLOGY,
                    },
                ),
            )
        }

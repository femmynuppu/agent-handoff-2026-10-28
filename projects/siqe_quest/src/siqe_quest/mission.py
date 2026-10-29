"""Finite, evidence-bound QUEST ALPHA orchestration and offline reproduction.

The immutable experiment is the numerical unit of identity. Learning exposures,
operator controls and worker delivery are separate, dated operational evidence.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import zipfile

from .core import Store, canonical_json, digest, utcnow
from .events import Event, EventQueue
from .knowledge import KnowledgeEngine
from .learning import Curriculum
from .research import run_alpha
from .runtime import Worker
from .sources import SourceHunter
from .tradingview import parity_report, render_pine

GAP = "USD CAD FXUSDCAD daily average exchange rate 2023 2024 2025"


def _ref(record: dict) -> dict:
    return {key: record[key] for key in ("kind", "key", "record_id", "evidence")}


def numeric_content(result: dict) -> dict:
    """Exclude dated learning/operational evidence, not any numerical output."""
    return {
        key: result[key]
        for key in (
            "dataset_id",
            "spec",
            "segments",
            "audits",
            "outcomes",
            "scientific_claim",
        )
    }


def _software(store: Store) -> dict:
    files = {}
    for path in sorted(Path(__file__).parent.glob("*.py")):
        files[path.name] = store.put_blob(path.read_bytes(), "text/x-python")
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "files": files,
        "sha256": digest({name: value["sha256"] for name, value in files.items()}),
    }


def _discovery(store: Store, dataset: dict) -> list[dict]:
    source = dataset["manifest"]["source"]
    matches = []
    for record in store.records("discovery_result"):
        value = record["value"]
        if value.get("status") == "COMPLETE_BOUNDED_SCOPE" and any(
            item.get("source_id") == source["source_id"]
            and item.get("version") == source["version"]
            for item in value.get("sources", [])
        ):
            matches.append(_ref(record))
    return matches


def _dataset(store: Store, refresh: bool) -> dict:
    records = store.records("dataset")
    if records and not refresh:
        dataset = records[-1]["value"]
        source = dataset["manifest"]["source"]
        if source.get("verification_outcome") != "VALIDATED_RESEARCH_ONLY":
            raise ValueError("retained dataset lacks validated source evidence")
        if not any(r["value"] == source for r in store.records("source_validation")):
            raise ValueError("retained dataset source validation is not registered")
        store.read_blob(source["evidence"])
        store.read_blob(dataset["manifest"]["raw"])
        normalized = store.read_blob(dataset["manifest"]["normalized"])
        if normalized != canonical_json(dataset["observations"]).encode():
            raise ValueError("dataset differs from normalized evidence")
        return dataset
    # A committed acquisition is reused even if the process died before its
    # mission checkpoint. No network refresh is silently retried after that point.
    if refresh:
        manifested = {
            r["value"]["dataset"]["dataset_id"]
            for r in store.records("mission")
            if r["value"].get("status") == "COMPLETED"
        }
        for acquisition in reversed(store.records("mission_acquisition")):
            dataset_id = acquisition["value"]["dataset_id"]
            if dataset_id not in manifested:
                recovered = store.get("dataset", dataset_id)
                if recovered is not None:
                    return recovered["value"]
    intents = store.records("mission_acquisition_intent")
    unfinished = next(
        (
            r
            for r in reversed(intents)
            if store.get("mission_acquisition", r["key"]) is None
        ),
        None,
    )
    if unfinished:
        intent = unfinished
        before = set(intent["value"]["existing_datasets"])
        acquired = [r for r in records if r["record_id"] not in before]
        if acquired:
            dataset = acquired[-1]["value"]
            store.record(
                "mission_acquisition",
                intent["key"],
                {"dataset_id": dataset["dataset_id"], "recovered": True},
            )
            return dataset
    else:
        value = {
            "started_at": utcnow(),
            "refresh": refresh,
            "existing_datasets": [r["record_id"] for r in records],
        }
        intent = store.record("mission_acquisition_intent", digest(value), value)
    hunter = SourceHunter(store)
    discovery_key = intent["key"] + ":discovery"
    if store.get("mission_stage", discovery_key) is None:
        # Do not trust a preloaded URL registry as proof of catalog traversal.
        recovered_discovery = [
            r
            for r in store.records("discovery_result")
            if r["created_at"] >= intent["created_at"]
            and r["value"].get("status") == "COMPLETE_BOUNDED_SCOPE"
        ]
        if not recovered_discovery:
            hunter.discover(GAP)
        store.record(
            "mission_stage",
            discovery_key,
            {"discovery": [_ref(r) for r in store.records("discovery_result")[-1:]]},
        )
    dataset = hunter.acquire_alpha()
    store.record(
        "mission_acquisition",
        intent["key"],
        {"dataset_id": dataset["dataset_id"], "recovered": False},
    )
    return dataset


def _artifact(store: Store, relative: str, content: bytes, media_type: str) -> dict:
    blob = store.put_blob(content, media_type)
    path = store.path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)  # Regenerable view; the versioned blob is immutable.
    return {**blob, "artifact_path": relative}


def _reference_source(store: Store, dataset: dict, result: dict) -> str:
    """Package only trusted local engine code plus exact pinned input bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("__init__.py", "core.py", "research.py"):
            entry = zipfile.ZipInfo("siqe_quest/" + name, (2026, 1, 1, 0, 0, 0))
            archive.writestr(entry, (Path(__file__).parent / name).read_bytes())
    package = buffer.getvalue()
    payload = {
        "dataset": dataset,
        "raw": base64.b64encode(store.read_blob(dataset["manifest"]["raw"])).decode(),
        "normalized": base64.b64encode(
            store.read_blob(dataset["manifest"]["normalized"])
        ).decode(),
    }
    # This launcher executes the pinned local reference implementation, never
    # provider text. It requires only Python's standard library and no network.
    return '''#!/usr/bin/env python3
"""Pinned offline QUEST ALPHA reference; restricted source data, local research only."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile

PACKAGE = %r
PACKAGE_SHA256 = %r
INPUT = %r
INPUT_SHA256 = %r
SPEC_SHA256 = %r
EXPECTED_NUMERIC = %r
EXPECTED_RESULT = %r

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Optional output evidence workspace; otherwise temporary")
    args = parser.parse_args()
    package = base64.b64decode(PACKAGE)
    raw_input = base64.b64decode(INPUT)
    if hashlib.sha256(package).hexdigest() != PACKAGE_SHA256 or hashlib.sha256(raw_input).hexdigest() != INPUT_SHA256:
        raise ValueError("pinned source/input checksum mismatch")
    with tempfile.TemporaryDirectory(prefix="siqe-reference-") as temporary:
        archive = Path(temporary) / "reference.zip"
        archive.write_bytes(package)
        sys.path.insert(0, str(archive))
        from siqe_quest.core import Store, canonical_json, digest
        from siqe_quest.research import run_alpha, alpha_spec
        payload = json.loads(raw_input)
        dataset = payload["dataset"]
        if digest(alpha_spec(dataset["dataset_id"])) != SPEC_SHA256:
            raise ValueError("pinned specification mismatch")
        store = Store(args.root or str(Path(temporary) / "workspace"))
        for field in ("raw", "normalized"):
            expected = dataset["manifest"][field]
            actual = store.put_blob(base64.b64decode(payload[field]), expected["media_type"])
            if actual != expected:
                raise ValueError("pinned input blob mismatch")
        store.record("dataset", dataset["dataset_id"], dataset)
        result = run_alpha(store, dataset)["result"]
        numeric = digest({key: result[key] for key in (
            "dataset_id", "spec", "segments", "audits", "outcomes", "scientific_claim")})
        # Store registration envelopes include creation times in a new workspace;
        # compare all numerical content, not those operational envelope identities.
        match = numeric == EXPECTED_NUMERIC
        print(canonical_json({"status": "REPRODUCED" if match else "MISMATCH",
              "dataset_id": dataset["dataset_id"], "experiment_id": result["experiment_id"],
              "numeric_digest": numeric, "result_sha256": result["reproduction"]["result_sha256"],
              "offline": True, "spec_sha256": SPEC_SHA256}))
        return 0 if match else 1

if __name__ == "__main__":
    raise SystemExit(main())
''' % (
        base64.b64encode(package).decode(),
        hashlib.sha256(package).hexdigest(),
        base64.b64encode(canonical_json(payload).encode()).decode(),
        hashlib.sha256(canonical_json(payload).encode()).hexdigest(),
        digest(result["spec"]),
        digest(numeric_content(result)),
        result["reproduction"]["result_sha256"],
    )


def _knowledge(store: Store, dataset: dict, run: dict) -> dict:
    engine = KnowledgeEngine(store)
    source = dataset["manifest"]["source"]
    evidence = source["evidence"]
    original = store.read_blob(evidence).decode("utf-8")
    metadata = json.loads(original)
    detail = metadata.get("seriesDetails", metadata.get("seriesDetail", {}))
    if "FXUSDCAD" in detail:
        detail = detail["FXUSDCAD"]
    phrase = detail.get("description") or detail.get("label")
    if not isinstance(phrase, str) or not phrase or phrase not in original:
        raise ValueError("no exact literal series metadata phrase in raw source")
    quote = engine.extract(phrase, evidence, source["source_id"], "FXUSDCAD_units")
    result = run["result"]
    temporal = {
        "experiment_id": run["experiment_id"],
        "checks": result["audits"],
        "interpretation": "One-observation research lag; historical first availability unknown.",
    }
    audit = store.record("audit", "alpha-temporal:" + run["experiment_id"], temporal)
    lesson = engine.add_lesson(
        "For this locked reference-rate experiment, delayed execution, ledger checks and a fee-only negative control must precede interpretation; passing them does not establish tradable alpha.",
        [run["records"]["experiment"], audit],
        [
            "FXUSDCAD 2023-2025 retained vintage " + dataset["dataset_id"],
            "Fixed SMA20/60; train 2023, validation 2024, sealed historical test 2025",
            "Publication/first availability unknown; nontradable reference proxy",
        ],
        [
            "Executable FX quotes, financing and carry are absent",
            "Same-observation or future-feature execution invalidates this procedure",
            "Failed positive hypothesis and negative outcomes remain registered",
        ],
    )
    links = [
        engine.relate(
            quote["record_id"], "supported_by", source["source_id"], [evidence]
        ),
        engine.relate(
            lesson["record_id"],
            "tested_by",
            run["experiment_id"],
            [run["records"]["experiment"]],
        ),
        engine.relate(
            run["experiment_id"],
            "uses_method",
            digest(result["spec"]),
            [run["records"]["strategy"]],
        ),
    ]
    return {
        "quote": _ref(quote),
        "lesson": _ref(lesson),
        "temporal_audit": _ref(audit),
        "relations": [_ref(r) for r in links],
        "exact_phrase": phrase,
    }


def _learning(store: Store, run: dict) -> dict:
    curriculum = Curriculum(store)
    module = curriculum.module()
    module_record = store.record("learning_module", digest(module), module)
    intent_key = run["experiment_id"]
    intent = store.get("mission_evaluation_intent", intent_key)
    if intent is None:
        intent = store.record(
            "mission_evaluation_intent",
            intent_key,
            {
                "previous": [
                    r["record_id"] for r in store.records("learning_evaluation")
                ]
            },
        )
    candidates = [
        r
        for r in store.records("learning_evaluation")
        if r["record_id"] not in intent["value"]["previous"]
    ]
    if candidates:
        evaluation_record = candidates[0]
        evaluation = evaluation_record["value"]
    else:
        evaluation = curriculum.evaluate()
        evaluation_record = next(
            r
            for r in store.records("learning_evaluation")
            if r["record_id"] == evaluation["record_id"]
        )
    priorities = curriculum.prioritize(
        [
            {
                "objective": "Explain locked SMA underperformance without retuning the sealed historical test",
                "knowledge_gap": "Independent executable data and prospective availability remain missing",
                "expected_cost": 1,
                "maximum_attempts": 1,
                "uncertainty": 1,
                "source_plan": [
                    "Review retained split outcomes and cost sensitivity only; no network"
                ],
                "required_tools": ["Worker.run_once"],
                "research_relevance": 1,
                "evaluation_method": "Immutable experiment review; never infer unseen transfer from public cases",
                "acceptance_criteria": [
                    "Preserve losses and controls",
                    "No holdout retuning or promotion",
                ],
            }
        ],
        budget=1,
    )
    priority_record = store.record(
        "learning_priorities", run["experiment_id"], {"budget": 1, "quests": priorities}
    )
    return {
        "module": _ref(module_record),
        "evaluation": _ref(evaluation_record),
        "priorities": _ref(priority_record),
        "case_count": evaluation["case_count"],
        "accuracy": evaluation["accuracy"],
        "improvement_demonstrated": False,
        "mastery": "NOT_VERIFIED",
        "model_weights_updated": False,
        "exposure_number": evaluation["exposure_number"],
        "statement": evaluation["unseen_transfer_statement"],
    }


def _followup(store: Store, run: dict) -> dict:
    queue = EventQueue(store)
    experiment = run["records"]["experiment"]
    event = Event(
        event_type="EXPERIMENT_COMPLETED",
        idempotency_key="alpha-experiment-completed:" + run["experiment_id"],
        payload_reference={"kind": "experiment", "key": run["experiment_id"]},
        provenance_reference=_ref(experiment),
        source_id="quest-alpha",
        source_version=run["experiment_id"],
        affected_entities=["USD/CAD"],
        priority=100,
        task_budget=1,
        maximum_attempts=1,
    )
    first, second = queue.emit(event), queue.emit(event)
    cycles = []
    worker = None
    for _ in range(4):
        current = next(e for e in queue.events() if e["event_id"] == first)
        if (
            current["status"] in {"COMPLETED", "DEADLETTER", "QUARANTINED"}
            or queue.state() != "RUNNING"
        ):
            break
        worker = worker or Worker(store, schedule=False)
        cycles.append(worker.run_once())
    current = next(e for e in queue.events() if e["event_id"] == first)
    reviews = [
        r
        for r in store.records("runtime_review")
        if r["value"].get("event_id") == first
    ]
    reviewed = (
        current["status"] == "COMPLETED"
        and (current.get("result") or {}).get("status") == "REVIEWED"
        and any(r["value"].get("status") == "REVIEWED" for r in reviews)
    )
    return {
        "event_id": first,
        "second_event_id": second,
        "event_count": sum(
            e["idempotency_key"] == event.idempotency_key for e in queue.events()
        ),
        "deduplicated": first == second,
        "delivery_status": current["status"],
        "status": "REVIEWED" if reviewed else "BLOCKED",
        "queue_state": queue.state(),
        "result": current.get("result"),
        "reviews": [_ref(r) for r in reviews],
        "cycles": cycles,
        "maximum_cycles": 4,
        "auto_resume": False,
        "background_service_claimed": False,
    }


def run_mission(store: Store, refresh: bool = False) -> dict:
    """Run the bounded lifecycle, replaying retained data unless refresh is explicit."""
    store.authorize("research.mission")
    dataset = _dataset(store, refresh)
    software = _software(store)
    run = run_alpha(store, dataset)
    result = run["result"]
    base = digest(
        {
            "dataset": dataset["dataset_id"],
            "spec": digest(result["spec"]),
            "numeric": digest(numeric_content(result)),
            "software": software["sha256"],
        }
    )
    for record in reversed(store.records("mission")):
        if (
            record["value"].get("identity") == base
            and record["value"].get("status") == "COMPLETED"
        ):
            return {**record["value"], "record": _ref(record)}
    start = store.get("mission_started", base)
    if start is None:
        start = store.record(
            "mission_started", base, {"started_at": utcnow(), "identity": base}
        )
    stages = {}
    for name, action in (
        ("knowledge", lambda: _knowledge(store, dataset, run)),
        (
            "artifacts",
            lambda: {
                "pine": _artifact(
                    store,
                    "artifacts/pine_v6/quest_alpha.pine",
                    render_pine(result["spec"]).encode(),
                    "text/plain",
                ),
                "reference": _artifact(
                    store,
                    "artifacts/quest_alpha_reference.py",
                    _reference_source(store, dataset, result).encode(),
                    "text/x-python",
                ),
                "parity": parity_report(result["segments"]["sealedtest"]["candidate"]),
                "spec_sha256": digest(result["spec"]),
                "python_execution": "NOT_TESTED_UNTIL_REFERENCE_ARTIFACT_EXECUTED",
            },
        ),
    ):
        key = base + ":" + name
        checkpoint = store.get("mission_stage", key)
        if checkpoint is None:
            checkpoint = store.record("mission_stage", key, action())
        stages[name] = checkpoint["value"]
    followup = _followup(store, run)
    # The public independent answer-key benchmark is the final evaluation stage;
    # retain its exact exposure record on resume instead of manufacturing a new one.
    learning_key = base + ":learning"
    learning = store.get("mission_stage", learning_key)
    if learning is None:
        learning = store.record("mission_stage", learning_key, _learning(store, run))
    stages["learning"] = learning["value"]
    manifest = dataset["manifest"]
    discovery = _discovery(store, dataset)
    limitations = list(
        dict.fromkeys(
            result["limitations"]
            + manifest.get("limitations", [])
            + [
                "Pine compilation and TradingView parity NOT_VERIFIED; portable source is not platform execution.",
                "Public 21-case reference benchmark is not unseen LLM evaluation, mastery, or measured improvement.",
                "No fine-tuning, model-weight updates, live trading, broker or publication actions.",
                "Only one reference-rate instrument slice; liquidity, executable fills and global coverage not established.",
                "Operator STOP/PAUSE is never automatically resumed; worker follow-up may remain blocked.",
            ]
        )
    )
    status = (
        "COMPLETED"
        if (
            followup["status"] == "REVIEWED"
            and discovery
            and result["audits"]["passed"]
            and followup["deduplicated"]
            and followup["event_count"] == 1
            and stages["learning"]["case_count"] == 21
        )
        else "BLOCKED"
    )
    value = {
        "schema_version": 1,
        "quest_id": "QUEST-ALPHA-01",
        "identity": base,
        "status": status,
        "started_at": start["value"]["started_at"],
        "completed_at": utcnow(),
        "dataset": {
            "dataset_id": dataset["dataset_id"],
            "manifest": manifest,
            "record": _ref(store.get("dataset", dataset["dataset_id"])),
            "discovery": discovery,
            "offline_replay": not refresh,
        },
        "research": {
            "experiment_id": run["experiment_id"],
            "result_sha256": result["reproduction"]["result_sha256"],
            "numeric_digest": digest(numeric_content(result)),
            "spec_sha256": digest(result["spec"]),
            "spec": result["spec"],
            "hypothesis": result["hypothesis"],
            "splits": result["spec"]["splits"],
            "costs": result["spec"]["trading_costs"],
            "slippage": result["spec"]["slippage"],
            "records": {key: _ref(r) for key, r in run["records"].items()},
            "outcomes": result["outcomes"],
            "audits": result["audits"],
            "metrics": {
                split: {mode: output["metrics"] for mode, output in modes.items()}
                for split, modes in result["segments"].items()
            },
            "scientific_claim": result["scientific_claim"],
        },
        **stages,
        "followup": followup,
        "software": software,
        "reproducibility": {
            "command": "siqe-quest --root ROOT reproduce",
            "reference_command": "python3 artifacts/quest_alpha_reference.py",
            "input_raw_sha256": manifest["raw"]["sha256"],
            "input_normalized_sha256": manifest["normalized"]["sha256"],
            "comparison": "Exact canonical numerical content; learning exposure times excluded",
            "verification": [_ref(r) for r in store.records("verification")],
            "network_required": False,
        },
        "limitations": limitations,
    }
    value["mission_id"] = digest(value)
    record = store.record("mission", value["mission_id"], value)
    return {**value, "record": _ref(record)}


def reproduce_mission(store: Store) -> dict:
    """Recalculate pinned numerical evidence without learning exposures or events."""
    missions = store.records("mission")
    if not missions:
        raise ValueError("no mission to reproduce; run alpha first")
    mission = missions[-1]
    value = mission["value"]
    dataset_record = store.get("dataset", value["dataset"]["dataset_id"])
    if dataset_record is None:
        raise ValueError("pinned dataset missing")
    run = run_alpha(store, dataset_record["value"])
    numeric = digest(numeric_content(run["result"]))
    expected = value["research"]["numeric_digest"]
    full_hash = run["result"]["reproduction"]["result_sha256"]
    matches = numeric == expected and full_hash == value["research"]["result_sha256"]
    result = {
        "mission_id": value["mission_id"],
        "experiment_id": run["experiment_id"],
        "dataset_id": dataset_record["key"],
        "status": "REPRODUCED" if matches else "MISMATCH",
        "identical_numeric_content": numeric == expected,
        "numeric_digest": numeric,
        "expected_numeric_digest": expected,
        "result_sha256": full_hash,
        "expected_result_sha256": value["research"]["result_sha256"],
        "offline": True,
        "learning_reexecuted": False,
        "followup_reemitted": False,
    }
    record = store.record("mission_reproduction", digest(result), result)
    return {**result, "record": _ref(record)}

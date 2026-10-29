"""Regenerable local research views backed by immutable Store evidence.

A successful unit test, an artifact filename and a historical daemon smoke are
not interchangeable with a reproduced experiment or a currently running service.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from .core import Store, canonical_json, digest, utcnow
from .events import EventQueue
from .knowledge import KnowledgeEngine
from .learning import DIMENSIONS
from .markets import coverage_matrix
from .runtime import service_status

REPORT_TYPES = (
    "daily_discovery_digest",
    "new_source_intelligence_summary",
    "academic_literature_review",
    "quantitative_hypothesis_register",
    "strategy_experiment_report",
    "tradingview_parity_report",
    "cross_market_performance_comparison",
    "statistical_robustness_report",
    "knowledge_improvement_scorecard",
    "weekly_research_priorities",
    "operational_health_report",
)
GATE_STATUSES = frozenset(
    {
        "VERIFIED_BY_EXECUTION",
        "VERIFIED_BY_REPRODUCTION",
        "PARTIALLY_VERIFIED",
        "IMPLEMENTED_NOT_TESTED",
        "BLOCKED",
        "FAILED",
        "NOT_TESTED",
    }
)
GATE_TITLES = (
    "New project is isolated",
    "Runtime capabilities discovered",
    "First source registry implemented",
    "Official source retrieved and validated",
    "Durable hook queue works",
    "Duplicate and recursive storms prevented",
    "Knowledge extraction traceable to evidence",
    "Complete scored learning module executable",
    "Representative dataset acquired and versioned",
    "Baseline experiment reproduced",
    "Legitimate backtesting methodology implemented",
    "Pine v6 artifact generated",
    "Pine compilation truthfully classified",
    "TradingView parity truthfully classified",
    "Adversarial test catches a material planted error",
    "Negative experiment preserved",
    "Independent evaluation benchmark executed",
    "Unseen improvement or explicit no improvement",
    "No live trading",
    "Persistent service genuinely running",
    "Resource limits enforced",
)
LIMITATIONS = [
    "Local research report, not investment advice or client publication authorization.",
    "Bank of Canada daily average FX reference rates are not executable fills; historical first availability is unknown.",
    "Retrospective locked splits are not prospective preregistration or proof of alpha.",
    "Public numerical benchmark results are not LLM mastery, unseen transfer or model training.",
]
REPRODUCTION_COMMANDS = [
    "python -m siqe_quest.cli --root <workspace> reproduce",
    "python -m siqe_quest.cli --root <workspace> report",
    "python -m siqe_quest.cli --root <workspace> service status",
]


def _ref(record: dict) -> dict:
    return {
        key: record[key]
        for key in ("kind", "key", "record_id", "created_at", "evidence")
    }


def _blob_refs(value):
    """Walk JSON for actual immutable descriptors, without treating strings as proof."""
    if isinstance(value, dict):
        if {"sha256", "path", "bytes"} <= value.keys():
            yield value
        for child in value.values():
            yield from _blob_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _blob_refs(child)


def _checks(records: list[dict]) -> dict:
    checks = {}
    # Store insertion order, not lexical hash order, defines the latest observation.
    for record in records:
        value = record["value"]
        for name, check in value.get("checks", {}).items():
            if isinstance(check, dict):
                checks[name] = {
                    "check": check,
                    "verification": _ref(record),
                    "status": value.get("status"),
                    "observed_at": value.get("observed_at"),
                }
    return checks


def _passed(checks: dict, name: str) -> bool:
    item = checks.get(name, {})
    return item.get("check", {}).get("passed") is True and item.get("status") in {
        "VERIFIED_BY_EXECUTION",
        "VERIFIED_BY_REPRODUCTION",
    }


def _scorecard(evaluations: list[dict], exposures: list[dict]) -> dict:
    latest = evaluations[-1]["value"] if evaluations else {}
    metrics = {
        key: {"name": name, "value": None, "status": "UNMEASURED", "scope": None}
        for key, name in DIMENSIONS.items()
    }
    # Independently keyed literal answers score the public reference implementation.
    # Never adopt arbitrary metric claims from a caller-supplied mission dictionary.
    if latest.get("evaluated_system") == "reference_numerical_implementation":
        for key, domains in (
            ("D", {"Financial calculations", "Probability", "Statistics"}),
            (
                "E",
                {
                    "Financial statement interpretation",
                    "Economic reasoning",
                    "Trading cost handling",
                },
            ),
        ):
            rows = [
                row for row in latest.get("results", []) if row.get("domain") in domains
            ]
            if rows and all(type(row.get("correct")) is bool for row in rows):
                metrics[key].update(
                    value=sum(row["correct"] for row in rows) / len(rows),
                    status="MEASURED_NARROW_REFERENCE_CASES",
                    scope="Public numerical reference implementation; not LLM capability",
                )
    return {
        "dimensions": metrics,
        "evaluation": evaluations[-1] if evaluations else None,
        "exposures": exposures,
        "exposure_count": len(exposures),
        "unseen_to_model": False,
        "mastery": "NOT_VERIFIED",
        "retention": "NOT_TESTED",
        "improvement": "NO_IMPROVEMENT_DEMONSTRATED",
        "training_performed": False,
        "model_weights_updated": False,
        "needed_evidence": "Independently sealed before/after tasks, controlled comparison, regression checks and delayed retention.",
    }


def _context(store: Store, mission: dict | None) -> dict:
    kinds = (
        "source",
        "source_validation",
        "source_policy",
        "source_retrieval",
        "source_snapshot",
        "source_update",
        "source_health",
        "discovery_plan",
        "discovery_result",
        "discovery_links",
        "dataset",
        "hypothesis",
        "strategy",
        "experiment",
        "learning_evaluation",
        "benchmark_manifest",
        "benchmark_exposure",
        "learning_comparison",
        "runtime_review",
        "verification",
        "mission",
        "market_coverage",
        "report_review",
        "audit",
        "source_proof",
        "learning_module",
        "learning_retention",
        "learning_review",
        "controlled_comparison",
        "learning_priorities",
        "mission_reproduction",
    )
    records = {kind: store.records(kind) for kind in kinds}
    latest_mission = records["mission"][-1] if records["mission"] else None
    selected = deepcopy(
        mission
        if mission is not None
        else latest_mission["value"]
        if latest_mission
        else {}
    )
    if selected.get("kind") == "mission" and isinstance(selected.get("value"), dict):
        selected = selected["value"]
    knowledge = KnowledgeEngine(store).index()
    queue = EventQueue(store)
    events, stats = queue.events(), queue.stats()
    try:
        service = service_status(store.root)
    except (OSError, ValueError, RuntimeError) as exc:
        service = {
            "running": None,
            "status": "NOT_TESTED",
            "error_class": type(exc).__name__,
        }
    matrix = coverage_matrix()
    for record in records["market_coverage"]:
        value = record["value"]
        for cell in matrix["cells"]:
            if cell["cell_id"] == value.get("cell_id"):
                cell.update(value)
    matrix["coverage_history"] = records["market_coverage"]
    matrix["dataset_evidence"] = [
        dict(_ref(r), manifest=r["value"].get("manifest", {}))
        for r in records["dataset"]
    ]
    # Preserve the catalog's untested comparison status even when a data cell is acquired.
    checks = _checks(records["verification"])
    return {
        "records": records,
        "mission": selected,
        "mission_record": _ref(latest_mission)
        if latest_mission
        and (
            mission is None
            or selected == latest_mission["value"]
            or (
                selected.get("mission_id")
                and selected.get("mission_id")
                == latest_mission["value"].get("mission_id")
            )
        )
        else None,
        "knowledge": knowledge,
        "events": events,
        "queue": stats,
        "service": service,
        "matrix": matrix,
        "checks": checks,
        "scorecard": _scorecard(
            records["learning_evaluation"], records["benchmark_exposure"]
        ),
    }


def _release_gates(store: Store, context: dict) -> dict:
    records, checks = context["records"], context["checks"]
    experiments = records["experiment"]
    gates = {
        f"SIQE-G{i}": {
            "title": title,
            "status": "NOT_TESTED",
            "evidence": [],
            "reason": "No matching exercised evidence recorded.",
        }
        for i, title in enumerate(GATE_TITLES)
    }

    def set_gate(number, status, reason, evidence=()):
        if status not in GATE_STATUSES:
            raise ValueError("unsupported release gate status")
        gates[f"SIQE-G{number}"].update(
            status=status, reason=reason, evidence=list(evidence)
        )

    def checked(
        number, names, reason, prerequisites=True, status="VERIFIED_BY_EXECUTION"
    ):
        evidence = [checks[name] for name in names if name in checks]
        if prerequisites and all(_passed(checks, name) for name in names):
            set_gate(number, status, reason, evidence)
        elif any(item["check"].get("passed") is False for item in evidence):
            set_gate(
                number, "FAILED", "Latest matching execution check failed.", evidence
            )

    checked(0, ["workspace_isolation"], "Independent workspace isolation exercised.")
    checked(1, ["runtime_capabilities"], "Runtime capabilities actually observed.")
    # A historical environment observation is content evidence, not mere file presence.
    path = store.path("artifacts/reports/environment.json")
    if path.is_file():
        try:
            raw = path.read_bytes()
            env = json.loads(raw)
            evidence = [
                {
                    "path": "artifacts/reports/environment.json",
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "observed_at": env.get("observed_at"),
                    "observation": env,
                }
            ]
            if (
                gates["SIQE-G0"]["status"] == "NOT_TESTED"
                and env.get("workspace") == str(store.root)
                and env.get("isolation")
                and env.get("workspace_initial_state")
            ):
                set_gate(
                    0,
                    "PARTIALLY_VERIFIED",
                    "Recorded isolation observation; not an independent filesystem-wide isolation audit.",
                    evidence,
                )
            if (
                gates["SIQE-G1"]["status"] == "NOT_TESTED"
                and env.get("runtime", {}).get("python")
                and env.get("host", {}).get("architecture")
            ):
                set_gate(
                    1,
                    "VERIFIED_BY_EXECUTION",
                    "Recorded runtime probe results, with observation time preserved.",
                    evidence,
                )
        except (OSError, ValueError, TypeError):
            pass
    source_observed = (
        checks.get("official_source_acquisition", {})
        .get("check", {})
        .get("observed", {})
    )
    acquired = False
    if isinstance(source_observed, dict):
        for record in records["dataset"]:
            value = record["value"]
            manifest = value.get("manifest", {})
            source = manifest.get("source", {})
            matching_validation = any(
                r["value"] == source for r in records["source_validation"]
            )
            if (
                value.get("dataset_id") == source_observed.get("dataset_id")
                and manifest.get("raw", {}).get("sha256")
                == source_observed.get("raw_sha")
                and manifest.get("source_id") == source_observed.get("source_id")
                and manifest.get("source_version")
                == source_observed.get("source_version")
                and source.get("verification_outcome") == "VALIDATED_RESEARCH_ONLY"
                and matching_validation
            ):
                store.read_blob(manifest["raw"])
                normalized = store.read_blob(manifest["normalized"])
                acquired = normalized == canonical_json(
                    value.get("observations")
                ).encode("utf-8")
                if acquired:
                    break
    if records["source"]:
        set_gate(
            2,
            "VERIFIED_BY_EXECUTION",
            "Immutable discovered-source registry contains actual records.",
            map(_ref, records["source"]),
        )
    checked(
        3,
        ["official_source_acquisition"],
        "Executed official acquisition linked to source validation and dataset.",
        prerequisites=bool(
            acquired and records["source_validation"] and records["dataset"]
        ),
    )
    checked(
        4,
        ["core_evidence_smoke"],
        "Durable Store and reopened queue behavior exercised.",
    )
    checked(
        5,
        ["event_reopen_dedup_depth"],
        "Deduplication, recursive depth and queue budgets exercised.",
    )
    if context["knowledge"]["concepts"]:
        set_gate(
            6,
            "VERIFIED_BY_EXECUTION",
            "Knowledge index rechecked exact source spans and immutable evidence hashes.",
            [_ref(row) for row in context["knowledge"]["concepts"]],
        )
    module_reference = context["mission"].get("learning", {}).get("module", {})
    module_present = isinstance(module_reference, dict) and any(
        r["record_id"] == module_reference.get("record_id")
        and r["value"].get("deterministic_test")
        and r["value"].get("retention")
        and r["value"].get("applied_experiment")
        for r in records["learning_module"]
    )
    checked(
        7,
        ["learning_independent_cases"],
        "Complete learning module and independent scoring exercised.",
        prerequisites=bool(module_present and records["learning_evaluation"]),
    )
    checked(
        8,
        ["official_source_acquisition"],
        "Acquired normalized and raw dataset with immutable versioned manifest.",
        prerequisites=bool(
            acquired and records["dataset"] and records["source_snapshot"]
        ),
    )
    replay = (
        checks.get("numeric_experiment_reproduction", {})
        .get("check", {})
        .get("observed", {})
    )
    replay_matches = (
        isinstance(replay, dict)
        and replay.get("same_numeric_outputs") is True
        and any(
            row["value"].get("experiment_id") == replay.get("experiment_id")
            and row["value"].get("dataset_id") == replay.get("dataset_id")
            and row["value"].get("reproduction", {}).get("result_sha256")
            == replay.get("result_sha256")
            for row in experiments
        )
    )
    checked(
        9,
        ["numeric_experiment_reproduction"],
        "Actual numeric replay matched persisted experiment and result digest.",
        prerequisites=replay_matches,
        status="VERIFIED_BY_REPRODUCTION",
    )
    checked(
        10,
        ["independent_ledger", "independent_leakage"],
        "Independent ledger and planted-leakage checks supplement recorded temporal/cost/split methodology.",
        prerequisites=any(
            row["value"].get("audits", {}).get("passed") is True for row in experiments
        ),
    )
    artifacts = context["mission"].get("artifacts", {})
    pine = artifacts.get("pine", {}) if isinstance(artifacts, dict) else {}
    for reference in _blob_refs(pine):
        content = store.read_blob(reference).decode("utf-8")
        if "//@version=6" in content and "strategy(" in content:
            set_gate(
                11,
                "VERIFIED_BY_EXECUTION",
                "Generated immutable Pine v6 source inspected; no platform compilation implied.",
                [reference],
            )
            break
    checked(11, ["pine_artifact"], "Pine artifact generation exercised.")
    for number in (12, 13):
        set_gate(
            number,
            "NOT_TESTED",
            "Classification MET: NOT_VERIFIED. No authenticated TradingView compilation/execution evidence; portable source is not platform execution.",
        )
        gates[f"SIQE-G{number}"]["classification"] = "MET"
        gates[f"SIQE-G{number}"]["platform_status"] = "NOT_VERIFIED"
        gates[f"SIQE-G{number}"]["needed_evidence"] = (
            "Actual TradingView compiler output and timestamped platform exports for matched feed/session/spec, independently authenticated."
        )
    checked(
        14,
        ["independent_leakage"],
        "Actual planted future dependency/same-observation error rejected.",
        prerequisites=any(
            r["value"].get("audits", {}).get("planted_leak", {}).get("passed") is True
            for r in experiments
        ),
    )
    checked(
        15,
        ["negative_preserved"],
        "Negative experiment outcomes remain in immutable experiment evidence.",
        prerequisites=any(
            o.get("net_return", 0) < 0
            for r in experiments
            for o in r["value"].get("outcomes", [])
        ),
    )
    evaluations = records["learning_evaluation"]
    if any(
        r["value"].get("results") and r["value"].get("provenance", {}).get("answer_key")
        for r in evaluations
    ):
        set_gate(
            16,
            "VERIFIED_BY_EXECUTION",
            "Executed public independently keyed numerical benchmark; not sealed unseen LLM evaluation.",
            map(_ref, evaluations),
        )
    set_gate(
        17,
        "VERIFIED_BY_EXECUTION",
        "NO_IMPROVEMENT_DEMONSTRATED: no controlled independently sealed unseen transfer or delayed retention established.",
        map(_ref, records["learning_comparison"]),
    )
    gates["SIQE-G17"]["improvement_demonstrated"] = False
    checked(
        18,
        ["no_live_actions"],
        "Research-only policy rejection observed; no live execution asserted.",
        prerequisites=store.config.get("live_trading") is False,
    )
    if store.config.get("live_trading") is not False:
        set_gate(
            18, "FAILED", "Configuration does not explicitly disable live trading."
        )
    service = context["service"]
    if all(
        service.get(key) is True
        for key in (
            "running",
            "process_verified",
            "heartbeat_verified",
            "heartbeat_fresh",
            "singleton_held",
        )
    ):
        set_gate(
            19,
            "VERIFIED_BY_EXECUTION",
            "Current workspace service identity, singleton and fresh heartbeat verified at report generation.",
            [service],
        )
    else:
        set_gate(
            19,
            "FAILED" if service.get("running") is False else "NOT_TESTED",
            "Current workspace service is not verified running. Historical disposable-worker lifecycle proof does not establish current operation.",
            [service],
        )
    checked(
        20,
        ["resource_rlimits", "maxcyclebudget"],
        "Actual child resource limits and cycle budgets exercised.",
    )
    if gates["SIQE-G20"]["status"] == "NOT_TESTED" and _passed(
        checks, "resource_rlimits"
    ):
        set_gate(
            20,
            "PARTIALLY_VERIFIED",
            "Actual child rlimits observed in recorded test scope; cycle budget execution not yet verified.",
            [checks["resource_rlimits"]],
        )
    return {
        "schema_version": 1,
        "gates": gates,
        "allowed_statuses": sorted(GATE_STATUSES),
        "authoritative_view": "release_gates.json",
        "legacy_claims_are_authoritative": False,
        "service_observed_at": utcnow(),
        "limitations": [
            "Verification scope and timestamps are retained; temporary worker tests are not proof of main service operation."
        ],
    }


def _result_rows(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        value = record["value"]
        for split, modes in value.get("segments", {}).items():
            for mode, result in modes.items():
                metrics = result.get("metrics", {})
                net = metrics.get("net_return")
                initial = result.get("initial_capital")
                rows.append(
                    {
                        "experiment": _ref(record),
                        "dataset_id": value.get("dataset_id"),
                        "split": split,
                        "mode": mode,
                        "metrics": metrics,
                        "net_return_fraction": net,
                        "net_return_percent": net * 100
                        if isinstance(net, (int, float))
                        else None,
                        "net_pnl_cad": net * initial
                        if isinstance(net, (int, float))
                        and isinstance(initial, (int, float))
                        else None,
                        "initial_capital_cad": initial,
                        "confidence_interval": result.get("confidence_interval"),
                        "sensitivity": result.get("sensitivity"),
                        "temporal_audit": result.get("temporal_audit"),
                        "evidence_level": "HISTORICAL_NONTRADABLE_REFERENCE_PROXY",
                    }
                )
    return rows


def _reports(store: Store, context: dict) -> dict:
    records = context["records"]
    manifests = [
        dict(_ref(r), manifest=r["value"].get("manifest", {}))
        for r in records["dataset"]
    ]
    rows = _result_rows(records["experiment"])
    sources = {
        "discovered": records["source"],
        "validations": records["source_validation"],
        "discovery_history": records["discovery_result"],
        "links": records["discovery_links"],
        "policy_history": records["source_policy"],
        "retrievals": records["source_retrieval"],
        "updates": records["source_update"],
        "health": records["source_health"],
        "distinction": "Discovery is not validation. Validation applies only to the exact source_id/version in its immutable record.",
    }
    shared = {
        "schema_version": 1,
        "generated_at": utcnow(),
        "dataset_versions": manifests,
        "market_coverage": context["matrix"],
        "limitations": list(LIMITATIONS),
        "reproduction_commands": REPRODUCTION_COMMANDS,
        "source_references": [_ref(r) for r in records["source_validation"]],
        "mission_record": context["mission_record"],
        "review_status": "LOCAL_RESEARCH_ONLY_NOT_APPROVED_FOR_PUBLICATION",
    }
    priority_reference = context["mission"].get("learning", {}).get("priorities", [])
    priorities = priority_reference
    if isinstance(priority_reference, dict):
        priority_record = next(
            (
                r
                for r in records["learning_priorities"]
                if r["record_id"] == priority_reference.get("record_id")
            ),
            None,
        )
        priorities = (
            priority_record["value"].get("quests", []) if priority_record else []
        )

    def report(name, data, methodology, status=None, needed=None):
        if status is None:
            required_kind = {
                "daily_discovery_digest": "source",
                "new_source_intelligence_summary": "source",
                "quantitative_hypothesis_register": "hypothesis",
                "strategy_experiment_report": "experiment",
                "statistical_robustness_report": "experiment",
                "knowledge_improvement_scorecard": "learning_evaluation",
                "weekly_research_priorities": "mission",
                "operational_health_report": "verification",
            }.get(name)
            status = (
                "PARTIALLY_VERIFIED"
                if required_kind and records[required_kind]
                else "NOT_TESTED"
            )
        value = dict(
            shared,
            report_type=name,
            status=status,
            methodology=methodology,
            statistical_metrics=None,
            data=data,
        )
        if needed:
            value["needed_evidence"] = needed
        return value

    reports = {}
    reports[REPORT_TYPES[0]] = report(
        REPORT_TYPES[0],
        {
            "sources": sources,
            "plans": records["discovery_plan"],
            "events": context["events"],
        },
        "Cumulative immutable discovery history as of generation; timestamps permit daily filtering, not a fabricated daily count.",
    )
    reports[REPORT_TYPES[1]] = report(
        REPORT_TYPES[1],
        sources,
        "Exact registered and separately validated source versions, rights and retrieval histories.",
    )
    reports[REPORT_TYPES[2]] = report(
        REPORT_TYPES[2],
        {"reviewed_papers": [], "source_catalog": sources["discovered"]},
        "No academic paper corpus was acquired or critically reviewed by this mission.",
        "NOT_TESTED",
        "Acquire authorized full-text papers with bibliographic identifiers, methods, assumptions, competing findings and exact evidence spans; official API documentation is not literature-review evidence.",
    )
    reports[REPORT_TYPES[3]] = report(
        REPORT_TYPES[3],
        records["hypothesis"],
        "Immutable registration and retrospective lock status; no prospective preregistration inferred.",
    )
    reports[REPORT_TYPES[4]] = report(
        REPORT_TYPES[4],
        {
            "experiments": [_ref(r) for r in records["experiment"]],
            "results": rows,
            "strategies": records["strategy"],
        },
        "Fixed split/mode reference-proxy simulations; returns are fractions, percent=100*fraction, CAD PnL=initial capital*fraction.",
    )
    reports[REPORT_TYPES[4]]["statistical_metrics"] = rows
    artifacts = context["mission"].get("artifacts", {})
    reports[REPORT_TYPES[5]] = report(
        REPORT_TYPES[5],
        {
            "artifacts": artifacts,
            "compilation_status": "NOT_VERIFIED",
            "parity_status": "NOT_VERIFIED",
        },
        "Portable Pine generation and available comparison evidence are distinct from actual TradingView execution.",
        "NOT_TESTED",
        "Authenticated TradingView compiler output and matched OHLC/signals/trades/equity/drawdown export with feed/calendar/cost alignment.",
    )
    reports[REPORT_TYPES[6]] = report(
        REPORT_TYPES[6],
        {"coverage_catalog": context["matrix"], "comparisons": []},
        "Single USD/CAD reference-rate study cannot establish cross-market performance.",
        "NOT_TESTED",
        "At least two authorized market datasets with independent calendars, currency/corporate-action/roll metadata, matched methods and costs, plus reproduced experiments. Catalog entries alone are not evaluated markets.",
    )
    reports[REPORT_TYPES[7]] = report(
        REPORT_TYPES[7],
        {
            "results": rows,
            "audits": [
                dict(
                    experiment=_ref(r),
                    audits=r["value"].get("audits"),
                    limitations=r["value"].get("limitations"),
                )
                for r in records["experiment"]
            ],
        },
        "Recorded block bootstrap, sensitivity, temporal and ledger checks only; no invented significance, capacity or prospective OOS claim.",
    )
    reports[REPORT_TYPES[7]]["statistical_metrics"] = rows
    reports[REPORT_TYPES[8]] = report(
        REPORT_TYPES[8],
        context["scorecard"],
        "Nullable 16-dimensional scorecard; only actual public reference-case correctness measured, no LLM mastery or unseen improvement.",
    )
    reports[REPORT_TYPES[9]] = report(
        REPORT_TYPES[9],
        {
            "priorities": priorities,
            "priority_reference": priority_reference,
            "followup": context["mission"].get("followup"),
            "contradictions": context["knowledge"]["contradictions"],
        },
        "Persisted bounded mission priorities; no claims of a completed week or continuous scientific improvement.",
        needed="Resolve point-in-time data, independently sealed transfer/retention, actual platform exports and authorized broader-market datasets before promotion.",
    )
    reports[REPORT_TYPES[10]] = report(
        REPORT_TYPES[10],
        {
            "queue": context["queue"],
            "events": context["events"],
            "current_service": context["service"],
            "runtime_reviews": records["runtime_review"],
            "verification_history": records["verification"],
            "release_gates": _release_gates(store, context),
            "fine_tuning": store.config.get("fine_tuning"),
            "live_trading": store.config.get("live_trading"),
        },
        "Live local service_status plus immutable execution evidence; temporary service tests retain their scope. Operational reliability is not scientific improvement.",
    )
    return reports


def build_reports(store: Store, mission: dict | None = None) -> dict:
    """Build all eleven local report types without acquiring data or executing research."""
    store.authorize("report.build")
    return _reports(store, _context(store, mission))


def export_bundle(store: Store, mission: dict | None = None) -> dict:
    """Archive immutable originals, then replace regenerable latest views only.

    Legacy foundation_initial_gates.json remains untouched historical material;
    release_gates.json is the sole current gate view. Nothing is published.
    """
    store.authorize("report.export")
    context = _context(store, mission)
    reports = _reports(store, context)
    records = context["records"]
    source_data = reports["new_source_intelligence_summary"]["data"]
    provenance_records = [r for group in records.values() for r in group]
    for key in (
        "concepts",
        "claims",
        "lessons",
        "entities",
        "graph",
        "operational_memory",
        "lifecycle",
        "promotions",
    ):
        provenance_records.extend(context["knowledge"][key])
    blobs = {
        r["sha256"]: r for record in provenance_records for r in _blob_refs(record)
    }
    graph = {
        "records": [_ref(r) for r in provenance_records],
        "blobs": list(blobs.values()),
        "knowledge_edges": context["knowledge"]["graph"],
        "events": context["events"],
        "mission": context["mission_record"],
        "reference_policy": "Record ids and content-addressed blobs preserve original evidence; graph inclusion is not scientific validation.",
    }
    values = {
        "source_registry": source_data,
        "hook_event_log": {"events": context["events"], "stats": context["queue"]},
        "knowledge_index": context["knowledge"],
        "hypothesis_registry": records["hypothesis"],
        "experiment_registry": records["experiment"],
        "dataset_manifests": [
            dict(_ref(r), manifest=r["value"].get("manifest", {}))
            for r in records["dataset"]
        ],
        "backtest_results": {
            "results": _result_rows(records["experiment"]),
            "experiments": records["experiment"],
        },
        "strategy_specifications": records["strategy"],
        "evaluation_scores": {
            "evaluations": records["learning_evaluation"],
            "manifests": records["benchmark_manifest"],
            "exposures": records["benchmark_exposure"],
            "comparisons": records["learning_comparison"],
            "scorecard": context["scorecard"],
        },
        "provenance_graph": graph,
        "release_gates": reports["operational_health_report"]["data"]["release_gates"],
        "market_coverage": context["matrix"],
        "reports": reports,
    }
    exports = {}
    directory = store.path("artifacts/reports")
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in values.items():
        content = (canonical_json(value) + "\n").encode("utf-8")
        blob = store.put_blob(content, "application/json")
        relative = f"artifacts/reports/{name}.json"
        store.path(relative).write_bytes(content)
        exports[name] = {
            "path": relative,
            "sha256": blob["sha256"],
            "bytes": blob["bytes"],
            "original": blob,
        }
    for name, report in reports.items():
        # Pretty-printed human-readable JSON preserves the exact machine fields.
        content = (
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode("utf-8")
        blob = store.put_blob(content, "application/json")
        relative = f"artifacts/reports/{name}.json"
        store.path(relative).write_bytes(content)
        exports[name] = {
            "path": relative,
            "sha256": blob["sha256"],
            "bytes": blob["bytes"],
            "original": blob,
        }
    snapshot_value = {
        "generated_at": reports[REPORT_TYPES[0]]["generated_at"],
        "mission": context["mission_record"],
        "exports": exports,
        "publication": "LOCAL_ONLY_REQUIRES_SEPARATE_REVIEW_AND_AUTHORIZATION",
    }
    snapshot = store.record("report_snapshot", digest(snapshot_value), snapshot_value)
    store.audit(
        "report.exported",
        {
            "snapshot_record_id": snapshot["record_id"],
            "export_count": len(exports),
            "publication": False,
        },
    )
    return {"reports": reports, "exports": exports, "snapshot": snapshot}

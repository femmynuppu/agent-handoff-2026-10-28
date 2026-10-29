"""Bounded research worker and Linux detached-service lifecycle.

No event payload is an executable instruction.  Only this module's fixed handlers
can run; all external acquisition is the separately bounded scheduled source review.
Freshness review succeeds only for unchanged or changed-but-needing-revalidation
source checks; failed or unknown results never establish source freshness.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
from datetime import datetime, timezone
import json
import copy
import math
import os
from pathlib import Path
from urllib.parse import urlsplit
import resource
import signal
import subprocess
import sys
import threading
import time
import uuid
from typing import Callable

from .core import Store, SafetyError, canonical_json, digest, utcnow
from .events import EventQueue

HOOKS = frozenset(
    {
        "session_initialized",
        "knowledge_gap_detected",
        "new_source_discovered",
        "source_updated",
        "new_research_paper",
        "new_market_event",
        "new_knowledge_validated",
        "experiment_completed",
        "backtest_failed",
        "strategy_passed_research_gate",
        "retrieval_or_memory_contradiction",
        "tool_failure",
        "periodic_research_review",
        "safety_violation",
        "knowledge_decay_detected",
    }
)
HEARTBEAT_TTL = 90.0
LOG_BYTES = 1024 * 1024


def _state_path(store: Store, name: str) -> Path:
    original = store.root / "state" / name
    if original.is_symlink():
        raise SafetyError("Runtime state must not use symbolic links")
    path = store.path("state/" + name)
    if path.exists() and not path.is_file():
        raise SafetyError("Runtime state must be a regular file")
    return path


def _json_read(path: Path) -> dict:
    try:
        if path.stat().st_size > 65536:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(canonical_json(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _identity(pid: int) -> dict:
    """Linux boot and start ticks disambiguate PID reuse (including zombies)."""
    proc = Path("/proc") / str(pid)
    text = (proc / "stat").read_text(encoding="ascii")
    fields = text[text.rfind(")") + 2 :].split()
    if fields[0] == "Z":
        raise ProcessLookupError("zombie process")
    return {
        "pid": pid,
        "start_ticks": fields[19],
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "uid": proc.stat().st_uid,
        "executable": str((proc / "exe").resolve(strict=True)),
        "command_hash": hashlib.sha256((proc / "cmdline").read_bytes()).hexdigest(),
    }


def _owned(identity: dict) -> bool:
    try:
        pid = int(identity["pid"])
        if pid <= 1 or identity.get("uid") != os.getuid():
            return False
        return _identity(pid) == {
            key: identity[key]
            for key in (
                "pid",
                "start_ticks",
                "boot_id",
                "uid",
                "executable",
                "command_hash",
            )
        }
    except (OSError, ValueError, KeyError, TypeError, ProcessLookupError):
        return False


def _worker_process(store: Store, identity: dict) -> bool:
    if not _owned(identity):
        return False
    try:
        proc = Path("/proc") / str(identity["pid"])
        args = (proc / "cmdline").read_bytes().decode().split("\0")
        root_at = args.index("--root")
        module = any(
            arg == "siqe_quest.runtime"
            or 'runpy.run_module("siqe_quest.runtime",run_name="__main__")' in arg
            for arg in args
        )
        return (
            module
            and args[root_at + 1] == str(store.root)
            and (proc / "cwd").resolve() == store.root
        )
    except (OSError, ValueError, IndexError, UnicodeError):
        return False


def _singleton_held(store: Store) -> bool:
    descriptor = os.open(
        _state_path(store, "worker.lock"), os.O_RDWR | os.O_CREAT, 0o600
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    finally:
        os.close(descriptor)


def _log(store: Store, action: str, **details: object) -> None:
    """Only callers' fixed, non-payload metadata enters the rotating log."""
    path = _state_path(store, "worker.log")
    if path.exists() and path.stat().st_size >= LOG_BYTES:
        os.replace(path, _state_path(store, "worker.log.1"))
    line = canonical_json({"at": utcnow(), "action": action, **details}) + "\n"
    if len(line.encode("utf-8")) > 4096:
        line = (
            canonical_json(
                {
                    "at": utcnow(),
                    "action": action,
                    "details": "oversize_metadata_omitted",
                }
            )
            + "\n"
        )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(line)


class Worker:
    """Single-consumer durable worker; injectable handler/clock enable offline tests."""

    def __init__(
        self,
        store: Store,
        handler: Callable | None = None,
        *,
        clock: Callable[[], float] = time.time,
        schedule: bool = True,
    ) -> None:
        self.store = store
        self.queue = EventQueue(store)
        self.clock = clock
        if type(schedule) is not bool:
            raise ValueError("schedule must be a boolean")
        self.schedule_enabled = schedule
        self.handler = handler or self._handle
        self.worker_id = "worker-" + uuid.uuid4().hex
        self.instance = uuid.uuid4().hex
        self.shutdown = threading.Event()
        self.identity: dict = {}
        self._lock_active = False
        self._network_used = False
        self.cap = max(1, min(8, int(store.config.get("max_tasks_per_cycle", 8))))
        self.network_cap = min(
            4, int(store.config.get("max_network_requests_per_cycle", 4))
        )
        self.interval = max(
            21600, int(store.config.get("review_interval_seconds", 21600))
        )
        with contextlib.closing(store.connection()) as conn, conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS runtime_schedule (
                    bucket INTEGER PRIMARY KEY, event_id TEXT, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runtime_checkpoints (
                    event_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                    result TEXT, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runtime_source_checks (
                    event_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                    result TEXT, updated_at TEXT NOT NULL);
            """)

    def _heartbeat(self, mode: str, **extra: object) -> dict:
        heartbeat = {
            "worker_id": self.worker_id,
            "instance": self.instance,
            "identity": self.identity,
            "root": str(self.store.root),
            "at": utcnow(),
            "epoch": self.clock(),
            "mode": mode,
            "queue_state": self.queue.state(),
            "queue": self.queue.stats(),
            "limits": {
                "tasks_per_cycle": self.cap,
                "network_requests_per_cycle": self.network_cap,
                "review_interval_seconds": self.interval,
                "automatic_llm_calls": 0,
            },
            **extra,
        }
        _atomic_json(_state_path(self.store, "worker-heartbeat.json"), heartbeat)
        return heartbeat

    def _schedule(self) -> None:
        if not self.schedule_enabled or self.queue.state() != "RUNNING":
            return
        bucket = int(self.clock() // self.interval)
        # Emit is idempotent across a crash between queue insertion and this table.
        # Do not hold a writer transaction while queue.emit opens its connection.
        with contextlib.closing(self.store.connection()) as conn:
            row = conn.execute(
                "SELECT event_id FROM runtime_schedule WHERE bucket=?", (bucket,)
            ).fetchone()
        if row and row["event_id"]:
            return
        event_id = self.queue.emit(
            {
                "event_type": "PERIODIC_RESEARCH_REVIEW",
                "idempotency_key": "runtime-review-" + str(bucket),
                "source_id": "runtime-scheduler",
                "source_version": "1",
                "observed_at": datetime.fromtimestamp(
                    bucket * self.interval, timezone.utc
                ).isoformat(),
                "task_budget": 1,
                "maximum_attempts": 1,
                "payload_reference": {"review_bucket": bucket, "research_only": True},
                "provenance_reference": {
                    "scheduler": "runtime",
                    "interval": self.interval,
                },
            }
        )
        with contextlib.closing(self.store.connection()) as conn, conn:
            conn.execute(
                "INSERT OR IGNORE INTO runtime_schedule VALUES(?,?,?)",
                (bucket, event_id, utcnow()),
            )

    def _source_review(self, event: dict) -> dict:
        if not self.schedule_enabled:
            return {
                "status": "BLOCKED",
                "prerequisite": "Offline follow-up cannot execute a scheduled network review; use the authorized daemon.",
            }
        event_id = event["event_id"]
        if self._network_used:
            return {
                "status": "BLOCKED",
                "prerequisite": "Network budget consumed this cycle; await next scheduled review.",
            }
        with contextlib.closing(self.store.connection()) as conn, conn:
            authorized = conn.execute(
                "SELECT 1 FROM runtime_schedule WHERE event_id=?", (event_id,)
            ).fetchone()
            prior = conn.execute(
                "SELECT * FROM runtime_source_checks WHERE event_id=?", (event_id,)
            ).fetchone()
            if prior:
                if prior["result"]:
                    return json.loads(prior["result"])
                return {
                    "status": "BLOCKED",
                    "prerequisite": "Interrupted freshness check has uncertain request count; wait for next scheduled interval.",
                }
            if not authorized:
                return {
                    "status": "BLOCKED",
                    "prerequisite": "Only the durable six-hour scheduler authorizes network freshness checks.",
                }
            conn.execute(
                "INSERT INTO runtime_source_checks VALUES(?,?,?,?)",
                (event_id, "STARTED", None, utcnow()),
            )
        self._network_used = True
        try:
            from .sources import SourceHunter

            self.store.authorize("research.source_review")
            result = SourceHunter(self.store).check_updates()
            if int(result.get("request_count", 0)) > self.network_cap:
                raise SafetyError("source review exceeded request budget")
        except Exception as exc:
            # Exception text may carry fetched URLs, credentials or content: retain class only.
            result = {
                "status": "BLOCKED",
                "error_class": type(exc).__name__,
                "prerequisite": "Successful authorized provider freshness check at the next interval.",
            }
        record = self.store.record(
            "source_health",
            event_id,
            {
                "event_id": event_id,
                "result": result,
                "checked_at": utcnow(),
                "request_cap": self.network_cap,
                "no_automatic_retry": True,
            },
        )
        final = {
            "status": result.get("status", "UNKNOWN"),
            "record_id": record["record_id"],
            "evidence": record["evidence"],
            "result": result,
        }
        with contextlib.closing(self.store.connection()) as conn, conn:
            conn.execute(
                "UPDATE runtime_source_checks SET status=?,result=?,updated_at=? WHERE event_id=?",
                ("FINISHED", canonical_json(final), utcnow(), event_id),
            )
        return final

    def _references(self, event: dict) -> tuple[list[dict], list[str]]:
        """Resolve only actual immutable record/blob references, never paths/URLs as code."""
        references: list[dict] = []
        errors: list[str] = []
        for field in ("payload_reference", "provenance_reference"):
            ref = event.get(field)
            if not isinstance(ref, dict):
                errors.append(field + ": requires structured evidence reference")
                continue
            try:
                if isinstance(ref.get("evidence"), dict):
                    blob = ref["evidence"]
                    self.store.read_blob(blob)
                    references.append(blob)
                elif "sha256" in ref and "path" in ref:
                    self.store.read_blob(ref)
                    references.append(ref)
                elif isinstance(ref.get("kind"), str) and isinstance(
                    ref.get("key"), str
                ):
                    record = self.store.get(ref["kind"], ref["key"])
                    if record is None:
                        errors.append(field + ": referenced record is absent")
                    else:
                        self.store.read_blob(record["evidence"])
                        references.append(record["evidence"])
                else:
                    errors.append(field + ": no verifiable evidence descriptor")
            except (OSError, ValueError, KeyError, SafetyError):
                errors.append(field + ": evidence failed verification")
        return references, errors

    def _experiment_review(self, event: dict) -> dict:
        """Inspect immutable locked outputs; never optimize or rerun the holdout."""
        experiment = None
        for field in ("payload_reference", "provenance_reference"):
            ref = event.get(field)
            if not isinstance(ref, dict):
                continue
            key = ref.get("experiment_id") or (
                ref.get("key") if ref.get("kind") == "experiment" else None
            )
            if isinstance(key, str):
                experiment = self.store.get("experiment", key)
            elif isinstance(ref.get("record_id"), str):
                experiment = next(
                    (
                        r
                        for r in self.store.records("experiment")
                        if r["record_id"] == ref["record_id"]
                    ),
                    None,
                )
            elif isinstance(ref.get("evidence"), dict):
                experiment = next(
                    (
                        r
                        for r in self.store.records("experiment")
                        if r["evidence"] == ref["evidence"]
                    ),
                    None,
                )
            if experiment:
                break
        if not experiment:
            return {
                "status": "BLOCKED",
                "prerequisite": "Reference an existing immutable experiment by kind/key, experiment_id, record_id or evidence descriptor.",
            }
        try:
            self.store.read_blob(experiment["evidence"])
            result = experiment["value"]
            experiment_id = result["experiment_id"]
            spec_record = self.store.get("strategy", experiment_id)
            hypothesis_record = self.store.get("hypothesis", experiment_id)
            dataset_record = self.store.get("dataset", result["dataset_id"])
            if not spec_record or not hypothesis_record or not dataset_record:
                raise ValueError("missing locked record")
            for record in (spec_record, hypothesis_record, dataset_record):
                self.store.read_blob(record["evidence"])
            spec = spec_record["value"]
            dataset = dataset_record["value"]
            manifest = dataset["manifest"]
            normalized = self.store.read_blob(manifest["normalized"])
            self.store.read_blob(manifest["raw"])
            if normalized != canonical_json(dataset["observations"]).encode():
                raise ValueError("normalized evidence differs")
            bound_id = digest(
                {
                    "series": "FXUSDCAD",
                    "raw": manifest["raw"]["sha256"],
                    "normalized": manifest["normalized"]["sha256"],
                }
            )
            if bound_id != result["dataset_id"] or dataset["dataset_id"] != bound_id:
                raise ValueError("dataset hash differs")
            if (
                result["spec"] != spec
                or result["hypothesis"] != hypothesis_record["value"]
            ):
                raise ValueError("locked specification differs")
            if (
                digest({"spec": spec, "observations": dataset["observations"]})
                != experiment_id
            ):
                raise ValueError("experiment identity differs")
            expected = copy.deepcopy(result)
            content_hash = expected["reproduction"]["result_sha256"]
            expected["reproduction"]["result_sha256"] = None
            if digest(expected) != content_hash:
                raise ValueError("result reproduction hash differs")
            from .research import audit_temporal

            comparisons = []
            defects = []
            negatives = []
            independent_temporal = {}
            for split, bounds in spec["splits"].items():
                modes = result["segments"][split]
                for mode in ("candidate", "buy_hold", "cash", "cost_control"):
                    run = modes[mode]
                    metrics = run["metrics"]
                    rows = run["equity"]
                    if not rows or any(
                        not bounds["start"] <= row["date"] <= bounds["end"]
                        for row in rows
                    ):
                        raise ValueError("missing or unbounded split equity")
                    net = rows[-1]["equity"] / run["initial_capital"] - 1
                    if not math.isfinite(net) or not math.isclose(
                        net, metrics["net_return"], abs_tol=1e-12
                    ):
                        defects.append(
                            split + ":" + mode + ": net return accounting mismatch"
                        )
                    fees = math.fsum(fill["fee"] for fill in run["fills"])
                    if not math.isclose(fees, metrics["fees_paid"], abs_tol=1e-9):
                        defects.append(split + ":" + mode + ": fee mismatch")
                    temporal = audit_temporal(dataset["observations"], run["signals"])
                    independent_temporal[split + ":" + mode] = temporal
                    if not temporal["passed"]:
                        defects.append(split + ":" + mode + ": temporal audit failed")
                    if metrics["net_return"] < 0:
                        negatives.append(
                            {
                                "split": split,
                                "mode": mode,
                                "net_return": metrics["net_return"],
                            }
                        )
                candidate = modes["candidate"]["metrics"]
                baseline = modes["buy_hold"]["metrics"]
                difference = candidate["net_return"] - baseline["net_return"]
                if not math.isclose(
                    candidate["benchmark_relative_return"], difference, abs_tol=1e-12
                ):
                    defects.append(split + ": baseline-relative metric mismatch")
                if modes["cost_control"]["metrics"]["net_return"] >= 0:
                    defects.append(
                        split + ": fee-only negative control did not lose money"
                    )
                comparisons.append(
                    {
                        "split": split,
                        "locked_bounds": bounds,
                        "candidate_net_return": candidate["net_return"],
                        "buy_hold_net_return": baseline["net_return"],
                        "candidate_minus_buy_hold": difference,
                        "fees_paid": candidate["fees_paid"],
                        "slippage_paid": candidate["slippage_paid"],
                        "confidence_interval": modes["candidate"][
                            "confidence_interval"
                        ],
                        "cost_sensitivity": modes["candidate"]["sensitivity"],
                    }
                )
            if not result["audits"]["passed"]:
                defects.append("registered experiment audit failed")
            failed_relative = any(
                row["candidate_minus_buy_hold"] <= 0 for row in comparisons
            )
            if defects:
                question, priority = (
                    "Resolve numerical/temporal defects before interpreting economic results.",
                    "CRITICAL",
                )
            elif failed_relative:
                question, priority = (
                    "Explain locked SMA underperformance versus buy-and-hold, without holdout parameter search.",
                    "HIGH",
                )
            else:
                question, priority = (
                    "Can independent licensed executable quotes and known availability support a prospective test?",
                    "MEDIUM",
                )
            return {
                "status": "REVIEWED",
                "experiment_id": experiment_id,
                "verified_records": [
                    r["record_id"]
                    for r in (
                        experiment,
                        spec_record,
                        hypothesis_record,
                        dataset_record,
                    )
                ],
                "input_evidence": [
                    r["evidence"]
                    for r in (
                        experiment,
                        spec_record,
                        hypothesis_record,
                        dataset_record,
                    )
                ],
                "comparisons": comparisons,
                "negative_results": negatives,
                "registered_audits": result["audits"],
                "independent_temporal": independent_temporal,
                "methodology_defects": defects,
                "falsification": "IMPLEMENTATION_DEFECT"
                if defects
                else "NOT_SUPPORTED_ACROSS_LOCKED_SPLITS"
                if failed_relative
                else "NOT_FALSIFIED_IN_THIS_PROXY_ONLY",
                "next_question": {
                    "objective": question,
                    "priority": priority,
                    "maximum_attempts": 1,
                    "network_requests": 0,
                    "stop_condition": "Do not promote or retune on the sealed historical segment.",
                },
                "registration": "RETROSPECTIVE_LOCK_NOT_PROSPECTIVE",
                "evidence_level": "HISTORICAL_NONTRADABLE_REFERENCE_PROXY",
                "optimization_launched": False,
                "automatic_promotion": False,
            }
        except (ValueError, KeyError, TypeError, OSError, ZeroDivisionError) as exc:
            return {
                "status": "BLOCKED",
                "error_class": type(exc).__name__,
                "prerequisite": "Complete hash-consistent dataset/spec/hypothesis/experiment, split baselines and audit evidence.",
            }

    def _local_record_review(self, event: dict, kind: str) -> dict:
        """Validate provided registered source/knowledge evidence without fetching."""
        records = []
        for field in ("payload_reference", "provenance_reference"):
            ref = event.get(field)
            if (
                isinstance(ref, dict)
                and isinstance(ref.get("kind"), str)
                and isinstance(ref.get("key"), str)
            ):
                record = self.store.get(ref["kind"], ref["key"])
                if record:
                    self.store.read_blob(record["evidence"])
                    records.append(record)
        if not records:
            return {
                "status": "BLOCKED",
                "prerequisite": "A registered source or knowledge kind/key with immutable evidence.",
            }
        if kind in {"new_source_discovered", "source_updated"}:
            snapshots = [
                r for r in records if r["kind"] in {"source_snapshot", "dataset"}
            ]
            if not snapshots:
                return {
                    "status": "BLOCKED",
                    "prerequisite": "A retrieved source_snapshot or dataset record containing publisher, rights and raw response evidence.",
                }
            manifests = [
                r["value"]["manifest"] if r["kind"] == "dataset" else r["value"]
                for r in snapshots
            ]
            for manifest in manifests:
                target = urlsplit(manifest["request_url"])
                if (
                    target.scheme != "https"
                    or target.hostname != "www.bankofcanada.ca"
                    or target.username
                    or target.password
                    or manifest["publisher"] != "Bank of Canada"
                    or not manifest.get("policy")
                ):
                    raise SafetyError("source publisher or policy mismatch")
                self.store.read_blob(manifest["raw"])
                self.store.read_blob(manifest["normalized"])
            return {
                "status": "REVIEWED",
                "verified_source_manifests": [m.get("manifest_id") for m in manifests],
                "source_versions": [m["source_version"] for m in manifests],
                "verified_records": [r["record_id"] for r in snapshots],
                "duplicate_raw_versions": len(manifests)
                - len({m["raw"]["sha256"] for m in manifests}),
                "staleness_notices": [
                    {
                        "record_id": r["record_id"],
                        "source_update_record_id": update["record_id"],
                    }
                    for r in self.store.records("experiment")[-8:]
                    for update in self.store.records("source_update")[-8:]
                    if update["value"].get("changed")
                    and update["value"].get("dataset_id")
                    == r["value"].get("dataset_id")
                ],
                "preserved_versions": True,
                "network_requests": 0,
                "scope": "Local immutable provenance review, not a new access/license authorization or scientific rerun.",
            }
        from .knowledge import KnowledgeEngine

        engine = KnowledgeEngine(self.store)
        index = engine.index()
        lessons = [r for r in records if r["kind"] == "knowledge_lesson"]
        if not lessons or index["contradictions"]:
            return {
                "status": "BLOCKED",
                "contradictions": index["contradictions"],
                "promotion_blocked": True,
                "prerequisite": "An evidence-accepted scoped procedural lesson without unresolved contradictions.",
            }
        for record in lessons:
            value = record["value"]
            if (
                not value.get("acceptance", {}).get("passed")
                or not value.get("conditions")
                or not value.get("counterexamples")
            ):
                return {
                    "status": "BLOCKED",
                    "prerequisite": "Passed artifact checks, applicability conditions and counterexamples.",
                }
        return {
            "status": "REVIEWED",
            "verified_lesson_ids": [r["record_id"] for r in lessons],
            "scope": "Existing evidence-backed scoped procedural interpretations only.",
            "promotion_blocked": True,
            "automatic_promotion": False,
            "conditions": [r["value"]["conditions"] for r in lessons],
            "counterexamples": [r["value"]["counterexamples"] for r in lessons],
        }

    def _handle(self, event: dict, plans: list[dict]) -> dict:
        self.store.authorize("research.followup")
        refs, ref_errors = self._references(event)
        actions = []
        for plan in plans:
            kind = plan.get("kind", "")
            if kind not in HOOKS:
                raise SafetyError("unknown research handler kind")
            key = event["event_id"] + ":" + kind
            previous = self.store.get("runtime_review", key)
            if previous:
                value = previous["value"]
                actions.append(
                    {
                        "kind": kind,
                        "status": value["status"],
                        "record_id": previous["record_id"],
                        "evidence": previous["evidence"],
                        "prerequisite": value.get("prerequisite"),
                    }
                )
                continue
            value: dict = {
                "event_id": event["event_id"],
                "kind": kind,
                "objective": plan.get("objective"),
                "input_evidence": refs,
                "evidence_gaps": ref_errors,
                "automatic_promotion": False,
                "depth": event.get("depth", 0),
                "spawned_children": 0,
                "scientific_improvement": "NOT_MEASURED",
            }
            if kind == "session_initialized":
                value.update(
                    status="REVIEWED",
                    workspace=self.store.config.get("workspace_id"),
                    pending=self.queue.stats(),
                    interrupted=self._interrupted(),
                    resource_budget={"tasks": self.cap, "network": self.network_cap},
                    authorization="Only RUNNING queue claims may resume.",
                )
            elif kind == "periodic_research_review":
                source_health = self._source_review(event)
                source_status = source_health.get("status")
                source_checked = source_status in (
                    "UNCHANGED",
                    "CHANGED_REVALIDATION_REQUIRED",
                )
                value.update(
                    status="REVIEWED" if source_checked else "BLOCKED",
                    queue=self.queue.stats(),
                    source_health=source_health,
                    source_freshness=(
                        "UNCHANGED"
                        if source_status == "UNCHANGED"
                        else "REVALIDATION_REQUIRED"
                        if source_checked
                        else "NOT_VERIFIED"
                    ),
                    unresolved_review_ids=[
                        r["record_id"]
                        for r in self.store.records("runtime_review")[-8:]
                        if r["value"].get("status") == "BLOCKED"
                    ],
                    next_experiment="No automatic parameter search; inspect unresolved review records.",
                    budget={"task_cap": self.cap, "network_cap": self.network_cap},
                )
                if source_status == "CHANGED_REVALIDATION_REQUIRED":
                    value.update(
                        derived_artifacts_stale=True,
                        revalidation_required=True,
                        stale_dependencies=source_health.get("result", {}).get(
                            "stale_dependencies", []
                        ),
                        prerequisite="Upstream content changed; revalidate the source and rerun derived artifacts before treating them as current or promoting them.",
                    )
                elif source_status == "CHECK_FAILED":
                    value["prerequisite"] = (
                        "Source retrieval or permission validation failed; a successful authorized bounded source check is required at the next scheduled interval."
                    )
                elif source_status == "NO_SNAPSHOT":
                    value["prerequisite"] = (
                        "Acquire an authorized source snapshot before a bounded freshness check can establish its status."
                    )
                elif source_status == "BLOCKED":
                    value["prerequisite"] = source_health.get("prerequisite") or (
                        "Resolve the blocked authorized source check before claiming source freshness."
                    )
                elif not source_checked:
                    value["prerequisite"] = (
                        "Source check returned no recognized successful status; a successful authorized bounded source check is required before claiming source freshness."
                    )
            elif kind in {
                "retrieval_or_memory_contradiction",
                "knowledge_decay_detected",
            }:
                from .knowledge import KnowledgeEngine

                contradictions = KnowledgeEngine(self.store).contradictions()
                value.update(
                    status="BLOCKED",
                    contradictions=contradictions,
                    prerequisite="Independent dated source revalidation before supersession or promotion.",
                    preserve_history=True,
                    promotion_blocked=True,
                )
            elif kind == "tool_failure":
                value.update(
                    status="REVIEWED" if refs else "BLOCKED",
                    failure_class="reported_tool_failure",
                    retry_decision="No handler retry; queue bounded attempts apply.",
                    input_preserved=bool(refs),
                    fallback="No unapproved provider or external executable.",
                )
                if not refs:
                    value["prerequisite"] = (
                        "Verified redacted failure evidence before actual runtime error classification."
                    )
            elif kind == "safety_violation":
                value.update(
                    status="QUARANTINED",
                    action_prevented=True,
                    prerequisite="Explicit operator policy review; protected operations remain forbidden.",
                )
                self.store.audit(
                    "research.safety_quarantine", {"event_id": event["event_id"]}
                )
            elif kind == "knowledge_gap_detected":
                value.update(
                    status="BLOCKED",
                    proposal={
                        "source_plan": "Review registered official Bank of Canada metadata; no arbitrary payload URL fetch.",
                        "expected_cost": {"network_requests": 0, "llm_calls": 0},
                        "evaluation_method": "Verify domain, license, timestamps and coverage before acquisition.",
                        "maximum_attempts": 1,
                        "stop_condition": "Missing approved source or exhausted budget",
                    },
                    prerequisite="A scoped gap, approved licensed dataset and explicit acquisition authorization.",
                )
            elif kind in {"new_source_discovered", "source_updated"}:
                value.update(self._local_record_review(event, kind))
            elif kind == "new_research_paper":
                value.update(
                    status="BLOCKED",
                    reproduction_proposal={
                        "method": "Extract supported question/hypothesis and reproduce with locked independent evaluation.",
                        "data_available": "NOT_VERIFIED",
                        "claimed_results": "UNVERIFIED",
                    },
                    prerequisite="Verifiable full-text supporting spans, methodology and licensed reproduction dataset.",
                )
            elif kind == "new_market_event":
                value.update(
                    status="BLOCKED",
                    temporal_review={
                        "event_time": "NOT_VERIFIED",
                        "publication_time": "NOT_VERIFIED",
                        "historical_availability": "NOT_VERIFIED",
                    },
                    prerequisite="Verified event evidence, resolved instruments and dated pre-event forecast before comparison.",
                )
            elif kind == "new_knowledge_validated":
                value.update(self._local_record_review(event, kind))
            elif kind in {"experiment_completed", "backtest_failed"}:
                value.update(self._experiment_review(event))
            elif kind == "strategy_passed_research_gate":
                value.update(
                    status="BLOCKED",
                    strategies=[
                        r["record_id"] for r in self.store.records("strategy")[-8:]
                    ],
                    gate="NOT_VERIFIED",
                    prerequisite="Independent gate evidence, frozen spec, actual platform compilation/parity and forward-paper observations.",
                )
            value["action_outcomes"] = [
                {
                    "action": action,
                    "status": value["status"],
                    "evidence_note": "See this immutable review and input_evidence; no automatic scientific promotion.",
                }
                for action in plan.get("actions", [])
            ]
            record = self.store.record("runtime_review", key, value)
            actions.append(
                {
                    "kind": kind,
                    "status": value["status"],
                    "record_id": record["record_id"],
                    "evidence": record["evidence"],
                    "prerequisite": value.get("prerequisite"),
                }
            )
        return {
            "status": "BLOCKED"
            if any(a["status"] == "BLOCKED" for a in actions)
            else "REVIEWED",
            "actions": actions,
            "spawned_children": 0,
            "automatic_llm_calls": 0,
        }

    def _interrupted(self) -> list[str]:
        with contextlib.closing(self.store.connection()) as conn:
            return [
                row["event_id"]
                for row in conn.execute(
                    "SELECT event_id FROM runtime_checkpoints WHERE status='STARTED' LIMIT 8"
                )
            ]

    def run_once(self) -> dict:
        if self._lock_active:
            return self._cycle()
        descriptor = os.open(
            _state_path(self.store, "worker.lock"), os.O_RDWR | os.O_CREAT, 0o600
        )
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("a worker already owns this workspace") from exc
            return self._cycle()
        finally:
            os.close(descriptor)

    def _cycle(self) -> dict:
        self._network_used = False
        state = self.queue.state()
        if state != "RUNNING" or self.shutdown.is_set():
            return self._heartbeat("STOPPED" if state == "STOPPED" else "PAUSED")
        try:
            self._schedule()
        except Exception as exc:
            # Queue backpressure and schedule conflicts do not kill monitoring.
            self.store.audit(
                "research.schedule_blocked", {"error_class": type(exc).__name__}
            )
        processed = 0
        task_count = 0
        failures = 0
        while task_count < self.cap and not self.shutdown.is_set():
            event = self.queue.claim(self.worker_id, lease_seconds=120)
            if event is None:
                break
            event_id = event["event_id"]
            task_count += 1
            try:
                plans = event.get("tasks") or self.queue.dispatch(event)
                if not plans or len(plans) > self.cap - task_count + 1:
                    raise SafetyError("plan exceeds remaining cycle budget")
                task_count += len(plans) - 1
                with contextlib.closing(self.store.connection()) as conn, conn:
                    checkpoint = conn.execute(
                        "SELECT * FROM runtime_checkpoints WHERE event_id=?",
                        (event_id,),
                    ).fetchone()
                    if not checkpoint:
                        conn.execute(
                            "INSERT INTO runtime_checkpoints VALUES(?,?,?,?)",
                            (event_id, "STARTED", None, utcnow()),
                        )
                if checkpoint and checkpoint["status"] == "FINISHED":
                    result = json.loads(checkpoint["result"])
                else:
                    result = self.handler(event, plans)
                    if not isinstance(result, dict):
                        raise TypeError("handler must return structured result")
                    with contextlib.closing(self.store.connection()) as conn, conn:
                        conn.execute(
                            "UPDATE runtime_checkpoints SET status=?,result=?,updated_at=? WHERE event_id=?",
                            ("FINISHED", canonical_json(result), utcnow(), event_id),
                        )
                self.queue.complete(event_id, self.worker_id, result)
                processed += 1
                _log(
                    self.store,
                    "event_completed",
                    event_id=event_id,
                    result_status=result.get("status", "RECORDED"),
                )
            except Exception as exc:
                failures += 1
                error_class = type(exc).__name__
                self.store.audit(
                    "research.worker_failure",
                    {"event_id": event_id, "error_class": error_class},
                )
                try:
                    self.queue.fail(event_id, self.worker_id, error_class)
                except Exception as lease_error:
                    _log(
                        self.store,
                        "lease_not_owned",
                        event_id=event_id,
                        error_class=type(lease_error).__name__,
                    )
                _log(
                    self.store,
                    "event_failed",
                    event_id=event_id,
                    error_class=error_class,
                )
        return self._heartbeat(
            "ACTIVE" if processed else "IDLE",
            processed=processed,
            tasks=task_count,
            failures=failures,
        )

    def run(self, max_cycles: int | None = None, idle_seconds: float = 2) -> None:
        if max_cycles is not None and max_cycles < 0:
            raise ValueError("max_cycles must be nonnegative")
        idle_seconds = max(1.0, min(float(idle_seconds), 30.0))
        lock_path = _state_path(self.store, "worker.lock")
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        previous = {}
        acquired = False
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                self._lock_active = True
            except BlockingIOError as exc:
                raise RuntimeError("a worker already owns this workspace") from exc
            self.identity = _identity(os.getpid())
            pidfile = {
                "identity": self.identity,
                "instance": self.instance,
                "root": str(self.store.root),
                "started_at": utcnow(),
            }
            _atomic_json(_state_path(self.store, "worker.pid.json"), pidfile)
            if threading.current_thread() is threading.main_thread():
                for sig in (signal.SIGTERM, signal.SIGINT):
                    previous[sig] = signal.signal(sig, lambda *_: self.shutdown.set())
            self._heartbeat("READY")
            _log(self.store, "worker_started", instance=self.instance, pid=os.getpid())
            cycles = 0
            while not self.shutdown.is_set() and (
                max_cycles is None or cycles < max_cycles
            ):
                self.run_once()
                cycles += 1
                if self.queue.state() == "STOPPED":
                    break
                # Even active queues yield; finite CPU cap is cumulative over process life.
                self.shutdown.wait(idle_seconds)
            self._heartbeat("STOPPED" if self.queue.state() == "STOPPED" else "EXITED")
            _log(self.store, "worker_exited", instance=self.instance, cycles=cycles)
        finally:
            for sig, old in previous.items():
                signal.signal(sig, old)
            if acquired:
                own = _json_read(_state_path(self.store, "worker.pid.json"))
                if own.get("instance") == self.instance:
                    _state_path(self.store, "worker.pid.json").unlink(missing_ok=True)
                self._lock_active = False
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def service_status(root: str | Path) -> dict:
    store = Store(root)
    pidfile = _json_read(_state_path(store, "worker.pid.json"))
    heartbeat = _json_read(_state_path(store, "worker-heartbeat.json"))
    identity = pidfile.get("identity", {})
    singleton_held = _singleton_held(store)
    owned = bool(
        pidfile.get("root") == str(store.root)
        and isinstance(identity, dict)
        and _worker_process(store, identity)
        and singleton_held
    )
    matching = bool(
        owned
        and heartbeat.get("instance") == pidfile.get("instance")
        and heartbeat.get("identity") == identity
        and heartbeat.get("root") == str(store.root)
    )
    try:
        age = time.time() - float(heartbeat.get("epoch", 0))
    except (ValueError, TypeError):
        age = HEARTBEAT_TTL + 1
    fresh = matching and 0 <= age <= HEARTBEAT_TTL
    return {
        "running": bool(fresh and heartbeat.get("mode") not in {"STOPPED", "EXITED"}),
        "process_verified": owned,
        "heartbeat_verified": matching,
        "heartbeat_fresh": bool(fresh),
        "heartbeat_age_seconds": age if matching else None,
        "singleton_held": singleton_held,
        "identity": identity if owned else None,
        "instance": pidfile.get("instance") if owned else None,
        "queue_state": EventQueue(store).state(),
        "heartbeat": heartbeat,
        "root": str(store.root),
    }


def start_service(root: str | Path, *, timeout: float = 15) -> dict:
    store = Store(root)
    store.authorize("research.worker_start")
    queue = EventQueue(store)
    if queue.state() == "STOPPED":
        raise SafetyError("durable STOP requires explicit RESUME before startup")
    descriptor = os.open(
        _state_path(store, "service-start.lock"), os.O_RDWR | os.O_CREAT, 0o600
    )
    process = None
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        existing = service_status(store.root)
        if existing["process_verified"]:
            if existing["running"]:
                return existing
            raise RuntimeError(
                "existing owned worker is unhealthy; stop it before restart"
            )
        executable = Path(sys.executable).resolve(strict=True)
        source = Path(__file__).resolve().parents[1]
        if (
            not executable.is_file()
            or not (source / "siqe_quest" / "runtime.py").is_file()
        ):
            raise SafetyError("trusted Python executable or package path missing")
        instance = uuid.uuid4().hex
        # -I rejects cwd, environment PYTHONPATH and user-site injection. Only the
        # implementation's resolved package directory is introduced explicitly.
        bootstrap = (
            "import sys,runpy;sys.path.insert(0," + repr(str(source)) + ");"
            'runpy.run_module("siqe_quest.runtime",run_name="__main__")'
        )
        command = [
            str(executable),
            "-I",
            "-c",
            bootstrap,
            "--root",
            str(store.root),
            "--instance",
            instance,
            "worker",
        ]
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(store.root),
            "LANG": "C.UTF-8",
            "PYTHONUNBUFFERED": "1",
        }
        with open(_state_path(store, "worker-bootstrap.log"), "wb") as output:
            process = subprocess.Popen(
                command,
                cwd=store.root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=output,
                start_new_session=True,
                close_fds=True,
            )
        deadline = time.monotonic() + max(0.1, min(timeout, 30))
        while time.monotonic() < deadline:
            status = service_status(store.root)
            if (
                status["running"]
                and status["instance"] == instance
                and status["identity"]["pid"] == process.pid
            ):
                return status
            if process.poll() is not None:
                raise RuntimeError(
                    "worker exited before verified readiness; inspect bootstrap log"
                )
            time.sleep(0.05)
        # Popen owns this child; no arbitrary pidfile process is signaled.
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        raise TimeoutError("worker readiness identity/heartbeat timeout")
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def stop_service(root: str | Path, *, timeout: float = 30) -> dict:
    store = Store(root)
    queue = EventQueue(store)
    queue.control("STOP")
    status = service_status(store.root)
    identity = status.get("identity")
    if identity and _worker_process(store, identity):
        try:
            os.kill(identity["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + max(0.1, min(timeout, 30))
        while time.monotonic() < deadline and _owned(identity):
            time.sleep(0.05)
        if _owned(identity):
            # Escalation is permitted only with the original start identity still matching.
            try:
                os.kill(identity["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and _owned(identity):
                time.sleep(0.05)
    return service_status(store.root)


def _limits(store: Store) -> None:
    def cap(which: int, requested: int) -> None:
        soft, hard = resource.getrlimit(which)
        value = min(requested, hard) if hard != resource.RLIM_INFINITY else requested
        resource.setrlimit(which, (value, value))

    cap(
        resource.RLIMIT_AS,
        max(32, min(256, int(store.config.get("memory_mb", 256)))) * 1024 * 1024,
    )
    cap(
        resource.RLIMIT_CPU, max(1, min(120, int(store.config.get("cpu_seconds", 120))))
    )
    cap(resource.RLIMIT_NOFILE, 128)
    cap(resource.RLIMIT_FSIZE, 16 * 1024 * 1024)
    cap(resource.RLIMIT_CORE, 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--instance", help=argparse.SUPPRESS)
    parser.add_argument(
        "command",
        choices=["worker", "start", "status", "stop", "pause", "resume"],
        nargs="?",
        default="worker",
    )
    args = parser.parse_args(argv)
    store = Store(args.root)
    if args.command == "worker":
        _limits(store)
        worker = Worker(store)
        if args.instance:
            worker.instance = args.instance
        worker.run()
    elif args.command == "start":
        print(canonical_json(start_service(store.root)))
    elif args.command == "status":
        print(canonical_json(service_status(store.root)))
    elif args.command == "stop":
        print(canonical_json(stop_service(store.root)))
    else:
        print(
            canonical_json(
                {"queue_state": EventQueue(store).control(args.command.upper())}
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

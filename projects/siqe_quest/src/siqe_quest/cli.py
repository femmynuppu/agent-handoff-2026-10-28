"""Explicit finite research commands; only service start launches a daemon."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .core import Store, canonical_json
from .events import EventQueue
from .learning import Curriculum
from .mission import GAP, reproduce_mission, run_mission
from .runtime import Worker, service_status, start_service, stop_service
from .sources import SourceHunter


class CommandError(ValueError):
    """Invalid invocation, returned as sanitized machine-readable output."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # Argparse includes raw user arguments in its default error messages.
        raise CommandError("invalid command arguments")


def _positive(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 128:
        raise argparse.ArgumentTypeError("must be between 1 and 128")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = Parser(
        prog="siqe-quest",
        description="Evidence-bound research only; never live trading",
    )
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[2]),
        help="Workspace root; place this global option before the command",
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "doctor", help="Inspect local configuration and evidence, without network"
    )
    discover = commands.add_parser(
        "discover", help="Bounded official docs/catalog discovery"
    )
    discover.add_argument("gap", nargs="?", default=GAP)
    commands.add_parser(
        "acquire",
        help="Explicitly validate and retrieve the official reference dataset",
    )
    alpha = commands.add_parser(
        "alpha", help="Complete lifecycle using retained data by default"
    )
    alpha.add_argument(
        "--refresh",
        action="store_true",
        help="Explicit official discovery and fresh retrieval",
    )
    commands.add_parser(
        "reproduce", help="Offline exact numerical replay; no benchmark reexposure"
    )
    commands.add_parser(
        "evaluate", help="Execute public 21-case reference evaluation, not LLM mastery"
    )
    commands.add_parser(
        "report", help="Regenerate evidence-backed machine report bundle"
    )
    commands.add_parser(
        "status", help="Inspect durable queue and actual service identity"
    )
    worker = commands.add_parser(
        "worker", help="Finite foreground worker; default one cycle"
    )
    duration = worker.add_mutually_exclusive_group()
    duration.add_argument("--once", action="store_true")
    duration.add_argument("--max-cycles", type=_positive, default=1)
    service = commands.add_parser(
        "service", help="Explicit detached research service lifecycle"
    )
    service.add_argument("action", choices=("start", "stop", "status"))
    control = commands.add_parser(
        "control", help="Persist operator queue control; no implicit resume"
    )
    control.add_argument("action", choices=("STOP", "PAUSE", "RESUME"))
    return parser


def _run(args: argparse.Namespace, store: Store) -> dict:
    command = args.command
    if command == "doctor":
        counts = {
            kind: len(store.records(kind))
            for kind in (
                "source",
                "discovery_result",
                "dataset",
                "experiment",
                "mission",
                "verification",
            )
        }
        return {
            "status": "READY_RESEARCH_ONLY",
            "python": sys.version,
            "workspace": str(store.root),
            "records": counts,
            "queue": EventQueue(store).stats(),
            "service": service_status(store.root),
            "live_trading": False,
            "fine_tuning": False,
            "network_probed": False,
            "pine_compilation": "NOT_VERIFIED",
            "allowed_domains": store.config["allowed_domains"],
        }
    if command == "discover":
        return {
            "sources": SourceHunter(store).discover(args.gap),
            "scope": "bounded official Bank of Canada catalog",
        }
    if command == "acquire":
        dataset = SourceHunter(store).acquire_alpha()
        return {
            "dataset_id": dataset["dataset_id"],
            "manifest": dataset["manifest"],
            "observations_count": len(dataset["observations"]),
        }
    if command == "alpha":
        return run_mission(store, refresh=args.refresh)
    if command == "reproduce":
        return reproduce_mission(store)
    if command == "evaluate":
        return Curriculum(store).evaluate()
    if command == "report":
        from .reporting import export_bundle

        return export_bundle(store)
    if command == "status":
        return {
            "service": service_status(store.root),
            "queue": EventQueue(store).stats(),
            "latest_mission": [r["record_id"] for r in store.records("mission")[-1:]],
        }
    if command == "worker":
        worker = Worker(store)
        cycles = []
        for _ in range(1 if args.once else args.max_cycles):
            cycles.append(worker.run_once())
            if EventQueue(store).state() != "RUNNING":
                break
        return {
            "status": "FINITE_WORKER_RETURNED",
            "cycles": cycles,
            "queue": EventQueue(store).stats(),
            "resource_limits_applied_to_cli": False,
        }
    if command == "service":
        return {"start": start_service, "stop": stop_service, "status": service_status}[
            args.action
        ](store.root)
    if command == "control":
        return {"queue_state": EventQueue(store).control(args.action)}
    raise CommandError("unknown command")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if args.command is None:
            parser.print_help()
            return 0
        result = _run(args, Store(args.root))
        print(canonical_json(result))
        failed = result.get("status") in {"BLOCKED", "MISMATCH", "FAILED", "REFUSED"}
        return 1 if failed else 0
    except Exception as exc:
        # Do not echo exception text, payloads, URLs, tokens or filesystem secrets.
        print(
            canonical_json(
                {
                    "status": "ERROR",
                    "error_class": type(exc).__name__,
                    "message": "Command failed; inspect immutable redacted workspace audit evidence.",
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

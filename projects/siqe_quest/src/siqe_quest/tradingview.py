"""Portable Pine v6 strategy generation and evidence-conscious export comparisons.

No function invokes TradingView, compiles Pine, or submits orders. Comparisons
measure supplied observations; they do not authenticate their platform origin.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import math
import re
from typing import Any

from .core import canonical_json, digest


TOLERANCES = {
    "timestamps_seconds": 0.0,
    "indicators": {"absolute": 1e-8, "relative": 1e-8},
    "trade_prices": {"absolute": 0.00001, "relative": 0.0},
    "equity": {"absolute": 0.01, "relative": 1e-8},
    "drawdown": {"absolute": 1e-6, "relative": 0.0},
    "trade_count": 0,
}

LIMITATIONS = [
    "Bank of Canada FXUSDCAD observations are daily average reference rates, not chart OHLC or executable quotes.",
    "Python executes at the next observed reference rate; Pine market orders execute at the next chart bar open.",
    "Python schedules final-observation liquidation; Pine requires an explicit predeclared chart exit-signal timestamp and fills next open.",
    "Provider holidays, chart sessions, bar timestamps and feed vintages can differ; no missing observations are synthesized.",
    "Historical publication/first-availability timestamps are unknown; neither implementation establishes point-in-time tradability.",
    "TradingView fixed quantity is chart contracts/units; point value 1 and broker unit conventions require manual confirmation.",
    "Carry, financing, spread beyond configured slippage, liquidity and capacity are not modeled.",
    "Portable source and numerical export comparison do not constitute Pine compilation or TradingView execution evidence.",
]


def _validate_spec(spec: dict) -> None:
    if not isinstance(spec, dict):
        raise ValueError("spec must be a canonical strategy dictionary")
    supported = {
        "strategy_id": "quest-alpha-usdcad-sma",
        "version": 1,
        "instrument": "USD/CAD",
        "exchange": "OTC_FX_REFERENCE",
        "timeframe": "business_daily_reference",
        "indicator_parameters": {"fast": 20, "slow": 60},
        "entry_rules": "fast > slow",
        "exit_rules": "fast <= slow",
        "stop_loss": None,
        "take_profit": None,
        "position_sizing": {
            "units": 1000.0,
            "initial_capital": 10000.0,
            "currency": "CAD",
        },
        "trading_costs": {"commission_bps": 5.0},
        "slippage": {"ticks": 1, "tick_size": 0.00001},
        "session_rules": "observed_provider_dates_only",
        "execution_timing": "next_observation_reference_proxy",
        "warmup_period": 60,
        "risk_limits": {"leverage": False, "pyramiding": 0},
        "end_policy": "scheduled_final_observation_liquidation",
        "warmup_policy": "past_only_features_flat_segment_start",
        "splits": {
            "train": {"start": "2023-01-01", "end": "2023-12-31"},
            "validation": {"start": "2024-01-01", "end": "2024-12-31"},
            "sealedtest": {"start": "2025-01-01", "end": "2025-12-31"},
        },
    }
    # Equality of nested dictionaries deliberately rejects unimplemented stop,
    # risk, size, cost, and session options instead of quietly discarding them.
    for field, expected in supported.items():
        if field not in spec or spec[field] != expected:
            raise ValueError(
                f"Unsupported canonical strategy field: {field}; expected {expected!r}"
            )
    if (
        not isinstance(spec.get("data_vintage"), str)
        or not spec["data_vintage"].strip()
    ):
        raise ValueError("data_vintage must identify the pinned source dataset")
    for field in ("evaluation_start", "evaluation_end"):
        if field in spec:
            raise ValueError(
                f"Unsupported {field}: select one canonical Pine segment instead"
            )
    # Reject NaN/Infinity even in descriptive metadata; hash covers the full spec.
    canonical_json(spec)


def render_pine(spec: dict) -> str:
    """Render the supported canonical strategy; reject unsupported semantics.

    This is a chart-OHLC adaptation, NOT a claim that reference-rate data can be
    loaded as TradingView OHLC. The hash pins the complete requested specification.
    """
    _validate_spec(spec)
    return f"""//@version=6
// SIQE QUEST research only. Compilation: NOT_VERIFIED; parity: NOT_VERIFIED.
// canonical_spec_sha256: {digest(spec)}
// source_vintage_sha256: {digest(spec["data_vintage"])}
// Reference daily averages are NOT chart OHLC; next-open != next-reference fills.
strategy("SIQE QUEST USD/CAD SMA20/60 research", overlay = true,
     initial_capital = 10000, currency = currency.CAD,
     default_qty_type = strategy.fixed, default_qty_value = 1000,
     pyramiding = 0, commission_type = strategy.commission.percent,
     commission_value = 0.05, slippage = 1, margin_long = 100, margin_short = 100,
     process_orders_on_close = false, calc_on_every_tick = false,
     calc_on_order_fills = false, use_bar_magnifier = false)

// Research splits are locked retrospectively, not prospectively preregistered.
segment = input.string("Test 2025", "Isolated research segment",
     options = ["Train 2023", "Validation 2024", "Test 2025"])
startYear = segment == "Train 2023" ? 2023 : segment == "Validation 2024" ? 2024 : 2025
startTime = timestamp("America/Toronto", startYear, 1, 1, 0, 0)
endTime = timestamp("America/Toronto", startYear + 1, 1, 1, 0, 0)
inSegment = time >= startTime and time < endTime
// Set BEFORE running: opening timestamp of penultimate chart bar in chosen year.
// Its confirmed-close exit fills at final chart open, not final reference average.
exitSignalTime = input.time(0, "Required scheduled exit SIGNAL bar timestamp")
scheduledExit = time >= exitSignalTime

if barstate.isfirst
    if syminfo.type != "forex" or syminfo.basecurrency != "USD" or syminfo.currency != "CAD"
        runtime.error("Use a standard USD/CAD forex chart, not an inverse or derivative.")
    if not timeframe.isdaily or timeframe.multiplier != 1 or not chart.is_standard
        runtime.error("Use standard one-day OHLC bars; synthetic/intraday charts unsupported.")
    if math.abs(syminfo.mintick - 0.00001) > 0.0000000001 or math.abs(syminfo.pointvalue - 1.0) > 0.0000000001
        runtime.error("Expected tick size 0.00001 and point value 1; review unit conventions.")
    if exitSignalTime < startTime or exitSignalTime >= endTime
        runtime.error("Set the scheduled exit SIGNAL timestamp inside the selected segment before running.")

fast = ta.sma(close, 20)
slow = ta.sma(close, 60)
warmed = bar_index >= 59 and not na(fast) and not na(slow)
entryCondition = warmed and fast > slow
exitCondition = warmed and fast <= slow
confirmed = barstate.isconfirmed and warmed and inSegment
// Orders are market orders, created on confirmed close and filled next chart open.
if confirmed
    if scheduledExit
        if strategy.position_size > 0
            strategy.close("Long", comment = "Scheduled segment liquidation")
    else
        if entryCondition and strategy.position_size == 0
            strategy.entry("Long", strategy.long, qty = 1000)
        if exitCondition and strategy.position_size > 0
            strategy.close("Long")

plot(fast, "SIQE fast SMA20", color = color.teal)
plot(slow, "SIQE slow SMA60", color = color.orange)
plot(confirmed ? (entryCondition ? 1 : 0) : na, "SIQE entry condition", display = display.data_window)
plot(confirmed ? (exitCondition ? 1 : 0) : na, "SIQE exit condition", display = display.data_window)
plot(confirmed ? (entryCondition ? 1 : 0) : na, "SIQE long target", display = display.data_window)
plot(confirmed ? (scheduledExit ? 1 : 0) : na, "SIQE scheduled liquidation condition", display = display.data_window)
plot(time, "SIQE bar timestamp ms", display = display.data_window)
plot(strategy.equity, "SIQE equity CAD", display = display.data_window)
var float peakEquity = 10000.0
peakEquity := math.max(peakEquity, strategy.equity)
plot(strategy.equity / peakEquity - 1.0, "SIQE drawdown fraction", display = display.data_window)
// No same-close execution or last-bar hindsight; scheduled exit still uses next open.
// No request.security(), imports, lookahead, live routing or direct webhook delivery.
"""


def _number(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def _timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO date or timezone-aware timestamp")
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value).isoformat()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone required")
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid {label}: {value!r}") from exc


def _series(output: dict, name: str, keys: tuple[str, ...]) -> dict[tuple, dict] | None:
    if name not in output:
        return None
    rows = output[name]
    if not isinstance(rows, list):
        raise ValueError(f"{name} must be an exported list")
    indexed = {}
    for row in rows:
        if not isinstance(row, dict) or any(key not in row for key in keys):
            raise ValueError(f"{name} row requires {keys}")
        identity = tuple(_timestamp(row[key], f"{name}.{key}") for key in keys)
        if identity in indexed:
            raise ValueError(f"Duplicate {name} timestamp identity: {identity}")
        indexed[identity] = row
    return indexed


def _compare_series(
    left: dict,
    right: dict,
    name: str,
    keys: tuple[str, ...],
    fields: dict[str, dict | None],
) -> dict:
    a, b = _series(left, name, keys), _series(right, name, keys)
    result: dict[str, Any] = {
        "status": "NOT_TESTED",
        "python_count": None if a is None else len(a),
        "tradingview_count": None if b is None else len(b),
        "missing_in_python": [],
        "missing_in_tradingview": [],
        "fields": {},
    }
    if a is None or b is None:
        return result
    result["missing_in_python"] = [list(k) for k in sorted(b.keys() - a.keys())]
    result["missing_in_tradingview"] = [list(k) for k in sorted(a.keys() - b.keys())]
    different = bool(result["missing_in_python"] or result["missing_in_tradingview"])
    incomplete = not a or not b
    for field, tolerance in fields.items():
        compared, missing, mismatches = 0, 0, 0
        maximum = None
        for identity in sorted(a.keys() & b.keys()):
            x, y = a[identity], b[identity]
            if field not in x or field not in y:
                missing += 1
                continue
            xv, yv = x[field], y[field]
            compared += 1
            if tolerance is None:
                if not isinstance(xv, bool) or not isinstance(yv, bool):
                    raise ValueError(f"{name}.{field} must be boolean")
                mismatches += xv != yv
            elif xv is None or yv is None:
                # SMA warmup legitimately has no value; one-sided null differs.
                if name != "signals":
                    raise ValueError(f"{name}.{field} cannot be null")
                if xv is not None:
                    _number(xv, field)
                if yv is not None:
                    _number(yv, field)
                mismatches += (xv is None) != (yv is None)
            else:
                xv, yv = _number(xv, field), _number(yv, field)
                error = abs(xv - yv)
                maximum = error if maximum is None else max(maximum, error)
                allowed = tolerance["absolute"] + tolerance["relative"] * max(
                    abs(xv), abs(yv)
                )
                mismatches += error > allowed
        result["fields"][field] = {
            "compared": compared,
            "missing": missing,
            "mismatches": mismatches,
            "max_absolute_error": maximum,
        }
        different |= bool(mismatches)
        incomplete |= bool(missing)
    result["status"] = (
        "DIFFERENT" if different else "INCOMPLETE" if incomplete else "MATCH"
    )
    return result


def parity_report(python_output: dict, tradingview_output: dict | None = None) -> dict:
    """Measure normalized external exports, never manufacture platform proof.

    Inputs contain signals(date,fast,slow,entry_condition,exit_condition), closed
    trades(entry_date,exit_date,entry_price,exit_price), equity(date,equity,
    drawdown), and optional assumptions/provenance mappings. Dates must retain
    real export precision/timezone; a date is not silently matched to a timestamp.
    Empty/missing categories cannot prove agreement. Tolerances are fixed below.
    """
    if not isinstance(python_output, dict) or (
        tradingview_output is not None and not isinstance(tradingview_output, dict)
    ):
        raise ValueError("Outputs must be dictionaries")
    report: dict[str, Any] = {
        "compilation_status": "NOT_VERIFIED",
        "parity_status": "NOT_VERIFIED",
        "gate": "NOT_TESTED",
        "comparison_status": "NOT_TESTED",
        "tolerances": {
            key: dict(value) if isinstance(value, dict) else value
            for key, value in TOLERANCES.items()
        },
        "limitations": list(LIMITATIONS),
        "comparisons": {},
        "assumption_mismatches": [],
        "platform_origin_verified": False,
        "evidence_note": "No TradingView compiler/account is invoked. Supplied exports require independent provenance review.",
    }
    if tradingview_output is None:
        return report
    canonical_json(python_output)
    canonical_json(tradingview_output)
    for output in (python_output, tradingview_output):
        for name in ("assumptions", "provenance"):
            if name in output and not isinstance(output[name], dict):
                raise ValueError(f"{name} must be a dictionary")
    report["external_provenance"] = tradingview_output.get("provenance", {})
    report["supplied_python_output_sha256"] = digest(python_output)
    report["supplied_external_output_sha256"] = digest(tradingview_output)
    report["comparisons"] = {
        "signals": _compare_series(
            python_output,
            tradingview_output,
            "signals",
            ("date",),
            {
                "fast": TOLERANCES["indicators"],
                "slow": TOLERANCES["indicators"],
                "entry_condition": None,
                "exit_condition": None,
            },
        ),
        "trades": _compare_series(
            python_output,
            tradingview_output,
            "trades",
            ("entry_date", "exit_date"),
            {
                "entry_price": TOLERANCES["trade_prices"],
                "exit_price": TOLERANCES["trade_prices"],
            },
        ),
        "equity": _compare_series(
            python_output,
            tradingview_output,
            "equity",
            ("date",),
            {"equity": TOLERANCES["equity"], "drawdown": TOLERANCES["drawdown"]},
        ),
    }
    assumptions_a, assumptions_b = (
        python_output.get("assumptions", {}),
        tradingview_output.get("assumptions", {}),
    )
    for key in sorted(assumptions_a.keys() | assumptions_b.keys()):
        if (
            key not in assumptions_a
            or key not in assumptions_b
            or assumptions_a[key] != assumptions_b[key]
        ):
            report["assumption_mismatches"].append(
                {
                    "field": key,
                    "python": assumptions_a.get(key),
                    "tradingview": assumptions_b.get(key),
                    "missing_in_python": key not in assumptions_a,
                    "missing_in_tradingview": key not in assumptions_b,
                }
            )
    trades = report["comparisons"]["trades"]
    a_count, b_count = trades["python_count"], trades["tradingview_count"]
    report["trade_count_difference"] = (
        None if a_count is None or b_count is None else b_count - a_count
    )
    statuses = [entry["status"] for entry in report["comparisons"].values()]
    different = "DIFFERENT" in statuses or bool(report["assumption_mismatches"])
    incomplete = (
        any(status in ("NOT_TESTED", "INCOMPLETE") for status in statuses)
        or not assumptions_a
        or not assumptions_b
    )
    report["comparison_status"] = (
        "DIFFERENT" if different else "INCOMPLETE" if incomplete else "MATCH"
    )
    if different:
        report["parity_status"], report["gate"] = "DIFFERENT", "FAILED"
    # Even exact Python self-comparison cannot turn into platform verification.
    return report

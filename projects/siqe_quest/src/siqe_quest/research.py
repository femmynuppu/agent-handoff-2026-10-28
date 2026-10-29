"""Locked, retrospective reference-rate experiments; not executable FX backtests.

All fills below are accounting proxies on observed daily averages. Unknown historical
publication times remain unknown. No carry, financing, intraday OHLC or calendar is
inferred. Public APIs are deterministic except immutable store registration metadata.
"""

from __future__ import annotations

import copy
from datetime import date, datetime
import math
import random
import statistics

from .core import Store, canonical_json, digest


MODES = ("candidate", "buy_hold", "cash", "cost_control")
LIMITATIONS = [
    "Bank of Canada indicative daily average reference rates are not tradable fills.",
    "Publication and historical first-availability times are unknown; no point-in-time claim.",
    "One-observation lag is a research convention, not proof of executable availability.",
    "No invented OHLC, missing-date fills, intraday ordering or exchange-calendar certainty.",
    "FX carry, interest on cash, financing, taxes and executable spread are omitted.",
    "Capacity and market impact are unknown; fixed costs are assumptions, not estimates.",
    "Retrospective locked specification is not prospective historical preregistration.",
    "Single instrument, three years and one fixed parameter pair cannot establish alpha.",
]


def alpha_spec(dataset_id: str) -> dict:
    """Return the complete fixed, unfitted common Python/Pine research specification."""
    if not isinstance(dataset_id, str) or not dataset_id:
        raise ValueError("dataset_id is required")
    return {
        "strategy_id": "quest-alpha-usdcad-sma",
        "version": 1,
        "instrument": "USD/CAD",
        "exchange": "OTC_FX_REFERENCE",
        "timeframe": "business_daily_reference",
        "data_vintage": dataset_id,
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
        "splits": {
            "train": {"start": "2023-01-01", "end": "2023-12-31"},
            "validation": {"start": "2024-01-01", "end": "2024-12-31"},
            "sealedtest": {"start": "2025-01-01", "end": "2025-12-31"},
        },
        "baseline_modes": list(MODES[1:]),
        "end_policy": "scheduled_final_observation_liquidation",
        "warmup_policy": "past_only_features_flat_segment_start",
        "annualization": {
            "observations_per_year": 252,
            "risk_free_rate": 0.0,
            "status": "descriptive_observation_time_assumption_not_calendar_fact",
        },
        "bootstrap": {
            "method": "paired_circular_moving_block",
            "block_length": 5,
            "replicates": 400,
            "seed": 1729,
            "confidence": 0.95,
            "minimum_observations": 20,
        },
        "parameter_selection": "fixed_educational_parameters_no_fitting_or_holdout_tuning",
        "limitations": list(LIMITATIONS),
    }


def _validated(observations: list[dict], spec: dict) -> tuple[list[float], list[str]]:
    # This engine implements one strategy, not an interpreter for arbitrary rules.
    supported = alpha_spec(spec.get("data_vintage", "validation"))
    if set(spec) - (set(supported) | {"evaluation_start", "evaluation_end"}):
        raise ValueError("unsupported strategy fields")
    for field in (
        "instrument",
        "exchange",
        "timeframe",
        "entry_rules",
        "exit_rules",
        "stop_loss",
        "take_profit",
        "session_rules",
        "execution_timing",
        "end_policy",
        "warmup_policy",
    ):
        if field not in spec or spec[field] != supported[field]:
            raise ValueError(f"unsupported {field}")
    for field in (
        "indicator_parameters",
        "position_sizing",
        "trading_costs",
        "slippage",
        "risk_limits",
        "annualization",
        "bootstrap",
    ):
        if not isinstance(spec.get(field), dict) or set(spec[field]) != set(
            supported[field]
        ):
            raise ValueError(f"unsupported {field} fields")
    if spec["position_sizing"]["currency"] != "CAD":
        raise ValueError("only fixed-unit CAD accounting supported")
    if spec["annualization"]["risk_free_rate"] != 0.0:
        raise ValueError("only zero risk-free rate supported")
    if spec["bootstrap"]["method"] != "paired_circular_moving_block":
        raise ValueError("unsupported bootstrap method")
    dates, values = [], []
    for row in observations:
        day = row["date"]
        parsed = date.fromisoformat(day)
        if parsed.isoformat() != day or parsed.weekday() >= 5:
            raise ValueError("noncanonical date or weekend observation")
        if dates and day <= dates[-1]:
            raise ValueError("observations must be unique and ascending")
        value = float(row["value"])
        if not math.isfinite(value) or value <= 0:
            raise ValueError("reference rates must be finite and positive")
        if row.get("complete") is False:
            raise ValueError("incomplete observation")
        if "normalized_value" in row and float(row["normalized_value"]) != value:
            raise ValueError("normalized value mismatch")
        dates.append(day)
        values.append(value)
    params = spec["indicator_parameters"]
    fast, slow = params["fast"], params["slow"]
    if type(fast) is not int or type(slow) is not int or not 0 < fast < slow:
        raise ValueError("invalid SMA windows")
    if type(spec["warmup_period"]) is not int or spec["warmup_period"] < slow:
        raise ValueError("warmup shorter than slow SMA")
    sizing = spec["position_sizing"]
    numbers = [
        sizing["units"],
        sizing["initial_capital"],
        spec["trading_costs"]["commission_bps"],
        spec["slippage"]["ticks"],
        spec["slippage"]["tick_size"],
    ]
    if not all(math.isfinite(float(x)) for x in numbers):
        raise ValueError("nonfinite accounting assumption")
    if min(numbers[:2]) <= 0 or min(numbers[2:]) < 0:
        raise ValueError("invalid sizing or costs")
    if spec["annualization"]["observations_per_year"] <= 0:
        raise ValueError("invalid annualization assumption")
    bootstrap = spec["bootstrap"]
    if (
        type(bootstrap["block_length"]) is not int
        or bootstrap["block_length"] < 1
        or type(bootstrap["replicates"]) is not int
        or bootstrap["replicates"] < 1
        or not 0 < bootstrap["confidence"] < 1
    ):
        raise ValueError("invalid bootstrap assumptions")
    if (
        spec["risk_limits"].get("leverage") is not False
        or spec["risk_limits"].get("pyramiding") != 0
    ):
        raise ValueError("only unlevered nonpyramiding research supported")
    return values, dates


def _engine(observations: list[dict], spec: dict, mode: str) -> dict:
    """Accounting engine. No bootstrap/sensitivity recursion occurs here."""
    if mode not in MODES:
        raise ValueError("unsupported mode")
    values, dates = _validated(observations, spec)
    start, end = (
        spec.get("evaluation_start", "0001-01-01"),
        spec.get("evaluation_end", "9999-12-31"),
    )
    active = [i for i, day in enumerate(dates) if start <= day <= end]
    initial = float(spec["position_sizing"]["initial_capital"])
    quantity = float(spec["position_sizing"]["units"])
    fee_rate = float(spec["trading_costs"]["commission_bps"]) / 10000
    slip = float(spec["slippage"]["ticks"]) * float(spec["slippage"]["tick_size"])
    cash = gross_cash = initial
    units = 0.0
    signals, fills, trades, equity, rejected = [], [], [], [], []
    pending = None
    entry = None
    peak = initial
    fast_n, slow_n = (
        spec["indicator_parameters"]["fast"],
        spec["indicator_parameters"]["slow"],
    )
    last = active[-1] if active else None
    previous_active = None
    exposure_periods = 0

    def fill(i: int, side: str, source: dict | None, reason: str) -> bool:
        nonlocal cash, gross_cash, units, entry
        ref = values[i]
        price = ref + slip if side == "buy" else ref - slip
        if price <= 0:
            raise ValueError("slippage exceeds positive exit reference")
        fee = quantity * price * fee_rate
        if side == "buy" and quantity * price + fee > cash:
            rejected.append(
                {"date": dates[i], "reason": "insufficient_cash_no_leverage"}
            )
            return False
        row = {
            "date": dates[i],
            "side": side,
            "units": quantity,
            "price": price,
            "reference": ref,
            "fee": fee,
            "signal_index": source["observation_index"] if source else None,
            "execution_index": i,
            "reason": reason,
        }
        fills.append(row)
        if source is not None:
            source["execution_index"] = i
            source["execution_date"] = dates[i]
        if side == "buy":
            cash -= quantity * price + fee
            gross_cash -= quantity * ref
            units = quantity
            entry = row
        else:
            cash += quantity * price - fee
            gross_cash += quantity * ref
            units = 0.0
            gross_pnl = quantity * (ref - entry["reference"])
            net_pnl = quantity * (price - entry["price"]) - entry["fee"] - fee
            trades.append(
                {
                    "entry_date": entry["date"],
                    "exit_date": dates[i],
                    "entry_price": entry["price"],
                    "exit_price": price,
                    "entry_reference": entry["reference"],
                    "exit_reference": ref,
                    "units": quantity,
                    "entry_fee": entry["fee"],
                    "exit_fee": fee,
                    "gross_pnl": gross_pnl,
                    "net_pnl": net_pnl,
                    "exit_reason": reason,
                }
            )
            entry = None
        return True

    for i in active:
        if units:
            exposure_periods += 1
        if pending is not None:
            target, source = pending
            if target and not units:
                fill(i, "buy", source, "lagged_signal")
            elif not target and units:
                fill(i, "sell", source, "lagged_signal")
        pending = None
        # A deliberately fee-only debit has no invented price movement or position.
        if mode == "cost_control" and previous_active is not None:
            charge = 2 * quantity * values[i] * fee_rate
            if charge > cash:
                raise ValueError("fee-only control exhausts cash")
            cash -= charge
            fills.append(
                {
                    "date": dates[i],
                    "side": "fee_only",
                    "units": quantity,
                    "price": values[i],
                    "reference": values[i],
                    "fee": charge,
                    "signal_index": previous_active,
                    "execution_index": i,
                    "reason": "deliberate_fee_only_mechanism_control",
                }
            )
        ready = i + 1 >= spec["warmup_period"]
        fast = (
            math.fsum(values[i - fast_n + 1 : i + 1]) / fast_n
            if i + 1 >= fast_n
            else None
        )
        slow = (
            math.fsum(values[i - slow_n + 1 : i + 1]) / slow_n
            if i + 1 >= slow_n
            else None
        )
        desired = (
            bool(ready and fast > slow) if mode == "candidate" else mode == "buy_hold"
        )
        signal = {
            "date": dates[i],
            "observation_index": i,
            "fast": fast,
            "slow": slow,
            "entry_condition": bool(ready and fast > slow),
            "exit_condition": bool(ready and fast <= slow),
            "signal": ("long" if desired else "flat")
            if ready or mode != "candidate"
            else "warmup",
            "target_units": quantity if desired else 0.0,
            "feature_max_index": i,
            "feature_start_index": max(0, i - slow_n + 1),
            "fast_window": fast_n,
            "slow_window": slow_n,
            "execution_index": None,
            "execution_date": None,
        }
        signals.append(signal)
        if mode in ("candidate", "buy_hold") and desired != bool(units):
            pending = (desired, signal)
        # Scheduled boundary liquidation is NOT a same-time signal-driven exit.
        if i == last and units:
            fill(i, "sell", None, "scheduled_end_liquidation")
        marked = cash + units * values[i]
        gross_marked = gross_cash + units * values[i]
        peak = max(peak, marked)
        equity.append(
            {
                "date": dates[i],
                "equity": marked,
                "gross_equity": gross_marked,
                "cash": cash,
                "units": units,
                "reference": values[i],
                "drawdown": marked / peak - 1.0,
            }
        )
        previous_active = i
    return {
        "mode": mode,
        "initial_capital": initial,
        "signals": signals,
        "fills": fills,
        "trades": trades,
        "equity": equity,
        "rejected_orders": rejected,
        "exposure_periods": exposure_periods,
        "final_units": units,
        "end_policy": spec["end_policy"],
        "limitations": list(LIMITATIONS),
        "control_label": "deliberate_fee_only_mechanism_sanity_not_alpha_failure"
        if mode == "cost_control"
        else None,
    }


def _returns(result: dict) -> list[float]:
    prior = result["initial_capital"]
    returns = []
    for row in result["equity"]:
        returns.append(row["equity"] / prior - 1.0 if prior > 0 else 0.0)
        prior = row["equity"]
    return returns


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * probability
    low, high = math.floor(index), math.ceil(index)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (
        index - low
    )


def _metrics(result: dict, spec: dict, baseline: dict) -> dict:
    rows, initial = result["equity"], result["initial_capital"]
    returns = _returns(result)
    n = len(returns)
    net = rows[-1]["equity"] / initial - 1 if n else 0.0
    gross = rows[-1]["gross_equity"] / initial - 1 if n else 0.0
    ann = float(spec["annualization"]["observations_per_year"])
    stdev = statistics.stdev(returns) if n > 1 else None
    mean = statistics.mean(returns) if n else None
    downside = (
        math.sqrt(math.fsum(min(0.0, r) ** 2 for r in returns) / n) if n else None
    )
    drawdown = -min([0.0] + [row["drawdown"] for row in rows])
    annual_return = (1 + net) ** (ann / n) - 1 if n >= 2 and net > -1 else None
    pnls = [trade["net_pnl"] for trade in result["trades"]]
    profits, losses = (
        math.fsum(max(0, p) for p in pnls),
        -math.fsum(min(0, p) for p in pnls),
    )
    var = _quantile(returns, 0.05)
    lower_tail = [r for r in returns if r <= var] if var is not None else []
    baseline_net = (
        baseline["equity"][-1]["equity"] / initial - 1 if baseline["equity"] else 0.0
    )
    notional = math.fsum(
        f["units"] * f["price"] for f in result["fills"] if f["side"] != "fee_only"
    )
    return {
        "gross_return": gross,
        "net_return": net,
        "benchmark_relative_return": net - baseline_net,
        "annualized_return": annual_return,
        "max_drawdown": drawdown,
        "volatility": stdev * math.sqrt(ann) if stdev is not None else None,
        "sharpe": mean / stdev * math.sqrt(ann) if stdev and mean is not None else None,
        "sortino": mean / downside * math.sqrt(ann)
        if downside and mean is not None
        else None,
        "calmar": annual_return / drawdown
        if drawdown and annual_return is not None
        else None,
        "profit_factor": profits / losses if losses > 0 else None,
        "hit_rate": sum(p > 0 for p in pnls) / len(pnls) if pnls else None,
        "turnover": notional / initial,
        "exposure": result["exposure_periods"] / max(1, n - 1),
        "tail_loss": {
            "return_quantile_05": var,
            "expected_shortfall_05": statistics.mean(lower_tail)
            if lower_tail
            else None,
            "worst_observation_return": min(returns) if returns else None,
        },
        "trade_distribution": {
            "count": len(pnls),
            "wins": sum(p > 0 for p in pnls),
            "losses": sum(p < 0 for p in pnls),
            "zero": sum(p == 0 for p in pnls),
            "mean_net_pnl": statistics.mean(pnls) if pnls else None,
            "median_net_pnl": statistics.median(pnls) if pnls else None,
            "min_net_pnl": min(pnls) if pnls else None,
            "max_net_pnl": max(pnls) if pnls else None,
        },
        "fees_paid": math.fsum(f["fee"] for f in result["fills"]),
        "slippage_paid": math.fsum(
            f["units"] * abs(f["price"] - f["reference"]) for f in result["fills"]
        ),
        "observations": n,
        "return_sampling": "consecutive_observed_reference_equity_including_flat_start",
        "annualization_assumptions": copy.deepcopy(spec["annualization"]),
        "capacity": {"status": "UNKNOWN", "reason": "no executable quotes or volume"},
        "undefined_policy": "null when denominator, sample size or closed trades are insufficient",
    }


def _paired_bootstrap(candidate: dict, baseline: dict, spec: dict) -> dict:
    differences = [a - b for a, b in zip(_returns(candidate), _returns(baseline))]
    config = spec["bootstrap"]
    n, block = len(differences), config["block_length"]
    output = {
        "method": config["method"],
        "estimand": "mean_observation_return_difference_vs_buy_hold",
        "confidence": config["confidence"],
        "n": n,
        "block_length": block,
        "replicates": config["replicates"],
        "seed": config["seed"],
        "mean_difference": statistics.mean(differences) if n else None,
        "lower": None,
        "upper": None,
        "p_value": None,
        "claim": "conditional_descriptive_interval_not_alpha_or_significance",
        "assumptions": [
            "paired aligned observation returns",
            "approximately stationary weakly dependent blocks",
            "fixed block length may miss long dependence and regime shifts",
            "no multiplicity correction; no confirmatory hypothesis test",
        ],
    }
    if n < config["minimum_observations"]:
        output["status"] = "INSUFFICIENT_SAMPLE"
        return output
    rng = random.Random(config["seed"])
    samples = []
    for _ in range(config["replicates"]):
        selected = []
        while len(selected) < n:
            start = rng.randrange(n)
            selected.extend(
                differences[(start + k) % n]
                for k in range(min(block, n - len(selected)))
            )
        samples.append(statistics.mean(selected))
    alpha = (1 - config["confidence"]) / 2
    output.update(
        status="DESCRIPTIVE_ONLY",
        lower=_quantile(samples, alpha),
        upper=_quantile(samples, 1 - alpha),
    )
    return output


def simulate(observations: list[dict], spec: dict, mode: str = "candidate") -> dict:
    """Run one flat-start segment, with past-only warmup and explicit terminal sale.

    Optional evaluation_start/evaluation_end bound the segment while observations
    before its start provide features only. Earlier positions/orders never carry in.
    Unsupported rule, sizing, stop and session semantics are rejected, never ignored.
    """
    result = _engine(observations, spec, mode)
    baseline = _engine(observations, spec, "buy_hold")
    result["metrics"] = _metrics(result, spec, baseline)
    result["daily_returns"] = _returns(result)
    result["confidence_interval"] = _paired_bootstrap(result, baseline, spec)
    scenarios = []
    for label, fee_multiplier, slip_multiplier in [
        ("zero_costs", 0, 0),
        ("double_commission", 2, 1),
        ("zero_slippage", 1, 0),
        ("double_slippage", 1, 2),
    ]:
        changed = copy.deepcopy(spec)
        changed["trading_costs"]["commission_bps"] *= fee_multiplier
        changed["slippage"]["ticks"] *= slip_multiplier
        alternative = _engine(observations, changed, mode)
        last = (
            alternative["equity"][-1]["equity"]
            if alternative["equity"]
            else alternative["initial_capital"]
        )
        scenarios.append(
            {
                "scenario": label,
                "commission_bps": changed["trading_costs"]["commission_bps"],
                "slippage_ticks": changed["slippage"]["ticks"],
                "net_return": last / alternative["initial_capital"] - 1,
            }
        )
    result["sensitivity"] = {
        "status": "ASSUMPTION_SCENARIOS_NOT_ESTIMATED_EXECUTION_COSTS",
        "scenarios": scenarios,
        "fixed_parameters": True,
    }
    result["temporal_audit"] = audit_temporal(observations, result["signals"])
    return result


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def audit_temporal(observations: list[dict], signal_records: list[dict]) -> dict:
    """Independently check feature dependencies, order lag and stated availability.

    Unknown first availability does not fail the proxy check and NEVER passes a
    point-in-time gate. Explicit availability is checked against decision_time and
    execution_time when supplied; ambiguous timestamps fail closed.
    """
    errors, unknown = [], 0
    dates = [row["date"] for row in observations]
    for j, signal in enumerate(signal_records):
        index = signal.get("observation_index", signal.get("signal_index"))
        if type(index) is not int or not 0 <= index < len(observations):
            errors.append({"record": j, "error": "invalid_signal_index"})
            continue
        if signal.get("date", dates[index]) != dates[index]:
            errors.append({"record": j, "error": "signal_date_mismatch"})
        maximum = signal.get("feature_max_index")
        dependencies = signal.get("feature_indices", [])
        if type(maximum) is not int or maximum > index or maximum < 0:
            errors.append(
                {"record": j, "error": "future_or_unknown_feature_dependency"}
            )
        if any(type(k) is not int or not 0 <= k <= index for k in dependencies):
            errors.append({"record": j, "error": "future_feature_dependency"})
        for value_key, window_key in (("fast", "fast_window"), ("slow", "slow_window")):
            window = signal.get(window_key)
            if window is not None:
                if type(window) is not int or window <= 0:
                    errors.append({"record": j, "error": "invalid_indicator_window"})
                else:
                    expected = (
                        math.fsum(
                            float(observations[k]["value"])
                            for k in range(index - window + 1, index + 1)
                        )
                        / window
                        if index + 1 >= window
                        else None
                    )
                    actual = signal.get(value_key)
                    if (expected is None) != (actual is None) or (
                        expected is not None
                        and (
                            not isinstance(actual, (float, int))
                            or not math.isclose(
                                expected, actual, rel_tol=1e-12, abs_tol=1e-12
                            )
                        )
                    ):
                        errors.append(
                            {
                                "record": j,
                                "error": "noncausal_or_incorrect_" + value_key,
                            }
                        )
        execution = signal.get("execution_index")
        if execution is not None:
            if type(execution) is not int or not index < execution < len(observations):
                errors.append(
                    {"record": j, "error": "same_observation_or_invalid_fill"}
                )
            elif signal.get("execution_date") != dates[execution]:
                errors.append({"record": j, "error": "execution_date_mismatch"})
        row = observations[index]
        first = signal.get("feature_start_index", index)
        if type(first) is not int or not 0 <= first <= index:
            errors.append({"record": j, "error": "invalid_feature_start"})
            first = index
        timestamps = [signal.get("feature_available_at")]
        if row.get("available_at") is None:
            unknown += 1
        for dependency in observations[first : index + 1]:
            timestamps.extend(
                (dependency.get("available_at"), dependency.get("publication_time"))
            )
        for timestamp in timestamps:
            if timestamp is None:
                continue
            try:
                moment = _time(timestamp)
                if moment.tzinfo is None:
                    raise ValueError("availability requires explicit timezone")
                # Date-only comparison is deliberately weaker than PIT certification.
                if moment.date().isoformat() > dates[index]:
                    errors.append(
                        {"record": j, "error": "future_availability_at_decision"}
                    )
                for field in ("decision_time", "execution_time"):
                    if signal.get(field) and moment > _time(signal[field]):
                        errors.append(
                            {"record": j, "error": "availability_after_" + field}
                        )
            except (TypeError, ValueError):
                errors.append(
                    {"record": j, "error": "ambiguous_availability_timestamp"}
                )
    return {
        "passed": not errors,
        "errors": errors,
        "checked_signals": len(signal_records),
        "unknown_availability": unknown,
        "point_in_time_status": "NOT_VERIFIED",
        "scope": "recorded_dependency_and_proxy_order_timing_not_unobservable_historical_availability",
    }


def _audit_accounting(result: dict) -> dict:
    """Separate ledger reconstruction and analytical completed-trade conservation."""
    cash, units = result["initial_capital"], 0.0
    errors = []
    fills_by_date: dict[str, list[dict]] = {}
    for fill in result["fills"]:
        fills_by_date.setdefault(fill["date"], []).append(fill)
        if fill["side"] in ("buy", "sell"):
            adverse = (
                fill["price"] >= fill["reference"]
                if fill["side"] == "buy"
                else fill["price"] <= fill["reference"]
            )
            if not adverse:
                errors.append("favorable_slippage")
            if (
                fill["reason"] == "lagged_signal"
                and fill["execution_index"] <= fill["signal_index"]
            ):
                errors.append("same_observation_fill")
    for row in result["equity"]:
        for fill in fills_by_date.get(row["date"], []):
            notional = fill["units"] * fill["price"]
            if fill["side"] == "buy":
                cash -= notional + fill["fee"]
                units += fill["units"]
            elif fill["side"] == "sell":
                cash += notional - fill["fee"]
                units -= fill["units"]
            else:
                cash -= fill["fee"]
        if cash < -1e-8 or units < 0:
            errors.append("negative_cash_or_short_units")
        if not math.isclose(
            cash + units * row["reference"], row["equity"], abs_tol=1e-7
        ):
            errors.append("ledger_equity_mismatch")
        if not math.isclose(cash, row["cash"], abs_tol=1e-7) or units != row["units"]:
            errors.append("ledger_state_mismatch")
    for trade in result["trades"]:
        independent_gross = trade["units"] * (
            trade["exit_reference"] - trade["entry_reference"]
        )
        independent_net = (
            trade["units"] * (trade["exit_price"] - trade["entry_price"])
            - trade["entry_fee"]
            - trade["exit_fee"]
        )
        if not math.isclose(independent_gross, trade["gross_pnl"], abs_tol=1e-7):
            errors.append("trade_gross_sign_error")
        if not math.isclose(independent_net, trade["net_pnl"], abs_tol=1e-7):
            errors.append("trade_net_accounting_error")
    if result["equity"]:
        expected = result["initial_capital"] + math.fsum(
            t["net_pnl"] for t in result["trades"]
        )
        if result["mode"] == "cost_control":
            expected -= math.fsum(f["fee"] for f in result["fills"])
        if not math.isclose(expected, result["equity"][-1]["equity"], abs_tol=1e-7):
            errors.append("completed_trade_conservation_mismatch")
        expected_gross = result["initial_capital"] + math.fsum(
            t["gross_pnl"] for t in result["trades"]
        )
        if not math.isclose(
            expected_gross, result["equity"][-1]["gross_equity"], abs_tol=1e-7
        ):
            errors.append("gross_equity_conservation_mismatch")
        if result["mode"] == "buy_hold" and result["trades"]:
            trade = result["trades"][0]
            analytical = trade["units"] * (
                trade["exit_reference"] - trade["entry_reference"]
            )
            if not math.isclose(analytical, trade["gross_pnl"], abs_tol=1e-7):
                errors.append("buy_hold_analytical_sign_error")
    if units:
        errors.append("terminal_position_not_liquidated")
    return {
        "passed": not errors,
        "errors": errors,
        "scope": "independent_cash_ledger_adverse_cost_and_closed_trade_conservation",
    }


def run_alpha(store: Store, dataset: dict) -> dict:
    """Register before calculating; persist all observed signs, including failures.

    The lock is made now on an already historical vintage, not prospectively in
    2023. Repeating the same dataset produces identical record values and hashes.
    """
    store.authorize("simulate")
    spec = alpha_spec(dataset["dataset_id"])
    observations = dataset["observations"]
    _validated(observations, spec)
    manifest = dataset["manifest"]
    normalized = store.read_blob(manifest["normalized"])
    store.read_blob(manifest["raw"])
    if normalized != canonical_json(observations).encode("utf-8"):
        raise ValueError("observations differ from immutable normalized evidence")
    bound_dataset_id = digest(
        {
            "series": "FXUSDCAD",
            "raw": manifest["raw"]["sha256"],
            "normalized": manifest["normalized"]["sha256"],
        }
    )
    if dataset["dataset_id"] != bound_dataset_id:
        raise ValueError("dataset identity differs from raw and normalized evidence")
    if not observations:
        raise ValueError("alpha requires observed historical data")
    if any(
        not bounds["start"] <= row["date"] <= bounds["end"]
        for row in observations
        for bounds in [{"start": "2023-01-01", "end": "2025-12-31"}]
    ):
        raise ValueError("alpha dataset lies outside locked study years")
    experiment_id = digest({"spec": spec, "observations": observations})
    hypothesis = {
        "hypothesis_id": "h-" + experiment_id,
        "statement": "Fixed SMA20/60 lagged long exposure may improve reference-proxy mean returns over buy-and-hold.",
        "classification": "EXPLORATORY_RESEARCH_IDEA",
        "asset_class": "FX_REFERENCE_PROXY",
        "rationale": "Trend persistence is a testable behavioral conjecture, not established for these rates.",
        "expected_regime": "persistent directional trend; likely failure in reversals and sideways rates",
        "required_data": "FXUSDCAD observed reference rates, known historical availability unavailable",
        "signal_formulation": "SMA20(t)>SMA60(t); fixed1000USD; next observed reference proxy",
        "failure_conditions": [
            "nonpositive candidate-minus-buy_hold mean return",
            "cost fragility",
            "temporal or accounting audit failure",
        ],
        "baselines": list(MODES[1:]),
        "locked_splits": spec["splits"],
        "test_plan": "Report every disjoint year, no fitting, selection or repeated holdout optimization.",
        "registration_status": "RETROSPECTIVE_LOCK_BEFORE_THIS_IMPLEMENTATION_RUN_NOT_PROSPECTIVE",
        "statistical_assumptions": spec["bootstrap"],
        "resource_budget": {
            "bootstrap_replicates": 400,
            "block_length": 5,
            "models_fitted": 0,
        },
        "evidence_levels_not_claimed": [
            "prospective_out_of_sample",
            "forward_paper",
            "live_performance",
            "alpha",
        ],
    }
    # These append-only records must exist before the first engine call.
    hypothesis_record = store.record("hypothesis", experiment_id, hypothesis)
    strategy_record = store.record("strategy", experiment_id, spec)
    segments, temporal, accounting, controls, outcomes = {}, {}, {}, {}, []
    for segment, bounds in spec["splits"].items():
        segment_spec = copy.deepcopy(spec)
        segment_spec.update(
            evaluation_start=bounds["start"], evaluation_end=bounds["end"]
        )
        if not any(
            bounds["start"] <= row["date"] <= bounds["end"] for row in observations
        ):
            raise ValueError("missing observations for locked split " + segment)
        segments[segment] = {}
        for mode in MODES:
            result = simulate(observations, segment_spec, mode)
            segments[segment][mode] = result
            key = segment + ":" + mode
            temporal[key] = result["temporal_audit"]
            accounting[key] = _audit_accounting(result)
            net = result["metrics"]["net_return"]
            outcomes.append(
                {
                    "segment": segment,
                    "mode": mode,
                    "net_return": net,
                    "sign": "positive"
                    if net > 0
                    else "negative"
                    if net < 0
                    else "zero",
                    "evidence_level": "HISTORICAL_NONTRADABLE_REFERENCE_PROXY",
                }
            )
        control = segments[segment]["cost_control"]
        enough = len(control["equity"]) > 1
        controls[segment] = {
            "passed": enough and control["metrics"]["net_return"] < 0,
            "label": "mechanism_sanity_not_alpha_failure",
            "positive_fees": True,
        }
    planted = {
        "date": observations[0]["date"],
        "observation_index": 0,
        "feature_max_index": 1,
        "execution_index": 0,
        "execution_date": observations[0]["date"],
    }
    planted_report = audit_temporal(observations, [planted])
    # Independently perturb ledger equity to ensure the audit is not vacuous.
    corrupted = copy.deepcopy(segments["train"]["cash"])
    corrupted["equity"][0]["equity"] += 1
    planted_accounting = _audit_accounting(corrupted)
    planted_report["sample_rejected"] = not planted_report.pop("passed")
    planted_accounting["sample_rejected"] = not planted_accounting.pop("passed")
    audits = {
        "temporal": temporal,
        "accounting": accounting,
        "negative_control": controls,
        "planted_leak": {
            "passed": planted_report["sample_rejected"],
            "detection": planted_report,
        },
        "planted_accounting": {
            "passed": planted_accounting["sample_rejected"],
            "detection": planted_accounting,
        },
    }
    audits["passed"] = (
        all(a["passed"] for a in temporal.values())
        and all(a["passed"] for a in accounting.values())
        and all(a["passed"] for a in controls.values())
        and audits["planted_leak"]["passed"]
        and audits["planted_accounting"]["passed"]
    )
    result = {
        "experiment_id": experiment_id,
        "dataset_id": dataset["dataset_id"],
        "spec": spec,
        "hypothesis": hypothesis,
        "segments": segments,
        "audits": audits,
        "outcomes": outcomes,
        "limitations": list(LIMITATIONS),
        "scientific_claim": "DESCRIPTIVE_REFERENCE_PROXY_ONLY_NO_ALPHA_CLAIM",
        "registration": {
            "hypothesis_record_id": hypothesis_record["record_id"],
            "strategy_record_id": strategy_record["record_id"],
            "locked_before_simulation": True,
        },
        "reproduction": {
            "api": "run_alpha(Store(root), dataset)",
            "dataset_manifest": dataset["manifest"],
            "result_sha256": None,
        },
    }
    # Avoid self-referential hashing: hash all result content with this field null.
    result["reproduction"]["result_sha256"] = digest(result)
    experiment_record = store.record("experiment", experiment_id, result)
    manifest = {
        "dataset": dataset["manifest"],
        "spec": strategy_record["evidence"],
        "hypothesis": hypothesis_record["evidence"],
        "experiment": experiment_record["evidence"],
        "experiment_id": experiment_id,
        "result_sha256": result["reproduction"]["result_sha256"],
    }
    return {
        "experiment_id": experiment_id,
        "result": result,
        "manifest": manifest,
        "records": {
            "strategy": strategy_record,
            "hypothesis": hypothesis_record,
            "experiment": experiment_record,
        },
    }

"""Synthetic accounting/causality fixtures; never substitutes for provider evidence."""

import json
import copy
from datetime import date, timedelta
import math
import tempfile
import unittest
from unittest.mock import patch

from siqe_quest.core import Store, canonical_json, digest
from siqe_quest.research import (
    _audit_accounting,
    alpha_spec,
    audit_temporal,
    run_alpha,
    simulate,
)


def fixture(values, start="2024-01-01"):
    day = date.fromisoformat(start)
    rows = []
    for value in values:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        rows.append(
            {
                "date": day.isoformat(),
                "value": float(value),
                "available_at": None,
                "publication_time": None,
                "complete": True,
            }
        )
        day += timedelta(days=1)
    return rows


def short_spec():
    spec = alpha_spec("synthetic-test-only")
    spec["indicator_parameters"] = {"fast": 2, "slow": 3}
    spec["warmup_period"] = 3
    return spec


class ResearchTests(unittest.TestCase):
    def test_fixed_spec_is_fresh_complete_and_unfitted(self):
        spec = alpha_spec("vintage")
        self.assertEqual(spec["indicator_parameters"], {"fast": 20, "slow": 60})
        self.assertEqual(spec["position_sizing"]["initial_capital"], 10000)
        self.assertEqual(spec["splits"]["sealedtest"]["start"], "2025-01-01")
        self.assertIn("no_fitting", spec["parameter_selection"])
        spec["indicator_parameters"]["fast"] = 1
        self.assertEqual(alpha_spec("vintage")["indicator_parameters"]["fast"], 20)

    def test_hand_computed_buy_hold_cash_fees_and_adverse_sides(self):
        result = simulate(fixture([1, 2, 3, 4]), short_spec(), "buy_hold")
        trade = result["trades"][0]
        self.assertEqual(trade["entry_date"], "2024-01-02")
        self.assertEqual(trade["exit_date"], "2024-01-04")
        self.assertAlmostEqual(trade["entry_price"], 2.00001)
        self.assertAlmostEqual(trade["exit_price"], 3.99999)
        self.assertAlmostEqual(trade["entry_fee"], 1.000005)
        self.assertAlmostEqual(trade["exit_fee"], 1.999995)
        self.assertAlmostEqual(trade["gross_pnl"], 2000)
        self.assertAlmostEqual(trade["net_pnl"], 1996.98)
        self.assertAlmostEqual(result["equity"][1]["cash"], 7998.989995)
        self.assertAlmostEqual(result["equity"][1]["equity"], 9998.989995)
        self.assertAlmostEqual(result["equity"][-1]["equity"], 11996.98)
        self.assertAlmostEqual(result["metrics"]["gross_return"], 0.2)
        self.assertAlmostEqual(result["metrics"]["net_return"], 0.199698)
        self.assertAlmostEqual(result["metrics"]["slippage_paid"], 0.02)
        self.assertEqual(result["final_units"], 0)
        self.assertTrue(_audit_accounting(result)["passed"])

    def test_candidate_signal_at_t_fill_t_plus_one(self):
        result = simulate(fixture([1, 2, 3, 4, 5]), short_spec())
        signal = result["signals"][2]
        self.assertEqual(signal["date"], "2024-01-03")
        self.assertEqual(signal["fast"], 2.5)
        self.assertEqual(signal["slow"], 2)
        self.assertEqual(signal["execution_date"], "2024-01-04")
        self.assertEqual(result["trades"][0]["entry_date"], "2024-01-04")
        self.assertAlmostEqual(result["trades"][0]["net_pnl"], 995.48)
        self.assertTrue(result["temporal_audit"]["passed"])

    def test_cash_and_undefined_metrics_are_json_null(self):
        result = simulate(fixture([1, 2, 3]), short_spec(), "cash")
        self.assertEqual([r["equity"] for r in result["equity"]], [10000] * 3)
        for key in ("sharpe", "sortino", "calmar", "profit_factor", "hit_rate"):
            self.assertIsNone(result["metrics"][key])
        self.assertEqual(result["metrics"]["net_return"], 0)
        self.assertIn('"sharpe":null', canonical_json(result))
        empty = simulate([], short_spec(), "cash")
        self.assertIsNone(empty["metrics"]["volatility"])
        self.assertIsNone(empty["metrics"]["annualized_return"])
        self.assertEqual(empty["confidence_interval"]["status"], "INSUFFICIENT_SAMPLE")

    def test_fee_only_control_is_negative_not_alpha_strategy(self):
        result = simulate(fixture([2, 2, 2, 2]), short_spec(), "cost_control")
        self.assertEqual(result["trades"], [])
        self.assertAlmostEqual(result["equity"][-1]["equity"], 9994)
        self.assertAlmostEqual(result["metrics"]["gross_return"], 0)
        self.assertLess(result["metrics"]["net_return"], 0)
        self.assertIn("not_alpha_failure", result["control_label"])
        self.assertEqual(result["metrics"]["exposure"], 0)
        self.assertTrue(_audit_accounting(result)["passed"])

    def test_flat_segment_start_past_only_warmup(self):
        spec = short_spec()
        spec.update(evaluation_start="2024-01-04", evaluation_end="2024-01-05")
        result = simulate(fixture([1, 2, 3, 4, 5]), spec)
        self.assertEqual(len(result["equity"]), 2)
        self.assertEqual(result["equity"][0]["units"], 0)
        self.assertEqual(result["signals"][0]["slow"], 3)
        self.assertEqual(result["trades"][0]["entry_date"], "2024-01-05")
        self.assertAlmostEqual(result["trades"][0]["net_pnl"], -5.02)
        self.assertEqual(result["fills"][-1]["reason"], "scheduled_end_liquidation")

    def test_no_leverage_when_fixed_units_unaffordable(self):
        result = simulate(fixture([20, 20, 20]), short_spec(), "buy_hold")
        self.assertEqual(result["trades"], [])
        self.assertTrue(result["rejected_orders"])
        self.assertEqual(result["equity"][-1]["equity"], 10000)

    def test_adversarial_prefix_invariance(self):
        rows = fixture([1 + i * 0.001 + math.sin(i) * 0.01 for i in range(100)])
        spec = alpha_spec("synthetic")
        original = simulate(rows, spec)
        changed = copy.deepcopy(rows)
        for row in changed[75:]:
            row["value"] *= 3
        perturbed = simulate(changed, spec)
        prefix = simulate(rows[:75], spec)
        for i in range(74):
            for key in (
                "fast",
                "slow",
                "signal",
                "target_units",
                "entry_condition",
                "exit_condition",
            ):
                self.assertEqual(
                    original["signals"][i][key], perturbed["signals"][i][key]
                )
                self.assertEqual(original["signals"][i][key], prefix["signals"][i][key])
            self.assertEqual(original["equity"][i], perturbed["equity"][i])
            self.assertEqual(original["equity"][i], prefix["equity"][i])
        # Prefix terminal liquidation is intentionally different from an ongoing run.
        self.assertEqual(prefix["final_units"], 0)

    def test_temporal_audit_catches_same_time_future_and_lying_indicator(self):
        rows = fixture([1, 2, 3, 4, 5])
        signal = simulate(rows, short_spec())["signals"][2]
        same_time = copy.deepcopy(signal)
        same_time.update(execution_index=2, execution_date=rows[2]["date"])
        self.assertFalse(audit_temporal(rows, [same_time])["passed"])
        future = copy.deepcopy(signal)
        future["feature_max_index"] = 4
        self.assertFalse(audit_temporal(rows, [future])["passed"])
        future = copy.deepcopy(signal)
        future["feature_indices"] = [4]
        self.assertFalse(audit_temporal(rows, [future])["passed"])
        future = copy.deepcopy(signal)
        future["fast"] = 4.5
        self.assertFalse(audit_temporal(rows, [future])["passed"])
        rows[1]["available_at"] = "2024-01-05T18:00:00-05:00"
        self.assertFalse(audit_temporal(rows, [signal])["passed"])
        rows[1]["available_at"] = None
        self.assertEqual(
            audit_temporal(rows, [signal])["point_in_time_status"], "NOT_VERIFIED"
        )

    def test_timestamp_timezone_and_explicit_intraday_availability(self):
        rows = fixture([1, 2, 3])
        signal = {
            "date": rows[0]["date"],
            "observation_index": 0,
            "feature_max_index": 0,
            "execution_index": 1,
            "execution_date": rows[1]["date"],
            "decision_time": "2024-01-01T15:00:00+00:00",
        }
        rows[0]["available_at"] = "2024-01-01T16:00:00+00:00"
        self.assertFalse(audit_temporal(rows, [signal])["passed"])
        rows[0]["available_at"] = "2024-01-01T14:00:00"
        self.assertFalse(audit_temporal(rows, [signal])["passed"])

    def test_independent_accounting_audit_detects_planted_sign_and_equity_errors(self):
        result = simulate(fixture([1, 2, 3, 4]), short_spec(), "buy_hold")
        bad = copy.deepcopy(result)
        bad["trades"][0]["gross_pnl"] *= -1
        self.assertFalse(_audit_accounting(bad)["passed"])
        bad = copy.deepcopy(result)
        bad["equity"][1]["equity"] += 10
        self.assertFalse(_audit_accounting(bad)["passed"])
        bad = copy.deepcopy(result)
        bad["fills"][0]["price"] = 1.99999
        self.assertIn("favorable_slippage", _audit_accounting(bad)["errors"])

    def test_bootstrap_and_sensitivity_are_deterministic_conditional(self):
        rows = fixture([1 + i * 0.001 for i in range(90)])
        spec = alpha_spec("synthetic")
        first, second = simulate(rows, spec), simulate(rows, spec)
        self.assertEqual(canonical_json(first), canonical_json(second))
        interval = first["confidence_interval"]
        self.assertEqual(interval["status"], "DESCRIPTIVE_ONLY")
        self.assertIsNone(interval["p_value"])
        self.assertLessEqual(interval["lower"], interval["upper"])
        self.assertIn("not_alpha", interval["claim"])
        scenarios = {r["scenario"]: r for r in first["sensitivity"]["scenarios"]}
        self.assertGreaterEqual(
            scenarios["zero_costs"]["net_return"], first["metrics"]["net_return"]
        )
        self.assertLessEqual(
            scenarios["double_commission"]["net_return"], first["metrics"]["net_return"]
        )
        self.assertLessEqual(
            scenarios["double_slippage"]["net_return"], first["metrics"]["net_return"]
        )

    def test_simulate_rejects_unsupported_strategy_semantics(self):
        rows = fixture([1, 2, 3, 4, 5])
        overrides = {
            "entry_rules": "fast < slow",
            "exit_rules": "hold_until_stop",
            "stop_loss": {"percent": 0.01},
            "take_profit": {"percent": 0.02},
            "session_rules": "new_york_session_only",
            "warmup_policy": "carry_previous_segment_position",
            "execution_timing": "same_observation_close",
            "end_policy": "leave_position_open",
            "instrument": "EUR/USD",
            "exchange": "EXECUTABLE_FX",
            "timeframe": "hourly",
            "sizing_rules": "risk_one_percent",
        }
        for field, value in overrides.items():
            with self.subTest(field=field):
                spec = short_spec()
                spec[field] = value
                with self.assertRaises(ValueError):
                    simulate(rows, spec)
        for field, key, value in (
            ("position_sizing", "method", "percent_equity"),
            ("position_sizing", "currency", "USD"),
            ("risk_limits", "max_holding_observations", 1),
            ("risk_limits", "leverage", True),
            ("risk_limits", "pyramiding", 1),
            ("indicator_parameters", "indicator", "EMA"),
            ("trading_costs", "fixed_fee", 10),
            ("slippage", "model", "volume_dependent"),
        ):
            with self.subTest(field=field, key=key):
                spec = short_spec()
                spec[field][key] = value
                with self.assertRaises(ValueError):
                    simulate(rows, spec)

    def test_simulate_retains_supported_variable_assumptions(self):
        spec = short_spec()
        spec["position_sizing"].update(units=10.0, initial_capital=100.0)
        spec["trading_costs"]["commission_bps"] = 10.0
        spec["slippage"].update(ticks=2, tick_size=0.001)
        spec.update(evaluation_start="2024-01-04", evaluation_end="2024-01-05")
        result = simulate(fixture([1, 2, 3, 4, 5]), spec)
        trade = result["trades"][0]
        self.assertEqual(trade["units"], 10.0)
        self.assertAlmostEqual(trade["entry_price"], 5.002)
        self.assertAlmostEqual(trade["exit_price"], 4.998)
        self.assertAlmostEqual(trade["net_pnl"], -0.14)
        self.assertEqual(len(result["equity"]), 2)
        self.assertEqual(len(result["sensitivity"]["scenarios"]), 4)

    def test_invalid_observations_rejected_without_fabricated_gaps(self):
        rows = fixture([1, 2, 3])
        for bad in ([rows[0], rows[0]], list(reversed(rows)), fixture([float("nan")])):
            with self.assertRaises(ValueError):
                simulate(bad, short_spec())
        with self.assertRaises(ValueError):
            simulate([{"date": "2024-01-06", "value": 1}], short_spec())
        gap = [rows[0], rows[2]]
        self.assertEqual(len(simulate(gap, short_spec())["equity"]), 2)

    def test_registration_before_results_replay_and_evidence_binding(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            rows = []
            for year in (2023, 2024, 2025):
                rows.extend(
                    fixture([1.2 + i * 0.0002 for i in range(65)], f"{year}-01-02")
                )
            normalized = store.put_blob(
                canonical_json(rows).encode(), "application/json"
            )
            raw = store.put_blob(
                b"synthetic-test-only-not-provider-data", "application/octet-stream"
            )
            dataset_id = digest(
                {
                    "series": "FXUSDCAD",
                    "raw": raw["sha256"],
                    "normalized": normalized["sha256"],
                }
            )
            dataset = {
                "dataset_id": dataset_id,
                "observations": rows,
                "manifest": {"raw": raw, "normalized": normalized, "fixture": True},
            }
            original = simulate

            def checked(*args, **kwargs):
                self.assertEqual(len(store.records("hypothesis")), 1)
                self.assertEqual(len(store.records("strategy")), 1)
                return original(*args, **kwargs)

            with patch("siqe_quest.research.simulate", side_effect=checked):
                first = run_alpha(store, dataset)
            second = run_alpha(store, dataset)
            self.assertEqual(first, second)
            self.assertEqual(len(store.records("experiment")), 1)
            self.assertTrue(first["result"]["audits"]["passed"])
            self.assertEqual(len(first["result"]["outcomes"]), 12)
            self.assertTrue(first["result"]["audits"]["planted_leak"]["passed"])
            self.assertTrue(first["result"]["audits"]["planted_accounting"]["passed"])
            self.assertTrue(
                any(row["sign"] == "negative" for row in first["result"]["outcomes"])
            )
            persisted = json.loads(store.read_blob(first["manifest"]["experiment"]))
            self.assertEqual(persisted["value"], first["result"])
            tampered = copy.deepcopy(dataset)
            tampered["observations"][0]["value"] += 0.01
            with self.assertRaises(ValueError):
                run_alpha(store, tampered)

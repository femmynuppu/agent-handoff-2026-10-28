"""Numerical export comparison tests, not a TradingView compiler substitute."""

from copy import deepcopy
import math
import unittest

from siqe_quest.research import alpha_spec
from siqe_quest.tradingview import parity_report, render_pine


def exported_run():
    """Small explicit fixture; deliberately NOT labeled as platform execution."""
    return {
        "signals": [
            {
                "date": "2024-01-02",
                "fast": None,
                "slow": None,
                "entry_condition": False,
                "exit_condition": False,
            },
            {
                "date": "2024-04-02",
                "fast": 1.35,
                "slow": 1.34,
                "entry_condition": True,
                "exit_condition": False,
            },
            {
                "date": "2024-04-03",
                "fast": 1.33,
                "slow": 1.34,
                "entry_condition": False,
                "exit_condition": True,
            },
        ],
        "trades": [
            {
                "entry_date": "2024-04-03",
                "exit_date": "2024-04-04",
                "entry_price": 1.35001,
                "exit_price": 1.32999,
            }
        ],
        "equity": [
            {"date": "2024-04-03", "equity": 9999.0, "drawdown": -0.0001},
            {"date": "2024-04-04", "equity": 9978.64, "drawdown": -0.002136},
        ],
        "assumptions": {
            "data": "test-only",
            "execution": "next_observation_reference_proxy",
            "currency": "CAD",
            "drawdown_units": "signed_fraction",
        },
    }


class PineContractTests(unittest.TestCase):
    def test_supported_spec_has_deterministic_portable_artifact(self):
        spec = alpha_spec("dataset-a")
        source = render_pine(spec)
        self.assertIsInstance(source, str)
        self.assertEqual(source, render_pine(deepcopy(spec)))
        changed_vintage = deepcopy(spec)
        changed_vintage["data_vintage"] = "dataset-b"
        self.assertNotEqual(source, render_pine(changed_vintage))
        # A local string is not an independently compiled Pine program.
        self.assertEqual(parity_report({})["compilation_status"], "NOT_VERIFIED")

    def test_unsupported_strategy_semantics_rejected(self):
        changes = [
            ("stop_loss", 0.01),
            ("take_profit", 0.02),
            ("entry_rules", "cross over"),
            ("exit_rules", "never"),
            ("position_sizing", {"percent_of_equity": 10}),
            (
                "position_sizing",
                {"units": 2000, "initial_capital": 10000, "currency": "CAD"},
            ),
            ("trading_costs", {"commission_bps": 0}),
            ("slippage", {"ticks": 0, "tick_size": 0.00001}),
            ("risk_limits", {"leverage": True, "pyramiding": 0}),
            ("warmup_period", 10),
            ("session_rules", "all_days"),
            ("indicator_parameters", {"fast": 5, "slow": 10}),
            ("execution_timing", "same_close"),
            ("instrument", "CAD/USD"),
            ("end_policy", "leave_open"),
            ("warmup_policy", "future_features"),
            ("splits", {"train": {"start": "2024-01-01", "end": "2025-12-31"}}),
            ("evaluation_start", "2024-02-01"),
            ("evaluation_end", "2024-11-30"),
        ]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                spec = alpha_spec("dataset-a")
                spec[field] = value
                with self.assertRaisesRegex(ValueError, field):
                    render_pine(spec)

    def test_required_vintage_and_rule_fields(self):
        for field in (
            "data_vintage",
            "stop_loss",
            "take_profit",
            "entry_rules",
            "risk_limits",
        ):
            spec = alpha_spec("dataset-a")
            del spec[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                render_pine(spec)


class ParityComparisonTests(unittest.TestCase):
    def test_no_platform_results_no_platform_claim(self):
        report = parity_report(exported_run())
        self.assertEqual(report["compilation_status"], "NOT_VERIFIED")
        self.assertEqual(report["parity_status"], "NOT_VERIFIED")
        self.assertEqual(report["gate"], "NOT_TESTED")
        self.assertEqual(report["comparisons"], {})

    def test_self_comparison_can_match_but_cannot_prove_platform_execution(self):
        run = exported_run()
        report = parity_report(run, deepcopy(run))
        self.assertEqual(report["comparison_status"], "MATCH")
        self.assertEqual(report["parity_status"], "NOT_VERIFIED")
        self.assertEqual(report["gate"], "NOT_TESTED")
        self.assertFalse(report["platform_origin_verified"])
        self.assertEqual(report["trade_count_difference"], 0)
        self.assertEqual(
            report["comparisons"]["equity"]["fields"]["equity"]["max_absolute_error"], 0
        )

    def test_material_numerical_disagreements_are_measured(self):
        left, right = exported_run(), exported_run()
        right["signals"][1]["fast"] += 0.01
        right["signals"][1]["entry_condition"] = False
        right["trades"][0]["entry_price"] += 0.0001
        right["trades"][0]["exit_price"] -= 0.002
        right["equity"][1]["equity"] -= 50
        right["equity"][1]["drawdown"] -= 0.005
        report = parity_report(left, right)
        self.assertEqual(report["parity_status"], "DIFFERENT")
        self.assertEqual(report["gate"], "FAILED")
        signals, trades, equity = (
            report["comparisons"][name] for name in ("signals", "trades", "equity")
        )
        self.assertAlmostEqual(signals["fields"]["fast"]["max_absolute_error"], 0.01)
        self.assertEqual(signals["fields"]["entry_condition"]["mismatches"], 1)
        self.assertEqual(trades["fields"]["entry_price"]["mismatches"], 1)
        self.assertAlmostEqual(
            trades["fields"]["exit_price"]["max_absolute_error"], 0.002
        )
        self.assertEqual(equity["fields"]["equity"]["max_absolute_error"], 50)
        self.assertAlmostEqual(
            equity["fields"]["drawdown"]["max_absolute_error"], 0.005
        )

    def test_defined_tolerances_accept_small_rounding_not_large_errors(self):
        left, right = exported_run(), exported_run()
        right["signals"][1]["fast"] += 1e-9
        right["trades"][0]["exit_price"] += 0.000005
        right["equity"][0]["equity"] += 0.005
        right["equity"][0]["drawdown"] += 0.0000005
        report = parity_report(left, right)
        self.assertEqual(report["comparison_status"], "MATCH")
        self.assertEqual(report["tolerances"]["trade_prices"]["absolute"], 0.00001)

    def test_unmatched_timestamps_and_trade_counts_are_material(self):
        left, right = exported_run(), exported_run()
        right["signals"][1]["date"] = "2024-04-01"
        right["trades"] = []
        report = parity_report(left, right)
        self.assertEqual(report["trade_count_difference"], -1)
        self.assertEqual(
            report["comparisons"]["signals"]["missing_in_tradingview"], [["2024-04-02"]]
        )
        self.assertEqual(
            report["comparisons"]["signals"]["missing_in_python"], [["2024-04-01"]]
        )
        self.assertEqual(report["gate"], "FAILED")

    def test_timezone_equivalents_match_but_daily_date_not_assumed_midnight(self):
        left, right = exported_run(), exported_run()
        left["signals"][0]["date"] = "2024-01-02T01:00:00+01:00"
        right["signals"][0]["date"] = "2024-01-02T00:00:00Z"
        self.assertEqual(parity_report(left, right)["comparison_status"], "MATCH")
        left["signals"][0]["date"] = "2024-01-02"
        self.assertEqual(parity_report(left, right)["comparison_status"], "DIFFERENT")

    def test_assumption_difference_cannot_hide_behind_matching_numbers(self):
        left, right = exported_run(), exported_run()
        right["assumptions"]["execution"] = "next_chart_open"
        right["assumptions"]["data"] = "chart OHLC"
        report = parity_report(left, right)
        self.assertEqual(report["comparison_status"], "DIFFERENT")
        self.assertEqual(
            {m["field"] for m in report["assumption_mismatches"]}, {"data", "execution"}
        )

    def test_missing_exports_and_fields_remain_incomplete(self):
        left, right = exported_run(), exported_run()
        del right["signals"][1]["fast"]
        del right["equity"]
        report = parity_report(left, right)
        self.assertEqual(report["comparison_status"], "INCOMPLETE")
        self.assertEqual(report["gate"], "NOT_TESTED")
        self.assertEqual(
            report["comparisons"]["signals"]["fields"]["fast"]["missing"], 1
        )
        empty = parity_report(
            {"signals": [], "trades": [], "equity": []},
            {"signals": [], "trades": [], "equity": []},
        )
        self.assertEqual(empty["comparison_status"], "INCOMPLETE")

    def test_one_sided_indicator_null_is_difference(self):
        left, right = exported_run(), exported_run()
        right["signals"][0]["fast"] = 1.0
        report = parity_report(left, right)
        self.assertEqual(
            report["comparisons"]["signals"]["fields"]["fast"]["mismatches"], 1
        )

    def test_duplicate_timestamps_invalid_numbers_and_nonbool_conditions_rejected(self):
        bad = exported_run()
        bad["signals"].append(deepcopy(bad["signals"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            parity_report(exported_run(), bad)
        for value in (math.nan, math.inf, -math.inf, True, "1.35"):
            with self.subTest(value=value):
                bad = exported_run()
                bad["trades"][0]["entry_price"] = value
                with self.assertRaises(ValueError):
                    parity_report(exported_run(), bad)
        bad = exported_run()
        bad["signals"][0]["entry_condition"] = "false"
        with self.assertRaisesRegex(ValueError, "boolean"):
            parity_report(exported_run(), bad)

    def test_naive_or_invalid_timestamp_rejected(self):
        for value in ("2024-04-02T00:00:00", "2024-02-30", 1712016000000):
            bad = exported_run()
            bad["signals"][1]["date"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                parity_report(exported_run(), bad)


if __name__ == "__main__":
    unittest.main()

# SIQE backtesting standards

## Interpretation gate

An implemented calculation, a passing unit fixture, a historical proxy result,
a prospective out-of-sample result, forward-paper evidence and live evidence
are different evidence levels. QUEST ALPHA provides the first three only when
its real acquisition and experiment actually run. Bank of Canada averages are
indicative, not execution prices. There is no authentic point-in-time vintage,
carry model, quote/spread/volume series or independently certified exchange
calendar. Thus even favorable results cannot pass a tradable-alpha/live-return
gate. TradingView compilation/parity require actual external outputs and are
not established by the Python engine.

No invented observations, OHLC, source downloads, fills described as real,
positive outcomes, p-values or verified mastery are permitted. Negative
candidate outcomes are retained. A deliberate fee-only negative control is
reported as mechanism sanity, never mislabeled as evidence against alpha.

## Canonical measurement definitions

Let initial CAD cash be `C=10000`, marked net equity after each observed row be
`E[t]`, gross shadow equity `G[t]`, and `E[-1]=C`. All quantities below are
computed per flat-start reporting partition, not by silently concatenating
independently capitalized years. A scheduled final-observation liquidation
includes both side costs and produces zero final units. Closed trade net
profit is `1000*(exit_fill-entry_fill)-entry_fee-exit_fee`; gross profit uses
unmodified reference prices. Both entry and exit fees are on absolute slipped
notional. A fixed-size unaffordable buy is rejected, not funded by leverage.

| Field | Definition / undefined rule |
| --- | --- |
| gross_return | `G[last]/C - 1`; zero for no observations |
| net_return | `E[last]/C - 1`; zero for no observations |
| benchmark_relative_return | Net return minus matched buy-hold net return (difference, not ratio) |
| annualized_return | `(1+net_return) ** (252/n) - 1` for at least 2 observations and positive terminal wealth; otherwise null |
| drawdown row | `E[t]/max(C,E[0],...,E[t]) - 1`, nonpositive |
| max_drawdown | Positive maximum loss from running peak; zero for unchanged cash |
| volatility | Sample standard deviation (`n-1`) of observation returns times `sqrt(252)`; null if fewer than 2 observations |
| sharpe | Mean observation return / sample standard deviation times `sqrt(252)`; assumed zero risk-free return; null for zero deviation/insufficient observations |
| sortino | Mean return / `sqrt(mean(min(r,0)^2))` times `sqrt(252)`; null if no downside denominator |
| calmar | Annualized return / positive max drawdown; null if annualized return undefined or zero drawdown |
| profit_factor | Sum positive closed net trade P&Ls / absolute sum negative closed net trade P&Ls; null without losses, not infinity |
| hit_rate | Fraction of closed roundtrips with strictly positive net P&L; null without trades; zero trades count separately |
| turnover | Sum absolute executed buy/sell slipped notionals / initial capital (two-way turnover); excludes artificial fee-only debits |
| exposure | Inter-observation intervals held / `max(1,n-1)`; reference holdings are not leveraged capital exposure |
| fees_paid | Sum all executed fees, including fee-only control debits |
| slippage_paid | Sum `units*abs(fill-reference)`; fee-only debits have zero slippage |
| trade_distribution | Count, wins, losses, zero outcomes and mean/median/min/max net closed-trade P&L; null summaries without trades |
| tail_loss | Interpolated empirical 5% return quantile, mean of returns at or below it, and worst observation return; null for empty sample |
| capacity | `UNKNOWN`, because executable quotes and volume are unavailable |

Observation returns are `E[t]/E[t-1]-1`, including the initial cash mark and
terminal liquidation. They are not business-calendar-resampled returns.
`n` is the count of actual observed rows. The factor 252 is an explicit
observation-time convention for descriptive comparison, not evidence of a
known exchange calendar. Annualizing a short or nearly flat sample can be
unstable; display the sample size and assumption alongside annualized metrics.
Cash interest and risk-free returns being set to zero are unmeasured model
assumptions, not empirical financing facts. Undefined metrics serialize as
JSON null; never NaN or infinity. A zero-return/zero-drawdown strategy does not
have infinite Sharpe, Sortino, Calmar or profit factor.

## Confidence interval standard

For candidate and matched buy-hold, pair each observation's net equity return
and subtract. Report the mean paired observation-return difference, **not** a
confidence interval for terminal compounded-return difference. Reconstruct
400 mean statistics with a deterministic local PRNG (seed 1729), circular
moving blocks of 5 consecutive paired differences sampled with replacement,
truncating the final block to retain exactly `n` observations. Report linear
interpolated empirical 2.5% and 97.5% percentile bounds. Below 20 observations,
report `INSUFFICIENT_SAMPLE`, null bounds and no p-value.

This computation retains contemporaneous pairing and some short dependence,
but stationarity/weak dependence, block adequacy and coverage across regimes
are unverified. Circular wraparound is itself a modeling assumption. Flat
warmup intervals, few actual trades, structural change, one instrument and
three adjacent years can dominate inference. The intervals are explicitly
`DESCRIPTIVE_ONLY` and conditional on the observed vintage. Confidence bounds
excluding zero do not authorize an alpha/significance claim. There is no
confirmatory p-value, HAC test, multiplicity correction, purged cross-validation,
walk-forward fitting or fitted statistical model implemented here; those
methods must not be claimed merely because they exist in the wider catalog.

The same interface reports a descriptive interval for other modes against
buy-hold for completeness. Cash/control comparisons are not independent
research discoveries, and the buy-hold self-difference interval is identically
zero. No best model/year is selected from these outputs.

## Cost robustness and boundaries

The preregistered assumption scenarios are zero commission/slippage, double
commission with unchanged slippage, zero slippage with unchanged commission,
and double slippage with unchanged commission. Every scenario retains fixed
parameters, initial capital and risk constraints. The default five-basis-point
commission and one tick are not calibrated spread/cost estimates. FX carry,
market impact, taxes and cash interest remain omitted in every scenario.
Differences that cross cash affordability boundaries may change accepted
orders rather than being pure fee adjustments. Slippage must never improve a
buy/sell side. Extremely large slippage that makes a sale price nonpositive is
rejected. A deliberately fee-only control has no price/slippage movement.

Segments are disjoint in their evaluated observations, start flat, and use
only earlier rows for warmup. There is no label-fitting horizon, fitted
training target or overlapping forward-label sample to purge in this fixed
SMA study; this is not proof all possible leakage classes are eliminated.
Provider revisions and unknown historical availability prevent genuine PIT
certification even after index-level causality checks pass.

A prefix simulation and a longer simulation must have identical decisions,
indicators and equity strictly before the shorter endpoint's terminal
liquidation. Changing future reference values cannot change earlier decisions
or fills. A final-row boundary sale is allowed only as an explicitly scheduled
end policy, never as a signal-driven same-row fill. An entry requested on a
segment's first row cannot execute before the second observed row even when
60 warmup observations precede the segment.

## Independent checks and rejection

The temporal auditor independently recomputes recorded moving averages from
trailing observations; checks feature max/explicit dependency indices and
feature-start bounds; checks signal/execution date alignment and strict
execution-index lag; checks available/publication timestamps for all recorded
feature observations. Timezone-less availability timestamps fail closed.
Explicit decision/execution timestamps support stronger intraday comparisons;
without them, same-date availability establishes no historical certainty.
Unknown availability is counted and always leaves PIT `NOT_VERIFIED`.
Auditing cannot discover invisible dependencies in a fraudulent producer.

The separate accounting auditor reconstructs all cash debits/credits and
units from fills, recomputes marked equity, checks nonnegative cash/no shorting,
adverse slippage, strict nonterminal signal lag, individual trade gross/net
profit and final gross/net conservation. Buy-hold additionally has an analytic
reference endpoint sign check. It never calls the simulator to manufacture
its expected ledger. `run_alpha` plants a future/same-time signal and a
one-CAD cash-equity corruption: expected rejection must be observed. Fixtures
also plant favorable-slippage and reversed trade-profit errors. These controls
can detect material errors, but they do not independently establish provider
history accuracy or tradability.

An audit failure is preserved in result evidence and must block downstream
promotion. It is not suppressed to produce favorable research. Negative
control acceptance requires a strictly negative control net return in every
partition with at least two rows and positive fees. The artificial sample's
rejection is named `sample_rejected` to avoid confusing expected rejection
with a failing experiment acceptance gate.

## Exact reproduction and required operator checks

Public APIs are `alpha_spec(dataset_id)`, `simulate(observations, spec,
mode='candidate')`, `audit_temporal(observations, signals)` and
`run_alpha(store, dataset)`. See `SIQE_QUANT_RESEARCH_PROTOCOL.md` for complete
return/evidence shapes and persisted-dataset replay. Optional
`evaluation_start`/`evaluation_end` spec keys bound a reporting segment but
leave earlier observations available for features only. Unknown mode,
nonfinite/nonpositive reference values, out-of-order/duplicate/weekend rows,
incomplete observations and unsupported execution/risk conventions fail.

The assigned implementation includes synthetic unittest fixtures; those are
not real provider results. The repository suite has since run: 201 tests passed
with no failures or errors on 2026-10-27 (about 69.4 seconds); Ruff passed.
Actual QUEST ALPHA research used 747 source observations and its recorded run,
methodology, limitations, artifacts, and hashes are documented in
`docs/SIQE_FINAL_EXECUTION_REPORT.md`. The tests do not establish tradability,
authentic point-in-time availability, external platform behavior, or live returns.

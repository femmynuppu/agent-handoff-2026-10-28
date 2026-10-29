# SIQE QUEST TradingView Pine v6 laboratory

## Evidence boundary

`siqe_quest.tradingview.render_pine(spec)` produces portable native Pine v6
**strategy** source, not an uploaded, compiled or platform-backtested strategy.
There is no configured TradingView account/compiler or actual platform export in
this implementation assignment. Compilation and parity are **NOT_VERIFIED**;
the parity release gate is **NOT_TESTED**. A local test of Python comparison
arithmetic is not TradingView execution evidence. No screenshots, compiler logs,
Strategy Report results, fills or platform metrics are invented.

The first supported strategy is the canonical `alpha_spec(dataset_id)` from
`siqe_quest.research`: USD/CAD, SMA20/60, long when fast > slow, exit when
fast <= slow, fixed 1,000 units, initial CAD10,000, no leverage or pyramiding,
no stop-loss or take-profit. The generator checks every execution-affecting
canonical rule against this supported specification and raises `ValueError`
when a caller requests an unsupported stop, size, period, cost, risk, session or
execution rule. It does not silently omit requested protection. The complete
canonical specification SHA256 and a digest of its source-vintage identifier
are embedded in source comments. Preserve the exact JSON specification alongside
the generated source; the source is not a reversible serialization of it.

## Native implementation and assumptions

- `//@version=6`, `strategy()` with actual `strategy.entry()` and
  `strategy.close()` market orders; no imports, private libraries or
  `request.security()` calls.
- SMA calculated from chart close, warmup of at least 60 loaded chart bars,
  `barstate.isconfirmed` gating, long only, no pyramiding.
- `process_orders_on_close=false`, `calc_on_every_tick=false`,
  `calc_on_order_fills=false`, `use_bar_magnifier=false`: orders generated on
  confirmed closes normally fill at the next chart bar open in the broker
  emulator, not the signal bar's close.
- `strategy.fixed`, explicit quantity1,000; `currency.CAD`,
  `margin_long=100`, `margin_short=100`. Chart point value1 is required; the
  operator must still confirm that a fixed chart contract is the intended FX
  unit. 100% margin is not a promise of identical buying-power handling across
  simulators.
- Commission is percent-of-notional **0.05 percent =5 basis points per fill**, not
  5 percent; slippage is one tick, guarded to tick size0.00001 CAD/USD.
- Runtime guards reject non-USD/CAD forex, inverse pairs, wrong tick/point value,
  non-one-day and synthetic/nonstandard charts. These guards do not authenticate
  the feed or reconcile session calendars.
- Locked train2023, validation2024 and test2025 research segments can be selected
  separately. Each chart run starts flat and can use prior loaded bars only for
  indicator warmup. This is retrospective locked research, not prospective
  preregistration. Python preschedules liquidation at the final observed reference
  price. Pine requires the operator to set the **scheduled exit SIGNAL bar
  timestamp** to the penultimate chart bar before running, so its market exit
  fills at the final chart open. Default0 deliberately raises a runtime error
  until that input is reconciled; this is not an unattended platform run. New
  entries stop at that scheduled boundary. Final-chart-open versus final daily
  reference-average liquidation remains an explicit difference, not parity.
- Indicator, confirmed entry/exit condition, target, timestamp, CAD equity and
  signed fractional drawdown plots support chart-data export. Conditions are
  desired rules, not proof that an order filled. An open trade is not a closed
  roundtrip and must not be inserted into the closed-trade list.

### Why the first source cannot prove chart parity

Bank of Canada Valet FXUSDCAD is **a daily average indicative reference rate**
(CAD per USD), not OHLC, bid/ask or an executable market feed. Python uses a
one-observation-delayed reference-price fill proxy. Pine uses chart OHLC and
normally next-chart-open fills. The data cannot honestly be made identical by
calling the reference value an OHLC candle or by inventing an opening price.
Provider holidays, weekends/session boundaries, publication times, feed
revisions, spread, carry and financing differ or are unavailable. Neither
implementation proves historical data availability or live tradability.

The generator intentionally preserves that discrepancy rather than claiming
that matching SMA formulas establish numerical parity. The sealed2025 segment
must not be used to tune parameters. No live, account, broker or public
publication action is performed by this module.

## Manual reproducible platform workflow

1. Save the canonical strategy JSON, pinned raw/normalized dataset manifest,
   generated Pine source and source/spec SHA256. Record acquisition vintage,
   segment, provider calendar and timezone. The parent mission generates these
   artifacts; no automated unofficial TradingView upload API is assumed.
2. In a separately authorized TradingView account, open a **standard USD/CAD
   forex1D chart** with point value1 and minimum tick0.00001. Record exact
   `EXCHANGE:TICKER`, chart type, session, timezone, date coverage and feed
   identity. Load sufficient bars preceding the chosen segment for SMA60.
3. Paste the unchanged source into Pine Editor, compile, and retain the actual
   compiler result plus timestamp, source hash and any errors. Until this step
   has actual evidence, compilation stays NOT_VERIFIED. Local syntax/string
   tests cannot establish Pine compatibility.
4. Select one isolated research year. Record all Strategy Properties and input
   settings; do not change costs, quantity, capital, margin, order processing or
   intrabar settings to obtain a better result. Review next-open boundary fills
   and any open position. Source guards can fail legitimately on a feed whose
   metadata does not meet the supported assumptions; do not bypass silently.
   Set the required scheduled exit SIGNAL timestamp to the opening timestamp of
   the actual penultimate chart bar in that segment, then confirm that the exit
   fills at the intended final chart open. Never derive chart sessions by
   assuming the BoC calendar. For example, **only if the acquired dataset has
   validated 2025-12-30 as its penultimate observation**, that date can illustrate
   the reference boundary; it is not automatically the chart's penultimate bar
   and is not asserted here as an acquired observation. Record the input value
   and mapping. A missing input is intentionally rejected instead of leaving a
   canonical liquidation rule silently unimplemented.
5. Save actual Strategy Report trade data and chart exports through supported
   platform interfaces available to the account. Availability/history depth can
   depend on plan; record missing data rather than inventing it. Preserve raw
   exports unchanged, byte hashes, timestamps and the platform provenance.
6. Manually normalize exports to the dictionary schema below, documenting each
   column mapping, unit conversion and timestamp/calendar alignment. Preserve
   unmodified raw exports separately. Evaluate Python on the same segment and
   history where possible. If using actual chart OHLC instead of BoC reference
   data, register that as a different pinned data experiment; do not relabel it
   as the original reference-rate result.
7. Call `parity_report(python_output, normalized_external_output)`. Inspect every
   timestamp mismatch, rule/indicator discrepancy, count, fill-price, equity and
   drawdown error, plus assumption differences. Attach evidence references and
   perform independent origin/compilation review. The comparator does not
   authenticate an arbitrary Python dictionary as a TradingView export and
   deliberately cannot promote the gate to a verified state by self-comparison.
8. Keep compilation evidence, provenance review and numerical reconciliation
   separate. Do not claim parity proven where feed/fill/session differences
   remain. Stop on unexplained material differences. This is research, not
   investment advice or permission for live execution.

## Export contract and comparison semantics

`parity_report(python_output: dict, tradingview_output: dict | None = None)`
accepts the reference `simulate()` result directly. The external normalizer
must provide the following fields using actual export values:

```json
{
  "signals": [{"date": "2024-04-02", "fast": 1.35, "slow": 1.34,
               "entry_condition": true, "exit_condition": false}],
  "trades": [{"entry_date": "2024-04-03", "exit_date": "2024-04-04",
              "entry_price": 1.35001, "exit_price": 1.32999}],
  "equity": [{"date": "2024-04-04", "equity": 9978.64,
              "drawdown": -0.002136}],
  "assumptions": {"data": "actual feed and vintage", "execution": "next_chart_open",
                  "currency": "CAD", "drawdown_units": "signed_fraction"},
  "provenance": {"platform": "TradingView", "source_sha256": "actual saved source hash",
                 "raw_export_sha256": "actual saved export hash"}
}
```

These numbers illustrate the **schema only**, not observed TradingView outputs.
Daily labels are exact ISO dates; intraday labels must be aware ISO timestamps,
normalized to UTC by the comparator. A day label does not silently equal a UTC
midnight timestamp. Convert chart bars to provider dates only with a documented
mapping outside the comparator. Duplicate identities are rejected; trade
identity is the entry/exit timestamp pair. Missing dates are counted on each
side, never inner-joined away. This strategy has at most one trade per date
pair; finer-grained exports need their true timestamps.

Fixed tolerances are: timestamps and trade counts exact; indicator absolute1e-8
plus relative1e-8; entry/exit prices absolute0.00001 (one pinned tick); equity
absoluteCAD0.01 plus relative1e-8; drawdown absolute1e-6 (signed fraction, not
percent). A numeric error is material if greater than absolute tolerance plus
relative tolerance times the larger absolute magnitude. Warmup null SMAs on
both sides agree; a one-sided null differs. Nonfinite numbers, boolean prices,
nonboolean conditions and ambiguous/invalid timestamps are rejected.

The report supplies counts, unmatched identities, field comparison/missing/
mismatch counts and maximum absolute errors, total closed-trade-count
difference, all unequal or missing assumption keys, hashes of supplied outputs
and external provenance as supplied (not authenticated). It compares entry and
exit prices separately and both equity and drawdown curves. Missing/empty
categories or missing assumptions remain INCOMPLETE, not a passed comparison.
A material difference yields comparison/parity DIFFERENT and gate FAILED.
A complete numerical match can yield comparison MATCH, but parity and
compilation remain NOT_VERIFIED and gate NOT_TESTED until independent platform
review. With no external output all three remain unverified/not tested. These
states are intentional; a fabricated platform label or identical Python output
cannot establish TradingView proof.

## Official documentation

The official sources were consulted through Context7 for declaration/execution
semantics and chart guards. Documentation is authoritative about API syntax,
not evidence that this particular generated strategy has compiled:

- [Strategies: broker emulator, execution, costs, margin and orders](https://www.tradingview.com/pine-script-docs/concepts/strategies/)
- [Declaration statements](https://www.tradingview.com/pine-script-docs/language/declaration-statements/)
- [Pine Script v6 reference: syminfo, timeframe, chart, strategy and runtime built-ins](https://www.tradingview.com/pine-script-reference/v6/)
- [Execution model](https://www.tradingview.com/pine-script-docs/language/execution-model/)
- [Repainting](https://www.tradingview.com/pine-script-docs/concepts/repainting/)

No direct TradingView webhook delivery, authenticated platform origin, Pine
compiler run, Strategy Report result or forward-paper trading is established
by this module. Local authenticated intake testing is a separate boundary and
must not be described as tested end-to-end TradingView delivery.

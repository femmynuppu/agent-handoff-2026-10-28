# SIQE world market coverage

## Scope and evidence boundary

This is a progressive research catalog, not a statement of global data access,
exchange integration or profitable strategies. `siqe_quest.markets.coverage_matrix()`
returns a fresh sparse matrix. It materializes ten useful study cells, not the
Cartesian product of every region, asset, sector, timeframe and provider.
Absent combinations are unresearched, not successful, failed or unavailable.
The runtime execution report and immutable workspace records, not this document,
are authoritative for measured results and acceptance gates.

The eight dimensions are **region × asset class × sector × timeframe × research
method × economic regime × data provider × evaluation status**. Sector is null
for non-equity studies; global studies have an explicit global scope and null
region rather than pretending that “Global” is a validated jurisdiction.
Regimes are `NOT_CLASSIFIED` until a causal, documented classification exists.

## Complete discovery taxonomy

The original regional names are:

1. North America
2. Latin America
3. Europe
4. United Kingdom
5. Middle East
6. Africa
7. East Asia
8. Southeast Asia
9. South Asia
10. Australia and Oceania

The eleven broad GICS-style equity sector labels are:

1. Information Technology
2. Communication Services
3. Financials
4. Health Care
5. Industrials
6. Consumer Discretionary
7. Consumer Staples
8. Energy
9. Materials
10. Utilities
11. Real Estate

The seventeen other asset-class research labels, preserved separately from
individual equities, are:

1. Equity indices
2. Government bonds
3. Corporate bonds
4. Yield curves
5. Foreign exchange
6. Commodity futures
7. Energy markets
8. Precious and industrial metals
9. Agricultural futures
10. ETF flows
11. Equity options
12. Index options
13. Interest-rate derivatives
14. Crypto spot
15. Crypto derivatives
16. DEX liquidity
17. Volatility benchmarks

These names organize research; overlapping categories such as commodity
futures and energy markets do not imply interchangeable instruments or feeds.
Subsectors such as banks or semiconductors remain study instruments, not new
GICS sector labels or validated investment universes.

## Sparse study selection

| Study | Region/scope | Asset / sector | Timeframe | Method | Initial research state |
| --- | --- | --- | --- | --- | --- |
| USD/CAD reference | North America | Foreign exchange / not applicable | Business-daily reference | SMA20/60 baseline | NOT_TESTED |
| Indonesia banks | Southeast Asia | Equities / Financials | Daily | Momentum | NOT_TESTED |
| US semiconductors | North America | Equities / Information Technology | Weekly | Relative Strength | NOT_TESTED |
| Japan equities | East Asia | Equities / unresolved | Monthly | Value Factors | NOT_TESTED |
| Europe government bonds | Europe | Government bonds / not applicable | Daily | Yield Curve | NOT_TESTED |
| Gold | Global | Precious and industrial metals / not applicable | Daily | Inflation Regime | NOT_TESTED |
| USD/JPY | East Asia reference study scope | Foreign exchange / not applicable | 4H | Volatility | NOT_TESTED |
| BTC | Global crypto | Crypto spot / not applicable | Daily | Trend Following | NOT_TESTED |
| Crude oil futures | Global; venue unresolved | Commodity futures / not applicable | Daily | Term Structure | NOT_TESTED |
| Utilities | Global equities | Equities / Utilities | Monthly | Defensive Factors | NOT_TESTED |

Each cell contains a concrete `next_quest`, provider-access state and evidence
list. This is a selection menu for `Curriculum.prioritize`, not automatic work
execution or a prediction that a dataset will be licensed and reachable.
Regions without a study cell still have jurisdiction/exchange discovery targets.

## Jurisdiction and exchange metadata

The catalog names NYSE (United States), B3 (Brazil), Euronext Paris (France),
London Stock Exchange (United Kingdom), Saudi Exchange (Saudi Arabia), JSE
(South Africa), Tokyo Stock Exchange (Japan), Indonesia Stock Exchange
(Indonesia), NSE India (India), and ASX (Australia) as discovery targets only.
Each owns its own metadata dictionary; currency, timezone, calendars, holiday
and DST rules, sessions, fees, tick/lot size, settlement, corporate actions,
historical universes, availability, publication time and license are **unknown**
until validated against that jurisdiction and exchange. They are not installed
adapters. No generic equity conventions are applied to FX, crypto or futures.

LSEG licensed historical datasets are tracked as an entitlement and licensing
dependency. Their access is `ACCESS_NOT_VALIDATED`, not asserted unavailable or
`BLOCKED` without a recorded actual probe. Discovery must record an observed
failure before calling a provider inaccessible, and must not infer universal
unavailability from one denied endpoint or absent credentials.

## Representative Bank of Canada reference adapter

The representative data entry point is `SourceHunter.acquire_alpha()`; it targets
Valet series `FXUSDCAD`, requested for 2023-01-01 through 2025-12-31. An acquisition
run must determine actual observed coverage. The publisher is Bank of Canada;
`OTC_FX_REFERENCE` is a research identifier, **not** a centralized exchange.

- Instrument: USD/CAD; base USD, quote CAD, units **CAD per USD**.
- Timezone: `America/Toronto`; retain the IANA zone and its DST behavior, not a
  guessed constant UTC publication hour.
- Calendar: dates actually published by the source. Validate ordering, unique
  weekdays, finite positive values and recorded coverage; do not fill missing
  holidays or gaps. An observed-date calendar is not an independently verified
  complete Canadian holiday calendar.
- Session: publisher daily reference observation, not a stock-exchange close or
  executable FX session. Do not substitute 24/7 crypto or generic equity hours.
- Execution: research uses a next-observation reference-price proxy. No broker
  adapter, executable bid/ask, depth, actual fills, validated spread, lot size,
  settlement or capacity is supplied. Simulation slippage is an explicit study
  assumption, not a verified market tick size.
- Point-in-time: event date and ingestion timestamp are retained. Historical
  publication time and first availability are unknown/null. A retrieved vintage
  may contain revisions; it is not proof of historical as-reported availability.
- License: verify publisher terms and attribution on acquisition; underlying LSEG
  restrictions matter. Public retrieval does not establish redistribution rights.
- No equity corporate-action, delisting or survivorship claim applies. Financing
  and FX carry omissions remain explicit limitations of the reference experiment.

## Evidence-only progression

`record_coverage(store, dataset_manifest)` accepts the manifest dictionary from
an existing immutable acquired dataset, not a fabricated status flag. It checks
that the stored manifest matches, validates publisher/series conventions and
hash-verifies raw and normalized evidence. It fails closed for an unsupported
series, mismatched units/timezone, missing provenance, corrupted content or
inconsistent observation coverage. No network requests are made by this API.

Only `north-america-usdcad-reference-sma` advances to
`data_status=ACQUIRED_AND_CHECKED`. The evidence contains dataset identity,
source and version, actual retrieval time, vintage, observed coverage and blob
references. The immutable `market_coverage` record makes repeated identical
promotion idempotent. `evaluation_status` stays `NOT_TESTED`, including for that
cell; acquisition is neither a backtest nor a passed acceptance gate. No other
cell, jurisdiction adapter or scientific stage is promoted. Calling
`coverage_matrix()` again intentionally returns the evidence-free selection
baseline; call `record_coverage` with the checked manifest to obtain the evidence
view, or inspect stored `market_coverage` records for acquisition history.

## Recorded coverage outcome

In the recorded run, the only acquired-and-checked data cell is the Bank of Canada USD/CAD indicative reference series, with 747 observations dated 2023-01-03 through 2025-12-31. That cell's `data_status` is `ACQUIRED_AND_CHECKED`; its `evaluation_status` remains `NOT_TESTED`. Every other region, sector, asset, and provider entry remains catalog/discovery scope only. No global provider adapters or broad operational coverage are established. The acquisition is not a strategy evaluation, live price feed, or evidence of point-in-time availability.

## Expansion and acceptance policy

Add market adapters only after the representative end-to-end workflow is green
with actual acquisition, source validation, temporal checks, independently
executed tests and honest external-platform gate classification. Then validate
each new adapter's own rules, source rights, units, calendars, revisions and
representative workflow before treating it as covered. Cross-asset expansion
must not silently inherit FX accounting or equity assumptions.

Stage 5's broader cross-asset sampling and Stage 9's cross-market expansion
remain separate from this single FX slice. The presence of catalog entries does
not fulfill those stages. SIQE-G8 needs actual acquired/versioned data;
SIQE-G9/G10 need experiment/methodology evidence; SIQE-G12/G13 must distinguish
unexecuted Pine compilation/parity from success. Global coverage remains
`NOT_TESTED`. The code does not manufacture gate success from documentation.

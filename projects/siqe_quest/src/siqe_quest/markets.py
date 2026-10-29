"""Sparse research coverage, not a claim of globally validated market adapters.

Dataset acquisition and scientific evaluation are separate progress axes. Only an
existing immutable, checked Bank of Canada manifest can advance data coverage.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import json
import math
from typing import Any

from .core import Store, canonical_json, digest

REGIONS = (
    "North America",
    "Latin America",
    "Europe",
    "United Kingdom",
    "Middle East",
    "Africa",
    "East Asia",
    "Southeast Asia",
    "South Asia",
    "Australia and Oceania",
)
SECTORS = (
    "Information Technology",
    "Communication Services",
    "Financials",
    "Health Care",
    "Industrials",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Materials",
    "Utilities",
    "Real Estate",
)
OTHER_ASSET_CLASSES = (
    "Equity indices",
    "Government bonds",
    "Corporate bonds",
    "Yield curves",
    "Foreign exchange",
    "Commodity futures",
    "Energy markets",
    "Precious and industrial metals",
    "Agricultural futures",
    "ETF flows",
    "Equity options",
    "Index options",
    "Interest-rate derivatives",
    "Crypto spot",
    "Crypto derivatives",
    "DEX liquidity",
    "Volatility benchmarks",
)
DIMENSIONS = (
    "region",
    "asset_class",
    "sector",
    "timeframe",
    "research_method",
    "economic_regime",
    "data_provider",
    "evaluation_status",
)
ALPHA_CELL = "north-america-usdcad-reference-sma"


def _candidate_markets() -> list[dict[str, Any]]:
    candidates = (
        ("North America", "United States", "New York Stock Exchange"),
        ("Latin America", "Brazil", "B3"),
        ("Europe", "France", "Euronext Paris"),
        ("United Kingdom", "United Kingdom", "London Stock Exchange"),
        ("Middle East", "Saudi Arabia", "Saudi Exchange"),
        ("Africa", "South Africa", "Johannesburg Stock Exchange"),
        ("East Asia", "Japan", "Tokyo Stock Exchange"),
        ("Southeast Asia", "Indonesia", "Indonesia Stock Exchange"),
        ("South Asia", "India", "National Stock Exchange of India"),
        ("Australia and Oceania", "Australia", "Australian Securities Exchange"),
    )
    # These are discovery targets, not working adapters. None of their rules
    # are inherited from the representative OTC reference-rate convention.
    return [
        {
            "region": region,
            "jurisdiction": jurisdiction,
            "exchange": exchange,
            "status": "ACCESS_NOT_VALIDATED",
            "adapter_installed": False,
            "metadata": {
                "currency": None,
                "timezone": None,
                "observation_calendar": None,
                "holiday_rules": None,
                "dst_rules": None,
                "sessions": None,
                "execution_rules": None,
                "fees": None,
                "tick_size": None,
                "lot_size": None,
                "settlement": None,
                "corporate_actions": None,
                "historical_universe": None,
                "data_availability": None,
                "publication_time": None,
                "first_available_at": None,
                "license": None,
                "metadata_source": None,
            },
            "next_quest": "Validate official jurisdiction/exchange rules, licensing and timestamp semantics before adapter implementation.",
        }
        for region, jurisdiction, exchange in candidates
    ]


def _study(
    cell_id: str,
    title: str,
    region: str | None,
    asset: str,
    sector: str | None,
    timeframe: str,
    method: str,
    instrument: str,
    provider: str | None = None,
) -> dict[str, Any]:
    return {
        "cell_id": cell_id,
        "title": title,
        "region": region,
        "geographic_scope": region or "Global or cross-region; jurisdiction unresolved",
        "asset_class": asset,
        "sector": sector,
        "timeframe": timeframe,
        "research_method": method,
        "economic_regime": "NOT_CLASSIFIED",
        "data_provider": provider,
        "instrument": instrument,
        "evaluation_status": "NOT_TESTED",
        "data_status": "ACCESS_NOT_VALIDATED",
        "adapter_status": "NOT_IMPLEMENTED",
        "evidence": [],
        "next_quest": "Resolve an official source and licensing; validate native market conventions and point-in-time limitations.",
    }


def coverage_matrix() -> dict[str, Any]:
    """Return a fresh, finite quest-selection catalog with no evidence promotions.

    Missing cells mean not researched, not implicitly failed or complete. Sector
    is null where not applicable (FX is not an equity sector); a null region
    represents a global study scope, not an eleventh validated jurisdiction.
    """
    studies = [
        _study(
            ALPHA_CELL,
            "QUEST ALPHA: USD/CAD reference SMA",
            "North America",
            "Foreign exchange",
            None,
            "business_daily_reference",
            "SMA20/60 reference-proxy baseline",
            "USD/CAD",
            "Bank of Canada Valet",
        ),
        _study(
            "indonesia-banks",
            "Indonesia × Banks × Daily × Momentum",
            "Southeast Asia",
            "Equities",
            "Financials",
            "Daily",
            "Momentum",
            "Banks",
        ),
        _study(
            "us-semiconductors",
            "US × Semiconductors × Weekly × Relative Strength",
            "North America",
            "Equities",
            "Information Technology",
            "Weekly",
            "Relative Strength",
            "Semiconductors",
        ),
        _study(
            "japan-value",
            "Japan × Equities × Monthly × Value Factors",
            "East Asia",
            "Equities",
            None,
            "Monthly",
            "Value Factors",
            "Japanese equities",
        ),
        _study(
            "europe-yield-curve",
            "Europe × Government Bonds × Daily × Yield Curve",
            "Europe",
            "Government bonds",
            None,
            "Daily",
            "Yield Curve",
            "Government bonds",
        ),
        _study(
            "global-gold",
            "Global × Gold × Daily × Inflation Regime",
            None,
            "Precious and industrial metals",
            None,
            "Daily",
            "Inflation Regime",
            "Gold",
        ),
        _study(
            "fx-usdjpy",
            "FX × USD/JPY × 4H × Volatility",
            "East Asia",
            "Foreign exchange",
            None,
            "4H",
            "Volatility",
            "USD/JPY",
        ),
        _study(
            "global-btc",
            "Global Crypto × BTC × Daily × Trend Following",
            None,
            "Crypto spot",
            None,
            "Daily",
            "Trend Following",
            "BTC",
        ),
        _study(
            "crude-term-structure",
            "Energy × Crude Oil Futures × Daily × Term Structure",
            None,
            "Commodity futures",
            None,
            "Daily",
            "Term Structure",
            "Crude oil futures",
        ),
        _study(
            "global-utilities",
            "Global Equities × Utilities × Monthly × Defensive Factors",
            None,
            "Equities",
            "Utilities",
            "Monthly",
            "Defensive Factors",
            "Utilities",
        ),
    ]
    studies[0].update(
        {
            "adapter_status": "IMPLEMENTED_NOT_TESTED",
            "next_quest": "Acquire and check a versioned official manifest; then run the locked retrospective baseline and temporal audit without claiming executable FX prices.",
        }
    )
    return {
        "schema_version": 1,
        "representation": "sparse_study_cells",
        "dimensions": list(DIMENSIONS),
        "catalog": {
            "regions": list(REGIONS),
            "equity_sectors": list(SECTORS),
            "other_asset_classes": list(OTHER_ASSET_CLASSES),
            "asset_classes": ["Equities", *OTHER_ASSET_CLASSES],
        },
        "catalog_status": "NOT_TESTED",
        "cells": studies,
        "candidate_markets": _candidate_markets(),
        "representative_adapter": {
            "adapter_id": "boc-usdcad-reference",
            "entrypoint": "sources.SourceHunter.acquire_alpha",
            "status": "IMPLEMENTED_NOT_TESTED",
            "research_only": True,
            "instrument": "USD/CAD",
            "exchange": "OTC_FX_REFERENCE",
            "jurisdiction": "Canada (publisher); decentralized OTC FX is not an exchange",
            "base_currency": "USD",
            "quote_currency": "CAD",
            "units": "CAD per USD",
            "timezone": "America/Toronto",
            "timeframe": "business_daily_reference",
            "observation_calendar": "Only dates actually published in the Valet FXUSDCAD series; no gap filling",
            "holiday_rules": "Publisher observation dates; no complete holiday calendar is inferred",
            "dst_rules": "America/Toronto IANA zone; never assume a fixed UTC publication hour",
            "sessions": "Daily reference observations, not an exchange session or executable close",
            "execution_rules": "Next-observation reference proxy only; no live order adapter",
            "tick_size": None,
            "lot_size": None,
            "settlement": None,
            "publication_time": None,
            "first_available_at": None,
            "point_in_time_status": "UNKNOWN_HISTORICAL_AVAILABILITY",
            "license_status": "REQUIRES_PER_RETRIEVAL_TERMS_CHECK",
            "limitations": [
                "Indicative daily average; not bid/ask, OHLCV, a tradable quote or market depth.",
                "Retrieved vintage is not historical as-reported availability; revisions may exist.",
                "No equity calendar, corporate-action or survivorship conventions apply to this FX series.",
                "No verified FX carry, financing, broker fees, execution capacity or live fills.",
                "Bank attribution and underlying LSEG restrictions require review before reuse or redistribution.",
            ],
        },
        "provider_access": [
            {
                "provider": "Bank of Canada Valet",
                "status": "ACCESS_NOT_VALIDATED",
                "availability": "UNKNOWN_UNTIL_CHECKED_MANIFEST",
                "probe_evidence": [],
            },
            {
                "provider": "LSEG licensed historical datasets",
                "status": "ACCESS_NOT_VALIDATED",
                "availability": "UNKNOWN",
                "probe_evidence": [],
                "prerequisites": [
                    "Verify entitlement, price, redistribution rights and point-in-time history"
                ],
                "reason": "Licensed-data dependency tracked; no access denial or unavailability asserted without a probe.",
            },
        ],
        "expansion_policy": {
            "add_adapter_only_after": "Representative end-to-end workflow independently green, then validate each new adapter end-to-end",
            "end_to_end_status": "NOT_TESTED",
            "global_coverage_status": "NOT_TESTED",
            "no_cartesian_materialization": True,
            "data_acquisition_does_not_verify_research": True,
        },
    }


def _existing_manifest(store: Store, manifest: dict[str, Any]) -> dict[str, Any]:
    """Find an exact immutable manifest, not caller-supplied provenance prose."""
    serialized = canonical_json(manifest)
    for kind in ("dataset",):
        for record in store.records(kind):
            value = record["value"]
            candidate = value.get("manifest", value)
            if canonical_json(candidate) == serialized:
                # Verify record evidence as well as raw/normalized descriptors.
                store.read_blob(record["evidence"])
                return record
    raise ValueError("Coverage requires an existing immutable dataset manifest record")


def record_coverage(store: Store, dataset_manifest: dict) -> dict:
    """Advance exactly one data cell using existing, hash-verified evidence.

    The returned matrix contains a persisted coverage record reference. This API
    does not run a backtest or infer research/TradingView/exchange completion.
    Unsupported manifests fail closed rather than populating arbitrary cells.
    """
    if not isinstance(dataset_manifest, dict):
        raise ValueError("dataset_manifest must be a dictionary")
    manifest = deepcopy(dataset_manifest)
    record = _existing_manifest(store, manifest)
    return _record_checked_alpha(store, manifest, record)


def _record_checked_alpha(store: Store, manifest: dict, manifest_record: dict) -> dict:
    """Validate the publisher-specific contract before assigning a cell."""
    source = manifest.get("source", {})
    if (
        not isinstance(source, dict)
        or source.get("verification_outcome") != "VALIDATED_RESEARCH_ONLY"
    ):
        raise ValueError("Manifest requires a validated research-only source")
    if manifest.get("series") != "FXUSDCAD" or manifest.get("instrument") != "USD/CAD":
        raise ValueError("Only the FXUSDCAD reference series has a coverage adapter")
    if manifest.get("publisher") != "Bank of Canada":
        raise ValueError("Unexpected reference-rate publisher")
    if not manifest.get("source_id") or not manifest.get("source_version"):
        raise ValueError("Source identity and version are required")
    if (
        source.get("source_id") != manifest["source_id"]
        or source.get("version") != manifest["source_version"]
    ):
        raise ValueError("Source identity or version mismatch")
    validation = next(
        (
            item
            for item in store.records("source_validation")
            if item["value"] == source
        ),
        None,
    )
    if validation is None or not source.get("validation_evidence"):
        raise ValueError("Existing source validation evidence is required")
    store.read_blob(validation["evidence"])
    validation_evidence = source["validation_evidence"]
    if not isinstance(validation_evidence, dict) or not isinstance(
        validation_evidence.get("raw"), dict
    ):
        raise ValueError(
            "Source validation must reference immutable retrieval evidence"
        )
    store.read_blob(validation_evidence["raw"])
    snapshot = store.get("source_snapshot", manifest.get("manifest_id", ""))
    if snapshot is None or snapshot["value"] != manifest:
        raise ValueError("Existing source snapshot must match the manifest")
    identity_body = {
        key: value for key, value in manifest.items() if key != "manifest_id"
    }
    if digest(identity_body) != manifest["manifest_id"]:
        raise ValueError("Manifest identity mismatch")
    store.read_blob(snapshot["evidence"])
    if (
        manifest.get("units") != "CAD per USD"
        or manifest.get("timezone") != "America/Toronto"
    ):
        raise ValueError("USD/CAD units and timezone must match the reference adapter")
    retrieved_at = manifest.get("retrieved_at")
    if not isinstance(retrieved_at, str):
        raise ValueError("An actual retrieval timestamp is required")
    parsed = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Retrieval timestamp must be timezone aware")
    raw = manifest.get("raw")
    normalized = manifest.get("normalized")
    if not isinstance(raw, dict) or not isinstance(normalized, dict):
        raise ValueError("Raw and normalized immutable blob references are required")
    raw_bytes = store.read_blob(raw)
    observations = json.loads(store.read_blob(normalized))
    expected_id = digest(
        {"series": "FXUSDCAD", "raw": raw["sha256"], "normalized": normalized["sha256"]}
    )
    if (
        manifest.get("dataset_id") != expected_id
        or manifest.get("vintage") != raw["sha256"]
    ):
        raise ValueError("Dataset identity or vintage mismatch")
    if (
        manifest_record["value"].get("dataset_id") != expected_id
        or manifest_record["value"].get("observations") != observations
    ):
        raise ValueError("Dataset record disagrees with normalized evidence")
    _check_observations(observations, json.loads(raw_bytes), manifest)
    matrix = coverage_matrix()
    cell = matrix["cells"][0]
    cell.update(
        {
            "data_status": "ACQUIRED_AND_CHECKED",
            "evidence": [
                {
                    "manifest_record_id": manifest_record["record_id"],
                    "dataset_id": manifest["dataset_id"],
                    "source_id": manifest["source_id"],
                    "source_version": manifest["source_version"],
                    "source": source,
                    "retrieved_at": retrieved_at,
                    "vintage": manifest["vintage"],
                    "coverage": manifest["coverage"],
                    "raw": raw,
                    "normalized": normalized,
                }
            ],
            "next_quest": "Run the locked retrospective baseline, delayed-reference simulation, independent leakage checks and explicit unverified TradingView gates.",
        }
    )
    matrix["provider_access"][0].update(
        {
            "status": "RETRIEVED_FOR_THIS_DATASET",
            "availability": "OBSERVED_FOR_RECORDED_WINDOW",
            "probe_evidence": [manifest_record["record_id"]],
        }
    )
    coverage = {
        "schema_version": 1,
        "cell_id": ALPHA_CELL,
        "data_status": cell["data_status"],
        "evaluation_status": "NOT_TESTED",
        "evidence": cell["evidence"],
    }
    matrix["coverage_record"] = store.record(
        "market_coverage", digest(coverage), coverage
    )
    return matrix


def _check_observations(observations: Any, raw: Any, manifest: dict) -> None:
    """Check only the reference data semantics used by this coverage cell."""
    if not isinstance(observations, list) or not observations:
        raise ValueError("Nonempty normalized observation evidence is required")
    if not isinstance(raw, dict) or not isinstance(raw.get("observations"), list):
        raise ValueError("Raw source must contain actual observations")
    raw_rows = raw["observations"]
    if len(raw_rows) != len(observations):
        raise ValueError("Raw and normalized observation counts differ")
    last = ""
    for observation, original in zip(observations, raw_rows):
        if not isinstance(observation, dict) or not isinstance(original, dict):
            raise ValueError("Invalid observation object")
        day = observation.get("date")
        if not isinstance(day, str) or len(day) != 10:
            raise ValueError("Observation date must have date-only precision")
        parsed = date.fromisoformat(day)
        if parsed.weekday() >= 5 or day <= last:
            raise ValueError("Reference dates must be unique ascending weekdays")
        number = observation.get("value")
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(number)
            or number <= 0
        ):
            raise ValueError("Reference observations must be finite positive numbers")
        raw_series = original.get("FXUSDCAD")
        if not isinstance(raw_series, dict):
            raise ValueError("Missing original FXUSDCAD observation")
        original_value = raw_series.get("v")
        if (
            original.get("d") != day
            or not isinstance(original_value, str)
            or float(original_value) != number
        ):
            raise ValueError("Raw observation disagrees with normalized value")
        if (
            observation.get("original_value") != original_value
            or observation.get("normalized_value") != number
        ):
            raise ValueError("Original/normalized value provenance mismatch")
        if (
            observation.get("timezone") != "America/Toronto"
            or observation.get("complete") is not True
        ):
            raise ValueError("Incomplete or incorrectly zoned reference observation")
        if (
            observation.get("publication_time") is not None
            or observation.get("available_at") is not None
        ):
            raise ValueError("Unknown historical availability must not be fabricated")
        last = day
    coverage = manifest.get("coverage")
    if not isinstance(coverage, dict):
        raise ValueError("Observed coverage metadata is required")
    if (
        coverage.get("start") != observations[0]["date"]
        or coverage.get("end") != last
        or coverage.get("observation_count") != len(observations)
    ):
        raise ValueError("Manifest coverage disagrees with actual observations")
    if (
        manifest.get("publication_time") is not None
        or manifest.get("available_at") is not None
    ):
        raise ValueError(
            "Reference manifest must retain unknown historical availability"
        )

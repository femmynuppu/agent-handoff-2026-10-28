#!/usr/bin/env python3
"""
Indonesian Banking, Stock Market & Fintech MCP Server
Provides real-time quotes, fundamental ratios, financial comparisons, and macroeconomic
indicators for Indonesian Banks (IDX / BEI), Fintech companies, and the IHSG composite index.
"""

import warnings
warnings.filterwarnings("ignore")

import json
from typing import Optional, List, Dict, Any
from fastmcp import FastMCP
import yfinance as yf

mcp = FastMCP("Indonesia Banking & Fintech MCP")

DEFAULT_BANKS = ["BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "BBTN", "ARTO"]
DEFAULT_FINTECH = ["ARTO", "BBHI", "BBYB", "GOTO", "BUKA"]

def _normalize_ticker(ticker: str) -> str:
    ticker = ticker.strip().upper()
    if not ticker.endswith(".JK") and not ticker.startswith("^") and "=" not in ticker:
        return f"{ticker}.JK"
    return ticker

@mcp.tool()
def get_indonesia_bank_quotes(tickers: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Get live quotes and price metrics for Indonesian banks on the Indonesia Stock Exchange (IDX).
    
    Args:
        tickers: Optional list of Indonesian bank tickers (e.g. ['BBCA', 'BBRI', 'BMRI']).
                 Defaults to Big 4 (BCA, BRI, Mandiri, BNI) + BSI (BRIS) + BTN (BBTN) + Bank Jago (ARTO).
    """
    target_tickers = tickers if tickers else DEFAULT_BANKS
    normalized = [_normalize_ticker(t) for t in target_tickers]
    
    results = []
    for sym in normalized:
        try:
            t = yf.Ticker(sym)
            info = t.info
            clean_sym = sym.replace(".JK", "")
            results.append({
                "ticker": clean_sym,
                "full_symbol": sym,
                "company_name": info.get("shortName") or info.get("longName") or clean_sym,
                "current_price_idr": info.get("currentPrice") or info.get("regularMarketPrice"),
                "previous_close": info.get("previousClose") or info.get("regularMarketPreviousClose"),
                "day_high": info.get("dayHigh"),
                "day_low": info.get("dayLow"),
                "volume": info.get("volume") or info.get("regularMarketVolume"),
                "52_week_high": info.get("fiftyTwoWeekHigh"),
                "52_week_low": info.get("fiftyTwoWeekLow"),
                "market_cap_idr": info.get("marketCap"),
                "trailing_pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "price_to_book": info.get("priceToBook"),
                "dividend_yield_pct": round((info.get("dividendYield") if info.get("dividendYield", 0) < 1 else info.get("dividendYield") / 100) * 100, 2) if info.get("dividendYield") else None,
            })
        except Exception as e:
            results.append({"ticker": sym, "error": str(e)})
    return results

@mcp.tool()
def get_indonesia_bank_financials(ticker: str) -> Dict[str, Any]:
    """
    Get detailed fundamental financials and balance sheet indicators for an Indonesian bank.
    
    Args:
        ticker: Indonesian bank ticker symbol (e.g. 'BBCA', 'BBRI', 'BMRI', 'BBNI', 'BRIS').
    """
    sym = _normalize_ticker(ticker)
    t = yf.Ticker(sym)
    info = t.info
    clean_sym = sym.replace(".JK", "")

    return {
        "ticker": clean_sym,
        "symbol": sym,
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "valuation": {
            "market_cap_idr": info.get("marketCap"),
            "enterprise_value": info.get("enterpriseValue"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "book_value_per_share": info.get("bookValue"),
        },
        "profitability": {
            "return_on_equity_pct": (info.get("returnOnEquity") or 0) * 100 if info.get("returnOnEquity") else None,
            "return_on_assets_pct": (info.get("returnOnAssets") or 0) * 100 if info.get("returnOnAssets") else None,
            "profit_margins_pct": (info.get("profitMargins") or 0) * 100 if info.get("profitMargins") else None,
            "operating_margins_pct": (info.get("operatingMargins") or 0) * 100 if info.get("operatingMargins") else None,
        },
        "income_statement_summary": {
            "total_revenue_idr": info.get("totalRevenue"),
            "net_income_to_common_idr": info.get("netIncomeToCommon"),
            "revenue_growth_yoy_pct": (info.get("revenueGrowth") or 0) * 100 if info.get("revenueGrowth") else None,
            "earnings_growth_yoy_pct": (info.get("earningsGrowth") or 0) * 100 if info.get("earningsGrowth") else None,
            "trailing_eps_idr": info.get("trailingEps"),
        },
        "balance_sheet_summary": {
            "total_cash_idr": info.get("totalCash"),
            "total_debt_idr": info.get("totalDebt"),
            "debt_to_equity": info.get("debtToEquity"),
        },
        "dividends": {
            "dividend_rate": info.get("dividendRate"),
            "dividend_yield_pct": round((info.get("dividendYield") if info.get("dividendYield", 0) < 1 else info.get("dividendYield") / 100) * 100, 2) if info.get("dividendYield") else None,
            "payout_ratio_pct": (info.get("payoutRatio") or 0) * 100 if info.get("payoutRatio") else None,
        }
    }

@mcp.tool()
def compare_indonesia_banks(tickers: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Compare Indonesian banks side-by-side across valuation (PE, PBV), profitability (ROE, ROA),
    size (Market Cap), and dividend yields.
    
    Args:
        tickers: Optional list of tickers to compare (e.g. ['BBCA', 'BBRI', 'BMRI', 'BBNI']).
                 Defaults to all Big 4 + BSI + Bank Jago.
    """
    target_tickers = tickers if tickers else ["BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "ARTO"]
    results = []
    for sym in target_tickers:
        norm = _normalize_ticker(sym)
        try:
            info = yf.Ticker(norm).info
            results.append({
                "ticker": sym.upper().replace(".JK", ""),
                "company": info.get("shortName") or sym,
                "price_idr": info.get("currentPrice") or info.get("regularMarketPrice"),
                "pe_ratio": round(info.get("trailingPE"), 2) if info.get("trailingPE") else None,
                "pbv_ratio": round(info.get("priceToBook"), 2) if info.get("priceToBook") else None,
                "roe_pct": round(info.get("returnOnEquity") * 100, 2) if info.get("returnOnEquity") else None,
                "dividend_yield_pct": round((info.get("dividendYield") if info.get("dividendYield", 0) < 1 else info.get("dividendYield") / 100) * 100, 2) if info.get("dividendYield") else None,
                "market_cap_trillion_idr": round(info.get("marketCap") / 1e12, 2) if info.get("marketCap") else None,
            })
        except Exception as e:
            results.append({"ticker": sym, "error": str(e)})
    return results

@mcp.tool()
def get_indonesia_market_macro() -> Dict[str, Any]:
    """
    Get macroeconomic indicators relevant to Indonesia:
    - IHSG (IDX Composite Index `^JKSE`)
    - USD / IDR Exchange Rate (`IDR=X`)
    - SGD / IDR Exchange Rate (`SGDIDR=X`)
    - EUR / IDR Exchange Rate (`EURIDR=X`)
    """
    macro_symbols = {
        "ihsg_composite": "^JKSE",
        "usd_idr": "IDR=X",
        "sgd_idr": "SGDIDR=X",
        "eur_idr": "EURIDR=X",
    }
    data = {}
    for label, sym in macro_symbols.items():
        try:
            info = yf.Ticker(sym).info
            data[label] = {
                "symbol": sym,
                "value": info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose"),
                "previous_close": info.get("previousClose"),
                "day_high": info.get("dayHigh"),
                "day_low": info.get("dayLow"),
            }
        except Exception as e:
            data[label] = {"symbol": sym, "error": str(e)}
    return data

@mcp.tool()
def get_indonesia_fintech_and_digital_banks() -> List[Dict[str, Any]]:
    """
    Get stock and valuation data for Indonesian digital banks, fintechs, and tech platforms:
    - ARTO (Bank Jago / GoTo Financial)
    - BBHI (Allo Bank Indonesia / CT Corp)
    - BBYB (Bank Neo Commerce / Akulaku)
    - GOTO (GoTo Gojek Tokopedia)
    - BUKA (Bukalapak.com)
    """
    results = []
    for sym in DEFAULT_FINTECH:
        norm = _normalize_ticker(sym)
        try:
            info = yf.Ticker(norm).info
            results.append({
                "ticker": sym,
                "company_name": info.get("shortName") or info.get("longName"),
                "price_idr": info.get("currentPrice") or info.get("regularMarketPrice"),
                "market_cap_trillion_idr": round(info.get("marketCap") / 1e12, 2) if info.get("marketCap") else None,
                "pbv": round(info.get("priceToBook"), 2) if info.get("priceToBook") else None,
                "pe": round(info.get("trailingPE"), 2) if info.get("trailingPE") else None,
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
            })
        except Exception as e:
            results.append({"ticker": sym, "error": str(e)})
    return results

if __name__ == "__main__":
    mcp.run()

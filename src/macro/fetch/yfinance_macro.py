"""
yfinance batch fetch for macro indicators — yields, currencies, futures.

Fetches multiple tickers in one yfinance.download() call.
Per-ticker isolation: failed tickers are logged but do not block others.

Spread computation:
  SPREAD_2S10S = US_10Y_YIELD (^TNX) - US_2Y_YIELD (DGS2/FRED)
  SPREAD_10Y3M = US_10Y_YIELD (^TNX) - US_3M_YIELD (^IRX fallback DGS3MO)

CNH=X fallback: if CNH=X returns <52 rows, try CNY=X.
^IRX fallback: if ^IRX returns <52 rows, use FRED DGS3MO series (passed in).
"""

import logging
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_yfinance_batch(
    tickers: list,
    period: str = "2y",
) -> dict:
    """
    Fetch Close prices for a list of tickers via yfinance.download().

    Args:
        tickers: List of yfinance ticker symbols.
        period: yfinance period string (default '2y').

    Returns:
        dict mapping ticker -> pd.Series (DatetimeIndex, float Close values).
        Tickers that fail or return empty data are omitted with a log warning.
    """
    if not tickers:
        return {}

    raw = yf.download(
        tickers,
        period=period,
        interval="1d",
        auto_adjust=True,
        progress=False,
    )

    if raw is None or len(raw) == 0:
        logger.warning("yfinance.download returned no data for tickers: %s", tickers)
        return {}

    result = {}

    # Handle single vs multi-ticker column structure
    if isinstance(raw.columns, pd.MultiIndex):
        # Multi-ticker: columns are (price_type, ticker)
        if "Close" in raw.columns.get_level_values(0):
            close_df = raw["Close"]
        elif "Adj Close" in raw.columns.get_level_values(0):
            close_df = raw["Adj Close"]
        else:
            logger.warning(
                "Expected 'Close' or 'Adj Close' in multi-ticker download. "
                "Available: %s", list(raw.columns.get_level_values(0).unique())
            )
            return {}

        for ticker in tickers:
            if ticker in close_df.columns:
                series = close_df[ticker].dropna()
                if len(series) == 0:
                    logger.warning("Ticker %s returned empty series after dropna", ticker)
                else:
                    result[ticker] = series
            else:
                logger.warning("Ticker %s not found in download result", ticker)
    else:
        # Single ticker: flat columns
        if "Close" in raw.columns:
            series = raw["Close"].dropna()
        elif "Adj Close" in raw.columns:
            series = raw["Adj Close"].dropna()
        else:
            logger.warning(
                "Expected 'Close' or 'Adj Close' for single ticker. "
                "Available: %s", list(raw.columns)
            )
            return {}

        if len(tickers) == 1 and len(series) > 0:
            result[tickers[0]] = series
        else:
            logger.warning("Single-ticker result shape mismatch for tickers: %s", tickers)

    return result


def fetch_yields_currencies_futures(
    period: str = "2y",
    fred_dgs2_series: "pd.Series | None" = None,
    fred_dgs3mo_series: "pd.Series | None" = None,
) -> dict:
    """
    Fetch all yield, currency, and futures indicators from yfinance.
    Computes SPREAD_2S10S and SPREAD_10Y3M.
    Handles CNH=X and ^IRX fallbacks.

    Args:
        period: yfinance period string.
        fred_dgs2_series: FRED DGS2 series (pd.Series with DatetimeIndex) — used
                          for SPREAD_2S10S computation alongside ^TNX.
        fred_dgs3mo_series: FRED DGS3MO series — fallback for ^IRX if it returns
                            fewer than 52 rows.

    Returns:
        dict mapping indicator_id -> pd.Series (DatetimeIndex, float values).
        Includes SPREAD_2S10S and SPREAD_10Y3M where computable.
    """
    # Define ticker groups
    yield_tickers = ["^FVX", "^TNX", "^TYX", "^IRX"]
    currency_tickers = ["DX-Y.NYB", "EURUSD=X", "GBPUSD=X", "JPY=X", "AUDUSD=X", "CNH=X", "CHF=X"]
    futures_tickers = ["GC=F", "CL=F", "HG=F", "NG=F", "ZC=F"]

    all_tickers = yield_tickers + currency_tickers + futures_tickers

    raw_series = fetch_yfinance_batch(all_tickers, period=period)

    # --- CNH=X fallback ---
    cnh_series = raw_series.get("CNH=X")
    if cnh_series is None or len(cnh_series) < 52:
        logger.warning("CNH=X returned <52 rows — falling back to CNY=X")
        cny_raw = fetch_yfinance_batch(["CNY=X"], period=period)
        if "CNY=X" in cny_raw and len(cny_raw["CNY=X"]) >= 52:
            raw_series["CNH=X"] = cny_raw["CNY=X"]
            logger.info("CNY=X fallback succeeded for USD_CNH")
        else:
            logger.warning("CNY=X fallback also insufficient for USD_CNH")

    # --- ^IRX fallback to FRED DGS3MO ---
    irx_series = raw_series.get("^IRX")
    us_3m_series = None
    if irx_series is not None and len(irx_series) >= 52:
        us_3m_series = irx_series
    elif fred_dgs3mo_series is not None and len(fred_dgs3mo_series) >= 52:
        logger.warning("^IRX returned <52 rows — using FRED DGS3MO for US_3M_YIELD")
        us_3m_series = fred_dgs3mo_series
    else:
        logger.warning("^IRX and FRED DGS3MO both insufficient — SPREAD_10Y3M will be skipped")

    # Ticker -> indicator_id mapping
    ticker_to_id = {
        "^FVX": "US_5Y_YIELD",
        "^TNX": "US_10Y_YIELD",
        "^TYX": "US_30Y_YIELD",
        "DX-Y.NYB": "DXY",
        "EURUSD=X": "EUR_USD",
        "GBPUSD=X": "GBP_USD",
        "JPY=X": "USD_JPY",
        "AUDUSD=X": "AUD_USD",
        "CNH=X": "USD_CNH",
        "CHF=X": "USD_CHF",
        "GC=F": "GOLD_FRONT",
        "CL=F": "WTI_FRONT",
        "HG=F": "COPPER_FRONT",
        "NG=F": "NATGAS_FRONT",
        "ZC=F": "CORN_FRONT",
    }

    result = {}

    for ticker, indicator_id in ticker_to_id.items():
        if ticker in raw_series and len(raw_series[ticker]) > 0:
            result[indicator_id] = raw_series[ticker]
        else:
            logger.warning("Ticker %s missing from yfinance results — %s will be absent", ticker, indicator_id)

    # --- US_2Y_YIELD from FRED DGS2 ---
    if fred_dgs2_series is not None and len(fred_dgs2_series) >= 52:
        result["US_2Y_YIELD"] = fred_dgs2_series
    else:
        logger.warning("FRED DGS2 series not available or <52 rows — US_2Y_YIELD will be absent")

    # --- SPREAD_2S10S: ^TNX - DGS2 (inner join on dates) ---
    tnx = raw_series.get("^TNX")
    dgs2 = fred_dgs2_series
    if tnx is not None and dgs2 is not None and len(tnx) >= 52 and len(dgs2) >= 52:
        tnx_aligned, dgs2_aligned = tnx.align(dgs2, join="inner")
        spread_2s10s = tnx_aligned - dgs2_aligned
        spread_2s10s = spread_2s10s.dropna()
        if len(spread_2s10s) >= 52:
            result["SPREAD_2S10S"] = spread_2s10s
        else:
            logger.warning("SPREAD_2S10S inner join yielded <52 rows after dropna")
    else:
        logger.warning("Cannot compute SPREAD_2S10S — ^TNX or DGS2 unavailable/insufficient")

    # --- SPREAD_10Y3M: ^TNX - ^IRX (or DGS3MO fallback) inner join ---
    if tnx is not None and us_3m_series is not None and len(tnx) >= 52 and len(us_3m_series) >= 52:
        tnx_aligned, m3_aligned = tnx.align(us_3m_series, join="inner")
        spread_10y3m = tnx_aligned - m3_aligned
        spread_10y3m = spread_10y3m.dropna()
        if len(spread_10y3m) >= 52:
            result["SPREAD_10Y3M"] = spread_10y3m
        else:
            logger.warning("SPREAD_10Y3M inner join yielded <52 rows after dropna")
    else:
        logger.warning("Cannot compute SPREAD_10Y3M — ^TNX or US_3M_YIELD unavailable/insufficient")

    return result

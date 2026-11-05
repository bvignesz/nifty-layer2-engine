#!/usr/bin/env python3
"""
NSE Equity Dual-Track POC Research Screener v0.7.0

Standalone, observation-only Yahoo Finance screener. It does not place orders,
size positions, or modify any trading engine.

Research lifecycle states
-------------------------
PULLBACK_AT_POC
    Current completed daily bar has relative strength versus the configured
    benchmark (Nifty 500 by default),
    Williams %R(3) <= -80, and closes from -0.10 to +0.30 ATR around the
    swing-anchored approximate volume-profile POC, at or above VAL, on
    contracting volume, with at least 2:1 structural reward-to-risk.

RECOVERY_FROM_POC
    A PULLBACK_AT_POC setup occurred within the previous five sessions;
    W%R(3) has recovered above -80, relative strength remains valid, and price
    is above but no more than +0.30 setup-day ATR from the frozen setup POC.

EXPANSION_AFTER_SETUP
    The same recent setup exists, but price is now more than +0.30 setup-day
    ATR above the frozen setup POC. This is a lifecycle observation, not a
    fresh pullback condition.

SPRING_WATCH_AT_VAL
    Price has marginally undercut the relevant VAL by no more than 0.50 ATR
    while remaining within 0.50 ATR below POC and above the structural stop.
    This is a watch-only failed-auction candidate that requires a subsequent
    VAL reclaim; it is not an entry signal or an active lifecycle match.

AUCTION_BREAKDOWN
    Price has closed materially below the relevant Value Area Low or through
    the structural stop. This invalidates an active setup (when one exists) and
    is reported separately from actionable lifecycle matches.

POC_COMPRESSION_WATCH (Track B)
    Relative strength is positive, W%R(3) is between -60 and -10, range and
    volume are contracting, and price is contained around a separate fixed
    15-session POC/value area. Track B deliberately has no stock-price EMA20
    condition. It is a watch, not an entry.

BREAKOUT_READY_NEXT_OPEN / BREAKOUT_EXTENDED_WAIT_RETEST (Track B)
    A later completed bar closes above the frozen watch-day VAH with volume
    and candle-quality confirmation. A close no more than 0.75 setup ATR above
    VAH can be considered at the next open subject to its price/risk check;
    a larger extension is labelled wait-for-retest rather than chased.

POC, VAL, and VAH are approximations made from Yahoo 15-minute OHLCV. Thirty
percent of each bar's volume is distributed by geometric overlap across its
full range and seventy percent by geometric overlap across its candle body.
Profiles are anchored to the latest confirmed five-bar daily fractal low (two
closed bars on either side) that is covered by the available intraday history.
The target daily candle is excluded from its own reference profile. Yahoo does not provide exchange
volume-at-price/tick data through yfinance, so results will not exactly match a
broker or TradingView volume profile.

Current profile zone, POC reclaim/loss, and an ATR-aware tolerance are reported
for every evaluated row. Their small POC_Rank_Adjustment only orders rows within
the existing lifecycle state; it does not bypass or create a qualification gate.

Composite breadth is the percentage of liquid, seasoned scanned stocks above
their daily SMA50. It is informational by default; use --require-breadth to
make adequate coverage and breadth >= the configured threshold a hard gate.
Model B fields are reference planning levels only. They do not represent fills,
orders, or a portfolio backtest.

Install:
    python -m pip install yfinance pandas numpy scipy scikit-learn

Examples:
    python nifty500_rs_wpr_poc_screener.py
    python nifty500_rs_wpr_poc_screener.py --universe nifty500
    python nifty500_rs_wpr_poc_screener.py --universe nse --nse-series EQ,BE
    python nifty500_rs_wpr_poc_screener.py --symbols KIRLOSENG,RELIANCE,TCS
    python nifty500_rs_wpr_poc_screener.py --symbols-file my_symbols.csv
    python nifty500_rs_wpr_poc_screener.py --self-test
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
import tempfile
import time
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from datetime import time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

VERSION = "0.7.0"
HYPOTHESIS_ID = "HYP_DUAL_TRACK_POC_LIFECYCLE_008"
IST = ZoneInfo("Asia/Kolkata")

NIFTY_500_URLS = (
    "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
)
NSE_EQUITY_URLS = (
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
)

STATE_ORDER = {
    "PULLBACK_AT_POC": 0,
    "BREAKOUT_READY_NEXT_OPEN": 1,
    "POC_COMPRESSION_WATCH": 2,
    "RECOVERY_FROM_POC": 3,
    "EXPANSION_AFTER_SETUP": 4,
    "BREAKOUT_EXTENDED_WAIT_RETEST": 5,
    "BREAKOUT_CONFIRMED_RR_FAIL": 6,
    "SPRING_WATCH_AT_VAL": 7,
    "FAILED_BREAKOUT": 8,
    "INVALIDATED": 9,
    "WATCH_EXPIRED": 10,
    "AUCTION_BREAKDOWN": 11,
}
ACTIVE_STATES = (
    "PULLBACK_AT_POC",
    "RECOVERY_FROM_POC",
    "EXPANSION_AFTER_SETUP",
    "BREAKOUT_READY_NEXT_OPEN",
)
WATCH_STATES = (
    "SPRING_WATCH_AT_VAL",
    "POC_COMPRESSION_WATCH",
    "BREAKOUT_EXTENDED_WAIT_RETEST",
    "BREAKOUT_CONFIRMED_RR_FAIL",
)
TRACK_B_STATES = (
    "POC_COMPRESSION_WATCH",
    "BREAKOUT_READY_NEXT_OPEN",
    "BREAKOUT_EXTENDED_WAIT_RETEST",
    "BREAKOUT_CONFIRMED_RR_FAIL",
    "FAILED_BREAKOUT",
    "INVALIDATED",
    "WATCH_EXPIRED",
)


@dataclass(frozen=True)
class ScannerConfig:
    benchmark: str = "^CRSLDX"
    daily_period: str = "1y"
    intraday_period: str = "60d"
    intraday_interval: str = "15m"
    rs_ema_length: int = 20
    rs_slope_sessions: int = 5
    excess_return_sessions: int = 20
    wpr_length: int = 3
    wpr_oversold: float = -80.0
    atr_length: int = 14
    poc_sessions: int = 20
    poc_bins: int = 50
    fractal_left_bars: int = 2
    fractal_right_bars: int = 2
    min_anchored_profile_sessions: int = 5
    body_volume_weight: float = 0.70
    value_area_pct: float = 0.70
    profile_tolerance_atr: float = 0.20
    poc_distance_min_atr: float = -0.10
    poc_distance_max_atr: float = 0.30
    volume_contraction_multiplier: float = 1.10
    structural_stop_atr: float = 0.50
    spring_max_val_undercut_atr: float = 0.50
    spring_max_poc_extension_atr: float = 0.50
    min_risk_reward: float = 2.0
    lifecycle_sessions: int = 5
    compression_profile_sessions: int = 15
    compression_wpr_min: float = -60.0
    compression_wpr_max: float = -10.0
    compression_tr_atr_max: float = 0.85
    compression_volume_ratio_max: float = 0.85
    compression_volume_ratio_3d_max: float = 0.90
    compression_poc_min_atr: float = -0.10
    compression_poc_max_atr: float = 0.55
    compression_vah_buffer_atr: float = 0.15
    compression_value_area_width_max_atr: float = 2.00
    compression_width_percentile: float = 0.35
    compression_width_lookback_sessions: int = 20
    compression_width_min_observations: int = 10
    compression_watch_expiry_sessions: int = 5
    breakout_volume_ratio_min: float = 1.30
    breakout_clv_min: float = 0.70
    breakout_body_ratio_min: float = 0.50
    breakout_wpr_min: float = -15.0
    breakout_max_extension_atr: float = 0.75
    breakout_stop_vah_buffer_atr: float = 0.25
    breakout_stop_low_buffer_atr: float = 0.10
    breakout_min_risk_reward: float = 1.80
    min_turnover_crore: float = 1.0
    min_price: float = 0.0
    breadth_sma_length: int = 50
    breadth_threshold_pct: float = 50.0
    breadth_min_turnover_crore: float = 5.0
    breadth_min_constituents: int = 100
    require_breadth: bool = False
    trade_plan_ema_length: int = 10
    batch_size: int = 40
    intraday_batch_size: int = 20
    retries: int = 3
    retry_pause_seconds: float = 5.0
    benchmark_regime_ema_length: int = 20
    market_close_grace: clock_time = clock_time(15, 45)


@dataclass(frozen=True)
class ProfileLevels:
    poc: float = math.nan
    val: float = math.nan
    vah: float = math.nan
    anchor_date: str = ""
    sessions: int = 0
    anchor_method: str = ""
    bin_width: float = math.nan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NSE equity RS-W%R3-POC lifecycle research screener"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--symbols",
        help="Comma-separated NSE symbols, e.g. KIRLOSENG,RELIANCE,TCS",
    )
    source.add_argument(
        "--symbols-file",
        type=Path,
        help="CSV/TXT file. CSV may use Symbol, Ticker, or Yahoo_Symbol column.",
    )
    parser.add_argument(
        "--universe",
        choices=("nse", "nifty500"),
        default="nse",
        help="Automatic universe when --symbols/--symbols-file is absent (default: nse)",
    )
    parser.add_argument(
        "--nse-series",
        default="EQ",
        help="Comma-separated NSE series for --universe nse; use ALL for every series (default: EQ)",
    )
    parser.add_argument("--benchmark", default="^CRSLDX", help="Yahoo benchmark ticker")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output CSV path. Default is based on the selected universe and date.",
    )
    parser.add_argument("--max-symbols", type=int, help="Limit universe for a trial run")
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument(
        "--intraday-batch-size",
        type=int,
        default=20,
        help="Symbols per Yahoo 15-minute batch (default: 20)",
    )
    parser.add_argument("--pause", type=float, default=1.0, help="Pause between Yahoo batches")
    parser.add_argument("--retries", type=int, default=3, help="Yahoo attempts per request")
    parser.add_argument(
        "--retry-pause",
        type=float,
        default=5.0,
        help="Base seconds between retry attempts; backoff is progressive",
    )
    parser.add_argument("--min-turnover-crore", type=float, default=1.0)
    parser.add_argument("--min-price", type=float, default=0.0)
    parser.add_argument(
        "--breadth-min-turnover-crore",
        type=float,
        default=5.0,
        help="Minimum 20-day median turnover for breadth membership (default: 5)",
    )
    parser.add_argument(
        "--breadth-threshold",
        type=float,
        default=50.0,
        help="Minimum percent above SMA50 when the breadth gate is active (default: 50)",
    )
    parser.add_argument(
        "--require-breadth",
        action="store_true",
        help="Require breadth coverage and percent-above-SMA50 threshold for long states",
    )
    parser.add_argument(
        "--include-partial-day",
        action="store_true",
        help="Include today's daily bar before 15:45 IST (not recommended)",
    )
    parser.add_argument(
        "--all-results",
        action="store_true",
        help="Include evaluated non-matches as well as lifecycle matches",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        help="Track B frozen-state JSON (default: beside this script)",
    )
    parser.add_argument(
        "--no-state-update",
        action="store_true",
        help="Read the Track B state cache but do not update it",
    )
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def require_yfinance():
    try:
        import yfinance as yf  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency 'yfinance'. Install with:\n"
            "  python -m pip install yfinance pandas numpy scipy scikit-learn"
        ) from exc
    return yf


def yahoo_symbol(symbol: str) -> str:
    symbol = str(symbol).strip().upper()
    if not symbol:
        return ""
    if symbol.startswith("^") or symbol.endswith((".NS", ".BO")):
        return symbol
    return f"{symbol}.NS"


def display_symbol(symbol: str) -> str:
    return symbol.removesuffix(".NS")


def unique_in_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def fetch_nifty500_symbols(timeout: int = 30) -> list[str]:
    errors: list[str] = []
    headers = {"User-Agent": "Mozilla/5.0 (research screener)"}
    for url in NIFTY_500_URLS:
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
            table = pd.read_csv(io.BytesIO(raw))
            normalized = {str(col).strip().lower(): col for col in table.columns}
            symbol_col = normalized.get("symbol")
            if symbol_col is None:
                raise ValueError(f"Symbol column missing; columns={list(table.columns)}")
            symbols = unique_in_order(yahoo_symbol(x) for x in table[symbol_col].dropna())
            if len(symbols) < 400:
                raise ValueError(f"Only {len(symbols)} constituents returned")
            return symbols
        except Exception as exc:  # noqa: BLE001 - try the next official source
            errors.append(f"{url}: {exc}")
    raise RuntimeError(
        "Could not download the current Nifty 500 constituent list. "
        "Use --symbols or --symbols-file. Details: " + " | ".join(errors)
    )


def parse_nse_series(value: str) -> tuple[str, ...] | None:
    requested = tuple(
        unique_in_order(
            part.strip().upper() for part in str(value).split(",") if part.strip()
        )
    )
    if not requested:
        raise ValueError("--nse-series must contain at least one series or ALL")
    if "ALL" in requested:
        if len(requested) != 1:
            raise ValueError("Use --nse-series ALL by itself")
        return None
    return requested


def fetch_nse_equity_symbols(
    allowed_series: tuple[str, ...] | None = ("EQ",), timeout: int = 30
) -> list[str]:
    """Download current NSE cash-equity symbols from the official NSE list."""
    errors: list[str] = []
    headers = {"User-Agent": "Mozilla/5.0 (research screener)"}
    for url in NSE_EQUITY_URLS:
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
            table = pd.read_csv(io.BytesIO(raw))
            normalized = {str(col).strip().lower(): col for col in table.columns}
            symbol_col = normalized.get("symbol")
            series_col = normalized.get("series")
            if symbol_col is None or series_col is None:
                raise ValueError(
                    f"Symbol/series columns missing; columns={list(table.columns)}"
                )

            table = table.dropna(subset=[symbol_col, series_col]).copy()
            table[series_col] = table[series_col].astype(str).str.strip().str.upper()
            if allowed_series is not None:
                table = table[table[series_col].isin(allowed_series)]
            symbols = unique_in_order(yahoo_symbol(x) for x in table[symbol_col])
            if not symbols:
                requested = "ALL" if allowed_series is None else ",".join(allowed_series)
                raise ValueError(f"No symbols returned for NSE series {requested}")
            if allowed_series == ("EQ",) and len(symbols) < 1_500:
                raise ValueError(f"Only {len(symbols)} EQ-series securities returned")
            return symbols
        except Exception as exc:  # noqa: BLE001 - try the next official source
            errors.append(f"{url}: {exc}")
    raise RuntimeError(
        "Could not download the current NSE equity universe. "
        "Use --symbols or --symbols-file. Details: " + " | ".join(errors)
    )


def load_symbols_file(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".csv":
        table = pd.read_csv(path)
        normalized = {str(col).strip().lower(): col for col in table.columns}
        selected = None
        for candidate in ("symbol", "ticker", "yahoo_symbol"):
            if candidate in normalized:
                selected = normalized[candidate]
                break
        if selected is None:
            if table.shape[1] != 1:
                raise ValueError("CSV needs a Symbol, Ticker, or Yahoo_Symbol column")
            selected = table.columns[0]
        raw_symbols = table[selected].dropna().astype(str).tolist()
    else:
        text = path.read_text(encoding="utf-8")
        raw_symbols = [item for line in text.splitlines() for item in line.split(",")]
    symbols = unique_in_order(yahoo_symbol(x) for x in raw_symbols)
    if not symbols:
        raise ValueError(f"No symbols found in {path}")
    return symbols


def chunked(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _standardize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result.columns = [str(col).strip().title().replace(" ", "_") for col in result.columns]
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [col for col in required if col not in result.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {missing}")
    result = result[required].apply(pd.to_numeric, errors="coerce")
    return result.dropna(subset=["Open", "High", "Low", "Close"])


def _extract_downloaded_ticker(
    downloaded: pd.DataFrame, ticker: str, requested_count: int
) -> pd.DataFrame:
    if downloaded.empty:
        return pd.DataFrame()
    if isinstance(downloaded.columns, pd.MultiIndex):
        level0 = downloaded.columns.get_level_values(0)
        level1 = downloaded.columns.get_level_values(1)
        if ticker in level0:
            frame = downloaded[ticker]
        elif ticker in level1:
            frame = downloaded.xs(ticker, axis=1, level=1)
        else:
            return pd.DataFrame()
    elif requested_count == 1:
        frame = downloaded
    else:
        return pd.DataFrame()
    try:
        return _standardize_columns(frame)
    except ValueError:
        return pd.DataFrame()


def _download_with_retries(yf, tickers: list[str] | str, config: ScannerConfig, **kwargs):
    last_error: Exception | None = None
    for attempt in range(1, config.retries + 1):
        try:
            data = yf.download(
                tickers=tickers,
                progress=False,
                timeout=30,
                **kwargs,
            )
            if data is not None and not data.empty:
                return data
            last_error = RuntimeError(
                "Yahoo returned no rows (possible rate limit, temporary outage, "
                "or unsupported ticker)"
            )
        except Exception as exc:  # noqa: BLE001 - provider may raise many error types
            last_error = exc
        if attempt < config.retries:
            time.sleep(config.retry_pause_seconds * attempt)
    raise RuntimeError(str(last_error) if last_error else "Yahoo download failed")


def _normalize_daily_index(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    index = pd.DatetimeIndex(pd.to_datetime(result.index))
    if index.tz is not None:
        index = index.tz_convert(IST).tz_localize(None)
    result.index = index.normalize()
    result = result[~result.index.duplicated(keep="last")].sort_index()
    return result


def drop_partial_daily_bar(frame: pd.DataFrame, include_partial: bool) -> pd.DataFrame:
    if include_partial or frame.empty:
        return frame
    now = datetime.now(IST)
    if now.time() < clock_time(15, 45) and frame.index[-1].date() == now.date():
        return frame.iloc[:-1]
    return frame


def download_daily_data(
    yf,
    symbols: list[str],
    config: ScannerConfig,
    include_partial: bool,
    pause_seconds: float,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, dict[str, str]]:
    errors: dict[str, str] = {}
    benchmark_raw = _download_with_retries(
        yf,
        config.benchmark,
        config,
        period=config.daily_period,
        interval="1d",
        auto_adjust=True,
        repair=True,
        group_by="ticker",
        threads=False,
    )
    benchmark = _extract_downloaded_ticker(benchmark_raw, config.benchmark, 1)
    benchmark = drop_partial_daily_bar(_normalize_daily_index(benchmark), include_partial)
    if benchmark.empty:
        raise RuntimeError(f"No completed daily data for benchmark {config.benchmark}")

    stock_data: dict[str, pd.DataFrame] = {}
    batches = list(chunked(symbols, config.batch_size))
    for batch_number, batch in enumerate(batches, start=1):
        print(
            f"Daily data batch {batch_number}/{len(batches)} ({len(batch)} symbols)...",
            file=sys.stderr,
        )
        try:
            downloaded = _download_with_retries(
                yf,
                batch,
                config,
                period=config.daily_period,
                interval="1d",
                auto_adjust=True,
                repair=True,
                group_by="ticker",
                threads=True,
            )
            for symbol in batch:
                frame = _extract_downloaded_ticker(downloaded, symbol, len(batch))
                frame = drop_partial_daily_bar(_normalize_daily_index(frame), include_partial)
                if frame.empty:
                    errors[symbol] = "No completed daily OHLCV"
                else:
                    stock_data[symbol] = frame
        except Exception as exc:  # noqa: BLE001 - isolate a failed Yahoo batch
            for symbol in batch:
                errors[symbol] = f"Daily download failed: {exc}"
        if batch_number < len(batches) and pause_seconds > 0:
            time.sleep(pause_seconds)
    return stock_data, benchmark, errors


def wilder_atr(frame: pd.DataFrame, length: int) -> pd.Series:
    previous_close = frame["Close"].shift(1)
    true_range = pd.concat(
        [
            frame["High"] - frame["Low"],
            (frame["High"] - previous_close).abs(),
            (frame["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


def williams_r(frame: pd.DataFrame, length: int) -> pd.Series:
    highest = frame["High"].rolling(length, min_periods=length).max()
    lowest = frame["Low"].rolling(length, min_periods=length).min()
    denominator = (highest - lowest).replace(0, np.nan)
    return -100.0 * (highest - frame["Close"]) / denominator


def add_daily_indicators(
    stock: pd.DataFrame, benchmark: pd.DataFrame, config: ScannerConfig
) -> pd.DataFrame:
    aligned = stock.join(
        benchmark[["Close"]].rename(columns={"Close": "Benchmark_Close"}),
        how="inner",
    ).copy()
    aligned["ATR14"] = wilder_atr(aligned, config.atr_length)
    previous_close = aligned["Close"].shift(1)
    aligned["True_Range"] = pd.concat(
        [
            aligned["High"] - aligned["Low"],
            (aligned["High"] - previous_close).abs(),
            (aligned["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    # Track B compares today's observations with baselines known before today.
    # This avoids allowing today's wide/high-volume bar to dilute its own test.
    aligned["ATR14_Prior"] = aligned["ATR14"].shift(1)
    aligned["TR_ATR_Ratio"] = aligned["True_Range"] / aligned[
        "ATR14_Prior"
    ].replace(0, np.nan)
    aligned["NR4"] = aligned["True_Range"].le(
        aligned["True_Range"].rolling(4, min_periods=4).min()
    )
    aligned["WPR3"] = williams_r(aligned, config.wpr_length)
    aligned["SMA50"] = aligned["Close"].rolling(
        config.breadth_sma_length,
        min_periods=config.breadth_sma_length,
    ).mean()
    aligned["EMA10"] = aligned["Close"].ewm(
        span=config.trade_plan_ema_length,
        adjust=False,
        min_periods=config.trade_plan_ema_length,
    ).mean()
    aligned["RS_Ratio"] = aligned["Close"] / aligned["Benchmark_Close"]
    aligned["RS_EMA20"] = aligned["RS_Ratio"].ewm(
        span=config.rs_ema_length,
        adjust=False,
        min_periods=config.rs_ema_length,
    ).mean()
    aligned["Stock_Return_20D"] = aligned["Close"].pct_change(
        config.excess_return_sessions
    )
    aligned["Benchmark_Return_20D"] = aligned["Benchmark_Close"].pct_change(
        config.excess_return_sessions
    )
    aligned["RS_Excess_20D"] = (
        aligned["Stock_Return_20D"] - aligned["Benchmark_Return_20D"]
    )
    aligned["RS_Strong"] = (
        (aligned["RS_Ratio"] > aligned["RS_EMA20"])
        & (
            aligned["RS_EMA20"]
            > aligned["RS_EMA20"].shift(config.rs_slope_sessions)
        )
        & (aligned["RS_Excess_20D"] > 0)
    )
    aligned["Median_Turnover_Cr"] = (
        (aligned["Close"] * aligned["Volume"]).rolling(20, min_periods=20).median()
        / 10_000_000.0
    )
    aligned["Volume_SMA20"] = aligned["Volume"].rolling(20, min_periods=20).mean()
    aligned["Volume_SMA20_Prior"] = aligned["Volume_SMA20"].shift(1)
    aligned["Volume_Ratio"] = aligned["Volume"] / aligned[
        "Volume_SMA20_Prior"
    ].replace(0, np.nan)
    aligned["Volume_Ratio_3D"] = aligned["Volume_Ratio"].rolling(
        3, min_periods=3
    ).mean()
    aligned["Volume_Contraction"] = aligned["Volume"] <= (
        config.volume_contraction_multiplier * aligned["Volume_SMA20"]
    )
    aligned["Daily_Return_Pct"] = aligned["Close"].pct_change() * 100.0
    aligned["Eligibility_Pass"] = (
        (aligned["Close"] >= config.min_price)
        & (aligned["Median_Turnover_Cr"] >= config.min_turnover_crore)
    )
    # No stock-price EMA20 condition belongs to Track B. RS_Strong retains its
    # own RS-ratio EMA because that is the relative-strength definition, not a
    # price-trend filter.
    aligned["Track_B_Daily_Pass"] = (
        aligned["RS_Strong"]
        & aligned["Eligibility_Pass"]
        & aligned["WPR3"].between(
            config.compression_wpr_min,
            config.compression_wpr_max,
            inclusive="both",
        )
        & (
            aligned["TR_ATR_Ratio"].le(config.compression_tr_atr_max)
            | aligned["NR4"]
        )
        & aligned["Volume_Ratio"].le(config.compression_volume_ratio_max)
        & aligned["Volume_Ratio_3D"].le(config.compression_volume_ratio_3d_max)
    )
    return aligned


def add_composite_breadth(
    indicators: dict[str, pd.DataFrame], config: ScannerConfig
) -> pd.DataFrame:
    """Calculate point-in-time breadth and attach it to every symbol frame."""
    if not indicators:
        return pd.DataFrame(
            columns=[
                "Breadth_Pct_Above_SMA50",
                "Breadth_Eligible_Count",
                "Breadth_Pass",
            ]
        )

    eligible_by_symbol: dict[str, pd.Series] = {}
    above_by_symbol: dict[str, pd.Series] = {}
    for symbol, frame in indicators.items():
        eligible = (
            frame["SMA50"].notna()
            & frame["Median_Turnover_Cr"].ge(config.breadth_min_turnover_crore)
        )
        eligible_by_symbol[symbol] = eligible.astype(bool)
        above_by_symbol[symbol] = (
            eligible & frame["Close"].gt(frame["SMA50"])
        ).astype(bool)

    eligible_panel = pd.concat(eligible_by_symbol, axis=1).fillna(False).astype(bool)
    above_panel = pd.concat(above_by_symbol, axis=1).fillna(False).astype(bool)
    eligible_count = eligible_panel.sum(axis=1).astype(int)
    above_count = above_panel.sum(axis=1).astype(int)
    breadth_pct = (100.0 * above_count / eligible_count.replace(0, np.nan)).astype(float)
    breadth_pass = (
        eligible_count.ge(config.breadth_min_constituents)
        & breadth_pct.ge(config.breadth_threshold_pct)
    )
    breadth = pd.DataFrame(
        {
            "Breadth_Pct_Above_SMA50": breadth_pct,
            "Breadth_Eligible_Count": eligible_count,
            "Breadth_Pass": breadth_pass.astype(bool),
        }
    ).sort_index()

    for frame in indicators.values():
        aligned = breadth.reindex(frame.index)
        frame["Breadth_Pct_Above_SMA50"] = aligned[
            "Breadth_Pct_Above_SMA50"
        ]
        frame["Breadth_Eligible_Count"] = aligned[
            "Breadth_Eligible_Count"
        ].fillna(0).astype(int)
        frame["Breadth_Pass"] = aligned["Breadth_Pass"].fillna(False).astype(bool)
    return breadth


def evaluate_benchmark_regime(
    benchmark: pd.DataFrame, ema_length: int
) -> tuple[str, float, float]:
    """Return an auditable benchmark regime label and its latest EMA values."""
    if "Close" not in benchmark:
        return "UNKNOWN", math.nan, math.nan
    close = pd.to_numeric(benchmark["Close"], errors="coerce").dropna()
    if len(close) < ema_length:
        return "UNKNOWN", math.nan, math.nan
    benchmark_close = float(close.iloc[-1])
    benchmark_ema = float(
        close.ewm(span=ema_length, adjust=False, min_periods=ema_length).mean().iloc[-1]
    )
    if not np.isfinite(benchmark_ema):
        return "UNKNOWN", benchmark_close, math.nan
    regime = "RISK_ON" if benchmark_close >= benchmark_ema else "RISK_OFF"
    return regime, benchmark_close, benchmark_ema


def _normalize_intraday(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    index = pd.DatetimeIndex(pd.to_datetime(result.index))
    if index.tz is None:
        index = index.tz_localize(IST)
    else:
        index = index.tz_convert(IST)
    result.index = index
    result = result[~result.index.duplicated(keep="last")].sort_index()
    session_times = result.index.time
    regular = (session_times >= clock_time(9, 15)) & (
        session_times <= clock_time(15, 30)
    )
    result = result.loc[regular].copy()
    result["Session_Date"] = [timestamp.date() for timestamp in result.index]
    return result


def download_intraday_data(
    yf,
    symbols: list[str],
    config: ScannerConfig,
    pause_seconds: float,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Download and normalize 15-minute data in rate-limit-friendly batches."""
    intraday_data: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    batches = list(chunked(symbols, config.intraday_batch_size))
    for batch_number, batch in enumerate(batches, start=1):
        print(
            f"Intraday batch {batch_number}/{len(batches)} ({len(batch)} symbols)...",
            file=sys.stderr,
        )
        try:
            raw = _download_with_retries(
                yf,
                batch,
                config,
                period=config.intraday_period,
                interval=config.intraday_interval,
                auto_adjust=True,
                repair=True,
                prepost=False,
                group_by="ticker",
                threads=True,
            )
            for symbol in batch:
                frame = _extract_downloaded_ticker(raw, symbol, len(batch))
                if frame.empty:
                    errors[symbol] = "No intraday OHLCV"
                else:
                    intraday_data[symbol] = _normalize_intraday(frame)
        except Exception as exc:  # noqa: BLE001 - isolate a failed Yahoo batch
            for symbol in batch:
                errors[symbol] = f"Intraday download failed: {exc}"
        if batch_number < len(batches) and pause_seconds > 0:
            time.sleep(pause_seconds)
    return intraday_data, errors


def extract_value_area(
    profile: np.ndarray,
    edges: np.ndarray,
    poc_idx: int,
    target_pct: float = 0.70,
) -> tuple[float, float]:
    """Expand from POC until the selected bins contain target_pct of volume."""
    total_volume = float(profile.sum())
    if total_volume <= 0 or not 0 < target_pct <= 1:
        return math.nan, math.nan

    target_volume = total_volume * target_pct
    current_volume = float(profile[poc_idx])
    upper_idx = poc_idx
    lower_idx = poc_idx
    n_bins = len(profile)

    while current_volume < target_volume and (
        upper_idx < n_bins - 1 or lower_idx > 0
    ):
        next_upper = (
            float(profile[upper_idx + 1]) if upper_idx < n_bins - 1 else -1.0
        )
        next_lower = float(profile[lower_idx - 1]) if lower_idx > 0 else -1.0
        if (
            upper_idx < n_bins - 1
            and lower_idx > 0
            and math.isclose(next_upper, next_lower, rel_tol=1e-12, abs_tol=1e-9)
        ):
            upper_idx += 1
            lower_idx -= 1
            current_volume += float(profile[upper_idx]) + float(profile[lower_idx])
        elif next_upper > next_lower and upper_idx < n_bins - 1:
            upper_idx += 1
            current_volume += float(profile[upper_idx])
        elif lower_idx > 0:
            lower_idx -= 1
            current_volume += float(profile[lower_idx])
        else:
            break

    return float(edges[lower_idx]), float(edges[upper_idx + 1])


def distribute_volume_profile(
    frame: pd.DataFrame,
    bins: int,
    body_weight: float = 0.70,
) -> tuple[np.ndarray, np.ndarray]:
    """Return price edges and a volume-conserving OHLCV profile.

    Volume is allocated in proportion to each price bin's geometric overlap    with the bar range and candle body. Dojis use the range distribution, and
    a zero-range bar becomes a point mass in its containing bin.
    """
    if bins < 1:
        raise ValueError("Volume-profile bins must be at least 1")
    if not 0 <= body_weight <= 1:
        raise ValueError("Body volume weight must be between 0 and 1")

    required = ["Open", "High", "Low", "Close", "Volume"]
    if frame.empty or any(column not in frame for column in required):
        return np.array([], dtype=float), np.array([], dtype=float)
    clean = frame[required].apply(pd.to_numeric, errors="coerce")
    finite = np.isfinite(clean.to_numpy(dtype=float)).all(axis=1)
    clean = clean.loc[finite & clean["Volume"].gt(0)].copy()
    if clean.empty:
        return np.array([], dtype=float), np.array([], dtype=float)

    raw_highs = clean["High"].to_numpy(dtype=float)
    raw_lows = clean["Low"].to_numpy(dtype=float)
    lows = np.minimum(raw_lows, raw_highs)
    highs = np.maximum(raw_lows, raw_highs)
    opens = np.clip(clean["Open"].to_numpy(dtype=float), lows, highs)
    closes = np.clip(clean["Close"].to_numpy(dtype=float), lows, highs)
    volumes = clean["Volume"].to_numpy(dtype=float)

    profile_low = float(np.min(lows))
    profile_high = float(np.max(highs))
    if profile_high <= profile_low:
        return (
            np.array([profile_low, profile_low], dtype=float),
            np.array([float(volumes.sum())], dtype=float),
        )

    edges = np.linspace(profile_low, profile_high, bins + 1, dtype=float)
    lower_edges = edges[:-1][None, :]
    upper_edges = edges[1:][None, :]

    range_overlap = np.maximum(
        0.0,
        np.minimum(highs[:, None], upper_edges)
        - np.maximum(lows[:, None], lower_edges),
    )
    range_totals = range_overlap.sum(axis=1)
    range_weights = np.zeros_like(range_overlap)
    positive_range = range_totals > 0
    range_weights[positive_range] = (
        range_overlap[positive_range] / range_totals[positive_range, None]
    )

    point_rows = np.flatnonzero(~positive_range)
    if point_rows.size:
        point_bins = np.searchsorted(edges, lows[point_rows], side="right") - 1
        point_bins = np.clip(point_bins, 0, len(edges) - 2)
        range_weights[point_rows, point_bins] = 1.0

    body_lows = np.minimum(opens, closes)
    body_highs = np.maximum(opens, closes)
    body_overlap = np.maximum(
        0.0,
        np.minimum(body_highs[:, None], upper_edges)
        - np.maximum(body_lows[:, None], lower_edges),
    )
    body_totals = body_overlap.sum(axis=1)
    body_weights = range_weights.copy()
    non_doji = body_totals > 0
    body_weights[non_doji] = (
        body_overlap[non_doji] / body_totals[non_doji, None]
    )

    weights = (1.0 - body_weight) * range_weights + body_weight * body_weights
    weight_totals = weights.sum(axis=1)
    weights = np.divide(
        weights,
        weight_totals[:, None],
        out=np.zeros_like(weights),
        where=weight_totals[:, None] > 0,
    )
    return edges, volumes @ weights


def approximate_volume_profile_poc(
    frame: pd.DataFrame,
    bins: int,
    body_weight: float = 0.70,
    value_area_pct: float = 0.70,
) -> tuple[float, float, float]:
    """Return geometric-overlap body-weighted (POC, VAL, VAH)."""
    edges, profile = distribute_volume_profile(frame, bins, body_weight)
    if len(profile) == 0:
        return math.nan, math.nan, math.nan
    if float(edges[-1]) <= float(edges[0]):
        price = float(edges[0])
        return price, price, price

    midpoints = (edges[:-1] + edges[1:]) / 2.0
    maximum = float(np.max(profile))
    tie_tolerance = max(abs(maximum) * 1e-12, 1e-9)
    candidates = np.flatnonzero(np.abs(profile - maximum) <= tie_tolerance)
    profile_midpoint = (float(edges[0]) + float(edges[-1])) / 2.0
    poc_bin = int(
        candidates[np.argmin(np.abs(midpoints[candidates] - profile_midpoint))]
    )
    poc = float((edges[poc_bin] + edges[poc_bin + 1]) / 2.0)
    val, vah = extract_value_area(profile, edges, poc_bin, value_area_pct)
    return poc, val, vah


def latest_confirmed_fractal_low(
    daily: pd.DataFrame,
    target_date,
    earliest_intraday_date,
    left_bars: int = 2,
    right_bars: int = 2,
) -> pd.Timestamp | None:
    """Return the latest strict fractal low known before ``target_date``.

    A candidate at k must be lower than every configured bar on both sides.
    Because only rows before the target are inspected, the right-side bars are
    completed and no lookahead is introduced. The anchor must also be covered
    by the retained intraday history used to construct the profile.
    """
    if "Low" not in daily or left_bars < 1 or right_bars < 1:
        return None
    target_timestamp = pd.Timestamp(target_date).normalize()
    prior = daily.loc[daily.index.normalize() < target_timestamp, ["Low"]].copy()
    prior["Low"] = pd.to_numeric(prior["Low"], errors="coerce")
    if len(prior) < left_bars + right_bars + 1:
        return None

    earliest_timestamp = pd.Timestamp(earliest_intraday_date).normalize()
    lows = prior["Low"].to_numpy(dtype=float)
    confirmed: list[pd.Timestamp] = []
    for position in range(left_bars, len(prior) - right_bars):
        candidate = lows[position]
        if not np.isfinite(candidate):
            continue
        neighbours = np.concatenate(
            (
                lows[position - left_bars : position],
                lows[position + 1 : position + right_bars + 1],
            )
        )
        if np.isfinite(neighbours).all() and bool((candidate < neighbours).all()):
            timestamp = pd.Timestamp(prior.index[position])
            if timestamp.normalize() >= earliest_timestamp:
                confirmed.append(timestamp)
    return confirmed[-1] if confirmed else None


def profile_before_date(
    intraday: pd.DataFrame,
    daily: pd.DataFrame,
    target_date,
    config: ScannerConfig,
) -> tuple[ProfileLevels, int]:
    eligible = intraday[intraday["Session_Date"] < target_date]
    available_sessions = sorted(eligible["Session_Date"].unique())
    available_count = len(available_sessions)
    if available_count < config.poc_sessions:
        return ProfileLevels(sessions=available_count), available_count

    earliest_intraday_date = available_sessions[0]
    anchor_timestamp = latest_confirmed_fractal_low(
        daily,
        target_date,
        earliest_intraday_date,
        config.fractal_left_bars,
        config.fractal_right_bars,
    )
    if anchor_timestamp is None:
        return (
            ProfileLevels(anchor_method="NO_CONFIRMED_FRACTAL_IN_INTRADAY_WINDOW"),
            available_count,
        )

    anchor_date = anchor_timestamp.date()
    selected = eligible[eligible["Session_Date"] >= anchor_date]
    profile_sessions = int(selected["Session_Date"].nunique())
    if selected.empty:
        return ProfileLevels(
            anchor_date=anchor_date.isoformat(),
            sessions=0,
            anchor_method="CONFIRMED_5_BAR_FRACTAL_NO_INTRADAY_BARS",
        ), available_count
    if profile_sessions < config.min_anchored_profile_sessions:
        return (
            ProfileLevels(
                anchor_date=anchor_date.isoformat(),
                sessions=profile_sessions,
                anchor_method="CONFIRMED_5_BAR_FRACTAL_TOO_YOUNG",
            ),
            available_count,
        )

    poc, val, vah = approximate_volume_profile_poc(
        selected,
        config.poc_bins,
        config.body_volume_weight,
        config.value_area_pct,
    )
    selected_low = float(pd.to_numeric(selected["Low"], errors="coerce").min())
    selected_high = float(pd.to_numeric(selected["High"], errors="coerce").max())
    bin_width = (
        (selected_high - selected_low) / config.poc_bins
        if selected_high > selected_low
        else 0.0
    )
    return (
        ProfileLevels(
            poc=poc,
            val=val,
            vah=vah,
            anchor_date=anchor_date.isoformat(),
            sessions=profile_sessions,
            anchor_method="CONFIRMED_5_BAR_FRACTAL_CONTINUOUS_OVERLAP",
            bin_width=bin_width,
        ),
        available_count,
    )


def build_profile_map(
    intraday: pd.DataFrame,
    daily: pd.DataFrame,
    dates: Iterable[pd.Timestamp],
    config: ScannerConfig,
) -> tuple[dict[pd.Timestamp, ProfileLevels], int]:
    result: dict[pd.Timestamp, ProfileLevels] = {}
    minimum_available = config.poc_sessions
    for timestamp in dates:
        levels, available = profile_before_date(
            intraday,
            daily,
            timestamp.date(),
            config,
        )
        minimum_available = min(minimum_available, available)
        result[pd.Timestamp(timestamp)] = levels
    return result, minimum_available


def fixed_profile_before_date(
    intraday: pd.DataFrame,
    target_date,
    config: ScannerConfig,
) -> tuple[ProfileLevels, int]:
    """Build Track B's comparable fixed-session profile from completed bars."""
    eligible = intraday[intraday["Session_Date"] < target_date]
    available_sessions = sorted(eligible["Session_Date"].unique())
    available_count = len(available_sessions)
    required = config.compression_profile_sessions
    if available_count < required:
        return (
            ProfileLevels(
                sessions=available_count,
                anchor_method=f"FIXED_{required}_SESSION_INSUFFICIENT_HISTORY",
            ),
            available_count,
        )

    selected_dates = set(available_sessions[-required:])
    selected = eligible[eligible["Session_Date"].isin(selected_dates)]
    poc, val, vah = approximate_volume_profile_poc(
        selected,
        config.poc_bins,
        config.body_volume_weight,
        config.value_area_pct,
    )
    selected_low = float(pd.to_numeric(selected["Low"], errors="coerce").min())
    selected_high = float(pd.to_numeric(selected["High"], errors="coerce").max())
    bin_width = (
        (selected_high - selected_low) / config.poc_bins
        if selected_high > selected_low
        else 0.0
    )
    return (
        ProfileLevels(
            poc=poc,
            val=val,
            vah=vah,
            anchor_date=min(selected_dates).isoformat(),
            sessions=required,
            anchor_method=f"FIXED_{required}_SESSION_CONTINUOUS_OVERLAP",
            bin_width=bin_width,
        ),
        available_count,
    )


def build_fixed_profile_map(
    intraday: pd.DataFrame,
    dates: Iterable[pd.Timestamp],
    config: ScannerConfig,
) -> tuple[dict[pd.Timestamp, ProfileLevels], int]:
    result: dict[pd.Timestamp, ProfileLevels] = {}
    minimum_available = config.compression_profile_sessions
    for timestamp in dates:
        levels, available = fixed_profile_before_date(
            intraday,
            pd.Timestamp(timestamp).date(),
            config,
        )
        minimum_available = min(minimum_available, available)
        result[pd.Timestamp(timestamp)] = levels
    return result, minimum_available


def _safe_float(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if np.isfinite(result) else math.nan


def profile_method_label(config: ScannerConfig) -> str:
    body_pct = config.body_volume_weight * 100.0
    range_pct = 100.0 - body_pct
    return (
        f"YAHOO_{config.intraday_interval.upper()}_BODY{body_pct:g}_"
        f"RANGE{range_pct:g}_CONTINUOUS_OVERLAP_PRIOR_BARS"
    )


def observe_profile_location(
    close: float,
    previous_close: float,
    atr: float,
    levels: ProfileLevels,
    config: ScannerConfig,
) -> dict[str, object]:
    """Classify price against a fixed prior profile without creating a gate."""
    poc = _safe_float(levels.poc)
    val = _safe_float(levels.val)
    vah = _safe_float(levels.vah)
    bin_width = _safe_float(levels.bin_width)
    if not all(np.isfinite(value) for value in (close, poc, val, vah)):
        return {
            "zone": "UNAVAILABLE",
            "state": "UNAVAILABLE",
            "tolerance": math.nan,
            "distance_pct": math.nan,
            "distance_atr": math.nan,
            "reclaim": False,
            "lost": False,
            "rank_adjustment": 0.0,
        }

    tolerance = max(
        bin_width / 2.0 if np.isfinite(bin_width) and bin_width > 0 else 0.0,
        config.profile_tolerance_atr * atr if atr > 0 else 0.0,
    )
    if close > vah + tolerance:
        zone = "ABOVE_VAH"
    elif close < val - tolerance:
        zone = "BELOW_VAL"
    elif close > poc + tolerance:
        zone = "UPPER_VALUE"
    elif close < poc - tolerance:
        zone = "LOWER_VALUE"
    else:
        zone = "AT_POC"

    reclaim = bool(
        np.isfinite(previous_close)
        and previous_close < poc - tolerance
        and close > poc + tolerance
    )
    lost = bool(
        np.isfinite(previous_close)
        and previous_close > poc + tolerance
        and close < poc - tolerance
    )
    state = "RECLAIMED_POC" if reclaim else "LOST_POC" if lost else zone
    if reclaim:
        rank_adjustment = 5.0
    elif lost:
        rank_adjustment = -3.0
    else:
        rank_adjustment = {
            "ABOVE_VAH": 2.0,
            "UPPER_VALUE": 1.0,
            "AT_POC": 0.5,
            "LOWER_VALUE": 0.0,
            "BELOW_VAL": -2.0,
        }.get(zone, 0.0)

    return {
        "zone": zone,
        "state": state,
        "tolerance": tolerance,
        "distance_pct": (close - poc) / poc * 100.0 if poc > 0 else math.nan,
        "distance_atr": (close - poc) / atr if atr > 0 else math.nan,
        "reclaim": reclaim,
        "lost": lost,
        "rank_adjustment": rank_adjustment,
    }


def breadth_gate_passes(row: pd.Series, config: ScannerConfig) -> bool:
    if not config.require_breadth:
        return True
    value = row.get("Breadth_Pass", False)
    return bool(value) if pd.notna(value) else False


def classify_compression_track(
    daily: pd.DataFrame,
    profiles: dict[pd.Timestamp, ProfileLevels],
    config: ScannerConfig,
    stored_setup: dict[str, object] | None = None,
) -> dict[str, object]:
    """Evaluate the completed-bar Track B watch and its frozen-level follow-up."""
    empty = {
        "state": "NO_MATCH",
        "setup_record": None,
        "current_record": None,
        "reference_type": "",
        "actionability": "NO_MATCH",
        "breakout_trigger": math.nan,
        "breakout_extension_atr": math.nan,
        "breakout_clv": math.nan,
        "breakout_body_ratio": math.nan,
        "breakout_volume_pass": False,
        "indicative_stop": math.nan,
        "indicative_tp1": math.nan,
        "indicative_tp2": math.nan,
        "indicative_rr_tp1": math.nan,
        "compression_age": math.nan,
        "entry_rule": "",
    }
    if daily.empty:
        return empty

    # Calculate a point-in-time width threshold. Each date is compared only
    # with older fixed-profile widths, never with a future observation.
    width_thresholds: dict[pd.Timestamp, float] = {}
    prior_widths: list[float] = []
    for timestamp in sorted(profiles):
        timestamp = pd.Timestamp(timestamp)
        if timestamp not in daily.index:
            continue
        levels = profiles[timestamp]
        atr = _safe_float(daily.loc[timestamp].get("ATR14_Prior"))
        width = (
            (_safe_float(levels.vah) - _safe_float(levels.val)) / atr
            if atr > 0
            and np.isfinite(_safe_float(levels.vah))
            and np.isfinite(_safe_float(levels.val))
            else math.nan
        )
        history = prior_widths[-config.compression_width_lookback_sessions :]
        if len(history) >= config.compression_width_min_observations:
            relative_limit = float(
                np.quantile(history, config.compression_width_percentile)
            )
            width_thresholds[timestamp] = min(
                config.compression_value_area_width_max_atr,
                relative_limit,
            )
        else:
            width_thresholds[timestamp] = config.compression_value_area_width_max_atr
        if np.isfinite(width):
            prior_widths.append(width)

    history_length = config.compression_watch_expiry_sessions + 2
    window = daily.tail(history_length).copy()
    if len(window) < 2:
        return empty

    records: list[dict[str, object]] = []
    for timestamp, row in window.iterrows():
        levels = profiles.get(pd.Timestamp(timestamp), ProfileLevels())
        poc = _safe_float(levels.poc)
        val = _safe_float(levels.val)
        vah = _safe_float(levels.vah)
        close = _safe_float(row.get("Close"))
        atr = _safe_float(row.get("ATR14_Prior"))
        if not np.isfinite(atr) or atr <= 0:
            atr = _safe_float(row.get("ATR14"))
        poc_distance = (
            (close - poc) / atr
            if atr > 0 and np.isfinite(close) and np.isfinite(poc)
            else math.nan
        )
        value_area_width = vah - val if np.isfinite(vah) and np.isfinite(val) else math.nan
        value_area_width_atr = (
            value_area_width / atr
            if atr > 0 and np.isfinite(value_area_width)
            else math.nan
        )
        width_threshold_atr = width_thresholds.get(
            pd.Timestamp(timestamp),
            config.compression_value_area_width_max_atr,
        )
        daily_pass = bool(
            row.get("Track_B_Daily_Pass", False)
            and breadth_gate_passes(row, config)
        )
        watch = bool(
            daily_pass
            and np.isfinite(poc_distance)
            and config.compression_poc_min_atr
            <= poc_distance
            <= config.compression_poc_max_atr
            and np.isfinite(val)
            and np.isfinite(vah)
            and close >= val
            and close <= vah + config.compression_vah_buffer_atr * atr
            and np.isfinite(value_area_width_atr)
            and value_area_width_atr <= width_threshold_atr
        )
        records.append(
            {
                "timestamp": pd.Timestamp(timestamp),
                "close": close,
                "low": _safe_float(row.get("Low")),
                "high": _safe_float(row.get("High")),
                "open": _safe_float(row.get("Open")),
                "poc": poc,
                "val": val,
                "vah": vah,
                "atr": atr,
                "distance": poc_distance,
                "value_area_width": value_area_width,
                "value_area_width_atr": value_area_width_atr,
                "width_threshold_atr": width_threshold_atr,
                "anchor_date": levels.anchor_date,
                "anchor_method": levels.anchor_method,
                "profile_sessions": levels.sessions,
                "daily_pass": daily_pass,
                "watch": watch,
                "setup": watch,
                "structural_stop": (
                    val - config.structural_stop_atr * atr
                    if atr > 0 and np.isfinite(val)
                    else math.nan
                ),
                "risk_reward": math.nan,
            }
        )

    current = window.iloc[-1]
    current_record = records[-1]
    result = dict(empty)
    result["current_record"] = current_record
    if bool(current_record["watch"]):
        result.update(
            {
                "state": "POC_COMPRESSION_WATCH",
                "setup_record": current_record,
                "reference_type": "TRACK_B_NEW_FROZEN_WATCH",
                "actionability": "WATCH_ONLY_BREAKOUT_CONFIRMATION_REQUIRED",
                "compression_age": 0,
                "entry_rule": "NO_ENTRY_UNTIL_LATER_COMPLETED_BAR_CONFIRMS_BREAKOUT",
            }
        )
        return result

    prior_watches = [record for record in records[:-1] if bool(record["watch"])]
    if not prior_watches and stored_setup and bool(stored_setup.get("active", False)):
        try:
            setup_timestamp = pd.Timestamp(stored_setup.get("setup_date")).normalize()
        except (TypeError, ValueError):
            setup_timestamp = pd.NaT
        current_timestamp = pd.Timestamp(current_record["timestamp"]).normalize()
        if pd.notna(setup_timestamp) and setup_timestamp < current_timestamp:
            age = int((daily.index.normalize() > setup_timestamp).sum())
            if age >= 1:
                stored_poc = _safe_float(stored_setup.get("poc"))
                stored_val = _safe_float(stored_setup.get("val"))
                stored_vah = _safe_float(stored_setup.get("vah"))
                stored_atr = _safe_float(stored_setup.get("atr"))
                if all(
                    np.isfinite(value)
                    for value in (stored_poc, stored_val, stored_vah, stored_atr)
                ) and stored_atr > 0:
                    prior_watches.append(
                        {
                            "timestamp": setup_timestamp,
                            "close": math.nan,
                            "poc": stored_poc,
                            "val": stored_val,
                            "vah": stored_vah,
                            "atr": stored_atr,
                            "distance": math.nan,
                            "value_area_width": stored_vah - stored_val,
                            "value_area_width_atr": _safe_float(
                                stored_setup.get("value_area_width_atr")
                            ),
                            "width_threshold_atr": math.nan,
                            "anchor_date": str(
                                stored_setup.get("profile_anchor_date", "")
                            ),
                            "anchor_method": str(
                                stored_setup.get("profile_method", "")
                            ),
                            "profile_sessions": _safe_float(
                                stored_setup.get("profile_sessions")
                            ),
                            "daily_pass": True,
                            "watch": True,
                            "setup": True,
                            "structural_stop": (
                                stored_val - config.structural_stop_atr * stored_atr
                            ),
                            "risk_reward": math.nan,
                            "stored_age": age,
                        }
                    )
    if not prior_watches:
        return result

    setup = prior_watches[-1]
    setup_timestamp = pd.Timestamp(setup["timestamp"])
    current_timestamp = pd.Timestamp(current_record["timestamp"])
    age = int(
        setup.get(
            "stored_age",
            len(window.loc[setup_timestamp:current_timestamp]) - 1,
        )
    )
    setup_atr = _safe_float(setup["atr"])
    setup_val = _safe_float(setup["val"])
    setup_vah = _safe_float(setup["vah"])
    current_close = _safe_float(current_record["close"])
    current_low = _safe_float(current_record["low"])
    current_high = _safe_float(current_record["high"])
    current_open = _safe_float(current_record["open"])
    breakout_trigger = (
        setup_vah + config.compression_vah_buffer_atr * setup_atr
        if setup_atr > 0 and np.isfinite(setup_vah)
        else math.nan
    )
    candle_range = current_high - current_low
    breakout_clv = (
        (current_close - current_low) / candle_range
        if candle_range > 0
        else math.nan
    )
    breakout_body_ratio = (
        abs(current_close - current_open) / candle_range
        if candle_range > 0
        else math.nan
    )
    volume_ratio = _safe_float(current.get("Volume_Ratio"))
    volume_pass = bool(
        np.isfinite(volume_ratio)
        and volume_ratio >= config.breakout_volume_ratio_min
    )
    breakout_confirmed = bool(
        np.isfinite(breakout_trigger)
        and current_close > breakout_trigger
        and volume_pass
        and np.isfinite(breakout_clv)
        and breakout_clv >= config.breakout_clv_min
        and np.isfinite(breakout_body_ratio)
        and breakout_body_ratio >= config.breakout_body_ratio_min
        and _safe_float(current.get("WPR3")) >= config.breakout_wpr_min
    )
    failed_breakout = bool(
        np.isfinite(breakout_trigger)
        and np.isfinite(current_high)
        and current_high > breakout_trigger
        and current_close <= setup_vah
    )

    result.update(
        {
            "setup_record": setup,
            "reference_type": "TRACK_B_PRIOR_FROZEN_WATCH",
            "breakout_trigger": breakout_trigger,
            "breakout_clv": breakout_clv,
            "breakout_body_ratio": breakout_body_ratio,
            "breakout_volume_pass": volume_pass,
            "compression_age": age,
        }
    )

    # Failure/invalidation is evaluated before confirmation so a frozen setup
    # cannot silently reset its support levels on a later day.
    if np.isfinite(setup_val) and current_close < setup_val:
        result.update(
            {
                "state": "INVALIDATED",
                "actionability": "INVALIDATED_NOT_ACTIONABLE",
                "entry_rule": "FROZEN_VAL_LOST",
            }
        )
        return result
    if failed_breakout:
        result.update(
            {
                "state": "FAILED_BREAKOUT",
                "actionability": "INVALIDATED_NOT_ACTIONABLE",
                "entry_rule": "INTRADAY_BREAK_ABOVE_TRIGGER_CLOSED_BACK_BELOW_VAH",
            }
        )
        return result

    if age > config.compression_watch_expiry_sessions:
        result.update(
            {
                "state": "WATCH_EXPIRED",
                "actionability": "EXPIRED_NOT_ACTIONABLE",
                "entry_rule": "WATCH_WINDOW_EXPIRED_WITHOUT_CONFIRMED_BREAKOUT",
            }
        )
        return result

    if breakout_confirmed:
        extension = (current_close - setup_vah) / setup_atr
        stop = max(
            setup_vah - config.breakout_stop_vah_buffer_atr * setup_atr,
            current_low - config.breakout_stop_low_buffer_atr * setup_atr,
        )
        value_area_width = _safe_float(setup["value_area_width"])
        tp1 = current_close + value_area_width
        tp2 = current_close + 2.0 * setup_atr
        risk = current_close - stop
        rr_tp1 = value_area_width / risk if risk > 0 else math.nan
        setup["structural_stop"] = stop
        setup["risk_reward"] = rr_tp1
        if extension > config.breakout_max_extension_atr:
            state = "BREAKOUT_EXTENDED_WAIT_RETEST"
            actionability = "WAIT_RETEST_NOT_ACTIONABLE"
            entry_rule = "DO_NOT_CHASE_WAIT_FOR_RETEST_NEAR_FROZEN_VAH"
        elif not np.isfinite(rr_tp1) or rr_tp1 < config.breakout_min_risk_reward:
            state = "BREAKOUT_CONFIRMED_RR_FAIL"
            actionability = "WAIT_RETEST_RR_INSUFFICIENT"
            entry_rule = "NO_ENTRY_UNLESS_NEXT_OPEN_IMPROVES_REWARD_TO_RISK"
        else:
            state = "BREAKOUT_READY_NEXT_OPEN"
            actionability = "READY_NEXT_OPEN_PRICE_CHECK"
            entry_rule = "NEXT_SESSION_OPEN_IF_GAP_LIQUIDITY_AND_RISK_REMAIN_ACCEPTABLE"
        result.update(
            {
                "state": state,
                "actionability": actionability,
                "breakout_extension_atr": extension,
                "indicative_stop": stop,
                "indicative_tp1": tp1,
                "indicative_tp2": tp2,
                "indicative_rr_tp1": rr_tp1,
                "entry_rule": entry_rule,
            }
        )
        return result

    result.update(
        {
            "state": "POC_COMPRESSION_WATCH",
            "actionability": "WATCH_ONLY_BREAKOUT_CONFIRMATION_REQUIRED",
            "entry_rule": "FROZEN_LEVELS_ACTIVE_WAIT_FOR_COMPLETED_BAR_BREAKOUT",
        }
    )
    return result


def classify_with_profiles(
    symbol: str,
    daily: pd.DataFrame,
    profiles: dict[pd.Timestamp, ProfileLevels],
    config: ScannerConfig,
    include_nonmatch: bool,
    compression_profiles: dict[pd.Timestamp, ProfileLevels] | None = None,
    stored_track_b: dict[str, object] | None = None,
) -> dict | None:
    if daily.empty:
        return None
    window = daily.tail(config.lifecycle_sessions + 1).copy()
    if len(window) < config.lifecycle_sessions + 1:
        return None

    setup_records: list[dict] = []
    for timestamp, row in window.iterrows():
        levels = profiles.get(pd.Timestamp(timestamp), ProfileLevels())
        poc = _safe_float(levels.poc)
        val = _safe_float(levels.val)
        vah = _safe_float(levels.vah)
        atr = _safe_float(row.get("ATR14"))
        close = _safe_float(row.get("Close"))
        distance = (close - poc) / atr if atr > 0 and np.isfinite(poc) else math.nan
        structural_stop = (
            min(val, poc) - (config.structural_stop_atr * atr)
            if atr > 0 and np.isfinite(val) and np.isfinite(poc)
            else math.nan
        )
        risk = close - structural_stop
        risk_reward = (
            (vah - close) / risk
            if risk > 0 and np.isfinite(vah)
            else math.nan
        )
        base_signal = bool(
            row.get("RS_Strong", False)
            and row.get("Eligibility_Pass", False)
            and breadth_gate_passes(row, config)
            and _safe_float(row.get("WPR3")) <= config.wpr_oversold
        )
        auction_breakdown = bool(
            base_signal
            and np.isfinite(val)
            and np.isfinite(poc)
            and close < val
            and close < poc
        )
        setup = bool(
            base_signal
            and row.get("Volume_Contraction", False)
            and np.isfinite(distance)
            and config.poc_distance_min_atr
            <= distance
            <= config.poc_distance_max_atr
            and np.isfinite(val)
            and close >= val
            and np.isfinite(risk_reward)
            and risk_reward >= config.min_risk_reward
        )
        setup_records.append(
            {
                "timestamp": pd.Timestamp(timestamp),
                "close": close,
                "poc": poc,
                "val": val,
                "vah": vah,
                "atr": atr,
                "distance": distance,
                "structural_stop": structural_stop,
                "risk_reward": risk_reward,
                "anchor_date": levels.anchor_date,
                "anchor_method": levels.anchor_method,
                "profile_sessions": levels.sessions,
                "auction_breakdown": auction_breakdown,
                "setup": setup,
            }
        )

    current_timestamp = pd.Timestamp(window.index[-1])
    current = window.iloc[-1]
    current_record = setup_records[-1]
    current_close = _safe_float(current.get("Close"))
    state = "NO_MATCH"
    setup_record: dict | None = None
    reference_type = ""

    if current_record["auction_breakdown"]:
        state = "AUCTION_BREAKDOWN"
        setup_record = current_record
        reference_type = "CURRENT_PROFILE_OBSERVATION"
    elif current_record["setup"]:
        state = "PULLBACK_AT_POC"
        setup_record = current_record
        reference_type = "VALID_SETUP"
    else:
        prior_setups = [record for record in setup_records[:-1] if record["setup"]]
        if prior_setups:
            candidate = prior_setups[-1]
            sessions_since = len(window.loc[candidate["timestamp"] : current_timestamp]) - 1
            current_wpr = _safe_float(current.get("WPR3"))
            extension = (
                (current_close - candidate["poc"]) / candidate["atr"]
                if candidate["atr"] > 0
                else math.nan
            )
            if np.isfinite(candidate["val"]) and current_close < candidate["val"]:
                state = "AUCTION_BREAKDOWN"
                setup_record = candidate
                reference_type = "PRIOR_VALID_SETUP"
            else:
                lifecycle_valid = bool(
                    sessions_since <= config.lifecycle_sessions
                    and current.get("RS_Strong", False)
                    and current.get("Eligibility_Pass", False)
                    and breadth_gate_passes(current, config)
                    and current_wpr > config.wpr_oversold
                    and current_close > candidate["poc"]
                    and np.isfinite(extension)
                )
                if lifecycle_valid:
                    state = (
                        "RECOVERY_FROM_POC"
                        if extension <= config.poc_distance_max_atr
                        else "EXPANSION_AFTER_SETUP"
                    )
                    setup_record = candidate
                    reference_type = "PRIOR_VALID_SETUP"

    # A marginal VAL undercut that remains above the structural stop is a
    # watch-only failed-auction candidate. Measure the undercut from VAL, not
    # from POC, because the two levels can be materially separated.
    if state == "AUCTION_BREAKDOWN" and setup_record is not None:
        reference_val = _safe_float(setup_record.get("val"))
        reference_poc = _safe_float(setup_record.get("poc"))
        reference_atr = _safe_float(setup_record.get("atr"))
        reference_stop = _safe_float(setup_record.get("structural_stop"))
        val_undercut_atr = (
            (current_close - reference_val) / reference_atr
            if reference_atr > 0 and np.isfinite(reference_val)
            else math.nan        )
        poc_extension_atr = (
            (current_close - reference_poc) / reference_atr
            if reference_atr > 0 and np.isfinite(reference_poc)
            else math.nan
        )
        if (
            -config.spring_max_val_undercut_atr <= val_undercut_atr < 0.0
            and -config.spring_max_poc_extension_atr <= poc_extension_atr < 0.0
            and np.isfinite(reference_stop)
            and current_close > reference_stop
        ):
            state = "SPRING_WATCH_AT_VAL"

    strategy_track = "TRACK_A_PULLBACK" if state != "NO_MATCH" else ""
    compression_result = classify_compression_track(
        daily,
        compression_profiles or {},
        config,
        stored_track_b,
    )
    compression_state = str(compression_result["state"])
    if compression_state != "NO_MATCH":
        # Track B is a fresh compression/breakout observation and takes display
        # priority over an older Track A recovery/expansion lifecycle.
        state = compression_state
        setup_record = compression_result["setup_record"]  # type: ignore[assignment]
        reference_type = str(compression_result["reference_type"])
        strategy_track = "TRACK_B_COMPRESSION_BREAKOUT"

    if state == "NO_MATCH" and not include_nonmatch:
        return None

    current_levels = profiles.get(current_timestamp, ProfileLevels())
    current_poc = _safe_float(current_levels.poc)
    current_val = _safe_float(current_levels.val)
    current_vah = _safe_float(current_levels.vah)
    current_atr = _safe_float(current.get("ATR14"))
    previous_close = (
        _safe_float(window["Close"].iloc[-2]) if len(window) >= 2 else math.nan
    )
    current_profile = observe_profile_location(
        current_close,
        previous_close,
        current_atr,
        current_levels,
        config,
    )
    current_poc_distance = _safe_float(current_profile["distance_atr"])
    poc_rank_adjustment = _safe_float(current_profile["rank_adjustment"])
    if state == "SPRING_WATCH_AT_VAL" and current_profile["zone"] == "BELOW_VAL":
        # A controlled VAL undercut is already labelled watch-only and should
        # not receive an additional ranking penalty before its reclaim test.
        poc_rank_adjustment = 0.0
    if setup_record is None:
        reference_date = ""
        setup_date = ""
        sessions_since_setup = math.nan
        setup_poc = math.nan
        setup_val = math.nan
        setup_vah = math.nan
        structural_stop = math.nan
        target_vah = math.nan
        risk_reward = math.nan
        profile_anchor_date = current_levels.anchor_date
        profile_anchor_method = current_levels.anchor_method
        profile_sessions = current_levels.sessions
        extension_atr = math.nan
        val_undercut_atr = math.nan
    else:
        reference_date = setup_record["timestamp"].date().isoformat()
        has_valid_setup = bool(setup_record.get("setup", False))
        setup_date = reference_date if has_valid_setup else ""
        sessions_since_setup = (
            len(window.loc[setup_record["timestamp"] : current_timestamp]) - 1
            if has_valid_setup
            else math.nan
        )
        setup_poc = setup_record["poc"]
        setup_val = setup_record["val"]
        setup_vah = setup_record["vah"]
        structural_stop = setup_record["structural_stop"]
        target_vah = setup_vah
        current_risk = current_close - structural_stop
        risk_reward = (
            (target_vah - current_close) / current_risk
            if current_risk > 0 and np.isfinite(target_vah)
            else math.nan
        )
        profile_anchor_date = setup_record["anchor_date"]
        profile_anchor_method = setup_record["anchor_method"]
        profile_sessions = setup_record["profile_sessions"]
        extension_atr = (
            (current_close - setup_poc) / setup_record["atr"]
            if setup_record["atr"] > 0
            else math.nan
        )
        val_undercut_atr = (
            (current_close - setup_val) / setup_record["atr"]
            if setup_record["atr"] > 0 and np.isfinite(setup_val)
            else math.nan
        )

    if state in ("AUCTION_BREAKDOWN", "INVALIDATED", "FAILED_BREAKOUT", "WATCH_EXPIRED"):
        structural_stop = math.nan
        target_vah = math.nan
        risk_reward = math.nan

    if strategy_track == "TRACK_B_COMPRESSION_BREAKOUT":
        actionability = str(compression_result["actionability"])
    elif state in ACTIVE_STATES:
        actionability = "RESEARCH_CANDIDATE"
    elif state in WATCH_STATES:
        actionability = "WATCH_ONLY_VAL_RECLAIM_REQUIRED"
    elif state == "AUCTION_BREAKDOWN":
        actionability = "INVALIDATED_NOT_ACTIONABLE"
    else:
        actionability = "NO_MATCH"

    if (
        strategy_track == "TRACK_B_COMPRESSION_BREAKOUT"
        and state == "BREAKOUT_READY_NEXT_OPEN"
        and setup_record is not None
    ):
        model_b_status = "CONDITIONAL_NEXT_OPEN_NO_FILL_TRACKING"
        model_b_reference_entry = current_close
        model_b_scale_out_pct = 50.0
        model_b_scale_out_level = _safe_float(compression_result["indicative_tp1"])
        model_b_breakeven_level = current_close
        model_b_runner_trail_ema10 = _safe_float(current.get("EMA10"))
        model_b_activation_rule = str(compression_result["entry_rule"])
        model_b_runner_exit_rule = "COMPLETED_DAILY_CLOSE_BELOW_EMA10_AFTER_TP1"
    elif state in ACTIVE_STATES and setup_record is not None:
        model_b_status = "REFERENCE_ONLY_NO_FILL_TRACKING"
        model_b_reference_entry = _safe_float(setup_record.get("close"))
        model_b_scale_out_pct = 50.0
        model_b_scale_out_level = target_vah
        model_b_breakeven_level = model_b_reference_entry
        model_b_runner_trail_ema10 = _safe_float(current.get("EMA10"))
        model_b_activation_rule = "AFTER_VAH_SCALE_OUT_CONFIRMED"
        model_b_runner_exit_rule = "COMPLETED_DAILY_CLOSE_BELOW_EMA10"
    else:
        model_b_status = (
            "WATCH_ONLY_NO_TRADE_PLAN"
            if state in WATCH_STATES
            else "INVALIDATED_NO_TRADE_PLAN"
            if state in ("AUCTION_BREAKDOWN", "INVALIDATED", "FAILED_BREAKOUT")
            else "EXPIRED_NO_TRADE_PLAN"
            if state == "WATCH_EXPIRED"
            else "NO_PLAN"
        )
        model_b_reference_entry = math.nan
        model_b_scale_out_pct = math.nan
        model_b_scale_out_level = math.nan
        model_b_breakeven_level = math.nan
        model_b_runner_trail_ema10 = math.nan
        model_b_activation_rule = ""
        model_b_runner_exit_rule = ""

    compression_current = compression_result.get("current_record")
    compression_current = (
        compression_current if isinstance(compression_current, dict) else {}
    )

    return {
        "Symbol": display_symbol(symbol),
        "Yahoo_Symbol": symbol,
        "As_Of": current_timestamp.date().isoformat(),
        "Research_State": state,
        "Strategy_Track": strategy_track or "NONE",
        "Actionability": actionability,
        "Reference_Date": reference_date,
        "Reference_Type": reference_type,
        "Setup_Date": setup_date,
        "Sessions_Since_Setup": sessions_since_setup,
        "Close": current_close,
        "Daily_Return_Pct": _safe_float(current.get("Daily_Return_Pct")),
        "RS_Ratio": _safe_float(current.get("RS_Ratio")),
        "RS_EMA20": _safe_float(current.get("RS_EMA20")),
        "RS_Excess_20D_Pct": _safe_float(current.get("RS_Excess_20D")) * 100.0,
        "RS_Strong": bool(current.get("RS_Strong", False)),
        "Williams_R_3": _safe_float(current.get("WPR3")),
        "ATR14": current_atr,
        "SMA50": _safe_float(current.get("SMA50")),
        "EMA10": _safe_float(current.get("EMA10")),
        "Volume_SMA20": _safe_float(current.get("Volume_SMA20")),
        "Volume_Contraction": bool(current.get("Volume_Contraction", False)),
        "True_Range": _safe_float(current.get("True_Range")),
        "Track_B_TR_ATR_Ratio": _safe_float(current.get("TR_ATR_Ratio")),
        "Track_B_NR4": bool(current.get("NR4", False)),
        "Track_B_Volume_Ratio": _safe_float(current.get("Volume_Ratio")),
        "Track_B_Volume_Ratio_3D": _safe_float(current.get("Volume_Ratio_3D")),
        "Track_B_Daily_Pass": bool(current.get("Track_B_Daily_Pass", False)),
        "Track_B_Price_EMA20_Required": False,
        "Setup_POC": setup_poc,
        "VAL": setup_val,
        "VAH": setup_vah,
        "Current_Anchored_POC": current_poc,
        "Current_VAL": current_val,
        "Current_VAH": current_vah,
        "Current_Profile_Zone": current_profile["zone"],
        "Current_POC_State": current_profile["state"],
        "Current_POC_Distance_Pct": current_profile["distance_pct"],
        "Current_POC_Distance_ATR": current_poc_distance,
        "Current_POC_Reclaim": current_profile["reclaim"],
        "Current_POC_Lost": current_profile["lost"],
        "Current_Profile_Tolerance": current_profile["tolerance"],
        "POC_Rank_Adjustment": poc_rank_adjustment,
        "Extension_From_Setup_POC_ATR": extension_atr,
        "VAL_Undercut_ATR": val_undercut_atr,
        "Stop_Loss_Structural": structural_stop,
        "Target_VAH": target_vah,
        "Risk_Reward_Ratio": risk_reward,
        "Profile_Anchor_Date": profile_anchor_date,
        "Profile_Anchor_Method": profile_anchor_method,
        "Profile_Sessions": profile_sessions,
        "Current_Profile_Bin_Width": current_levels.bin_width,
        "Profile_Method": profile_method_label(config),
        "Compression_POC": _safe_float(compression_current.get("poc")),
        "Compression_VAL": _safe_float(compression_current.get("val")),
        "Compression_VAH": _safe_float(compression_current.get("vah")),
        "Compression_POC_Distance_ATR": _safe_float(
            compression_current.get("distance")
        ),
        "Compression_Value_Area_Width_ATR": _safe_float(
            compression_current.get("value_area_width_atr")
        ),
        "Compression_Width_Threshold_ATR": _safe_float(
            compression_current.get("width_threshold_atr")
        ),
        "Compression_Profile_Sessions": _safe_float(
            compression_current.get("profile_sessions")
        ),
        "Compression_Profile_Method": str(
            compression_current.get("anchor_method", "")
        ),
        "Compression_Setup_Date": (
            pd.Timestamp(setup_record["timestamp"]).date().isoformat()
            if strategy_track == "TRACK_B_COMPRESSION_BREAKOUT"
            and setup_record is not None
            else ""
        ),
        "Compression_Setup_ATR": (
            _safe_float(setup_record.get("atr"))
            if strategy_track == "TRACK_B_COMPRESSION_BREAKOUT"
            and setup_record is not None
            else math.nan
        ),
        "Compression_Setup_Value_Area_Width_ATR": (
            _safe_float(setup_record.get("value_area_width_atr"))
            if strategy_track == "TRACK_B_COMPRESSION_BREAKOUT"
            and setup_record is not None
            else math.nan
        ),
        "Compression_Age_Sessions": _safe_float(
            compression_result["compression_age"]
        ),
        "Breakout_Trigger": _safe_float(compression_result["breakout_trigger"]),
        "Breakout_Extension_ATR": _safe_float(
            compression_result["breakout_extension_atr"]
        ),
        "Breakout_Close_Location": _safe_float(compression_result["breakout_clv"]),
        "Breakout_Body_Ratio": _safe_float(
            compression_result["breakout_body_ratio"]
        ),
        "Breakout_Volume_Pass": bool(compression_result["breakout_volume_pass"]),
        "Indicative_Next_Open_Stop": _safe_float(
            compression_result["indicative_stop"]
        ),
        "Indicative_TP1": _safe_float(compression_result["indicative_tp1"]),
        "Indicative_TP2": _safe_float(compression_result["indicative_tp2"]),
        "Indicative_RR_TP1": _safe_float(compression_result["indicative_rr_tp1"]),
        "Track_B_Entry_Rule": str(compression_result["entry_rule"]),
        "Median_Turnover_Cr": _safe_float(current.get("Median_Turnover_Cr")),
        "Breadth_Pct_Above_SMA50": _safe_float(
            current.get("Breadth_Pct_Above_SMA50")
        ),
        "Breadth_Eligible_Count": _safe_float(
            current.get("Breadth_Eligible_Count")
        ),
        "Breadth_Pass": bool(current.get("Breadth_Pass", False)),
        "Breadth_Gate_Required": config.require_breadth,
        "Model_B_Status": model_b_status,
        "Model_B_Reference_Entry": model_b_reference_entry,
        "Model_B_Scale_Out_Pct": model_b_scale_out_pct,
        "Model_B_Scale_Out_Level_VAH": model_b_scale_out_level,
        "Model_B_Breakeven_After_VAH": model_b_breakeven_level,
        "Model_B_Runner_Trail_EMA10": model_b_runner_trail_ema10,
        "Model_B_Activation_Rule": model_b_activation_rule,
        "Model_B_Runner_Exit_Rule": model_b_runner_exit_rule,
        "Data_Quality": (
            "B_APPROX_YAHOO_15M_CONTINUOUS_OVERLAP_FIXED_15_SESSION"
            if strategy_track == "TRACK_B_COMPRESSION_BREAKOUT"
            else "B_APPROX_YAHOO_15M_CONTINUOUS_OVERLAP_FRACTAL_ANCHORED"
        ),
        "Hypothesis_ID": HYPOTHESIS_ID,
        "Rule_Version": VERSION,
    }


def diagnostic_row(
    symbol: str,
    daily: pd.DataFrame,
    reason: str,
    config: ScannerConfig | None = None,
) -> dict:
    row = daily.iloc[-1] if not daily.empty else pd.Series(dtype=float)
    timestamp = daily.index[-1] if not daily.empty else None
    return {
        "Symbol": display_symbol(symbol),
        "Yahoo_Symbol": symbol,
        "As_Of": pd.Timestamp(timestamp).date().isoformat() if timestamp is not None else "",
        "Research_State": "DATA_INCOMPLETE",
        "Strategy_Track": "NONE",
        "Actionability": "DATA_INCOMPLETE",
        "Reference_Date": "",
        "Reference_Type": "",
        "Setup_Date": "",
        "Sessions_Since_Setup": math.nan,
        "Close": _safe_float(row.get("Close")),
        "Daily_Return_Pct": _safe_float(row.get("Daily_Return_Pct")),
        "RS_Ratio": _safe_float(row.get("RS_Ratio")),
        "RS_EMA20": _safe_float(row.get("RS_EMA20")),
        "RS_Excess_20D_Pct": _safe_float(row.get("RS_Excess_20D")) * 100.0,
        "RS_Strong": bool(row.get("RS_Strong", False)),
        "Williams_R_3": _safe_float(row.get("WPR3")),
        "ATR14": _safe_float(row.get("ATR14")),
        "SMA50": _safe_float(row.get("SMA50")),
        "EMA10": _safe_float(row.get("EMA10")),
        "Volume_SMA20": _safe_float(row.get("Volume_SMA20")),
        "Volume_Contraction": bool(row.get("Volume_Contraction", False)),
        "True_Range": _safe_float(row.get("True_Range")),
        "Track_B_TR_ATR_Ratio": _safe_float(row.get("TR_ATR_Ratio")),
        "Track_B_NR4": bool(row.get("NR4", False)),
        "Track_B_Volume_Ratio": _safe_float(row.get("Volume_Ratio")),
        "Track_B_Volume_Ratio_3D": _safe_float(row.get("Volume_Ratio_3D")),
        "Track_B_Daily_Pass": bool(row.get("Track_B_Daily_Pass", False)),
        "Track_B_Price_EMA20_Required": False,
        "Setup_POC": math.nan,
        "VAL": math.nan,
        "VAH": math.nan,
        "Current_Anchored_POC": math.nan,
        "Current_VAL": math.nan,
        "Current_VAH": math.nan,
        "Current_Profile_Zone": "UNAVAILABLE",
        "Current_POC_State": "UNAVAILABLE",
        "Current_POC_Distance_Pct": math.nan,
        "Current_POC_Distance_ATR": math.nan,
        "Current_POC_Reclaim": False,
        "Current_POC_Lost": False,
        "Current_Profile_Tolerance": math.nan,
        "POC_Rank_Adjustment": 0.0,
        "Extension_From_Setup_POC_ATR": math.nan,
        "VAL_Undercut_ATR": math.nan,
        "Stop_Loss_Structural": math.nan,
        "Target_VAH": math.nan,
        "Risk_Reward_Ratio": math.nan,
        "Profile_Anchor_Date": "",
        "Profile_Anchor_Method": "",
        "Profile_Sessions": math.nan,
        "Current_Profile_Bin_Width": math.nan,
        "Profile_Method": profile_method_label(config or ScannerConfig()),
        "Compression_POC": math.nan,
        "Compression_VAL": math.nan,
        "Compression_VAH": math.nan,
        "Compression_POC_Distance_ATR": math.nan,
        "Compression_Value_Area_Width_ATR": math.nan,
        "Compression_Width_Threshold_ATR": math.nan,
        "Compression_Profile_Sessions": math.nan,
        "Compression_Profile_Method": "",
        "Compression_Setup_Date": "",
        "Compression_Setup_ATR": math.nan,
        "Compression_Setup_Value_Area_Width_ATR": math.nan,
        "Compression_Age_Sessions": math.nan,
        "Breakout_Trigger": math.nan,
        "Breakout_Extension_ATR": math.nan,
        "Breakout_Close_Location": math.nan,
        "Breakout_Body_Ratio": math.nan,
        "Breakout_Volume_Pass": False,
        "Indicative_Next_Open_Stop": math.nan,
        "Indicative_TP1": math.nan,
        "Indicative_TP2": math.nan,
        "Indicative_RR_TP1": math.nan,
        "Track_B_Entry_Rule": "",
        "Median_Turnover_Cr": _safe_float(row.get("Median_Turnover_Cr")),
        "Breadth_Pct_Above_SMA50": _safe_float(
            row.get("Breadth_Pct_Above_SMA50")
        ),
        "Breadth_Eligible_Count": _safe_float(row.get("Breadth_Eligible_Count")),
        "Breadth_Pass": bool(row.get("Breadth_Pass", False)),
        "Breadth_Gate_Required": bool(config.require_breadth) if config else False,
        "Model_B_Status": "NO_PLAN",
        "Model_B_Reference_Entry": math.nan,
        "Model_B_Scale_Out_Pct": math.nan,
        "Model_B_Scale_Out_Level_VAH": math.nan,
        "Model_B_Breakeven_After_VAH": math.nan,
        "Model_B_Runner_Trail_EMA10": math.nan,
        "Model_B_Activation_Rule": "",
        "Model_B_Runner_Exit_Rule": "",
        "Data_Quality": reason,
        "Hypothesis_ID": HYPOTHESIS_ID,
        "Rule_Version": VERSION,
    }


def daily_prefilter(daily: pd.DataFrame, config: ScannerConfig) -> bool:
    lookback = max(
        config.lifecycle_sessions,
        config.compression_watch_expiry_sessions + 1,
    )
    recent = daily.tail(lookback + 1)
    track_a = (
        recent["RS_Strong"]
        & recent["Eligibility_Pass"]
        & (recent["WPR3"] <= config.wpr_oversold)
    )
    track_b = recent["Track_B_Daily_Pass"].fillna(False)
    if config.require_breadth:
        breadth = recent["Breadth_Pass"].fillna(False)
        track_a = track_a & breadth
        track_b = track_b & breadth
    return bool((track_a | track_b).any())


def round_output(table: pd.DataFrame) -> pd.DataFrame:
    rounded = table.copy()
    decimals = {
        "Close": 2,
        "Daily_Return_Pct": 2,
        "RS_Ratio": 5,
        "RS_EMA20": 5,
        "RS_Excess_20D_Pct": 2,
        "Williams_R_3": 2,
        "ATR14": 2,
        "SMA50": 2,
        "EMA10": 2,
        "Volume_SMA20": 0,
        "True_Range": 2,
        "Track_B_TR_ATR_Ratio": 2,
        "Track_B_Volume_Ratio": 2,
        "Track_B_Volume_Ratio_3D": 2,
        "Setup_POC": 2,
        "VAL": 2,
        "VAH": 2,
        "Current_Anchored_POC": 2,
        "Current_VAL": 2,
        "Current_VAH": 2,
        "Current_POC_Distance_Pct": 2,
        "Current_POC_Distance_ATR": 2,
        "Current_Profile_Tolerance": 4,
        "POC_Rank_Adjustment": 1,
        "Extension_From_Setup_POC_ATR": 2,
        "VAL_Undercut_ATR": 2,
        "Stop_Loss_Structural": 2,
        "Target_VAH": 2,
        "Risk_Reward_Ratio": 2,
        "Current_Profile_Bin_Width": 4,
        "Compression_POC": 2,
        "Compression_VAL": 2,
        "Compression_VAH": 2,
        "Compression_POC_Distance_ATR": 2,
        "Compression_Value_Area_Width_ATR": 2,
        "Compression_Width_Threshold_ATR": 2,
        "Compression_Profile_Sessions": 0,
        "Compression_Age_Sessions": 0,
        "Compression_Setup_ATR": 2,
        "Compression_Setup_Value_Area_Width_ATR": 2,
        "Breakout_Trigger": 2,
        "Breakout_Extension_ATR": 2,
        "Breakout_Close_Location": 2,
        "Breakout_Body_Ratio": 2,
        "Indicative_Next_Open_Stop": 2,
        "Indicative_TP1": 2,
        "Indicative_TP2": 2,
        "Indicative_RR_TP1": 2,
        "Median_Turnover_Cr": 2,
        "Breadth_Pct_Above_SMA50": 2,
        "Breadth_Eligible_Count": 0,
        "Model_B_Reference_Entry": 2,
        "Model_B_Scale_Out_Pct": 0,
        "Model_B_Scale_Out_Level_VAH": 2,
        "Model_B_Breakeven_After_VAH": 2,
        "Model_B_Runner_Trail_EMA10": 2,
        "Benchmark_Close": 2,
        "Benchmark_EMA20": 2,
        "State_Rank_Pct": 1,
    }
    for column, digits in decimals.items():
        if column in rounded:
            rounded[column] = pd.to_numeric(rounded[column], errors="coerce").round(digits)
    return rounded


def add_state_percentile_ranking(table: pd.DataFrame) -> pd.DataFrame:
    """Rank comparable rows within each state; do not mix unlike strategies."""
    ranked = table.copy()
    ranked["State_Rank_Pct"] = math.nan
    if ranked.empty:
        return ranked
    for _, indices in ranked.groupby("Research_State", dropna=False).groups.items():
        group = ranked.loc[indices]
        components: list[pd.Series] = []
        rs = pd.to_numeric(group["RS_Excess_20D_Pct"], errors="coerce")
        components.append(rs.rank(pct=True, method="average"))
        if bool(group["Strategy_Track"].eq("TRACK_B_COMPRESSION_BREAKOUT").any()):
            for column, ascending in (
                ("Compression_Value_Area_Width_ATR", False),
                ("Track_B_Volume_Ratio_3D", False),
                ("Breakout_Close_Location", True),
            ):
                values = pd.to_numeric(group[column], errors="coerce")
                if values.notna().any():
                    components.append(
                        values.rank(
                            pct=True,
                            method="average",
                            ascending=ascending,
                        )
                    )
        else:
            values = pd.to_numeric(group["POC_Rank_Adjustment"], errors="coerce")
            if values.notna().any():
                components.append(values.rank(pct=True, method="average"))
        score = pd.concat(components, axis=1).mean(axis=1, skipna=True) * 100.0
        ranked.loc[indices, "State_Rank_Pct"] = score
    return ranked


def load_lifecycle_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"schema_version": 1, "symbols": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARNING: Could not read state file {path}: {exc}", file=sys.stderr)
        return {"schema_version": 1, "symbols": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), dict):
        print(f"WARNING: Ignoring malformed state file {path}", file=sys.stderr)
        return {"schema_version": 1, "symbols": {}}
    return payload


def active_state_symbols(state: dict[str, object]) -> set[str]:
    symbols = state.get("symbols", {})
    if not isinstance(symbols, dict):
        return set()
    return {
        str(symbol)
        for symbol, record in symbols.items()
        if isinstance(record, dict) and bool(record.get("active", False))
    }


def update_lifecycle_state(
    state: dict[str, object],
    symbol: str,
    row: dict,
) -> None:
    symbols = state.setdefault("symbols", {})
    if not isinstance(symbols, dict):
        symbols = {}
        state["symbols"] = symbols
    research_state = str(row.get("Research_State", ""))
    if row.get("Strategy_Track") != "TRACK_B_COMPRESSION_BREAKOUT":
        if symbol in symbols and research_state not in ("DATA_INCOMPLETE", ""):
            previous = symbols[symbol]
            if isinstance(previous, dict):
                previous["active"] = False
                previous["last_state"] = research_state
                previous["last_evaluated_date"] = row.get("As_Of", "")
        return

    active = research_state in (
        "POC_COMPRESSION_WATCH",
        "BREAKOUT_EXTENDED_WAIT_RETEST",
        "BREAKOUT_CONFIRMED_RR_FAIL",
    )
    def finite_or_none(value):
        number = _safe_float(value)
        return number if np.isfinite(number) else None

    symbols[symbol] = {
        "active": active,
        "last_state": research_state,
        "setup_date": row.get("Compression_Setup_Date", ""),
        "last_evaluated_date": row.get("As_Of", ""),
        "poc": finite_or_none(row.get("Setup_POC")),
        "val": finite_or_none(row.get("VAL")),
        "vah": finite_or_none(row.get("VAH")),
        "atr": finite_or_none(row.get("Compression_Setup_ATR")),
        "value_area_width_atr": finite_or_none(
            row.get("Compression_Setup_Value_Area_Width_ATR")
        ),
        "profile_anchor_date": row.get("Profile_Anchor_Date", ""),
        "profile_method": row.get("Profile_Anchor_Method", ""),
        "profile_sessions": finite_or_none(row.get("Profile_Sessions")),
        "rule_version": VERSION,
    }


def write_lifecycle_state(state: dict[str, object], path: Path) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    state["schema_version"] = 1
    state["updated_at_ist"] = datetime.now(IST).isoformat(timespec="seconds")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(state, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _unique_csv_path(directory: Path, output_path: Path) -> Path:
    timestamp = datetime.now(IST).strftime("%H%M%S_%f")
    suffix = output_path.suffix or ".csv"
    stem = output_path.stem or "nifty500_rs_wpr_poc"
    return directory / f"{stem}_{timestamp}{suffix}"


def write_csv_with_fallback(output: pd.DataFrame, output_path: Path) -> Path:
    """Write results, falling back when the requested file/location is locked."""
    requested_path = output_path.expanduser()
    attempts = [requested_path]

    # A unique name in the requested directory handles a CSV currently open in
    # Excel and a directory that happens to have the requested CSV name.
    attempts.append(_unique_csv_path(requested_path.parent, requested_path))

    # A caller can launch this script from a protected working directory.  The
    # script directory is normally user-writable and is a predictable fallback.
    script_directory = Path(__file__).resolve().parent
    attempts.append(_unique_csv_path(script_directory, requested_path))

    # Last resort: the OS per-user temporary directory should be writable.
    attempts.append(_unique_csv_path(Path(tempfile.gettempdir()), requested_path))

    seen: set[Path] = set()
    failures: list[str] = []
    for candidate in attempts:
        absolute_candidate = candidate.absolute()
        if absolute_candidate in seen:
            continue
        seen.add(absolute_candidate)
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            output.to_csv(candidate, index=False)
            if candidate != requested_path:
                print(
                    f"WARNING: Could not write {requested_path.absolute()}. "
                    f"Saved results to {candidate.absolute()} instead.",
                    file=sys.stderr,
                )
            return candidate
        except (PermissionError, IsADirectoryError) as exc:
            failures.append(f"{absolute_candidate}: {exc}")

    raise PermissionError(
        "Could not save the CSV in any writable fallback location. "
        + " | ".join(failures)
    )


def run_self_test() -> None:
    assert parse_nse_series("eq") == ("EQ",)
    assert parse_nse_series("EQ,BE,EQ") == ("EQ", "BE")
    assert parse_nse_series("ALL") is None

    dates = pd.date_range("2026-01-01", periods=30, freq="B")
    base = pd.DataFrame(
        {
            "Open": np.linspace(100, 103, 30),
            "High": np.linspace(101, 104, 30),
            "Low": np.linspace(99, 102, 30),
            "Close": np.linspace(100, 103, 30),
            "Volume": np.full(30, 100_000),
        },
        index=dates,
    )
    wpr = williams_r(base, 3)
    assert wpr.notna().sum() == 28
    atr = wilder_atr(base, 14)
    assert atr.notna().sum() == 17

    fractal_dates = pd.date_range("2026-02-02", periods=7, freq="B")
    fractal_daily = pd.DataFrame(
        {"Low": [11.0, 10.0, 8.0, 10.0, 11.0, 9.0, 10.0]},
        index=fractal_dates,
    )
    assert (
        latest_confirmed_fractal_low(
            fractal_daily,
            fractal_dates[4],
            fractal_dates[0].date(),
        )
        is None
    )
    confirmed = latest_confirmed_fractal_low(
        fractal_daily,
        fractal_dates[5],
        fractal_dates[0].date(),
    )
    assert confirmed == fractal_dates[2], confirmed
    assert (
        latest_confirmed_fractal_low(
            fractal_daily,
            fractal_dates[5],
            fractal_dates[3].date(),
        )
        is None
    )

    profile_bars = pd.DataFrame(
        {
            "Open": [99.9, 100.0, 104.2, 102.0],
            "Low": [99.8, 99.9, 104.0, 102.0],
            "High": [100.2, 100.1, 105.0, 102.0],
            "Close": [100.0, 100.0, 104.3, 102.0],
            "Volume": [1_000_000, 2_000_000, 1_000, 500_000],
        }
    )
    profile_edges, distributed_volume = distribute_volume_profile(profile_bars, 50)
    assert len(profile_edges) == 51
    assert np.isclose(distributed_volume.sum(), profile_bars["Volume"].sum())
    assert bool((distributed_volume >= 0).all())
    poc, val, vah = approximate_volume_profile_poc(profile_bars, 50)
    assert 99.7 <= poc <= 100.4, poc
    assert val <= poc <= vah, (val, poc, vah)
    tie_val, tie_vah = extract_value_area(
        np.array([10.0, 50.0, 30.0, 10.0]),
        np.array([0.0, 1.0, 2.0, 3.0, 4.0]),
        1,
        0.70,
    )
    assert (tie_val, tie_vah) == (1.0, 3.0)

    observed = observe_profile_location(
        close=101.0,
        previous_close=99.0,
        atr=2.0,
        levels=ProfileLevels(poc=100.0, val=98.0, vah=104.0, bin_width=0.20),
        config=ScannerConfig(),
    )
    assert observed["state"] == "RECLAIMED_POC", observed
    assert observed["rank_adjustment"] == 5.0

    breadth_config = ScannerConfig(
        min_turnover_crore=0.0,
        breadth_min_turnover_crore=0.0,
        breadth_min_constituents=2,
    )
    breadth_index = pd.date_range("2026-03-02", periods=2, freq="B")
    breadth_frames = {
        "A.NS": pd.DataFrame(
            {
                "Close": [90.0, 110.0],
                "SMA50": [100.0, 100.0],
                "Median_Turnover_Cr": [10.0, 10.0],
            },
            index=breadth_index,
        ),
        "B.NS": pd.DataFrame(
            {
                "Close": [110.0, 90.0],
                "SMA50": [100.0, 100.0],
                "Median_Turnover_Cr": [10.0, 10.0],
            },
            index=breadth_index,
        ),
    }
    breadth = add_composite_breadth(breadth_frames, breadth_config)
    assert breadth.loc[breadth_index[-1], "Breadth_Eligible_Count"] == 2
    assert breadth.loc[breadth_index[-1], "Breadth_Pct_Above_SMA50"] == 50.0
    assert bool(breadth.loc[breadth_index[-1], "Breadth_Pass"])

    config = ScannerConfig(min_turnover_crore=0.0)
    test = pd.DataFrame(index=pd.date_range("2026-09-21", periods=6, freq="B"))
    test["Close"] = [100.0, 100.5, 100.1, 100.3, 100.2, 105.0]
    test["ATR14"] = 2.0
    test["WPR3"] = [-30.0, -40.0, -90.0, -60.0, -35.0, -10.0]
    test["RS_Ratio"] = 0.10
    test["RS_EMA20"] = 0.09
    test["RS_Excess_20D"] = 0.05
    test["RS_Strong"] = True
    test["Eligibility_Pass"] = True
    test["Volume_SMA20"] = 100_000.0
    test["Volume_Contraction"] = True
    test["Daily_Return_Pct"] = test["Close"].pct_change() * 100
    test["Median_Turnover_Cr"] = 5.0
    test["EMA10"] = 101.0
    profiles = {
        timestamp: ProfileLevels(100.0, 99.0, 110.0, "2026-08-01", 30)
        for timestamp in test.index
    }
    result = classify_with_profiles(
        "KIRLOSENG.NS", test, profiles, config, False
    )
    assert result is not None
    assert result["Research_State"] == "EXPANSION_AFTER_SETUP", result
    assert result["Setup_Date"] == test.index[2].date().isoformat()
    assert result["Model_B_Status"] == "REFERENCE_ONLY_NO_FILL_TRACKING"
    assert result["Model_B_Reference_Entry"] == 100.1
    assert result["Model_B_Scale_Out_Pct"] == 50.0
    assert result["Model_B_Scale_Out_Level_VAH"] == 110.0
    assert result["Model_B_Runner_Trail_EMA10"] == 101.0
    assert result["Current_VAL"] == 99.0
    assert result["Current_VAH"] == 110.0
    assert result["Current_Profile_Zone"] == "UPPER_VALUE"
    assert result["POC_Rank_Adjustment"] == 1.0

    breadth_gated = test.copy()
    breadth_gated["Breadth_Pass"] = False
    gated_config = ScannerConfig(min_turnover_crore=0.0, require_breadth=True)
    gated_result = classify_with_profiles(
        "KIRLOSENG.NS", breadth_gated, profiles, gated_config, True
    )
    assert gated_result is not None
    assert gated_result["Research_State"] == "NO_MATCH", gated_result
    breadth_gated["Breadth_Pass"] = True
    gated_result = classify_with_profiles(
        "KIRLOSENG.NS", breadth_gated, profiles, gated_config, False
    )
    assert gated_result is not None
    assert gated_result["Research_State"] == "EXPANSION_AFTER_SETUP", gated_result

    spring = test.copy()
    spring.loc[spring.index[-1], "Close"] = 99.25
    spring_profiles = {
        timestamp: ProfileLevels(100.0, 99.5, 110.0, "2026-08-01", 30)
        for timestamp in spring.index
    }
    spring_result = classify_with_profiles(
        "KIRLOSENG.NS", spring, spring_profiles, config, False
    )
    assert spring_result is not None
    assert spring_result["Research_State"] == "SPRING_WATCH_AT_VAL", spring_result
    assert spring_result["Actionability"] == "WATCH_ONLY_VAL_RECLAIM_REQUIRED"
    assert spring_result["POC_Rank_Adjustment"] == 0.0
    assert np.isfinite(spring_result["Stop_Loss_Structural"])

    breakdown = test.copy()
    breakdown.loc[breakdown.index[-1], "Close"] = 97.5
    breakdown_result = classify_with_profiles(
        "KIRLOSENG.NS", breakdown, profiles, config, False
    )
    assert breakdown_result is not None
    assert breakdown_result["Research_State"] == "AUCTION_BREAKDOWN"
    assert math.isnan(breakdown_result["Stop_Loss_Structural"])
    assert math.isnan(breakdown_result["Target_VAH"])
    assert math.isnan(breakdown_result["Risk_Reward_Ratio"])
    assert breakdown_result["Model_B_Status"] == "INVALIDATED_NO_TRADE_PLAN"
    assert breakdown_result["Current_Profile_Zone"] == "BELOW_VAL"
    assert breakdown_result["POC_Rank_Adjustment"] == -2.0

    # Track B has no stock-price EMA20 dependency. A frozen fixed-session watch
    # on the prior bar can become a confirmed, risk-qualified breakout today.
    compression = pd.DataFrame(
        index=pd.date_range("2026-10-01", periods=7, freq="B")
    )
    compression["Open"] = [100.0] * 5 + [100.1, 101.55]
    compression["High"] = [100.8] * 5 + [100.7, 102.10]
    compression["Low"] = [99.7] * 5 + [99.8, 101.50]
    compression["Close"] = [100.2] * 5 + [100.5, 102.00]
    compression["ATR14"] = 2.0
    compression["ATR14_Prior"] = 2.0
    compression["WPR3"] = [-30.0] * 6 + [-5.0]
    compression["Track_B_Daily_Pass"] = [False] * 5 + [True, False]
    compression["Volume_Ratio"] = [0.7] * 6 + [1.5]
    compression["Volume_Ratio_3D"] = 0.8
    compression["NR4"] = False
    compression["TR_ATR_Ratio"] = 0.7
    compression["RS_Strong"] = False
    compression["Eligibility_Pass"] = True
    compression["Volume_Contraction"] = True
    compression_profiles = {
        timestamp: ProfileLevels(
            poc=100.0,
            val=99.0,
            vah=101.0,
            anchor_date="2026-09-10",
            sessions=15,
            anchor_method="FIXED_15_SESSION_CONTINUOUS_OVERLAP",
            bin_width=0.10,
        )
        for timestamp in compression.index
    }
    compression_result = classify_with_profiles(
        "NOEMA20.NS",
        compression,
        {},
        config,
        False,
        compression_profiles,
    )
    assert compression_result is not None
    assert compression_result["Research_State"] == "BREAKOUT_READY_NEXT_OPEN", compression_result
    assert compression_result["Strategy_Track"] == "TRACK_B_COMPRESSION_BREAKOUT"
    assert compression_result["Track_B_Price_EMA20_Required"] is False
    assert compression_result["Compression_Setup_Date"] == compression.index[-2].date().isoformat()
    assert compression_result["Indicative_RR_TP1"] >= config.breakout_min_risk_reward    assert daily_prefilter(compression, config)

    extended = compression.copy()
    extended.loc[extended.index[-1], ["Open", "Low", "High", "Close"]] = [
        101.2,
        101.2,
        104.2,
        104.0,
    ]
    extended_result = classify_with_profiles(
        "EXTENDED.NS", extended, {}, config, False, compression_profiles
    )
    assert extended_result is not None
    assert extended_result["Research_State"] == "BREAKOUT_EXTENDED_WAIT_RETEST"
    assert extended_result["Actionability"] == "WAIT_RETEST_NOT_ACTIONABLE"

    cached_only = compression.copy()
    cached_only["Track_B_Daily_Pass"] = False
    stored_setup = {
        "active": True,
        "setup_date": compression.index[-2].date().isoformat(),
        "poc": 100.0,
        "val": 99.0,
        "vah": 101.0,
        "atr": 2.0,
        "value_area_width_atr": 1.0,
        "profile_anchor_date": "2026-09-10",
        "profile_method": "FIXED_15_SESSION_CONTINUOUS_OVERLAP",
        "profile_sessions": 15,
    }
    cached_result = classify_with_profiles(
        "CACHED.NS",
        cached_only,
        {},
        config,
        False,
        compression_profiles,
        stored_setup,
    )
    assert cached_result is not None
    assert cached_result["Research_State"] == "BREAKOUT_READY_NEXT_OPEN"
    state_payload: dict[str, object] = {"schema_version": 1, "symbols": {}}
    update_lifecycle_state(state_payload, "EXTENDED.NS", extended_result)
    with tempfile.TemporaryDirectory() as temp_directory:
        test_state_path = Path(temp_directory) / "state.json"
        write_lifecycle_state(state_payload, test_state_path)
        reloaded_state = load_lifecycle_state(test_state_path)
        assert "EXTENDED.NS" in reloaded_state["symbols"]
        assert reloaded_state["symbols"]["EXTENDED.NS"]["active"] is True

    regime, benchmark_close, benchmark_ema = evaluate_benchmark_regime(base, 20)
    assert regime == "RISK_ON", (regime, benchmark_close, benchmark_ema)
    print(
        "Self-test passed: NSE universe parsing, indicators, confirmed fractal "
        "anchoring, continuous-overlap volume conservation, body-weighted value "
        "area, profile reclaim ranking, Model B references, Track B's no-price-"
        "EMA20 compression/breakout flow, extension protection, persistent "
        "frozen state, spring-watch, breakdown blanking, market regime, and "
        "lifecycle states."
    )


def main() -> int:
    args = parse_args()
    if args.self_test:
        run_self_test()
        return 0

    config = ScannerConfig(
        benchmark=args.benchmark,
        batch_size=max(1, args.batch_size),
        intraday_batch_size=max(1, args.intraday_batch_size),
        retries=max(1, args.retries),
        retry_pause_seconds=max(0.0, args.retry_pause),
        min_turnover_crore=max(0.0, args.min_turnover_crore),
        min_price=max(0.0, args.min_price),
        breadth_min_turnover_crore=max(0.0, args.breadth_min_turnover_crore),
        breadth_threshold_pct=min(100.0, max(0.0, args.breadth_threshold)),
        require_breadth=bool(args.require_breadth),
    )
    state_path = args.state_file or (
        Path(__file__).resolve().parent / "poc_lifecycle_state.json"
    )
    lifecycle_state = load_lifecycle_state(state_path)
    if args.symbols:
        symbols = unique_in_order(yahoo_symbol(x) for x in args.symbols.split(","))
        universe_label = "CUSTOM_SYMBOLS"
    elif args.symbols_file:
        symbols = load_symbols_file(args.symbols_file)
        universe_label = "CUSTOM_FILE"
    elif args.universe == "nifty500":
        print("Downloading current Nifty 500 universe...", file=sys.stderr)
        symbols = fetch_nifty500_symbols()
        universe_label = "NIFTY500"
    else:
        allowed_series = parse_nse_series(args.nse_series)
        series_label = "ALL" if allowed_series is None else "+".join(allowed_series)
        print(
            f"Downloading current NSE equity universe (series={series_label})...",
            file=sys.stderr,
        )
        symbols = fetch_nse_equity_symbols(allowed_series)
        universe_label = f"NSE_{series_label}"
    if args.max_symbols:
        symbols = symbols[: max(1, args.max_symbols)]
        universe_label = f"{universe_label}_FIRST_{len(symbols)}"
    if not symbols:
        raise SystemExit("No symbols to scan")

    yf = require_yfinance()
    print(
        f"Scanning {len(symbols)} symbols | universe={universe_label} | "
        f"benchmark={config.benchmark} | "
        f"version={VERSION}",
        file=sys.stderr,
    )
    stock_data, benchmark, daily_errors = download_daily_data(
        yf,
        symbols,
        config,
        include_partial=args.include_partial_day,
        pause_seconds=max(0.0, args.pause),
    )
    market_regime, benchmark_close, benchmark_ema20 = evaluate_benchmark_regime(
        benchmark, config.benchmark_regime_ema_length
    )
    if market_regime == "RISK_OFF":
        print(
            "ALERT: Broad market benchmark below 20 EMA. "
            "All long-side breakdown risks are elevated.",
            file=sys.stderr,
        )
    elif market_regime == "UNKNOWN":
        print(
            "WARNING: Benchmark 20-EMA regime could not be evaluated.",
            file=sys.stderr,
        )

    indicators: dict[str, pd.DataFrame] = {}
    for symbol, frame in stock_data.items():
        enriched = add_daily_indicators(frame, benchmark, config)
        if len(enriched) >= 30:
            indicators[symbol] = enriched
        else:
            daily_errors[symbol] = f"Only {len(enriched)} aligned daily rows"

    breadth = add_composite_breadth(indicators, config)
    valid_breadth = breadth.dropna(subset=["Breadth_Pct_Above_SMA50"])
    if valid_breadth.empty:
        latest_breadth_pct = math.nan
        latest_breadth_count = 0
        latest_breadth_label = "UNKNOWN"
        print(
            "WARNING: Composite breadth could not be calculated.",
            file=sys.stderr,
        )
    else:
        latest_breadth = valid_breadth.iloc[-1]
        latest_breadth_pct = float(latest_breadth["Breadth_Pct_Above_SMA50"])
        latest_breadth_count = int(latest_breadth["Breadth_Eligible_Count"])
        if latest_breadth_count < config.breadth_min_constituents:
            latest_breadth_label = "INSUFFICIENT_COVERAGE"
        elif bool(latest_breadth["Breadth_Pass"]):
            latest_breadth_label = "BROAD"
        else:
            latest_breadth_label = "NARROW"
        print(
            f"Composite breadth: {latest_breadth_pct:.1f}% above SMA50 | "
            f"eligible={latest_breadth_count} | {latest_breadth_label}",
            file=sys.stderr,
        )
    if config.require_breadth:
        print(
            f"Breadth gate ACTIVE: require >= {config.breadth_threshold_pct:.1f}% "
            f"and >= {config.breadth_min_constituents} eligible stocks.",
            file=sys.stderr,
        )

    candidates = [
        symbol for symbol, frame in indicators.items() if daily_prefilter(frame, config)
    ]
    persisted_candidates = active_state_symbols(lifecycle_state).intersection(indicators)
    candidates = unique_in_order([*candidates, *sorted(persisted_candidates)])
    print(
        f"Daily prefilter/state cache: {len(candidates)} of {len(indicators)} "
        "symbols need profile evaluation.",
        file=sys.stderr,
    )

    intraday_data, intraday_errors = download_intraday_data(
        yf,
        candidates,
        config,
        pause_seconds=max(0.0, args.pause),
    )

    rows: list[dict] = []
    for number, symbol in enumerate(candidates, start=1):
        print(
            f"Profile evaluation {number}/{len(candidates)}: {display_symbol(symbol)}",
            file=sys.stderr,
        )
        daily = indicators[symbol]
        track_a_dates = daily.tail(config.lifecycle_sessions + 1).index
        compression_profile_lookback = (
            config.compression_width_lookback_sessions
            + config.compression_watch_expiry_sessions
            + 2
        )
        compression_dates = daily.tail(compression_profile_lookback).index
        try:
            if symbol in intraday_errors:
                raise RuntimeError(intraday_errors[symbol])
            intraday = intraday_data[symbol]
            profiles, available = build_profile_map(
                intraday, daily, track_a_dates, config
            )
            compression_profiles, compression_available = build_fixed_profile_map(
                intraday, compression_dates, config
            )
            if (
                available < config.poc_sessions
                and compression_available < config.compression_profile_sessions
            ):
                raise RuntimeError(
                    "Insufficient prior intraday sessions for both tracks: "
                    f"Track A={available}/{config.poc_sessions}, "
                    f"Track B={compression_available}/{config.compression_profile_sessions}"
                )
            row = classify_with_profiles(
                symbol,
                daily,
                profiles,
                config,
                include_nonmatch=args.all_results,
                compression_profiles=compression_profiles,
                stored_track_b=(
                    lifecycle_state.get("symbols", {}).get(symbol)
                    if isinstance(lifecycle_state.get("symbols"), dict)
                    else None
                ),
            )
            if row is not None:
                rows.append(row)
                update_lifecycle_state(lifecycle_state, symbol, row)
        except Exception as exc:  # noqa: BLE001 - isolate a failed symbol
            if args.all_results:
                rows.append(
                    diagnostic_row(symbol, daily, f"POC_ERROR: {exc}", config)
                )
            print(f"  skipped: {exc}", file=sys.stderr)

    if not args.no_state_update:
        try:
            write_lifecycle_state(lifecycle_state, state_path)
        except (OSError, ValueError) as exc:
            print(
                f"WARNING: Could not update Track B state file {state_path}: {exc}",
                file=sys.stderr,
            )

    if args.all_results:
        evaluated = set(candidates)
        for symbol, daily in indicators.items():
            if symbol not in evaluated:
                row = classify_with_profiles(symbol, daily, {}, config, True)
                if row is not None:
                    row["Data_Quality"] = "DAILY_PREFILTER_NOT_MET"
                    rows.append(row)
        for symbol, reason in daily_errors.items():
            rows.append(diagnostic_row(symbol, pd.DataFrame(), reason, config))

    columns = [
        "Symbol",
        "Yahoo_Symbol",
        "Universe",
        "As_Of",
        "Research_State",
        "Strategy_Track",
        "Actionability",
        "Reference_Date",
        "Reference_Type",
        "Setup_Date",
        "Sessions_Since_Setup",
        "Close",
        "Daily_Return_Pct",
        "RS_Ratio",
        "RS_EMA20",
        "RS_Excess_20D_Pct",
        "RS_Strong",
        "Williams_R_3",
        "ATR14",
        "SMA50",
        "EMA10",
        "Volume_SMA20",
        "Volume_Contraction",
        "True_Range",
        "Track_B_TR_ATR_Ratio",
        "Track_B_NR4",
        "Track_B_Volume_Ratio",
        "Track_B_Volume_Ratio_3D",
        "Track_B_Daily_Pass",
        "Track_B_Price_EMA20_Required",
        "Setup_POC",
        "VAL",
        "VAH",
        "Current_Anchored_POC",
        "Current_VAL",
        "Current_VAH",
        "Current_Profile_Zone",
        "Current_POC_State",
        "Current_POC_Distance_Pct",
        "Current_POC_Distance_ATR",
        "Current_POC_Reclaim",
        "Current_POC_Lost",
        "Current_Profile_Tolerance",
        "POC_Rank_Adjustment",
        "Extension_From_Setup_POC_ATR",
        "VAL_Undercut_ATR",
        "Stop_Loss_Structural",
        "Target_VAH",
        "Risk_Reward_Ratio",
        "Profile_Anchor_Date",
        "Profile_Anchor_Method",
        "Profile_Sessions",
        "Current_Profile_Bin_Width",
        "Profile_Method",
        "Compression_POC",
        "Compression_VAL",
        "Compression_VAH",
        "Compression_POC_Distance_ATR",
        "Compression_Value_Area_Width_ATR",
        "Compression_Width_Threshold_ATR",
        "Compression_Profile_Sessions",
        "Compression_Profile_Method",
        "Compression_Setup_Date",
        "Compression_Setup_ATR",
        "Compression_Setup_Value_Area_Width_ATR",
        "Compression_Age_Sessions",
        "Breakout_Trigger",
        "Breakout_Extension_ATR",
        "Breakout_Close_Location",
        "Breakout_Body_Ratio",
        "Breakout_Volume_Pass",
        "Indicative_Next_Open_Stop",
        "Indicative_TP1",
        "Indicative_TP2",
        "Indicative_RR_TP1",
        "Track_B_Entry_Rule",
        "Median_Turnover_Cr",
        "Breadth_Pct_Above_SMA50",
        "Breadth_Eligible_Count",
        "Breadth_Pass",
        "Breadth_Gate_Required",
        "Model_B_Status",
        "Model_B_Reference_Entry",
        "Model_B_Scale_Out_Pct",
        "Model_B_Scale_Out_Level_VAH",
        "Model_B_Breakeven_After_VAH",
        "Model_B_Runner_Trail_EMA10",
        "Model_B_Activation_Rule",
        "Model_B_Runner_Exit_Rule",
        "Market_Regime",
        "Benchmark_Close",
        "Benchmark_EMA20",
        "Data_Quality",
        "Hypothesis_ID",
        "Rule_Version",
        "State_Rank_Pct",
    ]
    output = pd.DataFrame(rows, columns=columns)
    output["Universe"] = universe_label
    output["Market_Regime"] = market_regime
    output["Benchmark_Close"] = benchmark_close
    output["Benchmark_EMA20"] = benchmark_ema20
    if not output.empty:
        output = add_state_percentile_ranking(output)
        output["_State_Order"] = output["Research_State"].map(STATE_ORDER).fillna(99)
        output = output.sort_values(
            ["_State_Order", "State_Rank_Pct", "RS_Excess_20D_Pct"],
            ascending=[True, False, False],
        ).drop(columns="_State_Order")
    output = round_output(output)

    default_prefix = (
        "nifty500" if universe_label.startswith("NIFTY500") else "nse_equity"
    )
    output_path = args.output or (
        Path(__file__).resolve().parent
        / f"{default_prefix}_rs_wpr_poc_{datetime.now(IST):%Y%m%d}.csv"
    )
    output_path = write_csv_with_fallback(output, output_path)

    matched = int(output["Research_State"].isin(ACTIVE_STATES).sum()) if not output.empty else 0
    watches = int(output["Research_State"].isin(WATCH_STATES).sum()) if not output.empty else 0
    spring_watches = (
        int((output["Research_State"] == "SPRING_WATCH_AT_VAL").sum())
        if not output.empty
        else 0
    )
    track_b_watches = (
        int(
            output["Research_State"]
            .isin(
                (
                    "POC_COMPRESSION_WATCH",
                    "BREAKOUT_EXTENDED_WAIT_RETEST",
                    "BREAKOUT_CONFIRMED_RR_FAIL",
                )
            )
            .sum()
        )
        if not output.empty
        else 0
    )
    breakdowns = (
        int((output["Research_State"] == "AUCTION_BREAKDOWN").sum())
        if not output.empty
        else 0
    )
    print(f"\nSaved: {output_path.resolve()}")
    print(f"Lifecycle matches: {matched}")
    print(f"Track A spring watches (VAL reclaim required): {spring_watches}")
    print(f"Track B compression/retest watches: {track_b_watches}")
    print(f"Auction breakdowns: {breakdowns}")
    print(
        f"Market regime: {market_regime} | benchmark close={benchmark_close:.2f} | "
        f"EMA20={benchmark_ema20:.2f}"
    )
    if np.isfinite(latest_breadth_pct):
        print(
            f"Composite breadth: {latest_breadth_pct:.1f}% above SMA50 | "
            f"eligible={latest_breadth_count} | {latest_breadth_label} | "
            f"gate={'ON' if config.require_breadth else 'OFF'}"
        )
    else:
        print(
            f"Composite breadth: UNKNOWN | gate={'ON' if config.require_breadth else 'OFF'}"
        )
    if daily_errors:
        print(f"Daily-data warnings: {len(daily_errors)}", file=sys.stderr)
    if intraday_errors:
        print(f"Intraday-data warnings: {len(intraday_errors)}", file=sys.stderr)
    if matched:
        preview_columns = [
            "Symbol",
            "Research_State",
            "Setup_Date",
            "Close",
            "Williams_R_3",
            "Current_Profile_Zone",
            "Current_POC_State",
            "POC_Rank_Adjustment",
            "Extension_From_Setup_POC_ATR",
        ]
        print(output.loc[output["Research_State"].isin(ACTIVE_STATES), preview_columns].to_string(index=False))
    else:
        print("No stocks matched the frozen research states on the latest completed bar.")
    if spring_watches:
        watch_columns = [
            "Symbol",
            "Research_State",
            "Reference_Type",
            "Setup_Date",
            "Close",
            "VAL",
            "Current_Profile_Zone",
            "Current_POC_State",
            "VAL_Undercut_ATR",
        ]
        print("\nWatch-only candidates; a completed-bar VAL reclaim is required:")
        print(
            output.loc[
                output["Research_State"].eq("SPRING_WATCH_AT_VAL"),
                watch_columns,
            ]
            .to_string(index=False)
        )
    if track_b_watches:
        track_b_watch_states = (
            "POC_COMPRESSION_WATCH",
            "BREAKOUT_EXTENDED_WAIT_RETEST",
            "BREAKOUT_CONFIRMED_RR_FAIL",
        )
        watch_columns = [
            "Symbol",
            "Research_State",
            "Actionability",
            "Compression_Setup_Date",
            "Close",
            "Setup_POC",
            "VAL",
            "VAH",
            "Breakout_Trigger",
            "Breakout_Extension_ATR",
            "Indicative_RR_TP1",
        ]
        print("\nTrack B compression/retest observations:")
        print(
            output.loc[
                output["Research_State"].isin(track_b_watch_states),
                watch_columns,
            ].to_string(index=False)
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:  # noqa: BLE001 - present a concise CLI failure
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
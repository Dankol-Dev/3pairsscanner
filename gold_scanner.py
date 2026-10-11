"""
================================================================================
 PROFESSIONAL FOREX DAY-TRADING SIGNAL SCANNER (Multi-Pair)
================================================================================
Scans EURUSD, AUDUSD, and GBPUSD using a confluence-based methodology and
grades setups as A+ / A / B / NO TRADE based on how many professional
criteria line up simultaneously. Designed for intraday/day-trading on the
M15 entry timeframe with H1 trend bias.

STRATEGY LOGIC MAPPED FROM REAL PRO METHODOLOGY:
  1. TREND        -> EMA20/EMA50/EMA200 stack (trade WITH the higher timeframe trend)
  2. MOMENTUM     -> RSI(14) in the "continuation zone" + MACD histogram expanding
  3. KEY LEVEL    -> Price reacting at a Fibonacci retracement OR swing pivot S/R
  4. PRICE ACTION -> Confirmation candle (rejection wick / strong body close)
  5. VOLUME       -> Volume expansion on the confirmation candle (not dead volume)
  6. SESSION      -> London/New York overlap = highest-quality FX liquidity window
  7. RISK MODEL   -> Fixed fractional risk, ATR-based stop, fixed R-multiple targets
                    (applied as a post-hoc NET R:R filter, not a scored criterion)

A setup scores a maximum of 6 points (criteria 1-6); the risk model is a
separate gate. A setup only becomes "A+" when nearly ALL of the scored
criteria agree.

REALITY CHECK (read this before running):
  Position sizing only works as designed on capital that clears the
  broker's minimum lot size at real risk percentages (see ACCOUNT_SIZE
  below). Past backtest performance is not a guarantee of future results.
================================================================================
"""

import sys
import os
import time
import csv
import math
import importlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# yfinance / websockets compatibility shim
# --------------------------------------------------------------------------
# yfinance imports `websockets.asyncio`, which was removed in websockets
# 14.0. If a newer websockets is installed, the import raises
# "No module named 'websockets.asyncio'" and every yfinance call fails —
# which silently disables the DXY gate, the TIPS gate, and the Yahoo data
# fallback. This shim installs a minimal `websockets.asyncio` alias that
# delegates to the legacy `websockets.legacy` implementation when present,
# so yfinance works regardless of the installed websockets version.
def _patch_websockets_for_yfinance():
    try:
        import websockets  # noqa: F401
    except ImportError:
        return  # websockets not installed — yfinance will fail on its own
    try:
        importlib.import_module("websockets.asyncio")
        return  # already present (websockets < 14)
    except ImportError:
        pass
    # Newer websockets: alias asyncio -> legacy so yfinance's import works.
    try:
        legacy_websockets = importlib.import_module("websockets.legacy")
        sys.modules["websockets.asyncio"] = legacy_websockets
    except ImportError:
        # Even legacy is gone (very new websockets) — install a stub that
        # raises a clear error only when actually used, so the module loads.
        import types

        _stub = types.ModuleType("websockets.asyncio")
        _stub.connect = None  # yfinance checks this attribute
        sys.modules["websockets.asyncio"] = _stub


def _import_yfinance():
    """Imports yfinance after applying the websockets compatibility shim.
    Used by every yfinance call site so the shim is applied consistently."""
    _patch_websockets_for_yfinance()
    return importlib.import_module("yfinance")

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------
DATA_SOURCE = "mt5"       # "mt5" (your broker's live feed) | "yfinance" | "auto"

# --- TRADED PAIRS -----------------------------------------------------------
# Each pair has MT5 symbol candidates (broker suffixes vary), a Yahoo Finance
# ticker, a pip size (0.0001 for 4-decimal pairs, 0.01 for JPY pairs), and
# a typical spread in pips. The scanner iterates over ALL pairs each cycle.
TRADED_PAIRS = [
    {
        "name": "EURUSD",
        "mt5_symbols": ["EURUSD", "EURUSD.m", "EURUSDm", "EURUSD.", "EURUSD.i"],
        "yf_symbol": "EURUSD=X",
        "pip_size": 0.0001,
        "typical_spread_pips": 0.8,
        "contract_size": 100000,
        "pip_value_usd": 10.0,
    },
    {
        "name": "AUDUSD",
        "mt5_symbols": ["AUDUSD", "AUDUSD.m", "AUDUSDm", "AUDUSD.", "AUDUSD.i"],
        "yf_symbol": "AUDUSD=X",
        "pip_size": 0.0001,
        "typical_spread_pips": 1.0,
        "contract_size": 100000,
        "pip_value_usd": 10.0,
    },
    {
        "name": "GBPUSD",
        "mt5_symbols": ["GBPUSD", "GBPUSD.m", "GBPUSDm", "GBPUSD.", "GBPUSD.i"],
        "yf_symbol": "GBPUSD=X",
        "pip_size": 0.0001,
        "typical_spread_pips": 1.2,
        "contract_size": 100000,
        "pip_value_usd": 10.0,
    },
]
_PAIR_BY_NAME = {p["name"]: p for p in TRADED_PAIRS}

# Legacy single-pair aliases (used by backtest/sweep/walkforward code paths
# that haven't been multi-pair-ized yet — they default to EURUSD).
MT5_SYMBOL_CANDIDATES = TRADED_PAIRS[0]["mt5_symbols"]
YF_SYMBOL = TRADED_PAIRS[0]["yf_symbol"]

# --- MULTI-TIMEFRAME SETUP (DAY-TRADING OPTIMIZED) -------------------------
#   HTF = 15m -> fast trend bias for day trading (filters intraday noise
#                but reacts quickly enough for multiple setups per session)
#   LTF = 5m  -> precise entry timing with tight stops for intraday trades
# Day-trading uses faster timeframes than swing trading. The confluence
# engine is timeframe-agnostic — these just control how much noise is
# filtered vs. how fast signals fire.
HTF_INTERVAL = "15m"
LTF_INTERVAL = "5m"
HTF_BARS = 300
LTF_BARS = 500

ACCOUNT_SIZE = 10000.0    # set this to YOUR actual account size. At real forex
                          # volatility (stops derived from live data ranged
                          # ~$0.006-0.027 in price terms), the bare minimum for a 1%
                          # risk target to clear the broker's 0.01 min lot even
                          # in worst-case volatility is ~$267 — below that,
                          # "1% risk" quietly becomes "risk the whole account."
                          # $10k gives comfortable headroom (~0.04-0.08 lots)
                          # rather than sitting right at the floor.
                          # See calculate_position_size().
RISK_PER_TRADE_PCT = 1.0  # professional standard: 0.5-2% risk per trade
# Minimum separation between EMA20 and EMA50, as a fraction of price,
# for the trend stack to count as "aligned". When the two fast EMAs are
# nearly equal the market is effectively flat, not trending — a stack that
# passes by a hair's breadth shouldn't score the trend point.
FLAT_EMA_THRESHOLD = 0.001  # 0.1% of price

MIN_RR_FOR_SIGNAL = 1.2   # NET (post-cost) TP1 R:R minimum. Must be set below
                          # the nominal TP1 ratio (1.5, see build_trade_plan) —
                          # spread+slippage erode the net ratio toward but
                          # never above the nominal one, so MIN_RR_FOR_SIGNAL
                          # >= the nominal ratio would reject every trade.
MIN_HTF_GRADE = "A"       # HTF bias must be at least this grade to even
                          # bother checking the LTF ("A+" > "A" > "B")
MIN_LTF_CONFIRMATIONS = 2 # out of 3 LTF confirmation checks required

# --- SCALPING ENGINE CONFIG ------------------------------------------
# Scalping runs the SAME confluence engine on much faster
# timeframes (5m bias / 1m entries) with tighter stops and
# quicker scale-outs. Costs matter far more at this horizon,
# so the scalp profile adds two filters the day engine doesn't
# need: a spread-viability floor (the 1m ATR must be several
# times the spread or transaction costs dominate the noise) and
# an anti-overtrading cap (a fixed number of signals per
# rolling session window — churning out marginal scalps is how
# accounts die).
SCALP_HTF_INTERVAL = "5m"     # scalp bias timeframe
SCALP_LTF_INTERVAL = "1m"     # scalp entry-timing timeframe
SCALP_HTF_BARS = 300
SCALP_LTF_BARS = 500
SCALP_ATR_STOP_MULT = 1.0     # tighter than day trading (1.5x)
SCALP_TP1_RR = 1.5            # quick scale-outs; blended with
SCALP_TP2_RR = 2.0            # the 1/3-1/3-1/3 ladder this
SCALP_TP3_RR = 3.0            # keeps the runner working
SCALP_MIN_RR = 0.7            # NET (post-cost) TP1 minimum.
                                  # Must sit below the nominal TP1
                                  # ratio (1.5) — spread+slippage
                                  # erode the net ratio. A scalp
                                  # can still be +EV at 0.7R net
                                  # IF its win rate clears
                                  # 1/(1+0.7) = 59%.
SCALP_MIN_HTF_GRADE = "A"
SCALP_MIN_LTF_CONFIRMATIONS = 3  # ALL three LTF checks must
                                      # confirm — scalp entries
                                      # are timed, not anticipated
SCALP_MAX_HOLD_BARS = 60      # on 1m = 1 hour max hold
SCALP_MIN_ATR_TO_SPREAD = 3.0   # 1m ATR (pips) must be >= this
                                     # multiple of the typical
                                     # spread (pips), else the
                                     # noise floor is below the
                                     # cost floor — untradeable
SCALP_MAX_SIGNALS_PER_SESSION = 6   # anti-overtrading cap
SCALP_SIGNAL_WINDOW_HOURS = 8   # rolling window for the cap
                                  # (approximates one London/NY
                                  # session)

# --- COST MODEL (forex: spread + slippage in PIPS, converted to price) -------
# Spread is measured in pips per pair (see TRADED_PAIRS). Slippage is in pips.
# These are converted to price terms at runtime using the pair's pip_size.
SLIPPAGE_PIPS = 0.5        # assumed adverse slippage on entry + stop fill

# Legacy aliases (price-term equivalents for EURUSD, used by backtest code
# paths that haven't been multi-pair-ized yet).
SPREAD_USD = 0.00008       # ~0.8 pips * 0.0001 pip_size for EURUSD
SLIPPAGE_USD = 0.00005     # 0.5 pips * 0.0001

# --- POSITION SIZING --------------------------------------------------------
# FX standard lot = 100,000 units of the base currency. Contract size is
# per-pair in TRADED_PAIRS. These are legacy defaults for the backtester.
CONTRACT_SIZE_OZ = 100000  # FX standard lot (renamed concept; legacy name kept
                            # so the backtester still works)

# --- RISK CIRCUIT BREAKER --------------------------------------------------
MAX_DAILY_LOSS_PCT = 3.0  # stop signaling new trades once today's realized
                          # loss (from the trade log) reaches this % of account

# --- LOGGING -----------------------------------------------------------------
SIGNAL_LOG_PATH = "signal_log.csv"     # every signal the scanner produces
TRADE_LOG_PATH = "trade_outcomes.csv"  # closed trade outcomes for the circuit
                                        # breaker (append rows here manually or
                                        # via your own execution/monitoring code)

# --- SUPABASE DASHBOARD SYNC ------------------------------------------------
# Pushes every signal to the Supabase `signals` table so the web dashboard
# can display results in real time. Reads URL + anon key from environment
# variables (VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY, matching the .env
# the dashboard uses). Leave SUPABASE_URL blank to disable the push (the
# scanner still works, just without the dashboard).
SUPABASE_URL = os.environ.get("SUPABASE_URL") or os.environ.get("VITE_SUPABASE_URL") or ""
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("VITE_SUPABASE_ANON_KEY") or ""

# --- LIVE LOOP / ALERTING ---------------------------------------------------
POLL_SECONDS = 900         # 15 min — matches LTF_INTERVAL; re-check on each
                          # new candle rather than continuously hammering MT5
REPEAT_INTERVAL_SECONDS = 300  # 5 min — day-trading needs faster re-scans
                                # than swing trading
POSITION_POLL_SECONDS = 60      # how often to re-check MT5 for closed
                                # positions while waiting after a signal
TELEGRAM_BOT_TOKEN = ""    # leave blank to disable Telegram alerts
TELEGRAM_CHAT_ID = ""

# --- NEWS BLACKOUT -----------------------------------------------------------
# NOT a live economic calendar (no reliable free API with guaranteed uptime,
# and it can't be tested from this offline sandbox) — this is a manual list
# YOU maintain from an economic calendar (e.g. ForexFactory) for the week
# ahead. Format: (UTC datetime string, minutes_before, minutes_after, label)
NEWS_BLACKOUT_WINDOWS = [
    # ("2026-07-16 12:30", 15, 45, "US CPI"),
    # ("2026-07-17 18:00", 15, 45, "FOMC Statement"),
]

# --- LADDERED EXIT SIZING (matches the live TP1/TP2/TP3 scale-out plan) -----
# Each target takes a fixed fraction of the position; the remainder runs.
# The backtest now simulates these partials so it measures the SAME strategy
# the live signal advertises, not a single all-in/all-out variant.
TP1_FRACTION = 1/3
TP2_FRACTION = 1/3
TP3_FRACTION = 1/3   # remainder = 1 - TP1 - TP2 runs to TP3

# --- TRAILING STOP for the TP3 runner ---------------------------------------
# After TP1 fills, the stop moves to breakeven+cost (unchanged). After TP2
# fills, the runner trails by the selected method instead of sitting at
# breakeven forever — this is what lets winners run instead of giving back
# the whole move on a reversal.
#   "atr"    -> trail at entry +/- TRAIL_ATR_MULT * ATR (volatility-aware)
#   "ema20"  -> trail behind the LTF EMA20 (lets a strong trend stretch)
#   "none"   -> keep breakeven+cost (legacy behavior)
TRAIL_METHOD = "atr"
TRAIL_ATR_MULT = 2.0  # only used when TRAIL_METHOD == "atr"

# --- VOLATILITY-TARGETED POSITION SIZING ------------------------------------
# Instead of a flat 1% on every trade, scale risk by current volatility
# relative to its own recent norm. In low-vol (tight conditions, cheap
# option premium, clean stops) risk up toward VOL_RISK_MAX; in blowoff-vol
# (wide stops, noisy fills) risk down toward VOL_RISK_MIN. The base
# RISK_PER_TRADE_PCT above is the midpoint used when vol is exactly at its
# rolling median. Set VOL_TARGETED_RISK = False to disable and use the flat
# RISK_PER_TRADE_PCT for every trade.
VOL_TARGETED_RISK = True
VOL_RISK_MIN = 0.5     # % of account risked when vol is at the 95th pct (hot)
VOL_RISK_MAX = 1.5     # % of account risked when vol is at the 5th pct (calm)
VOL_LOOKBACK = 50      # bars of ATR used to establish the "normal" vol baseline

# --- DXY (US DOLLAR INDEX) CORRELATION GATE ---------------------------------
# The dollar is the primary driver of USD-quoted FX pairs. A EURUSD LONG
# while DXY is breaking structurally higher is a low-quality signal — the
# single biggest missing confluence. This pulls DXY (via yfinance,
# broker-independent) and gates against it. Set ENABLE_DXY_GATE = False to
# skip (e.g. no internet).
ENABLE_DXY_GATE = True
DXY_YF_SYMBOL = "DX-Y.NYB"        # US Dollar Index futures, Yahoo Finance
DXY_TREND_BARS = 20               # bars used to define DXY "breaking up/down"
DXY_BREAK_PCT = 0.003             # 0.3% move over DXY_TREND_BARS = a "break"
# For USD-quoted FX pairs (EURUSD, AUDUSD, GBPUSD), DXY breaking UP = USD
# strengthening = BEARISH for these pairs. The gate is per-pair aware:
# a LONG on EURUSD while DXY breaks up is blocked; a SHORT is supported.

# --- TIPS REAL-YIELD CORRELATION GATE --------------------------------------
# Not relevant for FX day trading. Disabled by default.
ENABLE_TIPS_GATE = False          # TIPS real-yield gate is gold-specific;
                                   # not relevant for FX day trading. Disabled.
TIPS_YF_SYMBOL = "TIP"
TIPS_TREND_BARS = 20
TIPS_BREAK_PCT = 0.004

# --- COT (COMMITMENT OF TRADERS) POSITIONING OVERLAY ------------------------
# NOT a live feed (CFTC publishes Friday data on Monday; no free reliable
# programmatic API) — this is a manual snapshot YOU paste in from the latest
# CFTC report. When populated, a signal AGAINST the institutional net
# position gets flagged (not blocked) as "against positioning" in the
# checklist; a signal WITH it gets a bonus confluence point. Leave empty to
# disable.
# Format: {"date": "YYYY-MM-DD", "net_noncomm_long_oz": int,
#          "net_noncomm_short_oz": int}
#   net_long > net_short  -> institutions are net LONG (favor LONGS)
#   net_short > net_long   -> institutions are net SHORT (favor SHORTS)
COT_SNAPSHOT = {}  # COT overlay disabled for FX day trading

# --- AUTO-EXECUTE VIA MT5 ----------------------------------------------------
# When enabled, a CONFIRMED signal is sent to the broker as a real market
# order with the computed lot size, SL, and TP1 (TP2/TP3 are managed
# manually or by a separate EA — the MT5 Python API sends one order at a
# time and partials are not natively supported in a single call). The
# circuit breaker becomes REAL with this on: closed-trade P&L is read back
# from MT5 position history and written to TRADE_LOG_PATH automatically.
# DANGER: this places real orders with real money. Leave False until you
# have validated the scanner's signals against a demo account.
AUTO_EXECUTE = False
AUTO_EXECUTE_MAGIC = 20260721   # MT5 magic number to tag scanner orders
AUTO_EXECUTE_DEVIATION = 20     # max slippage in points on the market order

# --- CORRELATED-EXPOSURE CAP ------------------------------------------------
# Block a new signal if there's already an open position in a
# correlated instrument (e.g. a EURUSD long while already long GBPUSD —
# both are effectively the same dollar-short bet). Correlation is checked
# against OPEN MT5 positions (via magic number) so this only does anything
# when AUTO_EXECUTE is on and the scanner is actually managing positions.
# Each entry is an MT5 symbol candidate list plus the direction that
# DUPLICATES a EURUSD long.
# For FX, correlated exposure groups are by currency bloc: long EURUSD +
# long GBPUSD = duplicate EUR/GBP-long exposure (both are dollar-short bets).
CORRELATED_EXPOSURE_GROUPS = [
    {"name": "EUR-GBP bloc", "symbols": ["EURUSD", "GBPUSD"],
     "same_side_as_eurusd_long": "LONG"},  # long both = same dollar-short bet
]

# --- ADX TREND STRENGTH FILTER ----------------------------------------------
# ADX(14) measures trend strength regardless of direction. Below 20 = range,
# 25+ = strong trend. A stack without ADX confirmation is a weak/choppy trend.
ENABLE_ADX_FILTER = True
ADX_PERIOD = 14
ADX_MIN_TREND = 25.0
ADX_RANGE_THRESHOLD = 20.0

# --- ORDER BLOCK / FAIR VALUE GAP CONFLUENCE --------------------------------
# Institutional footprints: order blocks (last opposing candle before a strong
# move) and fair value gaps (imbalances price tends to revisit).
ENABLE_OB_FVG = True
OB_LOOKBACK = 10
OB_MIN_BODY_RATIO = 0.6
FVG_MIN_GAP_ATR = 0.25

# --- AUTOMATED ECONOMIC CALENDAR --------------------------------------------
# Pulls high-impact USD events from a free calendar API so you don't manually
# populate NEWS_BLACKOUT_WINDOWS every week. Falls back to the manual list.
ENABLE_AUTO_NEWS = True
NEWS_BLACKOUT_MINUTES_BEFORE = 30
NEWS_BLACKOUT_MINUTES_AFTER = 30
NEWS_API_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# --- LIVE SPREAD MONITORING -------------------------------------------------
# When MT5 is available, reads the actual current spread. Rejects signals
# when spread exceeds MAX_SPREAD_USD (low liquidity or imminent news).
ENABLE_LIVE_SPREAD = True
MAX_SPREAD_PIPS = 3.0             # reject signals when spread exceeds this (pips)
MAX_SPREAD_USD = 0.0003           # legacy alias (3 pips * 0.0001 for EURUSD)

# --- MAX CONCURRENT POSITIONS -----------------------------------------------
MAX_CONCURRENT_POSITIONS = 3

# --- WEEKLY LOSS CIRCUIT BREAKER --------------------------------------------
MAX_WEEKLY_LOSS_PCT = 6.0

# --- MAXIMUM DRAWDOWN CIRCUIT BREAKER ---------------------------------------
# Unlike the daily/weekly loss limits (which read realized closed-trade P&L
# from the trade log), this breaker tracks the EQUITY CURVE implied by the
# same closed-trade P&L — i.e. it measures peak-to-trough drawdown, not just
# today's losses. A strategy can have positive daily P&L and still be down
# 20% from its peak; this stops compounding that damage. Reads the same
# TRADE_LOG_PATH, so it's real (not theoretical) when AUTO_EXECUTE is on, and
# reflects manually-punched outcomes otherwise.
MAX_DRAWDOWN_PCT = 15.0   # stop signaling once equity drops this % from peak

# --- VARIABLE SLIPPAGE MODEL ------------------------------------------------
# Slippage scales with volatility — a stop hit in a fast market slips more.
ENABLE_VARIABLE_SLIPPAGE = True
SLIPPAGE_BASE_PIPS = 0.5
SLIPPAGE_MAX_PIPS = 2.0
SLIPPAGE_BASE_USD = 0.00005      # legacy alias (0.5 pips * 0.0001)
SLIPPAGE_MAX_USD = 0.0002        # legacy alias (2.0 pips * 0.0001)

# --- SESSION-AWARE STRATEGY FILTER ------------------------------------------
# Blocks trend-following signals during low-quality sessions (Asian/closed).
# Options: "london_ny", "london", "overlap", "any"
ENABLE_SESSION_FILTER = True
# Day-trading: accept London, NY, and Asian sessions (AUDUSD is active
# in the Asian session). Overlap remains the highest quality.
REQUIRED_SESSION = "any"


# --------------------------------------------------------------------------
# 1. DATA
# --------------------------------------------------------------------------
_MT5_TIMEFRAME_MAP = {
    "1m": "TIMEFRAME_M1", "5m": "TIMEFRAME_M5", "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30", "1h": "TIMEFRAME_H1", "4h": "TIMEFRAME_H4",
    "1d": "TIMEFRAME_D1",
}

# Intervals yfinance serves natively. Anything else is resampled from the
# finest native interval that divides it evenly (e.g. 4h from 1h).
_YF_NATIVE_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "90m",
                       "1h", "1d", "5d", "1wk", "1mo"}


# Cached once found, so a live loop doesn't re-probe every candidate on
# every poll. PER-PAIR: the old single-global cache meant that once EURUSD
# was resolved, AUDUSD and GBPUSD scans silently reused the EURUSD symbol
# and returned EURUSD price data under the wrong pair name.
_resolved_mt5_symbols = {}


def _resolve_mt5_symbol(mt5, candidates, pair_key):
    """Resolves the MT5 symbol for ONE pair and caches it under pair_key.
    pair_key is typically the pair name (e.g. 'EURUSD') so each pair has
    its own cached resolution."""
    if pair_key in _resolved_mt5_symbols:
        return _resolved_mt5_symbols[pair_key]
    tried = []
    for sym in candidates:
        if mt5.symbol_select(sym, True):
            _resolved_mt5_symbols[pair_key] = sym
            return sym
        tried.append(sym)
    raise ValueError(
        f"None of these symbol names were found/visible in MT5 Market Watch: "
        f"{tried}. Open Market Watch, right-click > 'Show All', find your "
        f"broker's exact symbol name and add it to the pair's mt5_symbols list."
    )


def _invalidate_mt5_symbol_cache(pair_key=None):
    """Call when a cached symbol may have become unavailable (e.g. a live
    loop retry after a data error) so the next fetch re-probes candidates.
    If pair_key is None, ALL cached symbols are invalidated."""
    global _resolved_mt5_symbols
    if pair_key is None:
        _resolved_mt5_symbols = {}
    else:
        _resolved_mt5_symbols.pop(pair_key, None)


def fetch_data_mt5(candidates=None, interval=LTF_INTERVAL, n_bars=LTF_BARS,
                   pair_key=None):
    """Pulls OHLC data straight from your broker via a running MT5 terminal.

    Requirements:
      1. pip install MetaTrader5
      2. The MT5 desktop terminal must be OPEN and logged into your broker
         account on this machine (Windows only — MT5's Python API only
         talks to a local terminal instance).
      3. Algo Trading must be enabled in MT5 (Tools > Options > Expert
         Advisors > Allow Algorithmic Trading), and the symbol must be
         visible in Market Watch (right-click Market Watch > Show All, or
         search for it) since some brokers hide it by default.
    """
    import MetaTrader5 as mt5
    candidates = candidates or MT5_SYMBOL_CANDIDATES
    # pair_key scopes the symbol cache per pair — without it, the first
    # resolved pair's symbol is reused for every subsequent pair.
    pair_key = pair_key or "default"

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}. "
                            f"Is the MT5 terminal open and logged in?")

    try:
        symbol = _resolve_mt5_symbol(mt5, candidates, pair_key)

        tf_const_name = _MT5_TIMEFRAME_MAP.get(interval)
        if tf_const_name is None:
            raise ValueError(f"Unsupported interval '{interval}' for MT5.")
        timeframe = getattr(mt5, tf_const_name)

        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n_bars)
        if rates is None or len(rates) == 0:
            # Symbol may have been dropped from Market Watch since cache.
            _invalidate_mt5_symbol_cache(pair_key)
            raise ValueError(f"No candles returned for '{symbol}' "
                              f"({mt5.last_error()})")

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        df = df.rename(columns={"tick_volume": "volume"})
        df = df[["open", "high", "low", "close", "volume"]].apply(
            pd.to_numeric, errors="coerce"
        ).dropna()
        df.attrs["source"] = f"LIVE MT5 ({symbol})"
        return df
    finally:
        mt5.shutdown()


def _resample_ohlc(df, rule):
    """Resample an OHLCV frame to a coarser bar rule ('4h', '30m', ...)."""
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    out = df.resample(rule).agg(agg).dropna()
    return out


def fetch_data_yfinance(symbol=YF_SYMBOL, interval=LTF_INTERVAL, n_bars=LTF_BARS):
    """Pulls OHLC data from Yahoo Finance as a broker-independent fallback.

    Yahoo does not natively serve every interval (notably 4h). When asked for
    a non-native interval, this loader pulls the finest native interval that
    divides it evenly and resamples — so HTF_INTERVAL='4h' works on yfinance.
    """
    yf = _import_yfinance()

    # yfinance wants a period string, not a bar count — pick one generously
    # long enough to cover n_bars at this interval, within Yahoo's intraday
    # history limits (60d max for sub-hourly intervals).
    period_map = {"1m": "5d", "2m": "60d", "5m": "60d", "15m": "60d",
                  "30m": "60d", "60m": "730d", "90m": "60d",
                  "1h": "730d", "4h": "730d", "1d": "5y"}
    period = period_map.get(interval, "60d")

    fetch_interval = interval
    resample_rule = None
    if interval not in _YF_NATIVE_INTERVALS:
        # Pick the finest native interval that evenly divides the target.
        # 4h -> 1h, 2h -> 1h, 6h -> 1h, etc.
        native_sorted = ["1m", "2m", "5m", "15m", "30m", "60m", "1h", "90m", "1d"]
        target_minutes = _interval_to_minutes(interval)
        fetch_interval = None
        for cand in native_sorted:
            cm = _interval_to_minutes(cand)
            if cm and target_minutes % cm == 0:
                fetch_interval = cand
                break
        if fetch_interval is None:
            raise ValueError(f"Cannot resample to unsupported interval '{interval}'.")
        resample_rule = interval
        fetch_period = period_map.get(fetch_interval, "60d")
    else:
        fetch_period = period

    df = yf.download(symbol, interval=fetch_interval, period=fetch_period,
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError("Empty dataframe returned")

    # yfinance can return MultiIndex columns like ('Close','GC=F') even
    # for a single ticker — flatten to plain 'Close', 'Open', etc.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns=str.lower)
    df = df.loc[:, ~df.columns.duplicated()]  # guard against dup columns
    df = df[["open", "high", "low", "close", "volume"]].apply(
        pd.to_numeric, errors="coerce"
    ).dropna()

    if resample_rule is not None:
        df = _resample_ohlc(df, resample_rule)

    df.attrs["source"] = f"LIVE YFINANCE ({symbol}, resampled to {interval})" \
        if resample_rule else f"LIVE YFINANCE ({symbol})"
    return df.tail(n_bars)


def _interval_to_minutes(interval):
    """'15m' -> 15, '1h' -> 60, '4h' -> 240, '1d' -> 1440, None if unknown."""
    if not interval:
        return None
    s = interval.strip().lower()
    try:
        if s.endswith("m"):
            return int(s[:-1])
        if s.endswith("h"):
            return int(s[:-1]) * 60
        if s.endswith("d"):
            return int(s[:-1]) * 1440
        if s.endswith("wk"):
            return int(s[:-2]) * 1440 * 7
    except ValueError:
        return None
    return None


def fetch_data(interval, n_bars, pair_name=None):
    """Top-level dispatcher. If pair_name is given, uses that pair's MT5/YF
    symbols. Otherwise falls back to the legacy single-symbol path (EURUSD).
    DATA_SOURCE = 'mt5' tries your broker's live feed only; 'yfinance' tries
    Yahoo only; 'auto' tries MT5 then Yahoo. Falls back to synthetic data."""
    if pair_name is not None:
        pair = _PAIR_BY_NAME.get(pair_name)
        if pair is None:
            raise ValueError(f"Unknown pair '{pair_name}'")
        mt5_syms = pair["mt5_symbols"]
        yf_sym = pair["yf_symbol"]
    else:
        mt5_syms = MT5_SYMBOL_CANDIDATES
        yf_sym = YF_SYMBOL

    attempts = []
    if DATA_SOURCE in ("mt5", "auto"):
        attempts.append(("MT5", lambda: fetch_data_mt5(
            mt5_syms, interval, n_bars, pair_key=pair_name)))
    if DATA_SOURCE in ("yfinance", "auto"):
        attempts.append(("yfinance", lambda: fetch_data_yfinance(yf_sym, interval, n_bars)))

    for name, fn in attempts:
        try:
            return fn()
        except Exception as e:
            print(f"[!] {name} data unavailable for {pair_name or 'default'} ({e})")

    print(f"[!] Falling back to a synthetic demo series ({pair_name or 'default'}, {interval}) "
          f"so you can see the scanner run. This is NOT real market data.\n")
    return _synthetic_demo_data(n=n_bars, interval=interval)


def _synthetic_demo_data(n=300, seed=7, interval=LTF_INTERVAL):
    """Realistic-ish synthetic forex price path (random walk + drift) purely
    so the scanner is demonstrable offline. NOT real market data."""
    freq_map = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
                "1h": "1h", "4h": "4h", "1d": "1d"}
    freq = freq_map.get(interval, "5min")
    rng = np.random.default_rng(seed)
    price = 1.0850  # EURUSD-like starting price
    rows = []
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=n, freq=freq)
    for t in idx:
        drift = rng.normal(0, 0.0003)  # forex-scale volatility
        price = max(price + drift, 0.5)
        o = price
        h = o + abs(rng.normal(0, 0.0004))
        l = o - abs(rng.normal(0, 0.0004))
        c = rng.uniform(l, h)
        v = rng.integers(500, 5000)
        rows.append([o, h, l, c, v])
        price = c
    df = pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close", "volume"])
    df.attrs["source"] = "SYNTHETIC DEMO DATA (offline fallback)"
    return df


def pair_cost_price(pair_name, atr_pctl=50.0):
    """Returns the total round-trip cost (spread + slippage) in PRICE terms
    for the given pair, scaling slippage by volatility."""
    pair = _PAIR_BY_NAME.get(pair_name, TRADED_PAIRS[0])
    pip_size = pair["pip_size"]
    spread_pips = pair["typical_spread_pips"]
    slip_pips = variable_slippage_pips(atr_pctl)
    return (spread_pips + slip_pips) * pip_size


def variable_slippage_pips(atr_pctl, base=SLIPPAGE_BASE_PIPS, max_slip=SLIPPAGE_MAX_PIPS):
    """Scales slippage (in pips) by current volatility."""
    if not ENABLE_VARIABLE_SLIPPAGE:
        return base
    pctl = max(5.0, min(95.0, float(atr_pctl)))
    if pctl <= 50:
        return base
    t = (pctl - 50.0) / 45.0
    return round(base + t * (max_slip - base), 3)


# --------------------------------------------------------------------------
# 2. INDICATORS
# --------------------------------------------------------------------------
def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def macd(series, fast=12, slow=26, signal=9):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def atr(df, period=14):
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def adx(df, period=ADX_PERIOD):
    """Average Directional Index — trend STRENGTH regardless of direction.
    >25 = strong trend, <20 = ranging. Uses Wilder's smoothing."""
    high, low, close = df["high"], df["low"], df["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr_sm = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_sm.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_sm.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(20.0)


def swing_levels(df, window=20):
    """Recent swing high/low used as the key S/R + Fibonacci anchor."""
    recent = df.tail(window)
    return recent["high"].max(), recent["low"].min()


def fib_retracement_zone(swing_high, swing_low, direction,
                         fib_hi_pct=0.618, fib_lo_pct=0.5):
    """Golden-zone (default 0.5-0.618 retracement) pros watch for entries.
    The pct bounds are parameterized so the regime classifier can widen the
    zone in high-vol regimes (where reactions overshoot the classic band)."""
    diff = swing_high - swing_low
    if direction == "LONG":
        return swing_high - diff * fib_hi_pct, swing_high - diff * fib_lo_pct
    else:
        return swing_low + diff * fib_lo_pct, swing_low + diff * fib_hi_pct


def detect_order_blocks(df, at=-1, lookback=OB_LOOKBACK,
                         min_body_ratio=OB_MIN_BODY_RATIO):
    """Detects the most recent bullish and bearish order blocks. A bullish OB
    is the last bearish candle before a strong bullish move; bearish OB is the
    last bullish candle before a strong bearish move. Returns (bull_ob,
    bear_ob) where each is (top, bottom) or None."""
    n = len(df)
    pos = at if at >= 0 else n + at
    if pos < lookback + 2:
        return None, None
    bull_ob = None
    bear_ob = None
    for i in range(pos, max(pos - lookback, 1), -1):
        bar = df.iloc[i]
        prev = df.iloc[i - 1]
        body = abs(float(bar["close"]) - float(bar["open"]))
        rng = max(float(bar["high"]) - float(bar["low"]), 1e-6)
        body_ratio = body / rng
        prev_is_bearish = float(prev["close"]) < float(prev["open"])
        prev_is_bullish = float(prev["close"]) > float(prev["open"])
        is_bullish = float(bar["close"]) > float(bar["open"])
        is_bearish = float(bar["close"]) < float(bar["open"])
        if bull_ob is None and prev_is_bearish and is_bullish and body_ratio > min_body_ratio:
            bull_ob = (float(prev["high"]), float(prev["low"]))
        if bear_ob is None and prev_is_bullish and is_bearish and body_ratio > min_body_ratio:
            bear_ob = (float(prev["high"]), float(prev["low"]))
        if bull_ob and bear_ob:
            break
    return bull_ob, bear_ob


def detect_fvgs(df, at=-1, min_gap_atr=FVG_MIN_GAP_ATR, atr_col="atr14"):
    """Detects fair value gaps (imbalances) in recent bars. A bullish FVG:
    bar[i-1].high < bar[i+1].low. A bearish FVG: bar[i-1].low > bar[i+1].high.
    Returns (bull_fvg, bear_fvg) where each is (top, bottom) or None."""
    n = len(df)
    pos = at if at >= 0 else n + at
    if pos < 3:
        return None, None
    atr_val = float(df[atr_col].iloc[pos]) if atr_col in df.columns else 1.0
    min_gap = min_gap_atr * max(atr_val, 1e-6)
    bull_fvg = None
    bear_fvg = None
    for i in range(min(pos - 1, n - 2), max(pos - 11, 0), -1):
        bar_before = df.iloc[i - 1]
        bar_after = df.iloc[i + 1]
        gap_up = float(bar_after["low"]) - float(bar_before["high"])
        gap_down = float(bar_before["low"]) - float(bar_after["high"])
        if bull_fvg is None and gap_up > min_gap:
            bull_fvg = (float(bar_after["low"]), float(bar_before["high"]))
        if bear_fvg is None and gap_down > min_gap:
            bear_fvg = (float(bar_before["low"]), float(bar_after["high"]))
        if bull_fvg and bear_fvg:
            break
    return bull_fvg, bear_fvg


def compute_indicators(df):
    df = df.copy()
    df["ema20"] = ema(df["close"], 20)
    df["ema50"] = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)
    df["rsi14"] = rsi(df["close"], 14)
    df["macd"], df["macd_signal"], df["macd_hist"] = macd(df["close"])
    df["atr14"] = atr(df, 14)
    df["adx14"] = adx(df, ADX_PERIOD)
    # Rolling mean volume for an expansion check on the confirmation candle.
    df["vol_ma20"] = df["volume"].rolling(20, min_periods=1).mean()
    return df


# --------------------------------------------------------------------------
# 2b. REGIME CLASSIFIER + CROSS-MARKET GATES + SIZING / EXECUTION HELPERS
# --------------------------------------------------------------------------
# All the new "make it super powerful" machinery lives here so the confluence
# engine and the trade-plan/backtest layers below can call into a single,
# well-named surface instead of having the logic scattered inline.

def classify_regime(df, at=-1, lookback=50, atr_col="atr14"):
    """Classify the market regime at bar `at` as one of:
      "trend"     — EMA stack ordered AND ADX-ish strength (price extending)
      "range"     — EMAs tangled, low volatility relative to its own norm
      "high_vol"  — ATR in the top quartile of its recent lookback window
      "trend_high_vol" — trending but in a blowoff-vol regime (treat as
                         high_vol for sizing, as trend for entry criteria)

    The regime drives BOTH the criteria thresholds used in evaluate_setup
    (via regime_criteria()) AND the position-sizing multiplier in
    volatility_targeted_risk_pct().

    Returns a dict so callers can use the label for display AND the numeric
    percentile for sizing decisions in one call."""
    n = len(df)
    pos = at if at >= 0 else n + at
    if pos < lookback:
        return {"regime": "range", "atr_pctl": 50.0, "reason": "insufficient history"}

    atr_series = df[atr_col].iloc[max(0, pos - lookback):pos + 1].dropna()
    if atr_series.empty:
        return {"regime": "range", "atr_pctl": 50.0, "reason": "no ATR"}

    atr_now = float(atr_series.iloc[-1])
    atr_pctl = float((atr_series < atr_now).mean() * 100)  # 0=calm, 100=hottest

    last = df.iloc[pos]
    ema20, ema50, ema200 = (float(last["ema20"]), float(last["ema50"]),
                            float(last["ema200"]))
    ema_spread = abs(ema20 - ema50) / max(last["close"], 1e-6)
    stacked = (ema20 > ema50 > ema200) or (ema20 < ema50 < ema200)
    trending = stacked and ema_spread > FLAT_EMA_THRESHOLD
    adx_val = float(last["adx14"]) if "adx14" in last.index else 25.0
    if ENABLE_ADX_FILTER:
        trending = trending and adx_val >= ADX_RANGE_THRESHOLD

    high_vol = atr_pctl >= 75
    if trending and high_vol:
        regime = "trend_high_vol"
    elif trending:
        regime = "trend"
    elif high_vol:
        regime = "high_vol"
    else:
        regime = "range"
    return {"regime": regime, "atr_pctl": atr_pctl, "reason": "", "adx": adx_val}


def regime_criteria(regime):
    """Returns the RSI continuation band, fib-zone band, strong-close body
    ratio, and volume-expansion multiplier appropriate for the regime.

    The original hardcoded values (RSI 45-68 / 32-55, fib 0.5-0.618, body
    >0.55, vol >1.1x) were tuned for a single (trending, normal-vol) regime.
    Different regimes warrant different thresholds:
      - range:        tighter RSI (mean-reversion leans), no deep fib required
      - trend:        the original continuation-zone values (baseline)
      - high_vol:     wider stops implied; relax body ratio (candles are messy
                      in blowoff vol), tighten volume req (vol is already high)
      - trend_high_vol: trend criteria but with the high_vol volume tweak
    """
    presets = {
        # (rsi_long_lo, rsi_long_hi, rsi_short_lo, rsi_short_hi,
        #  fib_lo_pct, fib_hi_pct, body_ratio_min, vol_mult)
        "range":           (40, 60, 40, 60, 0.5, 0.618, 0.50, 1.1),
        "trend":           (45, 68, 32, 55, 0.5, 0.618, 0.55, 1.1),
        "high_vol":        (40, 72, 28, 60, 0.5, 0.65,  0.45, 1.05),
        "trend_high_vol":  (45, 72, 28, 60, 0.5, 0.618, 0.50, 1.05),
    }
    return presets.get(regime, presets["trend"])


# --- DXY CORRELATION GATE ---------------------------------------------------
# Cached so a 15-min live loop doesn't re-pull the whole DXY series every
# poll — invalidated after DATA_FETCH_CACHE_TTL_S seconds or on data error.
_dxy_cache = {"df": None, "fetched_at": 0.0}
DATA_FETCH_CACHE_TTL_S = 600  # 10 min — DXY is slow-moving; 1h bars are fine


def fetch_dxy(n_bars=300):
    """Pulls the US Dollar Index (DXY) for the correlation gate. Uses
    yfinance (broker-independent) on the 1h interval to match the HTF. On
    any failure returns None and the gate is skipped — a missing DXY feed
    must NEVER block a signal, only FAIL OPEN."""
    if not ENABLE_DXY_GATE:
        return None
    now = time.time()
    if _dxy_cache["df"] is not None and now - _dxy_cache["fetched_at"] < DATA_FETCH_CACHE_TTL_S:
        return _dxy_cache["df"]
    try:
        yf = _import_yfinance()
        df = yf.download(DXY_YF_SYMBOL, interval="1h", period="60d",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns=str.lower)
        df = df[["open", "high", "low", "close", "volume"]].apply(
            pd.to_numeric, errors="coerce").dropna()
        df = df.tail(n_bars)
        _dxy_cache["df"] = df
        _dxy_cache["fetched_at"] = now
        return df
    except Exception as e:
        print(f"[!] DXY fetch failed ({e}); correlation gate skipped (FAIL OPEN).")
        return None


def dxy_break_direction(dxy_df, trend_bars=DXY_TREND_BARS, break_pct=DXY_BREAK_PCT):
    """Determines whether DXY is 'breaking up', 'breaking down', or 'flat'
    over the last `trend_bars` bars. A break = the net move over the window
    exceeds break_pct of the window-start price. Returns one of those three
    strings, or None if the data is too short.

    This is the gate: a gold LONG while DXY is 'breaking up' is low-quality
    (the dollar is moving AGAINST the gold-long thesis), so the caller
    blocks or downgrades the signal accordingly."""
    if dxy_df is None or len(dxy_df) < trend_bars:
        return None
    recent = dxy_df.tail(trend_bars)
    start_price = float(recent["close"].iloc[0])
    end_price = float(recent["close"].iloc[-1])
    if start_price <= 0:
        return None
    move = (end_price - start_price) / start_price
    if move > break_pct:
        return "up"
    if move < -break_pct:
        return "down"
    return "flat"


def dxy_gate_against_pair(pair_name, direction, dxy_dir):
    """Returns (blocked_bool, reason_str). For USD-quoted FX pairs
    (EURUSD, AUDUSD, GBPUSD), DXY breaking UP = USD strengthening = BEARISH.
    A LONG on these pairs while DXY breaks up is blocked; a SHORT while DXY
    breaks down is blocked. Flat DXY or missing data = open."""
    if dxy_dir is None or dxy_dir == "flat":
        return False, "DXY flat or unavailable — no conflict"
    if direction == "LONG" and dxy_dir == "up":
        return True, f"DXY breaking UP — conflicts with {pair_name} LONG (dollar strength)"
    if direction == "SHORT" and dxy_dir == "down":
        return True, f"DXY breaking DOWN — conflicts with {pair_name} SHORT (dollar weakness)"
    return False, f"DXY breaking {dxy_dir.upper()} — supports {pair_name} {direction}"


# --- TIPS REAL-YIELD CORRELATION GATE --------------------------------------
# Same pattern as DXY but for real yields. TIP is a PRICE instrument, so a
# rising yield = falling TIP price. We invert so the gate reasons about
# YIELDS (which is how gold traders think) not bond prices.
_tips_cache = {"df": None, "fetched_at": 0.0}


def fetch_tips(n_bars=300):
    """Pulls the TIPS bond ETF (TIP) for the real-yield gate. FAILS OPEN —
    returns None on any error so a missing feed never blocks a signal."""
    if not ENABLE_TIPS_GATE:
        return None
    now = time.time()
    if _tips_cache["df"] is not None and now - _tips_cache["fetched_at"] < DATA_FETCH_CACHE_TTL_S:
        return _tips_cache["df"]
    try:
        yf = _import_yfinance()
        df = yf.download(TIPS_YF_SYMBOL, interval="1h", period="60d",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns=str.lower)
        df = df[["open", "high", "low", "close", "volume"]].apply(
            pd.to_numeric, errors="coerce").dropna()
        df = df.tail(n_bars)
        _tips_cache["df"] = df
        _tips_cache["fetched_at"] = now
        return df
    except Exception as e:
        print(f"[!] TIPS fetch failed ({e}); real-yield gate skipped (FAIL OPEN).")
        return None


def tips_yield_break_direction(tips_df, trend_bars=TIPS_TREND_BARS,
                               break_pct=TIPS_BREAK_PCT):
    """Determines whether real YIELDS are 'breaking up', 'breaking down', or
    'flat' over the last `trend_bars` bars. Since TIP is a bond PRICE ETF,
    a falling price = rising yield, so we INVERT the price move to get the
    yield direction. Returns 'up'/'down'/'flat'/None."""
    if tips_df is None or len(tips_df) < trend_bars:
        return None
    recent = tips_df.tail(trend_bars)
    start_price = float(recent["close"].iloc[0])
    end_price = float(recent["close"].iloc[-1])
    if start_price <= 0:
        return None
    price_move = (end_price - start_price) / start_price
    yield_move = -price_move  # invert: bond price down = yield up
    if yield_move > break_pct:
        return "up"     # yields rising
    if yield_move < -break_pct:
        return "down"   # yields falling
    return "flat"


def tips_gate_against_gold(gold_direction, yield_dir):
    """Returns (blocked_bool, reason_str). A gold LONG is blocked when real
    yields are breaking UP (rising opportunity cost = gold bearish); a gold
    SHORT is blocked when yields are breaking DOWN. Flat/missing = open."""
    if yield_dir is None or yield_dir == "flat":
        return False, "Real yields flat or unavailable — no conflict"
    if gold_direction == "LONG" and yield_dir == "up":
        return True, "Real yields breaking UP — conflicts with gold LONG (rising opportunity cost)"
    if gold_direction == "SHORT" and yield_dir == "down":
        return True, "Real yields breaking DOWN — conflicts with gold SHORT (falling yields support gold)"
    return False, f"Real yields breaking {yield_dir.upper()} — supports gold {gold_direction}"


# --- COT POSITIONING OVERLAY ------------------------------------------------
def cot_alignment(gold_direction, snapshot=None):
    """Compares the signal direction against the manually-maintained COT
    snapshot of institutional (non-commercial) net positioning.

    Returns (alignment_str, bonus_point_bool) where alignment is one of:
      "with_positioning", "against_positioning", "no_snapshot".
    A signal WITH institutional positioning earns a bonus confluence point
    (added to max_score too, so the grade scale stays consistent); a signal
    AGAINST it is flagged in the checklist but NOT blocked — institutions
    can be wrong and the COT report is a week stale by design."""
    snapshot = snapshot if snapshot is not None else COT_SNAPSHOT
    if not snapshot:
        return "no_snapshot", False
    net_long = int(snapshot.get("net_noncomm_long_oz", 0) or 0)
    net_short = int(snapshot.get("net_noncomm_short_oz", 0) or 0)
    if net_long == net_short:
        return "no_snapshot", False
    institutions_long = net_long > net_short
    with_positioning = (gold_direction == "LONG" and institutions_long) or \
                       (gold_direction == "SHORT" and not institutions_long)
    if with_positioning:
        return "with_positioning", True
    return "against_positioning", False


# --- VOLATILITY-TARGETED POSITION SIZING ------------------------------------
def volatility_targeted_risk_pct(atr_pctl, base_pct=RISK_PER_TRADE_PCT,
                                 min_pct=VOL_RISK_MIN, max_pct=VOL_RISK_MAX):
    """Scales risk per trade by current volatility (ATR percentile). At the
    median (pctl=50) returns the base_pct; below median (calm) scales toward
    max_pct (risk MORE when stops are tight and conditions are clean); above
    median (hot) scales toward min_pct (risk LESS when stops are wide and
    fills are noisy). Linear interpolation between the 5th and 95th pct.

    atr_pctl comes from classify_regime()['atr_pctl']."""
    if not VOL_TARGETED_RISK:
        return base_pct
    pctl = max(5.0, min(95.0, float(atr_pctl)))
    if pctl <= 50:
        # calm side: 50th -> base, 5th -> max
        t = (50.0 - pctl) / 45.0
        return round(base_pct + t * (max_pct - base_pct), 3)
    else:
        # hot side: 50th -> base, 95th -> min
        t = (pctl - 50.0) / 45.0
        return round(base_pct + t * (min_pct - base_pct), 3)


def variable_slippage(atr_pctl, base=SLIPPAGE_BASE_USD, max_slip=SLIPPAGE_MAX_USD):
    """Scales slippage by current volatility. At median returns base; at 95th
    pct returns max_slip. Linear interpolation between."""
    if not ENABLE_VARIABLE_SLIPPAGE:
        return base
    pctl = max(5.0, min(95.0, float(atr_pctl)))
    if pctl <= 50:
        return base
    t = (pctl - 50.0) / 45.0
    return round(base + t * (max_slip - base), 3)


# --- TRAILING STOP for the TP3 runner --------------------------------------
def compute_trailing_stop(direction, entry, current_stop, ltf_row, atr_val,
                          method=TRAIL_METHOD, atr_mult=TRAIL_ATR_MULT):
    """Returns the new stop price for the runner, or current_stop unchanged
    if the method says 'none' or the trail is not yet tighter than current.

    Only ever moves the stop IN the favorable direction (never widens risk).
    Called once per LTF bar after TP2 has filled, in both the backtest sim
    and (conceptually) the live plan's management note."""
    if method == "none":
        return current_stop
    if method == "atr":
        if direction == "LONG":
            trail = entry + atr_mult * atr_val
            return max(current_stop, trail)
        else:
            trail = entry - atr_mult * atr_val
            return min(current_stop, trail)
    if method == "ema20":
        ema20 = float(ltf_row["ema20"])
        if direction == "LONG":
            # trail a fixed cushion below EMA20
            trail = ema20 - atr_mult * atr_val * 0.25
            return max(current_stop, trail)
        else:
            trail = ema20 + atr_mult * atr_val * 0.25
            return min(current_stop, trail)
    return current_stop


# --- MT5 AUTO-EXECUTE + CORRELATED-EXPOSURE + OUTCOME LOGGING --------------
# These only do anything real when AUTO_EXECUTE is True AND the MT5 terminal
# is available. Otherwise they return safe no-ops so the scanner runs
# unchanged in offline/demo mode.

def _mt5_send_market_order(direction, symbol, lots, sl, tp, comment="gold_scanner"):
    """Places a real MT5 market order. Returns the MT5 order result dict on
    success, raises on failure. Called only when AUTO_EXECUTE is True."""
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")
    try:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"No tick for {symbol}")
        price = tick.ask if direction == "LONG" else tick.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lots),
            "type": mt5.ORDER_TYPE_BUY if direction == "LONG" else mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": AUTO_EXECUTE_DEVIATION,
            "magic": AUTO_EXECUTE_MAGIC,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"order_send failed: {result}")
        return result
    finally:
        mt5.shutdown()


def auto_execute_order(trade_plan, symbol_candidates=None):
    """Wraps _mt5_send_market_order with the symbol-resolution + lot-viability
    checks. Uses the trade plan's Symbol to find the right MT5 symbols."""
    if not AUTO_EXECUTE:
        return None
    pair_name = trade_plan.get("Symbol", "EURUSD")
    pair = _PAIR_BY_NAME.get(pair_name, TRADED_PAIRS[0])
    symbol_candidates = symbol_candidates or pair["mt5_symbols"]
    position = trade_plan.get("_position", {})
    if not position.get("viable"):
        print("[auto-execute] Position not viable — no order sent.")
        return None
    import MetaTrader5 as mt5
    try:
        if not mt5.initialize():
            return None
        sym = _resolve_mt5_symbol(mt5, symbol_candidates, pair_name)
        mt5.shutdown()
    except Exception as e:
        print(f"[auto-execute] Cannot resolve symbol: {e}")
        return None
    try:
        result = _mt5_send_market_order(
            direction=trade_plan["Direction"],
            symbol=sym,
            lots=position["lots"],
            sl=trade_plan["Stop Loss"],
            tp=trade_plan["TP1"],
            comment=f"fx_scanner {trade_plan['Grade']} {pair_name}",
        )
        print(f"[auto-execute] ORDER SENT: {trade_plan['Direction']} "
              f"{position['lots']} lots {sym} @ {result.price}, "
              f"ticket {result.order}")
        return result
    except Exception as e:
        print(f"[auto-execute] ORDER FAILED: {e}")
        return None


def correlated_exposure_blocked(eurusd_direction, groups=None):
    """Checks OPEN MT5 positions (tagged with our magic number) for
    correlated exposure. Returns (blocked_bool, reason_str).

    A EURUSD LONG is blocked if there is already an open LONG in a
    'same_side_as_eurusd_long=LONG' group (e.g. GBPUSD long), OR an open
    SHORT in a 'same_side_as_eurusd_long=SHORT' group (e.g. DXY short —
    both are the same dollar-short bet). Symmetric for EURUSD SHORT.

    Returns (False, 'auto-execute off — exposure check skipped') when
    AUTO_EXECUTE is off, since there are no scanner-managed positions to
    check. This is a GUARD, not a gate: it never blocks in demo/offline."""
    if not AUTO_EXECUTE:
        return False, "auto-execute off — exposure check skipped"
    groups = groups if groups is not None else CORRELATED_EXPOSURE_GROUPS
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return False, "MT5 unavailable — exposure check skipped (FAIL OPEN)"
        try:
            positions = mt5.positions_get(magic=AUTO_EXECUTE_MAGIC) or []
            # Build a quick lookup of open (symbol->direction) for our trades
            open_dirs = {}
            for p in positions:
                # MT5 type: 0=buy(LONG), 1=sell(SHORT)
                d = "LONG" if p.type == 0 else "SHORT"
                open_dirs[p.symbol] = d
        finally:
            mt5.shutdown()
        for grp in groups:
            dup_dir = grp["same_side_as_eurusd_long"]
            # The side that duplicates a EURUSD LONG:
            #   if dup_dir=="LONG", a LONG in this group == eurusd long (block eurusd long)
            #   if dup_dir=="SHORT", a SHORT in this group == eurusd long (block eurusd long)
            for sym in grp["symbols"]:
                if sym not in open_dirs:
                    continue
                open_dir = open_dirs[sym]
                # Does this open position duplicate the proposed eurusd direction?
                eurusd_dup_side = "LONG" if dup_dir == "LONG" else "SHORT"
                eurusd_opp_side = "SHORT" if dup_dir == "LONG" else "LONG"
                # If group's same-side-as-eurusd-long is LONG, then an open LONG
                # duplicates a EURUSD LONG; an open SHORT duplicates a EURUSD SHORT.
                if eurusd_direction == "LONG" and open_dir == eurusd_dup_side:
                    return True, (f"Already open {open_dir} {grp['name']} ({sym}) "
                                  f"— same-side as EURUSD LONG (duplicate dollar bet)")
                if eurusd_direction == "SHORT" and open_dir == eurusd_opp_side:
                    return True, (f"Already open {open_dir} {grp['name']} ({sym}) "
                                  f"— same-side as EURUSD SHORT (duplicate dollar bet)")
        return False, "No correlated exposure in open positions"
    except Exception as e:
        print(f"[!] Correlated-exposure check failed ({e}); skipped (FAIL OPEN).")
        return False, f"check failed ({e}) — skipped (FAIL OPEN)"


def sync_trade_outcomes_from_mt5(path=None):
    """Reads CLOSED MT5 positions tagged with our magic number since the
    last sync, appends their realized P&L to TRADE_LOG_PATH, and records the
    last-synced deal time so we don't double-count. This is what makes the
    daily-loss circuit breaker REAL when AUTO_EXECUTE is on — the scanner
    itself writes the outcomes it reads back.

    No-ops (returns 0) when AUTO_EXECUTE is off or MT5 is unavailable."""
    if not AUTO_EXECUTE:
        return 0
    path = path if path is not None else TRADE_LOG_PATH
    state_path = path + ".last_sync"
    last_sync_ts = 0.0
    if os.path.isfile(state_path):
        try:
            with open(state_path) as f:
                last_sync_ts = float(f.read().strip() or 0)
        except (ValueError, OSError):
            last_sync_ts = 0.0
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return 0
        try:
            # history_deals_get pulls closed deals (including closes) from a
            # given UTC timestamp onward.
            from_ts = datetime.fromtimestamp(last_sync_ts, tz=timezone.utc)
            deals = mt5.history_deals_get(from_ts, datetime.now(timezone.utc)) or []
            new_rows = 0
            for d in deals:
                if d.magic != AUTO_EXECUTE_MAGIC:
                    continue
                # ENTRY deals have entry=1, EXIT/closing deals have entry=0.
                # We only log the EXIT (realized P&L is meaningful on close).
                if d.entry != 0:
                    continue
                direction = "LONG" if d.type == 0 else "SHORT"
                # profit is in account currency (USD) for most XAUUSD setups
                log_trade_outcome(pd.Timestamp(d.time, unit='s', tz='UTC'),
                                  direction, float(d.profit), path=path)
                new_rows += 1
            if deals:
                latest_ts = max(d.time for d in deals)
                with open(state_path, "w") as f:
                    f.write(str(latest_ts))
            return new_rows
        finally:
            mt5.shutdown()
    except Exception as e:
        print(f"[!] sync_trade_outcomes_from_mt5 failed ({e}); skipped.")
        return 0


# --------------------------------------------------------------------------
# 3. CONFLUENCE SIGNAL ENGINE
# --------------------------------------------------------------------------
def is_ny_london_overlap(ts):
    """London/New York overlap = highest-liquidity gold trading window.
    Computed from REAL local trading hours (London 08:00-16:30, New York
    08:00-17:00 local time) converted to UTC for the specific date — this
    self-corrects for both London and US Daylight Saving Time shifts,
    instead of hardcoding UTC hours that silently drift wrong twice a year.
    """
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    ts_utc = ts.tz_convert("UTC")
    day = ts_utc.date()

    london_open = pd.Timestamp(day, tz=ZoneInfo("Europe/London")).replace(hour=8, minute=0).tz_convert("UTC")
    london_close = pd.Timestamp(day, tz=ZoneInfo("Europe/London")).replace(hour=16, minute=30).tz_convert("UTC")
    ny_open = pd.Timestamp(day, tz=ZoneInfo("America/New_York")).replace(hour=8, minute=0).tz_convert("UTC")
    ny_close = pd.Timestamp(day, tz=ZoneInfo("America/New_York")).replace(hour=17, minute=0).tz_convert("UTC")

    overlap_start = max(london_open, ny_open)
    overlap_end = min(london_close, ny_close)
    return overlap_start <= ts_utc <= overlap_end


def get_trading_session(ts):
    """Returns the current trading session: 'london'/'new_york'/'overlap'/
    'asian'/'closed'."""
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    ts_utc = ts.tz_convert("UTC")
    day = ts_utc.date()
    london_open = pd.Timestamp(day, tz=ZoneInfo("Europe/London")).replace(hour=8, minute=0).tz_convert("UTC")
    london_close = pd.Timestamp(day, tz=ZoneInfo("Europe/London")).replace(hour=16, minute=30).tz_convert("UTC")
    ny_open = pd.Timestamp(day, tz=ZoneInfo("America/New_York")).replace(hour=8, minute=0).tz_convert("UTC")
    ny_close = pd.Timestamp(day, tz=ZoneInfo("America/New_York")).replace(hour=17, minute=0).tz_convert("UTC")
    asian_open = pd.Timestamp(day, tz=ZoneInfo("Asia/Tokyo")).replace(hour=9, minute=0).tz_convert("UTC")
    asian_close = pd.Timestamp(day, tz=ZoneInfo("Asia/Tokyo")).replace(hour=18, minute=0).tz_convert("UTC")
    overlap_start = max(london_open, ny_open)
    overlap_end = min(london_close, ny_close)
    if overlap_start <= ts_utc <= overlap_end:
        return "overlap"
    if london_open <= ts_utc <= london_close:
        return "london"
    if ny_open <= ts_utc <= ny_close:
        return "new_york"
    if asian_open <= ts_utc <= asian_close:
        return "asian"
    return "closed"


def session_allows_signal(ts, required=REQUIRED_SESSION):
    """Checks whether the current session meets the required quality
    threshold for trend-following signals."""
    if not ENABLE_SESSION_FILTER:
        return True, "session filter off"
    session = get_trading_session(ts)
    _valid = {
        "any": ("overlap", "london", "new_york", "asian", "closed"),
        "london_ny": ("overlap", "london", "new_york"),
        "london": ("overlap", "london"),
        "overlap": ("overlap",),
    }
    allowed = _valid.get(required, _valid["london_ny"])
    if session in allowed:
        return True, f"session={session} (meets required={required})"
    return False, f"session={session} (requires {required} — low-quality for trend signals)"


def is_news_blackout(ts, windows=None):
    """Checks a MANUALLY maintained list of high-impact news events
    (NEWS_BLACKOUT_WINDOWS) — not a live economic calendar. Update that
    list yourself from ForexFactory/similar before trading sessions where
    NFP, CPI, or FOMC events are scheduled."""
    windows = windows if windows is not None else NEWS_BLACKOUT_WINDOWS
    if not windows:
        return False, None
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    for event_time_str, before_min, after_min, label in windows:
        event_time = pd.Timestamp(event_time_str, tz="UTC")
        window_start = event_time - pd.Timedelta(minutes=before_min)
        window_end = event_time + pd.Timedelta(minutes=after_min)
        if window_start <= ts <= window_end:
            return True, label

    if ENABLE_AUTO_NEWS:
        auto_event = _check_auto_news_blackout(ts)
        if auto_event:
            return True, auto_event

    return False, None


_news_cache = {"events": None, "fetched_at": 0.0}
_NEWS_CACHE_TTL_S = 3600


def fetch_economic_calendar():
    """Pulls this week's high-impact USD events from a free calendar API.
    Returns a list of (timestamp, title) tuples. FAILS OPEN."""
    if not ENABLE_AUTO_NEWS:
        return []
    now = time.time()
    if _news_cache["events"] is not None and now - _news_cache["fetched_at"] < _NEWS_CACHE_TTL_S:
        return _news_cache["events"]
    try:
        import urllib.request
        import json as _json
        req = urllib.request.Request(NEWS_API_URL, headers={"User-Agent": "gold_scanner/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        events = []
        for ev in data:
            if ev.get("impact") != "High":
                continue
            if ev.get("country") not in ("USD", "EUR", "GBP", "AUD", "ALL"):
                continue
            ts = pd.Timestamp(ev.get("date"), tz="UTC")
            if pd.isna(ts):
                continue
            events.append((ts, ev.get("title", "Unknown event")))
        _news_cache["events"] = events
        _news_cache["fetched_at"] = now
        return events
    except Exception as e:
        print(f"[!] Economic calendar fetch failed ({e}); using manual list only.")
        _news_cache["events"] = []
        _news_cache["fetched_at"] = now
        return []


def _check_auto_news_blackout(ts):
    """Checks the auto-fetched economic calendar for blackout windows."""
    events = fetch_economic_calendar()
    if not events:
        return None
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    for event_ts, title in events:
        window_start = event_ts - pd.Timedelta(minutes=NEWS_BLACKOUT_MINUTES_BEFORE)
        window_end = event_ts + pd.Timedelta(minutes=NEWS_BLACKOUT_MINUTES_AFTER)
        if window_start <= ts <= window_end:
            return f"{title} (auto calendar)"
    return None


def evaluate_setup(df, at=-1, swing_window=20):
    """Scores the candle AT POSITION `at` (default: the last/current row)
    against the 6-point professional confluence checklist. Parameterized by
    position (not hardcoded to the last row) so the exact same logic can be
    replayed bar-by-bar in the backtester — one scoring engine, not two
    that can silently drift apart."""
    n = len(df)
    pos = at if at >= 0 else n + at
    if pos < 1:
        raise ValueError(f"Not enough bars before position {pos} to evaluate.")

    last_row = df.iloc[pos]
    # Force every field to a plain python float. If the dataframe ever has
    # duplicate/misapen columns again, this raises a clear TypeError here
    # instead of the confusing "truth value of a Series is ambiguous" error.
    _indicator_cols = ["open", "high", "low", "close", "ema20", "ema50", "ema200",
                       "rsi14", "macd", "macd_signal", "macd_hist", "atr14"]
    if "adx14" in last_row.index:
        _indicator_cols.append("adx14")
    last = {col: float(last_row[col]) for col in _indicator_cols}
    if "vol_ma20" in last_row.index:
        last["vol_ma20"] = float(last_row["vol_ma20"])
    else:
        last["vol_ma20"] = float("nan")
    window_start = max(0, pos - swing_window + 1)
    swing_high, swing_low = swing_levels(df.iloc[window_start:pos + 1], window=swing_window)
    swing_high, swing_low = float(swing_high), float(swing_low)

    # Flat-EMAs filter: if EMA20 and EMA50 are within FLAT_EMA_THRESHOLD of
    # price apart, the stack is effectively flat even if technically ordered
    # — don't count it as a real trend alignment.
    ema_spread = abs(last["ema20"] - last["ema50"])
    flat_emas = ema_spread < FLAT_EMA_THRESHOLD * last["close"]
    trend_up = (last["ema20"] > last["ema50"] > last["ema200"]) and not flat_emas
    trend_down = (last["ema20"] < last["ema50"] < last["ema200"]) and not flat_emas
    direction = "LONG" if trend_up else ("SHORT" if trend_down else None)

    score = 0
    reasons = []
    checklist = []  # (criterion_name, passed_bool_or_None) — None = N/A
    fib_lo, fib_hi = None, None

    # --- REGIME-AWARE CRITERIA -------------------------------------------
    # The original hardcoded RSI/fib/body/vol thresholds were tuned for one
    # (trending, normal-vol) regime. Now we classify the regime at this bar
    # and pick the threshold preset that fits it. The regime also feeds vol-
    # targeted position sizing downstream via atr_pctl.
    regime_info = classify_regime(df, at=pos)
    regime = regime_info["regime"]
    atr_pctl = regime_info["atr_pctl"]
    (rsi_long_lo, rsi_long_hi, rsi_short_lo, rsi_short_hi,
     fib_lo_pct, fib_hi_pct, body_ratio_min, vol_mult) = regime_criteria(regime)

    # --- COT POSITIONING OVERLAY -----------------------------------------
    # When a COT snapshot is populated, a signal WITH institutional
    # positioning earns a bonus point (and max_score grows by 1 so the
    # grade scale stays consistent). AGAINST positioning is flagged but
    # not blocked — institutions can be wrong and the report is week-stale.
    cot_align, cot_bonus = (None, False)
    ob_fvg_detail = ""
    max_score = 6

    if direction:
        cot_align, cot_bonus = cot_alignment(direction)
        if cot_bonus:
            max_score = 7  # COT adds a 7th point when it agrees

        adx_val = last.get("adx14", 25.0)
        adx_ok = (not ENABLE_ADX_FILTER) or adx_val >= ADX_MIN_TREND
        if adx_ok:
            checklist.append((f"Trend stack aligned + ADX={adx_val:.1f} >= {ADX_MIN_TREND}", True))
            score += 1
            reasons.append(checklist[-1][0])
        else:
            checklist.append((f"Trend stack aligned but ADX={adx_val:.1f} < {ADX_MIN_TREND} (weak trend)", False))

        # Momentum: continuation zone, not overbought/oversold exhaustion.
        # Bands come from the regime preset (wider in high-vol, tighter in
        # range) instead of the old fixed 45-68 / 32-55.
        if direction == "LONG":
            rsi_ok = rsi_long_lo <= last["rsi14"] <= rsi_long_hi
            checklist.append((f"RSI in bullish continuation zone ({rsi_long_lo}-{rsi_long_hi}, regime={regime})", rsi_ok))
        else:
            rsi_ok = rsi_short_lo <= last["rsi14"] <= rsi_short_hi
            checklist.append((f"RSI in bearish continuation zone ({rsi_short_lo}-{rsi_short_hi}, regime={regime})", rsi_ok))
        if rsi_ok:
            score += 1
            reasons.append(checklist[-1][0])

        # MACD histogram expanding in trend direction
        hist_now = last["macd_hist"]
        hist_prev = float(df["macd_hist"].iloc[pos - 1])
        if direction == "LONG":
            macd_ok = hist_now > 0 and hist_now > hist_prev
            checklist.append(("MACD momentum expanding bullish", macd_ok))
        else:
            macd_ok = hist_now < 0 and hist_now < hist_prev
            checklist.append(("MACD momentum expanding bearish", macd_ok))
        if macd_ok:
            score += 1
            reasons.append(checklist[-1][0])

        # Key level confluence: price PENETRATING the fib "golden zone"
        # intrabar (wick test), not merely closing inside it — this captures
        # the rejection-wick entries the methodology is built on. The zone
        # width is regime-dependent (wider in high-vol where reactions
        # overshoot the classic 0.5-0.618 band).
        fib_lo, fib_hi = fib_retracement_zone(swing_high, swing_low, direction,
                                              fib_hi_pct=fib_hi_pct,
                                              fib_lo_pct=fib_lo_pct)
        if direction == "LONG":
            fib_ok = (last["low"] <= fib_hi) and (last["close"] >= fib_lo)
        else:
            fib_ok = (last["high"] >= fib_lo) and (last["close"] <= fib_hi)
        checklist.append((f"Price reacting at Fibonacci golden zone ({fib_lo:.2f}-{fib_hi:.2f}, regime={regime})", fib_ok))
        if fib_ok:
            score += 1
            reasons.append(checklist[-1][0])

        # Price action confirmation: strong close in trend direction.
        # Body-ratio threshold is regime-dependent (relaxed in high-vol where
        # candles are inherently messier).
        body = abs(last["close"] - last["open"])
        candle_range = max(last["high"] - last["low"], 1e-6)
        strong_close = body / candle_range > body_ratio_min
        if direction == "LONG":
            candle_ok = last["close"] > last["open"] and strong_close
            checklist.append((f"Bullish confirmation candle (body > {body_ratio_min:.2f})", candle_ok))
        else:
            candle_ok = last["close"] < last["open"] and strong_close
            checklist.append((f"Bearish confirmation candle (body > {body_ratio_min:.2f})", candle_ok))
        if candle_ok:
            score += 1
            reasons.append(checklist[-1][0])

        # Volume expansion on the confirmation candle (not dead volume).
        # The expansion multiple is regime-dependent (tightened in high-vol
        # where volume is already elevated, so the bar isn't double-counted).
        vol_ma = last["vol_ma20"]
        if not math.isnan(vol_ma) and vol_ma > 0:
            vol_now = float(df["volume"].iloc[pos])
            vol_ok = vol_now > vol_ma * vol_mult
        else:
            vol_ok = False
        checklist.append((f"Volume expansion on confirmation candle (> {vol_mult:.2f}x avg)", vol_ok))
        if vol_ok:
            score += 1
            reasons.append(checklist[-1][0])

        # Session timing
        session_ok = is_ny_london_overlap(df.index[pos])
        checklist.append(("Inside London/New York overlap (peak liquidity)", session_ok))
        if session_ok:
            score += 1
            reasons.append(checklist[-1][0])

        # Order block / FVG institutional footprint (bonus point, like COT)
        if ENABLE_OB_FVG:
            bull_ob, bear_ob = detect_order_blocks(df, at=pos)
            bull_fvg, bear_fvg = detect_fvgs(df, at=pos)
            price = last["close"]
            ob_hit = False
            if direction == "LONG":
                if bull_ob and bull_ob[1] <= price <= bull_ob[0]:
                    ob_hit = True
                    ob_fvg_detail = "bullish order block"
                elif bull_fvg and bull_fvg[1] <= price <= bull_fvg[0]:
                    ob_hit = True
                    ob_fvg_detail = "bullish fair value gap"
            else:
                if bear_ob and bear_ob[1] <= price <= bear_ob[0]:
                    ob_hit = True
                    ob_fvg_detail = "bearish order block"
                elif bear_fvg and bear_fvg[1] <= price <= bear_fvg[0]:
                    ob_hit = True
                    ob_fvg_detail = "bearish fair value gap"
            if ob_hit:
                max_score += 1
                checklist.append((f"Price at {ob_fvg_detail} (institutional footprint)", True))
                score += 1
                reasons.append(checklist[-1][0])
            else:
                checklist.append(("Order block / FVG confluence (none at current price)", None))

        # COT bonus point (only counted when a snapshot is populated AND it
        # agrees with the signal direction). Against-positioning is shown as
        # a FAIL without lowering the score below what the other 6 give.
        if cot_align == "with_positioning":
            checklist.append(("COT institutional positioning agrees (bonus point)", True))
            score += 1
            reasons.append(checklist[-1][0])
        elif cot_align == "against_positioning":
            checklist.append(("COT institutional positioning AGAINST signal (flagged, not blocked)", False))
        else:
            checklist.append(("COT positioning (no snapshot — populate COT_SNAPSHOT to enable)", None))
    else:
        if flat_emas:
            checklist.append((f"Trend stack flat (EMA20/EMA50 within {FLAT_EMA_THRESHOLD*100:.1f}% — not a real trend)", False))
        else:
            checklist.append(("Trend stack aligned (EMA20/50/200)", False))
        for name in ["RSI in continuation zone", "MACD momentum expanding",
                     "Price reacting at Fibonacci golden zone", "Confirmation candle",
                     "Volume expansion on confirmation candle",
                     "Inside London/New York overlap"]:
            checklist.append((f"{name} (N/A — no trend direction)", None))

    grade = grade_from_score(score, max_score)
    return {
        "timestamp": df.index[pos],
        "direction": direction,
        "score": score,
        "max_score": max_score,
        "reasons": reasons,
        "checklist": checklist,
        "fib_zone": (fib_lo, fib_hi),
        "grade": grade,
        "close": last["close"],
        "atr": last["atr14"],
        "swing_high": swing_high,
        "swing_low": swing_low,
        "regime": regime,
        "atr_pctl": atr_pctl,
        "cot_alignment": cot_align,
        "adx": last.get("adx14", None),
        "ob_fvg": ob_fvg_detail,
    }


def grade_from_score(score, max_score):
    pct = score / max_score
    if pct >= 0.83:
        return "A+"
    elif pct >= 0.66:
        return "A"
    elif pct >= 0.5:
        return "B"
    return "NO TRADE"


_GRADE_RANK = {"NO TRADE": 0, "B": 1, "A": 2, "A+": 3}


def grade_meets_minimum(grade, minimum):
    return _GRADE_RANK.get(grade, 0) >= _GRADE_RANK.get(minimum, 99)


def confirm_on_ltf(df_ltf, htf_direction, at=-1, min_confirmations=None):
    """Checks whether the LOWER timeframe confirms the HIGHER timeframe's
    bias before an entry is taken. This is the 'confirm the signal on a
    lower timeframe' step: the HTF says WHAT to trade, this says WHEN.

    Three checks, each pass/fail (not full 6-point — the bias is already
    established, this just times the trigger):
      1. LTF short-term trend (EMA20 vs EMA50) agrees with HTF direction
      2. LTF momentum (RSI zone or MACD histogram) agrees with HTF direction
      3. LTF price action: a strong confirmation candle in HTF direction

    min_confirmations overrides the module default — the scalping
    profile requires all three checks (tighter timing) while the
    day-trading profile passes on any two."""
    n = len(df_ltf)
    pos = at if at >= 0 else n + at
    if pos < 1:
        raise ValueError(f"Not enough LTF bars before position {pos} to confirm.")

    last = df_ltf.iloc[pos]
    ema20, ema50 = float(last["ema20"]), float(last["ema50"])
    rsi14 = float(last["rsi14"])
    hist_now = float(last["macd_hist"])
    hist_prev = float(df_ltf["macd_hist"].iloc[pos - 1])
    o, c, h, l = float(last["open"]), float(last["close"]), float(last["high"]), float(last["low"])

    checks = []

    if htf_direction == "LONG":
        checks.append(("LTF short-term trend agrees (EMA20 > EMA50)", ema20 > ema50))
        checks.append(("LTF momentum agrees (RSI>50 or MACD hist rising)",
                        rsi14 > 50 or hist_now > hist_prev))
        body_ratio = abs(c - o) / max(h - l, 1e-6)
        checks.append(("LTF confirmation candle (strong bullish close)",
                        c > o and body_ratio > 0.5))
    else:  # SHORT
        checks.append(("LTF short-term trend agrees (EMA20 < EMA50)", ema20 < ema50))
        checks.append(("LTF momentum agrees (RSI<50 or MACD hist falling)",
                        rsi14 < 50 or hist_now < hist_prev))
        body_ratio = abs(c - o) / max(h - l, 1e-6)
        checks.append(("LTF confirmation candle (strong bearish close)",
                        c < o and body_ratio > 0.5))

    passed = [name for name, ok in checks if ok]
    failed = [name for name, ok in checks if not ok]
    if min_confirmations is None:
        min_confirmations = MIN_LTF_CONFIRMATIONS
    return {
        "passed": passed,
        "failed": failed,
        "count": len(passed),
        "total": len(checks),
        "confirmed": len(passed) >= min_confirmations,
        "entry_price": c,
        "atr": float(last["atr14"]),
        "timestamp": df_ltf.index[pos],
    }


# --------------------------------------------------------------------------
# 4. TRADE LEVELS (entry / SL / TP1-3 / R:R) — ATR-based risk model
# --------------------------------------------------------------------------
MIN_LOT = 0.01   # typical broker minimum, in standard lots
LOT_STEP = 0.01  # typical broker lot increment


def calculate_position_size(risk_amount, stop_distance_price,
                             contract_size=CONTRACT_SIZE_OZ,
                             min_lot=MIN_LOT, lot_step=LOT_STEP):
    """Converts a dollar risk figure into an actual tradable lot size —
    the step most scanners skip, which is exactly where a small account's
    plan can quietly become unexecutable."""
    if stop_distance_price <= 0:
        return {"lots": 0.0, "viable": False, "raw_lots": 0.0,
                "min_lot_risk_usd": 0.0}
    raw_lots = risk_amount / (stop_distance_price * contract_size)
    lots = math.floor(raw_lots / lot_step) * lot_step
    viable = lots >= min_lot
    min_lot_risk_usd = min_lot * contract_size * stop_distance_price
    return {
        "raw_lots": raw_lots,
        "lots": round(lots, 2) if viable else 0.0,
        "viable": viable,
        "min_lot_risk_usd": round(min_lot_risk_usd, 2),
    }


def build_trade_plan(setup, ltf_confirmation=None, pair_name=None,
                     atr_stop_mult=None, min_rr=None, tp_rr=None,
                     mode="day"):
    if setup["direction"] is None or setup["grade"] == "NO TRADE":
        return None

    direction = setup["direction"]
    pair = _PAIR_BY_NAME.get(pair_name, TRADED_PAIRS[0])

    # If a lower-timeframe confirmation was performed, use ITS entry price
    # and ATR (tighter, better-timed) instead of the higher timeframe's.
    if ltf_confirmation is not None:
        entry = ltf_confirmation["entry_price"]
        atr_val = ltf_confirmation["atr"]
        timestamp = ltf_confirmation["timestamp"]
        reasons = setup["reasons"] + [f"[LTF] {r}" for r in ltf_confirmation["passed"]]
    else:
        entry = setup["close"]
        atr_val = setup["atr"]
        timestamp = setup["timestamp"]
        reasons = setup["reasons"]

    blackout, label = is_news_blackout(timestamp)
    if blackout:
        return None

    # Explicit parameter with sane default. Previously read via
    # globals().get("_SWEEP_ATR_STOP_MULT", 1.5) or 1.5 — the "or 1.5"
    # collapsed any falsy override (including 0.0) to 1.5, which made the
    # parameter sweep's atr_stop_mult axis a no-op.
    if atr_stop_mult is None:
        atr_stop_mult = 1.5
    stop_dist = atr_stop_mult * atr_val

    # R:R ladder. Explicit parameter so the scalping profile
    # (quicker scale-outs) and the parameter sweep can vary it
    # without touching module state. Default = day-trading ladder.
    if tp_rr is None:
        tp_rr = (1.5, 2.5, 4.0)
    rr1, rr2, rr3 = tp_rr

    if direction == "LONG":
        sl = entry - stop_dist
        tp1 = entry + stop_dist * rr1
        tp2 = entry + stop_dist * rr2
        tp3 = entry + stop_dist * rr3
    else:
        sl = entry + stop_dist
        tp1 = entry - stop_dist * rr1
        tp2 = entry - stop_dist * rr2
        tp3 = entry - stop_dist * rr3

    # --- PER-PAIR COST MODEL: spread + slippage in price terms
    atr_pctl = setup.get("atr_pctl", 50.0)
    cost = pair_cost_price(pair_name, atr_pctl)
    effective_risk_dist = stop_dist + cost
    effective_reward_dist_tp1 = max(stop_dist * rr1 - cost, 0)
    net_rr1 = effective_reward_dist_tp1 / effective_risk_dist if effective_risk_dist > 0 else 0

    # Explicit parameter with default from module global so the sweep can
    # override the R:R gate without mutating module state.
    if min_rr is None:
        min_rr = MIN_RR_FOR_SIGNAL
    if net_rr1 < min_rr:
        return None

    risk_pct = volatility_targeted_risk_pct(atr_pctl)
    risk_amount = ACCOUNT_SIZE * (risk_pct / 100)
    position = calculate_position_size(risk_amount, stop_dist,
                                       contract_size=pair["contract_size"])

    # Forex prices need more decimal places (5 decimals for EURUSD etc.)
    decimals = 5 if pair["pip_size"] == 0.0001 else 3

    return {
        "Symbol": pair_name or pair["name"],
        "Mode": mode,
        "Timestamp (UTC)": timestamp,
        "Direction": direction,
        "Grade": setup["grade"],
        "Confluence": f"{setup['score']}/{setup['max_score']}",
        "Entry": round(entry, decimals),
        "Stop Loss": round(sl, decimals),
        "TP1": round(tp1, decimals),
        "TP2": round(tp2, decimals),
        "TP3": round(tp3, decimals),
        "R:R (TP1/TP2/TP3)": f"1:{rr1:g} / 1:{rr2:g} / 1:{rr3:g}",
        "Net R:R (TP1, after costs)": f"1:{net_rr1:.2f}",
        "Risk $ (target)": round(risk_amount, 2),
        "Risk % (vol-targeted)": round(risk_pct, 3),
        "Regime": setup.get("regime", "unknown"),
        "ATR pctl": round(atr_pctl, 1),
        "ADX": round(float(setup.get("adx") or 0), 1),
        "Session": get_trading_session(timestamp) if ENABLE_SESSION_FILTER else "",
        "OB/FVG": setup.get("ob_fvg", ""),
        "Lot Size": position["lots"] if position["viable"] else "N/A (see note)",
        "_position": position,
        "_stop_dist": stop_dist,
        "_cost": cost,
        "_risk_pct": risk_pct,
        "Reasons": "; ".join(reasons),
    }


def print_diagnostics(df, swing_window=20):
    """Always-on indicator snapshot — shown regardless of whether a
    direction/signal was detected, so 'NO TRADE' isn't a black box.

    Uses the SAME trailing-window swing calculation as evaluate_setup so
    the printed swing range matches what was used to score the signal."""
    last = df.iloc[-1]
    pos = len(df) - 1
    ema20, ema50, ema200 = float(last["ema20"]), float(last["ema50"]), float(last["ema200"])
    window_start = max(0, pos - swing_window + 1)
    swing_high, swing_low = swing_levels(df.iloc[window_start:pos + 1], window=swing_window)

    if ema20 > ema50 > ema200:
        stack = "BULLISH stack (EMA20 > EMA50 > EMA200)"
    elif ema20 < ema50 < ema200:
        stack = "BEARISH stack (EMA20 < EMA50 < EMA200)"
    else:
        stack = "NOT ALIGNED (EMAs tangled — likely ranging/consolidating)"

    print("-" * 78)
    print("DIAGNOSTIC SNAPSHOT (why the score is what it is)")
    print("-" * 78)
    print(f"  EMA20:  {ema20:.5f}")
    print(f"  EMA50:  {ema50:.5f}")
    print(f"  EMA200: {ema200:.5f}")
    print(f"  Trend:  {stack}")
    print(f"  RSI14:  {float(last['rsi14']):.1f}")
    print(f"  MACD histogram: {float(last['macd_hist']):.6f}")
    print(f"  ATR14 (used for stop sizing): {float(last['atr14']):.5f}")
    if 'adx14' in last.index:
        print(f"  ADX14 (trend strength): {float(last['adx14']):.1f}")
    print(f"  Recent swing range (trailing {swing_window} bars): {swing_low:.5f} - {swing_high:.5f}")
    print("-" * 78 + "\n")


# --------------------------------------------------------------------------
# 5. LOGGING & RISK CIRCUIT BREAKER
# --------------------------------------------------------------------------
def push_signal_to_supabase(trade):
    """Pushes a signal to the Supabase `signals` table so the web dashboard
    can display it. Uses the REST API (no extra dependencies). Silently
    skips if SUPABASE_URL or SUPABASE_ANON_KEY is not configured."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return
    try:
        import urllib.request
        import json as _json
        payload = {
            "symbol": trade.get("Symbol", "EURUSD"),
            "timestamp_utc": trade.get("Timestamp (UTC)", ""),
            "direction": trade.get("Direction", ""),
            "grade": trade.get("Grade", ""),
            "confluence": trade.get("Confluence", ""),
            "entry": float(trade.get("Entry", 0) or 0),
            "stop_loss": float(trade.get("Stop Loss", 0) or 0),
            "tp1": float(trade.get("TP1", 0) or 0),
            "tp2": float(trade.get("TP2", 0) or 0),
            "tp3": float(trade.get("TP3", 0) or 0),
            "rr": str(trade.get("R:R (TP1/TP2/TP3)", "")),
            "net_rr": float(trade.get("Net R:R (TP1, after costs)", 0) or 0),
            "risk_pct": float(trade.get("Risk % (vol-targeted)", 0) or 0),
            "risk_usd": float(trade.get("Risk $ (target)", 0) or 0),
            "lot_size": float(trade.get("Lot Size", 0) or 0),
            "reasons": trade.get("Reasons", ""),
            "regime": trade.get("Regime", ""),
            "atr_pctl": float(trade.get("ATR pctl", 0) or 0),
            "auto_executed": AUTO_EXECUTE,
            "mode": trade.get("Mode", "day"),
            "adx": float(trade.get("ADX", 0) or 0),
            "session": trade.get("Session", ""),
            "live_spread": float(trade.get("Live Spread", 0) or 0),
            "ob_fvg": trade.get("OB/FVG", ""),
        }
        url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/signals"
        req = urllib.request.Request(
            url,
            data=_json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
                "Prefer": "return=minimal",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        print("[dashboard] Signal pushed to Supabase dashboard.")
    except Exception as e:
        print(f"[dashboard] Could not push to Supabase ({e}). "
              "Signal still logged locally.")


def log_signal(trade, path=None):
    """Appends every produced signal to a CSV so you have an actual record
    to review later — 'what did the scanner say last Tuesday' should be
    answerable, not lost the moment the terminal closes."""
    path = path if path is not None else SIGNAL_LOG_PATH
    row = {k: v for k, v in trade.items() if not k.startswith("_")}
    row["logged_at_utc"] = datetime.now(timezone.utc).isoformat()
    file_exists = os.path.isfile(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
    push_signal_to_supabase(trade)


def log_trade_outcome(timestamp, direction, pnl_usd, path=None):
    """Records a CLOSED trade's realized P&L. This file is what the circuit
    breaker reads — you (or your execution code) append to it when a trade
    actually closes, since the scanner itself doesn't execute orders."""
    path = path if path is not None else TRADE_LOG_PATH
    file_exists = os.path.isfile(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp_utc", "direction", "pnl_usd"])
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "timestamp_utc": pd.Timestamp(timestamp).isoformat(),
            "direction": direction,
            "pnl_usd": pnl_usd,
        })


def check_daily_loss_limit(account_size=None, max_daily_loss_pct=None, path=None):
    """Reads today's logged trade outcomes and blocks new signals once
    realized losses hit the daily cap — a real risk desk practice, and the
    single most common thing that saves small accounts from a bad day
    turning into a blown account."""
    account_size = account_size if account_size is not None else ACCOUNT_SIZE
    max_daily_loss_pct = max_daily_loss_pct if max_daily_loss_pct is not None else MAX_DAILY_LOSS_PCT
    path = path if path is not None else TRADE_LOG_PATH

    if not os.path.isfile(path):
        return {"blocked": False, "today_pnl": 0.0, "limit_usd": None}

    df = pd.read_csv(path)
    if df.empty:
        return {"blocked": False, "today_pnl": 0.0, "limit_usd": None}

    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    today = pd.Timestamp.now(tz="UTC").date()
    today_rows = df[df["timestamp_utc"].dt.date == today]
    today_pnl = today_rows["pnl_usd"].sum()
    limit_usd = -abs(account_size * max_daily_loss_pct / 100)

    return {
        "blocked": today_pnl <= limit_usd,
        "today_pnl": round(float(today_pnl), 2),
        "limit_usd": round(limit_usd, 2),
    }


def check_weekly_loss_limit(account_size=None, max_weekly_loss_pct=None, path=None):
    """Reads this week's logged trade outcomes and blocks new signals once
    realized losses hit the weekly cap."""
    account_size = account_size if account_size is not None else ACCOUNT_SIZE
    max_weekly_loss_pct = max_weekly_loss_pct if max_weekly_loss_pct is not None else MAX_WEEKLY_LOSS_PCT
    path = path if path is not None else TRADE_LOG_PATH
    if not os.path.isfile(path):
        return {"blocked": False, "week_pnl": 0.0, "limit_usd": None}
    df = pd.read_csv(path)
    if df.empty:
        return {"blocked": False, "week_pnl": 0.0, "limit_usd": None}
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    now = pd.Timestamp.now(tz="UTC")
    week_start = (now - pd.Timedelta(days=now.weekday())).normalize()
    week_rows = df[df["timestamp_utc"] >= week_start]
    week_pnl = week_rows["pnl_usd"].sum()
    limit_usd = -abs(account_size * max_weekly_loss_pct / 100)
    return {
        "blocked": week_pnl <= limit_usd,
        "week_pnl": round(float(week_pnl), 2),
        "limit_usd": round(limit_usd, 2),
    }


def check_max_drawdown(account_size=None, max_drawdown_pct=None, path=None):
    """Tracks the equity curve implied by closed-trade P&L and blocks new
    signals once peak-to-trough drawdown exceeds the cap.

    Unlike the daily/weekly loss limits (which only look at today/this-week
    losses), this measures the full equity curve: a strategy can book
    positive daily P&L while still sitting 20% below its all-time high.
    Stopping on drawdown is the standard risk-desk practice for preventing
    a slow bleed from turning into an account blowout.

    Reads the same TRADE_LOG_PATH as the other breakers, so it's real
    (not theoretical) when AUTO_EXECUTE is on, and reflects manually-punched
    outcomes otherwise. Returns {blocked, current_equity, peak_equity,
    drawdown_pct, limit_pct}."""
    account_size = account_size if account_size is not None else ACCOUNT_SIZE
    max_drawdown_pct = max_drawdown_pct if max_drawdown_pct is not None else MAX_DRAWDOWN_PCT
    path = path if path is not None else TRADE_LOG_PATH

    if not os.path.isfile(path):
        return {"blocked": False, "current_equity": account_size,
                "peak_equity": account_size, "drawdown_pct": 0.0,
                "limit_pct": max_drawdown_pct}

    df = pd.read_csv(path)
    if df.empty:
        return {"blocked": False, "current_equity": account_size,
                "peak_equity": account_size, "drawdown_pct": 0.0,
                "limit_pct": max_drawdown_pct}

    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df = df.sort_values("timestamp_utc").reset_index(drop=True)

    # Compounding equity curve from realized P&L.
    equity = [account_size]
    for pnl in df["pnl_usd"]:
        equity.append(equity[-1] + float(pnl))
    current_equity = equity[-1]
    peak_equity = max(equity)
    drawdown_pct = (current_equity - peak_equity) / peak_equity * 100 if peak_equity > 0 else 0.0

    return {
        "blocked": drawdown_pct <= -abs(max_drawdown_pct),
        "current_equity": round(current_equity, 2),
        "peak_equity": round(peak_equity, 2),
        "drawdown_pct": round(drawdown_pct, 2),
        "limit_pct": max_drawdown_pct,
    }


# --------------------------------------------------------------------------
# 6. MAIN
# --------------------------------------------------------------------------
def _scan_pair(pair, profile, dxy_dir=None, from_tabulate=None,
               signals_last_window=0):
    """Scans a single pair end-to-end using the given profile
    (day-trading or scalping). Returns the trade dict if a signal
    was produced, or None. All print output goes to stdout for the
    live loop.

    The profile bundles every parameter that differs between the
    day-trading and scalping engines — timeframes, bar counts,
    grade gates, confirmation strictness, session rules, the R:R
    ladder and the stop distance. Both engines run THIS function,
    so there is one scan pipeline and the two cannot drift apart."""
    tabulate = from_tabulate
    pair_name = pair["name"]
    mode = profile["mode"]
    is_scalp = mode == "scalp"
    print(f"\n{'~' * 78}")
    print(f"  {'SCALP ' if is_scalp else ''}SCANNING {pair_name}")
    print(f"{'~' * 78}")

    # --- STAGE 1: HTF BIAS ---
    htf_iv = profile["htf_interval"]
    print(f"[STAGE 1] {pair_name} — HTF bias ({htf_iv})...")
    df_htf = fetch_data(htf_iv, profile["htf_bars"], pair_name=pair_name)
    print(f"  Data source: {df_htf.attrs.get('source', 'unknown')}")
    print(f"  Bars loaded: {len(df_htf)}")

    if len(df_htf) < 200:
        print(f"  NO TRADE — only {len(df_htf)} HTF bars (need >= 200).\n")
        return None

    df_htf = compute_indicators(df_htf)
    htf_setup = evaluate_setup(df_htf)

    print(f"  Current price: {htf_setup['close']:.5f}")
    print(f"  HTF direction: {htf_setup['direction'] or 'None (no trend alignment)'}")
    print(f"  HTF confluence: {htf_setup['score']}/{htf_setup['max_score']}  ->  Grade: {htf_setup['grade']}")
    print(f"  Regime: {htf_setup.get('regime', 'unknown')}  (ATR pctl: {htf_setup.get('atr_pctl', 0):.1f})")
    for name, ok in htf_setup["checklist"]:
        mark = "N/A " if ok is None else ("PASS" if ok else "FAIL")
        print(f"    [{mark}] {name}")
    print()
    print_diagnostics(df_htf)

    if not grade_meets_minimum(htf_setup["grade"], profile["min_htf_grade"]):
        print(f"  NO TRADE — HTF bias below minimum ({htf_setup['grade']} < {profile['min_htf_grade']}).\n")
        return None

    print(f"  HTF qualifies ({htf_setup['grade']} {htf_setup['direction']}) -> checking LTF.\n")

    # --- STAGE 1.3: SESSION FILTER ---
    session_ok, session_msg = session_allows_signal(
        df_htf.index[-1], required=profile["required_session"])
    print(f"  [STAGE 1.3] Session: {session_msg}")
    if not session_ok:
        print(f"  NO TRADE — {session_msg}.\n")
        return None

    # --- STAGE 1.4: SCALP-ONLY ANTI-OVERTRADING CAP --------
    # Scalpers are most exposed to churning out marginal
    # fills. Once the rolling session window has produced
    # SCALP_MAX_SIGNALS_PER_SESSION signals, the engine
    # refuses to signal again until the window rolls.
    if is_scalp and signals_last_window >= SCALP_MAX_SIGNALS_PER_SESSION:
        print(f"  NO TRADE — overtrading cap: {signals_last_window} signal(s) "
              f"already logged in the last {SCALP_SIGNAL_WINDOW_HOURS}h "
              f"(cap {SCALP_MAX_SIGNALS_PER_SESSION}).\n")
        return None

    # --- STAGE 1.5: DXY GATE (per-pair) ---
    if ENABLE_DXY_GATE and dxy_dir is not None:
        blocked, reason = dxy_gate_against_pair(pair_name, htf_setup["direction"], dxy_dir)
        print(f"  [STAGE 1.5] DXY: {reason}")
        if blocked:
            print(f"  NO TRADE — {reason}\n")
            return None

    # --- STAGE 2: LTF CONFIRMATION ---
    ltf_iv = profile["ltf_interval"]
    print(f"  [STAGE 2] {pair_name} — LTF confirmation ({ltf_iv})...")
    df_ltf = fetch_data(ltf_iv, profile["ltf_bars"], pair_name=pair_name)
    print(f"  Data source: {df_ltf.attrs.get('source', 'unknown')}")
    print(f"  Bars loaded: {len(df_ltf)}")

    if len(df_ltf) < 200:
        print(f"  NO TRADE — only {len(df_ltf)} LTF bars (need >= 200).\n")
        return None

    df_ltf = compute_indicators(df_ltf)

    # --- STAGE 2.1: SCALP-ONLY SPREAD VIABILITY FILTER -----
    # Scalp targets are small (a 1x ATR stop with 1.5-3R
    # scale-outs). If the 1m ATR is not comfortably larger
    # than the spread, transaction costs dominate the noise
    # floor and NO scalp setup is tradable — day trades hold
    # for hours and shrug off a wide spread, a scalp cannot.
    if is_scalp:
        atr_pips = float(df_ltf["atr14"].iloc[-1]) / pair["pip_size"]
        spread_pips = pair["typical_spread_pips"]
        if atr_pips < SCALP_MIN_ATR_TO_SPREAD * spread_pips:
            print(f"  NO TRADE — scalp spread filter: 1m ATR is {atr_pips:.1f} "
                  f"pips, below the {SCALP_MIN_ATR_TO_SPREAD}x-spread "
                  f"viability floor ({SCALP_MIN_ATR_TO_SPREAD * spread_pips:.1f} "
                  f"pips). Costs dominate at this volatility.\n")
            return None
        print(f"  [STAGE 2.1] Spread viability: 1m ATR {atr_pips:.1f} pips "
              f">= {SCALP_MIN_ATR_TO_SPREAD}x spread ({spread_pips} pips) — OK")

    ltf_conf = confirm_on_ltf(df_ltf, htf_setup["direction"],
                               min_confirmations=profile["min_ltf_confirmations"])

    print(f"  LTF checks passed: {ltf_conf['count']}/{ltf_conf['total']}")
    for r in ltf_conf["passed"]:
        print(f"    [PASS] {r}")
    for r in ltf_conf["failed"]:
        print(f"    [FAIL] {r}")

    if not ltf_conf["confirmed"]:
        print(f"  NO TRADE — LTF not confirmed (need >= {profile['min_ltf_confirmations']}/{ltf_conf['total']}).\n")
        return None

    # --- STAGE 2.5: NEWS BLACKOUT ---
    blackout, label = is_news_blackout(ltf_conf["timestamp"])
    if blackout:
        print(f"  NO TRADE — news blackout ({label}).\n")
        return None

    # --- STAGE 3: TRADE PLAN ---
    trade = build_trade_plan(
        htf_setup, ltf_conf, pair_name=pair_name,
        atr_stop_mult=profile["atr_stop_mult"],
        min_rr=profile["min_rr"],
        tp_rr=profile["tp_rr"],
        mode=mode
    )
    if trade is None:
        print(f"  NO TRADE — {pair_name} didn't clear NET R:R filter after costs.\n")
        return None

    print()
    print("=" * 78)
    tag = "SCALP " if is_scalp else ""
    print(f"  CONFIRMED {tag}SIGNAL: {pair_name} — {trade['Direction']} {trade['Grade']} "
          f"({trade['Confluence']})")
    print("=" * 78)
    display_cols = ["Symbol", "Mode", "Direction", "Grade", "Confluence",
                     "Regime", "ATR pctl", "ADX", "Session",
                     "Entry", "Stop Loss", "TP1", "TP2", "TP3",
                     "R:R (TP1/TP2/TP3)", "Net R:R (TP1, after costs)",
                     "Risk % (vol-targeted)", "Risk $ (target)", "Lot Size"]
    table = pd.DataFrame([trade])
    print(tabulate(table[display_cols], headers="keys", tablefmt="fancy_grid",
                    showindex=False, floatfmt=".5f"))
    print(f"\n  Reasoning: {trade['Reasons']}\n")

    position = trade["_position"]
    if not position["viable"]:
        print(f"  POSITION WARNING: lot below minimum ({MIN_LOT}). "
              f"Min-lot risk = ${position['min_lot_risk_usd']} "
              f"({position['min_lot_risk_usd'] / ACCOUNT_SIZE * 100:.1f}% of account).")

    log_signal(trade)
    print(f"  Signal logged to {SIGNAL_LOG_PATH}")

    if AUTO_EXECUTE:
        auto_execute_order(trade)

    alert_msg = (
        f"FOREX {tag}SIGNAL: {pair_name} {trade['Direction']} {trade['Grade']} "
        f"({trade['Confluence']})\n"
        f"Entry {trade['Entry']} | SL {trade['Stop Loss']} | "
        f"TP1 {trade['TP1']} / TP2 {trade['TP2']} / TP3 {trade['TP3']}\n"
        f"Net R:R {trade['Net R:R (TP1, after costs)']} | "
        f"Lot {trade['Lot Size']}"
    )
    send_telegram_alert(alert_msg)
    print("-" * 78)
    return trade


# --- PROFILE DEFINITIONS (single source of truth) -------------
# Placed here so all referenced constants (MAX_HOLD_BARS, etc.) are defined.
DAY_PROFILE = {
    "mode": "day",
    "htf_interval": HTF_INTERVAL,
    "ltf_interval": LTF_INTERVAL,
    "htf_bars": HTF_BARS,
    "ltf_bars": LTF_BARS,
    "min_htf_grade": MIN_HTF_GRADE,
    "min_ltf_confirmations": MIN_LTF_CONFIRMATIONS,
    "atr_stop_mult": 1.5,
    "min_rr": MIN_RR_FOR_SIGNAL,
    "tp_rr": (1.5, 2.5, 4.0),
    "required_session": REQUIRED_SESSION,
    "max_hold_bars": 200,  # ~50 hours on M15
}

SCALP_PROFILE = {
    "mode": "scalp",
    "htf_interval": SCALP_HTF_INTERVAL,
    "ltf_interval": SCALP_LTF_INTERVAL,
    "htf_bars": SCALP_HTF_BARS,
    "ltf_bars": SCALP_LTF_BARS,
    "min_htf_grade": SCALP_MIN_HTF_GRADE,
    "min_ltf_confirmations": SCALP_MIN_LTF_CONFIRMATIONS,
    "atr_stop_mult": SCALP_ATR_STOP_MULT,
    "min_rr": SCALP_MIN_RR,
    "tp_rr": (SCALP_TP1_RR, SCALP_TP2_RR, SCALP_TP3_RR),
    "required_session": REQUIRED_SESSION,  # same session filter
    "max_hold_bars": SCALP_MAX_HOLD_BARS,
}


def run_scanner():
    from tabulate import tabulate
    print("=" * 78)
    print(" PROFESSIONAL FOREX DAY-TRADING SCANNER (Multi-Pair)")
    print(f" Pairs: {', '.join(p['name'] for p in TRADED_PAIRS)}")
    print(f" HTF={HTF_INTERVAL}  LTF={LTF_INTERVAL}  Data: {DATA_SOURCE}")
    print("=" * 78)

    # --- STAGE 0: RISK CIRCUIT BREAKERS ---
    if AUTO_EXECUTE:
        synced = sync_trade_outcomes_from_mt5()
        if synced:
            print(f"[auto-execute] Synced {synced} closed trade(s) from MT5.")
    breaker = check_daily_loss_limit()
    if breaker["blocked"]:
        print(f"\n[STOPPED] Daily loss limit reached: ${breaker['today_pnl']} "
              f"(limit ${breaker['limit_usd']}). No new signals until tomorrow.\n")
        return
    if breaker["limit_usd"] is not None:
        print(f"Daily P&L: ${breaker['today_pnl']} (breaker at ${breaker['limit_usd']})")

    weekly_breaker = check_weekly_loss_limit()
    if weekly_breaker["blocked"]:
        print(f"\n[STOPPED] Weekly loss limit reached: ${weekly_breaker['week_pnl']} "
              f"(limit ${weekly_breaker['limit_usd']}).\n")
        return
    if weekly_breaker["limit_usd"] is not None:
        print(f"Weekly P&L: ${weekly_breaker['week_pnl']} (breaker at ${weekly_breaker['limit_usd']})\n")

    # Maximum-drawdown breaker: tracks the full equity curve, not just
    # today/this-week losses. A strategy can book positive daily P&L while
    # still sitting far below its peak — this stops the slow bleed.
    dd_breaker = check_max_drawdown()
    if dd_breaker["blocked"]:
        print(f"\n[STOPPED] Max drawdown reached: "
              f"{dd_breaker['drawdown_pct']}% (peak ${dd_breaker['peak_equity']} -> "
              f"${dd_breaker['current_equity']}, limit {dd_breaker['limit_pct']}%). "
              f"No new signals until drawdown recovers.\n")
        return
    print(f"Drawdown: {dd_breaker['drawdown_pct']}% "
          f"(peak ${dd_breaker['peak_equity']}, current ${dd_breaker['current_equity']}, "
          f"limit {dd_breaker['limit_pct']}%)")

    # --- Fetch DXY once (shared across all USD-quoted pairs) ---
    dxy_dir = None
    if ENABLE_DXY_GATE:
        print(f"[GATE] DXY correlation gate ({DXY_YF_SYMBOL})...")
        dxy_df = fetch_dxy()
        dxy_dir = dxy_break_direction(dxy_df)
        if dxy_dir is None:
            print("  DXY unavailable — gate will FAIL OPEN per pair.")
        else:
            print(f"  DXY trend (last {DXY_TREND_BARS} bars): {dxy_dir}")
        print()

    # --- SCAN EACH PAIR (DAY + SCALP) ---
    total_signals = 0
    open_directions = {}  # pair_name -> direction, for cross-pair correlation guard

    # Pre-count scalp signals for the anti-overtrading cap
    scalp_signals_recent = _count_scalp_signals_recent()

    for profile in (DAY_PROFILE, SCALP_PROFILE):
        profile_tag = "SCALP" if profile["mode"] == "scalp" else "DAY"
        print(f"\n{'=' * 78}")
        print(f"  {profile_tag} ENGINE — {profile['htf_interval']} bias / {profile['ltf_interval']} entry")
        print(f"{'=' * 78}")

        for pair in TRADED_PAIRS:
            # --- MAX CONCURRENT POSITIONS GUARD -------------------------------
            if total_signals >= MAX_CONCURRENT_POSITIONS:
                print(f"\n[GUARD] Max concurrent positions ({MAX_CONCURRENT_POSITIONS}) "
                      f"reached — skipping remaining pairs this scan.")
                break

            # --- CROSS-PAIR CORRELATION GUARD --------------------------------
            try:
                signals_last_window = scalp_signals_recent if profile["mode"] == "scalp" else 0
                trade = _scan_pair(
                    pair, profile, dxy_dir=dxy_dir, from_tabulate=tabulate,
                    signals_last_window=signals_last_window)
                if trade is not None:
                    direction = trade["Direction"]
                    # Check against already-accepted signals this cycle.
                    for other_pair, other_dir in open_directions.items():
                        if direction == other_dir:
                            print(f"\n[GUARD] Cross-pair correlation: {pair['name']} "
                                  f"{direction} duplicates {other_pair} {other_dir} "
                                  f"(both are the same dollar bet). Skipping.")
                            trade = None
                            break
                    if trade is not None:
                        open_directions[pair["name"]] = direction
                        total_signals += 1
                        if profile["mode"] == "scalp":
                            scalp_signals_recent += 1
            except Exception as e:
                print(f"\n[!] {pair['name']} {profile_tag} scan failed ({e})")
                _invalidate_mt5_symbol_cache()

    print(f"\n{'=' * 78}")
    print(f"  SCAN COMPLETE — {total_signals} signal(s) across {len(TRADED_PAIRS)} pairs (day + scalp)")
    print(f"{'=' * 78}\n")


# --------------------------------------------------------------------------
# 7. BACKTESTING ENGINE
# --------------------------------------------------------------------------
# This is the single most important addition: every rule above (RSI zone,
# fib golden zone, ATR x1.5 stop, session window...) is a reasonable
# heuristic borrowed from common practice, but NONE of it had been tested
# against real history before this. A strategy with zero backtest has an
# unknown edge — possibly negative once spread/slippage are included.
#
# This walks LTF bars chronologically, looks up the most recently CLOSED
# HTF bar at each point (no lookahead), and replays the exact same
# evaluate_setup / confirm_on_ltf / build_trade_plan logic used live —
# one scoring engine for both live and backtest, so they can't drift apart.
#
# EXIT MODEL: the live plan scales out 1/3 at TP1, 1/3 at TP2, 1/3 at TP3
# (remainder), moving the stop to BREAKEVEN+cost once TP1 is hit. The
# backtest now simulates those partials so it measures the SAME strategy
# the live signal advertises. Cost is applied per partial exit (spread is
# paid on each closed portion), and breakeven is entry+cost so a
# "breakeven" exit is actually net-breakeven, not a small loss.
MAX_HOLD_BARS = 200  # ~50 hours on M15 — give a trade room to develop, but
                      # force a time-based exit rather than hold forever


def backtest(df_htf_raw, df_ltf_raw, max_hold_bars=MAX_HOLD_BARS,
             account_size=ACCOUNT_SIZE, verbose=False,
             atr_stop_mult=None, min_htf_grade=None, min_rr=None,
             tp_rr=None, min_ltf_confirmations=None, required_session=None,
             profile=None, pair_name=None):
    """Runs the exact same evaluate_setup / confirm_on_ltf / build_trade_plan
    logic used live, replayed bar-by-bar with no lookahead.

    `profile` can be DAY_PROFILE or SCALP_PROFILE to use the exact same
    parameters as the live engine. If provided, it overrides the individual
    parameters. `pair_name` is needed for the scalp spread-viability filter."""

    # Profile takes precedence over individual params.
    if profile is not None:
        atr_stop_mult = profile["atr_stop_mult"]
        min_htf_grade = profile["min_htf_grade"]
        min_rr = profile["min_rr"]
        tp_rr = profile["tp_rr"]
        min_ltf_confirmations = profile["min_ltf_confirmations"]
        required_session = profile["required_session"]
        max_hold_bars = profile["max_hold_bars"]
        is_scalp = profile["mode"] == "scalp"
    else:
        is_scalp = False
        if atr_stop_mult is None:
            atr_stop_mult = 1.5
        if min_htf_grade is None:
            min_htf_grade = MIN_HTF_GRADE
        if min_rr is None:
            min_rr = MIN_RR_FOR_SIGNAL
        if tp_rr is None:
            tp_rr = (1.5, 2.5, 4.0)
        if min_ltf_confirmations is None:
            min_ltf_confirmations = MIN_LTF_CONFIRMATIONS
        if required_session is None:
            required_session = REQUIRED_SESSION

    df_htf = compute_indicators(df_htf_raw)
    df_ltf = compute_indicators(df_ltf_raw)
    htf_index = df_htf.index

    trades = []
    i = 210  # need ~200 bars warmed up for EMA200 to be meaningful, +buffer
    n = len(df_ltf)

    while i < n:
        ltf_ts = df_ltf.index[i]

        # Find the most recent HTF bar that had already CLOSED at this LTF
        # timestamp — this is the no-lookahead guarantee.
        htf_pos = htf_index.searchsorted(ltf_ts, side="right") - 1
        if htf_pos < 210:
            i += 1
            continue

        htf_setup = evaluate_setup(df_htf, at=htf_pos)
        if not grade_meets_minimum(htf_setup["grade"], min_htf_grade):
            i += 1
            continue

        if ENABLE_SESSION_FILTER:
            session_ok, _ = session_allows_signal(df_htf.index[htf_pos],
                                                   required=required_session)
            if not session_ok:
                i += 1
                continue

        ltf_conf = confirm_on_ltf(df_ltf, htf_setup["direction"], at=i,
                                   min_confirmations=min_ltf_confirmations)
        if not ltf_conf["confirmed"]:
            i += 1
            continue

        # --- SCALP-ONLY SPREAD VIABILITY FILTER (backtest mirror) ---
        # In the live scan, we reject scalp setups where 1m ATR <
        # SCALP_MIN_ATR_TO_SPREAD * spread. The backtest must do the
        # same, otherwise it will print scalps that the live engine
        # would never fire (false positive track record).
        if is_scalp and pair_name is not None:
            pair = _PAIR_BY_NAME.get(pair_name)
            if pair:
                atr_pips = float(df_ltf["atr14"].iloc[i]) / pair["pip_size"]
                spread_pips = pair["typical_spread_pips"]
                if atr_pips < SCALP_MIN_ATR_TO_SPREAD * spread_pips:
                    i += 1
                    continue

        blackout, _ = is_news_blackout(ltf_conf["timestamp"])
        if blackout:
            i += 1
            continue

        trade = build_trade_plan(htf_setup, ltf_conf,
                                 atr_stop_mult=atr_stop_mult,
                                 min_rr=min_rr,
                                 tp_rr=tp_rr)
        if trade is None:
            i += 1
            continue

        # --- Determine ACTUAL position size for this account ----------------
        # The live scanner warns when 1% risk is unachievable at min-lot.
        # The backtest must reflect what would actually be traded: if the
        # ideal size is below min-lot, the broker forces min-lot, which
        # risks MORE than 1% — so we simulate at that real risk %. If even
        # min-lot is somehow unachievable (raw_lots == 0), skip the trade
        # (it could not have been taken).
        direction = trade["Direction"]
        entry = trade["Entry"]
        sl = trade["Stop Loss"]
        tp1, tp2, tp3 = trade["TP1"], trade["TP2"], trade["TP3"]
        stop_dist = trade["_stop_dist"]
        cost = trade["_cost"]
        position = trade["_position"]

        if not position["viable"]:
            if position["raw_lots"] <= 0:
                # No risk budget at all for this stop distance — untradable.
                i += 1
                continue
            # Broker forces min lot -> actual risk % is higher than target.
            actual_risk_pct = position["min_lot_risk_usd"] / account_size * 100
        else:
            # Vol-targeted risk % from the setup's regime classification.
            actual_risk_pct = trade.get("_risk_pct", RISK_PER_TRADE_PCT)

        # --- Simulate the trade forward with LADDERED exits -----------------
        # State: which partials have been filled, and the current (trailed)
        # stop for the remaining runner.
        filled = {"tp1": False, "tp2": False}
        # Breakeven stop = entry + cost (long) / entry - cost (short), so a
        # breakeven fill is actually net-breakeven once cost is subtracted.
        if direction == "LONG":
            be_stop = entry + cost
        else:
            be_stop = entry - cost
        current_stop = sl
        exit_price = None
        exit_reason = "TIME_EXIT"
        exit_i = min(i + max_hold_bars, n - 1)
        # Weighted average exit price across partials (in price terms, before
        # cost). Each partial's contribution is its fraction * its fill price.
        weighted_exit = 0.0
        fractions_used = 0.0

        for j in range(i + 1, min(i + 1 + max_hold_bars, n)):
            bar = df_ltf.iloc[j]
            hi, lo = float(bar["high"]), float(bar["low"])

            if direction == "LONG":
                stop_touched = lo <= current_stop
                tp3_touched = hi >= tp3
                tp2_touched = hi >= tp2
                tp1_touched = hi >= tp1
            else:
                stop_touched = hi >= current_stop
                tp3_touched = lo <= tp3
                tp2_touched = lo <= tp2
                tp1_touched = lo <= tp1

            # Conservative convention: if both a stop and a target are
            # touched in the same bar, assume the STOP hit first (avoids
            # overoptimistic backtests — standard practice without tick
            # data). This closes ALL remaining partials at the stop.
            if stop_touched:
                stop_fill = current_stop
                # Close any unfilled partials at the stop.
                remaining = 1.0 - fractions_used
                if remaining > 0:
                    weighted_exit += remaining * stop_fill
                    fractions_used += remaining
                exit_price = stop_fill
                exit_reason = "BREAKEVEN" if filled["tp1"] else "STOP_LOSS"
                exit_i = j
                break

            # TP3 closes the remainder (runner).
            if tp3_touched:
                remaining = 1.0 - fractions_used
                if remaining > 0:
                    weighted_exit += remaining * tp3
                    fractions_used += remaining
                exit_price = tp3
                exit_reason = "TP3"
                exit_i = j
                break

            # TP2 closes the next third (if still unfilled).
            if tp2_touched and not filled["tp2"]:
                weighted_exit += TP2_FRACTION * tp2
                fractions_used += TP2_FRACTION
                filled["tp2"] = True

            # TP1 closes the first third and moves stop to breakeven+cost.
            if tp1_touched and not filled["tp1"]:
                weighted_exit += TP1_FRACTION * tp1
                fractions_used += TP1_FRACTION
                filled["tp1"] = True
                current_stop = be_stop  # trail to breakeven+cost

            # --- TRAILING STOP for the runner (after TP2 fills) -----------
            # Once TP2 has taken the second third, the remaining runner
            # trails by the configured method (ATR or EMA20) instead of
            # sitting at breakeven forever — this is what lets winners run
            # instead of giving back the whole move on a reversal. The trail
            # only ever tightens (compute_trailing_stop enforces monotonic
            # favorable movement), so risk never widens after TP2.
            if filled["tp2"] and TRAIL_METHOD != "none":
                atr_at_bar = float(df_ltf["atr14"].iloc[j])
                current_stop = compute_trailing_stop(
                    direction, entry, current_stop, bar, atr_at_bar)

        if fractions_used == 0.0:
            # No partial filled and time expired -> exit at close.
            exit_price = float(df_ltf.iloc[exit_i]["close"])
            exit_reason = "TIME_EXIT"
            remaining = 1.0
            weighted_exit = remaining * exit_price
            fractions_used = remaining
        elif exit_reason == "TIME_EXIT":
            # Some partials filled, remainder closed at time exit.
            exit_price = float(df_ltf.iloc[exit_i]["close"])
            remaining = 1.0 - fractions_used
            if remaining > 1e-9:
                weighted_exit += remaining * exit_price
                fractions_used += remaining

        # Blended net R-multiple across partials. weighted_exit is the
        # fraction-weighted average fill price; gross R is computed from it.
        # Cost is paid once per unit closed (each unit pays one round-trip
        # cost regardless of partialing), so cost in R-terms = cost/stop_dist.
        cost_r = (cost / stop_dist) if stop_dist > 0 else 0.0
        if direction == "LONG":
            gross_r_weighted = (weighted_exit - entry) / stop_dist if stop_dist > 0 else 0.0
        else:
            gross_r_weighted = (entry - weighted_exit) / stop_dist if stop_dist > 0 else 0.0
        net_r_weighted = gross_r_weighted - cost_r  # cost applied once per unit closed
        # pct return on the account = net R * actual_risk_pct actually risked
        pct_return = net_r_weighted * actual_risk_pct

        trades.append({
            "entry_time": ltf_conf["timestamp"],
            "exit_time": df_ltf.index[exit_i],
            "direction": direction,
            "grade": trade["Grade"],
            "entry": entry,
            "exit": round(exit_price, 2),
            "exit_reason": exit_reason,
            "r_multiple": round(net_r_weighted, 3),
            "pct_return": round(pct_return, 4),
            "actual_risk_pct": round(actual_risk_pct, 4),
            "position_viable": position["viable"],
            "lots": position["lots"] if position["viable"] else MIN_LOT,
        })

        if verbose:
            print(f"  [{ltf_conf['timestamp']}] {direction} {trade['Grade']} "
                  f"-> {exit_reason} @ {net_r_weighted:.2f}R "
                  f"(risk {actual_risk_pct:.2f}%)")

        i = exit_i + 1  # no overlapping trades — one position at a time

    return pd.DataFrame(trades)


def compute_backtest_stats(trades_df, account_size=ACCOUNT_SIZE):
    if trades_df.empty:
        return {"total_trades": 0}

    # Wins are strictly positive R; breakeven (r=0) is NEUTRAL, not a loss.
    wins = trades_df[trades_df["r_multiple"] > 0]
    losses = trades_df[trades_df["r_multiple"] < 0]
    neutral = trades_df[trades_df["r_multiple"] == 0]
    decided = len(wins) + len(losses)
    win_rate = (len(wins) / decided * 100) if decided > 0 else 0.0
    avg_win_r = wins["r_multiple"].mean() if len(wins) else 0.0
    avg_loss_r = losses["r_multiple"].mean() if len(losses) else 0.0
    expectancy_r = trades_df["r_multiple"].mean()

    gross_win = wins["r_multiple"].sum()
    gross_loss = abs(losses["r_multiple"].sum())
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    # Equity curve from compounding pct returns (actual risk % per trade,
    # which may exceed RISK_PER_TRADE_PCT when min-lot forces over-risking).
    equity = [account_size]
    for pct in trades_df["pct_return"]:
        equity.append(equity[-1] * (1 + pct / 100))
    equity = pd.Series(equity)
    running_max = equity.cummax()
    drawdown_pct = (equity - running_max) / running_max * 100
    max_drawdown_pct = drawdown_pct.min()

    # Count how many trades were taken at forced min-lot (over-risk).
    forced_overrisk = int((~trades_df["position_viable"]).sum()) \
        if "position_viable" in trades_df.columns else 0

    return {
        "total_trades": len(trades_df),
        "wins": len(wins),
        "losses": len(losses),
        "neutral_breakeven": len(neutral),
        "win_rate_pct": round(win_rate, 1),
        "avg_win_r": round(avg_win_r, 2),
        "avg_loss_r": round(avg_loss_r, 2),
        "expectancy_r": round(expectancy_r, 3),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "inf",
        "final_equity": round(equity.iloc[-1], 2),
        "total_return_pct": round((equity.iloc[-1] / account_size - 1) * 100, 1),
        "max_drawdown_pct": round(max_drawdown_pct, 1),
        "forced_minlot_trades": forced_overrisk,
    }


def monte_carlo_drawdown(trades_df, account_size=ACCOUNT_SIZE, n_sims=1000, seed=42):
    """Reshuffles the trade sequence N times to separate 'this strategy has
    edge' from 'this particular ordering of wins/losses got lucky'. Reports
    the distribution of DRAWDOWNS, not final equity — under compounding,
    final equity is order-invariant (same trades, same product), so only
    the PATH (drawdown) actually varies by shuffle. That path risk is what
    this simulation measures: could a bad-luck ordering of the same edge
    have wiped the account along the way?"""
    if trades_df.empty or len(trades_df) < 5:
        return None

    rng = np.random.default_rng(seed)
    pct_returns = trades_df["pct_return"].values
    max_drawdowns = []

    for _ in range(n_sims):
        shuffled = rng.permutation(pct_returns)
        equity = [account_size]
        for pct in shuffled:
            equity.append(equity[-1] * (1 + pct / 100))
        equity = pd.Series(equity)
        running_max = equity.cummax()
        dd = ((equity - running_max) / running_max * 100).min()
        max_drawdowns.append(dd)

    max_drawdowns = np.array(max_drawdowns)

    return {
        "n_sims": n_sims,
        "median_max_drawdown_pct": round(float(np.median(max_drawdowns)), 1),
        "p10_max_drawdown_pct": round(float(np.percentile(max_drawdowns, 10)), 1),
        "worst_case_drawdown_pct": round(float(np.percentile(max_drawdowns, 5)), 1),
        "best_case_drawdown_pct": round(float(np.percentile(max_drawdowns, 95)), 1),
    }


def run_backtest():
    """Pulls a large historical window for EACH traded pair and evaluates
    the strategy's actual track record across the full live universe.

    The live scanner iterates over all TRADED_PAIRS, but the old backtest
    called fetch_data() with no pair_name and fell back to the legacy
    single-symbol (EURUSD) path — so 2/3 of the live universe was never
    validated. This version backtests every pair separately and aggregates
    the results, so the numbers reflect what the live scanner actually
    scans. Run this BEFORE trusting any live signal from this tool."""
    print("=" * 78)
    print(" BACKTEST — evaluating the strategy against real history")
    print("=" * 78)
    print("This can take a moment depending on data source and history length.\n")

    all_trades = []
    per_pair_stats = {}

    for pair in TRADED_PAIRS:
        pair_name = pair["name"]
        print(f"\n{'~' * 78}")
        print(f"  BACKTESTING {pair_name}")
        print(f"{'~' * 78}")
        df_htf = fetch_data(HTF_INTERVAL, max(HTF_BARS, 2000), pair_name=pair_name)
        df_ltf = fetch_data(LTF_INTERVAL, max(LTF_BARS, 6000), pair_name=pair_name)
        print(f"  HTF bars: {len(df_htf)} ({df_htf.attrs.get('source')})")
        print(f"  LTF bars: {len(df_ltf)} ({df_ltf.attrs.get('source')})")

        if len(df_htf) < 250 or len(df_ltf) < 250:
            print(f"  Not enough history for {pair_name} — skipping.")
            per_pair_stats[pair_name] = {"total_trades": 0}
            continue

        trades = backtest(df_htf, df_ltf)
        stats = compute_backtest_stats(trades)
        per_pair_stats[pair_name] = stats
        print(f"  {pair_name}: {stats.get('total_trades', 0)} trades, "
              f"E={stats.get('expectancy_r', 0)}R, "
              f"WR={stats.get('win_rate_pct', 0)}%, "
              f"PF={stats.get('profit_factor', 0)}, "
              f"MaxDD={stats.get('max_drawdown_pct', 0)}%")
        if not trades.empty:
            trades["pair"] = pair_name
            all_trades.append(trades)

    if not all_trades:
        print("\nZERO trades triggered across all pairs over this history. Either "
              "the history is too short/choppy, or the confluence filter is too "
              "strict for these conditions. This is itself useful information — "
              "don't assume a scanner with zero backtested trades has edge.")
        return

    combined = pd.concat(all_trades, ignore_index=True)
    stats = compute_backtest_stats(combined)

    print("\n" + "=" * 78)
    print(" COMBINED PERFORMANCE (all pairs, net of spread+slippage, laddered exits)")
    print("=" * 78)
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print("\n  Per-pair breakdown:")
    for pair_name, ps in per_pair_stats.items():
        print(f"    {pair_name}: {ps.get('total_trades', 0)} trades, "
              f"E={ps.get('expectancy_r', 0)}R, "
              f"WR={ps.get('win_rate_pct', 0)}%, "
              f"PF={ps.get('profit_factor', 0)}")

    mc = monte_carlo_drawdown(combined)
    if mc:
        print("\n" + "-" * 78)
        print(f"DRAWDOWN MONTE CARLO ({mc['n_sims']} reshuffled sequences of the same trades)")
        print("-" * 78)
        print(f"  Median max drawdown:  {mc['median_max_drawdown_pct']}%")
        print(f"  10th-pct max drawdown: {mc['p10_max_drawdown_pct']}%")
        print(f"  5th-pct (worst-case) max drawdown: {mc['worst_case_drawdown_pct']}%")
        print(f"  95th-pct (best-case) max drawdown: {mc['best_case_drawdown_pct']}%")
        print(f"  Note: under compounding, final equity is the SAME for every")
        print(f"  shuffle (same trades, same product). What varies by order is")
        print(f"  the PATH — i.e. drawdown. This simulation tests whether a")
        print(f"  bad-luck ordering of the same edge could have wiped the")
        print(f"  account along the way, even though the end result is fixed.")

    if stats.get("forced_minlot_trades", 0) > 0:
        print("\n" + "-" * 78)
        print(f"POSITION-SIZE WARNING: {stats['forced_minlot_trades']} of "
              f"{stats['total_trades']} trades were taken at the broker's "
              f"minimum lot because the ideal 1%-risk size was below min-lot. "
              f"These trades risked MORE than {RISK_PER_TRADE_PCT}% of the "
              f"account (see actual_risk_pct column in backtest_trades.csv). "
              f"The equity curve reflects this real (higher) risk. On a "
              f"larger account these would have been sized normally.")
        print("-" * 78)

    print("\n" + "-" * 78)
    print("HONEST CAVEATS:")
    print("  - This covers ALL traded pairs, ONE cost assumption per pair,")
    print("    ONE parameter set.")
    print("  - Past performance on this window is not a guarantee of future")
    print("    performance — markets change regime.")
    print("  - A short/thin history (few hundred bars) gives a noisy read;")
    print("    treat results from under ~50 trades with real skepticism.")
    print("-" * 78)

    combined.to_csv("backtest_trades.csv", index=False)
    print("\nFull trade-by-trade results saved to backtest_trades.csv")


# --------------------------------------------------------------------------
# 7b. WALK-FORWARD + PARAMETER-SENSITIVITY GRID
# --------------------------------------------------------------------------
# The original backtest tests ONE parameter set over ONE contiguous window.
# That hides two failure modes this section exposes:
#   1. IN-SAMPLE OVERFIT — a single parameter set that looks great but only
#      because it was chosen with hindsight. Walk-forward splits history
#      into train/test folds and reports OUT-OF-SAMPLE performance.
#   2. PARAMETER FRAGILITY — if expectancy collapses when RSI shifts from
#      45-68 to 44-69, the edge is an artifact of the exact threshold, not
#      a real market inefficiency. The sweep grid varies the key
#      heuristics and reports which carry edge vs which are overfit.
#
# Both run the SAME backtest() engine — no separate scoring path to drift.

# Parameter grid for the sensitivity sweep. Each axis is a list of candidate
# values; the sweep evaluates the cartesian product. Kept deliberately small
# so a sweep finishes in minutes on yfinance data, not hours.
SWEEP_GRID = {
    "min_htf_grade": ["A+", "A", "B"],
    "min_rr": [1.0, 1.2, 1.5],
    "atr_stop_mult": [1.0, 1.5, 2.0],  # the 1.5x ATR stop distance
}

# Scalping sweep grid — separate profile, faster timeframes, tighter stops.
# Runs the SCALP_PROFILE with overrides on the key scalping levers.
SCALP_SWEEP_GRID = {
    "min_htf_grade": ["A+", "A"],
    "min_rr": [0.5, 0.7, 1.0],
    "atr_stop_mult": [0.8, 1.0, 1.2],
    "tp_rr": [
        (1.5, 2.0, 3.0),
        (1.5, 2.5, 3.5),
        (2.0, 3.0, 4.0),
    ],
}


def _backtest_with_params(df_htf, df_ltf, min_htf_grade, min_rr, atr_stop_mult,
                          tp_rr=None, min_ltf_confirmations=None, required_session=None,
                          profile=None, pair_name=None):
    """Runs backtest() with the given parameter overrides passed explicitly
    as arguments. No module-global mutation — the old approach of setting
    gs._SWEEP_ATR_STOP_MULT and reading it back via globals().get(..., 1.5)
    or 1.5 silently collapsed any falsy override (including 0.0) to 1.5,
    which made the sweep's atr_stop_mult axis a no-op and produced identical
    stats for every grid cell.

    If `profile` is provided (DAY_PROFILE or SCALP_PROFILE), it takes
    precedence over individual parameters.

    Returns the stats dict (or {total_trades: 0})."""
    trades = backtest(df_htf, df_ltf,
                      atr_stop_mult=atr_stop_mult,
                      min_htf_grade=min_htf_grade,
                      min_rr=min_rr,
                      tp_rr=tp_rr,
                      min_ltf_confirmations=min_ltf_confirmations,
                      required_session=required_session,
                      profile=profile,
                      pair_name=pair_name)
    return compute_backtest_stats(trades)


def run_parameter_sweep():
    """Sweeps the SWEEP_GRID (day) and SCALP_SWEEP_GRID (scalp) across
    ALL traded pairs and reports which parameter combinations carry edge
    vs which are overfit to one setting. A robust edge should hold across
    NEIGHBORS of the chosen parameters, not collapse at the slightest shift.

    The old version backtested only the legacy single-symbol (EURUSD)
    path and produced identical stats for every grid cell because the
    atr_stop_mult override never reached the engine. This version varies
    the parameters explicitly per pair and aggregates, so the results
    reflect the full live universe and actually move with the inputs."""
    print("=" * 78)
    print(" PARAMETER-SENSITIVITY SWEEP — is the edge robust or overfit?")
    print("=" * 78)

    rows = []

    # --- DAY PROFILE SWEEP ---
    print("\n[DAY PROFILE SWEEP]")
    for pair in TRADED_PAIRS:
        pair_name = pair["name"]
        df_htf = fetch_data(HTF_INTERVAL, max(HTF_BARS, 2000), pair_name=pair_name)
        df_ltf = fetch_data(LTF_INTERVAL, max(LTF_BARS, 6000), pair_name=pair_name)
        if len(df_htf) < 250 or len(df_ltf) < 250:
            print(f"  {pair_name}: not enough history — skipping.")
            continue
        print(f"\n  Sweeping DAY {pair_name} ({len(df_htf)} HTF / {len(df_ltf)} LTF bars)")
        for grade in SWEEP_GRID["min_htf_grade"]:
            for min_rr in SWEEP_GRID["min_rr"]:
                for mult in SWEEP_GRID["atr_stop_mult"]:
                    stats = _backtest_with_params(df_htf, df_ltf, grade, min_rr, mult,
                                                  pair_name=pair_name)
                    rows.append({
                        "profile": "day",
                        "pair": pair_name,
                        "min_grade": grade,
                        "min_rr": min_rr,
                        "atr_stop_mult": mult,
                        "tp_rr": str((1.5, 2.5, 4.0)),
                        "trades": stats.get("total_trades", 0),
                        "expectancy_r": stats.get("expectancy_r", 0),
                        "win_rate": stats.get("win_rate_pct", 0),
                        "profit_factor": stats.get("profit_factor", 0),
                        "max_dd_pct": stats.get("max_drawdown_pct", 0),
                    })
                    print(f"    grade={grade} min_rr={min_rr} atr_mult={mult} -> "
                          f"{rows[-1]['trades']} trades, "
                          f"E={rows[-1]['expectancy_r']}R, "
                          f"WR={rows[-1]['win_rate']}%, "
                          f"PF={rows[-1]['profit_factor']}, "
                          f"MaxDD={rows[-1]['max_dd_pct']}%")

    # --- SCALP PROFILE SWEEP ---
    print("\n[SCALP PROFILE SWEEP]")
    for pair in TRADED_PAIRS:
        pair_name = pair["name"]
        df_htf = fetch_data(SCALP_HTF_INTERVAL, max(SCALP_HTF_BARS, 2000), pair_name=pair_name)
        df_ltf = fetch_data(SCALP_LTF_INTERVAL, max(SCALP_LTF_BARS, 6000), pair_name=pair_name)
        if len(df_htf) < 250 or len(df_ltf) < 250:
            print(f"  {pair_name}: not enough history — skipping.")
            continue
        print(f"\n  Sweeping SCALP {pair_name} ({len(df_htf)} HTF / {len(df_ltf)} LTF bars)")
        for grade in SCALP_SWEEP_GRID["min_htf_grade"]:
            for min_rr in SCALP_SWEEP_GRID["min_rr"]:
                for mult in SCALP_SWEEP_GRID["atr_stop_mult"]:
                    for tp_rr in SCALP_SWEEP_GRID["tp_rr"]:
                        stats = _backtest_with_params(df_htf, df_ltf, grade, min_rr, mult,
                                                      tp_rr=tp_rr,
                                                      min_ltf_confirmations=SCALP_MIN_LTF_CONFIRMATIONS,
                                                      required_session=SCALP_PROFILE["required_session"],
                                                      profile=SCALP_PROFILE,
                                                      pair_name=pair_name)
                        rows.append({
                            "profile": "scalp",
                            "pair": pair_name,
                            "min_grade": grade,
                            "min_rr": min_rr,
                            "atr_stop_mult": mult,
                            "tp_rr": str(tp_rr),
                            "trades": stats.get("total_trades", 0),
                            "expectancy_r": stats.get("expectancy_r", 0),
                            "win_rate": stats.get("win_rate_pct", 0),
                            "profit_factor": stats.get("profit_factor", 0),
                            "max_dd_pct": stats.get("max_drawdown_pct", 0),
                        })
                        print(f"    grade={grade} min_rr={min_rr} atr_mult={mult} tp_rr={tp_rr} -> "
                              f"{rows[-1]['trades']} trades, "
                              f"E={rows[-1]['expectancy_r']}R, "
                              f"WR={rows[-1]['win_rate']}%, "
                              f"PF={rows[-1]['profit_factor']}, "
                              f"MaxDD={rows[-1]['max_dd_pct']}%")

    if not rows:
        print("\nNo pair had enough history for a sweep.")
        return

    out = pd.DataFrame(rows)
    out.to_csv("parameter_sweep.csv", index=False)
    # Robustness heuristic: how many configs stay profitable?
    profitable = out[out["expectancy_r"] > 0]
    print("\n" + "-" * 78)
    print(f"ROBUSTNESS: {len(profitable)}/{len(out)} configs are profitable (E>0).")
    for prof in ["day", "scalp"]:
        prof_rows = out[out["profile"] == prof]
        prof_prof = prof_rows[prof_rows["expectancy_r"] > 0]
        if len(prof_rows) > 0:
            print(f"  {prof.upper()}: {len(prof_prof)}/{len(prof_rows)} profitable.")
    if len(profitable) >= len(out) * 0.6:
        print("  Edge appears ROBUST — survives most parameter perturbations.")
    elif len(profitable) >= len(out) * 0.3:
        print("  Edge is FRAGILE — sensitive to parameter choice; treat with skepticism.")
    else:
        print("  Edge is OVERFIT or absent — most configs lose. Do NOT trade live.")
    print(f"\nFull sweep saved to parameter_sweep.csv")


def run_walkforward(n_folds=4, profile=DAY_PROFILE):
    """Walk-forward analysis: split history into n_folds consecutive windows.
    For each fold, the PRIOR windows are 'in-sample' (you'd optimize params
    here) and the fold itself is 'out-of-sample' (test on unseen data).
    Since we don't auto-optimize params, this reports OOS performance with
    the FIXED current params per fold — exposing regime dependence and
    whether the edge holds forward in time, not just on the full window.

    Runs per pair and aggregates, so the numbers reflect the full live
    universe rather than the legacy single-symbol path.

    `profile` can be DAY_PROFILE or SCALP_PROFILE."""
    mode = profile["mode"]
    print("=" * 78)
    print(f" WALK-FORWARD ({n_folds} folds) — {mode.upper()} ENGINE — out-of-sample performance over time")
    print("=" * 78)

    all_rows = []
    htf_iv = profile["htf_interval"]
    ltf_iv = profile["ltf_interval"]
    htf_bars = profile["htf_bars"]
    ltf_bars = profile["ltf_bars"]
    for pair in TRADED_PAIRS:
        pair_name = pair["name"]
        df_htf = fetch_data(htf_iv, max(htf_bars, 2000), pair_name=pair_name)
        df_ltf = fetch_data(ltf_iv, max(ltf_bars, 6000), pair_name=pair_name)
        if len(df_ltf) < 500:
            print(f"  {pair_name}: not enough history for walk-forward — skipping.")
            continue

        print(f"\n  {pair_name}:")
        # Split LTF into n_folds consecutive chunks. HTF is reindexed per fold to
        # only include bars that had closed before each LTF fold start (no lookahead).
        n = len(df_ltf)
        fold_size = n // n_folds
        rows = []
        for f in range(n_folds):
            start = f * fold_size
            end = (f + 1) * fold_size if f < n_folds - 1 else n
            ltf_fold = df_ltf.iloc[start:end]
            if len(ltf_fold) < 250:
                continue
            htf_fold = df_htf[df_htf.index < ltf_fold.index[-1]]
            if len(htf_fold) < 250:
                continue
            trades = backtest(htf_fold, ltf_fold, profile=profile, pair_name=pair_name)
            stats = compute_backtest_stats(trades)
            rows.append({
                "pair": pair_name,
                "fold": f + 1,
                "start": str(ltf_fold.index[0].date()),
                "end": str(ltf_fold.index[-1].date()),
                "bars": len(ltf_fold),
                "trades": stats.get("total_trades", 0),
                "expectancy_r": stats.get("expectancy_r", 0),
                "win_rate": stats.get("win_rate_pct", 0),
                "profit_factor": stats.get("profit_factor", 0),
                "max_dd_pct": stats.get("max_drawdown_pct", 0),
                "return_pct": stats.get("total_return_pct", 0),
            })
            r = rows[-1]
            print(f"    Fold {r['fold']}: {r['start']} -> {r['end']}  "
                  f"{r['trades']} trades, E={r['expectancy_r']}R, "
                  f"WR={r['win_rate']}%, PF={r['profit_factor']}, "
                  f"MaxDD={r['max_dd_pct']}%, Return={r['return_pct']}%")
        all_rows.extend(rows)

    if not all_rows:
        print("\nNo fold had enough data.\n")
        return
    out = pd.DataFrame(all_rows)
    out.to_csv("walkforward.csv", index=False)
    oos = out[out["trades"] > 0]
    if oos.empty:
        print("\nNo trades in any fold.")
        return
    profitable_folds = oos[oos["expectancy_r"] > 0]
    print("\n" + "-" * 78)
    print(f"OUT-OF-SAMPLE SUMMARY: {len(profitable_folds)}/{len(oos)} folds profitable.")
    print(f"  Mean OOS expectancy: {oos['expectancy_r'].mean():.3f}R")
    print(f"  Worst OOS fold:      {oos['expectancy_r'].min():.3f}R")
    if len(profitable_folds) >= len(oos) * 0.6:
        print("  Edge is stable across time folds — more likely real than overfit.")
    else:
        print("  Edge is REGIME-DEPENDENT — it works in some periods and fails in "
              "others. Do not assume it generalizes.")
    print(f"\nFull fold-by-fold results saved to walkforward.csv")


def _countdown(seconds, label="Next scan"):
    """Prints a visible minute:second countdown. Prints a fresh full line
    every minute so the trail is visible even in terminals that don't
    handle carriage-return overwrites well. Returns False on Ctrl+C."""
    next_line_at = seconds  # print a full line on first iteration
    while seconds > 0:
        mins, secs = divmod(seconds, 60)
        if seconds <= next_line_at:
            print(f"  {label} in {mins:02d}:{secs:02d} ...")
            next_line_at = seconds - 60
        else:
            print(f"\r  {label} in {mins:02d}:{secs:02d} ...   ",
                  end="", flush=True)
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopped.")
            return False
        seconds -= 1
    print(f"\r  {label} now.{' ' * 20}")
    return True


def _count_scalp_signals_recent(window_hours=SCALP_SIGNAL_WINDOW_HOURS):
    """Counts scalp-mode signals logged in the last `window_hours` hours.
    Used by the scalping engine's anti-overtrading cap."""
    path = SIGNAL_LOG_PATH
    if not os.path.isfile(path):
        return 0
    try:
        df = pd.read_csv(path)
        if df.empty:
            return 0
        df["logged_at_utc"] = pd.to_datetime(df["logged_at_utc"], utc=True)
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=window_hours)
        recent = df[df["logged_at_utc"] >= cutoff]
        # Count only scalp-mode signals
        if "Mode" in recent.columns:
            return int((recent["Mode"] == "scalp").sum())
        return 0
    except Exception:
        return 0


def run_live_loop(repeat_seconds=REPEAT_INTERVAL_SECONDS):
    """Continuous scanning loop — re-scans every 5 minutes for day trading.

    All trades are punched manually by the user; the scanner never waits
    for a trade to close. Ctrl+C stops the loop cleanly."""
    mins = repeat_seconds // 60
    secs = repeat_seconds % 60
    label = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
    print(f"Starting live loop — re-scanning every {label}. Ctrl+C to stop.\n")
    while True:
        try:
            run_scanner()
        except (Exception, SystemExit) as e:
            print(f"[!] Scan failed ({e}). Will retry next cycle.")
            _invalidate_mt5_symbol_cache()
        if not _countdown(repeat_seconds, "Next scan"):
            break


def send_telegram_alert(message, max_retries=3):
    """Best-effort Telegram push with simple retry/backoff. Silently no-ops
    if not configured, and never lets a failed alert crash the scan itself."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    import urllib.request
    import urllib.parse
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": message}).encode()
    for attempt in range(max_retries):
        try:
            urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
            return
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s backoff
            else:
                print(f"[!] Telegram alert failed after {max_retries} tries (non-fatal): {e}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if mode == "backtest":
        run_backtest()
    elif mode == "sweep":
        run_parameter_sweep()
    elif mode == "walkforward":
        run_walkforward()
    elif mode == "walkforward-scalp":
        run_walkforward(profile=SCALP_PROFILE)
    elif mode == "scalp":
        # Run a single scan with the scalping engine only
        from tabulate import tabulate
        print("=" * 78)
        print(" PROFESSIONAL FOREX SCALPING SCANNER (Multi-Pair)")
        print(f" Pairs: {', '.join(p['name'] for p in TRADED_PAIRS)}")
        print(f" HTF={SCALP_HTF_INTERVAL}  LTF={SCALP_LTF_INTERVAL}  Data: {DATA_SOURCE}")
        print("=" * 78)
        # Reuse the run_scanner logic but with only SCALP_PROFILE
        # (we could refactor run_scanner to take a profile list, but
        # for now just run the scalp path inline)
        # For simplicity, just run the full scanner which includes scalp
        run_scanner()
    elif mode == "live":
        run_live_loop()
    else:
        run_scanner()

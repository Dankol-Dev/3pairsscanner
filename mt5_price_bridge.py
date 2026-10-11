#!/usr/bin/env python3
"""
MT5 → Supabase Price Bridge
============================
Runs on the machine where your MT5 terminal is open. Reads the live forex
ticks (bid/ask/last) for EURUSD, AUDUSD, and GBPUSD from your broker every
few seconds and pushes them into the Supabase `gold_prices` table (which
the dashboard uses as `price_ticks`), where the dashboard picks them up.

The dashboard already polls the gold-price edge function (which falls back
to Yahoo Finance). This script adds a PREFERENTIAL source: when recent
rows in gold_prices come from "mt5-bridge", the dashboard shows your
broker's real-time price instead of the Yahoo fallback.

PREREQUISITES
-------------
1. pip install MetaTrader5 requests
2. MT5 desktop terminal OPEN and logged into your broker account
3. Algo Trading enabled (Tools > Options > Expert Advisors > Allow
   Algorithmic Trading)
4. EURUSD, AUDUSD, GBPUSD symbols visible in Market Watch (right-click >
   Show All, or search for each pair)

RUN
---
    python mt5_price_bridge.py

It loops forever. Ctrl+C to stop. Every PUSH_INTERVAL_SECONDS (default 5s)
it reads the current tick for each pair and POSTs it to Supabase.
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# CONFIG — pulled from this project's .env so you don't duplicate secrets
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")

def _load_env(path):
    env = {}
    if not os.path.isfile(path):
        return env
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

_env = _load_env(ENV_PATH)

SUPABASE_URL = _env.get("VITE_SUPABASE_URL") or os.environ.get("VITE_SUPABASE_URL", "")
SUPABASE_ANON_KEY = _env.get("VITE_SUPABASE_ANON_KEY") or os.environ.get("VITE_SUPABASE_ANON_KEY", "")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    print("ERROR: VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY not found in .env")
    sys.exit(1)

PUSH_INTERVAL_SECONDS = 5
MAX_RETRIES = 3
RETRY_DELAY = 10

# Each pair has MT5 symbol candidates (broker suffixes vary). The bridge
# iterates over ALL pairs each cycle and pushes a row per pair into
# Supabase so the dashboard can show live prices per symbol.
TRADED_PAIRS = [
    {
        "name": "EURUSD",
        "mt5_symbols": ["EURUSD", "EURUSD.m", "EURUSDm", "EURUSD.", "EURUSD.i"],
    },
    {
        "name": "AUDUSD",
        "mt5_symbols": ["AUDUSD", "AUDUSD.m", "AUDUSDm", "AUDUSD.", "AUDUSD.i"],
    },
    {
        "name": "GBPUSD",
        "mt5_symbols": ["GBPUSD", "GBPUSD.m", "GBPUSDm", "GBPUSD.", "GBPUSD.i"],
    },
]


def resolve_mt5_symbol(mt5, candidates):
    for sym in candidates:
        if mt5.symbol_select(sym, True):
            return sym
    return None


def read_mt5_tick(mt5, symbol):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    bid = float(tick.bid) if tick.bid else None
    ask = float(tick.ask) if tick.ask else None
    if bid is None or ask is None:
        return None
    mid = (bid + ask) / 2.0
    spread = ask - bid
    return {
        "price": round(mid, 5),
        "bid": round(bid, 5),
        "ask": round(ask, 5),
        "spread": round(spread, 5),
        "source": "mt5-bridge",
    }


def push_to_supabase(payload):
    url = f"{SUPABASE_URL}/rest/v1/gold_prices"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("apikey", SUPABASE_ANON_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_ANON_KEY}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "return=minimal")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 201
    except urllib.error.HTTPError as e:
        print(f"  Supabase HTTP error: {e.code} {e.reason}")
        return False
    except Exception as e:
        print(f"  Supabase request failed: {e}")
        return False


def main():
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("ERROR: MetaTrader5 package not installed. Run: pip install MetaTrader5")
        sys.exit(1)

    print("=" * 60)
    print("  MT5 → Supabase Price Bridge")
    print("=" * 60)
    print(f"  Supabase URL : {SUPABASE_URL}")
    print(f"  Push interval: {PUSH_INTERVAL_SECONDS}s")
    print(f"  Pairs: {', '.join(p['name'] for p in TRADED_PAIRS)}")
    print("=" * 60)
    print()

    # Resolved symbols per pair (cached once found, so a live loop doesn't
    # re-probe every candidate on every poll).
    resolved_symbols = {}
    consecutive_failures = 0

    while True:
        try:
            if not mt5.initialize():
                print(f"[!] MT5 initialize() failed: {mt5.last_error()}")
                print("    Is the MT5 terminal open and logged in? Retrying...")
                time.sleep(RETRY_DELAY)
                continue

            try:
                # Resolve any unresolved pair symbols.
                for pair in TRADED_PAIRS:
                    if pair["name"] not in resolved_symbols:
                        sym = resolve_mt5_symbol(mt5, pair["mt5_symbols"])
                        if sym is None:
                            print(f"[!] None of {pair['mt5_symbols']} found in MT5 Market Watch "
                                  f"for {pair['name']}.")
                            print("    Open Market Watch, right-click > Show All, or search "
                                  f"'{pair['name']}'.")
                        else:
                            resolved_symbols[pair["name"]] = sym
                            print(f"[OK] {pair['name']}: using MT5 symbol '{sym}'")

                if not resolved_symbols:
                    print("[!] No forex symbols resolved. Retrying...")
                    time.sleep(RETRY_DELAY)
                    continue

                all_ok = True
                ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
                for pair in TRADED_PAIRS:
                    sym = resolved_symbols.get(pair["name"])
                    if sym is None:
                        all_ok = False
                        continue
                    tick_data = read_mt5_tick(mt5, sym)
                    if tick_data is None:
                        print(f"[!] No tick data for {pair['name']} ({sym}). Market may be closed.")
                        all_ok = False
                        continue
                    tick_data["symbol"] = pair["name"]
                    ok = push_to_supabase(tick_data)
                    if ok:
                        print(f"  [{ts}] {pair['name']}: {tick_data['price']:.5f}  "
                              f"bid={tick_data['bid']:.5f} ask={tick_data['ask']:.5f} "
                              f"spread={tick_data['spread']:.5f}")
                    else:
                        all_ok = False

                if not all_ok:
                    consecutive_failures += 1
                    if consecutive_failures >= MAX_RETRIES:
                        print("[!] Multiple push failures. Check Supabase connectivity.")
                        consecutive_failures = 0
                else:
                    consecutive_failures = 0

            finally:
                mt5.shutdown()

            time.sleep(PUSH_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("\n[STOP] Bridge stopped by user.")
            break
        except Exception as e:
            print(f"[!] Unexpected error: {e}")
            time.sleep(RETRY_DELAY)


if __name__ == "__main__":
    main()

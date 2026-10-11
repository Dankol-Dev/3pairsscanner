import { useEffect, useState, useRef } from 'react';
import { TrendingUp, TrendingDown, RefreshCw, Activity, Clock, Wifi } from 'lucide-react';
import { supabase, TRADED_PAIRS, type PriceTick } from '../lib/supabase';

const EDGE_FUNCTION_URL = `${import.meta.env.VITE_SUPABASE_URL}/functions/v1/gold-price`;
const BROKER_STALE_MS = 30_000;

type Props = {
  onPriceUpdate?: (price: number, symbol: string) => void;
};

type PairState = {
  tick: PriceTick | null;
  prevPrice: number | null;
  loading: boolean;
  usingBroker: boolean;
};

export function LivePriceCard({ onPriceUpdate }: Props) {
  const [pairStates, setPairStates] = useState<Record<string, PairState>>({});
  const [error, setError] = useState<string | null>(null);
  const [lastFetch, setLastFetch] = useState<Date | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchPrices = async () => {
    try {
      setError(null);

      // Check database for broker-pushed prices for each pair
      const { data: dbRows } = await supabase
        .from('gold_prices')
        .select('price, bid, ask, spread, source, symbol, fetched_at')
        .order('fetched_at', { ascending: false })
        .limit(50);

      type DbRow = NonNullable<typeof dbRows>[number];
      const latestByPair: Record<string, DbRow> = {};
      if (dbRows) {
        for (const row of dbRows) {
          if (!row.symbol) continue;
          if (!latestByPair[row.symbol]) {
            latestByPair[row.symbol] = row;
          }
        }
      }

      const newStates: Record<string, PairState> = {};

      for (const pair of TRADED_PAIRS) {
        const dbRow = latestByPair[pair];
        let brokerFresh = false;
        let tick: PriceTick | null = null;

        if (dbRow && dbRow.price != null) {
          const ageMs = Date.now() - new Date(dbRow.fetched_at).getTime();
          brokerFresh = ageMs < BROKER_STALE_MS;
          if (brokerFresh) {
            tick = {
              price: dbRow.price,
              bid: dbRow.bid,
              ask: dbRow.ask,
              spread: dbRow.spread,
              source: dbRow.source ?? 'broker',
              symbol: pair,
              timestamp: dbRow.fetched_at,
            };
          }
        }

        newStates[pair] = {
          tick,
          prevPrice: null,
          loading: !tick,
          usingBroker: brokerFresh,
        };
      }

      // For pairs without fresh broker data, fetch per-pair from edge function
      for (const pair of TRADED_PAIRS) {
        if (newStates[pair].tick) continue;
        try {
          const resp = await fetch(`${EDGE_FUNCTION_URL}?pair=${pair}`, {
            headers: {
              Authorization: `Bearer ${import.meta.env.VITE_SUPABASE_ANON_KEY}`,
              'Content-Type': 'application/json',
            },
          });
          if (resp.ok) {
            const data = await resp.json();
            if (data.price != null) {
              newStates[pair] = {
                tick: {
                  price: data.price,
                  bid: data.bid ?? null,
                  ask: data.ask ?? null,
                  spread: data.spread ?? null,
                  source: data.source ?? 'fallback',
                  symbol: pair,
                  timestamp: data.timestamp ?? new Date().toISOString(),
                },
                prevPrice: null,
                loading: false,
                usingBroker: false,
              };
            }
          }
        } catch {
          // Fail silently per pair — other pairs may still work
        }
      }

      // Preserve previous prices for flash effect
      setPairStates((old) => {
        const merged: Record<string, PairState> = {};
        for (const pair of TRADED_PAIRS) {
          const ns = newStates[pair];
          const os = old[pair];
          merged[pair] = {
            ...ns,
            prevPrice: os?.tick?.price ?? null,
            loading: false,
          };
        }
        return merged;
      });

      setLastFetch(new Date());
      // Notify parent of first pair's price for TP distance display
      const firstPair = TRADED_PAIRS[0];
      const firstTick = newStates[firstPair]?.tick;
      if (firstTick) onPriceUpdate?.(firstTick.price, firstPair);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch prices');
    }
  };

  useEffect(() => {
    fetchPrices();
    intervalRef.current = setInterval(fetchPrices, 5000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  return (
    <div className="rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-900/80 to-slate-900/40 p-6 backdrop-blur">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-sky-400 to-sky-600 flex items-center justify-center shadow-lg shadow-sky-500/20">
            <Activity className="w-6 h-6 text-slate-900" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-slate-200">Live FX Prices</h2>
            <p className="text-xs text-slate-500">EURUSD · AUDUSD · GBPUSD</p>
          </div>
        </div>
        <button
          onClick={fetchPrices}
          className="p-1.5 rounded-lg hover:bg-slate-800 transition-colors"
          title="Refresh prices"
        >
          <RefreshCw className="w-3.5 h-3.5 text-slate-400" />
        </button>
      </div>

      <div className="space-y-3">
        {TRADED_PAIRS.map((pair) => {
          const state = pairStates[pair];
          const tick = state?.tick;
          const price = tick?.price ?? null;
          const prev = state?.prevPrice;
          const change = prev != null && price != null ? price - prev : null;
          const isUp = change != null && change > 0;
          const isDown = change != null && change < 0;
          const flashClass = isUp ? 'text-emerald-400' : isDown ? 'text-rose-400' : 'text-sky-300';

          return (
            <div key={pair} className="flex items-center justify-between py-2 border-b border-slate-800/50 last:border-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-200 w-16">{pair}</span>
                {state?.usingBroker ? (
                  <span className="flex items-center gap-1 text-[10px] text-emerald-400 font-medium">
                    <Wifi className="w-2.5 h-2.5" />MT5
                  </span>
                ) : (
                  <span className="text-[10px] text-slate-600 font-medium">
                    {tick?.source === 'fallback' ? 'Yahoo' : tick?.source ?? '—'}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3">
                {state?.loading ? (
                  <RefreshCw className="w-3 h-3 text-sky-400 animate-spin" />
                ) : price != null ? (
                  <>
                    <span className={`text-lg font-bold tabular-nums ${flashClass} transition-colors duration-300`}>
                      {price.toFixed(5)}
                    </span>
                    {change != null && (
                      <span className={`text-xs tabular-nums ${isUp ? 'text-emerald-400' : isDown ? 'text-rose-400' : 'text-slate-500'}`}>
                        {isUp && <TrendingUp className="w-3 h-3 inline" />}
                        {isDown && <TrendingDown className="w-3 h-3 inline" />}
                        {change >= 0 ? '+' : ''}{change.toFixed(5)}
                      </span>
                    )}
                  </>
                ) : (
                  <span className="text-slate-600 text-sm">—</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-1.5 mt-3 pt-3 border-t border-slate-800/50 text-xs text-slate-600">
        <Clock className="w-3 h-3" />
        <span>{lastFetch ? `Updated ${lastFetch.toLocaleTimeString()}` : '—'}</span>
      </div>

      {error && (
        <div className="mt-3 p-2 rounded-lg bg-rose-950/50 border border-rose-800/50 text-rose-300 text-xs">
          {error}
        </div>
      )}
    </div>
  );
}

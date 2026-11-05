import { useEffect, useState, useMemo } from 'react';
import { GitBranch, RefreshCw, AlertTriangle } from 'lucide-react';

type WalkRow = {
  pair: string;
  fold: number;
  start: string;
  end: string;
  bars: number;
  trades: number;
  expectancy_r: number;
  win_rate: number;
  profit_factor: number;
  max_dd_pct: number;
  return_pct: number;
};

export function WalkforwardTable() {
  const [rows, setRows] = useState<WalkRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchWalkforward = async () => {
      setError(null);
      try {
        const resp = await fetch('/walkforward.csv');
        if (!resp.ok) throw new Error(`Failed to load CSV (${resp.status})`);
        const text = await resp.text();
        const parsed = parseWalkforwardCsv(text);
        setRows(parsed);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load walkforward data');
      }
      setLoading(false);
    };
    fetchWalkforward();
  }, []);

  const byPair = useMemo(() => {
    const map: Record<string, WalkRow[]> = {};
    for (const r of rows) {
      if (!map[r.pair]) map[r.pair] = [];
      map[r.pair].push(r);
    }
    return map;
  }, [rows]);

  const totalTrades = useMemo(() => rows.reduce((s, r) => s + r.trades, 0), [rows]);

  if (loading) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-12 text-center">
        <RefreshCw className="w-5 h-5 text-sky-400 animate-spin mx-auto mb-3" />
        <p className="text-slate-400 text-sm">Loading walkforward data...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-8">
        <div className="flex items-center gap-2 text-amber-400 mb-2">
          <AlertTriangle className="w-4 h-4" />
          <span className="text-sm font-medium">No walkforward data available</span>
        </div>
        <p className="text-slate-400 text-sm">{error}</p>
        <p className="text-slate-500 text-xs mt-2">
          Run <code className="text-slate-300 bg-slate-800 px-1.5 py-0.5 rounded">python gold_scanner.py --walkforward</code> to generate it.
        </p>
      </div>
    );
  }

  if (rows.length === 0 || totalTrades === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-8">
        <div className="flex items-center gap-2 text-amber-400 mb-2">
          <AlertTriangle className="w-4 h-4" />
          <span className="text-sm font-medium">No trades in any walkforward fold</span>
        </div>
        <p className="text-slate-400 text-sm">
          All {rows.length} folds across {Object.keys(byPair).length} pairs produced 0 trades.
          This means the strategy produced no qualifying setups in any out-of-sample window —
          there is no evidence of a live-tradeable edge.
        </p>
        <p className="text-slate-500 text-xs mt-2">
          Either the test period had no qualifying setups, or the confluence filter is too strict.
          Run with a longer history window or relax the minimum grade.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
          <p className="text-xs text-slate-500">Pairs</p>
          <p className="text-lg font-bold">{Object.keys(byPair).length}</p>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
          <p className="text-xs text-slate-500">Total Folds</p>
          <p className="text-lg font-bold">{rows.length}</p>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
          <p className="text-xs text-slate-500">Total Trades</p>
          <p className="text-lg font-bold">{totalTrades}</p>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
          <p className="text-xs text-slate-500">Folds w/ Trades</p>
          <p className="text-lg font-bold">{rows.filter(r => r.trades > 0).length}/{rows.length}</p>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 overflow-hidden">
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400 text-xs uppercase tracking-wider">
                <th className="text-left px-4 py-3 font-medium">Pair</th>
                <th className="text-left px-4 py-3 font-medium">Fold</th>
                <th className="text-left px-4 py-3 font-medium">Period</th>
                <th className="text-right px-4 py-3 font-medium">Bars</th>
                <th className="text-right px-4 py-3 font-medium">Trades</th>
                <th className="text-right px-4 py-3 font-medium">Exp (R)</th>
                <th className="text-right px-4 py-3 font-medium">Win %</th>
                <th className="text-right px-4 py-3 font-medium">PF</th>
                <th className="text-right px-4 py-3 font-medium">Max DD %</th>
                <th className="text-right px-4 py-3 font-medium">Return %</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(byPair).map(([pair, pairRows]) =>
                pairRows.map((row, idx) => {
                  const isZero = row.trades === 0;
                  return (
                    <tr
                      key={`${pair}-${row.fold}-${idx}`}
                      className={`border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors ${
                        isZero ? 'opacity-40' : ''
                      }`}
                    >
                      <td className="px-4 py-2.5">
                        <span className={`text-xs font-bold ${pairColor(pair)}`}>{pair}</span>
                      </td>
                      <td className="px-4 py-2.5 text-slate-400 tabular-nums">{row.fold}</td>
                      <td className="px-4 py-2.5 text-slate-400 text-xs whitespace-nowrap">
                        {row.start} → {row.end}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-slate-400">{row.bars}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-slate-200">{row.trades}</td>
                      <td className={`px-4 py-2.5 text-right tabular-nums ${
                        isZero ? 'text-slate-600' : row.expectancy_r > 0 ? 'text-emerald-400' : 'text-rose-400'
                      }`}>
                        {isZero ? '—' : row.expectancy_r.toFixed(3)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-slate-300">
                        {isZero ? '—' : `${row.win_rate.toFixed(1)}%`}
                      </td>
                      <td className={`px-4 py-2.5 text-right tabular-nums ${
                        isZero ? 'text-slate-600' : row.profit_factor >= 1.2 ? 'text-emerald-400' : 'text-rose-400'
                      }`}>
                        {isZero ? '—' : row.profit_factor.toFixed(2)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-slate-400">
                        {isZero ? '—' : `${row.max_dd_pct.toFixed(1)}%`}
                      </td>
                      <td className={`px-4 py-2.5 text-right tabular-nums ${
                        isZero ? 'text-slate-600' : row.return_pct > 0 ? 'text-emerald-400' : 'text-rose-400'
                      }`}>
                        {isZero ? '—' : `${row.return_pct.toFixed(1)}%`}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function pairColor(pair: string): string {
  if (pair === 'EURUSD') return 'text-sky-400';
  if (pair === 'AUDUSD') return 'text-emerald-400';
  if (pair === 'GBPUSD') return 'text-violet-400';
  return 'text-slate-400';
}

function parseWalkforwardCsv(text: string): WalkRow[] {
  const lines = text.trim().split('\n');
  if (lines.length < 2) return [];

  const parseLine = (line: string): string[] => {
    const result: string[] = [];
    let current = '';
    let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') {
        inQuotes = !inQuotes;
      } else if (ch === ',' && !inQuotes) {
        result.push(current);
        current = '';
      } else {
        current += ch;
      }
    }
    result.push(current);
    return result.map(s => s.trim());
  };

  const headers = parseLine(lines[0]);
  const rows: WalkRow[] = [];

  for (let i = 1; i < lines.length; i++) {
    if (!lines[i].trim()) continue;
    const values = parseLine(lines[i]);
    const obj: Record<string, string> = {};
    headers.forEach((h, idx) => {
      obj[h] = values[idx] ?? '';
    });

    rows.push({
      pair: obj['pair'] ?? '—',
      fold: parseInt(obj['fold']) || 0,
      start: obj['start'] ?? '—',
      end: obj['end'] ?? '—',
      bars: parseInt(obj['bars']) || 0,
      trades: parseInt(obj['trades']) || 0,
      expectancy_r: parseFloat(obj['expectancy_r']) || 0,
      win_rate: parseFloat(obj['win_rate']) || 0,
      profit_factor: parseFloat(obj['profit_factor']) || 0,
      max_dd_pct: parseFloat(obj['max_dd_pct']) || 0,
      return_pct: parseFloat(obj['return_pct']) || 0,
    });
  }

  return rows;
}

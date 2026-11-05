import { useEffect, useState, useMemo } from 'react';
import { Grid3x3, RefreshCw, TrendingUp, AlertTriangle, Award, ChevronRight } from 'lucide-react';

type SweepRow = {
  profile: string;
  pair: string;
  min_grade: string;
  min_rr: number;
  atr_stop_mult: number;
  tp_rr?: string;
  trades: number;
  expectancy_r: number;
  win_rate: number;
  profit_factor: number;
  max_dd_pct: number;
};

type SortKey = keyof SweepRow;

export function SweepTable() {
  const [rows, setRows] = useState<SweepRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>('profile');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [profileFilter, setProfileFilter] = useState<string>('ALL');

  const fetchSweep = async () => {
    setError(null);
    try {
      const resp = await fetch('/parameter_sweep.csv');
      if (!resp.ok) throw new Error(`Failed to load CSV (${resp.status})`);
      const text = await resp.text();
      const parsed = parseCsv(text);
      setRows(parsed);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load sweep data');
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchSweep();
  }, []);

  const sorted = useMemo(() => {
    const filtered = profileFilter === 'ALL'
      ? rows
      : rows.filter(r => r.profile === profileFilter);
    const arr = [...filtered];
    arr.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      let cmp = 0;
      if (typeof av === 'number' && typeof bv === 'number') {
        cmp = av - bv;
      } else {
        cmp = String(av ?? '').localeCompare(String(bv ?? ''));
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return arr;
  }, [rows, sortKey, sortDir, profileFilter]);

  const profiles = useMemo(() => {
    const set = new Set(rows.map(r => r.profile));
    return ['ALL', ...Array.from(set)];
  }, [rows]);

  const summary = useMemo(() => {
    if (rows.length === 0) return null;
    const profitable = rows.filter(r => r.expectancy_r > 0);
    const dayRows = rows.filter(r => r.profile === 'day');
    const scalpRows = rows.filter(r => r.profile === 'scalp');
    const dayProf = dayRows.filter(r => r.expectancy_r > 0);
    const scalpProf = scalpRows.filter(r => r.expectancy_r > 0);

    const tradeable = rows.filter(r => r.trades > 0);
    let best: SweepRow | null = null;
    if (tradeable.length > 0) {
      best = tradeable.reduce((top, row) => {
        const topScore = top.expectancy_r * (top.profit_factor > 0 ? top.profit_factor : 0.01);
        const rowScore = row.expectancy_r * (row.profit_factor > 0 ? row.profit_factor : 0.01);
        return rowScore > topScore ? row : top;
      });
    }

    return {
      total: rows.length,
      profitable: profitable.length,
      pct: (profitable.length / rows.length) * 100,
      dayCount: dayRows.length,
      dayProf: dayProf.length,
      scalpCount: scalpRows.length,
      scalpProf: scalpProf.length,
      bestExpectancy: Math.max(...rows.map(r => r.expectancy_r)),
      worstExpectancy: Math.min(...rows.map(r => r.expectancy_r)),
      best,
    };
  }, [rows]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  if (loading) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-12 text-center">
        <RefreshCw className="w-5 h-5 text-sky-400 animate-spin mx-auto mb-3" />
        <p className="text-slate-400 text-sm">Loading parameter sweep data...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-8">
        <div className="flex items-center gap-2 text-amber-400 mb-2">
          <AlertTriangle className="w-4 h-4" />
          <span className="text-sm font-medium">No sweep data available</span>
        </div>
        <p className="text-slate-400 text-sm">{error}</p>
        <p className="text-slate-500 text-xs mt-2">
          Run <code className="text-slate-300 bg-slate-800 px-1.5 py-0.5 rounded">python gold_scanner.py --sweep</code> to generate it,
          then place the CSV in the <code className="text-slate-300 bg-slate-800 px-1.5 py-0.5 rounded">public/</code> folder.
        </p>
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-12 text-center">
        <Grid3x3 className="w-6 h-6 text-slate-600 mx-auto mb-3" />
        <p className="text-slate-400 text-sm">No rows in parameter_sweep.csv.</p>
        <p className="text-slate-500 text-xs mt-2">Run the sweep to populate it.</p>
      </div>
    );
  }

  const headers: { key: SortKey; label: string; align?: string }[] = [
    { key: 'profile', label: 'Profile' },
    { key: 'pair', label: 'Pair' },
    { key: 'min_grade', label: 'Min Grade' },
    { key: 'min_rr', label: 'Min RR', align: 'text-right' },
    { key: 'atr_stop_mult', label: 'ATR Stop', align: 'text-right' },
    { key: 'tp_rr', label: 'TP RR', align: 'text-center' },
    { key: 'trades', label: 'Trades', align: 'text-right' },
    { key: 'expectancy_r', label: 'Expectancy (R)', align: 'text-right' },
    { key: 'win_rate', label: 'Win %', align: 'text-right' },
    { key: 'profit_factor', label: 'PF', align: 'text-right' },
    { key: 'max_dd_pct', label: 'Max DD %', align: 'text-right' },
  ];

  return (
    <div className="space-y-4">
      {/* Best configuration highlight */}
      {summary?.best && (
        <div className="rounded-xl border border-emerald-800/50 bg-gradient-to-br from-emerald-950/40 via-slate-900/60 to-slate-900/40 p-5">
          <div className="flex items-start gap-4 flex-wrap">
            <div className="flex items-center gap-3">
              <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-emerald-400 to-emerald-600 flex items-center justify-center shadow-lg shadow-emerald-500/20">
                <Award className="w-5 h-5 text-slate-900" />
              </div>
              <div>
                <p className="text-xs font-medium text-emerald-400 uppercase tracking-wider">Best Configuration</p>
                <p className="text-sm text-slate-300 mt-0.5">
                  {summary.best.profile === 'scalp' ? 'Scalp' : 'Day'} ·{' '}
                  <span className={pairColor(summary.best.pair)}>{summary.best.pair}</span> ·{' '}
                  Grade {summary.best.min_grade} ·{' '}
                  RR {summary.best.min_rr.toFixed(1)} ·{' '}
                  ATR {summary.best.atr_stop_mult.toFixed(1)}x
                </p>
              </div>
            </div>
            <div className="flex items-center gap-5 ml-auto">
              <div className="text-right">
                <p className="text-xs text-slate-500">Expectancy</p>
                <p className="text-lg font-bold text-emerald-400 tabular-nums">
                  {summary.best.expectancy_r.toFixed(3)}R
                </p>
              </div>
              <div className="text-right">
                <p className="text-xs text-slate-500">Profit Factor</p>
                <p className="text-lg font-bold text-emerald-400 tabular-nums">
                  {summary.best.profit_factor.toFixed(2)}
                </p>
              </div>
              <div className="text-right">
                <p className="text-xs text-slate-500">Win Rate</p>
                <p className="text-lg font-bold tabular-nums text-slate-200">
                  {summary.best.win_rate.toFixed(1)}%
                </p>
              </div>
              <div className="text-right">
                <p className="text-xs text-slate-500">Trades</p>
                <p className="text-lg font-bold tabular-nums text-slate-200">{summary.best.trades}</p>
              </div>
              <div className="text-right">
                <p className="text-xs text-slate-500">Max DD</p>
                <p className="text-lg font-bold tabular-nums text-amber-400">
                  {summary.best.max_dd_pct.toFixed(1)}%
                </p>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1.5 mt-3 pt-3 border-t border-emerald-800/30 text-xs text-slate-500">
            <ChevronRight className="w-3 h-3" />
            <span>
              Scored by expectancy × profit factor.{' '}
              {summary.best.tp_rr && summary.best.tp_rr !== '—' && `TP ladder: ${summary.best.tp_rr}.  `}
              Treat as in-sample best — verify it holds in the walk-forward tab before trading.
            </span>
          </div>
        </div>
      )}

      {/* Summary */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
            <p className="text-xs text-slate-500">Configs Tested</p>
            <p className="text-lg font-bold">{summary.total}</p>
            <p className="text-xs text-slate-500 mt-0.5">{summary.profitable} profitable ({summary.pct.toFixed(0)}%)</p>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
            <p className="text-xs text-slate-500">Day Profile</p>
            <p className="text-lg font-bold">{summary.dayProf}/{summary.dayCount}</p>
            <p className="text-xs text-slate-500 mt-0.5">profitable</p>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
            <p className="text-xs text-slate-500">Scalp Profile</p>
            <p className="text-lg font-bold">{summary.scalpProf}/{summary.scalpCount}</p>
            <p className="text-xs text-slate-500 mt-0.5">profitable</p>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
            <p className="text-xs text-slate-500">Expectancy Range</p>
            <p className="text-lg font-bold tabular-nums">
              {summary.bestExpectancy.toFixed(3)}R
            </p>
            <p className={`text-xs mt-0.5 tabular-nums ${summary.worstExpectancy < 0 ? 'text-rose-400' : 'text-slate-500'}`}>
              worst: {summary.worstExpectancy.toFixed(3)}R
            </p>
          </div>
        </div>
      )}

      {/* Robustness verdict */}
      {summary && (
        <div className={`flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium ${
          summary.pct >= 60 ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-800/50' :
          summary.pct >= 30 ? 'bg-amber-500/10 text-amber-300 border border-amber-800/50' :
          'bg-rose-500/10 text-rose-300 border border-rose-800/50'
        }`}>
          <TrendingUp className="w-4 h-4 flex-shrink-0" />
          {summary.pct >= 60
            ? `Edge appears ROBUST — ${summary.pct.toFixed(0)}% of configs survive parameter perturbation.`
            : summary.pct >= 30
            ? `Edge is FRAGILE — only ${summary.pct.toFixed(0)}% of configs are profitable. Treat with skepticism.`
            : `Edge is OVERFIT or absent — only ${summary.pct.toFixed(0)}% of configs are profitable. Do NOT trade live.`}
        </div>
      )}

      {/* Profile filter */}
      <div className="flex items-center gap-2">
        {profiles.map(p => (
          <button
            key={p}
            onClick={() => setProfileFilter(p)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              profileFilter === p
                ? 'bg-sky-500/20 text-sky-300 border border-sky-700'
                : 'bg-slate-800/50 text-slate-400 hover:bg-slate-800 border border-transparent'
            }`}
          >
            {p === 'ALL' ? 'All Profiles' : p.charAt(0).toUpperCase() + p.slice(1)}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 overflow-hidden">
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400 text-xs uppercase tracking-wider">
                {headers.map(h => (
                  <th
                    key={h.key}
                    onClick={() => handleSort(h.key)}
                    className={`${h.align ?? 'text-left'} px-4 py-3 font-medium cursor-pointer select-none hover:text-slate-200 transition-colors`}
                  >
                    <span className="inline-flex items-center gap-1">
                      {h.label}
                      {sortKey === h.key && (
                        <span className="text-sky-400">{sortDir === 'asc' ? '↑' : '↓'}</span>
                      )}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((row, i) => {
                const isProfit = row.expectancy_r > 0;
                const isZero = row.trades === 0;
                return (
                  <tr
                    key={`${row.profile}-${row.pair}-${row.min_grade}-${row.min_rr}-${row.atr_stop_mult}-${i}`}
                    className={`border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors ${
                      isZero ? 'opacity-40' : ''
                    }`}
                  >
                    <td className="px-4 py-2.5">
                      <span className={`text-xs px-2 py-0.5 rounded ${
                        row.profile === 'scalp' ? 'bg-violet-500/20 text-violet-300' : 'bg-sky-500/20 text-sky-300'
                      }`}>
                        {row.profile}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-slate-300 text-xs font-medium">{row.pair}</td>
                    <td className="px-4 py-2.5">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${gradeColor(row.min_grade)}`}>
                        {row.min_grade}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-slate-300">{row.min_rr.toFixed(1)}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-slate-300">{row.atr_stop_mult.toFixed(1)}</td>
                    <td className="px-4 py-2.5 text-center text-slate-500 text-xs">{row.tp_rr ?? '—'}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-slate-200">{row.trades}</td>
                    <td className={`px-4 py-2.5 text-right tabular-nums font-medium ${
                      isZero ? 'text-slate-600' : isProfit ? 'text-emerald-400' : 'text-rose-400'
                    }`}>
                      {isZero ? '—' : row.expectancy_r.toFixed(3)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-slate-300">
                      {isZero ? '—' : `${row.win_rate.toFixed(1)}%`}
                    </td>
                    <td className={`px-4 py-2.5 text-right tabular-nums ${
                      isZero ? 'text-slate-600' : row.profit_factor >= 1.2 ? 'text-emerald-400' : row.profit_factor >= 1.0 ? 'text-amber-400' : 'text-rose-400'
                    }`}>
                      {isZero ? '—' : row.profit_factor.toFixed(2)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-slate-400">
                      {isZero ? '—' : `${row.max_dd_pct.toFixed(1)}%`}
                    </td>
                  </tr>
                );
              })}
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

function gradeColor(grade: string): string {
  if (grade.includes('A+')) return 'bg-emerald-500/20 text-emerald-300 border border-emerald-700';
  if (grade.includes('A')) return 'bg-amber-500/20 text-amber-300 border border-amber-700';
  if (grade.includes('B')) return 'bg-sky-500/20 text-sky-300 border border-sky-700';
  return 'bg-slate-700 text-slate-300';
}

function parseCsv(text: string): SweepRow[] {
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
  const rows: SweepRow[] = [];

  for (let i = 1; i < lines.length; i++) {
    if (!lines[i].trim()) continue;
    const values = parseLine(lines[i]);
    const obj: Record<string, string> = {};
    headers.forEach((h, idx) => {
      obj[h] = values[idx] ?? '';
    });

    const profile = obj['profile'] ?? 'day';
    const tp_rr = obj['tp_rr'] && obj['tp_rr'] !== 'nan' ? obj['tp_rr'] : undefined;

    rows.push({
      profile,
      pair: obj['pair'] ?? obj['min_grade'] ?? '—',
      min_grade: obj['min_grade'] ?? '—',
      min_rr: parseFloat(obj['min_rr']) || 0,
      atr_stop_mult: parseFloat(obj['atr_stop_mult']) || 0,
      tp_rr,
      trades: parseInt(obj['trades']) || 0,
      expectancy_r: parseFloat(obj['expectancy_r']) || 0,
      win_rate: parseFloat(obj['win_rate']) || 0,
      profit_factor: parseFloat(obj['profit_factor']) || 0,
      max_dd_pct: parseFloat(obj['max_dd_pct']) || 0,
    });
  }

  return rows;
}


export { SweepTable }
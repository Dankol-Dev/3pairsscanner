import { useState } from 'react';
import { ArrowUpRight, ArrowDownRight, CheckCircle2, XCircle, Clock, MinusCircle } from 'lucide-react';
import type { Signal } from '../lib/supabase';
import { TRADED_PAIRS } from '../lib/supabase';

type Props = {
  signals: Signal[];
  livePrice?: number | null;
};

function formatTime(ts: string | null): string {
  if (!ts) return '—';
  const d = new Date(ts);
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function formatAge(ts: string | null): string {
  if (!ts) return '';
  const then = new Date(ts).getTime();
  const now = Date.now();
  const diffMs = now - then;
  if (diffMs < 0) return 'future';
  const mins = Math.floor(diffMs / 60000);
  const hrs = Math.floor(mins / 60);
  const days = Math.floor(hrs / 24);
  if (days > 0) return `${days}d ${hrs % 24}h ago`;
  if (hrs > 0) return `${hrs}h ${mins % 60}m ago`;
  if (mins > 0) return `${mins}m ago`;
  return 'just now';
}

function gradeColor(grade: string | null): string {
  if (!grade) return 'bg-slate-700 text-slate-300';
  if (grade.includes('A+')) return 'bg-emerald-500/20 text-emerald-300 border border-emerald-700';
  if (grade.includes('A')) return 'bg-amber-500/20 text-amber-300 border border-amber-700';
  if (grade.includes('B')) return 'bg-sky-500/20 text-sky-300 border border-sky-700';
  return 'bg-slate-700 text-slate-300';
}

function pairColor(symbol: string | null): string {
  if (!symbol) return 'text-slate-500';
  if (symbol === 'EURUSD') return 'text-sky-400';
  if (symbol === 'AUDUSD') return 'text-emerald-400';
  if (symbol === 'GBPUSD') return 'text-violet-400';
  return 'text-slate-400';
}

function TpBadge({
  label,
  hit,
  hitAt,
  price,
  livePrice,
  isLong,
}: {
  label: string;
  hit: boolean;
  hitAt: string | null;
  price: number | null;
  livePrice: number | null;
  isLong: boolean;
}) {
  const [showTime, setShowTime] = useState(false);

  if (price == null) {
    return <span className="text-slate-600 text-xs">—</span>;
  }

  if (hit) {
    return (
      <span
        className="inline-flex items-center gap-1 text-xs font-medium text-emerald-400 cursor-help"
        onMouseEnter={() => setShowTime(true)}
        onMouseLeave={() => setShowTime(false)}
        title={hitAt ? `Hit at ${formatTime(hitAt)}` : 'Hit'}
      >
        <CheckCircle2 className="w-3.5 h-3.5" />
        {label}
        {showTime && hitAt && (
          <span className="absolute -mt-8 ml-12 text-slate-500 text-[10px] whitespace-nowrap">
            {formatTime(hitAt)}
          </span>
        )}
      </span>
    );
  }

  if (livePrice != null) {
    const distance = isLong ? price - livePrice : livePrice - price;
    const distanceStr = distance > 0
      ? `+${distance.toFixed(5)}`
      : `-${Math.abs(distance).toFixed(5)}`;
    const isClose = Math.abs(distance) < 0.002;
    return (
      <span className={`inline-flex items-center gap-1 text-xs tabular-nums ${
        isClose ? 'text-amber-400' : 'text-slate-500'
      }`}>
        <Clock className="w-3 h-3" />
        {label} {distanceStr}
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1 text-xs text-slate-500">
      <MinusCircle className="w-3 h-3" />
      {label}
    </span>
  );
}

export function SignalsTable({ signals, livePrice }: Props) {
  const [filter, setFilter] = useState<string>('ALL');

  const filtered = filter === 'ALL'
    ? signals
    : signals.filter(s => s.symbol === filter);

  if (signals.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-12 text-center">
        <p className="text-slate-400 text-sm">
          No signals yet. The scanner will push signals here as they are generated.
        </p>
      </div>
    );
  }

  return (
    <div>
      {/* Pair filter tabs */}
      <div className="flex items-center gap-2 mb-4">
        {['ALL', ...TRADED_PAIRS].map((p) => {
          const count = p === 'ALL'
            ? signals.length
            : signals.filter(s => s.symbol === p).length;
          return (
            <button
              key={p}
              onClick={() => setFilter(p)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                filter === p
                  ? 'bg-sky-500/20 text-sky-300 border border-sky-700'
                  : 'bg-slate-800/50 text-slate-400 hover:bg-slate-800 border border-transparent'
              }`}
            >
              {p} <span className="text-slate-600">({count})</span>
            </button>
          );
        })}
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 overflow-hidden">
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400 text-xs uppercase tracking-wider">
                <th className="text-left px-4 py-3 font-medium">Pair</th>
                <th className="text-left px-4 py-3 font-medium">Signal Time</th>
                <th className="text-left px-4 py-3 font-medium">Age</th>
                <th className="text-left px-4 py-3 font-medium">Direction</th>
                <th className="text-left px-4 py-3 font-medium">Grade</th>
                <th className="text-right px-4 py-3 font-medium">Entry</th>
                <th className="text-right px-4 py-3 font-medium">Stop</th>
                <th className="text-center px-4 py-3 font-medium">TP Status</th>
                <th className="text-right px-4 py-3 font-medium">R:R</th>
                <th className="text-left px-4 py-3 font-medium">Type</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((sig) => {
                const isBuy = (sig.direction ?? '').toLowerCase().includes('buy') ||
                              (sig.direction ?? '').toLowerCase().includes('long');
                const signalTime = sig.signal_generated_at ?? sig.created_at;
                return (
                  <tr
                    key={sig.id}
                    className={`border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors ${
                      sig.stop_hit ? 'opacity-50' : ''
                    }`}
                  >
                    <td className="px-4 py-3">
                      <span className={`text-xs font-bold ${pairColor(sig.symbol)}`}>
                        {sig.symbol ?? '—'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-300 whitespace-nowrap">
                      {formatTime(signalTime)}
                    </td>
                    <td className="px-4 py-3 text-slate-500 whitespace-nowrap text-xs">
                      {formatAge(signalTime)}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1 font-medium ${
                        isBuy ? 'text-emerald-400' : 'text-rose-400'
                      }`}>
                        {isBuy
                          ? <ArrowUpRight className="w-3.5 h-3.5" />
                          : <ArrowDownRight className="w-3.5 h-3.5" />}
                        {sig.direction ?? '—'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${gradeColor(sig.grade)}`}>
                        {sig.grade ?? '—'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-slate-200 tabular-nums">
                      {sig.entry?.toFixed(5) ?? '—'}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {sig.stop_hit ? (
                        <span className="inline-flex items-center gap-1 text-rose-400">
                          <XCircle className="w-3.5 h-3.5" />
                          {sig.stop_loss?.toFixed(5) ?? '—'}
                        </span>
                      ) : (
                        <span className="text-rose-300">{sig.stop_loss?.toFixed(5) ?? '—'}</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3 justify-center whitespace-nowrap">
                        <TpBadge
                          label="TP1"
                          hit={sig.tp1_hit}
                          hitAt={sig.tp1_hit_at}
                          price={sig.tp1}
                          livePrice={livePrice}
                          isLong={isBuy}
                        />
                        <TpBadge
                          label="TP2"
                          hit={sig.tp2_hit}
                          hitAt={sig.tp2_hit_at}
                          price={sig.tp2}
                          livePrice={livePrice}
                          isLong={isBuy}
                        />
                        <TpBadge
                          label="TP3"
                          hit={sig.tp3_hit}
                          hitAt={sig.tp3_hit_at}
                          price={sig.tp3}
                          livePrice={livePrice}
                          isLong={isBuy}
                        />
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right text-slate-200 tabular-nums">
                      {sig.rr ?? '—'}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded ${
                        sig.auto_executed
                          ? 'bg-violet-500/20 text-violet-300'
                          : 'bg-slate-700 text-slate-400'
                      }`}>
                        {sig.auto_executed ? 'Auto' : 'Manual'}
                      </span>
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

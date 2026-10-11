import { TrendingUp, TrendingDown, Target, DollarSign, Percent, Activity } from 'lucide-react';
import type { Signal, Trade } from '../lib/supabase';
import { TRADED_PAIRS } from '../lib/supabase';

type Props = {
  signals: Signal[];
  trades: Trade[];
};

export function StatsCards({ signals, trades }: Props) {
  const totalSignals = signals.length;
  const aGrade = signals.filter(s => s.grade?.includes('A')).length;
  const buySignals = signals.filter(s => (s.direction ?? '').toLowerCase().includes('buy') ||
                                          (s.direction ?? '').toLowerCase().includes('long')).length;
  const sellSignals = signals.filter(s => (s.direction ?? '').toLowerCase().includes('sell') ||
                                           (s.direction ?? '').toLowerCase().includes('short')).length;
  const openTrades = trades.filter(t => t.status === 'open').length;
  const closedTrades = trades.filter(t => t.status === 'closed');
  const totalPnl = closedTrades.reduce((sum, t) => sum + (t.pnl_usd ?? 0), 0);
  const wins = closedTrades.filter(t => (t.pnl_usd ?? 0) > 0).length;
  const winRate = closedTrades.length > 0 ? (wins / closedTrades.length) * 100 : 0;

  const cards = [
    {
      label: 'Total Signals',
      value: totalSignals.toString(),
      sub: `${aGrade} A-grade`,
      icon: Target,
      color: 'text-sky-400',
      bg: 'bg-sky-500/10',
    },
    {
      label: 'Buy / Sell',
      value: `${buySignals} / ${sellSignals}`,
      sub: 'Direction split',
      icon: buySignals >= sellSignals ? TrendingUp : TrendingDown,
      color: buySignals >= sellSignals ? 'text-emerald-400' : 'text-rose-400',
      bg: buySignals >= sellSignals ? 'bg-emerald-500/10' : 'bg-rose-500/10',
    },
    {
      label: 'Open Trades',
      value: openTrades.toString(),
      sub: openTrades > 0 ? 'Awaiting close' : 'None open',
      icon: Activity,
      color: 'text-sky-400',
      bg: 'bg-sky-500/10',
    },
    {
      label: 'Win Rate',
      value: `${winRate.toFixed(0)}%`,
      sub: `${wins}W / ${closedTrades.length - wins}L`,
      icon: Percent,
      color: winRate >= 50 ? 'text-emerald-400' : 'text-slate-400',
      bg: winRate >= 50 ? 'bg-emerald-500/10' : 'bg-slate-700/30',
    },
    {
      label: 'Net P&L',
      value: `$${totalPnl.toFixed(2)}`,
      sub: closedTrades.length > 0 ? `${closedTrades.length} closed` : 'No closed trades',
      icon: DollarSign,
      color: totalPnl >= 0 ? 'text-emerald-400' : 'text-rose-400',
      bg: totalPnl >= 0 ? 'bg-emerald-500/10' : 'bg-rose-500/10',
    },
  ];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {cards.map((card) => {
          const Icon = card.icon;
          return (
            <div
              key={card.label}
              className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 hover:border-slate-700 transition-colors"
            >
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs text-slate-400 font-medium">{card.label}</span>
                <div className={`w-8 h-8 rounded-lg ${card.bg} flex items-center justify-center`}>
                  <Icon className={`w-4 h-4 ${card.color}`} />
                </div>
              </div>
              <p className="text-xl font-bold tracking-tight">{card.value}</p>
              <p className="text-xs text-slate-500 mt-1">{card.sub}</p>
            </div>
          );
        })}
      </div>

      {/* Per-pair signal count */}
      <div className="flex items-center gap-3 flex-wrap">
        {TRADED_PAIRS.map((pair) => {
          const count = signals.filter(s => s.symbol === pair).length;
          const aCount = signals.filter(s => s.symbol === pair && s.grade?.includes('A')).length;
          return (
            <div key={pair} className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900/50 border border-slate-800">
              <span className={`text-xs font-bold ${
                pair === 'EURUSD' ? 'text-sky-400' :
                pair === 'AUDUSD' ? 'text-emerald-400' : 'text-violet-400'
              }`}>{pair}</span>
              <span className="text-xs text-slate-400">{count} signals</span>
              {aCount > 0 && <span className="text-xs text-amber-400">{aCount} A-grade</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

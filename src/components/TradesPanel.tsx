import { useState } from 'react';
import { CheckCircle2, Clock, XCircle, TrendingUp, TrendingDown } from 'lucide-react';
import { supabase, type Trade } from '../lib/supabase';

type Props = {
  trades: Trade[];
  title: string;
  isOpen: boolean;
  onUpdate: () => void;
};

function formatTime(ts: string | null): string {
  if (!ts) return '—';
  return new Date(ts).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export function TradesPanel({ trades, title, isOpen, onUpdate }: Props) {
  const [closingId, setClosingId] = useState<string | null>(null);
  const [pnlInput, setPnlInput] = useState('');

  const handleMarkClosed = async (tradeId: string) => {
    const pnl = parseFloat(pnlInput) || 0;
    const { error } = await supabase
      .from('trades')
      .update({
        status: 'closed',
        closed_at: new Date().toISOString(),
        pnl_usd: pnl,
        closed_by_user: true,
      })
      .eq('id', tradeId);
    if (error) {
      alert(`Failed to close trade: ${error.message}`);
      return;
    }
    setClosingId(null);
    setPnlInput('');
    onUpdate();
  };

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        {isOpen ? (
          <Clock className="w-5 h-5 text-sky-400" />
        ) : (
          <CheckCircle2 className="w-5 h-5 text-emerald-400" />
        )}
        <h2 className="text-base font-semibold">{title}</h2>
        <span className="text-xs text-slate-500">({trades.length})</span>
      </div>

      <div className="space-y-3">
        {trades.map((trade) => {
          const isBuy = trade.direction?.toLowerCase().includes('buy');
          const isProfit = (trade.pnl_usd ?? 0) >= 0;
          return (
            <div
              key={trade.id}
              className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 hover:border-slate-700 transition-colors"
            >
              <div className="flex items-start justify-between flex-wrap gap-3">
                <div className="flex items-center gap-3">
                  <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${
                    isBuy ? 'bg-emerald-500/10' : 'bg-rose-500/10'
                  }`}>
                    {isBuy
                      ? <TrendingUp className="w-4 h-4 text-emerald-400" />
                      : <TrendingDown className="w-4 h-4 text-rose-400" />}
                  </div>
                  <div>
                    <p className="font-medium text-sm">
                      {trade.direction ?? '—'}
                      {trade.is_manual && (
                        <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300">
                          Manual
                        </span>
                      )}
                    </p>
                    <p className="text-xs text-slate-500">{formatTime(trade.created_at)}</p>
                  </div>
                </div>

                <div className="flex items-center gap-6 text-sm">
                  <div>
                    <p className="text-xs text-slate-500">Entry</p>
                    <p className="tabular-nums font-medium">{trade.entry_price?.toFixed(5) ?? '—'}</p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">Stop Loss</p>
                    <p className="tabular-nums text-rose-300">{trade.stop_loss?.toFixed(5) ?? '—'}</p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">Take Profit</p>
                    <p className="tabular-nums text-emerald-300">{trade.take_profit?.toFixed(5) ?? '—'}</p>
                  </div>
                  {!isOpen && (
                    <div>
                      <p className="text-xs text-slate-500">P&L</p>
                      <p className={`tabular-nums font-bold ${isProfit ? 'text-emerald-400' : 'text-rose-400'}`}>
                        ${(trade.pnl_usd ?? 0).toFixed(2)}
                      </p>
                    </div>
                  )}
                </div>
              </div>

              {/* Close trade confirmation — only for open trades */}
              {isOpen && (
                <div className="mt-4 pt-4 border-t border-slate-800">
                  {closingId === trade.id ? (
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className="text-sm text-slate-300">
                        Is this trade closed? Enter the realized P&L in USD:
                      </span>
                      <input
                        type="number"
                        step="0.01"
                        value={pnlInput}
                        onChange={(e) => setPnlInput(e.target.value)}
                        placeholder="e.g. 150.00 or -50.00"
                        className="w-40 px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-sm focus:outline-none focus:border-amber-500"
                        autoFocus
                      />
                      <button
                        onClick={() => handleMarkClosed(trade.id)}
                        className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition-colors"
                      >
                        Confirm Closed
                      </button>
                      <button
                        onClick={() => { setClosingId(null); setPnlInput(''); }}
                        className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setClosingId(trade.id)}
                      className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-medium transition-colors"
                    >
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      Mark as Closed
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

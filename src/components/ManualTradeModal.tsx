import { useState } from 'react';
import { X, TrendingUp, TrendingDown } from 'lucide-react';
import { supabase, type Signal, TRADED_PAIRS } from '../lib/supabase';

type Props = {
  signals: Signal[];
  onClose: () => void;
  onSaved: () => void;
};

export function ManualTradeModal({ signals, onClose, onSaved }: Props) {
  const [symbol, setSymbol] = useState<string>('EURUSD');
  const [direction, setDirection] = useState('BUY');
  const [entryPrice, setEntryPrice] = useState('');
  const [stopLoss, setStopLoss] = useState('');
  const [takeProfit, setTakeProfit] = useState('');
  const [linkedSignalId, setLinkedSignalId] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);

    const entry = parseFloat(entryPrice);
    const sl = parseFloat(stopLoss);
    const tp = parseFloat(takeProfit);

    if (isNaN(entry) || isNaN(sl) || isNaN(tp)) {
      setError('Please enter valid numbers for entry, stop loss, and take profit.');
      setSaving(false);
      return;
    }

    const payload: Record<string, unknown> = {
      direction,
      entry_price: entry,
      stop_loss: sl,
      take_profit: tp,
      is_manual: true,
      status: 'open',
    };
    if (linkedSignalId) payload.signal_id = linkedSignalId;

    const { error: insertError } = await supabase.from('trades').insert(payload);

    if (insertError) {
      setError(insertError.message);
      setSaving(false);
      return;
    }

    setSaving(false);
    onSaved();
    onClose();
  };

  const useSignalData = (signalId: string) => {
    setLinkedSignalId(signalId);
    if (!signalId) return;
    const sig = signals.find(s => s.id === signalId);
    if (sig) {
      if (sig.symbol) setSymbol(sig.symbol);
      setDirection(sig.direction ?? 'BUY');
      if (sig.entry) setEntryPrice(sig.entry.toString());
      if (sig.stop_loss) setStopLoss(sig.stop_loss.toString());
      if (sig.tp1) setTakeProfit(sig.tp1.toString());
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <h2 className="text-base font-semibold">Log Manual Trade</h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-slate-800 transition-colors"
          >
            <X className="w-4 h-4 text-slate-400" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
          {error && (
            <div className="p-3 rounded-lg bg-red-950/50 border border-red-800 text-red-200 text-sm">
              {error}
            </div>
          )}

          {/* Pair selector */}
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Currency Pair</label>
            <div className="flex gap-2">
              {TRADED_PAIRS.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setSymbol(p)}
                  className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                    symbol === p
                      ? 'bg-sky-500/20 text-sky-300 border border-sky-700'
                      : 'bg-slate-800 text-slate-400 hover:bg-slate-700 border border-transparent'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {signals.length > 0 && (
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">
                Link to signal (optional — auto-fills fields)
              </label>
              <select
                value={linkedSignalId}
                onChange={(e) => useSignalData(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-sm focus:outline-none focus:border-sky-500"
              >
                <option value="">No linked signal</option>
                {signals.slice(0, 20).map(sig => (
                  <option key={sig.id} value={sig.id}>
                    {sig.symbol ?? '?'} · {sig.direction ?? '?'} · {sig.grade ?? '?'} ·{' '}
                    {sig.entry?.toFixed(5) ?? '?'} ·{' '}
                    {new Date(sig.created_at).toLocaleDateString()}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Direction</label>
            <div className="flex gap-2">
              {['BUY', 'SELL'].map(dir => {
                const isBuy = dir === 'BUY';
                const active = direction === dir;
                return (
                  <button
                    key={dir}
                    type="button"
                    onClick={() => setDirection(dir)}
                    className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                      active
                        ? isBuy
                          ? 'bg-emerald-600 text-white'
                          : 'bg-rose-600 text-white'
                        : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                    }`}
                  >
                    {isBuy
                      ? <TrendingUp className="w-4 h-4" />
                      : <TrendingDown className="w-4 h-4" />}
                    {dir}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3">
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Entry Price</label>
              <input
                type="number"
                step="0.00001"
                value={entryPrice}
                onChange={(e) => setEntryPrice(e.target.value)}
                placeholder="e.g. 1.08500"
                required
                className="w-full px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-sm focus:outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Stop Loss</label>
              <input
                type="number"
                step="0.00001"
                value={stopLoss}
                onChange={(e) => setStopLoss(e.target.value)}
                placeholder="e.g. 1.08300"
                required
                className="w-full px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-sm focus:outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Take Profit</label>
              <input
                type="number"
                step="0.00001"
                value={takeProfit}
                onChange={(e) => setTakeProfit(e.target.value)}
                placeholder="e.g. 1.08800"
                required
                className="w-full px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-sm focus:outline-none focus:border-sky-500"
              />
            </div>
          </div>

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-medium transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex-1 px-4 py-2.5 rounded-lg bg-sky-500 hover:bg-sky-400 disabled:opacity-50 text-slate-900 text-sm font-bold transition-colors"
            >
              {saving ? 'Saving...' : 'Save Trade'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

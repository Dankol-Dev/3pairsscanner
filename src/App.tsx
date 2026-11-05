import { useEffect, useState, useCallback } from 'react';
import {
  TrendingUp, TrendingDown, Activity, Target, Clock,
  CheckCircle2, AlertCircle, DollarSign, Percent,
  RefreshCw, ArrowUpRight, ArrowDownRight, Zap,
  Grid3x3, GitBranch,
} from 'lucide-react';
import { supabase, type Signal, type Trade } from './lib/supabase';
import { StatsCards } from './components/StatsCards';
import { SignalsTable } from './components/SignalsTable';
import { TradesPanel } from './components/TradesPanel';
import { ManualTradeModal } from './components/ManualTradeModal';
import { LivePriceCard } from './components/LivePriceCard';
import { SweepTable } from './components/SweepTable';
import { WalkforwardTable } from './components/WalkforwardTable';

function App() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showManualModal, setShowManualModal] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [livePrice, setLivePrice] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<'signals' | 'sweep' | 'walkforward'>('signals');

  const fetchData = useCallback(async () => {
    setError(null);
    const [sigRes, tradeRes] = await Promise.all([
      supabase.from('signals').select('*').order('created_at', { ascending: false }).limit(100),
      supabase.from('trades').select('*').order('created_at', { ascending: false }).limit(50),
    ]);
    if (sigRes.error) setError(sigRes.error.message);
    if (tradeRes.error) setError(tradeRes.error.message);
    setSignals(sigRes.data ?? []);
    setTrades(tradeRes.data ?? []);
    setLoading(false);
    setLastRefresh(new Date());
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [fetchData]);

  useEffect(() => {
    const channel = supabase
      .channel('signals-changes')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'signals' },
        () => fetchData())
      .on('postgres_changes', { event: '*', schema: 'public', table: 'trades' },
        () => fetchData())
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [fetchData]);

  const openTrades = trades.filter(t => t.status === 'open');
  const closedTrades = trades.filter(t => t.status === 'closed');

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <RefreshCw className="w-8 h-8 text-sky-400 animate-spin" />
          <p className="text-slate-400">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-sky-400 to-sky-600 flex items-center justify-center shadow-lg shadow-sky-500/20">
              <Activity className="w-5 h-5 text-slate-900" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight">Forex Scanner</h1>
              <p className="text-xs text-slate-400">EURUSD · AUDUSD · GBPUSD · Day Trading</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-xs text-slate-500 hidden sm:inline">
              Updated {lastRefresh.toLocaleTimeString()}
            </span>
            <button
              onClick={fetchData}
              className="p-2 rounded-lg hover:bg-slate-800 transition-colors"
              title="Refresh"
            >
              <RefreshCw className="w-4 h-4 text-slate-400" />
            </button>
            <button
              onClick={() => setShowManualModal(true)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-900 font-medium text-sm transition-colors shadow-lg shadow-sky-500/20"
            >
              <Zap className="w-4 h-4" />
              Log Manual Trade
            </button>
          </div>
        </div>
      </header>

      {/* Tab navigation */}
      <div className="border-b border-slate-800 bg-slate-900/30">
        <div className="max-w-7xl mx-auto px-6 flex gap-1">
          {[
            { key: 'signals', label: 'Signals', icon: Target },
            { key: 'sweep', label: 'Parameter Sweep', icon: Grid3x3 },
            { key: 'walkforward', label: 'Walk-Forward', icon: GitBranch },
          ].map(tab => {
            const Icon = tab.icon;
            const active = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key as typeof activeTab)}
                className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                  active
                    ? 'border-sky-500 text-sky-300'
                    : 'border-transparent text-slate-400 hover:text-slate-200 hover:border-slate-700'
                }`}
              >
                <Icon className="w-4 h-4" />
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      <main className="max-w-7xl mx-auto px-6 py-8 space-y-8">
        {error && (
          <div className="flex items-center gap-3 p-4 rounded-xl bg-red-950/50 border border-red-800 text-red-200">
            <AlertCircle className="w-5 h-5 flex-shrink-0" />
            <span className="text-sm">{error}</span>
          </div>
        )}

        {/* Always-visible live prices + stats */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-1">
            <LivePriceCard onPriceUpdate={(price) => setLivePrice(price)} />
          </div>
          <div className="lg:col-span-2">
            <StatsCards signals={signals} trades={trades} />
          </div>
        </div>

        {/* Signals tab content */}
        {activeTab === 'signals' && (
          <>
            {openTrades.length > 0 && (
              <TradesPanel
                trades={openTrades}
                title="Open Trades"
                isOpen
                onUpdate={fetchData}
              />
            )}

            <div>
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Target className="w-5 h-5 text-sky-400" />
                  <h2 className="text-base font-semibold">Recent Signals</h2>
                  <span className="text-xs text-slate-500">({signals.length})</span>
                </div>
              </div>
              <SignalsTable signals={signals} livePrice={livePrice} />
            </div>

            {closedTrades.length > 0 && (
              <TradesPanel
                trades={closedTrades}
                title="Trade History"
                isOpen={false}
                onUpdate={fetchData}
              />
            )}
          </>
        )}

        {/* Parameter sweep tab content */}
        {activeTab === 'sweep' && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Grid3x3 className="w-5 h-5 text-sky-400" />
                <h2 className="text-base font-semibold">Parameter Sensitivity Sweep</h2>
              </div>
            </div>
            <SweepTable />
          </div>
        )}

        {/* Walk-forward tab content */}
        {activeTab === 'walkforward' && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <GitBranch className="w-5 h-5 text-sky-400" />
                <h2 className="text-base font-semibold">Walk-Forward Analysis</h2>
              </div>
            </div>
            <WalkforwardTable />
          </div>
        )}
      </main>

      {showManualModal && (
        <ManualTradeModal
          signals={signals}
          onClose={() => setShowManualModal(false)}
          onSaved={fetchData}
        />
      )}
    </div>
  );
}

export default App;

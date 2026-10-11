import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

export type Signal = {
  id: string;
  created_at: string;
  symbol: string | null;
  timestamp_utc: string | null;
  direction: string | null;
  grade: string | null;
  confluence: string | null;
  entry: number | null;
  stop_loss: number | null;
  tp1: number | null;
  tp2: number | null;
  tp3: number | null;
  rr: string | null;
  net_rr: number | null;
  risk_pct: number | null;
  risk_usd: number | null;
  lot_size: number | null;
  reasons: string | null;
  regime: string | null;
  atr_pctl: number | null;
  auto_executed: boolean;
  tp1_hit: boolean;
  tp2_hit: boolean;
  tp3_hit: boolean;
  tp1_hit_at: string | null;
  tp2_hit_at: string | null;
  tp3_hit_at: string | null;
  stop_hit: boolean;
  stop_hit_at: string | null;
  signal_generated_at: string | null;
};

export type Trade = {
  id: string;
  signal_id: string | null;
  created_at: string;
  direction: string | null;
  entry_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  is_manual: boolean;
  status: 'open' | 'closed';
  closed_at: string | null;
  pnl_usd: number | null;
  closed_by_user: boolean;
};

export type PriceTick = {
  price: number;
  bid: number | null;
  ask: number | null;
  spread: number | null;
  source: string;
  symbol: string;
  timestamp: string;
};

export const TRADED_PAIRS = ['EURUSD', 'AUDUSD', 'GBPUSD'] as const;
export type PairName = typeof TRADED_PAIRS[number];

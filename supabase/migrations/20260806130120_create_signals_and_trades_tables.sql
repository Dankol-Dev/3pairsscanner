/*
# Create signals and trades tables for the gold scanner dashboard

1. New Tables
- `signals`: Stores every signal the gold scanner produces (direction, grade,
  entry, stop loss, TP1/TP2/TP3, R:R, lot size, reasons, regime, etc.).
  Populated by the Python scanner via the Supabase REST API.
- `trades`: Stores user-confirmed manual trades linked to a signal, including
  the user-input entry price, stop loss, take profit, open/closed status,
  and realized P&L. Auto-executed trades also land here with is_manual=false.

2. Columns
signals:
  id, created_at, timestamp_utc, direction, grade, confluence, entry,
  stop_loss, tp1, tp2, tp3, rr, net_rr, risk_pct, risk_usd, lot_size,
  reasons, regime, atr_pctl, auto_executed

trades:
  id, signal_id (FK->signals, nullable), created_at, direction,
  entry_price, stop_loss, take_profit, is_manual, status (open/closed),
  closed_at, pnl_usd, closed_by_user

3. Security
- Both tables are single-tenant (no auth/sign-in screen).
- RLS enabled on both; CRUD open to anon + authenticated since the app
  has no login and the data is intentionally shared.
- USING (true) is correct here because there is no user ownership concept.

4. Notes
- signal_id is nullable because a user could log a manual trade that wasn't
  from a scanner signal.
- status defaults to 'open' so newly created trades start in the open state.
- closed_at and pnl_usd are nullable; they get filled when the user confirms
  the trade is closed on the dashboard.
*/

CREATE TABLE IF NOT EXISTS signals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  timestamp_utc text,
  direction text,
  grade text,
  confluence text,
  entry float8,
  stop_loss float8,
  tp1 float8,
  tp2 float8,
  tp3 float8,
  rr text,
  net_rr float8,
  risk_pct float8,
  risk_usd float8,
  lot_size float8,
  reasons text,
  regime text,
  atr_pctl float8,
  auto_executed boolean NOT NULL DEFAULT false
);

ALTER TABLE signals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "anon_select_signals" ON signals;
CREATE POLICY "anon_select_signals" ON signals FOR SELECT
  TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "anon_insert_signals" ON signals;
CREATE POLICY "anon_insert_signals" ON signals FOR INSERT
  TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "anon_update_signals" ON signals;
CREATE POLICY "anon_update_signals" ON signals FOR UPDATE
  TO anon, authenticated USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "anon_delete_signals" ON signals;
CREATE POLICY "anon_delete_signals" ON signals FOR DELETE
  TO anon, authenticated USING (true);

CREATE TABLE IF NOT EXISTS trades (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id uuid REFERENCES signals(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  direction text,
  entry_price float8,
  stop_loss float8,
  take_profit float8,
  is_manual boolean NOT NULL DEFAULT true,
  status text NOT NULL DEFAULT 'open',
  closed_at timestamptz,
  pnl_usd float8,
  closed_by_user boolean NOT NULL DEFAULT false
);

ALTER TABLE trades ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "anon_select_trades" ON trades;
CREATE POLICY "anon_select_trades" ON trades FOR SELECT
  TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "anon_insert_trades" ON trades;
CREATE POLICY "anon_insert_trades" ON trades FOR INSERT
  TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "anon_update_trades" ON trades;
CREATE POLICY "anon_update_trades" ON trades FOR UPDATE
  TO anon, authenticated USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "anon_delete_trades" ON trades;
CREATE POLICY "anon_delete_trades" ON trades FOR DELETE
  TO anon, authenticated USING (true);

CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_signal_id ON trades (signal_id);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades (status);

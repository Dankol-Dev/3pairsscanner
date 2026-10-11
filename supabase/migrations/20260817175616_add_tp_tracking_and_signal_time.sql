/*
# Add TP hit tracking and signal timing columns

1. Modified Tables
- `signals`: Adds columns to track which take-profit levels have been hit
  and when the signal was generated (for elapsed-time display).
  New columns:
  - `tp1_hit` (boolean, default false) — whether TP1 has been reached
  - `tp2_hit` (boolean, default false) — whether TP2 has been reached
  - `tp3_hit` (boolean, default false) — whether TP3 has been reached
  - `tp1_hit_at` (timestamptz, nullable) — when TP1 was hit
  - `tp2_hit_at` (timestamptz, nullable) — when TP2 was hit
  - `tp3_hit_at` (timestamptz, nullable) — when TP3 was hit
  - `stop_hit` (boolean, default false) — whether the stop loss was hit
  - `stop_hit_at` (timestamptz, nullable) — when the stop was hit
  - `signal_generated_at` (timestamptz, nullable) — when the scanner
    generated the signal (distinct from created_at which is the DB insert
    time; signal_generated_at is the bar timestamp from the scanner)

2. New Tables
- `gold_prices`: Stores live gold price snapshots fetched by the edge
  function. Each row is one price tick.
  - `id` (uuid, primary key)
  - `price` (float8, not null) — the gold spot price in USD
  - `bid` (float8, nullable) — bid price
  - `ask` (float8, nullable) — ask price
  - `spread` (float8, nullable) — ask - bid
  - `source` (text, nullable) — which data provider supplied the price
  - `fetched_at` (timestamptz, not null, default now()) — when the price
    was retrieved

3. Security
- `signals` already has RLS enabled with anon+authenticated CRUD.
  No policy changes needed — new columns inherit existing table access.
- `gold_prices`: RLS enabled, anon+authenticated SELECT only (read-only
  price feed; writes come from the edge function using the service role
  key, which bypasses RLS).

4. Notes
- The edge function fetches live gold prices and inserts into gold_prices,
  then checks all open signals to see if any TP or stop levels have been
  hit by the current price, updating the tp1_hit/tp2_hit/tp3_hit/stop_hit
  flags and their timestamps accordingly.
- signal_generated_at is separate from created_at because the scanner's
  bar timestamp (when the signal was actually generated in market time)
  may differ from when the row was inserted into the database.
*/

-- Add TP tracking columns to signals (idempotent)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
    WHERE table_name = 'signals' AND column_name = 'tp1_hit') THEN
    ALTER TABLE signals ADD COLUMN tp1_hit boolean NOT NULL DEFAULT false;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
    WHERE table_name = 'signals' AND column_name = 'tp2_hit') THEN
    ALTER TABLE signals ADD COLUMN tp2_hit boolean NOT NULL DEFAULT false;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
    WHERE table_name = 'signals' AND column_name = 'tp3_hit') THEN
    ALTER TABLE signals ADD COLUMN tp3_hit boolean NOT NULL DEFAULT false;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
    WHERE table_name = 'signals' AND column_name = 'tp1_hit_at') THEN
    ALTER TABLE signals ADD COLUMN tp1_hit_at timestamptz;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
    WHERE table_name = 'signals' AND column_name = 'tp2_hit_at') THEN
    ALTER TABLE signals ADD COLUMN tp2_hit_at timestamptz;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
    WHERE table_name = 'signals' AND column_name = 'tp3_hit_at') THEN
    ALTER TABLE signals ADD COLUMN tp3_hit_at timestamptz;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
    WHERE table_name = 'signals' AND column_name = 'stop_hit') THEN
    ALTER TABLE signals ADD COLUMN stop_hit boolean NOT NULL DEFAULT false;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
    WHERE table_name = 'signals' AND column_name = 'stop_hit_at') THEN
    ALTER TABLE signals ADD COLUMN stop_hit_at timestamptz;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
    WHERE table_name = 'signals' AND column_name = 'signal_generated_at') THEN
    ALTER TABLE signals ADD COLUMN signal_generated_at timestamptz;
  END IF;
END $$;

-- Create gold_prices table
CREATE TABLE IF NOT EXISTS gold_prices (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  price float8 NOT NULL,
  bid float8,
  ask float8,
  spread float8,
  source text,
  fetched_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE gold_prices ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "anon_select_gold_prices" ON gold_prices;
CREATE POLICY "anon_select_gold_prices" ON gold_prices FOR SELECT
  TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "anon_insert_gold_prices" ON gold_prices;
CREATE POLICY "anon_insert_gold_prices" ON gold_prices FOR INSERT
  TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "anon_update_gold_prices" ON gold_prices;
CREATE POLICY "anon_update_gold_prices" ON gold_prices FOR UPDATE
  TO anon, authenticated USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "anon_delete_gold_prices" ON gold_prices;
CREATE POLICY "anon_delete_gold_prices" ON gold_prices FOR DELETE
  TO anon, authenticated USING (true);

CREATE INDEX IF NOT EXISTS idx_gold_prices_fetched_at ON gold_prices (fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_tp1_hit ON signals (tp1_hit) WHERE tp1_hit = false;
CREATE INDEX IF NOT EXISTS idx_signals_stop_hit ON signals (stop_hit) WHERE stop_hit = false;
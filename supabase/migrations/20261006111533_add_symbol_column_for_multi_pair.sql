/*
# Add symbol column for multi-pair forex scanner

1. Modified Tables
- `signals`: Adds `symbol` column to identify which forex pair a signal
  belongs to (EURUSD, AUDUSD, GBPUSD, etc.). Defaults to 'XAUUSD' for
  backward compatibility with existing gold signals.
- `gold_prices`: Renamed conceptually to `price_ticks` — adds `symbol`
  column so prices for multiple pairs can be stored. Existing gold price
  rows default to 'XAUUSD'.

2. New Columns
- signals.symbol (text, NOT NULL, default 'XAUUSD') — the trading pair
- gold_prices.symbol (text, NOT NULL, default 'XAUUSD') — the trading pair

3. Security
- No policy changes — new columns inherit existing table access.

4. Notes
- The scanner now supports EURUSD, AUDUSD, and GBPUSD. Each signal
  row carries its symbol so the dashboard can group/filter by pair.
- The price feed stores ticks per symbol.
*/

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
    WHERE table_name = 'signals' AND column_name = 'symbol') THEN
    ALTER TABLE signals ADD COLUMN symbol text NOT NULL DEFAULT 'XAUUSD';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
    WHERE table_name = 'gold_prices' AND column_name = 'symbol') THEN
    ALTER TABLE gold_prices ADD COLUMN symbol text NOT NULL DEFAULT 'XAUUSD';
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals (symbol);
CREATE INDEX IF NOT EXISTS idx_gold_prices_symbol_time ON gold_prices (symbol, fetched_at DESC);
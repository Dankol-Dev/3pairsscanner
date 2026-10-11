/*
  Add mode column to signals table for day/scalp signal differentiation
*/

ALTER TABLE signals ADD COLUMN IF NOT EXISTS mode text DEFAULT 'day';

-- Optional: add check constraint for valid modes
-- ALTER TABLE signals ADD CONSTRAINT signals_mode_check CHECK (mode IN ('day', 'scalp'));

COMMENT ON COLUMN signals.mode IS 'Signal engine mode: "day" for day-trading (15m/5m), "scalp" for scalping (5m/1m)';
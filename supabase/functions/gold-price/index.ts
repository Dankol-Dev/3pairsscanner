import { createClient } from "npm:@supabase/supabase-js@2.45.4";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Client-Info, Apikey",
};

const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
const supabaseServiceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const supabase = createClient(supabaseUrl, supabaseServiceKey, {
  auth: { persistSession: false },
});

interface PriceResponse {
  price: number;
  bid?: number;
  ask?: number;
  spread?: number;
  source: string;
  timestamp: string;
}

// Yahoo Finance chart symbols for the three traded pairs.
const PAIR_SYMBOLS: Record<string, string> = {
  EURUSD: "EURUSD=X",
  AUDUSD: "AUDUSD=X",
  GBPUSD: "GBPUSD=X",
};

async function fetchPairPriceFromYahoo(symbol: string): Promise<PriceResponse | null> {
  try {
    const resp = await fetch(
      `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?interval=1m&range=1d`,
      {
        headers: { "User-Agent": "fx-scanner-edge/1.0" },
        signal: AbortSignal.timeout(8000),
      }
    );
    if (!resp.ok) return null;
    const data = await resp.json();
    const result = data?.chart?.result?.[0];
    if (!result) return null;
    const meta = result.meta;
    const price = meta?.regularMarketPrice ?? meta?.previousClose;
    if (price == null) return null;
    return {
      price: parseFloat(price),
      source: "yahoo-finance",
      timestamp: new Date().toISOString(),
    };
  } catch {
    return null;
  }
}

async function fetchLivePairPrice(pair: string): Promise<PriceResponse | null> {
  const yfSym = PAIR_SYMBOLS[pair];
  if (!yfSym) return null;
  return fetchPairPriceFromYahoo(yfSym);
}

async function checkSignalHits(pair: string, price: number): Promise<void> {
  const { data: activeSignals } = await supabase
    .from("signals")
    .select("id, direction, entry, stop_loss, tp1, tp2, tp3, tp1_hit, tp2_hit, tp3_hit, stop_hit")
    .eq("symbol", pair)
    .eq("stop_hit", false)
    .not("entry", "is", null)
    .not("tp1", "is", null)
    .limit(200);

  if (!activeSignals || activeSignals.length === 0) return;

  const now = new Date().toISOString();
  const updates: Array<{ id: string; data: Record<string, unknown> }> = [];

  for (const sig of activeSignals) {
    const isLong = (sig.direction ?? "").toUpperCase().includes("LONG") ||
      (sig.direction ?? "").toUpperCase().includes("BUY");
    const update: Record<string, unknown> = {};

    if (isLong) {
      if (!sig.tp1_hit && sig.tp1 != null && price >= sig.tp1) {
        update.tp1_hit = true;
        update.tp1_hit_at = now;
      }
      if (!sig.tp2_hit && sig.tp2 != null && price >= sig.tp2) {
        update.tp2_hit = true;
        update.tp2_hit_at = now;
      }
      if (!sig.tp3_hit && sig.tp3 != null && price >= sig.tp3) {
        update.tp3_hit = true;
        update.tp3_hit_at = now;
      }
      if (sig.stop_loss != null && price <= sig.stop_loss) {
        update.stop_hit = true;
        update.stop_hit_at = now;
      }
    } else {
      if (!sig.tp1_hit && sig.tp1 != null && price <= sig.tp1) {
        update.tp1_hit = true;
        update.tp1_hit_at = now;
      }
      if (!sig.tp2_hit && sig.tp2 != null && price <= sig.tp2) {
        update.tp2_hit = true;
        update.tp2_hit_at = now;
      }
      if (!sig.tp3_hit && sig.tp3 != null && price <= sig.tp3) {
        update.tp3_hit = true;
        update.tp3_hit_at = now;
      }
      if (sig.stop_loss != null && price >= sig.stop_loss) {
        update.stop_hit = true;
        update.stop_hit_at = now;
      }
    }

    if (Object.keys(update).length > 0) {
      updates.push({ id: sig.id, data: update });
    }
  }

  for (const { id, data } of updates) {
    await supabase.from("signals").update(data).eq("id", id);
  }
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 200, headers: corsHeaders });
  }

  try {
    const url = new URL(req.url);
    const requestedPair = url.searchParams.get("pair");
    const checkHits = url.searchParams.get("check") !== "false";

    const pairsToFetch = requestedPair ? [requestedPair] : Object.keys(PAIR_SYMBOLS);
    const results: Record<string, PriceResponse | null> = {};

    for (const pair of pairsToFetch) {
      const priceData = await fetchLivePairPrice(pair);
      results[pair] = priceData;

      if (priceData) {
        const { error: insertError } = await supabase.from("gold_prices").insert({
          price: priceData.price,
          bid: priceData.bid ?? null,
          ask: priceData.ask ?? null,
          spread: priceData.spread ?? null,
          source: priceData.source,
          symbol: pair,
        });
        if (insertError) {
          console.error(`Failed to store ${pair} price:`, insertError.message);
        }

        if (checkHits) {
          await checkSignalHits(pair, priceData.price);
        }
      }
    }

    if (requestedPair) {
      const priceData = results[requestedPair];
      if (!priceData) {
        return new Response(
          JSON.stringify({ error: `All price providers unavailable for ${requestedPair}`, price: null }),
          { status: 503, headers: { ...corsHeaders, "Content-Type": "application/json" } }
        );
      }
      return new Response(
        JSON.stringify({ ...priceData, symbol: requestedPair }),
        { status: 200, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    return new Response(
      JSON.stringify({ prices: results }),
      { status: 200, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  } catch (err) {
    return new Response(
      JSON.stringify({ error: (err as Error).message, price: null }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
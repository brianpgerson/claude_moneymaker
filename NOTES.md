# Claude MoneyMaker - Project Notes

## Overview

An aggressive crypto trading bot where Opus 4.5 attempts to turn $250 into something more. Runs every 2 hours, makes portfolio-level allocation decisions, goes big or goes home.

---

## Architecture (v2)

```
Every 2 hours:

┌─────────────────────────────────────────────────────────────┐
│                     DATA COLLECTION                          │
│  - Sync balances from Binance (what do we actually own?)    │
│  - Cancel any pending orders                                 │
│  - Fetch top 50 coins by 24h volume (our universe)          │
│  - Get OHLCV + technicals for each                          │
│  - Get Fear & Greed Index                                   │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                      OPUS 4.5                                │
│  "Here's what you own, here's the market, GO."              │
│                                                              │
│  Input: ~1000 tokens (condensed market brief)               │
│  Output: Target allocation via tool use                      │
│                                                              │
│  Philosophy: AGGRESSIVE. Bet big. Ride winners. Dump losers.│
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     EXECUTION                                │
│  - Calculate trades needed: current → target                │
│  - Sells first (free up USDT)                               │
│  - Then buys                                                │
│  - All trades route through USDT pairs                      │
│  - Skip trades < $10 (Binance minimum)                      │
└─────────────────────────────────────────────────────────────┘
```

---

## The Prompts

### System Prompt

```
You are an aggressive crypto trader managing a small degen portfolio (~$250).
Your goal is to maximize returns. You are NOT here to preserve capital.

PHILOSOPHY:
- This is gambling money. Act like it.
- Concentration > diversification. Bet big on your best ideas.
- Momentum is everything. Ride winners hard, dump losers fast.
- If you're not uncomfortable, you're not aggressive enough.
- Would rather blow up trying to 10x than slowly bleed out.

CONSTRAINTS:
- Minimum position: $10 (Binance minimum)
- Maximum single position: 80% of portfolio
- Cash reserve: 5% minimum (just enough to not get stuck)
- All trades go through USDT pairs

OUTPUT:
You must call the set_portfolio_allocation tool with your target allocation.
Include brief reasoning for significant moves.
```

### Turn Prompt (each cycle)

```
CURRENT PORTFOLIO:
Total value: ${total}
Holdings:
{for each holding: symbol, quantity, value, % of portfolio, entry price, P&L %}

MARKET CONTEXT:
- Fear & Greed Index: {score} ({label})
- BTC 24h: {change}%
- Market trend: {description}

TOP 50 COINS BY VOLUME:
| Symbol | Price | 24h % | RSI | MACD | Vol Spike |
{table of coins with technicals}

NOTABLE SETUPS:
{coins with interesting signals - oversold, breakouts, etc}

---

Set your target portfolio allocation.
```

### Tool Definition

```python
{
    "name": "set_portfolio_allocation",
    "description": "Set target portfolio allocation. Allocations + cash must sum to 100%.",
    "input_schema": {
        "type": "object",
        "properties": {
            "allocations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "percent": {"type": "number"},
                        "reasoning": {"type": "string"}
                    },
                    "required": ["symbol", "percent", "reasoning"]
                }
            },
            "usdt_percent": {"type": "number"},
            "market_outlook": {"enum": ["bullish", "neutral", "bearish"]},
            "conviction": {"enum": ["low", "medium", "high", "maximum"]}
        },
        "required": ["allocations", "usdt_percent"]
    }
}
```

---

## Cost Breakdown

| Item | Monthly Cost |
|------|--------------|
| Opus 4.5 (12 calls/day) | ~$5 |
| DigitalOcean droplet | $5 |
| Fear & Greed API | Free |
| Binance API | Free |
| **Total** | **~$10/month** |

Break-even: ~4% monthly returns on $250.

---

## Key Design Decisions

### 1. Claude picks the universe
- Fetch top 50 coins by 24h volume from Binance
- No user-specified symbols
- Refreshed each cycle

### 2. Portfolio-level decisions
- Not "should I buy DOGE?" but "how should my portfolio look?"
- Claude sees everything, decides allocation across all opportunities
- More like a portfolio manager than a per-coin trader

### 3. Tool use for structured output
- Guarantees parseable allocation output
- No regex parsing of text

### 4. Sync from exchange each cycle
- Cancel all pending orders at start of cycle
- Fetch real balances from Binance
- Ground truth, no drift

### 5. All trades through USDT
- Simplest routing
- Best liquidity for meme coins
- Fee difference negligible at our scale

### 6. Aggressive philosophy
- Max 80% in single position
- Only 5% cash reserve minimum
- Ride winners, cut losers
- Would rather blow up than bleed out

### 7. Stateless Claude
- No memory of past decisions
- Fresh eyes each cycle
- We track history in SQLite for our analysis

---

## Files to Change

### Delete/Simplify:
- `strategies/` - Remove all individual strategies
- `core/allocator.py` - No longer needed (Claude IS the allocator)

### Modify:
- `core/engine.py` - New cycle flow
- `core/executor.py` - Add cancel_all_orders(), sync_balances()
- `core/portfolio.py` - Add decisions table, simplify position tracking
- `data/market.py` - Add get_top_by_volume(), bulk OHLCV fetch
- `config.py` - Update defaults (2h interval, etc.)
- `cli.py` - Simplify (no symbol args)

### Add:
- `core/brain.py` - Opus integration with tool use

---

## Database Schema (v2)

```sql
-- Record of every trade
orders (
    id TEXT PRIMARY KEY,
    timestamp TEXT,
    symbol TEXT,
    side TEXT,  -- buy/sell
    quantity REAL,
    price REAL,
    status TEXT
)

-- Claude's decisions (for analysis)
decisions (
    id INTEGER PRIMARY KEY,
    timestamp TEXT,
    portfolio_before TEXT,  -- JSON
    market_summary TEXT,    -- JSON (what Claude saw)
    target_allocation TEXT, -- JSON (what Claude decided)
    conviction TEXT,
    reasoning TEXT,
    trades_executed TEXT    -- JSON (what we actually did)
)

-- Portfolio snapshots over time
snapshots (
    id INTEGER PRIMARY KEY,
    timestamp TEXT,
    total_value REAL,
    holdings TEXT,  -- JSON
    pnl_absolute REAL,
    pnl_percent REAL
)
```

---

## Running the Bot

### Paper Trading (testing)
```bash
moneymaker run --paper
```

### Live Trading (real money)
```bash
moneymaker run --live  # Requires confirmation
```

### Check Status
```bash
moneymaker status
# Or visit http://localhost:8080
```

---

## Deployment

```bash
# On DigitalOcean droplet with Docker

# Set env vars
export ANTHROPIC_API_KEY=xxx
export BINANCE_API_KEY=xxx
export BINANCE_API_SECRET=xxx
export TRADING_MODE=live

# Run
docker-compose up -d

# View logs
docker-compose logs -f

# Status page at http://<ip>:8080
```

---

## Risk Warnings

- This is $250 of gambling money
- The bot is intentionally aggressive
- You could lose everything in days
- That's the point
- Do not add more money than you can afford to lose

---

## Session Log

### 2024-12-21: Initial Design
- Built v1 with 4 weighted strategies
- Realized per-coin decisions are wrong
- Redesigned to portfolio-level allocation

### 2024-12-21: Walkthrough & Refinement
- Walked through entire flow step by step
- Key decisions:
  - Top 50 by volume = universe
  - Portfolio-level decisions
  - Tool use for structured output
  - Sync from exchange each cycle
  - Cancel pending orders at start
  - Route through USDT
  - Stateless Claude
- Cost analysis: Opus 4.5 at $5/25 per 1M tokens = ~$5/month
- Final architecture: Opus every 2 hours, aggressive prompts
- Ready to implement v2

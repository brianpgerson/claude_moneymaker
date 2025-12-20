# Claude MoneyMaker - Project Notes

## Overview

An experimental crypto trading bot where Claude attempts to grow ~$250 in DOGE through automated trading. The system uses multiple strategies, aggregates their signals, and dynamically reallocates capital toward strategies that perform well.

---

## Implementation Status

### Completed
- [x] Project structure and dependencies (`pyproject.toml`)
- [x] Configuration system (`.env` based, pydantic-settings)
- [x] Core data models (`Signal`, `Order`, `Position`, `PortfolioState`)
- [x] Strategy interface and registry
- [x] 4 initial strategies:
  - **Momentum** (30%) - RSI, MACD, moving averages
  - **Sentiment** (15%) - Reddit sentiment, Fear & Greed Index
  - **Contrarian** (15%) - Inverse crowd behavior at extremes
  - **Claude Vibes** (25%) - Claude analyzes all data holistically
- [x] Market data fetcher (ccxt/Binance)
- [x] Sentiment data fetcher (Reddit API, Fear & Greed Index)
- [x] Capital allocator with performance-based rebalancing
- [x] Trade executor (paper + live modes)
- [x] Portfolio manager with SQLite persistence
- [x] Main trading engine loop
- [x] CLI (`moneymaker run`, `status`, `strategies`, `config`)

### In Progress
- [ ] Fix paper trading to use real market data (sandbox mode issue)
- [ ] Test full trading cycle end-to-end

### Not Started
- [ ] Backtesting on historical data
- [ ] Additional sentiment sources (Twitter, Discord)
- [ ] Web dashboard for monitoring
- [ ] Notifications (Discord, Telegram)
- [ ] More strategies (grid trading, arbitrage)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    CAPITAL ALLOCATOR                        │
│  Reviews performance every 24h, shifts capital to winners   │
└─────────────────────────┬───────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   ┌─────────┐      ┌──────────┐     ┌───────────┐
   │Momentum │      │Sentiment │     │Contrarian │
   │  (30%)  │      │  (15%)   │     │  (15%)    │
   └─────────┘      └──────────┘     └───────────┘
        │                 │                 │
        └─────────────────┼─────────────────┘
                          ▼
                    ┌───────────┐
                    │  Claude   │
                    │  Vibes    │
                    │  (25%)    │
                    └───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   SIGNAL AGGREGATION  │
              │  (capital-weighted)   │
              └───────────────────────┘
                          │
                          ▼
                   ┌─────────────┐
                   │   EXECUTE   │
                   │   TRADES    │
                   └─────────────┘
                          │
                          ▼
                   ┌─────────────┐
                   │  PORTFOLIO  │
                   │  TRACKING   │
                   └─────────────┘
```

---

## The Main Loop

Every cycle (default: 1 hour):

1. **Fetch Data**
   - OHLCV candles from Binance (100 hourly candles)
   - Sentiment from Reddit + Crypto Fear & Greed Index

2. **Run Strategies**
   - Each strategy analyzes data independently
   - Produces signal: STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL
   - Each signal has confidence 0.0 - 1.0

3. **Aggregate Signals**
   - Weight by: `strategy_allocation * signal_confidence * signal_strength`
   - Combine into single directional score

4. **Execute Trade (if signal strong enough)**
   - Position size based on signal strength
   - Never exceed 25% in single position

5. **Track Performance**
   - Record trade to SQLite
   - Update strategy P&L
   - Take portfolio snapshot

6. **Rebalance (every 24h)**
   - Review strategy win rates and P&L
   - Shift allocation toward winners
   - Maintain minimum 5% allocation so losers can recover

---

## Open Questions

### Technical
1. **Which exchange to use?** - Decided on Binance for liquidity/fees. Need to set up API keys.
2. **How to handle API keys securely in remote Claude Code session?** - User can't paste keys in chat. Need local access or alternative approach.
3. **Paper trading data source** - Fixed: use real market data, simulate trades locally (not testnet).

### Strategy
4. **What coins to trade?** - Starting with DOGE/USDT. Could expand to SHIB, PEPE, other meme coins.
5. **Optimal loop interval?** - Default 1 hour. Could go faster (15-30 min) for more action.
6. **How aggressive should position sizing be?** - Currently max 25% per position. Could tune.

### Meta-Learning
7. **How fast should capital reallocation happen?** - Currently every 24h with 10% learning rate. Too slow? Too fast?
8. **Minimum data before trusting a strategy?** - Currently no minimum. Should we require N trades before adjusting allocation?

---

## Next Steps

### Immediate (to get running)
1. User sets up Binance account and generates API keys
2. User adds keys to `.env` locally (after this session or with local access)
3. Test paper trading cycle with real market data
4. Run for a few days, observe behavior

### Short-term
5. Add more sentiment sources (Twitter if API accessible)
6. Tune strategy parameters based on observed performance
7. Add basic notifications (print to log, maybe Discord webhook)

### Medium-term
8. Build backtesting to test strategies on historical data
9. Add more strategies based on what's working
10. Web dashboard for monitoring

---

## Risk Management

Current safeguards:
- **Paper trading default** - Must explicitly enable `--live`
- **Max position size** - 25% of portfolio per position
- **Minimum trade size** - $5 to avoid dust trades
- **15% cash reserve** - Always keep some powder dry

Potential additions:
- Stop-loss orders
- Maximum daily loss limit
- Drawdown circuit breaker

---

## File Structure

```
claude_moneymaker/
├── .env.example          # Template for API keys
├── .env                  # Actual keys (gitignored)
├── .gitignore
├── pyproject.toml        # Dependencies and build config
├── README.md             # User-facing documentation
├── NOTES.md              # This file - internal project notes
│
├── moneymaker/
│   ├── __init__.py
│   ├── cli.py            # Typer CLI commands
│   ├── config.py         # Pydantic settings
│   ├── models.py         # Data models (Signal, Order, etc.)
│   │
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── base.py       # Strategy interface
│   │   ├── momentum.py   # Technical analysis
│   │   ├── sentiment.py  # Social sentiment
│   │   ├── contrarian.py # Inverse crowd
│   │   └── claude_vibes.py # Claude's judgment
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   ├── market.py     # OHLCV from exchanges
│   │   └── sentiment.py  # Reddit, Fear & Greed
│   │
│   └── core/
│       ├── __init__.py
│       ├── allocator.py  # Capital allocation
│       ├── executor.py   # Trade execution
│       ├── portfolio.py  # Position tracking
│       └── engine.py     # Main loop orchestrator
│
└── data/                 # Created at runtime
    └── moneymaker.db     # SQLite database
```

---

## Session Log

### 2024-12-20
- Initial project scaffolding
- Built all core components
- Hit issue with paper trading using Binance testnet
- Fixed: use real market data for paper trading
- Created this notes document
- **Paused**: User needs to set up Binance API keys with local access

# Claude MoneyMaker

An AI-powered crypto trading bot where Claude tries to make money. What could go wrong?

## The Premise

You have $250 in DOGE. Rather than let it sit there, why not let Claude try to grow it? This bot runs a continuous loop:

1. **Fetch data** - Market prices, social sentiment, order books
2. **Analyze** - Multiple strategies analyze the data and produce signals
3. **Decide** - Signals are aggregated with capital-weighted averaging
4. **Execute** - Trades are placed (paper or live)
5. **Learn** - Capital is reallocated toward strategies that are working
6. **Repeat**

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    CAPITAL ALLOCATOR                        │
│  Dynamically shifts capital to winning strategies           │
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
                   ┌─────────────┐
                   │   EXECUTE   │
                   │   TRADES    │
                   └─────────────┘
```

## Strategies

### 1. Momentum (30%)
Classic technical analysis using RSI, MACD, and moving averages. The "sensible" baseline.

### 2. Sentiment (15%)
Trades based on social media sentiment shifts. Tracks Reddit, Twitter, and the Crypto Fear & Greed Index.

### 3. Contrarian (15%)
Inverse the crowd. When everyone is euphoric, it sells. When everyone is panicking, it buys.

### 4. Claude Vibes (25%)
The main event: Claude analyzes all available data and makes a judgment call. Pure vibes.

### Cash Reserve (15%)
Always keep some powder dry.

## Installation

```bash
# Clone the repo
git clone https://github.com/youruser/claude_moneymaker.git
cd claude_moneymaker

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install dependencies
pip install -e .

# Set up configuration
cp .env.example .env
# Edit .env with your API keys
```

## Configuration

Edit `.env` with your API keys:

```bash
# Required for Claude's brain
ANTHROPIC_API_KEY=your_key_here

# Required for trading (pick one)
COINBASE_API_KEY=your_key
COINBASE_API_SECRET=your_secret
# OR
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret

# Optional: Reddit for sentiment
REDDIT_CLIENT_ID=your_id
REDDIT_CLIENT_SECRET=your_secret

# Trading config
TRADING_MODE=paper  # Start with paper trading!
INITIAL_CAPITAL=250.0
```

## Usage

```bash
# Start paper trading (simulated, no real money)
moneymaker run

# Trade multiple coins
moneymaker run -s DOGE/USDT -s SHIB/USDT

# Run every 30 minutes instead of hourly
moneymaker run -i 30

# Run 10 cycles and stop
moneymaker run -c 10

# Check portfolio status
moneymaker status

# View strategy performance
moneymaker strategies

# See current config
moneymaker config

# YOLO mode (real money - be careful!)
moneymaker run --live
```

## How It Works

### The Trading Loop

Every cycle (default: 1 hour):

1. **Data Collection**
   - Fetch OHLCV candlestick data from exchange
   - Fetch sentiment from Reddit, Twitter, Fear & Greed Index

2. **Strategy Analysis**
   - Each strategy independently analyzes the data
   - Produces a signal: STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL
   - Each signal has a confidence score (0-1)

3. **Signal Aggregation**
   - Signals are combined using capital-weighted averaging
   - Strategy allocation * signal confidence * signal direction
   - Produces final aggregated signal

4. **Trade Execution**
   - If signal is strong enough, execute trade
   - Position size based on signal strength and available capital
   - Never exceed max position size (25% default)

5. **Performance Tracking**
   - Record all trades to SQLite database
   - Track P&L per strategy
   - Take portfolio snapshots

6. **Capital Reallocation** (every 24 hours)
   - Review strategy performance
   - Shift capital toward winning strategies
   - Maintain minimum allocations so strategies can recover

### Paper Trading

By default, the bot runs in paper trading mode. This simulates trades at current market prices without using real money. Great for testing!

### Database

All data is stored in `data/moneymaker.db`:
- Trade history
- Portfolio snapshots
- Strategy P&L

## Risk Warnings

This is an **experiment**. Do not use money you can't afford to lose.

- Crypto is volatile. $250 can become $0.
- The strategies are simple. They will not beat the market.
- Claude is making decisions. It might be wrong.
- Paper trading results don't predict live results.
- This is for educational purposes.

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
ruff format .
ruff check --fix .
```

## Future Ideas

- [ ] Backtesting on historical data
- [ ] More sentiment sources (Discord, Telegram)
- [ ] More strategies (arbitrage, grid trading)
- [ ] Web dashboard for monitoring
- [ ] Notifications (Discord, Telegram)
- [ ] Multi-exchange support

## License

MIT - Use at your own risk!

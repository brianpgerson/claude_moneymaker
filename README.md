# Claude MoneyMaker

An aggressive crypto trading bot where Opus 4.5 tries to turn $250 into something more. What could go wrong?

## The Premise

You have $250. Rather than let it sit there, why not let Claude try to grow it? This bot runs every 2 hours:

1. **Sync** - Get current balances from Binance
2. **Scan** - Fetch top 50 coins by volume with technicals
3. **Analyze** - Opus 4.5 reviews the market and your portfolio
4. **Allocate** - Claude decides target portfolio allocation
5. **Execute** - Trades are placed to reach target (sells first, then buys)
6. **Repeat**

## Philosophy

This is NOT a conservative trading bot. It's designed to be AGGRESSIVE:

- **Concentration > Diversification** - Bet big on your best ideas
- **Momentum is everything** - Ride winners hard, dump losers fast
- **80% max position** - Can go all-in on a conviction play
- **5% cash reserve** - Just enough to not get stuck
- **Would rather blow up trying to 10x than slowly bleed out**

## Architecture

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

## Installation

```bash
# Clone the repo
git clone https://github.com/youruser/claude_moneymaker.git
cd claude_moneymaker

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install
pip install -e .

# Set up configuration
cp .env.example .env
# Edit .env with your API keys
```

## Configuration

Edit `.env`:

```bash
# Required: Anthropic API Key (for Opus 4.5)
ANTHROPIC_API_KEY=your_key_here

# Required for live trading: Binance API
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret

# Trading config
TRADING_MODE=paper  # Start with paper trading!
INITIAL_CAPITAL=250
```

## Usage

```bash
# Start paper trading (simulated, no real money)
moneymaker run

# Run every 30 minutes
moneymaker run -i 30

# Run 5 cycles and stop
moneymaker run -c 5

# Check portfolio status
moneymaker status

# View recent Claude decisions
moneymaker decisions

# See current config
moneymaker config

# YOLO mode (real money - be careful!)
moneymaker run --live
```

## Docker Deployment

```bash
# Set env vars
export ANTHROPIC_API_KEY=xxx
export BINANCE_API_KEY=xxx
export BINANCE_API_SECRET=xxx
export TRADING_MODE=live

# Run
docker-compose up -d

# View logs
docker-compose logs -f

# Status page at http://localhost:8080
```

## Cost Breakdown

| Item | Monthly Cost |
|------|--------------|
| Opus 4.5 (12 calls/day) | ~$5 |
| DigitalOcean droplet | $5 |
| Fear & Greed API | Free |
| Binance API | Free |
| **Total** | **~$10/month** |

Break-even: ~4% monthly returns on $250.

## Risk Warnings

This is $250 of gambling money:

- The bot is **intentionally aggressive**
- You could **lose everything in days**
- That's the point
- Do **NOT** add more money than you can afford to lose
- Paper trading results **don't predict** live results

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

## License

MIT - Use at your own risk!

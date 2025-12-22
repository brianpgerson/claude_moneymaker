"""Simple web status page."""

import asyncio
from datetime import datetime

from aiohttp import web

from moneymaker.config import get_settings
from moneymaker.core.portfolio import PortfolioManager


class StatusServer:
    """Lightweight status page server."""

    def __init__(self, portfolio: PortfolioManager, port: int = 8080):
        self.portfolio = portfolio
        self.port = port
        self.start_time = datetime.utcnow()
        self._runner: web.AppRunner | None = None
        self._last_cycle: datetime | None = None
        self._cycle_count: int = 0

    def update_cycle(self, cycle_count: int) -> None:
        """Called after each trading cycle."""
        self._cycle_count = cycle_count
        self._last_cycle = datetime.utcnow()

    async def handle_status(self, request: web.Request) -> web.Response:
        """Main status endpoint."""
        settings = get_settings()
        state = self.portfolio.get_state()

        uptime = datetime.utcnow() - self.start_time
        uptime_str = str(uptime).split('.')[0]  # Remove microseconds

        # Get recent trades
        trades = self.portfolio.get_trade_history(limit=5)

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Claude MoneyMaker</title>
    <meta http-equiv="refresh" content="60">
    <style>
        body {{
            font-family: monospace;
            background: #1a1a2e;
            color: #eee;
            padding: 2rem;
            max-width: 800px;
            margin: 0 auto;
        }}
        h1 {{ color: #00d4ff; }}
        .card {{
            background: #16213e;
            padding: 1rem;
            margin: 1rem 0;
            border-radius: 8px;
            border-left: 4px solid #00d4ff;
        }}
        .positive {{ color: #00ff88; }}
        .negative {{ color: #ff4757; }}
        table {{ width: 100%; border-collapse: collapse; }}
        td, th {{ padding: 0.5rem; text-align: left; }}
        tr:nth-child(even) {{ background: #1a1a2e; }}
        .dim {{ color: #666; }}
    </style>
</head>
<body>
    <h1>Claude MoneyMaker</h1>

    <div class="card">
        <h3>Portfolio</h3>
        <table>
            <tr><td>Cash</td><td>${state.cash_balance:.2f}</td></tr>
            <tr><td>Total Value</td><td>${state.total_value:.2f}</td></tr>
            <tr>
                <td>P&L</td>
                <td class="{'positive' if state.total_pnl >= 0 else 'negative'}">
                    ${state.total_pnl:+.2f} ({state.total_pnl_pct:+.1%})
                </td>
            </tr>
        </table>
    </div>

    <div class="card">
        <h3>Positions</h3>
        <table>
            <tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>P&L</th></tr>
            {''.join(f'''
            <tr>
                <td>{sym}</td>
                <td>{pos.quantity:.4f}</td>
                <td>${pos.average_entry_price:.6f}</td>
                <td class="{'positive' if pos.unrealized_pnl >= 0 else 'negative'}">
                    {pos.unrealized_pnl_pct:+.1%}
                </td>
            </tr>
            ''' for sym, pos in state.positions.items()) or '<tr><td colspan="4" class="dim">No positions</td></tr>'}
        </table>
    </div>

    <div class="card">
        <h3>Recent Trades</h3>
        <table>
            <tr><th>Time</th><th>Symbol</th><th>Side</th><th>Price</th></tr>
            {''.join(f'''
            <tr>
                <td>{t["created_at"][:16]}</td>
                <td>{t["symbol"]}</td>
                <td class="{'positive' if t['side'] == 'buy' else 'negative'}">{t["side"].upper()}</td>
                <td>${(t["filled_price"] or 0):.6f}</td>
            </tr>
            ''' for t in trades) or '<tr><td colspan="4" class="dim">No trades yet</td></tr>'}
        </table>
    </div>

    <div class="card">
        <h3>Portfolio History</h3>
        <canvas id="chart" height="150"></canvas>
    </div>

    <div class="card">
        <h3>System</h3>
        <table>
            <tr><td>Mode</td><td>{settings.trading_mode.value}</td></tr>
            <tr><td>Uptime</td><td>{uptime_str}</td></tr>
            <tr><td>Cycles</td><td>{self._cycle_count}</td></tr>
            <tr><td>Last Cycle</td><td>{self._last_cycle.strftime('%Y-%m-%d %H:%M:%S') if self._last_cycle else 'Never'}</td></tr>
        </table>
    </div>

    <p class="dim">Auto-refreshes every 60 seconds</p>

    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
        fetch('/api/snapshots')
            .then(r => r.json())
            .then(data => {{
                const snapshots = data.snapshots;
                const initial = data.initial_capital;
                if (!snapshots.length) return;

                const labels = snapshots.map(s => s.timestamp.slice(5, 16).replace('T', ' '));
                const values = snapshots.map(s => s.total_value);
                const initialLine = snapshots.map(() => initial);

                // Calculate BTC baseline: what if we just held BTC?
                const firstBtcPrice = snapshots.find(s => s.btc_price)?.btc_price;
                const btcBaseline = firstBtcPrice
                    ? snapshots.map(s => s.btc_price ? (initial / firstBtcPrice) * s.btc_price : null)
                    : null;

                const datasets = [
                    {{
                        label: 'Claude Portfolio',
                        data: values,
                        borderColor: '#00d4ff',
                        backgroundColor: 'rgba(0, 212, 255, 0.1)',
                        fill: true,
                        tension: 0.3
                    }},
                    {{
                        label: 'Initial ($' + initial + ')',
                        data: initialLine,
                        borderColor: '#666',
                        borderDash: [5, 5],
                        pointRadius: 0
                    }}
                ];

                if (btcBaseline) {{
                    datasets.push({{
                        label: 'Just Hold BTC',
                        data: btcBaseline,
                        borderColor: '#f7931a',
                        borderWidth: 2,
                        pointRadius: 0,
                        tension: 0.3
                    }});
                }}

                new Chart(document.getElementById('chart'), {{
                    type: 'line',
                    data: {{ labels: labels, datasets: datasets }},
                    options: {{
                        responsive: true,
                        plugins: {{
                            legend: {{ labels: {{ color: '#eee' }} }}
                        }},
                        scales: {{
                            x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }},
                            y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }}
                        }}
                    }}
                }});
            }});
    </script>
</body>
</html>"""
        return web.Response(text=html, content_type='text/html')

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({"status": "ok", "cycles": self._cycle_count})

    async def handle_api_status(self, request: web.Request) -> web.Response:
        """JSON API status endpoint."""
        state = self.portfolio.get_state()
        return web.json_response({
            "cash": state.cash_balance,
            "total_value": state.total_value,
            "pnl": state.total_pnl,
            "pnl_pct": state.total_pnl_pct,
            "positions": {
                sym: {
                    "quantity": pos.quantity,
                    "entry_price": pos.average_entry_price,
                    "pnl_pct": pos.unrealized_pnl_pct,
                }
                for sym, pos in state.positions.items()
            },
            "cycles": self._cycle_count,
        })

    async def handle_test_keys(self, request: web.Request) -> web.Response:
        """Test Binance API keys endpoint."""
        import ccxt.async_support as ccxt
        settings = get_settings()

        results = {
            "binance_key_set": bool(settings.binance_api_key),
            "binance_secret_set": bool(settings.binance_api_secret),
            "key_prefix": settings.binance_api_key[:8] + "..." if settings.binance_api_key else None,
            "tests": {}
        }

        if not settings.binance_api_key or not settings.binance_api_secret:
            results["error"] = "API keys not configured"
            return web.json_response(results)

        exchange = ccxt.binance({
            "apiKey": settings.binance_api_key,
            "secret": settings.binance_api_secret,
            "enableRateLimit": True,
        })

        try:
            # Test balance fetch
            balance = await exchange.fetch_balance()
            usdt = balance.get("USDT", {}).get("free", 0)
            results["tests"]["fetch_balance"] = {"success": True, "usdt_balance": usdt}

            # Test market data
            ticker = await exchange.fetch_ticker("BTC/USDT")
            results["tests"]["fetch_ticker"] = {"success": True, "btc_price": ticker["last"]}

            # Test spot trading permission
            orders = await exchange.fetch_open_orders("BTC/USDT")
            results["tests"]["spot_trading"] = {"success": True, "open_orders": len(orders)}

            results["all_passed"] = True

        except Exception as e:
            results["error"] = str(e)
            results["all_passed"] = False
        finally:
            await exchange.close()

        return web.json_response(results)

    async def handle_snapshots(self, request: web.Request) -> web.Response:
        """Return portfolio snapshot history for charting."""
        snapshots = self.portfolio.get_snapshots(limit=100)
        # Reverse so oldest is first (for chart)
        snapshots = list(reversed(snapshots))
        return web.json_response({
            "snapshots": snapshots,
            "initial_capital": get_settings().initial_capital,
        })

    async def start(self) -> None:
        """Start the web server."""
        app = web.Application()
        app.router.add_get('/', self.handle_status)
        app.router.add_get('/health', self.handle_health)
        app.router.add_get('/api/status', self.handle_api_status)
        app.router.add_get('/api/test-keys', self.handle_test_keys)
        app.router.add_get('/api/snapshots', self.handle_snapshots)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, '0.0.0.0', self.port)
        await site.start()
        print(f"Status page running at http://localhost:{self.port}")

    async def stop(self) -> None:
        """Stop the web server."""
        if self._runner:
            await self._runner.cleanup()

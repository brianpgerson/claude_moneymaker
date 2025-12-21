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
                <td>${t["filled_price"]:.6f if t["filled_price"] else 0:.6f}</td>
            </tr>
            ''' for t in trades) or '<tr><td colspan="4" class="dim">No trades yet</td></tr>'}
        </table>
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

    async def start(self) -> None:
        """Start the web server."""
        app = web.Application()
        app.router.add_get('/', self.handle_status)
        app.router.add_get('/health', self.handle_health)
        app.router.add_get('/api/status', self.handle_api_status)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, '0.0.0.0', self.port)
        await site.start()
        print(f"Status page running at http://localhost:{self.port}")

    async def stop(self) -> None:
        """Stop the web server."""
        if self._runner:
            await self._runner.cleanup()

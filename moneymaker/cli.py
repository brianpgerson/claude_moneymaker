"""Command-line interface for MoneyMaker."""

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from moneymaker.config import Settings, TradingMode, get_settings
from moneymaker.core.engine import TradingEngine

app = typer.Typer(
    name="moneymaker",
    help="Opus 4.5 tries to turn $250 into something more. What could go wrong?",
)
console = Console()


@app.command()
def run(
    cycles: int = typer.Option(
        None,
        "--cycles", "-c",
        help="Number of cycles to run (default: infinite)",
    ),
    interval: int = typer.Option(
        None,
        "--interval", "-i",
        help="Minutes between cycles (default: 120)",
    ),
    paper: bool = typer.Option(
        True,
        "--paper/--live",
        help="Paper trading (simulated) or live (real money!)",
    ),
):
    """
    Run the trading bot.

    Opus 4.5 picks coins from top 50 by volume every 2 hours.

    Examples:
        # Paper trade (default)
        moneymaker run

        # Run 5 cycles and stop
        moneymaker run -c 5

        # Custom interval (every 30 minutes)
        moneymaker run -i 30

        # YOLO live trading (careful!)
        moneymaker run --live
    """
    settings = get_settings()
    settings.trading_mode = TradingMode.PAPER if paper else TradingMode.LIVE

    if interval:
        settings.loop_interval_minutes = interval

    if not paper:
        console.print("[bold red]" + "=" * 50 + "[/]")
        console.print("[bold red]         LIVE TRADING MODE[/]")
        console.print("[bold red]" + "=" * 50 + "[/]")
        console.print("[red]Real money will be used.[/]")
        console.print("[red]This bot is AGGRESSIVE - you could lose everything.[/]")
        confirm = typer.confirm("Continue with live trading?")
        if not confirm:
            raise typer.Abort()

    engine = TradingEngine(settings)
    asyncio.run(engine.run(cycles=cycles))


@app.command()
def status():
    """Show current portfolio status and recent trades."""
    settings = get_settings()

    from moneymaker.core.portfolio import PortfolioManager

    portfolio = PortfolioManager(settings)
    portfolio.load_state()

    state = portfolio.get_state()

    # Portfolio summary
    console.print("\n[bold cyan]═══ Portfolio Status ═══[/]")
    pnl_style = "green" if state.total_pnl >= 0 else "red"

    table = Table()
    table.add_column("Metric", style="cyan")
    table.add_column("Value")

    table.add_row("Cash Balance", f"${state.cash_balance:.2f}")
    table.add_row("Total Value", f"${state.total_value:.2f}")
    table.add_row(
        "Total P&L",
        f"[{pnl_style}]${state.total_pnl:+.2f} ({state.total_pnl_pct:+.1%})[/]"
    )

    console.print(table)

    # Positions
    if state.positions:
        console.print("\n[bold]Positions:[/]")
        pos_table = Table()
        pos_table.add_column("Symbol")
        pos_table.add_column("Quantity")
        pos_table.add_column("Entry Price")
        pos_table.add_column("Current Price")
        pos_table.add_column("P&L")

        for symbol, pos in state.positions.items():
            pnl_style = "green" if pos.unrealized_pnl >= 0 else "red"
            pos_table.add_row(
                symbol,
                f"{pos.quantity:.4f}",
                f"${pos.average_entry_price:.6f}",
                f"${pos.current_price:.6f}",
                f"[{pnl_style}]${pos.unrealized_pnl:+.2f}[/]",
            )

        console.print(pos_table)

    # Recent trades
    trades = portfolio.get_trade_history(limit=10)
    if trades:
        console.print("\n[bold]Recent Trades:[/]")
        trade_table = Table()
        trade_table.add_column("Time")
        trade_table.add_column("Symbol")
        trade_table.add_column("Side")
        trade_table.add_column("Quantity")
        trade_table.add_column("Price")

        for trade in trades:
            side_style = "green" if trade["side"] == "buy" else "red"
            trade_table.add_row(
                trade["created_at"][:19],
                trade["symbol"],
                f"[{side_style}]{trade['side'].upper()}[/]",
                f"{trade['quantity']:.4f}",
                f"${trade['filled_price']:.6f}" if trade["filled_price"] else "-",
            )

        console.print(trade_table)


@app.command()
def decisions(
    limit: int = typer.Option(5, "--limit", "-n", help="Number of decisions to show"),
):
    """Show recent Claude decisions for analysis."""
    settings = get_settings()

    from moneymaker.core.portfolio import PortfolioManager

    portfolio = PortfolioManager(settings)

    recent = portfolio.get_recent_decisions(limit=limit)

    if not recent:
        console.print("[yellow]No decisions recorded yet.[/]")
        return

    console.print("\n[bold cyan]═══ Recent Decisions ═══[/]")

    for d in recent:
        console.print(f"\n[bold]{d['timestamp'][:19]}[/]")
        console.print(f"Outlook: {d.get('reasoning', 'N/A')}")
        console.print(f"Conviction: {d.get('conviction', 'N/A')}")

        console.print("\nTarget Allocation:")
        for alloc in d.get("target_allocation", []):
            console.print(f"  {alloc['symbol']}: {alloc['percent']}% - {alloc.get('reasoning', '')[:50]}")

        trades = d.get("trades_executed", [])
        if trades:
            console.print(f"\nTrades: {len(trades)} executed")

        console.print("[dim]" + "-" * 40 + "[/]")


@app.command()
def config():
    """Show current configuration."""
    settings = get_settings()

    console.print("\n[bold cyan]═══ Configuration ═══[/]")

    table = Table()
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Trading Mode", settings.trading_mode.value)
    table.add_row("Initial Capital", f"${settings.initial_capital:.2f}")
    table.add_row("Base Currency", settings.base_currency)
    table.add_row("Preferred Exchange", settings.preferred_exchange.value)
    table.add_row("Loop Interval", f"{settings.loop_interval_minutes} minutes")
    table.add_row("Universe Size", f"Top {settings.universe_size} coins")
    table.add_row("Min Trade Size", f"${settings.min_trade_size_usd:.2f}")
    table.add_row("Max Position", f"{settings.max_position_pct:.0%}")
    table.add_row("Min Cash Reserve", f"{settings.min_cash_pct:.0%}")

    # Check API keys (show if configured, not the actual values)
    table.add_row("", "")  # Spacer
    table.add_row("[bold]API Keys[/]", "")
    table.add_row("Anthropic API", "[green]Configured[/]" if settings.anthropic_api_key else "[red]Missing[/]")
    table.add_row("Binance API", "[green]Configured[/]" if settings.binance_api_key else "[red]Missing[/]")

    console.print(table)


@app.command()
def init():
    """Initialize a new .env file with example configuration."""
    env_path = Path(".env")
    example_path = Path(".env.example")

    if env_path.exists():
        console.print("[yellow].env file already exists![/]")
        overwrite = typer.confirm("Overwrite?")
        if not overwrite:
            raise typer.Abort()

    if example_path.exists():
        env_path.write_text(example_path.read_text())
        console.print("[green]Created .env from .env.example[/]")
        console.print("Edit .env to add your API keys.")
    else:
        # Create a minimal example
        content = """# Claude MoneyMaker Configuration

# Required: Anthropic API Key (for Opus 4.5)
ANTHROPIC_API_KEY=

# Required for live trading: Binance API
BINANCE_API_KEY=
BINANCE_API_SECRET=

# Trading settings (optional - defaults shown)
TRADING_MODE=paper
INITIAL_CAPITAL=250
LOOP_INTERVAL_MINUTES=120
UNIVERSE_SIZE=50
MAX_POSITION_PCT=0.80
MIN_CASH_PCT=0.05
"""
        env_path.write_text(content)
        console.print("[green]Created .env file[/]")
        console.print("Edit .env to add your API keys.")


if __name__ == "__main__":
    app()

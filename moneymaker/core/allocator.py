"""Capital allocation based on strategy performance."""

from datetime import datetime, timedelta
from typing import Any

from moneymaker.models import StrategyPerformance


class CapitalAllocator:
    """
    Dynamically allocates capital across strategies based on performance.

    The core idea:
    - Track each strategy's P&L over time
    - Allocate more to strategies that are working
    - Reduce allocation to strategies that are underperforming
    - But keep minimum allocations so we can detect if a strategy starts working again
    """

    def __init__(
        self,
        min_allocation: float = 0.05,      # Minimum 5% for any enabled strategy
        max_allocation: float = 0.50,       # Maximum 50% for any single strategy
        rebalance_period_hours: int = 24,   # How often to rebalance
        performance_lookback_days: int = 7, # How far back to look for performance
        learning_rate: float = 0.1,         # How quickly to adjust allocations
    ):
        self.min_allocation = min_allocation
        self.max_allocation = max_allocation
        self.rebalance_period_hours = rebalance_period_hours
        self.performance_lookback_days = performance_lookback_days
        self.learning_rate = learning_rate

        self._performance: dict[str, StrategyPerformance] = {}
        self._allocation_history: list[dict[str, Any]] = []
        self._last_rebalance: datetime | None = None

    def register_strategy(self, name: str, initial_allocation: float) -> None:
        """Register a new strategy with initial allocation."""
        self._performance[name] = StrategyPerformance(
            strategy_name=name,
            current_allocation=initial_allocation,
        )

    def record_trade(
        self,
        strategy_name: str,
        pnl: float,
        pnl_pct: float,
    ) -> None:
        """Record a completed trade for a strategy."""
        if strategy_name not in self._performance:
            return

        perf = self._performance[strategy_name]
        is_winner = pnl > 0
        perf.update_metrics(pnl, is_winner)
        perf.total_pnl_pct += pnl_pct

    def get_allocation(self, strategy_name: str) -> float:
        """Get current allocation for a strategy."""
        if strategy_name not in self._performance:
            return 0.0
        return self._performance[strategy_name].current_allocation

    def get_all_allocations(self) -> dict[str, float]:
        """Get all current allocations."""
        return {
            name: perf.current_allocation
            for name, perf in self._performance.items()
        }

    def get_performance(self, strategy_name: str) -> StrategyPerformance | None:
        """Get performance metrics for a strategy."""
        return self._performance.get(strategy_name)

    def get_all_performance(self) -> dict[str, StrategyPerformance]:
        """Get all strategy performance metrics."""
        return dict(self._performance)

    def should_rebalance(self) -> bool:
        """Check if it's time to rebalance allocations."""
        if self._last_rebalance is None:
            return True

        time_since = datetime.utcnow() - self._last_rebalance
        return time_since > timedelta(hours=self.rebalance_period_hours)

    def rebalance(self) -> dict[str, float]:
        """
        Rebalance allocations based on strategy performance.

        Uses a modified multiplicative weights algorithm:
        - Calculate performance score for each strategy
        - Adjust allocations proportionally
        - Apply min/max constraints
        - Normalize so allocations sum to 1

        Returns:
            New allocation mapping
        """
        if not self._performance:
            return {}

        # Calculate performance scores
        scores: dict[str, float] = {}
        for name, perf in self._performance.items():
            # Base score on multiple factors
            win_rate_score = perf.win_rate if perf.total_trades > 0 else 0.5
            pnl_score = 0.5 + (perf.total_pnl_pct * 2)  # Center around 0.5
            trade_volume_score = min(perf.total_trades / 10, 1.0)  # More trades = more confidence

            # Weighted combination
            score = (
                win_rate_score * 0.4 +
                pnl_score * 0.4 +
                trade_volume_score * 0.2
            )

            # Ensure positive score
            scores[name] = max(score, 0.1)

        # Apply multiplicative update
        new_allocations: dict[str, float] = {}
        for name, perf in self._performance.items():
            current = perf.current_allocation
            score = scores[name]
            avg_score = sum(scores.values()) / len(scores)

            # Move towards strategies performing above average
            adjustment = 1 + self.learning_rate * (score - avg_score)
            new_allocation = current * adjustment

            # Apply constraints
            new_allocation = max(self.min_allocation, new_allocation)
            new_allocation = min(self.max_allocation, new_allocation)
            new_allocations[name] = new_allocation

        # Normalize to sum to 1
        total = sum(new_allocations.values())
        if total > 0:
            new_allocations = {
                name: alloc / total
                for name, alloc in new_allocations.items()
            }

        # Update allocations
        for name, new_alloc in new_allocations.items():
            self._performance[name].current_allocation = new_alloc

        # Record history
        self._allocation_history.append({
            "timestamp": datetime.utcnow(),
            "allocations": dict(new_allocations),
            "scores": dict(scores),
        })

        self._last_rebalance = datetime.utcnow()
        return new_allocations

    def get_rebalance_reasoning(self) -> str:
        """Get human-readable explanation of current allocations."""
        if not self._performance:
            return "No strategies registered."

        lines = ["Current Strategy Allocations:"]
        for name, perf in sorted(
            self._performance.items(),
            key=lambda x: x[1].current_allocation,
            reverse=True
        ):
            status = "🟢" if perf.total_pnl >= 0 else "🔴"
            lines.append(
                f"  {status} {name}: {perf.current_allocation:.1%} "
                f"(W/L: {perf.winning_trades}/{perf.losing_trades}, "
                f"P&L: ${perf.total_pnl:.2f})"
            )

        return "\n".join(lines)

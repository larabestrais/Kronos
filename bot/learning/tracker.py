"""
PerformanceTracker — met à jour les stats du LearningState à chaque trade fermé.
"""

import logging
from typing import Any

from .types import LearningState, Regime, SymbolStats

logger = logging.getLogger(__name__)


class PerformanceTracker:
    """Mute le LearningState passé en paramètre. Persistance gérée par l'appelant."""

    def __init__(self, state: LearningState):
        self.state = state

    def record_closed_trade(self, trade: Any, regime: Regime) -> None:
        """
        Enregistre un trade fermé. `trade` doit avoir au minimum :
          - .symbol (str)
          - .pnl (float)
        """
        symbol = trade.symbol
        pnl = float(trade.pnl)
        regime_key = regime.value

        # Crée les entrées si nécessaire
        if symbol not in self.state.symbol_stats_by_regime:
            self.state.symbol_stats_by_regime[symbol] = {}
        if regime_key not in self.state.symbol_stats_by_regime[symbol]:
            self.state.symbol_stats_by_regime[symbol][regime_key] = SymbolStats()

        stats = self.state.symbol_stats_by_regime[symbol][regime_key]

        # Update count
        stats.trades += 1
        if pnl > 0:
            stats.wins += 1
        elif pnl < 0:
            stats.losses += 1
        # pnl == 0 → ni win ni loss (rare)

        # Update expectancy = moyenne des pnl par trade
        # Recalcul incrémental : nouvelle moyenne = ((n-1)*ancienne + pnl) / n
        prev_total = stats.expectancy * (stats.trades - 1)
        stats.expectancy = (prev_total + pnl) / stats.trades

        # Update PnL 30j (approximation : on ajoute, le pruning >30j est fait
        # dans un cycle séparé par le scheduler)
        stats.pnl_30d += pnl

        logger.info(
            f"[Learning][Tracker] {symbol} {regime_key} pnl={pnl:+.2f} "
            f"→ trades={stats.trades} win_rate={stats.win_rate:.0%} "
            f"expectancy={stats.expectancy:+.3f}"
        )

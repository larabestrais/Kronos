import logging
from dataclasses import dataclass

from .signals import Signal, Action

logger = logging.getLogger(__name__)


@dataclass
class RiskCheck:
    approved: bool
    position_size: float
    reason: str


class RiskManager:

    def __init__(
        self,
        max_drawdown_pct: float = 0.10,
        max_daily_loss_pct: float = 0.03,
        max_open_positions: int = 3,
        risk_per_trade_pct: float = 0.02,
        max_position_pct: float = 0.20,
        leverage: float = 1.0,
    ):
        self.max_drawdown_pct = max_drawdown_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_open_positions = max_open_positions
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_position_pct = max_position_pct
        self.leverage = max(1.0, leverage)

    def check(self, signal: Signal, portfolio_value: float, cash: float, open_positions: int, daily_pnl: float, peak_value: float) -> RiskCheck:
        if signal.action == Action.HOLD:
            return RiskCheck(approved=False, position_size=0.0, reason="Signal HOLD, rien à faire")

        drawdown = (peak_value - portfolio_value) / peak_value if peak_value > 0 else 0
        if drawdown >= self.max_drawdown_pct:
            return RiskCheck(approved=False, position_size=0.0, reason=f"Drawdown max atteint: {drawdown:.1%}")

        daily_loss = -daily_pnl / portfolio_value if portfolio_value > 0 else 0
        if daily_loss >= self.max_daily_loss_pct:
            return RiskCheck(approved=False, position_size=0.0, reason=f"Perte journalière max atteinte: {daily_loss:.1%}")

        if signal.action == Action.BUY and open_positions >= self.max_open_positions:
            return RiskCheck(approved=False, position_size=0.0, reason=f"Max positions ouvertes: {open_positions}/{self.max_open_positions}")

        position_size = self._calculate_position_size(signal, portfolio_value, cash)

        if position_size <= 0:
            return RiskCheck(approved=False, position_size=0.0, reason="Taille de position nulle")

        logger.info(f"[Risk] {signal.symbol} approuvé: {position_size:.2f}$")
        return RiskCheck(approved=True, position_size=position_size, reason="Risque OK")

    def _calculate_position_size(self, signal: Signal, portfolio_value: float, cash: float) -> float:
        risk_amount = portfolio_value * self.risk_per_trade_pct

        if signal.action == Action.BUY:
            risk_per_share = abs(signal.current_close - signal.stop_loss)
        else:
            risk_per_share = abs(signal.stop_loss - signal.current_close)

        if risk_per_share <= 0:
            return 0.0

        shares = risk_amount / risk_per_share
        position_value = shares * signal.current_close

        # Avec levier, position max en notionnel = capital × max_position_pct × leverage
        max_allowed_notional = portfolio_value * self.max_position_pct * self.leverage
        if position_value > max_allowed_notional:
            shares = max_allowed_notional / signal.current_close

        if signal.action == Action.BUY:
            # Avec levier, le cash dispo permet d'ouvrir des positions de cash × leverage
            max_from_cash = (cash * self.leverage) / signal.current_close
            shares = min(shares, max_from_cash)

        # Paper trading: autoriser les fractions de parts (utile pour petits budgets)
        # Round à 4 décimales pour éviter les flottants moches
        return max(0.0, round(shares, 4))

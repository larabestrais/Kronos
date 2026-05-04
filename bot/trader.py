import logging

from .signals import Signal, Action
from .risk_manager import RiskManager, RiskCheck
from .portfolio import Portfolio

logger = logging.getLogger(__name__)


class PaperTrader:

    def __init__(self, portfolio: Portfolio, risk_manager: RiskManager):
        self.portfolio = portfolio
        self.risk_manager = risk_manager

    def execute(self, signal: Signal) -> bool:
        risk_check = self.risk_manager.check(
            signal=signal,
            portfolio_value=self.portfolio.total_value,
            cash=self.portfolio.cash,
            open_positions=self.portfolio.open_position_count,
            daily_pnl=self.portfolio.daily_pnl,
            peak_value=self.portfolio.peak_value,
        )

        if not risk_check.approved:
            logger.info(f"[Trader] {signal.symbol} rejeté: {risk_check.reason}")
            return False

        shares = risk_check.position_size

        if signal.action == Action.BUY:
            if signal.symbol in self.portfolio.positions:
                logger.info(f"[Trader] {signal.symbol} déjà en position")
                return False

            return self.portfolio.open_position(
                symbol=signal.symbol,
                side="LONG",
                shares=shares,
                price=signal.current_close,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
            )

        elif signal.action == Action.SELL:
            if signal.symbol in self.portfolio.positions:
                self.portfolio.close_position(signal.symbol, signal.current_close, reason="Signal SELL")
                return True

            return self.portfolio.open_position(
                symbol=signal.symbol,
                side="SHORT",
                shares=shares,
                price=signal.current_close,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
            )

        return False

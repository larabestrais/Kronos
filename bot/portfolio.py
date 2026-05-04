import pandas as pd
import numpy as np
import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    side: str
    shares: float
    entry_price: float
    stop_loss: float
    take_profit: float
    entry_time: str
    unrealized_pnl: float = 0.0

    def update_pnl(self, current_price: float):
        if self.side == "LONG":
            self.unrealized_pnl = (current_price - self.entry_price) * self.shares
        else:
            self.unrealized_pnl = (self.entry_price - current_price) * self.shares

    def should_stop_loss(self, current_price: float) -> bool:
        if self.side == "LONG":
            return current_price <= self.stop_loss
        return current_price >= self.stop_loss

    def should_take_profit(self, current_price: float) -> bool:
        if self.side == "LONG":
            return current_price >= self.take_profit
        return current_price <= self.take_profit


@dataclass
class Trade:
    symbol: str
    side: str
    shares: float
    price: float
    timestamp: str
    pnl: float = 0.0
    reason: str = ""


class Portfolio:

    def __init__(self, initial_capital: float = 10000.0, save_path: str = "portfolio_state.json"):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.daily_pnl = 0.0
        self.peak_value = initial_capital
        self.save_path = Path(save_path)
        self._equity_curve: list[dict] = []

    @property
    def total_value(self) -> float:
        positions_value = sum(
            p.shares * (p.entry_price + p.unrealized_pnl / p.shares) if p.shares > 0 else 0
            for p in self.positions.values()
        )
        return self.cash + positions_value

    @property
    def open_position_count(self) -> int:
        return len(self.positions)

    def open_position(self, symbol: str, side: str, shares: float, price: float, stop_loss: float, take_profit: float) -> bool:
        if symbol in self.positions:
            logger.warning(f"[Portfolio] Position déjà ouverte pour {symbol}")
            return False

        cost = shares * price
        if side == "LONG" and cost > self.cash:
            logger.warning(f"[Portfolio] Cash insuffisant: {self.cash:.2f}$ < {cost:.2f}$")
            return False

        if side == "LONG":
            self.cash -= cost

        now = pd.Timestamp.now().isoformat()
        self.positions[symbol] = Position(
            symbol=symbol, side=side, shares=shares, entry_price=price,
            stop_loss=stop_loss, take_profit=take_profit, entry_time=now,
        )

        self.trades.append(Trade(
            symbol=symbol, side=f"OPEN_{side}", shares=shares,
            price=price, timestamp=now, reason=f"Ouverture {side}",
        ))

        logger.info(f"[Portfolio] OPEN {side} {shares}x {symbol} @ {price:.2f}$")
        return True

    def close_position(self, symbol: str, price: float, reason: str = "") -> float:
        if symbol not in self.positions:
            return 0.0

        pos = self.positions[symbol]
        pos.update_pnl(price)
        pnl = pos.unrealized_pnl

        if pos.side == "LONG":
            self.cash += pos.shares * price
        else:
            self.cash += pnl

        now = pd.Timestamp.now().isoformat()
        self.trades.append(Trade(
            symbol=symbol, side=f"CLOSE_{pos.side}", shares=pos.shares,
            price=price, timestamp=now, pnl=pnl, reason=reason,
        ))

        self.daily_pnl += pnl
        del self.positions[symbol]

        logger.info(f"[Portfolio] CLOSE {symbol} @ {price:.2f}$ | PnL: {pnl:+.2f}$ | {reason}")
        return pnl

    def update_positions(self, prices: dict[str, float]):
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices:
                continue

            price = prices[symbol]
            pos.update_pnl(price)

            if pos.should_stop_loss(price):
                self.close_position(symbol, price, reason="STOP LOSS")
            elif pos.should_take_profit(price):
                self.close_position(symbol, price, reason="TAKE PROFIT")

    def record_equity(self):
        self._equity_curve.append({
            "timestamp": pd.Timestamp.now().isoformat(),
            "total_value": self.total_value,
            "cash": self.cash,
            "positions": self.open_position_count,
            "daily_pnl": self.daily_pnl,
        })
        self.peak_value = max(self.peak_value, self.total_value)

    def reset_daily(self):
        self.daily_pnl = 0.0

    def get_summary(self) -> dict:
        total = self.total_value
        return {
            "capital_initial": self.initial_capital,
            "valeur_totale": round(total, 2),
            "cash": round(self.cash, 2),
            "pnl_total": round(total - self.initial_capital, 2),
            "pnl_total_pct": round((total - self.initial_capital) / self.initial_capital * 100, 2),
            "pnl_journalier": round(self.daily_pnl, 2),
            "positions_ouvertes": self.open_position_count,
            "trades_total": len(self.trades),
            "peak": round(self.peak_value, 2),
            "drawdown": round((self.peak_value - total) / self.peak_value * 100, 2) if self.peak_value > 0 else 0,
        }

    def get_equity_df(self) -> pd.DataFrame:
        if not self._equity_curve:
            return pd.DataFrame()
        return pd.DataFrame(self._equity_curve)

    def save(self):
        state = {
            "cash": self.cash,
            "initial_capital": self.initial_capital,
            "peak_value": self.peak_value,
            "daily_pnl": self.daily_pnl,
            "positions": {k: asdict(v) for k, v in self.positions.items()},
            "trades": [asdict(t) for t in self.trades[-100:]],
        }
        self.save_path.write_text(json.dumps(state, indent=2, default=str))

    def load(self):
        if not self.save_path.exists():
            return
        state = json.loads(self.save_path.read_text())
        self.cash = state["cash"]
        self.initial_capital = state["initial_capital"]
        self.peak_value = state["peak_value"]
        self.daily_pnl = state.get("daily_pnl", 0)
        self.positions = {k: Position(**v) for k, v in state.get("positions", {}).items()}
        self.trades = [Trade(**t) for t in state.get("trades", [])]
        logger.info(f"[Portfolio] État chargé: {self.get_summary()}")

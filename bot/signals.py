import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class Action(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    symbol: str
    action: Action
    confidence: float
    predicted_return: float
    predicted_close: float
    current_close: float
    stop_loss: float
    take_profit: float
    timestamp: pd.Timestamp
    reason: str


class SignalEngine:

    def __init__(
        self,
        buy_threshold: float = 0.01,
        sell_threshold: float = -0.01,
        confidence_min: float = 0.6,
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.06,
    ):
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.confidence_min = confidence_min
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def generate(self, symbol: str, historical_df: pd.DataFrame, predicted_df: pd.DataFrame) -> Signal:
        current_close = historical_df["close"].iloc[-1]
        pred_closes = predicted_df["close"].values

        avg_pred_close = np.mean(pred_closes)
        predicted_return = (avg_pred_close - current_close) / current_close

        trend_direction = np.polyfit(range(len(pred_closes)), pred_closes, 1)[0]
        trend_positive = trend_direction > 0

        pred_high = predicted_df["high"].max()
        pred_low = predicted_df["low"].min()
        pred_range = (pred_high - pred_low) / current_close
        volatility_ok = pred_range < 0.15

        hist_close = historical_df["close"].values[-20:]
        sma_20 = np.mean(hist_close)
        above_sma = current_close > sma_20

        momentum = (current_close - hist_close[0]) / hist_close[0] if len(hist_close) >= 20 else 0

        confidence = self._calc_confidence(predicted_return, trend_positive, volatility_ok, above_sma, momentum)

        if predicted_return > self.buy_threshold and trend_positive and confidence >= self.confidence_min:
            action = Action.BUY
            stop_loss = current_close * (1 - self.stop_loss_pct)
            take_profit = current_close * (1 + self.take_profit_pct)
            reason = f"Return prédit: {predicted_return:+.2%}, tendance haussière, confiance: {confidence:.0%}"
        elif predicted_return < self.sell_threshold and not trend_positive and confidence >= self.confidence_min:
            action = Action.SELL
            stop_loss = current_close * (1 + self.stop_loss_pct)
            take_profit = current_close * (1 - self.take_profit_pct)
            reason = f"Return prédit: {predicted_return:+.2%}, tendance baissière, confiance: {confidence:.0%}"
        else:
            action = Action.HOLD
            stop_loss = 0.0
            take_profit = 0.0
            reason = f"Return prédit: {predicted_return:+.2%}, confiance insuffisante: {confidence:.0%}"

        signal = Signal(
            symbol=symbol,
            action=action,
            confidence=confidence,
            predicted_return=predicted_return,
            predicted_close=avg_pred_close,
            current_close=current_close,
            stop_loss=stop_loss,
            take_profit=take_profit,
            timestamp=pd.Timestamp.now(),
            reason=reason,
        )

        logger.info(f"[Signal] {symbol}: {action.value} | {reason}")
        return signal

    def _calc_confidence(
        self, predicted_return: float, trend_positive: bool, volatility_ok: bool, above_sma: bool, momentum: float
    ) -> float:
        score = 0.0

        magnitude = min(abs(predicted_return) / 0.05, 1.0)
        score += magnitude * 0.35

        if (predicted_return > 0 and trend_positive) or (predicted_return < 0 and not trend_positive):
            score += 0.25

        if volatility_ok:
            score += 0.15

        if (predicted_return > 0 and above_sma) or (predicted_return < 0 and not above_sma):
            score += 0.15

        if (predicted_return > 0 and momentum > 0) or (predicted_return < 0 and momentum < 0):
            score += 0.10

        return min(score, 1.0)

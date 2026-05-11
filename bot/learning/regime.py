"""
RegimeDetector — classifie le régime de marché parmi 4 catégories.

Inputs : VIX (yfinance ^VIX), pente du panier des symboles, ATR ratio.
Output : un Regime enum.

Décision (priorité à HIGH_VOLATILITY) :
  - VIX > 25 OU ATR > 3% → HIGH_VOLATILITY
  - sinon : selon pente
    - pente > +0.1%/h → TREND_UP
    - pente < -0.1%/h → TREND_DOWN
    - sinon → RANGING
"""

import logging
import numpy as np
import pandas as pd

from .types import Regime

logger = logging.getLogger(__name__)

# Seuils de classification
VIX_HIGH_THRESHOLD = 25.0
ATR_HIGH_THRESHOLD = 0.03  # 3%
SLOPE_TREND_THRESHOLD = 0.001  # 0.1% par heure


class RegimeDetector:

    def classify(
        self,
        vix: float,
        basket_df: pd.DataFrame,
        atr_ratio: float,
    ) -> Regime:
        """
        Classifie le régime à partir des 3 indicateurs.
        basket_df : DataFrame OHLCV du panier moyen pondéré (60+ bougies recommandées)
        """
        # 1. Priorité : volatilité élevée
        if vix > VIX_HIGH_THRESHOLD or atr_ratio > ATR_HIGH_THRESHOLD:
            return Regime.HIGH_VOLATILITY

        # 2. Tendance via régression linéaire
        slope = self.compute_basket_slope(basket_df)
        if slope > SLOPE_TREND_THRESHOLD:
            return Regime.TREND_UP
        if slope < -SLOPE_TREND_THRESHOLD:
            return Regime.TREND_DOWN

        # 3. Sinon, ranging
        return Regime.RANGING

    @staticmethod
    def compute_basket_slope(df: pd.DataFrame, lookback: int = 50) -> float:
        """
        Pente normalisée (par rapport au prix moyen) sur les `lookback` dernières bougies.
        Retourne la variation relative par bougie (sans unité, ex: 0.001 = 0.1%/h).
        """
        if len(df) < lookback:
            lookback = len(df)
        if lookback < 2:
            return 0.0

        prices = df["close"].iloc[-lookback:].values
        x = np.arange(lookback)
        slope, _ = np.polyfit(x, prices, 1)
        mean_price = np.mean(prices)
        if mean_price == 0:
            return 0.0
        return float(slope / mean_price)

    @staticmethod
    def compute_atr_ratio(df: pd.DataFrame, period: int = 20) -> float:
        """
        Average True Range / dernier prix de clôture.
        ATR = moyenne sur `period` du true range.
        true range = max(high-low, |high-close_prev|, |low-close_prev|).
        """
        if len(df) < period + 1:
            period = max(1, len(df) - 1)

        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        tr_list = []
        for i in range(1, len(df)):
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
            tr_list.append(tr)

        if not tr_list:
            return 0.0

        atr = float(np.mean(tr_list[-period:]))
        last_close = float(close[-1])
        if last_close == 0:
            return 0.0
        return atr / last_close

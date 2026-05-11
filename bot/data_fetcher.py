import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)

TIMEFRAME_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "1d": "1d", "1wk": "1wk",
}

MAX_PERIOD_MAP = {
    "1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d",
    "1h": "730d", "1d": "max", "1wk": "max",
}


class DataFetcher:
    """
    Récupère les bougies OHLCV pour un symbole.

    Sources supportées :
    - 'yfinance' (défaut) : Yahoo Finance, gratuit, latence ~15min
    - 'ig'                : IG Markets REST API, temps réel, requiert IGBroker connecté

    Si source='ig' mais que le broker IG est None ou échoue, fallback automatique
    vers yfinance pour rester opérationnel.
    """

    def __init__(self, timeframe: str = "1h", source: str = "yfinance", ig_broker=None):
        self.timeframe = timeframe
        self.source = source.lower()
        self.ig_broker = ig_broker
        self.yf_interval = TIMEFRAME_MAP.get(timeframe, "1h")
        self._cache: dict[str, pd.DataFrame] = {}

        if self.source == "ig" and self.ig_broker is None:
            logger.warning(
                "[DataFetcher] source='ig' mais broker non fourni, fallback yfinance"
            )
            self.source = "yfinance"

        logger.info(f"[DataFetcher] source={self.source}, timeframe={timeframe}")

    def fetch(self, symbol: str, lookback: int = 400, end: Optional[datetime] = None) -> pd.DataFrame:
        # Tentative IG d'abord si configuré
        if self.source == "ig" and self.ig_broker is not None:
            try:
                df = self.ig_broker.fetch_historical(
                    symbol=symbol,
                    timeframe=self.timeframe,
                    num_points=lookback,
                )
                if end is not None:
                    df = df[df.index <= pd.Timestamp(end, tz=df.index.tz)]
                self._cache[symbol] = df
                return df
            except Exception as e:
                logger.warning(
                    f"[DataFetcher] IG échec pour {symbol}: {e}. Fallback yfinance."
                )

        # Fallback yfinance
        return self._fetch_yfinance(symbol, lookback, end)

    def _fetch_yfinance(self, symbol: str, lookback: int, end: Optional[datetime]) -> pd.DataFrame:
        try:
            ticker = yf.Ticker(symbol)
            max_period = MAX_PERIOD_MAP.get(self.yf_interval, "730d")
            df = ticker.history(period=max_period, interval=self.yf_interval)

            if df.empty:
                raise ValueError(f"Aucune donnée pour {symbol}")

            df = df.rename(columns={
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
            })

            if "amount" not in df.columns:
                df["amount"] = df["volume"] * df[["open", "high", "low", "close"]].mean(axis=1)

            df = df[["open", "high", "low", "close", "volume", "amount"]]
            df = df.dropna()

            if end is not None:
                df = df[df.index <= end]

            if len(df) > lookback:
                df = df.iloc[-lookback:]

            df.index = pd.to_datetime(df.index)
            self._cache[symbol] = df
            logger.info(f"[DataFetcher] {symbol}: {len(df)} bougies (yfinance, {self.yf_interval})")
            return df

        except Exception as e:
            logger.error(f"[DataFetcher] Erreur pour {symbol}: {e}")
            raise

    def fetch_multiple(self, symbols: list[str], lookback: int = 400) -> dict[str, pd.DataFrame]:
        result = {}
        for sym in symbols:
            try:
                result[sym] = self.fetch(sym, lookback)
            except Exception as e:
                logger.warning(f"[DataFetcher] Skip {sym}: {e}")
        return result

    def get_cached(self, symbol: str) -> Optional[pd.DataFrame]:
        return self._cache.get(symbol)

    def generate_future_timestamps(self, last_timestamp: pd.Timestamp, pred_len: int) -> pd.DatetimeIndex:
        freq_map = {
            "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
            "1h": "1h", "1d": "1B", "1wk": "1W",
        }
        freq = freq_map.get(self.timeframe, "1h")
        future_idx = pd.date_range(start=last_timestamp + pd.Timedelta(freq), periods=pred_len, freq=freq)
        return future_idx

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

    def __init__(self, timeframe: str = "1h"):
        self.timeframe = timeframe
        self.yf_interval = TIMEFRAME_MAP.get(timeframe, "1h")
        self._cache: dict[str, pd.DataFrame] = {}

    def fetch(self, symbol: str, lookback: int = 400, end: Optional[datetime] = None) -> pd.DataFrame:
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
            logger.info(f"[DataFetcher] {symbol}: {len(df)} bougies ({self.yf_interval})")
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

import pandas as pd
import numpy as np
import logging
import sys
import os
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from model import Kronos, KronosTokenizer, KronosPredictor

logger = logging.getLogger(__name__)


class KronosPredictorWrapper:

    def __init__(self, model_name: str, tokenizer_name: str, max_context: int = 512, device: Optional[str] = None):
        logger.info(f"[Kronos] Chargement tokenizer: {tokenizer_name}")
        self.tokenizer = KronosTokenizer.from_pretrained(tokenizer_name)

        logger.info(f"[Kronos] Chargement modèle: {model_name}")
        self.model = Kronos.from_pretrained(model_name)

        self.predictor = KronosPredictor(self.model, self.tokenizer, device=device, max_context=max_context)
        logger.info(f"[Kronos] Prêt sur device: {self.predictor.device}")

    def predict(
        self,
        df: pd.DataFrame,
        pred_len: int = 10,
        temperature: float = 1.0,
        top_p: float = 0.9,
        top_k: int = 0,
        sample_count: int = 5,
    ) -> pd.DataFrame:
        x_timestamp = pd.Series(pd.to_datetime(df.index))
        last_ts = x_timestamp.iloc[-1]

        freq_seconds = np.median(np.diff(x_timestamp.values).astype("timedelta64[s]").astype(int))
        future_times = pd.Series(pd.date_range(
            start=last_ts + pd.Timedelta(seconds=freq_seconds),
            periods=pred_len,
            freq=pd.Timedelta(seconds=freq_seconds),
        ))

        input_df = df[["open", "high", "low", "close"]].copy()
        if "volume" in df.columns:
            input_df["volume"] = df["volume"]
        if "amount" in df.columns:
            input_df["amount"] = df["amount"]

        pred_df = self.predictor.predict(
            df=input_df,
            x_timestamp=x_timestamp,
            y_timestamp=future_times,
            pred_len=pred_len,
            T=temperature,
            top_p=top_p,
            top_k=top_k,
            sample_count=sample_count,
            verbose=False,
        )

        logger.info(f"[Kronos] Prédiction: {pred_len} bougies futures générées")
        return pred_df

    def predict_multiple(
        self,
        data_dict: dict[str, pd.DataFrame],
        pred_len: int = 10,
        temperature: float = 1.0,
        top_p: float = 0.9,
        top_k: int = 0,
        sample_count: int = 5,
    ) -> dict[str, pd.DataFrame]:
        results = {}
        for symbol, df in data_dict.items():
            try:
                results[symbol] = self.predict(df, pred_len, temperature, top_p, top_k, sample_count)
            except Exception as e:
                logger.error(f"[Kronos] Erreur prédiction {symbol}: {e}")
        return results

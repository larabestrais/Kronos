"""
IGBroker — connexion REST à IG Markets pour récupérer les prix historiques
en temps réel sur les comptes démo et réel.

Documentation IG REST :
- https://labs.ig.com/rest-trading-api-reference
- Resolution supportées : SECOND, MINUTE, MINUTE_2..30, HOUR..4, DAY, WEEK, MONTH
- Limite : 10 000 requêtes historiques / semaine sur compte démo
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import pandas as pd

from .symbol_map import to_epic, from_epic

logger = logging.getLogger(__name__)


class IGBrokerError(Exception):
    """Erreur générique remontée par IGBroker (auth, rate limit, epic invalide…)."""


# --- Mapping timeframes Kronos -> resolution IG ---
TIMEFRAME_TO_IG: dict[str, str] = {
    "1m":  "MINUTE",
    "2m":  "MINUTE_2",
    "3m":  "MINUTE_3",
    "5m":  "MINUTE_5",
    "10m": "MINUTE_10",
    "15m": "MINUTE_15",
    "30m": "MINUTE_30",
    "1h":  "HOUR",
    "2h":  "HOUR_2",
    "3h":  "HOUR_3",
    "4h":  "HOUR_4",
    "1d":  "DAY",
    "1wk": "WEEK",
    "1mo": "MONTH",
}


class IGBroker:
    """
    Wrapper haut-niveau autour de trading-ig.IGService.

    Usage:
        broker = IGBroker(username, password, api_key, account_type="DEMO")
        broker.connect()
        df = broker.fetch_historical("AAPL", timeframe="1h", num_points=400)
        broker.disconnect()
    """

    def __init__(
        self,
        username: str,
        password: str,
        api_key: str,
        account_type: str = "DEMO",
        max_retries: int = 3,
    ):
        self.username = (username or "").strip()
        self.password = (password or "").strip()
        self.api_key = (api_key or "").strip()
        self.account_type = (account_type or "DEMO").strip().upper()
        self.max_retries = max_retries

        if self.account_type not in ("DEMO", "LIVE"):
            raise IGBrokerError(
                f"account_type doit être 'DEMO' ou 'LIVE', reçu '{self.account_type}'"
            )

        if not (self.username and self.password and self.api_key):
            raise IGBrokerError(
                "IG_USERNAME, IG_PASSWORD et IG_API_KEY doivent être définis"
            )

        self._service = None
        self._epic_cache: dict[str, str] = {}
        self._connected = False

    # ------------------------------------------------------------------
    # Connexion / session
    # ------------------------------------------------------------------
    def connect(self) -> bool:
        """Établit la session IG. Retourne True si OK, raise IGBrokerError sinon."""
        try:
            from trading_ig import IGService
        except ImportError as e:
            raise IGBrokerError(
                "Le package 'trading-ig' n'est pas installé. "
                "Ajoute-le à requirements-bot.txt et reconstruis l'image."
            ) from e

        try:
            self._service = IGService(
                username=self.username,
                password=self.password,
                api_key=self.api_key,
                acc_type=self.account_type,
            )
            self._service.create_session()
            self._connected = True
            logger.info(
                f"[IG] Connecté ({self.account_type}) — user={self.username}"
            )
            return True
        except Exception as e:
            self._connected = False
            raise IGBrokerError(f"Échec connexion IG: {e}") from e

    def disconnect(self) -> None:
        if self._service is not None:
            try:
                self._service.logout()
            except Exception:
                pass
        self._connected = False
        self._service = None

    @property
    def connected(self) -> bool:
        return self._connected and self._service is not None

    # ------------------------------------------------------------------
    # Résolution d'epic (avec cache + fallback API)
    # ------------------------------------------------------------------
    def resolve_epic(self, symbol: str) -> str:
        """
        Trouve l'epic IG correspondant à un symbole.
        1) Cache local
        2) Mapping statique (symbol_map)
        3) Recherche API search_markets() avec scoring
        """
        if symbol in self._epic_cache:
            return self._epic_cache[symbol]

        # Tentative directe via le mapping connu
        epic = to_epic(symbol)
        if self._epic_exists(epic):
            self._epic_cache[symbol] = epic
            return epic

        logger.warning(
            f"[IG] Epic statique '{epic}' invalide pour {symbol}, recherche via API…"
        )

        # Fallback : recherche via API
        try:
            results = self._service.search_markets(symbol)
            if results is None or results.empty:
                raise IGBrokerError(f"Aucun marché trouvé pour {symbol}")

            # On filtre sur CASH si possible (spot/CFD)
            cash_rows = results[results["epic"].str.contains("CASH", na=False)]
            best = cash_rows.iloc[0] if not cash_rows.empty else results.iloc[0]
            epic = best["epic"]
            logger.info(f"[IG] {symbol} → {epic} (via search_markets)")

            self._epic_cache[symbol] = epic
            return epic

        except Exception as e:
            raise IGBrokerError(
                f"Impossible de résoudre l'epic pour {symbol}: {e}"
            ) from e

    def _epic_exists(self, epic: str) -> bool:
        """Vérifie qu'un epic est valide en récupérant ses détails marché."""
        try:
            details = self._service.fetch_market_by_epic(epic)
            return details is not None
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Données historiques
    # ------------------------------------------------------------------
    def fetch_historical(
        self,
        symbol: str,
        timeframe: str = "1h",
        num_points: int = 400,
    ) -> pd.DataFrame:
        """
        Récupère N dernières bougies pour un symbole.
        Retourne un DataFrame avec colonnes : open, high, low, close, volume, amount.
        Index = pandas.DatetimeIndex (UTC).
        """
        if not self.connected:
            self.connect()

        epic = self.resolve_epic(symbol)
        resolution = TIMEFRAME_TO_IG.get(timeframe, "HOUR")

        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                result = self._service.fetch_historical_prices_by_epic_and_num_points(
                    epic=epic,
                    resolution=resolution,
                    numpoints=num_points,
                )

                # Format trading-ig : dict avec clé 'prices' (DataFrame multi-index)
                if isinstance(result, dict):
                    prices_df = result.get("prices")
                else:
                    prices_df = result

                if prices_df is None or len(prices_df) == 0:
                    raise IGBrokerError(
                        f"Aucune donnée pour {symbol} (epic={epic}, res={resolution})"
                    )

                normalized = self._normalize_prices(prices_df)
                logger.info(
                    f"[IG] {symbol}: {len(normalized)} bougies ({resolution}) "
                    f"— allowance restant: {self._allowance_str(result)}"
                )
                return normalized

            except Exception as e:
                last_err = e
                wait = 2 ** attempt
                logger.warning(
                    f"[IG] Tentative {attempt}/{self.max_retries} échouée pour {symbol}: {e}. "
                    f"Retry dans {wait}s."
                )
                time.sleep(wait)

        raise IGBrokerError(
            f"Échec récupération historique pour {symbol} après {self.max_retries} tentatives: {last_err}"
        )

    def fetch_multiple(
        self,
        symbols: list[str],
        timeframe: str = "1h",
        num_points: int = 400,
    ) -> dict[str, pd.DataFrame]:
        """Récupère plusieurs symboles. Skip ceux qui échouent."""
        out: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                out[sym] = self.fetch_historical(sym, timeframe, num_points)
            except Exception as e:
                logger.warning(f"[IG] Skip {sym}: {e}")
        return out

    # ------------------------------------------------------------------
    # Normalisation prix IG -> format Kronos
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_prices(prices_df: pd.DataFrame) -> pd.DataFrame:
        """
        IG renvoie un DataFrame avec MultiIndex sur les colonnes :
        (Open, Bid), (Open, Ask), (Open, LastTraded),
        (High, Bid), (High, Ask), …, (Last, Volume)

        On calcule le mid = (bid + ask) / 2 pour OHLC, et on utilise Last Volume.
        """
        df = prices_df.copy()

        # Si MultiIndex, on flatten via mid bid/ask
        if isinstance(df.columns, pd.MultiIndex):
            normalized = pd.DataFrame(index=df.index)
            for ohlc in ("Open", "High", "Low", "Close"):
                bid = df.get((ohlc, "Bid"))
                ask = df.get((ohlc, "Ask"))
                last = df.get((ohlc, "LastTraded"))
                if bid is not None and ask is not None:
                    normalized[ohlc.lower()] = (bid + ask) / 2.0
                elif last is not None:
                    normalized[ohlc.lower()] = last
                else:
                    raise IGBrokerError(f"Colonnes prix manquantes pour {ohlc}")

            # Volume : (Last, Volume) ou ('Volume', '') selon version trading-ig
            vol = df.get(("Last", "Volume"))
            if vol is None:
                # Recherche fallback
                for col in df.columns:
                    if "Volume" in str(col):
                        vol = df[col]
                        break
            normalized["volume"] = vol.fillna(0) if vol is not None else 0
        else:
            # Colonnes simples (ancienne version trading-ig)
            rename = {}
            for c in df.columns:
                lc = c.lower().replace(" ", "")
                if lc in ("open", "high", "low", "close", "volume"):
                    rename[c] = lc
            df = df.rename(columns=rename)
            for col in ("open", "high", "low", "close"):
                if col not in df.columns:
                    raise IGBrokerError(f"Colonne {col} manquante après normalisation")
            normalized = df[["open", "high", "low", "close"]].copy()
            normalized["volume"] = df.get("volume", 0)

        # Synthétiser amount (notionnel) — Kronos l'attend
        normalized["amount"] = normalized["volume"] * normalized[
            ["open", "high", "low", "close"]
        ].mean(axis=1)

        normalized = normalized.dropna()
        normalized.index = pd.to_datetime(normalized.index, utc=True)
        return normalized[["open", "high", "low", "close", "volume", "amount"]]

    @staticmethod
    def _allowance_str(result) -> str:
        """Extrait le quota historique restant (utile pour monitorer le rate limit)."""
        if isinstance(result, dict):
            allow = result.get("allowance")
            if isinstance(allow, dict):
                rem = allow.get("remainingAllowance")
                tot = allow.get("totalAllowance")
                if rem is not None and tot is not None:
                    return f"{rem}/{tot}"
        return "?"

    # ------------------------------------------------------------------
    # Helpers diagnostics
    # ------------------------------------------------------------------
    def get_account_info(self) -> dict:
        """Retourne info compte : id, currency, balance disponible (utile pour healthcheck)."""
        if not self.connected:
            self.connect()
        try:
            accounts = self._service.fetch_accounts()
            if isinstance(accounts, dict):
                accounts = accounts.get("accounts", [])
            if hasattr(accounts, "to_dict"):
                accounts = accounts.to_dict("records")
            return {"accounts": accounts}
        except Exception as e:
            raise IGBrokerError(f"Échec fetch_accounts: {e}") from e


def from_env() -> Optional[IGBroker]:
    """
    Construit un IGBroker depuis les env vars :
      - IG_USERNAME, IG_PASSWORD, IG_API_KEY (obligatoires)
      - IG_ACC_TYPE (optionnel, défaut 'DEMO')
    Retourne None si les credentials ne sont pas configurés (silent fallback).
    """
    import os

    username = os.environ.get("IG_USERNAME", "").strip()
    password = os.environ.get("IG_PASSWORD", "").strip()
    api_key = os.environ.get("IG_API_KEY", "").strip()
    acc_type = os.environ.get("IG_ACC_TYPE", "DEMO").strip().upper()

    if not (username and password and api_key):
        logger.info(
            "[IG] Credentials non configurés (IG_USERNAME/IG_PASSWORD/IG_API_KEY) — "
            "fallback yfinance"
        )
        return None

    try:
        broker = IGBroker(username, password, api_key, account_type=acc_type)
        broker.connect()
        return broker
    except IGBrokerError as e:
        logger.error(f"[IG] Échec init depuis env: {e}")
        return None

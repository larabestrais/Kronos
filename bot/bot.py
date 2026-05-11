import os
import time
import logging
import signal as sig
from datetime import datetime

import pytz

from .config import BotConfig
from .data_fetcher import DataFetcher
from .predictor import KronosPredictorWrapper
from .signals import SignalEngine, Action
from .risk_manager import RiskManager
from .portfolio import Portfolio
from .trader import PaperTrader
from .brokers import IGBroker, IGBrokerError

logger = logging.getLogger(__name__)


class TradingBot:

    def __init__(self, config: BotConfig):
        self.config = config
        self.running = False

        logger.info("=== Initialisation du Trading Bot Kronos ===")

        # --- Broker IG (optionnel) ---
        self.ig_broker = None
        if config.data_source.lower() == "ig" and config.ig_username and config.ig_password and config.ig_api_key:
            try:
                self.ig_broker = IGBroker(
                    username=config.ig_username,
                    password=config.ig_password,
                    api_key=config.ig_api_key,
                    account_type=config.ig_account_type,
                )
                self.ig_broker.connect()
                logger.info(f"[IG] Broker connecté ({config.ig_account_type})")
            except IGBrokerError as e:
                logger.error(f"[IG] Échec connexion: {e}. Fallback yfinance.")
                self.ig_broker = None

        self.data_fetcher = DataFetcher(
            timeframe=config.timeframe,
            source=config.data_source if self.ig_broker else "yfinance",
            ig_broker=self.ig_broker,
        )

        self.predictor = KronosPredictorWrapper(
            model_name=config.model_name,
            tokenizer_name=config.tokenizer_name,
            max_context=config.max_context,
            device=config.device,
        )

        self.signal_engine = SignalEngine(
            buy_threshold=config.buy_threshold,
            sell_threshold=config.sell_threshold,
            confidence_min=config.confidence_min,
            stop_loss_pct=config.stop_loss_pct,
            take_profit_pct=config.take_profit_pct,
        )

        self.risk_manager = RiskManager(
            max_drawdown_pct=config.max_drawdown_pct,
            max_daily_loss_pct=config.max_daily_loss_pct,
            max_open_positions=config.max_open_positions,
            risk_per_trade_pct=config.risk_per_trade_pct,
            max_position_pct=config.max_position_pct,
            leverage=config.leverage,
        )

        portfolio_path = os.environ.get("PORTFOLIO_STATE_PATH", "portfolio_state.json")
        self.portfolio = Portfolio(
            initial_capital=config.initial_capital,
            save_path=portfolio_path,
            leverage=config.leverage,
        )
        self.portfolio.load()

        # --- Learning module (optionnel) ---
        self.learning_state = None
        self.learning_store = None
        self.regime_detector = None
        self.tracker = None

        if config.learning_enabled:
            try:
                from .learning import (
                    LearningStateStore, RegimeDetector, PerformanceTracker,
                )
                learning_path = os.environ.get(
                    "LEARNING_STATE_PATH",
                    os.path.join(os.path.dirname(portfolio_path), "learning_state.json"),
                )
                self.learning_store = LearningStateStore(save_path=learning_path)
                self.learning_state = self.learning_store.load()
                self.regime_detector = RegimeDetector()
                self.tracker = PerformanceTracker(self.learning_state)

                # Hook : tracker reçoit les trades fermés via callback
                def _on_trade_closed(trade, entry_price, _state=self.learning_state, _tracker=self.tracker):
                    try:
                        _tracker.record_closed_trade(trade, regime=_state.current_regime)
                    except Exception as e:
                        logger.exception(f"[Learning] tracker callback failed: {e}")

                self.portfolio.on_position_closed_callbacks.append(_on_trade_closed)

                logger.info(f"[Learning] Module activé, state: {learning_path}")
                if config.learning_dry_run:
                    logger.info("[Learning] Mode DRY-RUN actif, aucun ajustement appliqué")
            except Exception as e:
                logger.exception(f"[Learning] Échec init, désactivé: {e}")
                self.learning_state = None
                self.learning_store = None
                self.regime_detector = None
                self.tracker = None

        self.trader = PaperTrader(self.portfolio, self.risk_manager)

        logger.info(f"Symboles: {config.symbols}")
        logger.info(f"Capital: {config.initial_capital}$ | Timeframe: {config.timeframe} | Levier: {config.leverage}x")
        logger.info(f"Stop-loss: {config.stop_loss_pct*100:.1f}% | Take-profit: {config.take_profit_pct*100:.1f}%")
        logger.info("=== Bot prêt ===")

    def is_trading_hours(self) -> bool:
        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)
        start_h, start_m = map(int, self.config.trading_hours_start.split(":"))
        end_h, end_m = map(int, self.config.trading_hours_end.split(":"))

        start = now.replace(hour=start_h, minute=start_m, second=0)
        end = now.replace(hour=end_h, minute=end_m, second=0)

        if now.weekday() >= 5:
            return False

        return start <= now <= end

    def run_cycle(self) -> dict:
        cycle_results = {"signals": [], "trades": [], "errors": [], "predictions": {}, "data": {}}

        logger.info("--- Début du cycle de trading ---")

        data_dict = self.data_fetcher.fetch_multiple(self.config.symbols, self.config.lookback)
        if not data_dict:
            logger.warning("Aucune donnée récupérée")
            return cycle_results

        current_prices = {}
        for symbol, df in data_dict.items():
            current_prices[symbol] = df["close"].iloc[-1]
        self.portfolio.update_positions(current_prices)

        # --- Mise à jour du régime de marché si learning activé ---
        if self.learning_state is not None and self.regime_detector is not None:
            try:
                self._update_regime(data_dict)
            except Exception as e:
                logger.exception(f"[Learning] Erreur update_regime: {e}")

        predictions = self.predictor.predict_multiple(
            data_dict,
            pred_len=self.config.pred_len,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            top_k=self.config.top_k,
            sample_count=self.config.sample_count,
        )
        cycle_results["predictions"] = predictions
        cycle_results["data"] = data_dict

        for symbol in self.config.symbols:
            if symbol not in data_dict or symbol not in predictions:
                continue

            signal = self.signal_engine.generate(symbol, data_dict[symbol], predictions[symbol])

            # === Earnings blackout : force HOLD si symbole en fenêtre earnings ===
            from .learning.engine import is_in_earnings_blackout
            if is_in_earnings_blackout(symbol):
                if signal.action != Action.HOLD:
                    logger.warning(
                        f"[Earnings] {symbol} en blackout earnings — "
                        f"signal {signal.action.value} ignoré"
                    )
                signal.action = Action.HOLD
                signal.reason = f"EARNINGS_BLACKOUT — abstention forcée (voir EARNINGS_BLACKOUT_DATES)"

            cycle_results["signals"].append(signal)

            if signal.action != Action.HOLD:
                executed = self.trader.execute(signal)
                if executed:
                    cycle_results["trades"].append(signal)

        self.portfolio.record_equity()
        self.portfolio.save()

        summary = self.portfolio.get_summary()
        logger.info(f"Portfolio: {summary['valeur_totale']}$ | PnL: {summary['pnl_total']:+.2f}$ ({summary['pnl_total_pct']:+.1f}%)")
        logger.info(f"Positions: {summary['positions_ouvertes']} | Trades: {summary['trades_total']}")
        logger.info("--- Fin du cycle ---")

        return cycle_results

    def _update_regime(self, data_dict):
        """Calcule le régime actuel et met à jour le state."""
        import yfinance as yf
        import pandas as pd
        from datetime import datetime, timezone

        # 1. Récupère VIX (avec fallback)
        try:
            vix_ticker = yf.Ticker("^VIX")
            vix_hist = vix_ticker.history(period="1d", interval="1h")
            if len(vix_hist) == 0:
                raise ValueError("VIX history empty")
            vix = float(vix_hist["Close"].iloc[-1])
        except Exception as e:
            logger.warning(f"[Learning] VIX indisponible, fallback 15: {e}")
            vix = 15.0

        # 2. Calcule basket moyen pondéré
        if not data_dict:
            return
        symbols = list(data_dict.keys())
        # Aligner les indices avant de moyenner (dernières 200 bougies suffisent pour la pente 50)
        basket_close = None
        for s in symbols:
            df = data_dict[s]
            close_tail = df["close"].iloc[-200:]
            if basket_close is None:
                basket_close = close_tail.copy()
            else:
                # Aligne sur l'index commun (réindex sur basket_close si nécessaire)
                aligned = close_tail.reindex(basket_close.index, method="nearest")
                basket_close = basket_close.add(aligned, fill_value=0)
        if basket_close is None:
            return
        basket_close = basket_close / max(1, len(symbols))
        basket_df = pd.DataFrame({
            "open": basket_close, "high": basket_close * 1.001,
            "low": basket_close * 0.999, "close": basket_close,
            "volume": 0,
        })

        # 3. ATR ratio (sur le 1er symbole comme proxy)
        atr_ratio = self.regime_detector.compute_atr_ratio(data_dict[symbols[0]])

        # 4. Classification
        new_regime = self.regime_detector.classify(vix, basket_df, atr_ratio)
        if new_regime != self.learning_state.current_regime:
            logger.info(
                f"[Learning] Régime change : {self.learning_state.current_regime.value} → {new_regime.value}"
            )
            self.learning_state.current_regime = new_regime
            self.learning_state.regime_stable_since = datetime.now(timezone.utc).isoformat()

        # Sauvegarde après chaque cycle
        if self.learning_store:
            self.learning_store.save(self.learning_state)

    def run(self):
        self.running = True
        sig.signal(sig.SIGINT, lambda *_: setattr(self, "running", False))

        logger.info("Bot démarré. Ctrl+C pour arrêter.")

        while self.running:
            try:
                if self.is_trading_hours():
                    self.run_cycle()
                else:
                    logger.info("Hors heures de trading. En attente...")

                if self.running:
                    logger.info(f"Prochain cycle dans {self.config.poll_interval_seconds}s")
                    time.sleep(self.config.poll_interval_seconds)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Erreur dans le cycle: {e}", exc_info=True)
                time.sleep(60)

        logger.info("Bot arrêté.")
        self.portfolio.save()

    def run_once(self) -> dict:
        return self.run_cycle()

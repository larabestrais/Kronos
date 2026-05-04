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

logger = logging.getLogger(__name__)


class TradingBot:

    def __init__(self, config: BotConfig):
        self.config = config
        self.running = False

        logger.info("=== Initialisation du Trading Bot Kronos ===")

        self.data_fetcher = DataFetcher(timeframe=config.timeframe)

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

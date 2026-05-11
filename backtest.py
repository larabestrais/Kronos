#!/usr/bin/env python3
"""
Kronos Trading Bot — Backtester

Simule le bot sur données historiques pour évaluer la stratégie.
"""
import argparse
import logging
import json

import pandas as pd
import numpy as np

from bot.config import BotConfig
from bot.data_fetcher import DataFetcher
from bot.predictor import KronosPredictorWrapper
from bot.signals import SignalEngine, Action
from bot.risk_manager import RiskManager
from bot.portfolio import Portfolio
from bot.trader import PaperTrader

logger = logging.getLogger(__name__)


class Backtester:

    def __init__(self, config: BotConfig):
        self.config = config
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
        )

    def run(self, symbol: str, window_size: int = 400, step: int = 10, with_learning: bool = False) -> dict:
        logger.info(f"=== Backtest {symbol} ===")

        full_data = self.data_fetcher.fetch(symbol, lookback=5000)
        if len(full_data) < window_size + self.config.pred_len:
            raise ValueError(f"Pas assez de données pour {symbol}: {len(full_data)} bougies")

        portfolio = Portfolio(initial_capital=self.config.initial_capital)
        trader = PaperTrader(portfolio, self.risk_manager)

        # --- Learning (optional, enabled with --with-learning flag) ---
        learning_state = None
        learning_tracker = None
        learning_engine = None
        if with_learning:
            from bot.learning import (
                LearningState, PerformanceTracker, AdaptationEngine,
            )
            learning_state = LearningState()
            learning_tracker = PerformanceTracker(learning_state)
            learning_engine = AdaptationEngine(learning_state, dry_run=False)
            print("[Backtest] Learning module activated (collecting stats during replay)")

        total_steps = (len(full_data) - window_size - self.config.pred_len) // step
        logger.info(f"Données: {len(full_data)} bougies | {total_steps} étapes de backtest")

        results = []

        for i in range(0, len(full_data) - window_size - self.config.pred_len, step):
            window = full_data.iloc[i : i + window_size]
            future_actual = full_data.iloc[i + window_size : i + window_size + self.config.pred_len]

            try:
                prediction = self.predictor.predict(
                    window,
                    pred_len=self.config.pred_len,
                    temperature=self.config.temperature,
                    top_p=self.config.top_p,
                    sample_count=self.config.sample_count,
                )
            except Exception as e:
                logger.warning(f"Erreur prédiction step {i}: {e}")
                continue

            current_price = window["close"].iloc[-1]
            portfolio.update_positions({symbol: current_price})

            signal = self.signal_engine.generate(symbol, window, prediction)

            if signal.action != Action.HOLD:
                trader.execute(signal)

            portfolio.record_equity()

            pred_close = prediction["close"].mean()
            actual_close = future_actual["close"].mean() if len(future_actual) > 0 else None

            results.append({
                "step": i,
                "timestamp": window.index[-1].isoformat(),
                "current_price": current_price,
                "predicted_close": pred_close,
                "actual_close": actual_close,
                "signal": signal.action.value,
                "confidence": signal.confidence,
                "portfolio_value": portfolio.total_value,
            })

            if (i // step) % 10 == 0:
                logger.info(f"  Step {i // step}/{total_steps} | Portfolio: {portfolio.total_value:.2f}$")

        for symbol_pos in list(portfolio.positions.keys()):
            last_price = full_data["close"].iloc[-1]
            portfolio.close_position(symbol_pos, last_price, reason="Fin backtest")

        # Feed all closed trades to the learning tracker (post-hoc, regime defaults to RANGING)
        if learning_tracker is not None:
            from bot.learning.types import Regime
            for t in portfolio.trades:
                if "CLOSE" in t.side:
                    learning_tracker.record_closed_trade(t, regime=Regime.RANGING)

        if learning_state is not None:
            print("\n=== Learning module summary ===")
            for sym, by_regime in learning_state.symbol_stats_by_regime.items():
                for regime, stats in by_regime.items():
                    if stats.trades > 0:
                        print(f"  {sym} {regime}: {stats.trades} trades, "
                              f"win_rate={stats.win_rate:.0%}, "
                              f"expectancy={stats.expectancy:+.4f}")
            proposals = learning_engine.propose_adjustments() if learning_engine else []
            print(f"  Total proposals computed: {len(proposals)}")

        summary = portfolio.get_summary()
        results_df = pd.DataFrame(results)

        if not results_df.empty and "actual_close" in results_df.columns:
            valid = results_df.dropna(subset=["actual_close"])
            if len(valid) > 0:
                direction_correct = (
                    (valid["predicted_close"] > valid["current_price"]) == (valid["actual_close"] > valid["current_price"])
                )
                summary["precision_direction"] = round(direction_correct.mean() * 100, 1)
                mae = (valid["predicted_close"] - valid["actual_close"]).abs().mean()
                summary["mae"] = round(mae, 4)

        winning_trades = [t for t in portfolio.trades if t.pnl > 0 and "CLOSE" in t.side]
        losing_trades = [t for t in portfolio.trades if t.pnl <= 0 and "CLOSE" in t.side]
        total_closed = len(winning_trades) + len(losing_trades)
        summary["win_rate"] = round(len(winning_trades) / total_closed * 100, 1) if total_closed > 0 else 0
        summary["avg_win"] = round(np.mean([t.pnl for t in winning_trades]), 2) if winning_trades else 0
        summary["avg_loss"] = round(np.mean([t.pnl for t in losing_trades]), 2) if losing_trades else 0

        returns = results_df["portfolio_value"].pct_change().dropna()
        if len(returns) > 0 and returns.std() > 0:
            summary["sharpe"] = round((returns.mean() / returns.std()) * np.sqrt(252), 2)
        else:
            summary["sharpe"] = 0

        return {
            "summary": summary,
            "results": results_df,
            "trades": [{"symbol": t.symbol, "side": t.side, "price": t.price, "pnl": t.pnl, "reason": t.reason} for t in portfolio.trades],
            "equity": portfolio.get_equity_df(),
        }


def print_report(symbol: str, result: dict):
    s = result["summary"]
    print(f"\n{'='*60}")
    print(f"  RAPPORT DE BACKTEST — {symbol}")
    print(f"{'='*60}")
    print(f"  Capital initial:      {s['capital_initial']:>10.2f} $")
    print(f"  Valeur finale:        {s['valeur_totale']:>10.2f} $")
    print(f"  PnL total:            {s['pnl_total']:>+10.2f} $ ({s['pnl_total_pct']:+.1f}%)")
    print(f"  Drawdown max:         {s['drawdown']:>10.1f} %")
    print(f"  Sharpe ratio:         {s.get('sharpe', 'N/A'):>10}")
    print(f"  Win rate:             {s.get('win_rate', 'N/A'):>10} %")
    print(f"  Gain moyen:           {s.get('avg_win', 'N/A'):>+10} $")
    print(f"  Perte moyenne:        {s.get('avg_loss', 'N/A'):>+10} $")
    print(f"  Trades total:         {s['trades_total']:>10}")
    if "precision_direction" in s:
        print(f"  Précision direction:  {s['precision_direction']:>10.1f} %")
    if "mae" in s:
        print(f"  MAE prédiction:       {s['mae']:>10.4f}")
    print(f"{'='*60}")

    if result["trades"]:
        print(f"\n  Derniers trades:")
        for t in result["trades"][-10:]:
            pnl_str = f"PnL: {t['pnl']:+.2f}$" if t["pnl"] != 0 else ""
            print(f"    {t['side']:>12} {symbol} @ {t['price']:.2f}$ {pnl_str} {t['reason']}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Kronos Backtester")
    parser.add_argument("--symbol", default="AAPL", help="Symbole à backtester")
    parser.add_argument("--capital", type=float, default=10000.0, help="Capital initial")
    parser.add_argument("--timeframe", default="1d", help="Timeframe")
    parser.add_argument("--window", type=int, default=400, help="Taille de la fenêtre lookback")
    parser.add_argument("--step", type=int, default=5, help="Pas entre chaque prédiction")
    parser.add_argument("--pred-len", type=int, default=10, help="Bougies à prédire")
    parser.add_argument("--model", default="NeoQuasar/Kronos-small", help="Modèle Kronos")
    parser.add_argument("--save", type=str, help="Sauvegarder résultats en JSON")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--with-learning",
        action="store_true",
        help="Active le module d'apprentissage pendant le backtest (collecte stats, applique ajustements en dry-run)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = BotConfig(
        model_name=args.model,
        initial_capital=args.capital,
        timeframe=args.timeframe,
        pred_len=args.pred_len,
    )

    backtester = Backtester(config)
    result = backtester.run(
        args.symbol,
        window_size=args.window,
        step=args.step,
        with_learning=args.with_learning,
    )

    print_report(args.symbol, result)

    if args.save:
        save_data = {
            "symbol": args.symbol,
            "config": {
                "capital": args.capital,
                "timeframe": args.timeframe,
                "window": args.window,
                "step": args.step,
                "pred_len": args.pred_len,
                "model": args.model,
            },
            "summary": result["summary"],
            "trades": result["trades"],
        }
        with open(args.save, "w") as f:
            json.dump(save_data, f, indent=2, default=str)
        print(f"Résultats sauvegardés: {args.save}")


if __name__ == "__main__":
    main()

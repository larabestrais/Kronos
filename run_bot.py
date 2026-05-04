#!/usr/bin/env python3
"""
Kronos Trading Bot — Point d'entrée principal
"""
import argparse
import logging
import json

from bot.config import BotConfig
from bot.bot import TradingBot


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(description="Kronos Trading Bot")
    parser.add_argument("--symbols", nargs="+", default=["AAPL", "MSFT", "GOOGL"], help="Symboles à trader")
    parser.add_argument("--capital", type=float, default=10000.0, help="Capital initial ($)")
    parser.add_argument("--timeframe", default="1h", choices=["1m", "5m", "15m", "30m", "1h", "1d"], help="Timeframe")
    parser.add_argument("--model", default="NeoQuasar/Kronos-small", help="Modèle Kronos")
    parser.add_argument("--pred-len", type=int, default=10, help="Nombre de bougies à prédire")
    parser.add_argument("--once", action="store_true", help="Exécuter un seul cycle puis quitter")
    parser.add_argument("--interval", type=int, default=300, help="Intervalle entre cycles (secondes)")
    parser.add_argument("--log-level", default="INFO", help="Niveau de log")
    parser.add_argument("--config", type=str, help="Fichier de config JSON")

    args = parser.parse_args()
    setup_logging(args.log_level)

    if args.config:
        with open(args.config) as f:
            config_data = json.load(f)
        config = BotConfig(**config_data)
    else:
        config = BotConfig(
            symbols=args.symbols,
            initial_capital=args.capital,
            timeframe=args.timeframe,
            model_name=args.model,
            pred_len=args.pred_len,
            poll_interval_seconds=args.interval,
        )

    bot = TradingBot(config)

    if args.once:
        results = bot.run_once()
        print("\n=== Résultats du cycle ===")
        for sig in results["signals"]:
            print(f"  {sig.symbol}: {sig.action.value} | Confiance: {sig.confidence:.0%} | {sig.reason}")
        print(f"\nPortfolio: {json.dumps(bot.portfolio.get_summary(), indent=2)}")
    else:
        bot.run()


if __name__ == "__main__":
    main()

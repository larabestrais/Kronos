# Kronos Trading Bot + Dashboard

A live trading bot built on top of the [Kronos](README.md) foundation model, with a cyberpunk-style real-time dashboard.

> ⚠️ **Disclaimer**: This is a paper-trading prototype for research and educational purposes only. It is not financial advice and does not execute real orders. Backtests use historical data fetched via `yfinance`.

## Features

- **Kronos predictions**: wraps `KronosPredictor` for live OHLCV forecasting on any Yahoo-Finance ticker.
- **Signal engine**: turns predicted candles into BUY/SELL/HOLD signals with a confidence score (combines predicted return, trend slope, volatility, SMA, momentum).
- **Risk manager**: position sizing based on stop-loss distance, with caps on drawdown, daily loss, max open positions, and per-trade risk.
- **Paper trader & portfolio**: tracks long/short positions, stop-loss / take-profit, equity curve, trade history. Persists state to `portfolio_state.json`.
- **Backtester**: rolling-window evaluation with directional accuracy, Sharpe, win-rate, and trade list.
- **Web dashboard** (`webapp/`): Flask + vanilla JS, dense cyberpunk UI with live equity chart, volume bars, signal radar, news ribbon, positions, confidence mix, symbol yield.

## Project structure

```
bot/                       # Core bot library
├── config.py              # BotConfig dataclass
├── data_fetcher.py        # yfinance OHLCV fetcher
├── predictor.py           # KronosPredictor wrapper
├── signals.py             # Signal generation + confidence scoring
├── risk_manager.py        # Position sizing & risk gates
├── portfolio.py           # Positions, trades, equity, persistence
├── trader.py              # Paper trade execution
└── bot.py                 # Orchestrator with CET trading hours

webapp/                    # Flask dashboard
├── app.py                 # API: /api/state, /api/cycle, /api/reset
├── templates/dashboard.html
└── static/css/dashboard.css
└── static/js/dashboard.js # Polling, canvas charts, animations

run_bot.py                 # CLI: one-shot or continuous bot loop
run_dashboard.py           # CLI: launches Flask dashboard
backtest.py                # CLI: rolling-window backtest
setup.sh                   # Bootstrap venv + install deps
requirements-bot.txt       # Bot extras on top of Kronos requirements
```

## Quick start

```bash
# 1. Install (creates venv/, requires Python 3.10+)
./setup.sh
source venv/bin/activate

# 2. Run a single cycle on a few tickers
python run_bot.py --once --symbols AAPL MSFT GOOGL --capital 10000 --timeframe 1d

# 3. Or run the dashboard
python run_dashboard.py
# open http://127.0.0.1:5050 — click ▶ RUN CYCLE

# 4. Or backtest a single ticker
python backtest.py --symbol AAPL --timeframe 1d --window 400 --step 5
```

## Configuration

Edit `bot/config.py` or pass CLI flags. Defaults are set for European hours (15:30–22:00 CET) on US equities, daily timeframe.

| Param | Default | Notes |
|---|---|---|
| `model_name` | `NeoQuasar/Kronos-small` | Hugging Face model id |
| `pred_len` | 10 | Candles to forecast |
| `lookback` | 400 | Historical context window |
| `sample_count` | 5 | Monte-Carlo samples averaged |
| `buy_threshold` | 0.01 | Min predicted return to buy |
| `confidence_min` | 0.60 | Min confidence score |
| `stop_loss_pct` | 0.03 | Stop-loss distance |
| `take_profit_pct` | 0.06 | Take-profit distance |
| `max_drawdown_pct` | 0.10 | Halts trading above this DD |
| `risk_per_trade_pct` | 0.02 | Capital risked per trade |

## Caveats

- Kronos returns raw price-series forecasts — for production trading you would still need proper alpha extraction, factor neutralization, transaction-cost modeling, and slippage simulation. See the upstream Kronos README.
- `yfinance` data has gaps and adjustments that may differ from a real broker feed (e.g. IG Markets).
- The dashboard is a `localhost`-only Flask dev server — do not expose it publicly without auth.
- The risk manager uses fixed-fraction sizing; it does not perform portfolio-level optimization.

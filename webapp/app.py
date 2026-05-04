import sys
import os
import json
import time
import logging
import threading
import secrets
from pathlib import Path
from datetime import datetime, timedelta
from collections import deque
from functools import wraps

from flask import Flask, render_template, jsonify, request, Response

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.config import BotConfig
from bot.bot import TradingBot
from bot.signals import Action

logger = logging.getLogger(__name__)

# Charge les credentials depuis .env si présent
ENV_FILE = Path(__file__).parent.parent / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

DASHBOARD_USER = os.environ.get("DASHBOARD_USER", "kronos")
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
AUTH_ENABLED = bool(DASHBOARD_PASSWORD)

# Auto-scheduler config
AUTO_CYCLE_ENABLED = os.environ.get("AUTO_CYCLE_ENABLED", "true").lower() == "true"
AUTO_CYCLE_INTERVAL_SECONDS = int(os.environ.get("AUTO_CYCLE_INTERVAL_SECONDS", "3600"))
RESPECT_TRADING_HOURS = os.environ.get("RESPECT_TRADING_HOURS", "true").lower() == "true"

app = Flask(__name__, static_folder="static", template_folder="templates")


def check_auth(username: str, password: str) -> bool:
    if not AUTH_ENABLED:
        return True
    return secrets.compare_digest(username, DASHBOARD_USER) and secrets.compare_digest(password, DASHBOARD_PASSWORD)


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not AUTH_ENABLED:
            return f(*args, **kwargs)
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                "Authentification requise",
                401,
                {"WWW-Authenticate": 'Basic realm="Kronos Signal Grid"'},
            )
        return f(*args, **kwargs)
    return decorated

_bot: TradingBot | None = None
_bot_lock = threading.Lock()
_news_feed: deque = deque(maxlen=20)
_last_predictions: dict = {}
_last_signals: dict = {}
_cycle_running = False
_last_cycle_time: datetime | None = None
_next_cycle_time: datetime | None = None
_scheduler_thread: threading.Thread | None = None


def get_bot() -> TradingBot:
    global _bot
    if _bot is None:
        config = BotConfig(
            symbols=["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA"],
            initial_capital=10000.0,
            timeframe="1d",
            pred_len=10,
        )
        _bot = TradingBot(config)
    return _bot


def push_news(category: str, message: str):
    _news_feed.appendleft({
        "category": category,
        "message": message,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    })


def run_cycle_async():
    global _cycle_running, _last_cycle_time
    if _cycle_running:
        return
    _cycle_running = True
    try:
        bot = get_bot()
        push_news("SCAN", f"Cycle de prédiction lancé sur {len(bot.config.symbols)} symboles")
        results = bot.run_once()

        for sig in results.get("signals", []):
            _last_signals[sig.symbol] = {
                "symbol": sig.symbol,
                "action": sig.action.value,
                "confidence": float(sig.confidence),
                "predicted_return": float(sig.predicted_return),
                "predicted_close": float(sig.predicted_close),
                "current_close": float(sig.current_close),
                "stop_loss": float(sig.stop_loss),
                "take_profit": float(sig.take_profit),
                "reason": sig.reason,
            }
            if sig.action != Action.HOLD:
                push_news(sig.action.value, f"{sig.symbol} {sig.action.value} @ {sig.current_close:.2f}$ — {sig.predicted_return:+.2%}")

        predictions_dict = results.get("predictions", {})
        data_dict = results.get("data", {}) or (bot.data_fetcher._cache or {})

        for sym, df in data_dict.items():
            history_records = []
            for ts, row in df.tail(120).iterrows():
                history_records.append({
                    "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0)),
                })

            prediction_records = []
            pred_df = predictions_dict.get(sym)
            if pred_df is not None:
                for ts, row in pred_df.iterrows():
                    prediction_records.append({
                        "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row.get("volume", 0)),
                    })

            _last_predictions[sym] = {
                "history": history_records,
                "prediction": prediction_records,
            }

        push_news("RESOLVE", f"Cycle terminé — Portfolio: {bot.portfolio.total_value:.2f}$")
        _last_cycle_time = datetime.now()
    except Exception as e:
        logger.error(f"Erreur cycle: {e}", exc_info=True)
        push_news("ERROR", f"Erreur: {str(e)[:80]}")
    finally:
        _cycle_running = False


def auto_scheduler_loop():
    """Boucle qui lance des cycles automatiquement pendant les heures de marché."""
    global _next_cycle_time
    logger.info(f"[AutoScheduler] Démarrage — interval: {AUTO_CYCLE_INTERVAL_SECONDS}s, respect heures: {RESPECT_TRADING_HOURS}")
    time.sleep(20)  # let app finish booting

    while True:
        try:
            bot = get_bot()
            in_hours = bot.is_trading_hours() if RESPECT_TRADING_HOURS else True

            if not in_hours:
                _next_cycle_time = None
                logger.debug("[AutoScheduler] Hors heures de marché")
                time.sleep(300)
                continue

            if _cycle_running:
                logger.debug("[AutoScheduler] Cycle déjà en cours, attente")
                time.sleep(30)
                continue

            push_news("SCAN", "Cycle automatique déclenché")
            run_cycle_async()

            wait_start = time.time()
            while _cycle_running and (time.time() - wait_start < 600):
                time.sleep(5)

            _next_cycle_time = datetime.now() + timedelta(seconds=AUTO_CYCLE_INTERVAL_SECONDS)
            logger.info(f"[AutoScheduler] Prochain cycle à {_next_cycle_time.strftime('%H:%M:%S')}")
            time.sleep(AUTO_CYCLE_INTERVAL_SECONDS)

        except Exception as e:
            logger.error(f"[AutoScheduler] Erreur: {e}", exc_info=True)
            time.sleep(120)


@app.route("/")
@require_auth
def index():
    return render_template("dashboard.html")


@app.route("/api/state")
@require_auth
def api_state():
    bot = get_bot()
    p = bot.portfolio
    summary = p.get_summary()

    open_positions = []
    for sym, pos in p.positions.items():
        last_price = bot.data_fetcher._cache.get(sym, {})
        current_price = last_price["close"].iloc[-1] if hasattr(last_price, "empty") and not last_price.empty else pos.entry_price
        pos.update_pnl(current_price)
        open_positions.append({
            "symbol": pos.symbol,
            "side": pos.side,
            "shares": pos.shares,
            "entry_price": pos.entry_price,
            "current_price": current_price,
            "stop_loss": pos.stop_loss,
            "take_profit": pos.take_profit,
            "unrealized_pnl": pos.unrealized_pnl,
            "pnl_pct": (pos.unrealized_pnl / (pos.shares * pos.entry_price)) * 100 if pos.shares > 0 else 0,
            "entry_time": pos.entry_time,
        })

    closed_trades = [t for t in p.trades if "CLOSE" in t.side]
    winning = [t for t in closed_trades if t.pnl > 0]
    win_rate = (len(winning) / len(closed_trades) * 100) if closed_trades else 0

    long_pos = sum(1 for pos in p.positions.values() if pos.side == "LONG")
    total_pos = max(p.open_position_count, 1)
    long_pct = long_pos / total_pos * 100

    equity = p.get_equity_df()
    equity_data = []
    if not equity.empty:
        equity_data = equity.tail(120).to_dict(orient="records")

    return jsonify({
        "summary": summary,
        "win_rate": round(win_rate, 1),
        "long_pct": round(long_pct, 1),
        "short_pct": round(100 - long_pct, 1),
        "positions": open_positions,
        "trades": [
            {"symbol": t.symbol, "side": t.side, "price": t.price, "pnl": t.pnl, "timestamp": t.timestamp, "reason": t.reason}
            for t in p.trades[-15:]
        ],
        "signals": list(_last_signals.values()),
        "news": list(_news_feed),
        "equity": equity_data,
        "predictions": _last_predictions,
        "config": {
            "symbols": bot.config.symbols,
            "timeframe": bot.config.timeframe,
            "model": bot.config.model_name,
            "pred_len": bot.config.pred_len,
        },
        "cycle_running": _cycle_running,
        "is_trading_hours": bot.is_trading_hours(),
        "auto_cycle": {
            "enabled": AUTO_CYCLE_ENABLED,
            "interval_seconds": AUTO_CYCLE_INTERVAL_SECONDS,
            "respect_trading_hours": RESPECT_TRADING_HOURS,
            "last_cycle": _last_cycle_time.isoformat() if _last_cycle_time else None,
            "next_cycle": _next_cycle_time.isoformat() if _next_cycle_time else None,
        },
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/api/cycle", methods=["POST"])
@require_auth
def api_run_cycle():
    if _cycle_running:
        return jsonify({"status": "already_running"}), 409
    thread = threading.Thread(target=run_cycle_async, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/predictions/<symbol>")
@require_auth
def api_predictions(symbol: str):
    if symbol not in _last_predictions:
        return jsonify({"error": "no_data"}), 404
    return jsonify(_last_predictions[symbol])


_chart_cache: dict = {}
_chart_cache_lock = threading.Lock()


@app.route("/api/chart-data")
@require_auth
def api_chart_data():
    """Retourne les bougies OHLCV pour un symbole/timeframe donné, avec cache 60s."""
    symbol = request.args.get("symbol", "AAPL").upper()
    timeframe = request.args.get("timeframe", "1d")
    bars = int(request.args.get("bars", "120"))

    cache_key = f"{symbol}:{timeframe}:{bars}"
    now_ts = time.time()

    with _chart_cache_lock:
        cached = _chart_cache.get(cache_key)
        if cached and (now_ts - cached["fetched_at"]) < 60:
            return jsonify(cached["payload"])

    try:
        from bot.data_fetcher import DataFetcher
        fetcher = DataFetcher(timeframe=timeframe)
        df = fetcher.fetch(symbol, lookback=bars)

        candles = []
        for ts, row in df.iterrows():
            candles.append({
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0)),
            })

        prediction = []
        if symbol in _last_predictions:
            prediction = _last_predictions[symbol].get("prediction") or []

        payload = {
            "symbol": symbol,
            "timeframe": timeframe,
            "candles": candles,
            "prediction": prediction,
            "fetched_at": now_ts,
        }

        with _chart_cache_lock:
            _chart_cache[cache_key] = {"fetched_at": now_ts, "payload": payload}

        return jsonify(payload)
    except Exception as e:
        logger.error(f"[chart-data] {symbol}/{timeframe}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/reset", methods=["POST"])
@require_auth
def api_reset():
    global _bot, _last_signals, _last_predictions, _news_feed
    state_file = Path("portfolio_state.json")
    if state_file.exists():
        state_file.unlink()
    _bot = None
    _last_signals = {}
    _last_predictions = {}
    _news_feed.clear()
    push_news("SYSTEM", "État du bot réinitialisé")
    return jsonify({"status": "reset"})


def create_app():
    push_news("SYSTEM", "Dashboard Kronos initialisé")
    if AUTH_ENABLED:
        logger.info(f"[Auth] Authentification activée pour user: {DASHBOARD_USER}")
    else:
        logger.warning("[Auth] AUCUNE AUTHENTIFICATION — définir DASHBOARD_PASSWORD dans .env pour sécuriser")

    if AUTO_CYCLE_ENABLED:
        global _scheduler_thread
        if _scheduler_thread is None or not _scheduler_thread.is_alive():
            _scheduler_thread = threading.Thread(target=auto_scheduler_loop, daemon=True, name="auto-scheduler")
            _scheduler_thread.start()
            push_news("SYSTEM", f"Auto-scheduler ON — cycle toutes les {AUTO_CYCLE_INTERVAL_SECONDS // 60} min")
            logger.info(f"[AutoScheduler] Thread démarré")

    return app

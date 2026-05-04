import sys
import os
import json
import logging
import threading
import secrets
from pathlib import Path
from datetime import datetime
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
    global _cycle_running
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
                "confidence": sig.confidence,
                "predicted_return": sig.predicted_return,
                "predicted_close": sig.predicted_close,
                "current_close": sig.current_close,
                "stop_loss": sig.stop_loss,
                "take_profit": sig.take_profit,
                "reason": sig.reason,
            }
            if sig.action != Action.HOLD:
                push_news(sig.action.value, f"{sig.symbol} {sig.action.value} @ {sig.current_close:.2f}$ — {sig.predicted_return:+.2%}")

        for sym, df in (bot.data_fetcher._cache or {}).items():
            _last_predictions[sym] = {
                "history": df.tail(60).reset_index().to_dict(orient="records"),
            }

        push_news("RESOLVE", f"Cycle terminé — Portfolio: {bot.portfolio.total_value:.2f}$")
    except Exception as e:
        logger.error(f"Erreur cycle: {e}", exc_info=True)
        push_news("ERROR", f"Erreur: {str(e)[:80]}")
    finally:
        _cycle_running = False


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
    return app

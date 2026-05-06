from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BotConfig:
    # --- Kronos Model ---
    model_name: str = "NeoQuasar/Kronos-small"
    tokenizer_name: str = "NeoQuasar/Kronos-Tokenizer-base"
    max_context: int = 512
    device: Optional[str] = None

    # --- Prediction ---
    lookback: int = 400
    pred_len: int = 10
    temperature: float = 1.0
    top_p: float = 0.9
    top_k: int = 0
    sample_count: int = 5

    # --- Trading ---
    symbols: list = field(default_factory=lambda: ["AAPL", "MSFT", "GOOGL"])
    timeframe: str = "1h"
    initial_capital: float = 10000.0
    max_position_pct: float = 0.20
    stop_loss_pct: float = 0.03
    take_profit_pct: float = 0.06
    leverage: float = 1.0  # 1 = pas de levier, 5 = typique CFD US retail EU

    # --- Data source ---
    data_source: str = "yfinance"  # 'yfinance' ou 'ig'
    ig_username: Optional[str] = None
    ig_password: Optional[str] = None
    ig_api_key: Optional[str] = None
    ig_account_type: str = "DEMO"  # 'DEMO' ou 'LIVE'

    # --- Signals ---
    buy_threshold: float = 0.01
    sell_threshold: float = -0.01
    confidence_min: float = 0.6

    # --- Risk ---
    max_drawdown_pct: float = 0.10
    max_daily_loss_pct: float = 0.03
    max_open_positions: int = 3
    risk_per_trade_pct: float = 0.02

    # --- Scheduling ---
    poll_interval_seconds: int = 300
    trading_hours_start: str = "15:30"
    trading_hours_end: str = "22:00"
    timezone: str = "Europe/Brussels"

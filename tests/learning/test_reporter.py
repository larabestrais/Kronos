from bot.learning.types import (
    LearningState, Regime, SymbolStats, SymbolParams,
    ProposedAdjustment, ProposalStatus,
)
from bot.learning.reporter import DailyReporter


def test_format_message_basic():
    state = LearningState()
    state.current_regime = Regime.TREND_UP
    state.current_params = {"AAPL": SymbolParams(confidence_min=0.58)}
    state.symbol_stats_by_regime = {
        "AAPL": {"TREND_UP": SymbolStats(trades=12, wins=8, losses=4, expectancy=0.018, pnl_30d=4.2)}
    }
    reporter = DailyReporter(state)
    msg = reporter.format_daily_message(
        trades_today=4, wins_today=3, losses_today=1, pnl_today=2.34,
        equity=200.31, sharpe_30d=1.42, win_rate_30d=0.58,
        drawdown_30d=-0.032, expectancy_30d=0.0032,
        auto_applied=[], pending=[],
    )
    assert "TREND_UP" in msg
    assert "+2.34" in msg or "2.34" in msg
    assert "1.42" in msg


def test_format_includes_auto_adjustments():
    state = LearningState()
    state.current_regime = Regime.TREND_UP
    reporter = DailyReporter(state)
    auto = [ProposedAdjustment(
        id="x", type="confidence_min_change",
        param_path="current_params.AAPL.confidence_min",
        from_value=0.60, to_value=0.58,
        reason="win rate 68%", confidence_score=0.7,
        proposed_at="2026-05-08T22:00:00Z", applied_by=ProposalStatus.AUTO,
    )]
    msg = reporter.format_daily_message(
        trades_today=0, wins_today=0, losses_today=0, pnl_today=0,
        equity=200, sharpe_30d=1.0, win_rate_30d=0.5,
        drawdown_30d=0, expectancy_30d=0,
        auto_applied=auto, pending=[],
    )
    assert "AAPL" in msg
    assert "0.60" in msg
    assert "0.58" in msg


def test_format_includes_pending_approvals():
    state = LearningState()
    state.current_regime = Regime.HIGH_VOLATILITY
    reporter = DailyReporter(state)
    pending = [ProposedAdjustment(
        id="abc", type="leverage_change", param_path="global_leverage",
        from_value=5.0, to_value=4.0,
        reason="VIX 24, drawdown -3.5%", confidence_score=0.78,
        proposed_at="2026-05-08T22:00:00Z", applied_by=ProposalStatus.VALIDATION,
    )]
    msg = reporter.format_daily_message(
        trades_today=0, wins_today=0, losses_today=0, pnl_today=0,
        equity=200, sharpe_30d=1.0, win_rate_30d=0.5,
        drawdown_30d=0, expectancy_30d=0,
        auto_applied=[], pending=pending,
    )
    # Vérifie qu'il mentionne validation et les valeurs
    assert ("VALIDATION" in msg or "Validation" in msg or "alidation" in msg)
    assert "5.0" in msg or "5" in msg
    assert "4.0" in msg or "4" in msg


def test_callback_buttons_for_pending():
    state = LearningState()
    reporter = DailyReporter(state)
    pending = [ProposedAdjustment(
        id="abc", type="leverage_change", param_path="global_leverage",
        from_value=5.0, to_value=4.0, reason="x", confidence_score=0.8,
        proposed_at="2026-05-08T22:00:00Z", applied_by=ProposalStatus.VALIDATION,
    )]
    buttons = reporter.build_inline_keyboard(pending)
    # 1 row par proposition, 3 boutons par row
    assert len(buttons) == 1
    assert len(buttons[0]) == 3
    assert "approve" in buttons[0][0]["callback_data"]
    assert "abc" in buttons[0][0]["callback_data"]


def test_sharpe_emoji_for_high_value():
    state = LearningState()
    reporter = DailyReporter(state)
    msg = reporter.format_daily_message(
        trades_today=0, wins_today=0, losses_today=0, pnl_today=0,
        equity=200, sharpe_30d=2.5, win_rate_30d=0.5,
        drawdown_30d=0, expectancy_30d=0,
        auto_applied=[], pending=[],
    )
    # Sharpe excellent (>=2) doit afficher l'emoji ✨
    assert "2.50" in msg
    assert "✨" in msg

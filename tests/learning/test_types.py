import pytest
from bot.learning.types import Regime, SymbolStats, ProposedAdjustment, LearningState


def test_regime_enum_values():
    assert Regime.TREND_UP.value == "TREND_UP"
    assert Regime.TREND_DOWN.value == "TREND_DOWN"
    assert Regime.RANGING.value == "RANGING"
    assert Regime.HIGH_VOLATILITY.value == "HIGH_VOLATILITY"


def test_symbol_stats_default():
    s = SymbolStats()
    assert s.trades == 0
    assert s.wins == 0
    assert s.losses == 0
    assert s.expectancy == 0.0
    assert s.pnl_30d == 0.0


def test_symbol_stats_win_rate():
    s = SymbolStats(trades=10, wins=6, losses=4)
    assert s.win_rate == 0.6


def test_symbol_stats_win_rate_zero_trades():
    s = SymbolStats()
    assert s.win_rate == 0.0


def test_proposed_adjustment_required_fields():
    p = ProposedAdjustment(
        id="abc",
        type="leverage_change",
        param_path="leverage",
        from_value=5.0,
        to_value=4.0,
        reason="VIX high",
        confidence_score=0.8,
        proposed_at="2026-05-08T22:00:00Z",
        applied_by="VALIDATION",
    )
    assert p.id == "abc"
    assert p.applied_by == "VALIDATION"


def test_learning_state_default_empty():
    s = LearningState()
    assert s.version == 1
    assert s.current_regime == Regime.RANGING
    assert s.symbol_stats_by_regime == {}
    assert s.current_params == {}
    assert s.pending_approvals == []

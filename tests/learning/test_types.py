import json
from dataclasses import asdict

import pytest
from bot.learning.types import (
    Regime,
    SymbolStats,
    SymbolParams,
    ProposedAdjustment,
    LearningState,
)


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
    from bot.learning.types import ProposalStatus
    p = ProposedAdjustment(
        id="abc",
        type="leverage_change",
        param_path="leverage",
        from_value=5.0,
        to_value=4.0,
        reason="VIX high",
        confidence_score=0.8,
        proposed_at="2026-05-08T22:00:00Z",
        applied_by=ProposalStatus.VALIDATION,
    )
    assert p.id == "abc"
    assert p.applied_by == ProposalStatus.VALIDATION


def test_learning_state_default_empty():
    s = LearningState()
    assert s.version == 1
    assert s.current_regime == Regime.RANGING
    assert s.symbol_stats_by_regime == {}
    assert s.current_params == {}
    assert s.pending_approvals == []


def test_learning_state_json_roundtrip():
    """Vérifie que LearningState peut être sérialisé en JSON et reconstruit."""
    import json
    from dataclasses import asdict
    s = LearningState(current_regime=Regime.TREND_UP)
    s.symbol_stats_by_regime["AAPL"] = {"TREND_UP": SymbolStats(trades=10, wins=6, losses=4)}
    s.current_params["AAPL"] = SymbolParams(confidence_min=0.58)
    out = json.dumps(asdict(s))
    parsed = json.loads(out)
    assert parsed["current_regime"] == "TREND_UP"
    assert parsed["symbol_stats_by_regime"]["AAPL"]["TREND_UP"]["wins"] == 6
    assert parsed["current_params"]["AAPL"]["confidence_min"] == 0.58

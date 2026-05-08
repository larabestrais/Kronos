import pytest
from bot.learning.types import (
    LearningState, Regime, SymbolStats, SymbolParams,
    ProposedAdjustment, ProposalStatus,
)
from bot.learning.engine import AdaptationEngine


@pytest.fixture
def fresh_state():
    state = LearningState()
    state.current_regime = Regime.TREND_UP
    state.current_params = {
        "AAPL": SymbolParams(confidence_min=0.60, buy_threshold=0.01),
        "MSFT": SymbolParams(confidence_min=0.60, buy_threshold=0.01),
    }
    return state


def test_high_winrate_triggers_confidence_decrease(fresh_state):
    fresh_state.symbol_stats_by_regime["AAPL"] = {
        "TREND_UP": SymbolStats(trades=20, wins=14, losses=6, expectancy=0.018)
    }
    engine = AdaptationEngine(fresh_state)
    proposals = engine.propose_adjustments()

    auto = [p for p in proposals if p.applied_by == ProposalStatus.AUTO]
    aapl_conf = [p for p in auto if "AAPL.confidence_min" in p.param_path]
    assert len(aapl_conf) == 1
    assert aapl_conf[0].to_value < 0.60  # baissé
    assert aapl_conf[0].to_value >= 0.50  # clampé


def test_low_winrate_triggers_confidence_increase(fresh_state):
    fresh_state.symbol_stats_by_regime["AAPL"] = {
        "TREND_UP": SymbolStats(trades=15, wins=4, losses=11, expectancy=-0.012)
    }
    engine = AdaptationEngine(fresh_state)
    proposals = engine.propose_adjustments()

    aapl_conf = [p for p in proposals if "AAPL.confidence_min" in p.param_path]
    assert len(aapl_conf) == 1
    assert aapl_conf[0].to_value > 0.60  # augmenté


def test_insufficient_trades_no_adjustment(fresh_state):
    fresh_state.symbol_stats_by_regime["AAPL"] = {
        "TREND_UP": SymbolStats(trades=5, wins=4, losses=1, expectancy=0.02)
    }
    engine = AdaptationEngine(fresh_state)
    proposals = engine.propose_adjustments()

    aapl = [p for p in proposals if "AAPL" in p.param_path]
    assert len(aapl) == 0  # pas assez de trades


def test_drawdown_high_proposes_leverage_reduction(fresh_state):
    fresh_state.global_leverage = 5.0
    engine = AdaptationEngine(fresh_state)
    proposals = engine.propose_adjustments(
        recent_drawdown_pct=0.06, recent_avg_vix=23.0
    )

    leverage = [p for p in proposals if p.type == "leverage_change"]
    assert len(leverage) == 1
    assert leverage[0].to_value < 5.0
    assert leverage[0].applied_by == ProposalStatus.VALIDATION


def test_clamp_respected_on_extreme_winrate(fresh_state):
    """Win rate de 100% → on baisse confidence_min mais pas en dessous de 0.50."""
    fresh_state.current_params["AAPL"] = SymbolParams(confidence_min=0.55)
    fresh_state.symbol_stats_by_regime["AAPL"] = {
        "TREND_UP": SymbolStats(trades=30, wins=30, losses=0, expectancy=0.05)
    }
    engine = AdaptationEngine(fresh_state)
    proposals = engine.propose_adjustments()

    aapl_conf = [p for p in proposals if "AAPL.confidence_min" in p.param_path]
    if aapl_conf:
        assert aapl_conf[0].to_value >= 0.50


def test_apply_auto_proposals_updates_state(fresh_state):
    fresh_state.symbol_stats_by_regime["AAPL"] = {
        "TREND_UP": SymbolStats(trades=20, wins=14, losses=6, expectancy=0.02)
    }
    engine = AdaptationEngine(fresh_state)
    proposals = engine.propose_adjustments()
    engine.apply_auto(proposals)

    # AAPL.confidence_min doit avoir été mis à jour
    assert fresh_state.current_params["AAPL"].confidence_min < 0.60


def test_apply_auto_does_not_apply_validation(fresh_state):
    engine = AdaptationEngine(fresh_state)
    proposals = engine.propose_adjustments(
        recent_drawdown_pct=0.06, recent_avg_vix=23.0
    )
    engine.apply_auto(proposals)

    # leverage ne doit pas avoir bougé (c'est VALIDATION, pas AUTO)
    assert fresh_state.global_leverage == 5.0
    # mais doit être dans pending_approvals
    assert any(p.type == "leverage_change" for p in fresh_state.pending_approvals)


def test_dry_run_does_not_apply_anything(fresh_state):
    fresh_state.symbol_stats_by_regime["AAPL"] = {
        "TREND_UP": SymbolStats(trades=20, wins=14, losses=6, expectancy=0.02)
    }
    engine = AdaptationEngine(fresh_state, dry_run=True)
    proposals = engine.propose_adjustments()
    engine.apply_auto(proposals)

    # Dry run : aucun changement appliqué
    assert fresh_state.current_params["AAPL"].confidence_min == 0.60
    assert len(fresh_state.pending_approvals) == 0


def test_negative_expectancy_proposes_weight_decrease(fresh_state):
    """Expectancy négative persistante → réduction du poids du symbole."""
    fresh_state.symbol_stats_by_regime["AAPL"] = {
        "TREND_UP": SymbolStats(trades=25, wins=10, losses=15, expectancy=-0.015)
    }
    engine = AdaptationEngine(fresh_state)
    proposals = engine.propose_adjustments()

    weight_changes = [p for p in proposals if p.type == "weight_change" and "AAPL" in p.param_path]
    assert len(weight_changes) == 1
    assert weight_changes[0].to_value < fresh_state.current_params["AAPL"].weight

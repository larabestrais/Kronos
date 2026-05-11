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


from datetime import date
from bot.learning.engine import is_in_earnings_blackout, EARNINGS_BLACKOUT_DATES


def test_nvda_blackout_during_window():
    """NVDA earnings 2026-05-20 → blackout 19-21 mai."""
    assert is_in_earnings_blackout("NVDA", date(2026, 5, 19)) is True
    assert is_in_earnings_blackout("NVDA", date(2026, 5, 20)) is True
    assert is_in_earnings_blackout("NVDA", date(2026, 5, 21)) is True


def test_nvda_not_in_blackout_outside_window():
    assert is_in_earnings_blackout("NVDA", date(2026, 5, 18)) is False
    assert is_in_earnings_blackout("NVDA", date(2026, 5, 22)) is False
    assert is_in_earnings_blackout("NVDA", date(2026, 6, 1)) is False


def test_aapl_blackout_july_2026():
    """AAPL earnings 2026-07-30 → blackout 29-31 juillet."""
    assert is_in_earnings_blackout("AAPL", date(2026, 7, 29)) is True
    assert is_in_earnings_blackout("AAPL", date(2026, 7, 30)) is True
    assert is_in_earnings_blackout("AAPL", date(2026, 7, 31)) is True
    assert is_in_earnings_blackout("AAPL", date(2026, 7, 28)) is False
    assert is_in_earnings_blackout("AAPL", date(2026, 8, 1)) is False


def test_unknown_symbol_never_in_blackout():
    """Symboles non listés dans EARNINGS_BLACKOUT_DATES ne sont jamais en blackout."""
    assert is_in_earnings_blackout("XYZ", date(2026, 5, 20)) is False


def test_blackout_dict_contains_all_6_symbols():
    """Vérifie que les 6 symboles du portfolio sont dans le dict."""
    for sym in ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA", "INTC"]:
        assert sym in EARNINGS_BLACKOUT_DATES, f"Missing {sym} from blackout dict"


def test_blackout_windows_are_3_days_each():
    """Chaque fenêtre = (start, end) avec ~3 jours = veille + jour J + lendemain."""
    for sym, (start, end) in EARNINGS_BLACKOUT_DATES.items():
        assert isinstance(start, date), f"{sym} start not a date"
        assert isinstance(end, date), f"{sym} end not a date"
        delta = (end - start).days
        assert 1 <= delta <= 3, f"{sym} window too wide: {delta} days"

import pytest
from bot.learning.types import LearningState, Regime, SymbolStats
from bot.learning.tracker import PerformanceTracker


def make_trade(symbol="AAPL", pnl=0.0):
    """Mock minimal trade object."""
    class T:
        def __init__(self):
            self.symbol = symbol
            self.pnl = pnl
    return T()


def test_record_first_trade_creates_entry():
    state = LearningState()
    tracker = PerformanceTracker(state)
    tracker.record_closed_trade(make_trade("AAPL", pnl=2.5), regime=Regime.TREND_UP)

    stats = state.symbol_stats_by_regime["AAPL"]["TREND_UP"]
    assert stats.trades == 1
    assert stats.wins == 1
    assert stats.losses == 0


def test_record_loss():
    state = LearningState()
    tracker = PerformanceTracker(state)
    tracker.record_closed_trade(make_trade("AAPL", pnl=-1.5), regime=Regime.TREND_UP)

    stats = state.symbol_stats_by_regime["AAPL"]["TREND_UP"]
    assert stats.wins == 0
    assert stats.losses == 1


def test_aggregates_multiple_trades():
    state = LearningState()
    tracker = PerformanceTracker(state)
    for pnl in [+2.0, +1.5, -0.8, +3.0, -1.2]:
        tracker.record_closed_trade(make_trade("AAPL", pnl), regime=Regime.TREND_UP)

    stats = state.symbol_stats_by_regime["AAPL"]["TREND_UP"]
    assert stats.trades == 5
    assert stats.wins == 3
    assert stats.losses == 2
    assert stats.win_rate == 0.6


def test_separate_stats_per_regime():
    state = LearningState()
    tracker = PerformanceTracker(state)
    tracker.record_closed_trade(make_trade("AAPL", pnl=+2.0), regime=Regime.TREND_UP)
    tracker.record_closed_trade(make_trade("AAPL", pnl=-1.0), regime=Regime.HIGH_VOLATILITY)

    assert state.symbol_stats_by_regime["AAPL"]["TREND_UP"].trades == 1
    assert state.symbol_stats_by_regime["AAPL"]["HIGH_VOLATILITY"].trades == 1
    assert state.symbol_stats_by_regime["AAPL"]["TREND_UP"].wins == 1
    assert state.symbol_stats_by_regime["AAPL"]["HIGH_VOLATILITY"].losses == 1


def test_separate_stats_per_symbol():
    state = LearningState()
    tracker = PerformanceTracker(state)
    tracker.record_closed_trade(make_trade("AAPL", +2.0), regime=Regime.TREND_UP)
    tracker.record_closed_trade(make_trade("MSFT", -1.0), regime=Regime.TREND_UP)

    assert state.symbol_stats_by_regime["AAPL"]["TREND_UP"].wins == 1
    assert state.symbol_stats_by_regime["MSFT"]["TREND_UP"].losses == 1


def test_expectancy_updates_correctly():
    state = LearningState()
    tracker = PerformanceTracker(state)
    # 3 wins +2, 2 losses -1 → expectancy = (3*2 - 2*1) / 5 = 0.8
    for pnl in [+2.0, +2.0, +2.0, -1.0, -1.0]:
        tracker.record_closed_trade(make_trade("AAPL", pnl), regime=Regime.TREND_UP)

    stats = state.symbol_stats_by_regime["AAPL"]["TREND_UP"]
    assert abs(stats.expectancy - 0.8) < 0.01

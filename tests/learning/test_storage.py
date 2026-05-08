import json
import pytest
from pathlib import Path

from bot.learning.types import (
    LearningState, Regime, SymbolStats, SymbolParams,
    ProposedAdjustment, ProposalStatus,
)
from bot.learning.storage import LearningStateStore


@pytest.fixture
def store(tmp_path):
    return LearningStateStore(save_path=str(tmp_path / "learning_state.json"))


def test_load_returns_default_when_file_missing(store):
    state = store.load()
    assert state.version == 1
    assert state.current_regime == Regime.RANGING
    assert state.symbol_stats_by_regime == {}


def test_save_and_load_roundtrip(store):
    state = LearningState()
    state.current_regime = Regime.TREND_UP
    state.symbol_stats_by_regime = {
        "AAPL": {"TREND_UP": SymbolStats(trades=10, wins=7, losses=3, expectancy=0.018)}
    }
    state.current_params = {"AAPL": SymbolParams(confidence_min=0.58)}
    store.save(state)

    loaded = store.load()
    assert loaded.current_regime == Regime.TREND_UP
    assert loaded.symbol_stats_by_regime["AAPL"]["TREND_UP"].trades == 10
    assert loaded.symbol_stats_by_regime["AAPL"]["TREND_UP"].win_rate == 0.7
    assert loaded.current_params["AAPL"].confidence_min == 0.58


def test_save_is_atomic(store, tmp_path):
    """write-then-rename : pas de fichier .tmp résiduel après un save réussi."""
    state = LearningState()
    store.save(state)
    assert (tmp_path / "learning_state.json").exists()
    assert not (tmp_path / "learning_state.json.tmp").exists()


def test_load_corrupted_file_returns_default(store, tmp_path):
    """Si le fichier est corrompu, on retourne un état par défaut + log."""
    (tmp_path / "learning_state.json").write_text("{this is not valid json}")
    state = store.load()
    assert state.version == 1
    assert state.symbol_stats_by_regime == {}


def test_schema_version_mismatch_returns_default(store, tmp_path):
    """Si le schéma est plus récent que ce qu'on supporte, fallback default."""
    (tmp_path / "learning_state.json").write_text(json.dumps({"version": 999}))
    state = store.load()
    assert state.version == 1


def test_save_truncates_param_history_to_1000(store):
    state = LearningState()
    for i in range(1500):
        state.param_history.append(ProposedAdjustment(
            id=f"id-{i}", type="x", param_path="y", from_value=0, to_value=0,
            reason="test", confidence_score=0.5, proposed_at="2026-01-01T00:00:00Z",
            applied_by=ProposalStatus.AUTO,
        ))
    store.save(state)
    loaded = store.load()
    assert len(loaded.param_history) == 1000


def test_load_converts_enum_strings_back_to_enums(store, tmp_path):
    """Les strings JSON pour applied_by/regime_at_time doivent redevenir des enums."""
    state = LearningState()
    state.param_history.append(ProposedAdjustment(
        id="test-1", type="confidence_min_change",
        param_path="current_params.AAPL.confidence_min",
        from_value=0.60, to_value=0.58, reason="test",
        confidence_score=0.7, proposed_at="2026-05-08T22:00:00Z",
        applied_by=ProposalStatus.AUTO, regime_at_time=Regime.TREND_UP,
    ))
    store.save(state)
    loaded = store.load()
    p = loaded.param_history[0]
    assert isinstance(p.applied_by, ProposalStatus)
    assert p.applied_by == ProposalStatus.AUTO
    assert isinstance(p.regime_at_time, Regime)
    assert p.regime_at_time == Regime.TREND_UP

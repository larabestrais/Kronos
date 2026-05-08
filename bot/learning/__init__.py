"""
Module d'apprentissage adaptatif pour le bot Kronos.
Voir docs/superpowers/specs/2026-05-08-kronos-adaptive-learning-design.md
"""
from .types import (
    Regime,
    ProposalStatus,
    SymbolStats,
    SymbolParams,
    ProposedAdjustment,
    RejectedProposal,
    LearningState,
)
from .bounds import (
    clamp,
    is_within_daily_change_cap,
    CONFIDENCE_MIN_BOUNDS,
    BUY_THRESHOLD_BOUNDS,
    SELL_THRESHOLD_BOUNDS,
    WEIGHT_BOUNDS,
    DEFENSIVE_REDUCTION_BOUNDS,
    MAX_DAILY_CHANGE_PCT,
)
from .storage import LearningStateStore
from .regime import RegimeDetector
from .tracker import PerformanceTracker
from .engine import AdaptationEngine

__all__ = [
    "Regime",
    "ProposalStatus",
    "SymbolStats",
    "SymbolParams",
    "ProposedAdjustment",
    "RejectedProposal",
    "LearningState",
    "clamp",
    "is_within_daily_change_cap",
    "CONFIDENCE_MIN_BOUNDS",
    "BUY_THRESHOLD_BOUNDS",
    "SELL_THRESHOLD_BOUNDS",
    "WEIGHT_BOUNDS",
    "DEFENSIVE_REDUCTION_BOUNDS",
    "MAX_DAILY_CHANGE_PCT",
    "LearningStateStore",
    "RegimeDetector",
    "PerformanceTracker",
    "AdaptationEngine",
]

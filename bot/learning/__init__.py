"""
Module d'apprentissage adaptatif pour le bot Kronos.
Voir docs/superpowers/specs/2026-05-08-kronos-adaptive-learning-design.md
"""
from .types import (
    Regime,
    SymbolStats,
    SymbolParams,
    ProposedAdjustment,
    RejectedProposal,
    LearningState,
)

__all__ = [
    "Regime",
    "SymbolStats",
    "SymbolParams",
    "ProposedAdjustment",
    "RejectedProposal",
    "LearningState",
]

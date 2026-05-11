"""
Dataclasses pour l'état d'apprentissage du bot Kronos.
Tous les types sont sérialisables en JSON via dataclasses.asdict().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Regime(str, Enum):
    """4 régimes de marché détectés par le RegimeDetector."""
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"


class ProposalStatus(str, Enum):
    """Statut d'application d'une proposition d'ajustement."""
    AUTO = "AUTO"
    VALIDATION = "VALIDATION"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass
class SymbolStats:
    """Statistiques d'un symbole dans un régime donné."""
    trades: int = 0
    wins: int = 0
    losses: int = 0
    expectancy: float = 0.0  # moyenne pondérée des gains/pertes
    pnl_30d: float = 0.0     # PnL cumulé sur 30 jours

    @property
    def win_rate(self) -> float:
        if self.trades == 0:
            return 0.0
        return self.wins / self.trades


@dataclass
class SymbolParams:
    """Paramètres adaptatifs courants d'un symbole."""
    confidence_min: float = 0.60
    buy_threshold: float = 0.01
    sell_threshold: float = -0.01
    weight: float = 1.0  # poids d'allocation, normalisé par le RiskManager


@dataclass
class ProposedAdjustment:
    """
    Une proposition d'ajustement.
    Peut être AUTO (déjà appliquée) ou VALIDATION (en attente d'approbation).
    """
    id: str
    type: str            # ex: "confidence_min_change", "leverage_change", "skip_hour"
    param_path: str      # ex: "current_params.AAPL.confidence_min"
    from_value: float | int | bool
    to_value: float | int | bool
    reason: str
    confidence_score: float  # 0-1, la confiance dans la proposition
    proposed_at: str         # ISO 8601 UTC
    applied_by: ProposalStatus
    regime_at_time: Optional[Regime] = None
    expires_at: Optional[str] = None


@dataclass
class RejectedProposal:
    """Trace d'une proposition rejetée pour appliquer un cooldown."""
    proposal_hash: str       # hash type+param_path+to_value
    rejected_at: str
    cooldown_until: str


@dataclass
class LearningState:
    """État complet du module d'apprentissage. Sérialisé en JSON."""
    version: int = 1
    last_update: str = ""
    current_regime: Regime = Regime.RANGING
    regime_stable_since: str = ""
    warmup_completed_at: Optional[str] = None  # None = warmup encore en cours

    # Stats par symbole et par régime
    symbol_stats_by_regime: dict[str, dict[str, SymbolStats]] = field(default_factory=dict)

    # Paramètres courants (modifiables par AdaptationEngine)
    current_params: dict[str, SymbolParams] = field(default_factory=dict)

    # Heures à éviter par symbole, format "HH:MM-HH:MM"
    skip_hours_by_symbol: dict[str, list[str]] = field(default_factory=dict)

    # Historique des ajustements appliqués (rolling, max 1000 entrées)
    param_history: list[ProposedAdjustment] = field(default_factory=list)

    # Propositions en attente de validation utilisateur
    pending_approvals: list[ProposedAdjustment] = field(default_factory=list)

    # Propositions rejetées (cooldown)
    rejected_proposals: list[RejectedProposal] = field(default_factory=list)

    # Niveaux globaux (modifiables par VALIDATION)
    global_leverage: float = 5.0
    global_stop_loss_pct: float = 0.03
    global_take_profit_pct: float = 0.06
    defensive_mode: bool = False  # si True, positions max ÷2

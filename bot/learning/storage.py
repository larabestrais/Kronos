"""
Persistance atomique de l'état d'apprentissage.
Utilise write-then-rename pour éviter la corruption en cas de crash.
"""

import json
import logging
import os
from dataclasses import asdict
from pathlib import Path

from .types import (
    LearningState,
    Regime,
    SymbolStats,
    SymbolParams,
    ProposedAdjustment,
    ProposalStatus,
    RejectedProposal,
)

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 1
MAX_HISTORY_ENTRIES = 1000


class LearningStateStore:
    """Lit/écrit `learning_state.json` de façon atomique."""

    def __init__(self, save_path: str = "learning_state.json"):
        self.save_path = Path(save_path)
        self.save_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> LearningState:
        """Charge l'état. Retourne un état par défaut si fichier manquant ou corrompu."""
        if not self.save_path.exists():
            logger.info("[Learning] Pas de state file, démarrage à vide")
            return LearningState()

        try:
            data = json.loads(self.save_path.read_text())
        except json.JSONDecodeError as e:
            logger.error(f"[Learning] State file corrompu, retour à vide: {e}")
            return LearningState()

        version = data.get("version", 0)
        if version > CURRENT_SCHEMA_VERSION:
            logger.warning(
                f"[Learning] Schema version {version} non supportée "
                f"(max {CURRENT_SCHEMA_VERSION}), retour à vide"
            )
            return LearningState()

        return self._deserialize(data)

    def save(self, state: LearningState) -> None:
        """Sauvegarde atomique : écrit dans .tmp puis rename."""
        # Truncate history
        if len(state.param_history) > MAX_HISTORY_ENTRIES:
            state.param_history = state.param_history[-MAX_HISTORY_ENTRIES:]

        state.version = CURRENT_SCHEMA_VERSION
        data = self._serialize(state)

        tmp_path = self.save_path.with_suffix(self.save_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, indent=2))
        os.replace(str(tmp_path), str(self.save_path))

    @staticmethod
    def _serialize(state: LearningState) -> dict:
        """Convertit LearningState en dict JSON-friendly."""
        return {
            "version": state.version,
            "last_update": state.last_update,
            "current_regime": state.current_regime.value,
            "regime_stable_since": state.regime_stable_since,
            "warmup_completed_at": state.warmup_completed_at,
            "symbol_stats_by_regime": {
                sym: {regime: asdict(stats) for regime, stats in by_regime.items()}
                for sym, by_regime in state.symbol_stats_by_regime.items()
            },
            "current_params": {
                sym: asdict(params) for sym, params in state.current_params.items()
            },
            "skip_hours_by_symbol": state.skip_hours_by_symbol,
            "param_history": [_adjustment_to_dict(p) for p in state.param_history],
            "pending_approvals": [_adjustment_to_dict(p) for p in state.pending_approvals],
            "rejected_proposals": [asdict(r) for r in state.rejected_proposals],
            "global_leverage": state.global_leverage,
            "global_stop_loss_pct": state.global_stop_loss_pct,
            "global_take_profit_pct": state.global_take_profit_pct,
            "defensive_mode": state.defensive_mode,
        }

    @staticmethod
    def _deserialize(data: dict) -> LearningState:
        """Convertit un dict JSON en LearningState."""
        state = LearningState()
        state.version = data.get("version", 1)
        state.last_update = data.get("last_update", "")
        state.current_regime = Regime(data.get("current_regime", "RANGING"))
        state.regime_stable_since = data.get("regime_stable_since", "")
        state.warmup_completed_at = data.get("warmup_completed_at")

        state.symbol_stats_by_regime = {
            sym: {
                regime: SymbolStats(**stats_dict)
                for regime, stats_dict in by_regime.items()
            }
            for sym, by_regime in data.get("symbol_stats_by_regime", {}).items()
        }

        state.current_params = {
            sym: SymbolParams(**params_dict)
            for sym, params_dict in data.get("current_params", {}).items()
        }

        state.skip_hours_by_symbol = data.get("skip_hours_by_symbol", {})
        state.param_history = [
            _dict_to_adjustment(p) for p in data.get("param_history", [])
        ]
        state.pending_approvals = [
            _dict_to_adjustment(p) for p in data.get("pending_approvals", [])
        ]
        state.rejected_proposals = [
            RejectedProposal(**r) for r in data.get("rejected_proposals", [])
        ]
        state.global_leverage = data.get("global_leverage", 5.0)
        state.global_stop_loss_pct = data.get("global_stop_loss_pct", 0.03)
        state.global_take_profit_pct = data.get("global_take_profit_pct", 0.06)
        state.defensive_mode = data.get("defensive_mode", False)
        return state


def _adjustment_to_dict(p: ProposedAdjustment) -> dict:
    """Sérialise un ProposedAdjustment, convertissant les enums en string."""
    d = asdict(p)
    # asdict() handles str-Enum natively (renvoie la string), mais on est explicit
    if hasattr(p.applied_by, "value"):
        d["applied_by"] = p.applied_by.value
    if p.regime_at_time is not None and hasattr(p.regime_at_time, "value"):
        d["regime_at_time"] = p.regime_at_time.value
    return d


def _dict_to_adjustment(d: dict) -> ProposedAdjustment:
    """Désérialise, convertit les strings en enums."""
    data = dict(d)  # copy pour ne pas muter l'input
    if isinstance(data.get("applied_by"), str):
        data["applied_by"] = ProposalStatus(data["applied_by"])
    rt = data.get("regime_at_time")
    if isinstance(rt, str) and rt:
        data["regime_at_time"] = Regime(rt)
    return ProposedAdjustment(**data)

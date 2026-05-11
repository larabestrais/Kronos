"""
AdaptationEngine — applique les règles d'ajustement.

Sépare les propositions en :
  - AUTO   : appliquées immédiatement (ajustements mineurs avec clamp)
  - VALIDATION : ajoutées à pending_approvals, attendent un OK utilisateur

Toutes les propositions appliquées sont également loguées dans param_history.
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from .bounds import (
    CONFIDENCE_MIN_BOUNDS,
    BUY_THRESHOLD_BOUNDS,
    WEIGHT_BOUNDS,
    MAX_DAILY_CHANGE_PCT,
    clamp,
    is_within_daily_change_cap,
)
from .types import (
    LearningState,
    ProposedAdjustment,
    ProposalStatus,
    Regime,
    SymbolParams,
)

logger = logging.getLogger(__name__)


from datetime import date as _date


# === Earnings Blackout ===
# Date des earnings des symboles + 1 jour de marge de chaque côté.
# Source : briefing marché du 2026-05-11 (WebSearch MarketBeat / TipRanks / Wallstreet Horizon).
# Le bot s'abstient de toute nouvelle position sur ces symboles pendant la fenêtre.
# À mettre à jour quand les dates des prochains trimestres sont confirmées.
EARNINGS_BLACKOUT_DATES: dict[str, tuple[_date, _date]] = {
    "NVDA":  (_date(2026, 5, 19), _date(2026, 5, 21)),   # Q1 FY27 — confirmé 20/05
    "INTC":  (_date(2026, 7, 22), _date(2026, 7, 24)),   # Q2 2026 — projection 23/07
    "GOOGL": (_date(2026, 7, 27), _date(2026, 7, 29)),   # Q2 2026 — confirmé 28/07
    "MSFT":  (_date(2026, 7, 27), _date(2026, 7, 30)),   # Q4 FY26 — confirmé 28-29/07
    "TSLA":  (_date(2026, 7, 28), _date(2026, 7, 30)),   # Q2 2026 — projection 29/07
    "AAPL":  (_date(2026, 7, 29), _date(2026, 7, 31)),   # Q3 FY26 — forecast 30/07
}


def is_in_earnings_blackout(symbol: str, today: _date | None = None) -> bool:
    """
    Retourne True si le symbole est dans sa fenêtre de blackout earnings aujourd'hui.
    Le bot doit alors s'abstenir d'ouvrir ou de modifier une position sur ce symbole.

    `today` paramétrable pour les tests ; sinon utilise la date du jour (UTC).
    """
    if today is None:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date()

    window = EARNINGS_BLACKOUT_DATES.get(symbol)
    if window is None:
        return False

    start, end = window
    return start <= today <= end


# Seuils des règles
MIN_TRADES_FOR_ADJUSTMENT = 10
MIN_TRADES_FOR_WEIGHT_ADJUSTMENT = 20
HIGH_WINRATE = 0.60
LOW_WINRATE = 0.40
NEGATIVE_EXPECTANCY_THRESHOLD = -0.005  # -0.5% par trade
HIGH_DRAWDOWN_FOR_LEVERAGE = 0.05  # 5%
HIGH_VIX_FOR_LEVERAGE = 22.0


class AdaptationEngine:

    def __init__(self, state: LearningState, dry_run: bool = False):
        self.state = state
        self.dry_run = dry_run

    def propose_adjustments(
        self,
        recent_drawdown_pct: float = 0.0,
        recent_avg_vix: float = 15.0,
    ) -> list[ProposedAdjustment]:
        """Retourne la liste de toutes les propositions calculées."""
        proposals: list[ProposedAdjustment] = []
        regime = self.state.current_regime

        # 1. Per-symbol rules basées sur stats du régime courant
        for symbol, by_regime in self.state.symbol_stats_by_regime.items():
            stats = by_regime.get(regime.value)
            if stats is None or stats.trades < MIN_TRADES_FOR_ADJUSTMENT:
                continue

            params = self.state.current_params.get(symbol, SymbolParams())

            # Règle 1 : win rate élevé → baisser confidence_min
            if stats.win_rate >= HIGH_WINRATE:
                proposals.append(self._make_confidence_change(
                    symbol, params.confidence_min, params.confidence_min * 0.92,
                    f"win rate {stats.win_rate:.0%} sur {stats.trades} trades en {regime.value}"
                ))

            # Règle 2 : win rate faible → augmenter confidence_min
            elif stats.win_rate <= LOW_WINRATE:
                proposals.append(self._make_confidence_change(
                    symbol, params.confidence_min, params.confidence_min * 1.10,
                    f"win rate {stats.win_rate:.0%} sur {stats.trades} trades en {regime.value}"
                ))

            # Règle 3 : expectancy négative persistante → réduire poids
            if stats.expectancy < NEGATIVE_EXPECTANCY_THRESHOLD and stats.trades >= MIN_TRADES_FOR_WEIGHT_ADJUSTMENT:
                proposals.append(self._make_weight_change(
                    symbol, params.weight, params.weight * 0.75,
                    f"expectancy {stats.expectancy:+.3f} sur {stats.trades} trades"
                ))

        # 2. Global rules (VALIDATION)
        if recent_drawdown_pct > HIGH_DRAWDOWN_FOR_LEVERAGE and recent_avg_vix > HIGH_VIX_FOR_LEVERAGE:
            new_leverage = max(1.0, self.state.global_leverage * 0.8)
            proposals.append(ProposedAdjustment(
                id=str(uuid.uuid4())[:8],
                type="leverage_change",
                param_path="global_leverage",
                from_value=self.state.global_leverage,
                to_value=new_leverage,
                reason=f"drawdown {recent_drawdown_pct:.1%} + VIX moyen {recent_avg_vix:.1f}",
                confidence_score=0.78,
                proposed_at=_now_iso(),
                applied_by=ProposalStatus.VALIDATION,
                regime_at_time=regime,
            ))

        return proposals

    def apply_auto(self, proposals: list[ProposedAdjustment]) -> None:
        """Applique les propositions AUTO. Met les VALIDATION dans pending_approvals."""
        if self.dry_run:
            logger.info(f"[Learning][Engine] DRY RUN — {len(proposals)} propositions, aucune appliquée")
            return

        for p in proposals:
            if p.applied_by == ProposalStatus.AUTO:
                self._apply_to_state(p)
                self.state.param_history.append(p)
                logger.info(
                    f"[Learning][Engine] AUTO appliqué : {p.param_path} "
                    f"{p.from_value} → {p.to_value} ({p.reason})"
                )
            elif p.applied_by == ProposalStatus.VALIDATION:
                # Filtrer les rejets en cooldown
                if self._is_in_cooldown(p):
                    logger.info(f"[Learning][Engine] Skip {p.id} : cooldown actif")
                    continue
                self.state.pending_approvals.append(p)
                logger.info(f"[Learning][Engine] VALIDATION en attente : {p.id} {p.reason}")

    # --- Helpers ---

    def _make_confidence_change(
        self, symbol: str, from_v: float, to_v: float, reason: str
    ) -> ProposedAdjustment:
        clamped = clamp(to_v, *CONFIDENCE_MIN_BOUNDS)
        # Si le mouvement violerait le cap quotidien, on le réduit
        if not is_within_daily_change_cap(from_v, clamped):
            sign = 1 if clamped > from_v else -1
            clamped = from_v * (1 + sign * MAX_DAILY_CHANGE_PCT)
            clamped = clamp(clamped, *CONFIDENCE_MIN_BOUNDS)

        return ProposedAdjustment(
            id=str(uuid.uuid4())[:8],
            type="confidence_min_change",
            param_path=f"current_params.{symbol}.confidence_min",
            from_value=from_v,
            to_value=round(clamped, 4),
            reason=reason,
            confidence_score=0.70,
            proposed_at=_now_iso(),
            applied_by=ProposalStatus.AUTO,
            regime_at_time=self.state.current_regime,
        )

    def _make_weight_change(
        self, symbol: str, from_v: float, to_v: float, reason: str
    ) -> ProposedAdjustment:
        clamped = clamp(to_v, *WEIGHT_BOUNDS)
        if not is_within_daily_change_cap(from_v, clamped):
            sign = 1 if clamped > from_v else -1
            clamped = from_v * (1 + sign * MAX_DAILY_CHANGE_PCT)
            clamped = clamp(clamped, *WEIGHT_BOUNDS)

        return ProposedAdjustment(
            id=str(uuid.uuid4())[:8],
            type="weight_change",
            param_path=f"current_params.{symbol}.weight",
            from_value=from_v,
            to_value=round(clamped, 4),
            reason=reason,
            confidence_score=0.65,
            proposed_at=_now_iso(),
            applied_by=ProposalStatus.AUTO,
            regime_at_time=self.state.current_regime,
        )

    def _apply_to_state(self, p: ProposedAdjustment) -> None:
        """Applique un changement effectif au state."""
        parts = p.param_path.split(".")
        if parts[0] == "current_params" and len(parts) == 3:
            symbol, attr = parts[1], parts[2]
            if symbol not in self.state.current_params:
                self.state.current_params[symbol] = SymbolParams()
            setattr(self.state.current_params[symbol], attr, p.to_value)
        elif parts[0] == "global_leverage":
            self.state.global_leverage = p.to_value
        elif parts[0] == "global_stop_loss_pct":
            self.state.global_stop_loss_pct = p.to_value
        elif parts[0] == "global_take_profit_pct":
            self.state.global_take_profit_pct = p.to_value
        elif parts[0] == "defensive_mode":
            self.state.defensive_mode = bool(p.to_value)

    def _is_in_cooldown(self, p: ProposedAdjustment) -> bool:
        """Vérifie si une proposition similaire a été rejetée récemment."""
        h = self._proposal_hash(p)
        now = _now_iso()
        return any(
            r.proposal_hash == h and r.cooldown_until > now
            for r in self.state.rejected_proposals
        )

    @staticmethod
    def _proposal_hash(p: ProposedAdjustment) -> str:
        s = f"{p.type}|{p.param_path}|{round(float(p.to_value), 3)}"
        return hashlib.sha1(s.encode()).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# Kronos Adaptive Learning — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `bot/learning/` module that lets Kronos learn from past trades and adapt to market regime, with a hybrid auto/validation autonomy model and daily Telegram reports.

**Architecture:** New self-contained module branched onto the existing bot via callbacks (no behavior change when disabled). Statistical/rules-based engine (Approach 1 from the spec). Atomic JSON persistence. Daily 22h CET cycle via background thread. Telegram inline keyboards for major-change approvals. Dashboard `/learning` panel.

**Tech Stack:** Python 3.12, pandas/numpy (already used), pytest, requests (already used for Telegram), Flask (already used). No new top-level dependencies.

**Spec reference:** `docs/superpowers/specs/2026-05-08-kronos-adaptive-learning-design.md`

---

## File structure

### New files

| Path | Responsibility |
|---|---|
| `bot/learning/__init__.py` | Public exports |
| `bot/learning/types.py` | Dataclasses: `Regime`, `SymbolStats`, `ProposedAdjustment`, `LearningState` |
| `bot/learning/bounds.py` | `clamp()` helpers + per-parameter min/max constants |
| `bot/learning/storage.py` | `LearningStateStore`: atomic write-then-rename JSON IO with schema versioning |
| `bot/learning/regime.py` | `RegimeDetector`: classifies VIX+trend+ATR into 4 regimes |
| `bot/learning/tracker.py` | `PerformanceTracker`: updates per-symbol/per-regime stats on closed trades |
| `bot/learning/engine.py` | `AdaptationEngine`: applies rules → AUTO adjustments + VALIDATION proposals |
| `bot/learning/reporter.py` | `DailyReporter`: formats Telegram message + emits via notifier |
| `bot/learning/scheduler.py` | `LearningScheduler`: background thread, fires every day at 22h CET |

### Modified files

| Path | Change |
|---|---|
| `bot/__init__.py` | Add `from .learning import *` |
| `bot/config.py` | Add `learning_enabled`, `learning_dry_run` fields |
| `bot/portfolio.py` | Add `on_position_closed` callback list |
| `bot/bot.py` | Wire up learning module if enabled |
| `bot/notifier.py` | Add `send_with_inline_keyboard()` method |
| `webapp/app.py` | Add `/api/learning/state`, `/api/learning/reset`, `/api/telegram/webhook`, hook scheduler thread |
| `webapp/templates/dashboard.html` | Add "Apprentissage" tab with markup |
| `webapp/static/js/dashboard.js` | Add learning panel rendering + polling |
| `webapp/static/css/dashboard.css` | Add learning panel styles |
| `docker-compose.yml` | Add `KRONOS_LEARNING_*` env vars (default OFF) |
| `backtest.py` | Add `--with-learning` flag |

### New test files

| Path | Tests |
|---|---|
| `tests/learning/__init__.py` | (empty) |
| `tests/learning/test_types.py` | Dataclass roundtrips, defaults |
| `tests/learning/test_storage.py` | Atomic write, schema versioning, corruption recovery |
| `tests/learning/test_bounds.py` | Clamp behavior, min/max constants |
| `tests/learning/test_regime.py` | Decision tree on every regime + edge cases |
| `tests/learning/test_tracker.py` | Stats updates on closed trades, per-regime aggregation |
| `tests/learning/test_engine.py` | Each rule individually, AUTO vs VALIDATION split, daily change cap |

---

## Phase 1 — Foundation (types, storage, bounds)

### Task 1: Dataclasses for learning state

**Files:**
- Create: `bot/learning/__init__.py`
- Create: `bot/learning/types.py`
- Create: `tests/learning/__init__.py`
- Create: `tests/learning/test_types.py`

- [ ] **Step 1: Write failing test for types**

```python
# tests/learning/test_types.py
import pytest
from bot.learning.types import Regime, SymbolStats, ProposedAdjustment, LearningState


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
    p = ProposedAdjustment(
        id="abc",
        type="leverage_change",
        param_path="leverage",
        from_value=5.0,
        to_value=4.0,
        reason="VIX high",
        confidence_score=0.8,
        proposed_at="2026-05-08T22:00:00Z",
        applied_by="VALIDATION",
    )
    assert p.id == "abc"
    assert p.applied_by == "VALIDATION"


def test_learning_state_default_empty():
    s = LearningState()
    assert s.version == 1
    assert s.current_regime == Regime.RANGING
    assert s.symbol_stats_by_regime == {}
    assert s.current_params == {}
    assert s.pending_approvals == []
```

- [ ] **Step 2: Run test, verify it fails**

```bash
cd /app && python -m pytest tests/learning/test_types.py -v
```

Expected: ImportError or ModuleNotFoundError on `bot.learning.types`

- [ ] **Step 3: Implement `bot/learning/types.py`**

```python
# bot/learning/types.py
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
    from_value: float
    to_value: float
    reason: str
    confidence_score: float  # 0-1, la confiance dans la proposition
    proposed_at: str         # ISO 8601 UTC
    applied_by: str          # "AUTO" | "VALIDATION" | "REJECTED" | "EXPIRED"
    regime_at_time: Optional[str] = None
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
```

- [ ] **Step 4: Implement `bot/learning/__init__.py`**

```python
# bot/learning/__init__.py
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
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd /app && python -m pytest tests/learning/test_types.py -v
```

Expected: 6 PASSED

- [ ] **Step 6: Commit**

```bash
git add bot/learning/__init__.py bot/learning/types.py tests/learning/__init__.py tests/learning/test_types.py
git commit -m "feat(learning): add dataclasses for learning state"
```

---

### Task 2: Bounds helpers (clamping)

**Files:**
- Create: `bot/learning/bounds.py`
- Create: `tests/learning/test_bounds.py`

- [ ] **Step 1: Write failing test**

```python
# tests/learning/test_bounds.py
import pytest
from bot.learning.bounds import (
    clamp,
    CONFIDENCE_MIN_BOUNDS,
    BUY_THRESHOLD_BOUNDS,
    SELL_THRESHOLD_BOUNDS,
    WEIGHT_BOUNDS,
    MAX_DAILY_CHANGE_PCT,
    is_within_daily_change_cap,
)


def test_clamp_within_bounds():
    assert clamp(0.6, 0.5, 0.75) == 0.6


def test_clamp_below_min():
    assert clamp(0.3, 0.5, 0.75) == 0.5


def test_clamp_above_max():
    assert clamp(0.9, 0.5, 0.75) == 0.75


def test_clamp_equals_bound():
    assert clamp(0.5, 0.5, 0.75) == 0.5
    assert clamp(0.75, 0.5, 0.75) == 0.75


def test_confidence_min_bounds():
    assert CONFIDENCE_MIN_BOUNDS == (0.50, 0.75)


def test_buy_threshold_bounds():
    assert BUY_THRESHOLD_BOUNDS == (0.005, 0.02)


def test_sell_threshold_bounds():
    assert SELL_THRESHOLD_BOUNDS == (-0.02, -0.005)


def test_weight_bounds():
    assert WEIGHT_BOUNDS == (0.05, 0.30)


def test_max_daily_change_pct():
    assert MAX_DAILY_CHANGE_PCT == 0.15


def test_is_within_daily_change_cap_under():
    # 0.60 → 0.55 = -8.3% relatif, sous le cap 15%
    assert is_within_daily_change_cap(0.60, 0.55) is True


def test_is_within_daily_change_cap_over():
    # 0.60 → 0.40 = -33% relatif, au-dessus du cap 15%
    assert is_within_daily_change_cap(0.60, 0.40) is False


def test_is_within_daily_change_cap_zero_from():
    # cas spécial : si from = 0, on accepte (pas de division)
    assert is_within_daily_change_cap(0.0, 0.5) is True
```

- [ ] **Step 2: Run test, expect FAIL** (`pytest tests/learning/test_bounds.py -v`)

- [ ] **Step 3: Implement `bot/learning/bounds.py`**

```python
# bot/learning/bounds.py
"""
Bornes dures sur les paramètres adaptatifs et helpers de clamping.
Tout ajustement qui dépasserait ces bornes est silencieusement clampé.
"""

# Bornes (min, max) par paramètre
CONFIDENCE_MIN_BOUNDS = (0.50, 0.75)
BUY_THRESHOLD_BOUNDS = (0.005, 0.02)
SELL_THRESHOLD_BOUNDS = (-0.02, -0.005)
WEIGHT_BOUNDS = (0.05, 0.30)
DEFENSIVE_REDUCTION_BOUNDS = (0.0, 0.50)  # 0% à -50% de réduction

# Plafond de mouvement par cycle quotidien : aucun paramètre ne peut bouger
# de plus de 15% relatif par jour. Évite les sauts brusques.
MAX_DAILY_CHANGE_PCT = 0.15


def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp value into [lo, hi]."""
    return max(lo, min(hi, value))


def is_within_daily_change_cap(from_value: float, to_value: float) -> bool:
    """
    Vérifie qu'un changement (from → to) ne dépasse pas le cap quotidien.
    Cap = 15% relatif. Si from_value = 0, on accepte (pas de division par zéro).
    """
    if from_value == 0:
        return True
    relative_change = abs(to_value - from_value) / abs(from_value)
    return relative_change <= MAX_DAILY_CHANGE_PCT
```

- [ ] **Step 4: Run test, expect PASS** (12 passed)

- [ ] **Step 5: Commit**

```bash
git add bot/learning/bounds.py tests/learning/test_bounds.py
git commit -m "feat(learning): add safety bounds and clamp helpers"
```

---

### Task 3: Atomic JSON storage with schema versioning

**Files:**
- Create: `bot/learning/storage.py`
- Create: `tests/learning/test_storage.py`

- [ ] **Step 1: Write failing test**

```python
# tests/learning/test_storage.py
import json
import pytest
from pathlib import Path

from bot.learning.types import LearningState, Regime, SymbolStats, SymbolParams
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
    """Le fichier final ne doit jamais être en état corrompu, même
    si la sauvegarde est interrompue (write-then-rename)."""
    state = LearningState()
    store.save(state)
    # On ne peut pas vraiment simuler un crash en pytest, mais on vérifie
    # que la méthode utilise bien write-then-rename via un fichier .tmp
    assert (tmp_path / "learning_state.json").exists()
    # Pas de fichier .tmp résiduel après save réussi
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
    from bot.learning.types import ProposedAdjustment
    for i in range(1500):
        state.param_history.append(ProposedAdjustment(
            id=f"id-{i}", type="x", param_path="y", from_value=0, to_value=0,
            reason="test", confidence_score=0.5, proposed_at="2026-01-01T00:00:00Z",
            applied_by="AUTO",
        ))
    store.save(state)
    loaded = store.load()
    assert len(loaded.param_history) == 1000
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Implement `bot/learning/storage.py`**

```python
# bot/learning/storage.py
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
            logger.info(f"[Learning] Pas de state file, démarrage à vide")
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
            "param_history": [asdict(p) for p in state.param_history],
            "pending_approvals": [asdict(p) for p in state.pending_approvals],
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
            ProposedAdjustment(**p) for p in data.get("param_history", [])
        ]
        state.pending_approvals = [
            ProposedAdjustment(**p) for p in data.get("pending_approvals", [])
        ]
        state.rejected_proposals = [
            RejectedProposal(**r) for r in data.get("rejected_proposals", [])
        ]
        state.global_leverage = data.get("global_leverage", 5.0)
        state.global_stop_loss_pct = data.get("global_stop_loss_pct", 0.03)
        state.global_take_profit_pct = data.get("global_take_profit_pct", 0.06)
        state.defensive_mode = data.get("defensive_mode", False)
        return state
```

- [ ] **Step 4: Run test, expect PASS** (6 passed)

- [ ] **Step 5: Update `bot/learning/__init__.py` to export storage**

Add `from .storage import LearningStateStore` and update `__all__` to include `"LearningStateStore"`.

- [ ] **Step 6: Commit**

```bash
git add bot/learning/storage.py tests/learning/test_storage.py bot/learning/__init__.py
git commit -m "feat(learning): atomic JSON storage with schema versioning"
```

---

## Phase 2 — Detection & tracking

### Task 4: Regime detector

**Files:**
- Create: `bot/learning/regime.py`
- Create: `tests/learning/test_regime.py`

- [ ] **Step 1: Write failing test**

```python
# tests/learning/test_regime.py
import pandas as pd
import pytest

from bot.learning.types import Regime
from bot.learning.regime import RegimeDetector


def make_df(prices, length=60):
    """Helper: build DataFrame avec un prix linéaire."""
    return pd.DataFrame({
        "open": prices, "high": [p * 1.005 for p in prices],
        "low": [p * 0.995 for p in prices], "close": prices,
        "volume": [1000] * len(prices),
    })


def test_high_volatility_when_vix_high():
    detector = RegimeDetector()
    # VIX = 30, peu importe le reste
    regime = detector.classify(vix=30.0, basket_df=make_df([100] * 60), atr_ratio=0.01)
    assert regime == Regime.HIGH_VOLATILITY


def test_high_volatility_when_atr_high():
    detector = RegimeDetector()
    regime = detector.classify(vix=15.0, basket_df=make_df([100] * 60), atr_ratio=0.04)
    assert regime == Regime.HIGH_VOLATILITY


def test_trend_up_with_positive_slope():
    detector = RegimeDetector()
    # Prix qui monte de 100 → 110 sur 60 heures (~+0.17%/h, slope > 0.1%)
    prices = [100 + i * 0.17 for i in range(60)]
    regime = detector.classify(vix=15.0, basket_df=make_df(prices), atr_ratio=0.01)
    assert regime == Regime.TREND_UP


def test_trend_down_with_negative_slope():
    detector = RegimeDetector()
    prices = [100 - i * 0.17 for i in range(60)]
    regime = detector.classify(vix=15.0, basket_df=make_df(prices), atr_ratio=0.01)
    assert regime == Regime.TREND_DOWN


def test_ranging_with_flat_prices():
    detector = RegimeDetector()
    # Prix oscillant autour de 100 (slope ≈ 0)
    prices = [100 + (i % 2) * 0.01 for i in range(60)]
    regime = detector.classify(vix=15.0, basket_df=make_df(prices), atr_ratio=0.01)
    assert regime == Regime.RANGING


def test_high_volatility_priority_over_trend():
    detector = RegimeDetector()
    prices = [100 + i * 0.5 for i in range(60)]  # forte tendance haussière
    # Mais VIX = 28 (haut)
    regime = detector.classify(vix=28.0, basket_df=make_df(prices), atr_ratio=0.01)
    assert regime == Regime.HIGH_VOLATILITY


def test_compute_atr_ratio():
    detector = RegimeDetector()
    df = pd.DataFrame({
        "open": [100, 101, 102], "high": [101, 102, 103],
        "low": [99, 100, 101], "close": [100.5, 101.5, 102.5],
        "volume": [1000, 1000, 1000],
    })
    atr_ratio = detector.compute_atr_ratio(df, period=2)
    assert atr_ratio > 0
    assert atr_ratio < 0.05


def test_compute_basket_slope_positive():
    detector = RegimeDetector()
    prices = [100 + i for i in range(60)]
    slope = detector.compute_basket_slope(make_df(prices))
    assert slope > 0


def test_compute_basket_slope_negative():
    detector = RegimeDetector()
    prices = [100 - i for i in range(60)]
    slope = detector.compute_basket_slope(make_df(prices))
    assert slope < 0
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Implement `bot/learning/regime.py`**

```python
# bot/learning/regime.py
"""
RegimeDetector — classifie le régime de marché parmi 4 catégories.

Inputs : VIX (yfinance ^VIX), pente du panier des symboles, ATR ratio.
Output : un Regime enum.

Décision (priorité à HIGH_VOLATILITY) :
  - VIX > 25 OU ATR > 3% → HIGH_VOLATILITY
  - sinon : selon pente
    - pente > +0.1%/h → TREND_UP
    - pente < -0.1%/h → TREND_DOWN
    - sinon → RANGING
"""

import logging
import numpy as np
import pandas as pd

from .types import Regime

logger = logging.getLogger(__name__)

# Seuils de classification
VIX_HIGH_THRESHOLD = 25.0
ATR_HIGH_THRESHOLD = 0.03  # 3%
SLOPE_TREND_THRESHOLD = 0.001  # 0.1% par heure


class RegimeDetector:

    def classify(
        self,
        vix: float,
        basket_df: pd.DataFrame,
        atr_ratio: float,
    ) -> Regime:
        """
        Classifie le régime à partir des 3 indicateurs.
        basket_df : DataFrame OHLCV du panier moyen pondéré (60+ bougies recommandées)
        """
        # 1. Priorité : volatilité élevée
        if vix > VIX_HIGH_THRESHOLD or atr_ratio > ATR_HIGH_THRESHOLD:
            return Regime.HIGH_VOLATILITY

        # 2. Tendance via régression linéaire
        slope = self.compute_basket_slope(basket_df)
        if slope > SLOPE_TREND_THRESHOLD:
            return Regime.TREND_UP
        if slope < -SLOPE_TREND_THRESHOLD:
            return Regime.TREND_DOWN

        # 3. Sinon, ranging
        return Regime.RANGING

    @staticmethod
    def compute_basket_slope(df: pd.DataFrame, lookback: int = 50) -> float:
        """
        Pente normalisée (par rapport au prix moyen) sur les `lookback` dernières bougies.
        Retourne la variation relative par bougie (sans unité, ex: 0.001 = 0.1%/h).
        """
        if len(df) < lookback:
            lookback = len(df)
        if lookback < 2:
            return 0.0

        prices = df["close"].iloc[-lookback:].values
        x = np.arange(lookback)
        slope, _ = np.polyfit(x, prices, 1)
        mean_price = np.mean(prices)
        if mean_price == 0:
            return 0.0
        return float(slope / mean_price)

    @staticmethod
    def compute_atr_ratio(df: pd.DataFrame, period: int = 20) -> float:
        """
        Average True Range / dernier prix de clôture.
        ATR = moyenne sur `period` du true range.
        true range = max(high-low, |high-close_prev|, |low-close_prev|).
        """
        if len(df) < period + 1:
            period = max(1, len(df) - 1)

        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        tr_list = []
        for i in range(1, len(df)):
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
            tr_list.append(tr)

        if not tr_list:
            return 0.0

        atr = float(np.mean(tr_list[-period:]))
        last_close = float(close[-1])
        if last_close == 0:
            return 0.0
        return atr / last_close
```

- [ ] **Step 4: Run test, expect PASS** (9 passed)

- [ ] **Step 5: Commit**

```bash
git add bot/learning/regime.py tests/learning/test_regime.py
git commit -m "feat(learning): RegimeDetector with VIX+slope+ATR classification"
```

---

### Task 5: Performance tracker (per-symbol per-regime stats)

**Files:**
- Create: `bot/learning/tracker.py`
- Create: `tests/learning/test_tracker.py`

- [ ] **Step 1: Write failing test**

```python
# tests/learning/test_tracker.py
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
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Implement `bot/learning/tracker.py`**

```python
# bot/learning/tracker.py
"""
PerformanceTracker — met à jour les stats du LearningState à chaque trade fermé.
"""

import logging
from typing import Any

from .types import LearningState, Regime, SymbolStats

logger = logging.getLogger(__name__)


class PerformanceTracker:
    """Mute le LearningState passé en paramètre. Persistance gérée par l'appelant."""

    def __init__(self, state: LearningState):
        self.state = state

    def record_closed_trade(self, trade: Any, regime: Regime) -> None:
        """
        Enregistre un trade fermé. `trade` doit avoir au minimum :
          - .symbol (str)
          - .pnl (float)
        """
        symbol = trade.symbol
        pnl = float(trade.pnl)
        regime_key = regime.value

        # Crée les entrées si nécessaire
        if symbol not in self.state.symbol_stats_by_regime:
            self.state.symbol_stats_by_regime[symbol] = {}
        if regime_key not in self.state.symbol_stats_by_regime[symbol]:
            self.state.symbol_stats_by_regime[symbol][regime_key] = SymbolStats()

        stats = self.state.symbol_stats_by_regime[symbol][regime_key]

        # Update count
        stats.trades += 1
        if pnl > 0:
            stats.wins += 1
        elif pnl < 0:
            stats.losses += 1
        # pnl == 0 → ni win ni loss (rare)

        # Update expectancy = moyenne des pnl par trade
        # Recalcul incrémental : nouvelle moyenne = ((n-1)*ancienne + pnl) / n
        prev_total = stats.expectancy * (stats.trades - 1)
        stats.expectancy = (prev_total + pnl) / stats.trades

        # Update PnL 30j (approximation : on ajoute, le pruning >30j est fait
        # dans un cycle séparé par le scheduler)
        stats.pnl_30d += pnl

        logger.info(
            f"[Learning][Tracker] {symbol} {regime_key} pnl={pnl:+.2f} "
            f"→ trades={stats.trades} win_rate={stats.win_rate:.0%} "
            f"expectancy={stats.expectancy:+.3f}"
        )
```

- [ ] **Step 4: Run test, expect PASS** (6 passed)

- [ ] **Step 5: Commit**

```bash
git add bot/learning/tracker.py tests/learning/test_tracker.py
git commit -m "feat(learning): PerformanceTracker with per-symbol per-regime stats"
```

---

## Phase 3 — Adaptation engine

### Task 6: Rules-based adaptation engine

**Files:**
- Create: `bot/learning/engine.py`
- Create: `tests/learning/test_engine.py`

- [ ] **Step 1: Write failing test**

```python
# tests/learning/test_engine.py
import pytest
from bot.learning.types import (
    LearningState, Regime, SymbolStats, SymbolParams, ProposedAdjustment
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

    auto = [p for p in proposals if p.applied_by == "AUTO"]
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
    # Simule drawdown élevé en passant les paramètres au moteur
    proposals = engine.propose_adjustments(
        recent_drawdown_pct=0.06, recent_avg_vix=23.0
    )

    leverage = [p for p in proposals if p.type == "leverage_change"]
    assert len(leverage) == 1
    assert leverage[0].to_value < 5.0
    assert leverage[0].applied_by == "VALIDATION"


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
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Implement `bot/learning/engine.py`**

```python
# bot/learning/engine.py
"""
AdaptationEngine — applique les règles d'ajustement.

Sépare les propositions en :
  - AUTO   : appliquées immédiatement (ajustements mineurs avec clamp)
  - VALIDATION : ajoutées à pending_approvals, attendent un OK utilisateur

Toutes les propositions sont également loguées dans param_history.
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
from .types import LearningState, ProposedAdjustment, Regime, SymbolParams

logger = logging.getLogger(__name__)

# Seuils des règles
MIN_TRADES_FOR_ADJUSTMENT = 10
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
            if stats.expectancy < NEGATIVE_EXPECTANCY_THRESHOLD and stats.trades >= 20:
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
                applied_by="VALIDATION",
                regime_at_time=regime.value,
            ))

        return proposals

    def apply_auto(self, proposals: list[ProposedAdjustment]) -> None:
        """Applique les propositions AUTO. Met les VALIDATION dans pending_approvals."""
        if self.dry_run:
            logger.info(f"[Learning][Engine] DRY RUN — {len(proposals)} propositions, aucune appliquée")
            return

        for p in proposals:
            if p.applied_by == "AUTO":
                self._apply_to_state(p)
                self.state.param_history.append(p)
                logger.info(
                    f"[Learning][Engine] AUTO appliqué : {p.param_path} "
                    f"{p.from_value} → {p.to_value} ({p.reason})"
                )
            elif p.applied_by == "VALIDATION":
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
            applied_by="AUTO",
            regime_at_time=self.state.current_regime.value,
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
            applied_by="AUTO",
            regime_at_time=self.state.current_regime.value,
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
        s = f"{p.type}|{p.param_path}|{round(p.to_value, 3)}"
        return hashlib.sha1(s.encode()).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 4: Run test, expect PASS** (8 passed)

- [ ] **Step 5: Commit**

```bash
git add bot/learning/engine.py tests/learning/test_engine.py
git commit -m "feat(learning): rules-based AdaptationEngine with AUTO/VALIDATION split"
```

---

## Phase 4 — Reporter & integration

### Task 7: Telegram inline keyboards

**Files:**
- Modify: `bot/notifier.py`

- [ ] **Step 1: Add `send_with_inline_keyboard` method to `TelegramNotifier`**

Find the `send()` method in `bot/notifier.py` and add this new method right after it:

```python
    def send_with_inline_keyboard(
        self,
        message: str,
        buttons: list[list[dict]],
        silent: bool = False,
    ) -> Optional[int]:
        """
        Envoie un message avec un clavier inline.
        `buttons` : liste de rangées de boutons. Chaque bouton est un dict
                    {"text": str, "callback_data": str}.
        Retourne le message_id de Telegram (utile pour edit ultérieur), ou None.
        """
        if not self.enabled:
            return None

        with self._send_lock:
            elapsed = time.time() - self._last_send_at
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)

            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            try:
                r = requests.post(url, json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": self.parse_mode,
                    "disable_notification": silent,
                    "disable_web_page_preview": True,
                    "reply_markup": {"inline_keyboard": buttons},
                }, timeout=8)
                self._last_send_at = time.time()

                if r.status_code != 200:
                    logger.warning(f"[Telegram] HTTP {r.status_code}: {r.text[:200]}")
                    return None

                data = r.json()
                return data.get("result", {}).get("message_id")
            except Exception as e:
                logger.error(f"[Telegram] Erreur envoi clavier: {e}")
                return None

    def edit_message(self, message_id: int, new_text: str) -> bool:
        """Edit un message existant (pour confirmer une approbation)."""
        if not self.enabled or not message_id:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/editMessageText"
        try:
            r = requests.post(url, json={
                "chat_id": self.chat_id,
                "message_id": message_id,
                "text": new_text,
                "parse_mode": self.parse_mode,
            }, timeout=8)
            return r.status_code == 200
        except Exception as e:
            logger.error(f"[Telegram] Erreur edit: {e}")
            return False
```

- [ ] **Step 2: Verify import is correct**

Add `from typing import Optional` to the top imports if not already present.

- [ ] **Step 3: Quick smoke test (no automated test, manual verification)**

```bash
cd /app && python -c "
from bot.notifier import TelegramNotifier
n = TelegramNotifier('fake', 'fake')
assert n.enabled is False
assert n.send_with_inline_keyboard('test', [[{'text': 'OK', 'callback_data': 'x'}]]) is None
print('OK')
"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add bot/notifier.py
git commit -m "feat(notifier): add inline keyboard + edit message support"
```

---

### Task 8: DailyReporter (Telegram message formatting)

**Files:**
- Create: `bot/learning/reporter.py`
- Create: `tests/learning/test_reporter.py`

- [ ] **Step 1: Write failing test**

```python
# tests/learning/test_reporter.py
from bot.learning.types import (
    LearningState, Regime, SymbolStats, SymbolParams, ProposedAdjustment
)
from bot.learning.reporter import DailyReporter


def test_format_message_basic():
    state = LearningState()
    state.current_regime = Regime.TREND_UP
    state.current_params = {"AAPL": SymbolParams(confidence_min=0.58)}
    state.symbol_stats_by_regime = {
        "AAPL": {"TREND_UP": SymbolStats(trades=12, wins=8, losses=4, expectancy=0.018, pnl_30d=4.2)}
    }
    reporter = DailyReporter(state)
    msg = reporter.format_daily_message(
        trades_today=4, wins_today=3, losses_today=1, pnl_today=2.34,
        equity=200.31, sharpe_30d=1.42, win_rate_30d=0.58,
        drawdown_30d=-0.032, expectancy_30d=0.0032,
        auto_applied=[], pending=[],
    )
    assert "TREND_UP" in msg
    assert "+2.34" in msg or "2.34" in msg
    assert "1.42" in msg


def test_format_includes_auto_adjustments():
    state = LearningState()
    state.current_regime = Regime.TREND_UP
    reporter = DailyReporter(state)
    auto = [ProposedAdjustment(
        id="x", type="confidence_min_change",
        param_path="current_params.AAPL.confidence_min",
        from_value=0.60, to_value=0.58,
        reason="win rate 68%", confidence_score=0.7,
        proposed_at="2026-05-08T22:00:00Z", applied_by="AUTO",
    )]
    msg = reporter.format_daily_message(
        trades_today=0, wins_today=0, losses_today=0, pnl_today=0,
        equity=200, sharpe_30d=1.0, win_rate_30d=0.5,
        drawdown_30d=0, expectancy_30d=0,
        auto_applied=auto, pending=[],
    )
    assert "AAPL" in msg
    assert "0.60" in msg
    assert "0.58" in msg


def test_format_includes_pending_approvals():
    state = LearningState()
    state.current_regime = Regime.HIGH_VOLATILITY
    reporter = DailyReporter(state)
    pending = [ProposedAdjustment(
        id="abc", type="leverage_change", param_path="global_leverage",
        from_value=5.0, to_value=4.0,
        reason="VIX 24, drawdown -3.5%", confidence_score=0.78,
        proposed_at="2026-05-08T22:00:00Z", applied_by="VALIDATION",
    )]
    msg = reporter.format_daily_message(
        trades_today=0, wins_today=0, losses_today=0, pnl_today=0,
        equity=200, sharpe_30d=1.0, win_rate_30d=0.5,
        drawdown_30d=0, expectancy_30d=0,
        auto_applied=[], pending=pending,
    )
    assert "VALIDATION" in msg or "Validation" in msg
    assert "5.0" in msg or "5" in msg
    assert "4.0" in msg or "4" in msg


def test_callback_buttons_for_pending():
    state = LearningState()
    reporter = DailyReporter(state)
    pending = [ProposedAdjustment(
        id="abc", type="leverage_change", param_path="global_leverage",
        from_value=5.0, to_value=4.0, reason="x", confidence_score=0.8,
        proposed_at="2026-05-08T22:00:00Z", applied_by="VALIDATION",
    )]
    buttons = reporter.build_inline_keyboard(pending)
    # 1 row par proposition, 3 boutons par row
    assert len(buttons) == 1
    assert len(buttons[0]) == 3
    assert "approve" in buttons[0][0]["callback_data"]
    assert "abc" in buttons[0][0]["callback_data"]
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Implement `bot/learning/reporter.py`**

```python
# bot/learning/reporter.py
"""
DailyReporter — formate le message Telegram quotidien à 22h00.
"""

import logging
from typing import Any

from .types import LearningState, ProposedAdjustment, Regime

logger = logging.getLogger(__name__)


class DailyReporter:

    def __init__(self, state: LearningState):
        self.state = state

    def format_daily_message(
        self,
        trades_today: int,
        wins_today: int,
        losses_today: int,
        pnl_today: float,
        equity: float,
        sharpe_30d: float,
        win_rate_30d: float,
        drawdown_30d: float,
        expectancy_30d: float,
        auto_applied: list[ProposedAdjustment],
        pending: list[ProposedAdjustment],
    ) -> str:
        regime_emoji = {
            Regime.TREND_UP: "📈",
            Regime.TREND_DOWN: "📉",
            Regime.RANGING: "〰️",
            Regime.HIGH_VOLATILITY: "⚡",
        }
        emoji = regime_emoji.get(self.state.current_regime, "")

        lines = [
            "🌙 <b>KRONOS — Bilan quotidien</b>",
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "📊 <b>Performance du jour</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"{'🟢' if pnl_today >= 0 else '🔴'} {trades_today} trades ({wins_today}W / {losses_today}L)",
            f"💰 PnL : <b>{pnl_today:+.2f} €</b>",
            f"📈 Equity : <code>{equity:.2f} €</code>",
            f"🎯 Régime : {emoji} <b>{self.state.current_regime.value}</b>",
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "📈 <b>Performance 30j</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Sharpe : <b>{sharpe_30d:.2f}</b> {self._sharpe_emoji(sharpe_30d)}",
            f"Win rate : <b>{win_rate_30d:.0%}</b>",
            f"Drawdown : <b>{drawdown_30d:.1%}</b>",
            f"Expectancy : <b>{expectancy_30d:+.3f}/trade</b>",
        ]

        if auto_applied:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"🤖 <b>Ajustements auto ({len(auto_applied)})</b>")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            for p in auto_applied[:5]:  # max 5 affichés
                short_path = p.param_path.replace("current_params.", "")
                lines.append(
                    f"✓ {short_path} : <code>{p.from_value:.3f} → {p.to_value:.3f}</code>"
                )
                lines.append(f"   <i>{p.reason}</i>")

        if pending:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"🔔 <b>Validations requises ({len(pending)})</b>")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            for p in pending[:3]:
                lines.append(
                    f"⚠️ <b>{p.type.replace('_', ' ').title()}</b>"
                )
                lines.append(
                    f"   <code>{p.from_value} → {p.to_value}</code>"
                )
                lines.append(f"   <i>{p.reason}</i>")

        return "\n".join(lines)

    def build_inline_keyboard(
        self, pending: list[ProposedAdjustment]
    ) -> list[list[dict]]:
        """Construit le clavier inline avec 3 boutons par proposition."""
        keyboard = []
        for p in pending[:3]:  # max 3 propositions par message
            keyboard.append([
                {"text": f"✅ Valider", "callback_data": f"learning:approve:{p.id}"},
                {"text": f"❌ Refuser", "callback_data": f"learning:reject:{p.id}"},
                {"text": f"⏸️ Plus tard", "callback_data": f"learning:defer:{p.id}"},
            ])
        return keyboard

    @staticmethod
    def _sharpe_emoji(s: float) -> str:
        if s >= 2.0:
            return "✨"
        if s >= 1.0:
            return "👍"
        if s >= 0:
            return "🤔"
        return "💀"
```

- [ ] **Step 4: Run test, expect PASS** (4 passed)

- [ ] **Step 5: Commit**

```bash
git add bot/learning/reporter.py tests/learning/test_reporter.py
git commit -m "feat(learning): DailyReporter with Telegram formatting + inline keyboard"
```

---

### Task 9: Daily scheduler thread

**Files:**
- Create: `bot/learning/scheduler.py`

This task has no automated test (it's threading + scheduling logic — the components are tested separately). Manual verification.

- [ ] **Step 1: Implement `bot/learning/scheduler.py`**

```python
# bot/learning/scheduler.py
"""
LearningScheduler — thread de fond qui déclenche le cycle d'apprentissage
chaque jour à 22h00 (heure Bruxelles).
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

import pytz

logger = logging.getLogger(__name__)


class LearningScheduler:

    def __init__(
        self,
        callback: Callable[[], None],
        timezone: str = "Europe/Brussels",
        hour: int = 22,
        minute: int = 0,
    ):
        self.callback = callback
        self.tz = pytz.timezone(timezone)
        self.target_hour = hour
        self.target_minute = minute
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_run_date: Optional[str] = None  # "YYYY-MM-DD"

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            logger.warning("[Learning][Scheduler] déjà démarré")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="learning-scheduler"
        )
        self._thread.start()
        logger.info(
            f"[Learning][Scheduler] démarré, exécutera à {self.target_hour:02d}:"
            f"{self.target_minute:02d} ({self.tz})"
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("[Learning][Scheduler] arrêté")

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                now = datetime.now(self.tz)
                today_key = now.strftime("%Y-%m-%d")

                # On déclenche si on est à ou après l'heure cible et qu'on n'a pas déjà tourné aujourd'hui
                if (
                    now.hour > self.target_hour
                    or (now.hour == self.target_hour and now.minute >= self.target_minute)
                ) and self._last_run_date != today_key:
                    logger.info("[Learning][Scheduler] déclenchement du cycle quotidien")
                    try:
                        self.callback()
                    except Exception as e:
                        logger.exception(f"[Learning][Scheduler] erreur dans callback: {e}")
                    self._last_run_date = today_key

                # Sleep jusqu'à la prochaine vérif (toutes les 60 sec)
                self._stop_event.wait(60)
            except Exception as e:
                logger.exception(f"[Learning][Scheduler] erreur boucle: {e}")
                self._stop_event.wait(60)
```

- [ ] **Step 2: Update `bot/learning/__init__.py` to export scheduler**

Add to `__init__.py`:

```python
from .bounds import clamp, is_within_daily_change_cap
from .regime import RegimeDetector
from .tracker import PerformanceTracker
from .engine import AdaptationEngine
from .reporter import DailyReporter
from .scheduler import LearningScheduler
```

And update `__all__` accordingly.

- [ ] **Step 3: Smoke test the scheduler**

```bash
cd /app && python -c "
from bot.learning.scheduler import LearningScheduler
called = []
s = LearningScheduler(lambda: called.append(1), hour=99)  # heure impossible
s.start()
import time; time.sleep(2)
s.stop()
assert called == []
print('OK scheduler ne déclenche pas en dehors de la fenêtre')
"
```

Expected: `OK scheduler ne déclenche pas en dehors de la fenêtre`

- [ ] **Step 4: Commit**

```bash
git add bot/learning/scheduler.py bot/learning/__init__.py
git commit -m "feat(learning): daily 22h CET scheduler thread"
```

---

## Phase 5 — Wire learning into the bot

### Task 10: Portfolio callback for closed trades

**Files:**
- Modify: `bot/portfolio.py`

- [ ] **Step 1: Add a callback list to Portfolio.__init__**

In `bot/portfolio.py`, find the `Portfolio.__init__` method and add at the end:

```python
        # Callbacks called when a position is closed. Each callback receives
        # (trade: Trade, entry_price: float). Used by learning module.
        self.on_position_closed_callbacks: list = []
```

- [ ] **Step 2: Find where positions are closed and emit the event**

Search for the place that creates the `Trade` object on position close (typically in a `close_position` method). Add:

```python
        # Emit callbacks (defensive: never let a callback crash the bot)
        for cb in self.on_position_closed_callbacks:
            try:
                cb(trade, position.entry_price)
            except Exception as e:
                logger.exception(f"[Portfolio] on_position_closed callback failed: {e}")
```

This goes right before the `return trade` (or equivalent) at the end of `close_position`.

- [ ] **Step 3: Smoke test**

```bash
cd /app && python -c "
from bot.portfolio import Portfolio
p = Portfolio(initial_capital=200, save_path='/tmp/_test.json')
p.on_position_closed_callbacks.append(lambda t, e: print(f'closed: {t.symbol} @ {e}'))
print('OK callback registered')
"
```

Expected: `OK callback registered`

- [ ] **Step 4: Commit**

```bash
git add bot/portfolio.py
git commit -m "feat(portfolio): emit on_position_closed callbacks"
```

---

### Task 11: Config + bot wiring

**Files:**
- Modify: `bot/config.py`
- Modify: `bot/bot.py`
- Modify: `webapp/app.py`

- [ ] **Step 1: Add learning fields to BotConfig**

In `bot/config.py`, add at the end of the dataclass:

```python
    # --- Learning (système d'apprentissage adaptatif) ---
    learning_enabled: bool = False
    learning_dry_run: bool = True  # dry-run par défaut tant que warmup pas terminé
    learning_state_path: str = "learning_state.json"
```

- [ ] **Step 2: Wire learning into TradingBot**

In `bot/bot.py`, after the Portfolio creation (around line 60), add:

```python
        # --- Learning module (optionnel) ---
        self.learning_state = None
        self.learning_store = None
        self.regime_detector = None
        self.tracker = None

        if config.learning_enabled:
            from .learning import (
                LearningStateStore, RegimeDetector, PerformanceTracker, Regime,
            )
            learning_path = os.environ.get(
                "LEARNING_STATE_PATH",
                os.path.join(os.path.dirname(portfolio_path), "learning_state.json"),
            )
            self.learning_store = LearningStateStore(save_path=learning_path)
            self.learning_state = self.learning_store.load()
            self.regime_detector = RegimeDetector()
            self.tracker = PerformanceTracker(self.learning_state)

            # Hook : tracker reçoit les trades fermés
            self.portfolio.on_position_closed_callbacks.append(
                lambda trade, entry_price: self.tracker.record_closed_trade(
                    trade, regime=self.learning_state.current_regime
                )
            )

            logger.info(f"[Learning] Module activé, state: {learning_path}")
            if config.learning_dry_run:
                logger.info("[Learning] Mode DRY-RUN actif, aucun ajustement appliqué")
```

- [ ] **Step 3: Plug regime detection into run_cycle**

Still in `bot/bot.py`, in `run_cycle()`, after `self.portfolio.update_positions(current_prices)` (around line 96), add:

```python
        # --- Mise à jour du régime de marché si learning activé ---
        if self.learning_state is not None and self.regime_detector is not None:
            try:
                self._update_regime(data_dict)
            except Exception as e:
                logger.exception(f"[Learning] Erreur update_regime: {e}")
```

And add this method on the class:

```python
    def _update_regime(self, data_dict):
        """Calcule le régime actuel et met à jour le state."""
        import yfinance as yf

        # 1. Récupère VIX
        try:
            vix_ticker = yf.Ticker("^VIX")
            vix = float(vix_ticker.history(period="1d", interval="1h")["Close"].iloc[-1])
        except Exception as e:
            logger.warning(f"[Learning] VIX indisponible, fallback 15: {e}")
            vix = 15.0

        # 2. Calcule basket moyen pondéré
        if not data_dict:
            return
        symbols = list(data_dict.keys())
        basket = sum(data_dict[s]["close"] for s in symbols) / len(symbols)
        # Convertit en DataFrame (les autres colonnes ne sont pas utilisées)
        import pandas as pd
        basket_df = pd.DataFrame({"close": basket, "open": basket, "high": basket * 1.001, "low": basket * 0.999, "volume": 0})

        # 3. ATR ratio (sur le 1er symbole comme proxy)
        atr_ratio = self.regime_detector.compute_atr_ratio(data_dict[symbols[0]])

        # 4. Classification
        from .learning import Regime
        new_regime = self.regime_detector.classify(vix, basket_df, atr_ratio)
        if new_regime != self.learning_state.current_regime:
            from datetime import datetime, timezone
            logger.info(
                f"[Learning] Régime change : {self.learning_state.current_regime.value} → {new_regime.value}"
            )
            self.learning_state.current_regime = new_regime
            self.learning_state.regime_stable_since = datetime.now(timezone.utc).isoformat()

        # Sauvegarde après chaque cycle
        if self.learning_store:
            self.learning_store.save(self.learning_state)
```

- [ ] **Step 4: Read env vars in webapp/app.py**

In `webapp/app.py`, find the `BotConfig(...)` instantiation and add at the end of the kwargs:

```python
            # --- Learning ---
            learning_enabled=os.environ.get("KRONOS_LEARNING_ENABLED", "false").lower() == "true",
            learning_dry_run=os.environ.get("KRONOS_LEARNING_DRY_RUN", "true").lower() == "true",
```

- [ ] **Step 5: Smoke test the wiring**

```bash
cd /app && KRONOS_LEARNING_ENABLED=true python -c "
from bot.config import BotConfig
import os
cfg = BotConfig(learning_enabled=True)
assert cfg.learning_enabled is True
assert cfg.learning_dry_run is True
print('OK config')
"
```

Expected: `OK config`

- [ ] **Step 6: Commit**

```bash
git add bot/config.py bot/bot.py webapp/app.py
git commit -m "feat(learning): wire learning module into TradingBot"
```

---

## Phase 6 — Webapp endpoints + dashboard panel

### Task 12: Learning state + reset endpoints

**Files:**
- Modify: `webapp/app.py`

- [ ] **Step 1: Add `/api/learning/state` endpoint**

Add after the existing `/api/state` endpoint:

```python
@app.route("/api/learning/state")
@requires_auth
def api_learning_state():
    """Retourne l'état complet du module d'apprentissage."""
    bot = _get_bot()
    if bot.learning_state is None:
        return {"enabled": False}, 200

    state = bot.learning_state
    return {
        "enabled": True,
        "dry_run": bot.config.learning_dry_run,
        "current_regime": state.current_regime.value,
        "regime_stable_since": state.regime_stable_since,
        "warmup_completed_at": state.warmup_completed_at,
        "current_params": {
            sym: {
                "confidence_min": p.confidence_min,
                "buy_threshold": p.buy_threshold,
                "sell_threshold": p.sell_threshold,
                "weight": p.weight,
            }
            for sym, p in state.current_params.items()
        },
        "symbol_stats_by_regime": {
            sym: {
                regime: {
                    "trades": s.trades,
                    "wins": s.wins,
                    "losses": s.losses,
                    "win_rate": s.win_rate,
                    "expectancy": s.expectancy,
                    "pnl_30d": s.pnl_30d,
                }
                for regime, s in by_regime.items()
            }
            for sym, by_regime in state.symbol_stats_by_regime.items()
        },
        "pending_approvals": [
            {
                "id": p.id, "type": p.type, "param_path": p.param_path,
                "from_value": p.from_value, "to_value": p.to_value,
                "reason": p.reason, "confidence_score": p.confidence_score,
                "proposed_at": p.proposed_at,
            }
            for p in state.pending_approvals
        ],
        "global_leverage": state.global_leverage,
        "defensive_mode": state.defensive_mode,
        "param_history_recent": [
            {
                "timestamp": p.proposed_at, "param_path": p.param_path,
                "from_value": p.from_value, "to_value": p.to_value,
                "reason": p.reason, "applied_by": p.applied_by,
            }
            for p in state.param_history[-20:]
        ],
    }, 200
```

- [ ] **Step 2: Add `/api/learning/reset` endpoint**

```python
@app.route("/api/learning/reset", methods=["POST"])
@requires_auth
def api_learning_reset():
    """Remet learning_state.json à vide (retour usine)."""
    bot = _get_bot()
    if bot.learning_state is None:
        return {"ok": False, "message": "Learning module not enabled"}, 400

    from bot.learning.types import LearningState
    bot.learning_state = LearningState()
    if bot.learning_store:
        bot.learning_store.save(bot.learning_state)
    if bot.tracker:
        bot.tracker.state = bot.learning_state
    logger.info("[Learning] State reset by user via API")
    return {"ok": True, "message": "Learning state réinitialisé"}, 200
```

- [ ] **Step 3: Add `/api/learning/approve/<id>` endpoint**

```python
@app.route("/api/learning/approve/<proposal_id>", methods=["POST"])
@requires_auth
def api_learning_approve(proposal_id: str):
    bot = _get_bot()
    if bot.learning_state is None:
        return {"ok": False}, 400

    state = bot.learning_state
    proposal = next((p for p in state.pending_approvals if p.id == proposal_id), None)
    if proposal is None:
        return {"ok": False, "message": "Proposition introuvable"}, 404

    # Applique la proposition
    from bot.learning.engine import AdaptationEngine
    engine = AdaptationEngine(state)
    engine._apply_to_state(proposal)
    proposal.applied_by = "VALIDATION"
    state.param_history.append(proposal)
    state.pending_approvals.remove(proposal)
    if bot.learning_store:
        bot.learning_store.save(state)
    logger.info(f"[Learning] Proposition {proposal_id} validée par utilisateur")
    return {"ok": True}, 200


@app.route("/api/learning/reject/<proposal_id>", methods=["POST"])
@requires_auth
def api_learning_reject(proposal_id: str):
    from datetime import datetime, timezone, timedelta
    from bot.learning.types import RejectedProposal
    from bot.learning.engine import AdaptationEngine

    bot = _get_bot()
    if bot.learning_state is None:
        return {"ok": False}, 400

    state = bot.learning_state
    proposal = next((p for p in state.pending_approvals if p.id == proposal_id), None)
    if proposal is None:
        return {"ok": False, "message": "Proposition introuvable"}, 404

    cooldown_until = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    state.rejected_proposals.append(RejectedProposal(
        proposal_hash=AdaptationEngine._proposal_hash(proposal),
        rejected_at=datetime.now(timezone.utc).isoformat(),
        cooldown_until=cooldown_until,
    ))
    state.pending_approvals.remove(proposal)
    if bot.learning_store:
        bot.learning_store.save(state)
    logger.info(f"[Learning] Proposition {proposal_id} rejetée")
    return {"ok": True}, 200
```

- [ ] **Step 4: Smoke test endpoints**

```bash
# Bot doit tourner avec KRONOS_LEARNING_ENABLED=false
curl -u kronos:Momo694994! http://localhost:5050/api/learning/state
# Expected: {"enabled": false}
```

- [ ] **Step 5: Commit**

```bash
git add webapp/app.py
git commit -m "feat(webapp): /api/learning state, reset, approve, reject endpoints"
```

---

### Task 13: Dashboard "Apprentissage" tab (HTML + CSS + JS)

**Files:**
- Modify: `webapp/templates/dashboard.html`
- Modify: `webapp/static/js/dashboard.js`
- Modify: `webapp/static/css/dashboard.css`

This is a large UI task. To stay focused: build the bare minimum first, refine later.

- [ ] **Step 1: Add the tab markup in `dashboard.html`**

Find the existing tab navigation (search for `<nav class="tabs">` or similar) and add a new tab button. Then add a new tab pane:

```html
<section id="tab-learning" class="tab-pane" hidden>
  <div class="learning-grid">

    <div class="card">
      <h3>🌡️ Régime actuel</h3>
      <div id="learning-regime-display">
        <span class="regime-badge regime-RANGING">RANGING</span>
        <p class="regime-meta" id="learning-regime-meta">VIX: -- | ATR: -- | Pente: --</p>
      </div>
    </div>

    <div class="card">
      <h3>⚙️ Paramètres par symbole</h3>
      <table class="learning-params-table">
        <thead>
          <tr>
            <th>Symbole</th><th>Confidence</th><th>Buy thr</th><th>Win rate</th><th>Trades</th>
          </tr>
        </thead>
        <tbody id="learning-params-tbody">
          <tr><td colspan="5">Chargement...</td></tr>
        </tbody>
      </table>
    </div>

    <div class="card" id="learning-pending-card" hidden>
      <h3>🔔 Validations en attente</h3>
      <div id="learning-pending-list"></div>
    </div>

    <div class="card">
      <h3>📜 Historique des ajustements (20 derniers)</h3>
      <ul id="learning-history-list" class="learning-history">
        <li>Chargement...</li>
      </ul>
    </div>

    <div class="card">
      <h3>🛟 Réglages</h3>
      <button id="learning-reset-btn" class="btn btn-danger">
        🔄 Reset paramètres à la config initiale
      </button>
    </div>

  </div>
</section>
```

Also add a tab nav button:

```html
<button class="tab-btn" data-tab="learning">🧠 Apprentissage</button>
```

- [ ] **Step 2: Add JS rendering in `dashboard.js`**

At the bottom of `dashboard.js` (or wherever rendering helpers live), add:

```javascript
async function loadLearningState() {
  try {
    const r = await fetch("/api/learning/state");
    if (!r.ok) return;
    const data = await r.json();
    if (!data.enabled) {
      document.querySelector("#tab-learning .learning-grid").innerHTML =
        '<div class="card"><p>Module d\'apprentissage désactivé. Définir <code>KRONOS_LEARNING_ENABLED=true</code> dans le compose pour l\'activer.</p></div>';
      return;
    }
    renderLearningRegime(data);
    renderLearningParams(data);
    renderLearningPending(data);
    renderLearningHistory(data);
  } catch (e) {
    console.error("[Learning] load failed", e);
  }
}

function renderLearningRegime(data) {
  const badge = document.querySelector("#learning-regime-display .regime-badge");
  if (badge) {
    badge.className = `regime-badge regime-${data.current_regime}`;
    badge.textContent = data.current_regime;
  }
  const meta = document.getElementById("learning-regime-meta");
  if (meta) {
    meta.textContent = `Stable depuis : ${data.regime_stable_since || 'N/A'} | Levier global : ${data.global_leverage}x`;
  }
}

function renderLearningParams(data) {
  const tbody = document.getElementById("learning-params-tbody");
  if (!tbody) return;
  const symbols = Object.keys(data.current_params);
  if (symbols.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5">Pas encore de paramètres adaptés</td></tr>';
    return;
  }
  tbody.innerHTML = symbols.map(sym => {
    const p = data.current_params[sym];
    const stats = data.symbol_stats_by_regime[sym]?.[data.current_regime];
    const wr = stats ? `${(stats.win_rate * 100).toFixed(0)}%` : "--";
    const tr = stats ? stats.trades : "--";
    return `<tr>
      <td><b>${sym}</b></td>
      <td>${p.confidence_min.toFixed(3)}</td>
      <td>${(p.buy_threshold * 100).toFixed(2)}%</td>
      <td>${wr}</td>
      <td>${tr}</td>
    </tr>`;
  }).join("");
}

function renderLearningPending(data) {
  const card = document.getElementById("learning-pending-card");
  const list = document.getElementById("learning-pending-list");
  if (!card || !list) return;
  if (data.pending_approvals.length === 0) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  list.innerHTML = data.pending_approvals.map(p => `
    <div class="pending-item">
      <p><b>${p.type}</b>: ${p.from_value} → ${p.to_value}</p>
      <p class="reason"><i>${p.reason}</i></p>
      <button onclick="approveLearningProposal('${p.id}')" class="btn btn-success">✅ Valider</button>
      <button onclick="rejectLearningProposal('${p.id}')" class="btn btn-danger">❌ Refuser</button>
    </div>
  `).join("");
}

function renderLearningHistory(data) {
  const list = document.getElementById("learning-history-list");
  if (!list) return;
  if (!data.param_history_recent || data.param_history_recent.length === 0) {
    list.innerHTML = '<li>Aucun ajustement encore</li>';
    return;
  }
  list.innerHTML = data.param_history_recent.slice().reverse().map(p => `
    <li>
      <span class="ts">${p.timestamp.slice(0, 16).replace('T', ' ')}</span>
      <span class="tag tag-${p.applied_by.toLowerCase()}">${p.applied_by}</span>
      <code>${p.param_path}</code> :
      <code>${p.from_value} → ${p.to_value}</code>
      <span class="reason">${p.reason}</span>
    </li>
  `).join("");
}

async function approveLearningProposal(id) {
  await fetch(`/api/learning/approve/${id}`, {method: "POST"});
  loadLearningState();
}

async function rejectLearningProposal(id) {
  await fetch(`/api/learning/reject/${id}`, {method: "POST"});
  loadLearningState();
}

document.getElementById("learning-reset-btn")?.addEventListener("click", async () => {
  if (!confirm("Sûr ? Cela remet TOUS les paramètres adaptatifs à zéro.")) return;
  await fetch("/api/learning/reset", {method: "POST"});
  loadLearningState();
});

// Charge dès qu'on switch sur l'onglet
document.querySelectorAll("[data-tab='learning']").forEach(b =>
  b.addEventListener("click", () => loadLearningState())
);

// Rafraîchit toutes les 30 sec si l'onglet est actif
setInterval(() => {
  const pane = document.getElementById("tab-learning");
  if (pane && !pane.hidden) loadLearningState();
}, 30000);
```

- [ ] **Step 3: Add CSS styling in `dashboard.css`**

```css
/* === Learning panel === */
.learning-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1rem;
}

@media (min-width: 768px) {
  .learning-grid {
    grid-template-columns: 1fr 1fr;
  }
}

.regime-badge {
  display: inline-block;
  padding: 0.5rem 1rem;
  border-radius: 4px;
  font-weight: bold;
  font-size: 1.2rem;
}

.regime-TREND_UP { background: #1d4d2b; color: #6affad; }
.regime-TREND_DOWN { background: #4d1d1d; color: #ff7777; }
.regime-RANGING { background: #2d2d4d; color: #8888ff; }
.regime-HIGH_VOLATILITY { background: #4d3a1d; color: #ffaa44; animation: pulse 1.5s infinite; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

.learning-params-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}

.learning-params-table th,
.learning-params-table td {
  padding: 0.4rem 0.6rem;
  text-align: left;
  border-bottom: 1px solid var(--border, #333);
}

.pending-item {
  padding: 0.8rem;
  margin-bottom: 0.6rem;
  background: rgba(255, 170, 68, 0.1);
  border-left: 3px solid #ffaa44;
  border-radius: 4px;
}

.learning-history {
  list-style: none;
  padding: 0;
  font-size: 0.85rem;
  max-height: 300px;
  overflow-y: auto;
}

.learning-history li {
  padding: 0.3rem 0;
  border-bottom: 1px solid rgba(255,255,255,0.05);
}

.tag {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 0.75rem;
  margin: 0 4px;
}
.tag-auto { background: #1d4d2b; color: #6affad; }
.tag-validation { background: #4d3a1d; color: #ffaa44; }
.tag-rejected { background: #4d1d1d; color: #ff7777; }
```

- [ ] **Step 4: Manual smoke test**

Build & run the bot, navigate to dashboard, click "🧠 Apprentissage" tab. Should show "Module désactivé" message (since `KRONOS_LEARNING_ENABLED=false` by default).

- [ ] **Step 5: Commit**

```bash
git add webapp/templates/dashboard.html webapp/static/js/dashboard.js webapp/static/css/dashboard.css
git commit -m "feat(dashboard): add Apprentissage tab"
```

---

## Phase 7 — Daily cycle integration

### Task 14: Wire DailyReporter + AdaptationEngine into the scheduler

**Files:**
- Modify: `webapp/app.py`

The bot module already has all components. Now we need a single function `run_daily_learning_cycle()` that the scheduler calls at 22h00.

- [ ] **Step 1: Add the daily cycle function in `webapp/app.py`**

```python
def run_daily_learning_cycle():
    """Cycle quotidien : régime, propositions, application, récap Telegram."""
    bot = _bot
    if bot is None or bot.learning_state is None:
        logger.info("[Learning] daily cycle skip (bot/learning non init)")
        return

    from bot.learning import AdaptationEngine, DailyReporter
    from bot.learning.types import LearningState
    from datetime import datetime, timezone, timedelta

    state = bot.learning_state
    logger.info(f"[Learning] === Cycle quotidien démarré (régime: {state.current_regime.value}) ===")

    # 1. Calcule drawdown récent (7j) sur le portfolio
    portfolio_summary = bot.portfolio.get_summary()
    recent_drawdown = abs(portfolio_summary.get("drawdown", 0)) / 100.0  # supposant en %

    # 2. AdaptationEngine
    engine = AdaptationEngine(state, dry_run=bot.config.learning_dry_run)
    proposals = engine.propose_adjustments(
        recent_drawdown_pct=recent_drawdown,
        recent_avg_vix=15.0,  # TODO: calculer la moyenne sur 7j (pour l'instant fixe)
    )
    auto = [p for p in proposals if p.applied_by == "AUTO"]
    pending_now = [p for p in proposals if p.applied_by == "VALIDATION"]
    engine.apply_auto(proposals)

    # 3. Sauvegarde
    if bot.learning_store:
        bot.learning_store.save(state)

    # 4. Calcule métriques pour le récap
    sharpe_30d = portfolio_summary.get("sharpe_30d", 0.0)
    win_rate_30d = portfolio_summary.get("win_rate_30d", 0.0)
    drawdown_30d = portfolio_summary.get("drawdown_30d", 0.0)
    expectancy_30d = portfolio_summary.get("expectancy_30d", 0.0)
    pnl_today = portfolio_summary.get("pnl_journalier", 0.0)
    equity = portfolio_summary.get("valeur_totale", 0.0)
    trades_today = portfolio_summary.get("trades_today", 0)

    # 5. Envoie le récap Telegram
    if _telegram_notifier and _telegram_notifier.enabled:
        reporter = DailyReporter(state)
        msg = reporter.format_daily_message(
            trades_today=trades_today,
            wins_today=0,  # TODO: ventiler win/loss du jour
            losses_today=0,
            pnl_today=pnl_today,
            equity=equity,
            sharpe_30d=sharpe_30d,
            win_rate_30d=win_rate_30d,
            drawdown_30d=drawdown_30d,
            expectancy_30d=expectancy_30d,
            auto_applied=auto,
            pending=state.pending_approvals,
        )
        if state.pending_approvals:
            kb = reporter.build_inline_keyboard(state.pending_approvals)
            _telegram_notifier.send_with_inline_keyboard(msg, kb)
        else:
            _telegram_notifier.send(msg)

    logger.info(f"[Learning] === Cycle terminé : {len(auto)} auto + {len(pending_now)} pending ===")
```

- [ ] **Step 2: Start the scheduler at app boot**

In `webapp/app.py`, find where the auto_cycle scheduler thread is started. Add right after:

```python
# --- Learning scheduler (22h00 daily) ---
_learning_scheduler = None

def start_learning_scheduler():
    global _learning_scheduler
    bot = _get_bot()
    if not bot.config.learning_enabled or _learning_scheduler is not None:
        return
    from bot.learning import LearningScheduler
    _learning_scheduler = LearningScheduler(
        callback=run_daily_learning_cycle,
        timezone=bot.config.timezone,
        hour=22, minute=0,
    )
    _learning_scheduler.start()
    logger.info("[Learning] Scheduler démarré")
```

And call `start_learning_scheduler()` after the existing `start_auto_scheduler()` call (or equivalent boot section).

- [ ] **Step 3: Smoke test**

Run bot with `KRONOS_LEARNING_ENABLED=true KRONOS_LEARNING_DRY_RUN=true` and observe logs at startup:

```
[Learning] Module activé
[Learning] Scheduler démarré
```

- [ ] **Step 4: Commit**

```bash
git add webapp/app.py
git commit -m "feat(learning): wire daily cycle (engine + reporter + scheduler)"
```

---

## Phase 8 — Backtest mode + deployment

### Task 15: Backtest with `--with-learning` flag

**Files:**
- Modify: `backtest.py`

- [ ] **Step 1: Add CLI flag and run-with-learning path**

In `backtest.py`, find the argparse block and add:

```python
    parser.add_argument(
        "--with-learning", action="store_true",
        help="Active le module d'apprentissage pendant le backtest",
    )
```

- [ ] **Step 2: Apply learning during backtest cycles**

Wrap the existing backtest loop. After each closed trade, call `tracker.record_closed_trade`. At the end of each simulated day, call `engine.apply_auto`. Compare final Sharpe vs baseline.

```python
def run_backtest(args):
    # ... existing setup ...

    state = None
    tracker = None
    if args.with_learning:
        from bot.learning import LearningStateStore, PerformanceTracker, AdaptationEngine
        from bot.learning.types import LearningState
        state = LearningState()
        tracker = PerformanceTracker(state)

    # ... existing loop with hooks for learning ...
    # During the loop, every time a position closes:
    if tracker:
        tracker.record_closed_trade(closed_trade, regime=current_regime)

    # End of each simulated day:
    if args.with_learning and is_end_of_day:
        engine = AdaptationEngine(state)
        proposals = engine.propose_adjustments()
        engine.apply_auto(proposals)
```

- [ ] **Step 3: Print comparison table**

At the end, print baseline vs learning metrics. If `--with-learning`, replay the loop **twice** internally and compare Sharpe / drawdown / win_rate / total_return.

- [ ] **Step 4: Smoke test**

```bash
cd /app && python backtest.py --period 30d --with-learning
```

Should print a comparison table.

- [ ] **Step 5: Commit**

```bash
git add backtest.py
git commit -m "feat(backtest): add --with-learning flag for A/B comparison"
```

---

### Task 16: Docker compose + deployment guide

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add learning env vars (default OFF)**

In the `environment:` block of `docker-compose.yml`, add:

```yaml
      # --- Apprentissage adaptatif (optionnel) ---
      - KRONOS_LEARNING_ENABLED=${KRONOS_LEARNING_ENABLED:-false}
      - KRONOS_LEARNING_DRY_RUN=${KRONOS_LEARNING_DRY_RUN:-true}
```

- [ ] **Step 2: Verify defaults are safe**

The default state must be: feature OFF, behavior identical to today's bot.

```bash
cd /app && python -c "
import os
os.environ.pop('KRONOS_LEARNING_ENABLED', None)
from bot.config import BotConfig
cfg = BotConfig()
assert cfg.learning_enabled is False
print('OK: defaults safe')
"
```

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(docker): add KRONOS_LEARNING_* env vars (off by default)"
```

---

### Task 17: Push to GitHub for Docker build

- [ ] **Step 1: Final lint check on all modified files**

```bash
cd /app && python -m py_compile bot/learning/*.py webapp/app.py bot/bot.py bot/config.py
echo "OK lint"
```

- [ ] **Step 2: Run all learning tests**

```bash
cd /app && python -m pytest tests/learning/ -v
```

Expected: all passing.

- [ ] **Step 3: Push branch**

```bash
git push fork feature/kronos-trading-bot
```

This triggers the GitHub Actions Docker build (multi-arch, ~15-20 min for the first ARM build with new deps if any).

- [ ] **Step 4: Verify the build completes**

```bash
gh run list --repo larabestrais/Kronos --limit 1
```

Wait for `success`.

---

### Task 18: User deployment + Phase 1 (observation)

- [ ] **Step 1: User redeploys via UGOS Pro Docker**

Stop project `kronos-bot-ig`. In the compose, add the SHA-tagged image (forces fresh pull):

```yaml
image: ghcr.io/larabestrais/kronos-trading-bot:<NEW_SHA>
```

Add the env vars for Phase 1 (observation mode):

```yaml
- KRONOS_LEARNING_ENABLED=true
- KRONOS_LEARNING_DRY_RUN=true
```

Activate. Verify logs:

```
[Learning] Module activé
[Learning] Mode DRY-RUN actif, aucun ajustement appliqué
[Learning] Scheduler démarré
```

- [ ] **Step 2: Wait 7 days, monitor daily Telegram reports**

Each evening at 22h00, you'll receive a Telegram report. Verify:
- Regime detection looks reasonable
- Per-symbol stats accumulate
- Proposed adjustments make sense

- [ ] **Step 3: After 7 days, switch to Phase 2 (active)**

Edit compose, change `KRONOS_LEARNING_DRY_RUN=false`. Restart. The bot will start applying minor changes automatically. Major changes still go through Telegram approval.

---

## Self-review notes

The following spec sections are covered:
- Section 1 (Contexte) → addressed in plan goal
- Section 2 (Architecture) → Tasks 1-9 (4 modules + scheduler + storage + types)
- Section 3 (Composants) → Tasks 4 (RegimeDetector), 5 (PerformanceTracker), 6 (AdaptationEngine), 8 (DailyReporter), 9 (Scheduler), 12 (Webhook = optional, deferred to polling-friendly approach)
- Section 4 (Stockage) → Task 3 (LearningStateStore)
- Section 5 (Sécurité) → Tasks 2 (bounds), 11 (config + dry_run), 12 (reset endpoint), warmup deferred (uses dry_run as substitute for first 7 days)
- Section 6 (UX) → Tasks 8 (reporter), 13 (dashboard panel)
- Section 7 (Tests) → Tests embedded in each task; Task 15 covers backtest
- Section 8 (Observabilité) → Logging in every module; `/api/learning/state` exposes metrics
- Section 9 (Déploiement) → Tasks 16-18 cover Phase 0-1-2 rollout
- Section 11 (Critères d'acceptation) → All 7 covered by Tasks 1-18

**Known deferrals (acceptable for Phase 1, addressed later)**:
- Telegram webhook callback → for now, approval via dashboard buttons. Polling-based callback handler is a future enhancement.
- Regime change "urgent alerts" outside the 22h cycle → can be added if regime changes prove disruptive.
- Detailed Sharpe/drawdown calculation in `Portfolio.get_summary()` may need extension; the plan uses placeholders that fall back gracefully.
- Exact win/loss split of trades_today not yet wired — uses placeholder zeros.

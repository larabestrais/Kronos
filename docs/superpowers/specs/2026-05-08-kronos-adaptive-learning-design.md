# Kronos — Système d'apprentissage adaptatif

**Auteur** : Reda + Claude
**Date** : 2026-05-08
**Statut** : Design validé, en attente d'implémentation

---

## 1. Contexte et objectif

### Situation actuelle

Le bot Kronos tourne en paper trading sur un NAS UGREEN DH2300 :
- 200 € de capital, levier 5x
- 6 symboles US (AAPL, MSFT, GOOGL, NVDA, TSLA, INTC)
- Cycles horaires pendant les heures de marché (15h30-22h00 CET)
- Source de données : yfinance (15 min de retard)
- 37 trades exécutés, PnL total -1 € (-1%)
- Paramètres **statiques** définis dans le `docker-compose.yml` (`KRONOS_*`)

### Limite identifiée

Le bot **n'apprend pas de son expérience**. Si AAPL marche bien en marché trending mais foire systématiquement en marché stressé, les paramètres restent identiques. Il manque une boucle de rétroaction.

### Objectif

Faire en sorte que Kronos devienne **plus intelligent et plus intuitif au fil du temps** en apprenant :
1. **De son historique** : ajuster ses seuils par symbole en fonction des performances passées
2. **Du régime de marché** : détecter et s'adapter aux changements (trending, ranging, volatile)

### Métrique d'optimisation

**Retour ajusté au risque** (Sharpe ratio) avec un plancher minimum de win rate (≥45%). Choisi parce qu'il favorise une croissance régulière, évite les drawdowns destructeurs sous levier, et prépare la transition vers le compte réel.

### Mode d'autonomie

**Hybride** :
- **AUTO** sur les ajustements mineurs (seuils par symbole, poids d'allocation)
- **VALIDATION manuelle** sur les changements majeurs (levier, SL/TP, ajout/retrait symbole)

### Cadence

Cycle d'apprentissage **quotidien à 22h00 CET** (après clôture US), avec récap Telegram immédiat.

---

## 2. Architecture

### Vue d'ensemble

```
┌──────────────────────────────────────────────────────────────┐
│  KRONOS-BOT (existant, inchangé)                              │
│                                                                │
│  Toutes les heures pendant le marché :                        │
│    données → prédicteur Kronos → signal → trader → portfolio  │
│                                                  │             │
└──────────────────────────────────────────────────┼─────────────┘
                                                    │
                              [trades fermés écrits dans un journal]
                                                    │
                                                    ↓
┌──────────────────────────────────────────────────────────────┐
│  KRONOS-LEARNING (nouveau module)                              │
│                                                                │
│   📊 PerformanceTracker                                        │
│     → enregistre chaque trade + le régime de marché du moment │
│                                                                │
│   🌡️ RegimeDetector                                           │
│     → "marché haussier ?", "panique ?", "calme plat ?"        │
│                                                                │
│   🧠 AdaptationEngine          ← le cœur du système            │
│     → analyse les stats par symbole et par régime              │
│     → propose des ajustements basés sur des règles claires     │
│     → split AUTO / VALIDATION                                 │
│                                                                │
│   📲 DailyReporter (à 22h00)                                   │
│     → ping Telegram avec le bilan + les ajustements           │
└──────────────────────────────────────────────────────────────┘
```

### Principe d'isolation

- Le module `bot/learning/` est **branché** sur le bot existant via des hooks (events sur trade fermé, sur cycle terminé)
- Le bot existant **ne dépend pas** du module learning : si on désactive `KRONOS_LEARNING_ENABLED`, tout fonctionne comme avant
- Le module learning **lit** l'état du portefeuille mais ne modifie **directement** que ses propres paramètres adaptatifs

### Approche technique : Statistique / Règles (Approche 1)

Choisie parmi 3 alternatives évaluées :
1. **Statistique / Règles** ✅ — explicable, marche avec peu de données, validé pour Phase 1
2. Bandit Thompson Sampling — réservé pour Phase 3 (>200 trades)
3. Meta-modèle ML (gradient boosting incrémental) — non retenu pour l'instant (boîte noire, demande 500+ trades)

---

## 3. Composants

### 3.1 PerformanceTracker

**Responsabilité** : enregistrer chaque trade fermé avec son contexte enrichi.

**Entrée** : événement `position_closed` du `Portfolio`.

**Sortie** : ligne ajoutée à `learning_state.json` → section `symbol_stats_by_regime`.

**Calculs maintenus** (par symbole, par régime) :
- Nombre de trades, wins, losses
- Expectancy = moyenne((win_pnl × P_win) - (loss_pnl × P_loss))
- Win rate
- Sharpe rolling 30 jours
- PnL total, drawdown max

### 3.2 RegimeDetector

**Responsabilité** : classifier le régime de marché actuel parmi 4 catégories.

**Entrée** :
- VIX (récupéré via yfinance, symbole `^VIX`, mis à jour chaque cycle)
- Pente de régression linéaire sur 50 dernières heures du panier des 6 symboles (pondéré)
- ATR ratio = ATR(20) / prix actuel

**Sortie** : un des 4 régimes :
- `TREND_UP` — pente > +0.1% ET VIX < 25 ET ATR < 3%
- `TREND_DOWN` — pente < -0.1% ET VIX < 25 ET ATR < 3%
- `RANGING` — |pente| < 0.1% ET VIX < 25 ET ATR < 3%
- `HIGH_VOLATILITY` — VIX > 25 OU ATR > 3% (priorité absolue)

**Persistance** : régime actuel + horodatage du dernier changement stockés dans `learning_state.json`.

### 3.3 AdaptationEngine

**Responsabilité** : appliquer les règles d'ajustement.

**Trigger** : cycle quotidien à 22h00 + transitions de régime urgentes.

**Algorithme** :
1. Charger `symbol_stats_by_regime` et le régime actuel
2. Pour chaque symbole, calculer si une règle s'applique
3. Pour les ajustements **mineurs** : appliquer immédiatement (avec clamp aux bornes)
4. Pour les ajustements **majeurs** : enrichir avec une justification, ajouter à `pending_approvals`
5. Logger toutes les actions dans `param_history`

**Règles AUTO (mineures)** :

| Condition | Action |
|---|---|
| `win_rate(symbole, régime) > 60%` sur 20+ trades | `confidence_min` -5% (clamp [0.50, 0.75]) |
| `win_rate(symbole, régime) < 40%` sur 10+ trades | `confidence_min` +10% |
| `expectancy(symbole) < 0` sur 20+ trades | Poids d'allocation -25% |
| `expectancy(symbole) > +1%` sur 20+ trades | Poids d'allocation +20% |
| ATR(symbole) augmente de >30% en 5j | `buy_threshold` +30% |
| 3+ pertes consécutives sur 1 créneau horaire | Skip ce créneau pour ce symbole |

**Règles VALIDATION (majeures)** :

| Condition | Proposition |
|---|---|
| Drawdown 7j > 5% ET VIX > 22 | Levier × 0.8 (5x → 4x) |
| Régime = HIGH_VOLATILITY pendant 5+ jours | Mode défensif (positions max ÷2) |
| Symbole avec expectancy < -1% sur 30+ trades | Retirer le symbole |
| Sharpe rolling 30j tombe sous 0.5 | Pause complète + post-mortem |

### 3.4 DailyReporter

**Responsabilité** : envoyer le récap Telegram à 22h00.

**Format** : voir Section 4 du design (récap structuré 4 blocs : performance jour, performance 30j, ajustements auto, validations requises).

**Approbations Telegram** : utilisation de l'inline keyboard de l'API Telegram :
- `[✅ VALIDER]` callback `learning:approve:<id>`
- `[❌ REFUSER]` callback `learning:reject:<id>` (cooldown 7j sur la même proposition)
- `[⏸️ PLUS TARD]` callback `learning:defer:<id>` (reproposera demain)

### 3.5 Webhook Telegram (extension de la webapp existante)

Pas un nouveau module, mais un endpoint ajouté à `webapp/app.py` :

**Nouveau endpoint** : `POST /api/telegram/webhook` qui reçoit les callbacks des boutons inline.

Authentification via `X-Telegram-Bot-Api-Secret-Token`. À configurer côté Telegram via `setWebhook` au démarrage du bot (ou en mode polling si on préfère éviter d'exposer un endpoint public — décision à prendre pendant l'implémentation, le NAS étant accessible uniquement via Tailscale).

---

## 4. Stockage

### Fichier `learning_state.json`

Localisation : `/app/data/learning_state.json` (volume Docker `kronos-data`).

**Schéma JSON** :

```json
{
  "version": 1,
  "last_update": "2026-05-08T22:00:00Z",
  "current_regime": "TREND_UP",
  "regime_stable_since": "2026-05-08T16:00:00Z",
  "warmup_completed_at": "2026-05-15T22:00:00Z",
  
  "symbol_stats_by_regime": {
    "AAPL": {
      "TREND_UP":         { "trades": 12, "wins": 9, "losses": 3, "expectancy": 0.018, "pnl_30d": 4.2 },
      "TREND_DOWN":       { "trades": 3,  "wins": 1, "losses": 2, "expectancy": -0.005, "pnl_30d": -0.3 },
      "RANGING":          { "trades": 5,  "wins": 3, "losses": 2, "expectancy": 0.002, "pnl_30d": 0.8 },
      "HIGH_VOLATILITY":  { "trades": 4,  "wins": 1, "losses": 3, "expectancy": -0.021, "pnl_30d": -1.5 }
    }
  },
  
  "current_params": {
    "AAPL":  { "confidence_min": 0.58, "buy_threshold": 0.01, "sell_threshold": -0.01, "weight": 0.20 },
    "MSFT":  { "confidence_min": 0.60, "buy_threshold": 0.01, "sell_threshold": -0.01, "weight": 0.18 }
  },
  
  "skip_hours_by_symbol": {
    "GOOGL": ["16:00-17:00"]
  },
  
  "param_history": [
    {
      "timestamp": "2026-05-08T22:00:00Z",
      "symbol": "AAPL",
      "param": "confidence_min",
      "from": 0.60,
      "to": 0.58,
      "reason": "win rate 68% sur 20 trades en TREND_UP",
      "applied_by": "AUTO",
      "regime_at_time": "TREND_UP"
    }
  ],
  
  "pending_approvals": [
    {
      "id": "uuid-abc-123",
      "type": "leverage_change",
      "from": 5,
      "to": 4,
      "reason": "VIX moyen 22.5 sur la semaine, drawdown -3.5%",
      "confidence_score": 0.78,
      "proposed_at": "2026-05-08T22:00:00Z",
      "expires_at": "2026-05-15T22:00:00Z"
    }
  ],
  
  "rejected_proposals": [
    {
      "proposal_hash": "leverage_5_to_4",
      "rejected_at": "2026-05-08T22:00:00Z",
      "cooldown_until": "2026-05-15T22:00:00Z"
    }
  ]
}
```

**Sauvegarde atomique** : write-then-rename pour éviter la corruption en cas de crash. Versioning du schéma pour les migrations futures.

---

## 5. Sécurité

### 5.1 Kill switch global

```bash
KRONOS_LEARNING_ENABLED=false
```

→ Module entièrement désactivé. Bot revient à la config statique du compose. Aucun ajustement appliqué.

### 5.2 Mode dry-run

```bash
KRONOS_LEARNING_DRY_RUN=true
```

→ Calcule régimes, stats, ajustements proposés. Envoie le récap Telegram. **N'applique rien.**

### 5.3 Bornes dures (clamps)

| Paramètre | Min | Max |
|---|---|---|
| `confidence_min` | 0.50 | 0.75 |
| `buy_threshold` | 0.5% | 2.0% |
| `sell_threshold` | -2.0% | -0.5% |
| Poids d'allocation par symbole | 5% | 30% |
| Réduction position en HIGH_VOLATILITY | 0% | -50% |

Tout ajustement qui dépasserait ces bornes est **clampé** sans erreur, juste logué.

**Plafond de mouvement par jour** : aucun paramètre ne peut bouger de plus de **±15%** par cycle quotidien.

### 5.4 Période de chauffe (warmup)

**7 jours** après l'activation initiale, le module tourne en `KRONOS_LEARNING_DRY_RUN=true` forcé. Au bout de 7 jours, message Telegram :

```
🎓 KRONOS — Période d'observation terminée
[✅ ACTIVER L'APPRENTISSAGE AUTO]   [❌ ATTENDRE]
```

L'utilisateur valide manuellement le passage en mode actif.

### 5.5 Reset complet

Endpoint `POST /api/learning/reset` (avec auth basique) → vide `learning_state.json`, remet tous les paramètres aux valeurs du compose YAML. **Retour à l'état d'usine.**

Bouton dashboard équivalent dans le panel `/learning`.

### 5.6 Garde-fou sur drawdown

Si le drawdown 24h dépasse **5%**, le module **se met en pause automatique** et envoie une alerte Telegram. Aucun ajustement n'est appliqué jusqu'à ce que l'utilisateur clique "Reprendre".

---

## 6. UX (Telegram + Dashboard)

### 6.1 Récap Telegram quotidien

Voir Section 4 du design pour le format détaillé. 4 blocs structurés :

1. **Performance du jour** (trades, PnL, régime)
2. **Performance 30 jours** (Sharpe, win rate, drawdown, expectancy)
3. **Ajustements auto appliqués** (liste + raison)
4. **Validations requises** (avec boutons inline)

### 6.2 Alertes hors récap

Pour les **transitions urgentes** (passage en HIGH_VOLATILITY soudain) → message immédiat avec proposition.

### 6.3 Nouveau panel dashboard `/learning`

Onglet **"Apprentissage"** ajouté à `webapp/templates/dashboard.html` :
- Vue régime actuel (avec indicateurs VIX, ATR, pente)
- Tableau des paramètres par symbole (avec icônes ↑↓− et badges win rate)
- Equity curve 30j avec annotations des ajustements
- Liste des validations en attente
- Boutons "Pauser l'apprentissage" et "Reset paramètres"

---

## 7. Tests

### 7.1 Unitaires (`tests/learning/`)

- `test_regime_detector.py` : matrice d'inputs (VIX, pente, ATR) → régime attendu
- `test_adaptation_engine.py` : trades fictifs avec stats variées → ajustements attendus
- `test_storage.py` : sérialisation/désérialisation, atomicité, migration de schéma
- `test_safety_bounds.py` : tous les clamps + plafond de mouvement quotidien
- `test_telegram_callbacks.py` : webhook avec différents callbacks (approve/reject/defer)

### 7.2 Backtest avec apprentissage

Nouvelle option dans `backtest.py` : `--with-learning`.

Replay l'historique 2× (baseline vs avec learning), retourne un comparatif :

```
                    Baseline    With Learning
Total return        +5.2%       +8.7%        ✨
Sharpe ratio        0.92        1.38         ✨
Max drawdown        -8.1%       -5.4%        ✨
Win rate            52%         57%          ✨
```

**Critère de validation** : si `Sharpe(learning) < Sharpe(baseline) × 0.9`, on n'active pas en prod tant qu'on n'a pas compris pourquoi.

### 7.3 Intégration

Test e2e dans Docker : démarrer le bot avec `KRONOS_LEARNING_DRY_RUN=true`, simuler 10 cycles, vérifier qu'aucun paramètre du portfolio n'a bougé mais que `learning_state.json` est rempli.

---

## 8. Observabilité

### 8.1 Logs

Logger dédié `kronos.learning` avec niveau INFO. Format :

```
[Learning] === Cycle quotidien démarré (22:00:03) ===
[Learning] Régime actuel : TREND_UP (stable depuis 6h)
[Learning] AAPL : 12 trades en TREND_UP, win rate 68%, expectancy +1.8%
[Learning]   → Proposition AUTO : confidence_min 0.60 → 0.58
[Learning]   ✓ Appliqué (clamp [0.50, 0.75] respecté)
[Learning] === Cycle terminé en 1.4s ===
```

### 8.2 Métriques exposées via `/api/state`

```json
{
  "learning": {
    "enabled": true,
    "dry_run": false,
    "current_regime": "TREND_UP",
    "regime_stable_minutes": 360,
    "sharpe_30d": 1.42,
    "adjustments_today": 3,
    "pending_approvals": 1,
    "warmup_active": false
  }
}
```

Consommé par le panel dashboard `/learning`.

---

## 9. Stratégie de déploiement (3 phases)

### Phase 0 — Build initial (cette nuit)

- Code complet implémenté
- `KRONOS_LEARNING_ENABLED=false` par défaut dans le compose
- Bot fonctionne **exactement comme aujourd'hui**
- **Zéro risque** sur la prod actuelle

### Phase 1 — Observation (semaine 1)

- Activer `KRONOS_LEARNING_ENABLED=true` + `KRONOS_LEARNING_DRY_RUN=true`
- Le bot collecte les stats et envoie les recos chaque soir
- **Aucun paramètre n'est modifié**
- Validation par l'utilisateur de la qualité des recommandations

### Phase 2 — Activation auto (semaine 2+)

- Désactiver `KRONOS_LEARNING_DRY_RUN`
- Les ajustements **mineurs** s'appliquent automatiquement
- Les ajustements **majeurs** continuent à passer par Telegram
- Monitoring du Sharpe rolling 30j

### Phase 3 — (Optionnel, mois 2+)

- Si tout va bien et qu'on a 200+ trades, évaluer l'ajout de l'**Approche 2 (Bandit Thompson Sampling)** par-dessus les règles statistiques pour optimiser des combinaisons que les règles n'ont pas codifiées.
- Cette phase fera l'objet d'un nouveau cycle de design.

---

## 10. Questions ouvertes (à trancher pendant l'implémentation)

- **Cooldown sur les rejets de propositions** : 7 jours est un placeholder, à valider en pratique
- **Format exact du callback Telegram** : à finaliser selon les contraintes de l'API
- **Persistance des stats avant warmup** : on garde les 37 trades existants ou on repart de zéro ? Décision : on garde mais on les tag comme `regime=UNKNOWN` (warmup obligatoire pour bootstrap les stats par régime)

---

## 11. Critères d'acceptation

Le système sera considéré comme livré quand :

1. ✅ `bot/learning/` existe avec les 4 modules (PerformanceTracker, RegimeDetector, AdaptationEngine, DailyReporter)
2. ✅ Tous les tests unitaires passent
3. ✅ Backtest 90j montre `Sharpe(learning) ≥ Sharpe(baseline) × 0.9`
4. ✅ Bot tourne en Phase 0 (learning désactivé) sans régression vs aujourd'hui
5. ✅ Récap Telegram envoyé en mode dry-run pendant 7 jours
6. ✅ Panel dashboard `/learning` accessible et fonctionnel
7. ✅ Documentation utilisateur dans `docs/learning.md`

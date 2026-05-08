# Déploiement du module d'apprentissage adaptatif

Guide pas-à-pas pour activer la nouvelle fonctionnalité **apprentissage** sur le NAS UGREEN DH2300.

## 📊 État du code

- ✅ 16 commits ajoutés sur `feature/kronos-trading-bot`
- ✅ 55 tests unitaires passent (12 bounds + 9 regime + 7 storage + 6 tracker + 7 types + 9 engine + 5 reporter)
- ✅ Build Docker multi-arch GitHub Actions
- ✅ Defaults sécurisés : **off par défaut** → comportement identique à aujourd'hui tant que tu ne l'actives pas

## 🚀 Déploiement en 3 phases

### Phase 0 — Build et image fraîche (déjà en cours)

Le push GitHub a déclenché un build automatique. Vérifie l'état :

👉 https://github.com/larabestrais/Kronos/actions

Quand tu vois ✅ vert sur le commit "feat(deploy): add --with-learning flag", l'image est prête.

### Phase 1 — Observation (semaine 1)

**But** : laisser le bot collecter des stats pendant 7 jours sans rien modifier. Tu reçois le récap Telegram chaque soir à 22h pour valider la qualité des recommandations.

#### Sur UGOS Pro Docker

1. Va sur le projet `kronos-bot-ig` (ou ton projet actuel)
2. Onglet **Configuration Compose** → **modifie l'image** pour forcer le pull frais :

   Remplace cette ligne :
   ```yaml
   image: ghcr.io/larabestrais/kronos-trading-bot:9af252350e61e3b3d2a6448ae525ef4f8acd14b5
   ```

   Par le SHA du nouveau commit (vérifie avec `git log --oneline -1` sur le repo, ou copie-le de ce guide une fois le build vert) :
   ```yaml
   image: ghcr.io/larabestrais/kronos-trading-bot:<NOUVEAU_SHA>
   ```

   Tu peux aussi simplement utiliser `:latest` — l'image fraîche sera pull tant que UGOS pull bien :
   ```yaml
   image: ghcr.io/larabestrais/kronos-trading-bot:latest
   ```

3. **Ajoute ces 2 variables d'environnement** dans le `environment:` block :
   ```yaml
       - KRONOS_LEARNING_ENABLED=true
       - KRONOS_LEARNING_DRY_RUN=true
   ```

4. **Important : assure-toi que `TELEGRAM_CHAT_ID` est rempli** (sinon pas de récap quotidien). Si tu ne l'as pas, parle à `@userinfobot` sur Telegram.

5. Sauvegarde, **Stop**, **Activer** (force le re-pull).

#### Vérification

Dans les logs après démarrage, tu dois voir :
```
[Learning] Module activé, state: /app/data/learning_state.json
[Learning] Mode DRY-RUN actif, aucun ajustement appliqué
[Learning] Scheduler démarré (22h00 daily)
```

Sur le dashboard `http://192.168.76.177:5050` (login `kronos` / `Momo694994!`) tu vois maintenant le panel **🧠 Apprentissage Adaptatif** en bas avec :
- Le régime actuel (TREND_UP / TREND_DOWN / RANGING / HIGH_VOLATILITY)
- Les paramètres par symbole
- L'historique des ajustements
- Les validations en attente

#### Récap Telegram à 22h00

Chaque soir à 22h00 (Bruxelles), tu reçois un message Telegram :
```
🌙 KRONOS — Bilan quotidien

📊 Performance du jour : 4 trades (3W/1L), PnL +2.34€
📈 Performance 30j : Sharpe 1.42 ✨, Win rate 58%
🤖 Ajustements auto (DRY-RUN — non appliqués) :
  • AAPL : confidence 0.60 → 0.58
🔔 Validations requises : ...
```

**Pendant 7 jours**, tu lis ces récaps et tu vérifies :
- Les régimes détectés correspondent à ce que tu vois sur le marché ?
- Les ajustements proposés sont-ils sensés ?
- Y a-t-il des propositions absurdes ?

Si tout te semble cohérent → Phase 2.
Si ça déraille → reste en DRY-RUN ou désactive (`KRONOS_LEARNING_ENABLED=false`).

### Phase 2 — Activation auto (semaine 2+)

**But** : laisser le bot s'auto-ajuster sur les paramètres mineurs. Les changements majeurs (levier, SL/TP global) restent sous ta validation.

1. Sur UGOS, **modifie une seule variable** :
   ```yaml
       - KRONOS_LEARNING_DRY_RUN=false
   ```

2. **Stop / Activer** le projet.

À partir de ce moment :
- Le bot **applique automatiquement** les ajustements mineurs (confidence_min, buy_threshold, weight)
- Les ajustements majeurs apparaissent dans le récap Telegram avec des **boutons inline** ✅ Valider / ❌ Refuser / ⏸️ Plus tard
- Tu peux aussi gérer les validations depuis le dashboard `/learning`

### Phase 3 — (optionnel, mois 2+)

Quand tu auras 200+ trades et que la phase 2 est stable, on pourra évaluer :
- Ajout du **Bandit Thompson Sampling** par-dessus les règles statistiques
- Fine-tuning du modèle Kronos sur tes données spécifiques

Ça fera l'objet d'un nouveau cycle de design.

## 🛟 Sécurité — comment revenir en arrière

À tout moment, tu peux :

### Désactiver complètement le learning
```yaml
- KRONOS_LEARNING_ENABLED=false
```
→ Stop / Activer. Le bot revient à la config statique du compose. Aucun ajustement n'est appliqué.

### Reset les paramètres adaptatifs (sans désactiver)
Va sur dashboard → panel Apprentissage → bouton **🔄 Reset paramètres à la config initiale**.

Ou en API directe :
```bash
curl -u kronos:Momo694994! -X POST http://192.168.76.177:5050/api/learning/reset
```

### Repasser en DRY-RUN
```yaml
- KRONOS_LEARNING_DRY_RUN=true
```
→ Le bot continue à analyser et envoyer les recos Telegram, mais n'applique plus rien.

## 📚 Référence rapide des variables

| Variable | Défaut | Description |
|---|---|---|
| `KRONOS_LEARNING_ENABLED` | `false` | Active/désactive le module entier |
| `KRONOS_LEARNING_DRY_RUN` | `true` | Mode observation (calcule sans appliquer) |
| `LEARNING_STATE_PATH` | `/app/data/learning_state.json` | Chemin du fichier d'état |

## 📞 En cas de problème

1. **Logs du conteneur** : UGOS → kronos-bot-ig → Journaux → cherche `[Learning]`
2. **État du module** : `curl -u kronos:Momo694994! http://192.168.76.177:5050/api/learning/state | jq`
3. **Tests unitaires** (pour debug en local) :
   ```bash
   cd ~/Desktop/Claude/kronos-trading-bot
   source venv/bin/activate
   python -m pytest tests/learning/ -v
   ```
4. **Spec et plan** :
   - Spec : `docs/superpowers/specs/2026-05-08-kronos-adaptive-learning-design.md`
   - Plan : `docs/superpowers/plans/2026-05-08-kronos-adaptive-learning.md`

---

**Bon learning ! 🧠🚀**

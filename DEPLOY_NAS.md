# Déploiement sur NAS UGREEN (UGOS Pro)

Guide pas-à-pas pour faire tourner Kronos Trading Bot 24/7 sur ton NAS UGREEN.

## Prérequis

- NAS UGREEN avec UGOS Pro
- App **Docker** activée (Centre d'applications → installer "Docker")
- App **Tailscale** ou accès SSH (pour accès distant — voir étape 5)
- ~2 Go RAM dispo, 2 Go d'espace

## Architecture

```
NAS UGREEN
├── /volume1/docker/kronos-bot/    # le code (uploadé via SMB ou interface)
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── .env                        # tes credentials
│   └── data/                       # portfolio_state.json (persistant)
└── volume Docker
    └── kronos-models               # cache modèles HuggingFace (auto)
```

---

## Étape 1 — Activer Docker sur le NAS

1. Ouvre l'interface UGOS Pro dans ton navigateur (http://IP-DU-NAS:9999 ou via UGREEN NAS app)
2. **Centre d'applications** → cherche "Docker" → **Installer**
3. Lance Docker une fois installé
4. Optionnel : activer aussi **Portainer** (UI plus pratique pour Docker)

---

## Étape 2 — Uploader le code

**Option A — SMB depuis ton Mac** (le plus simple) :

1. Sur ton Mac : Finder → `Cmd+K` → `smb://IP-DU-NAS`
2. Connecte-toi avec ton compte UGREEN
3. Va dans le partage `docker` (ou `volume1` selon ta config)
4. Crée un dossier `kronos-bot`
5. Glisse-dépose tout le contenu de `/Users/redesign/Desktop/Claude/kronos-trading-bot/` dedans
   - **NE PAS copier** : `venv/`, `.git/`, `__pycache__/` (gros et inutile)

**Option B — SCP en ligne de commande** (plus propre) :

```bash
cd /Users/redesign/Desktop/Claude/kronos-trading-bot
rsync -av --exclude='venv' --exclude='.git' --exclude='__pycache__' \
  ./ admin@IP-DU-NAS:/volume1/docker/kronos-bot/
```

---

## Étape 3 — Configurer le `.env` sur le NAS

Sur le NAS, édite `/volume1/docker/kronos-bot/.env` (via File Station ou SSH) :

```env
DASHBOARD_USER=kronos
DASHBOARD_PASSWORD=YKvqk7zhlA4_6skujYwEhQ
```

⚠️ Tu peux changer le mot de passe — note-le bien quelque part.

---

## Étape 4 — Lancer le container

### Via UGOS Pro Docker UI (recommandé)

1. Ouvre **Docker** dans UGOS Pro
2. Onglet **Compose** (ou "Stack" selon version)
3. **Créer** → nomme la stack `kronos-bot`
4. Indique le chemin : `/volume1/docker/kronos-bot/docker-compose.yml`
5. **Construire et lancer**
6. La première fois ça prend **5-10 min** (téléchargement de PyTorch + Kronos)

### Via SSH (si tu préfères)

```bash
ssh admin@IP-DU-NAS
cd /volume1/docker/kronos-bot/
docker compose up -d --build

# Suivre les logs
docker compose logs -f kronos-bot
```

---

## Étape 5 — Accès distant via Tailscale

### Sur le NAS

1. **Centre d'applications** UGOS Pro → installer **Tailscale**
2. Lance Tailscale → clique sur le lien d'authentification → connecte-toi avec le **même compte** que sur ton iPhone
3. Note l'IP Tailscale du NAS (affichée dans l'interface, format `100.x.x.x`)

### Alternative : exposer via le LAN seulement

Si tu utilises seulement chez toi :
- L'IP locale du NAS suffit : `http://IP-LAN-NAS:5050`

---

## Étape 6 — Tester

Sur ton téléphone (Tailscale activé) ou portable :

```
http://IP-TAILSCALE-DU-NAS:5050
```

→ Tu obtiens le prompt d'auth :
- User : `kronos`
- Password : (celui dans ton `.env`)

→ Le dashboard Kronos s'affiche ✨

---

## Maintenance

### Voir les logs

```bash
docker compose logs -f kronos-bot
```

ou via Docker UGOS Pro → container `kronos-bot` → **Logs**.

### Redémarrer

```bash
docker compose restart kronos-bot
```

### Mettre à jour le code

1. Re-upload les fichiers modifiés
2. `docker compose up -d --build` → ça reconstruit l'image et relance

### Arrêter complètement

```bash
docker compose down
```

(les données dans `./data/` et le cache modèles sont préservés)

---

## Performance attendue

Sur un NAS UGREEN typique (Intel N100 ou ARM Cortex-A55) :

| Modèle Kronos | RAM | Temps prédiction (CPU) |
|---|---|---|
| Kronos-mini (4M) | ~500 MB | ~2 sec |
| Kronos-small (24M) | ~1.5 GB | ~5-10 sec |
| Kronos-base (102M) | ~3 GB | ~30-60 sec |

Pour du daily/hourly trading, **Kronos-small** est largement suffisant.

---

## Dépannage

**Le container redémarre en boucle**
→ Regarde les logs (`docker compose logs kronos-bot`). Souvent c'est le `.env` mal formé ou les dépendances Python.

**Pas d'accès au dashboard depuis le téléphone**
→ Vérifie que Tailscale est activé partout (sur le téléphone ET sur le NAS — interrupteur ON dans les deux apps).

**Le bot consomme trop de RAM**
→ Réduis `pred_len` ou `sample_count` dans `bot/config.py`. Ou passe à `Kronos-mini`.

**Erreur "no module named torch"**
→ Le build Docker a échoué. Reconstruit : `docker compose build --no-cache && docker compose up -d`.

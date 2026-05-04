#!/bin/bash
set -e

echo "=== Installation du Kronos Trading Bot ==="

# Vérifier Python 3.10+
if ! command -v python3 &> /dev/null; then
    echo "Python3 non trouvé. Installation via Homebrew..."
    brew install python@3.12
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo $PY_VERSION | cut -d. -f1)
PY_MINOR=$(echo $PY_VERSION | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    echo "Python $PY_VERSION détecté. Version 3.10+ requise."
    echo "Installation de Python 3.12 via Homebrew..."
    brew install python@3.12
    PYTHON=python3.12
else
    PYTHON=python3
fi

echo "Utilisation de $($PYTHON --version)"

# Créer l'environnement virtuel
if [ ! -d "venv" ]; then
    echo "Création de l'environnement virtuel..."
    $PYTHON -m venv venv
fi

source venv/bin/activate
echo "Environnement activé: $(which python)"

# Installer les dépendances
echo "Installation des dépendances..."
pip install --upgrade pip
pip install -r requirements-bot.txt

echo ""
echo "=== Installation terminée ==="
echo ""
echo "Pour activer l'environnement:"
echo "  source venv/bin/activate"
echo ""
echo "Pour lancer le bot (un cycle):"
echo "  python run_bot.py --once --symbols AAPL MSFT"
echo ""
echo "Pour lancer le bot en continu:"
echo "  python run_bot.py --symbols AAPL MSFT --interval 300"
echo ""
echo "Pour le backtest:"
echo "  python backtest.py --symbol AAPL --timeframe 1d"

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

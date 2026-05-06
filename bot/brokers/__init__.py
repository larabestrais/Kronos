"""
Brokers — interfaces vers les courtiers/data providers réels (IG Markets, etc.)
Le bot reste agnostique : il consomme un DataFetcher avec une API stable.
"""
from .ig import IGBroker, IGBrokerError
from .symbol_map import SYMBOL_TO_EPIC, EPIC_TO_SYMBOL, to_epic, from_epic

__all__ = [
    "IGBroker",
    "IGBrokerError",
    "SYMBOL_TO_EPIC",
    "EPIC_TO_SYMBOL",
    "to_epic",
    "from_epic",
]

"""
Mapping symboles tickers (style yfinance) -> epics IG Markets.

Format epic IG :
- Actions cash US      : UC.D.<TICKER>.CASH.IP
- Actions cash EU      : KC.D.<TICKER>.CASH.IP   (varie selon place)
- Indices cash         : IX.D.<INDEX>.IFE.IP
- Crypto CFD           : CS.D.<PAIR>.CFD.IP
- Forex spot           : CS.D.<PAIR>.MINI.IP

⚠️ Les epics peuvent VARIER entre compte démo et compte réel, et entre régions
géographiques. Si un epic ne fonctionne pas, le broker IG fait un fallback
automatique via `search_markets()` au runtime.

Mise à jour : 2026-05
"""

# Tickers US les plus communs (vérifié sur compte démo IG.com EU)
SYMBOL_TO_EPIC: dict[str, str] = {
    # --- Tech US (cash CFD) ---
    "AAPL":  "UC.D.AAPL.CASH.IP",
    "MSFT":  "UC.D.MSFT.CASH.IP",
    "GOOGL": "UC.D.GOOGL.CASH.IP",
    "GOOG":  "UC.D.GOOG.CASH.IP",
    "AMZN":  "UC.D.AMZN.CASH.IP",
    "META":  "UC.D.META.CASH.IP",
    "NVDA":  "UC.D.NVDA.CASH.IP",
    "TSLA":  "UC.D.TSLA.CASH.IP",
    "AMD":   "UC.D.AMD.CASH.IP",
    "NFLX":  "UC.D.NFLX.CASH.IP",
    "INTC":  "UC.D.INTC.CASH.IP",
    "ORCL":  "UC.D.ORCL.CASH.IP",
    "CRM":   "UC.D.CRM.CASH.IP",
    "ADBE":  "UC.D.ADBE.CASH.IP",

    # --- Indices US (cash) ---
    "SPX":   "IX.D.SPTRD.IFE.IP",
    "NDX":   "IX.D.NASDAQ.IFE.IP",
    "DJI":   "IX.D.DOW.IFE.IP",
    "RUT":   "IX.D.RUSSELL.IFE.IP",
    "VIX":   "IX.D.VIX.MONTH1.IP",

    # --- Crypto CFD ---
    "BTC-USD":  "CS.D.BITCOIN.CFD.IP",
    "ETH-USD":  "CS.D.ETHUSD.CFD.IP",
    "SOL-USD":  "CS.D.SOLUSD.CFD.IP",
    "DOGE-USD": "CS.D.DOGEUSD.CFD.IP",

    # --- Forex (mini, format spot) ---
    "EURUSD=X": "CS.D.EURUSD.MINI.IP",
    "GBPUSD=X": "CS.D.GBPUSD.MINI.IP",
    "USDJPY=X": "CS.D.USDJPY.MINI.IP",

    # --- Commodités ---
    "GC=F": "CS.D.CFDGOLD.CFDGC.IP",  # Gold
    "SI=F": "CS.D.CFDSILVER.CFDSI.IP",  # Silver
    "CL=F": "CC.D.CL.UNC.IP",  # WTI Crude Oil
}

EPIC_TO_SYMBOL: dict[str, str] = {v: k for k, v in SYMBOL_TO_EPIC.items()}


def to_epic(symbol: str) -> str:
    """Retourne l'epic IG pour un symbole. Fallback générique pour actions US."""
    if symbol in SYMBOL_TO_EPIC:
        return SYMBOL_TO_EPIC[symbol]
    # Fallback : action US cash CFD (à valider via search_markets si échoue)
    return f"UC.D.{symbol}.CASH.IP"


def from_epic(epic: str) -> str:
    """Retourne le symbole pour un epic IG. Fallback : retourne l'epic tel quel."""
    return EPIC_TO_SYMBOL.get(epic, epic)

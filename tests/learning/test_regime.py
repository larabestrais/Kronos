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

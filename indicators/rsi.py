import pandas as pd
import numpy as np
from typing import Optional

class RSI:
    
    def __init__(self, period: int = 14, overbought: int = 70, oversold: int = 30):
        self.period = period
        self.overbought = overbought
        self.oversold = oversold
        self._rsi_cache: Optional[pd.Series] = None
        self._last_hash: Optional[int] = None

    def _calculate_rsi_series(self, df: pd.DataFrame) -> pd.Series:
        """
        Kalkulator inti RSI.
        Optimized: Caching aman untuk Live Trade (Hash Index + Close).
        """
        if len(df) < self.period + 1:
            return pd.Series(dtype=float)
            
        # [FIX CACHING] Include Close price biar reaktif
        current_hash = hash((df.index[-1], df['close'].iloc[-1]))
        
        if current_hash == self._last_hash and self._rsi_cache is not None:
            return self._rsi_cache
        
        # --- Optimized Calculation (Vectorized) ---
        delta = df['close'].diff()
        
        # Pisahkan gain/loss tanpa iterasi
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        
        # Calculate Exponential Moving Average (Wilder's Smoothing)
        avg_gain = gain.ewm(alpha=1/self.period, min_periods=self.period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/self.period, min_periods=self.period, adjust=False).mean()
        
        # Calculate RS
        rs = avg_gain / avg_loss.replace(0, 1e-9)
        rsi_series = 100 - (100 / (1 + rs))
        
        self._rsi_cache = rsi_series
        self._last_hash = current_hash
        
        return rsi_series

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """Nilai RSI bar terakhir."""
        rsi_series = self._calculate_rsi_series(df)
        if rsi_series.empty or pd.isna(rsi_series.iloc[-1]):
            return None
        return rsi_series.iloc[-1]

    def get_signal(self, df: pd.DataFrame) -> str:
        """Sinyal RSI (Reversal/Zone)."""
        rsi_series = self._calculate_rsi_series(df)
        if len(rsi_series) < 2: return "NEUTRAL"
        
        curr = rsi_series.iloc[-1]
        prev = rsi_series.iloc[-2]
        
        if pd.isna(curr) or pd.isna(prev): return "NEUTRAL"

        # Reversal Signals (Cross Keluar dari Extreme Zone)
        if prev < self.oversold and curr > self.oversold:
            return "BUY" # Bounce dari Oversold
        elif prev > self.overbought and curr < self.overbought:
            return "SELL" # Reversal dari Overbought
            
        # Zone State
        if curr < self.oversold: return "OVERSOLD"
        if curr > self.overbought: return "OVERBOUGHT"
        
        # Trend State
        if curr > 55: return "BULLISH"
        if curr < 45: return "BEARISH"
        
        return "NEUTRAL"

    def check_divergence(self, df: pd.DataFrame, lookback: int = 5) -> Optional[str]:
        """Deteksi Divergensi Sederhana."""
        rsi_series = self._calculate_rsi_series(df)
        if len(rsi_series) < lookback: return None
        
        prices = df['close'].iloc[-lookback:]
        rsis = rsi_series.iloc[-lookback:]
        
        p0, p1 = prices.iloc[0], prices.iloc[-1]
        r0, r1 = rsis.iloc[0], rsis.iloc[-1]
        
        # Bullish Divergence: Price Lower, RSI Higher
        if p1 < p0 and r1 > r0: return "BULLISH_DIVERGENCE"
        # Bearish Divergence: Price Higher, RSI Lower
        if p1 > p0 and r1 < r0: return "BEARISH_DIVERGENCE"
        
        return None

    def get_strength(self, df: pd.DataFrame) -> Optional[str]:
        """Indikator Kekuatan Tren."""
        val = self.calculate(df)
        if val is None: return None
        
        if val > 80: return "EXTREME_BULLISH"
        if val > 60: return "STRONG_BULLISH"
        if val > 50: return "BULLISH"
        if val < 20: return "EXTREME_BEARISH"
        if val < 40: return "STRONG_BEARISH"
        if val < 50: return "BEARISH"
        
        return "NEUTRAL"
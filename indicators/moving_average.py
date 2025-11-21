import pandas as pd
import numpy as np
from typing import Optional

class MovingAverage:
    
    def __init__(self, period: int = 20, shift: int = 0):
        self.period = period
        self.shift = shift
        self._ma_cache: Optional[pd.Series] = None
        self._last_hash_ma: Optional[int] = None
        self._ema_cache: Optional[pd.Series] = None
        self._last_hash_ema: Optional[int] = None

    def _calculate_ma_series(self, df: pd.DataFrame) -> pd.Series:
        """SMA Core Calculation (Optimized Caching)."""
        if len(df) < self.period:
            return pd.Series(dtype=float)
            
        # [FIX CACHING] Hash harus sensitif terhadap perubahan harga terakhir
        current_hash = hash((df.index[-1], df['close'].iloc[-1]))
        
        if current_hash == self._last_hash_ma and self._ma_cache is not None:
            return self._ma_cache
        
        ma_series = df['close'].rolling(window=self.period).mean()
        
        if self.shift > 0:
            ma_series = ma_series.shift(self.shift)
            
        self._ma_cache = ma_series
        self._last_hash_ma = current_hash
        return ma_series

    def _calculate_ema_series(self, df: pd.DataFrame) -> pd.Series:
        """EMA Core Calculation (Optimized Caching)."""
        if len(df) < self.period:
            return pd.Series(dtype=float)
            
        current_hash = hash((df.index[-1], df['close'].iloc[-1]))
        
        if current_hash == self._last_hash_ema and self._ema_cache is not None:
            return self._ema_cache
        
        ema_series = df['close'].ewm(span=self.period, adjust=False).mean()
        
        if self.shift > 0:
            ema_series = ema_series.shift(self.shift)
            
        self._ema_cache = ema_series
        self._last_hash_ema = current_hash
        return ema_series

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """SMA Value Bar Terakhir."""
        res = self._calculate_ma_series(df)
        if res.empty or pd.isna(res.iloc[-1]): return None
        return res.iloc[-1]
    
    def get_ema(self, df: pd.DataFrame) -> Optional[float]:
        """EMA Value Bar Terakhir."""
        res = self._calculate_ema_series(df)
        if res.empty or pd.isna(res.iloc[-1]): return None
        return res.iloc[-1]

    def get_signal(self, df: pd.DataFrame) -> str:
        """
        Sinyal Price Cross SMA.
        BUY: Harga tembus SMA dari bawah ke atas.
        SELL: Harga tembus SMA dari atas ke bawah.
        """
        ma_series = self._calculate_ma_series(df)
        if len(ma_series) < 2: return "NEUTRAL"
        
        curr_price = df['close'].iloc[-1]
        prev_price = df['close'].iloc[-2]
        curr_ma = ma_series.iloc[-1]
        prev_ma = ma_series.iloc[-2]
        
        if pd.isna(curr_ma) or pd.isna(prev_ma): return "NEUTRAL"

        # Crossover Logic
        if prev_price <= prev_ma and curr_price > curr_ma:
            return "BUY" # Breakout Atas
        elif prev_price >= prev_ma and curr_price < curr_ma:
            return "SELL" # Breakdown Bawah
            
        # Trending Logic (Follow the flow)
        if curr_price > curr_ma: return "BULLISH"
        if curr_price < curr_ma: return "BEARISH"
        
        return "NEUTRAL"
    
    def get_crossover_signal(self, df: pd.DataFrame, fast_period: int = 10, slow_period: int = 20) -> str:
        """Golden Cross / Death Cross (Fast SMA vs Slow SMA)."""
        if len(df) < slow_period + 2: return "NEUTRAL"
        
        # Hitung lokal (tidak di-cache karena parameternya dinamis)
        fast_ma = df['close'].rolling(window=fast_period).mean()
        slow_ma = df['close'].rolling(window=slow_period).mean()
        
        curr_fast = fast_ma.iloc[-1]
        prev_fast = fast_ma.iloc[-2]
        curr_slow = slow_ma.iloc[-1]
        prev_slow = slow_ma.iloc[-2]
        
        if pd.isna(curr_slow) or pd.isna(prev_slow): return "NEUTRAL"

        if prev_fast <= prev_slow and curr_fast > curr_slow:
            return "BUY" # Golden Cross
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            return "SELL" # Death Cross
            
        return "NEUTRAL"
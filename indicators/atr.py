import pandas as pd
import numpy as np
from typing import Tuple, Optional, Dict

class ATR:
    
    def __init__(self, period: int = 14):
        self.period = period
        # Cache variables
        self._atr_series_cache: Optional[pd.Series] = None
        self._last_hash: Optional[int] = None

    def _calculate_atr_series(self, df: pd.DataFrame) -> pd.Series:
        """
        Kalkulator inti ATR.
        Optimized: Menggunakan NumPy vectorization & Caching yang aman untuk Live Trade.
        """
        if len(df) < self.period + 1:
            return pd.Series(dtype=float)
            
        # [FIX CACHING] Hash harus gabungan Waktu + Harga Close terakhir
        # Agar jika harga bergerak di candle yang sama, nilai ATR terupdate.
        current_hash = hash((df.index[-1], df['close'].iloc[-1]))
        
        if current_hash == self._last_hash and self._atr_series_cache is not None:
            return self._atr_series_cache
        
        # --- Optimized Calculation (Tanpa df.copy full) ---
        high = df['high']
        low = df['low']
        close_prev = df['close'].shift(1)
        
        # Hitung TR menggunakan Vectorized Operations (Lebih cepat dari apply/copy)
        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()
        
        # Ambil max dari 3 komponen TR
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Calculate ATR using EMA (Wilder's Smoothing approximation)
        atr_series = true_range.ewm(span=self.period, adjust=False).mean()
        
        # Update Cache
        self._atr_series_cache = atr_series
        self._last_hash = current_hash
        
        return atr_series

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """Mengembalikan nilai ATR bar terakhir."""
        atr_series = self._calculate_atr_series(df)
        if atr_series.empty or pd.isna(atr_series.iloc[-1]):
            return None
        return atr_series.iloc[-1]

    def get_volatility_state(self, df: pd.DataFrame, lookback: int = 20, high_vol_multiplier: float = 1.5, low_vol_multiplier: float = 0.8) -> str:
        """Mendapatkan status volatilitas (Ratio ATR Current vs Avg)."""
        atr_series = self._calculate_atr_series(df)
        
        if len(atr_series) < lookback + 1:
            return "UNKNOWN"
        
        current_atr = atr_series.iloc[-1]
        # Rata-rata historis (tidak termasuk bar sekarang)
        avg_atr = atr_series.iloc[-lookback-1:-1].mean()
        
        if pd.isna(current_atr) or pd.isna(avg_atr) or avg_atr == 0:
            return "NORMAL_VOLATILITY"

        ratio = current_atr / avg_atr
        
        if ratio > high_vol_multiplier:
            return "HIGH_VOLATILITY"
        elif ratio < low_vol_multiplier:
            return "LOW_VOLATILITY"
        
        return "NORMAL_VOLATILITY"

    def get_atr_percentile(self, df: pd.DataFrame, lookback: int = 100) -> Optional[float]:
        """Ranking volatilitas (0-100)."""
        atr_series = self._calculate_atr_series(df)
        
        if len(atr_series) < lookback:
            return None
        
        recent_atr = atr_series.iloc[-lookback:]
        current_atr = atr_series.iloc[-1]
        
        if pd.isna(current_atr): return None

        percentile = (recent_atr < current_atr).sum() / len(recent_atr) * 100
        return percentile

    def detect_volatility_breakout(self, df: pd.DataFrame, lookback: int = 20, multiplier: float = 2.0) -> Optional[str]:
        """Mendeteksi ledakan volatilitas ekstrem."""
        atr_series = self._calculate_atr_series(df)
        if len(atr_series) < lookback + 1: return None
        
        current_atr = atr_series.iloc[-1]
        avg_atr = atr_series.iloc[-lookback-1:-1].mean()
        
        if avg_atr > 0 and current_atr > (avg_atr * multiplier):
            return "VOLATILITY_BREAKOUT"
        return None

    def get_stop_distance(self, df: pd.DataFrame, multiplier: float = 1.5) -> Optional[float]:
        """Helper hitung SL distance."""
        val = self.calculate(df)
        return val * multiplier if val else None

    def get_atr_bands(self, df: pd.DataFrame, ma_period: int = 20, multiplier: float = 2.0) -> Tuple[Optional[pd.Series], Optional[pd.Series], Optional[pd.Series]]:
        """Keltner Channel Helper."""
        atr_series = self._calculate_atr_series(df)
        if len(df) < ma_period or atr_series.empty:
            return None, None, None
            
        middle_band = df['close'].rolling(window=ma_period).mean()
        upper_band = middle_band + (atr_series * multiplier)
        lower_band = middle_band - (atr_series * multiplier)
        
        return middle_band, upper_band, lower_band
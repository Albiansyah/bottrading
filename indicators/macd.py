import pandas as pd
import numpy as np
from typing import Tuple, Optional, Dict

class MACD:
    
    def __init__(self, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self._macd_cache: Dict[str, pd.Series] = {}
        self._last_hash: Optional[int] = None

    def _calculate_macd_data(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """
        Kalkulator inti MACD.
        Optimized: Caching aman untuk Live Trade (Hash Index + Close).
        """
        if len(df) < self.slow_period:
            return {}

        # [FIX CACHING] Include Close price agar indikator reaktif saat candle jalan
        current_hash = hash((df.index[-1], df['close'].iloc[-1]))
        
        if current_hash == self._last_hash and self._macd_cache:
            return self._macd_cache
        
        # --- Optimized Calculation ---
        close = df['close']
        
        ema_fast = close.ewm(span=self.fast_period, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow_period, adjust=False).mean()
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.signal_period, adjust=False).mean()
        histogram = macd_line - signal_line
        
        # Calculate Slopes (Momentum Change)
        # Menggunakan diff() biasa sudah cukup cepat
        macd_slope = macd_line.diff()
        signal_slope = signal_line.diff()
        
        self._macd_cache = {
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram,
            'macd_slope': macd_slope,
            'signal_slope': signal_slope
        }
        self._last_hash = current_hash
        
        return self._macd_cache

    def calculate(self, df: pd.DataFrame) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        data = self._calculate_macd_data(df)
        if not data or pd.isna(data['macd'].iloc[-1]):
            return None, None, None
        return (data['macd'].iloc[-1], data['signal'].iloc[-1], data['histogram'].iloc[-1])

    def get_state(self, df: pd.DataFrame) -> str:
        """Status Tren MACD (Berdasarkan Histogram)."""
        data = self._calculate_macd_data(df)
        if not data: return "NEUTRAL"
            
        hist = data['histogram'].iloc[-1]
        if pd.isna(hist): return "NEUTRAL"
        
        if hist > 0: return "BULLISH"
        elif hist < 0: return "BEARISH"
        return "NEUTRAL"

    def check_crossover_signal(self, df: pd.DataFrame) -> str:
        """Crossover Sinyal (Line cross Signal)."""
        data = self._calculate_macd_data(df)
        if not data or len(df) < 2: return "NEUTRAL"
            
        curr_macd = data['macd'].iloc[-1]
        curr_sig = data['signal'].iloc[-1]
        prev_macd = data['macd'].iloc[-2]
        prev_sig = data['signal'].iloc[-2]
        
        if pd.isna(curr_macd) or pd.isna(prev_macd): return "NEUTRAL"

        if prev_macd <= prev_sig and curr_macd > curr_sig:
            return "BUY"
        elif prev_macd >= prev_sig and curr_macd < curr_sig:
            return "SELL"
            
        return "NEUTRAL"

    def get_histogram_momentum(self, df: pd.DataFrame) -> str:
        """Momentum Histogram (Mendeteksi pelemahan tren)."""
        data = self._calculate_macd_data(df)
        if not data or len(df) < 2: return "NEUTRAL"
            
        curr = data['histogram'].iloc[-1]
        prev = data['histogram'].iloc[-2]
        
        if pd.isna(curr) or pd.isna(prev): return "NEUTRAL"
        
        if curr > 0:
            return "ACCELERATING_BULLISH" if curr > prev else "DECELERATING_BULLISH"
        elif curr < 0:
            return "ACCELERATING_BEARISH" if curr < prev else "DECELERATING_BEARISH"
            
        return "NEUTRAL"

    def check_zero_line_cross(self, df: pd.DataFrame) -> Optional[str]:
        """MACD Line cross 0."""
        data = self._calculate_macd_data(df)
        if not data or len(df) < 2: return None
            
        curr = data['macd'].iloc[-1]
        prev = data['macd'].iloc[-2]
        
        if prev <= 0 and curr > 0: return "BULLISH_ZERO_CROSS"
        if prev >= 0 and curr < 0: return "BEARISH_ZERO_CROSS"
        return None

    def get_divergence(self, df: pd.DataFrame, lookback: int = 14) -> Optional[str]:
        """Deteksi Divergensi Sederhana (Price vs MACD Line)."""
        data = self._calculate_macd_data(df)
        if not data or len(df) < lookback: return None
        
        recent_price = df['close'].iloc[-lookback:]
        recent_macd = data['macd'].iloc[-lookback:]
        
        p_start, p_end = recent_price.iloc[0], recent_price.iloc[-1]
        m_start, m_end = recent_macd.iloc[0], recent_macd.iloc[-1]
        
        # Bullish Divergence: Price Lower Low, MACD Higher Low
        if p_end < p_start and m_end > m_start:
            return "BULLISH_DIVERGENCE"
            
        # Bearish Divergence: Price Higher High, MACD Lower High
        elif p_end > p_start and m_end < m_start:
            return "BEARISH_DIVERGENCE"
            
        return None

    def get_macd_slope(self, df: pd.DataFrame) -> Optional[float]:
        data = self._calculate_macd_data(df)
        return data['macd_slope'].iloc[-1] if data else None

    def get_signal_slope(self, df: pd.DataFrame) -> Optional[float]:
        data = self._calculate_macd_data(df)
        return data['signal_slope'].iloc[-1] if data else None

    def get_centerline_crosses(self, df: pd.DataFrame, lookback: int = 50) -> Optional[int]:
        """Menghitung seberapa sering market 'choppy' (bolak-balik garis 0)."""
        data = self._calculate_macd_data(df)
        if not data or len(df) < lookback: return None
        
        hist = data['histogram'].iloc[-lookback:]
        crosses = np.sum(np.diff(np.sign(hist)) != 0)
        return int(crosses)
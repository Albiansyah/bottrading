import pandas as pd
import numpy as np
from typing import Tuple, Optional, Dict

class Stochastic:
    
    def __init__(self, k_period: int = 14, d_period: int = 3, slowing: int = 3, overbought: int = 80, oversold: int = 20):
        self.k_period = k_period
        self.d_period = d_period
        self.slowing = slowing
        self.overbought = overbought
        self.oversold = oversold
        self._stoch_cache: Dict[str, pd.Series] = {}
        self._last_hash: Optional[int] = None

    def _calculate_stochastic_data(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """
        Kalkulator inti Stochastic.
        Optimized: Caching aman untuk Live Trade.
        """
        if len(df) < self.k_period:
            return {}

        # [FIX CACHING]
        current_hash = hash((df.index[-1], df['close'].iloc[-1]))
        
        if current_hash == self._last_hash and self._stoch_cache:
            return self._stoch_cache
        
        # --- Calculation ---
        low_min = df['low'].rolling(window=self.k_period).min()
        high_max = df['high'].rolling(window=self.k_period).max()
        
        # Raw %K
        denom = (high_max - low_min).replace(0, 1e-9)
        stoch_k_raw = 100 * ((df['close'] - low_min) / denom)
        
        # %K (Slow)
        stoch_k = stoch_k_raw.rolling(window=self.slowing).mean()
        
        # %D (Signal)
        stoch_d = stoch_k.rolling(window=self.d_period).mean()
        
        # Slopes
        k_slope = stoch_k.diff()
        d_slope = stoch_d.diff()
        
        self._stoch_cache = {
            'k': stoch_k,
            'd': stoch_d,
            'k_slope': k_slope,
            'd_slope': d_slope
        }
        self._last_hash = current_hash
        
        return self._stoch_cache

    def calculate(self, df: pd.DataFrame) -> Tuple[Optional[float], Optional[float]]:
        """Return (%K, %D) bar terakhir."""
        data = self._calculate_stochastic_data(df)
        if not data or pd.isna(data['k'].iloc[-1]):
            return None, None
        return (data['k'].iloc[-1], data['d'].iloc[-1])

    def get_signal(self, df: pd.DataFrame) -> str:
        """Sinyal Trading Stochastic."""
        data = self._calculate_stochastic_data(df)
        if not data or len(data['k']) < 2: return "NEUTRAL"
        
        curr_k = data['k'].iloc[-1]
        curr_d = data['d'].iloc[-1]
        prev_k = data['k'].iloc[-2]
        prev_d = data['d'].iloc[-2]
        
        if pd.isna(curr_k) or pd.isna(prev_k): return "NEUTRAL"

        # Bullish Cross di Oversold (Strong Buy)
        if curr_k < self.oversold and prev_k <= prev_d and curr_k > curr_d:
            return "BUY"
            
        # Bearish Cross di Overbought (Strong Sell)
        elif curr_k > self.overbought and prev_k >= prev_d and curr_k < curr_d:
            return "SELL"
            
        # General Crossovers
        if prev_k <= prev_d and curr_k > curr_d: return "BULLISH_CROSS"
        if prev_k >= prev_d and curr_k < curr_d: return "BEARISH_CROSS"
        
        # Zones
        if curr_k < self.oversold: return "OVERSOLD"
        if curr_k > self.overbought: return "OVERBOUGHT"
        
        return "NEUTRAL"

    def check_divergence(self, df: pd.DataFrame, lookback: int = 5) -> Optional[str]:
        """Divergensi Price vs Stochastic %K."""
        data = self._calculate_stochastic_data(df)
        if not data or len(df) < lookback: return None
        
        prices = df['close'].iloc[-lookback:]
        stochs = data['k'].iloc[-lookback:]
        
        p0, p1 = prices.iloc[0], prices.iloc[-1]
        s0, s1 = stochs.iloc[0], stochs.iloc[-1]
        
        # Bullish Div: Price Lower, Stoch Higher
        if p1 < p0 and s1 > s0: return "BULLISH_DIVERGENCE"
        # Bearish Div: Price Higher, Stoch Lower
        if p1 > p0 and s1 < s0: return "BEARISH_DIVERGENCE"
        
        return None

    def is_oversold_bounce(self, df: pd.DataFrame) -> bool:
        """Deteksi pantulan cepat di area oversold (V-shape)."""
        data = self._calculate_stochastic_data(df)
        if not data or len(data['k']) < 3: return False
        
        k = data['k'].iloc[-3:].values
        # Pola V: Turun ke oversold -> Naik
        if k[0] < self.oversold and k[1] < k[0] and k[2] > k[1]:
            return True
        return False

    def is_overbought_reversal(self, df: pd.DataFrame) -> bool:
        """Deteksi reversal cepat di area overbought (Inverted V)."""
        data = self._calculate_stochastic_data(df)
        if not data or len(data['k']) < 3: return False
        
        k = data['k'].iloc[-3:].values
        # Pola A: Naik ke overbought -> Turun
        if k[0] > self.overbought and k[1] > k[0] and k[2] < k[1]:
            return True
        return False
        
    def get_k_slope(self, df: pd.DataFrame) -> Optional[float]:
        data = self._calculate_stochastic_data(df)
        return data['k_slope'].iloc[-1] if data else None

    def get_d_slope(self, df: pd.DataFrame) -> Optional[float]:
        data = self._calculate_stochastic_data(df)
        return data['d_slope'].iloc[-1] if data else None
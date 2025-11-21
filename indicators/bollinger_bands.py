import pandas as pd
import numpy as np
from typing import Tuple, Optional, Dict

class BollingerBands:
    
    def __init__(self, period: int = 20, deviation: int = 2):
        self.period = period
        self.deviation = deviation
        self._bands_cache: Dict[str, pd.Series] = {}
        self._last_hash: Optional[int] = None

    def _calculate_bands_data(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """
        Kalkulator inti BB.
        Optimized: Caching aman untuk Live Trade (Hash Index + Close).
        """
        if len(df) < self.period:
            return {}

        # [FIX CACHING] Include Close price untuk update real-time di bar yang sama
        current_hash = hash((df.index[-1], df['close'].iloc[-1]))
        
        if current_hash == self._last_hash and self._bands_cache:
            return self._bands_cache
        
        # Kalkulasi efisien: Panggil rolling object sekali
        rolling_obj = df['close'].rolling(window=self.period)
        middle_band = rolling_obj.mean()
        std_dev = rolling_obj.std()
        
        upper_band = middle_band + (std_dev * self.deviation)
        lower_band = middle_band - (std_dev * self.deviation)
        
        # Safe division
        safe_middle = middle_band.replace(0, 1e-9)
        bb_width = (upper_band - lower_band) / safe_middle
        
        safe_range = (upper_band - lower_band).replace(0, 1e-9)
        percent_b = ((df['close'] - lower_band) / safe_range) * 100
        
        self._bands_cache = {
            'middle': middle_band,
            'upper': upper_band,
            'lower': lower_band,
            'width': bb_width,
            'percent_b': percent_b
        }
        self._last_hash = current_hash
        
        return self._bands_cache

    def calculate(self, df: pd.DataFrame) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        data = self._calculate_bands_data(df)
        if not data or pd.isna(data['upper'].iloc[-1]):
            return None, None, None
        return (data['upper'].iloc[-1], data['middle'].iloc[-1], data['lower'].iloc[-1])

    def get_price_position_state(self, df: pd.DataFrame) -> str:
        """Menentukan posisi harga relatif terhadap band."""
        data = self._calculate_bands_data(df)
        if not data: return "NEUTRAL"
            
        close = df['close'].iloc[-1]
        upper = data['upper'].iloc[-1]
        lower = data['lower'].iloc[-1]
        middle = data['middle'].iloc[-1]
        
        if pd.isna(close) or pd.isna(upper): return "NEUTRAL"
        
        if close > upper: return "OVERBOUGHT"
        elif close < lower: return "OVERSOLD"
        elif close > middle: return "BULLISH"
        elif close < middle: return "BEARISH"
        return "NEUTRAL"

    def check_bounce_signal(self, df: pd.DataFrame) -> str:
        """
        Mendeteksi pantulan (Reversal) dari band luar.
        Cocok untuk mode SNIPER.
        """
        data = self._calculate_bands_data(df)
        if not data or len(df) < 2: return "NEUTRAL"
            
        curr_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        
        curr_upper = data['upper'].iloc[-1]
        curr_lower = data['lower'].iloc[-1]
        prev_upper = data['upper'].iloc[-2]
        prev_lower = data['lower'].iloc[-2]
        
        # Buy: Kemarin di bawah Lower, Sekarang tutup di dalam (di atas Lower)
        if prev_close <= prev_lower and curr_close > curr_lower:
            return "BUY"
        
        # Sell: Kemarin di atas Upper, Sekarang tutup di dalam (di bawah Upper)
        if prev_close >= prev_upper and curr_close < curr_upper:
            return "SELL"
            
        return "NEUTRAL"

    def get_squeeze(self, df: pd.DataFrame, lookback: int = 20, squeeze_threshold: float = 0.6, expansion_threshold: float = 1.5) -> Optional[str]:
        """Mendeteksi Squeeze (persiapan meledak) atau Expansion (sedang meledak)."""
        data = self._calculate_bands_data(df)
        if not data or len(data['width']) < lookback: return None
            
        current = data['width'].iloc[-1]
        # Bandingkan dengan rata-rata lebar band 20 candle terakhir
        avg_width = data['width'].iloc[-lookback:].mean()
        
        if avg_width == 0: return None
        
        if current < (avg_width * squeeze_threshold): return "SQUEEZE"
        if current > (avg_width * expansion_threshold): return "EXPANSION"
        return None

    def get_percent_b(self, df: pd.DataFrame) -> Optional[float]:
        data = self._calculate_bands_data(df)
        return data['percent_b'].iloc[-1] if data else None

    def check_breakout(self, df: pd.DataFrame) -> Optional[str]:
        """Breakout: Close candle tembus keluar band."""
        data = self._calculate_bands_data(df)
        if not data or len(df) < 2: return None
        
        curr_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        upper = data['upper'].iloc[-1]
        lower = data['lower'].iloc[-1]
        prev_upper = data['upper'].iloc[-2]
        prev_lower = data['lower'].iloc[-2]
        
        # Bullish Breakout: Candle sebelumnya di dalam, sekarang close di luar atas
        if prev_close <= prev_upper and curr_close > upper:
            return "BULLISH_BREAKOUT"
            
        # Bearish Breakout: Candle sebelumnya di dalam, sekarang close di luar bawah
        elif prev_close >= prev_lower and curr_close < lower:
            return "BEARISH_BREAKOUT"
            
        return None

    def is_walking_the_band(self, df: pd.DataFrame, lookback: int = 3) -> Optional[str]:
        """
        Mendeteksi trend kuat dimana harga 'menempel' di band.
        Berguna untuk mode BREAKOUT/TREND.
        """
        data = self._calculate_bands_data(df)
        if not data or len(df) < lookback: return None
        
        recent_closes = df['close'].iloc[-lookback:]
        recent_uppers = data['upper'].iloc[-lookback:]
        recent_lowers = data['lower'].iloc[-lookback:]
        
        # Toleransi 0.5% dari band
        if all(recent_closes >= (recent_uppers * 0.995)):
            return "WALKING_UPPER_BAND" # Super Bullish
            
        if all(recent_closes <= (recent_lowers * 1.005)):
            return "WALKING_LOWER_BAND" # Super Bearish
            
        return None
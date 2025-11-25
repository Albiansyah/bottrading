import pandas as pd
import numpy as np
from typing import Dict, Optional, Any

class FibonacciRetracement:
    
    def __init__(self, lookback: int = 100, min_swing_pct: float = 0.002):
        """
        Args:
            lookback: Jumlah candle ke belakang untuk mencari swing high/low.
            min_swing_pct: Minimum persentase jarak High-Low agar dianggap valid (0.002 = 0.2%).
        """
        self.lookback = lookback
        self.min_swing_pct = min_swing_pct

    def calculate_levels(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Menghitung level Fibonacci berdasarkan Swing High dan Swing Low terakhir.
        Menggunakan validasi size dan arah tren.
        """
        # 1. Validasi Data Dasar
        if df is None or len(df) < self.lookback:
            return {}
        
        # Validasi Kolom (Dipindah ke atas untuk efisiensi)
        if 'high' not in df.columns or 'low' not in df.columns:
            return {}

        # Ambil slice data terakhir
        recent_data = df.iloc[-self.lookback:]
        
        # 2. Cari Swing High & Swing Low (Global Extrema di window lookback)
        max_val = recent_data['high'].max()
        min_val = recent_data['low'].min()
        
        idx_max = recent_data['high'].idxmax()
        idx_min = recent_data['low'].idxmin()
        
        diff = max_val - min_val
        
        # 3. Validasi Ukuran Swing (Filter Noise & Division by Zero)
        # [FIX] Handle Diff 0 (Flat Market) atau Min Val 0
        if diff == 0 or min_val == 0:
            return {}
            
        if (diff / min_val) < self.min_swing_pct:
            return {} # Swing terlalu kecil/flat, return kosong.

        levels = {}
        
        # 4. Tentukan Arah Swing (Impuls)
        is_uptrend_swing = idx_min < idx_max

        if is_uptrend_swing:
            # === UPTREND IMPULSE (Low -> High) ===
            # Tarik Fib dari Low (100%) ke High (0%) untuk ukur KOREKSI TURUN.
            levels['trend'] = 'UP'
            levels['swing_high'] = max_val
            levels['swing_low'] = min_val
            levels['time_high'] = idx_max
            levels['time_low'] = idx_min
            
            # Retracement Levels
            levels['0.0'] = max_val
            levels['0.236'] = max_val - (0.236 * diff)
            levels['0.382'] = max_val - (0.382 * diff)
            levels['0.5'] = max_val - (0.5 * diff)
            levels['0.618'] = max_val - (0.618 * diff) # Golden Ratio
            levels['0.786'] = max_val - (0.786 * diff)
            levels['1.0'] = min_val
            
            # Extension Levels
            levels['1.272'] = max_val + (0.272 * diff)
            levels['1.414'] = max_val + (0.414 * diff)
            levels['1.618'] = max_val + (0.618 * diff)
            levels['2.0'] = max_val + (1.0 * diff)
            levels['2.618'] = max_val + (1.618 * diff)
            
        else:
            # === DOWNTREND IMPULSE (High -> Low) ===
            # Tarik Fib dari High (100%) ke Low (0%) untuk ukur KOREKSI NAIK.
            levels['trend'] = 'DOWN'
            levels['swing_high'] = max_val
            levels['swing_low'] = min_val
            levels['time_high'] = idx_max
            levels['time_low'] = idx_min
            
            # Retracement Levels
            levels['0.0'] = min_val
            levels['0.236'] = min_val + (0.236 * diff)
            levels['0.382'] = min_val + (0.382 * diff)
            levels['0.5'] = min_val + (0.5 * diff)
            levels['0.618'] = min_val + (0.618 * diff) # Golden Ratio
            levels['0.786'] = min_val + (0.786 * diff)
            levels['1.0'] = max_val
            
            # Extension Levels
            levels['1.272'] = min_val - (0.272 * diff)
            levels['1.414'] = min_val - (0.414 * diff)
            levels['1.618'] = min_val - (0.618 * diff)
            levels['2.0'] = min_val - (1.0 * diff)
            levels['2.618'] = min_val - (1.618 * diff)
            
        return levels

    def get_current_zone(self, current_price: float, levels: Dict[str, Any]) -> str:
        """
        Menentukan posisi harga relatif terhadap Golden Zone (0.5 - 0.786).
        """
        if not levels: return "UNKNOWN"
        
        trend = levels.get('trend')
        fib_05 = levels.get('0.5')
        fib_786 = levels.get('0.786')
        
        # Safety check
        if fib_05 is None or fib_786 is None: return "UNKNOWN"
        
        if trend == 'UP':
            # UPTREND: Diskon ada di bawah harga High
            upper_bound = fib_05
            lower_bound = fib_786
            
            if current_price > upper_bound: return "ABOVE_ZONE" # Masih mahal
            elif current_price < lower_bound: return "BELOW_ZONE" # Jebol support
            else: return "IN_GOLDEN_ZONE" # Siap Buy
                
        elif trend == 'DOWN':
            # DOWNTREND: Diskon ada di atas harga Low
            lower_bound = fib_05
            upper_bound = fib_786
            
            if current_price < lower_bound: return "BELOW_ZONE" # Masih murah
            elif current_price > upper_bound: return "ABOVE_ZONE" # Jebol resistance
            else: return "IN_GOLDEN_ZONE" # Siap Sell
                
        return "UNKNOWN"
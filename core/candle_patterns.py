import pandas as pd
import numpy as np
from typing import Dict, Optional

class CandlePattern:
    
    def __init__(self, rvol_threshold: float = 1.5):
        # Thresholds configuration
        self.min_body_ratio = 0.3       # Rasio body minimal vs range
        self.pinbar_tail_ratio = 2.0    # Ekor harus minimal 2x body
        self.doji_threshold = 0.1       # Body < 10% dari range dianggap Doji
        self.rvol_threshold = rvol_threshold # Volume harus 1.5x rata-rata
        
        # Weight multiplier untuk scoring
        self.PATTERN_WEIGHT = {
            'BULLISH_ENGULFING': 1.5,
            'BEARISH_ENGULFING': 1.5,
            'MORNING_STAR': 1.4,
            'EVENING_STAR': 1.4,
            'BULLISH_PINBAR': 1.0,
            'BEARISH_PINBAR': 1.0,
            'BULLISH_MARUBOZU': 1.0,
            'BEARISH_MARUBOZU': 1.0,
            'THREE_WHITE_SOLDIERS': 1.3,
            'THREE_BLACK_CROWS': 1.3,
            'DRAGONFLY_DOJI': 0.6,
            'GRAVESTONE_DOJI': 0.6,
        }

    def analyze(self, df: pd.DataFrame, atr: float = 0.0, current_trend: str = "NEUTRAL") -> Dict:
        
        # 1. Validasi Data Dasar
        if df is None or len(df) < 25:
            return self._default_result(note="Insufficient data for pattern analysis")

        # [FIX ERROR] Deteksi nama kolom volume yang benar
        vol_col = 'volume' # Default dari MT5Connector kita
        if 'tick_volume' in df.columns:
            vol_col = 'tick_volume'
        elif 'volume' not in df.columns:
            # Jika tidak ada data volume sama sekali, set None
            vol_col = None

        c0 = df.iloc[-1]
        c1 = df.iloc[-2]
        c2 = df.iloc[-3]
        c3 = df.iloc[-4]
        
        range0 = c0['high'] - c0['low']
        body0 = abs(c0['close'] - c0['open'])
        
        if range0 == 0:
            return self._default_result(note="Flat candle (range 0)")

        # [FIX ERROR] Logic Volume yang Aman
        volume_multiplier = 1.0
        rvol = 1.0
        
        if vol_col:
            try:
                avg_vol = df[vol_col].iloc[-22:-2].mean()
                curr_vol = c0[vol_col]
                rvol = curr_vol / avg_vol if avg_vol > 0 else 1.0
                
                if rvol > 2.5:
                    volume_multiplier = 1.5
                elif rvol > self.rvol_threshold:
                    volume_multiplier = 1.2
            except Exception:
                rvol = 1.0 # Fallback jika kalkulasi gagal
                
        close_position = (c0['close'] - c0['low']) / range0
        body_ratio = body0 / range0
        
        noise_penalty = 1.0
        if atr > 0 and range0 < (atr * 0.3):
            noise_penalty = 0.5

        upper0 = c0['high'] - max(c0['close'], c0['open'])
        lower0 = min(c0['close'], c0['open']) - c0['low']
        
        weak_candle_penalty = 1.0
        if body_ratio < 0.2 and body_ratio > self.doji_threshold:
            weak_candle_penalty = 0.7
        
        patterns = []
        score = 0
        
        # --- DETEKSI POLA ---

        # 1. DOJI
        is_doji = body_ratio <= self.doji_threshold
        if is_doji:
            if lower0 > (range0 * 0.6):
                patterns.append("DRAGONFLY_DOJI")
                score += 2 if current_trend == "BEARISH" else 0
            elif upper0 > (range0 * 0.6):
                patterns.append("GRAVESTONE_DOJI")
                score -= 2 if current_trend == "BULLISH" else 0

        # 2. PINBAR
        if lower0 > (body0 * self.pinbar_tail_ratio) and upper0 < (range0 * 0.2):
            if close_position > 0.5:
                if current_trend != "BULLISH":
                    patterns.append("BULLISH_PINBAR")
                    score += 2
        
        if upper0 > (body0 * self.pinbar_tail_ratio) and lower0 < (range0 * 0.2):
            if close_position < 0.5:
                if current_trend != "BEARISH":
                    patterns.append("BEARISH_PINBAR")
                    score -= 2

        # 3. ENGULFING
        if (c1['close'] < c1['open']) and (c0['close'] > c0['open']):
            if c0['open'] <= c1['close'] and c0['close'] >= c1['open']:
                body1 = abs(c1['close'] - c1['open'])
                engulf_ratio = body0 / body1 if body1 > 0 else 1.0
                
                if engulf_ratio >= 1.2 and close_position > 0.75:
                    patterns.append("BULLISH_ENGULFING")
                    base_s = 3
                    if engulf_ratio >= 1.5: base_s += 1
                    base_s = int(base_s * volume_multiplier)
                    if current_trend == "BEARISH": base_s += 1
                    score += base_s

        if (c1['close'] > c1['open']) and (c0['close'] < c0['open']):
            if c0['open'] >= c1['close'] and c0['close'] <= c1['open']:
                body1 = abs(c1['close'] - c1['open'])
                engulf_ratio = body0 / body1 if body1 > 0 else 1.0
                
                if engulf_ratio >= 1.2 and close_position < 0.25:
                    patterns.append("BEARISH_ENGULFING")
                    base_s = 3
                    if engulf_ratio >= 1.5: base_s += 1
                    base_s = int(base_s * volume_multiplier)
                    if current_trend == "BULLISH": base_s += 1
                    score -= base_s

        # 4. INSIDE BAR
        is_inside = c0['high'] <= c1['high'] and c0['low'] >= c1['low']
        if is_inside:
            patterns.append("INSIDE_BAR")
            mother_range = c1['high'] - c1['low']
            if mother_range > 0:
                close_in_mother = (c0['close'] - c1['low']) / mother_range
                if close_in_mother > 0.7: score += 1
                elif close_in_mother < 0.3: score -= 1
            
        # 5. MARUBOZU
        if body_ratio > 0.7 and range0 > (atr * 0.5):
            if c0['close'] > c0['open'] and close_position > 0.8:
                patterns.append("BULLISH_MARUBOZU")
                momentum_score = int(2 * volume_multiplier)
                score += momentum_score
            
            elif c0['close'] < c0['open'] and close_position < 0.2:
                patterns.append("BEARISH_MARUBOZU")
                momentum_score = int(2 * volume_multiplier)
                score -= momentum_score

        # 6. STAR PATTERNS
        if (c2['close'] < c2['open']) and (abs(c2['close']-c2['open']) > atr * 0.5):
            if abs(c1['close']-c1['open']) < (atr * 0.3):
                if c0['close'] > c0['open'] and c0['close'] > ((c2['open'] + c2['close'])/2):
                    patterns.append("MORNING_STAR")
                    score += 4

        if (c2['close'] > c2['open']) and (abs(c2['close']-c2['open']) > atr * 0.5):
            if abs(c1['close']-c1['open']) < (atr * 0.3):
                if c0['close'] < c0['open'] and c0['close'] < ((c2['open'] + c2['close'])/2):
                    patterns.append("EVENING_STAR")
                    score -= 4

        # 7. THREE SOLDIERS / CROWS
        if all([df.iloc[-i]['close'] > df.iloc[-i]['open'] for i in [1,2,3]]):
            if all([df.iloc[-i]['close'] > df.iloc[-i-1]['close'] for i in [1,2]]):
                patterns.append("THREE_WHITE_SOLDIERS")
                score += 3

        if all([df.iloc[-i]['close'] < df.iloc[-i]['open'] for i in [1,2,3]]):
            if all([df.iloc[-i]['close'] < df.iloc[-i-1]['close'] for i in [1,2]]):
                patterns.append("THREE_BLACK_CROWS")
                score -= 3

        # --- FINAL CALCULATION ---
        score = score * noise_penalty * weak_candle_penalty
        
        if patterns:
            max_weight = max([self.PATTERN_WEIGHT.get(p, 1.0) for p in patterns])
            score = score * max_weight
        
        score = int(score)
        
        signal_type = "NEUTRAL"
        if score >= 5: signal_type = "STRONG_BULLISH"
        elif score > 0: signal_type = "BULLISH"
        elif score <= -5: signal_type = "STRONG_BEARISH"
        elif score < 0: signal_type = "BEARISH"
        
        strength_val = "HIGH" if (abs(score) >= 5 or volume_multiplier >= 1.2) else "LOW"
        
        return {
            'signal': signal_type,
            'score': score,
            'strength': strength_val,
            'patterns': patterns,
            'is_doji': is_doji,
            'rvol': round(rvol, 2),
            'body_dominance': round(body_ratio, 2),
            'close_strength': round(close_position, 2),
            'volume_multiplier': round(volume_multiplier, 2)
        }

    def _default_result(self, note=""):
        return {
            'signal': "NEUTRAL",
            'score': 0,
            'strength': 'LOW',
            'patterns': [],
            'is_doji': False,
            'rvol': 0.0,
            'body_dominance': 0.0,
            'close_strength': 0.0,
            'volume_multiplier': 1.0,
            'note': note
        }
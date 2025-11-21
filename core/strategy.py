import pandas as pd
import numpy as np

from indicators.moving_average import MovingAverage
from indicators.rsi import RSI
from indicators.macd import MACD
from indicators.bollinger_bands import BollingerBands
from indicators.atr import ATR
from indicators.stochastic import Stochastic
from core.candle_patterns import CandlePattern

from utils.settings_manager import SettingsManager 

try:
    from core.ai_analyzer import AIAnalyzer
except Exception:
    AIAnalyzer = None


class TradingStrategy:

    def __init__(self, sm: SettingsManager):
        self.sm = sm
        self.settings = sm.load_settings()

        ind = self.settings['indicators']
        sig = self.settings['signal_requirements']
        
        self.settings.setdefault('debug', {})
        self.debug_config = self.settings['debug']
        self.log_mtf = self.debug_config.get('log_mtf_filter', False)
        self.log_regime = self.debug_config.get('log_regime_changes', False)

        self.ma = MovingAverage(period=ind['ma_period'], shift=ind['ma_shift'])
        self.ma_long = MovingAverage(period=ind['ma_long_period'], shift=ind['ma_shift']) 
        self.rsi = RSI(period=ind['rsi_period'],
                            overbought=ind['rsi_overbought'], oversold=ind['rsi_oversold'])
        self.macd = MACD(fast_period=ind['macd_fast'],
                            slow_period=ind['macd_slow'], signal_period=ind['macd_signal'])
        self.bb = BollingerBands(period=ind['bb_period'], deviation=ind['bb_deviation'])
        self.atr = ATR(period=ind['atr_period'])
        self.stoch = Stochastic(
            k_period=ind['stoch_k_period'],
            d_period=ind['stoch_d_period'],
            slowing=ind['stoch_slowing'],
            overbought=ind['stoch_overbought'],
            oversold=ind['stoch_oversold'],
        )
        
        self.cp = CandlePattern() 
        
        self.htf_timeframe = sig.get('higher_timeframe', 'H1') 
        self.enable_mtf = sig.get('enable_mtf', True)
        self.ma_htf = MovingAverage(period=50) 

        self.signal_config = sig
        self.scoring_config = sig.get('scoring', {})
        self.strategy_mode_override = sig.get('strategy_mode_override', 'AUTO').upper()

        self._base_min_conf_sniper = float(sig.get('min_conf_sniper', 2.0))
        self._base_min_conf_trend  = float(sig.get('min_conf_trend', 1.5))
        self._base_min_conf_pullback = float(sig.get('min_conf_pullback', 2.0)) 
        self._base_min_conf_breakout = float(sig.get('min_conf_breakout', 1.0))
        
        self.min_exit_score = float(sig.get('min_exit_score', 2.0))

        self.min_conf_sniper = self._base_min_conf_sniper
        self.min_conf_trend  = self._base_min_conf_trend
        self.min_conf_pullback = self._base_min_conf_pullback
        self.min_conf_breakout = self._base_min_conf_breakout

        self.current_regime = "UNKNOWN"
        self.regime_details = {} 

        self.ai_analyzer = None
        if sig.get('use_ai', False) and AIAnalyzer is not None:
            try:
                self.ai_analyzer = AIAnalyzer(self.settings)
            except Exception:
                self.ai_analyzer = None

    def analyze(self, df_main: pd.DataFrame, session: str, df_htf: pd.DataFrame = None, is_backtest: bool = False):
        if df_main is None or len(df_main) < 100:
            return None, 0, {}
        
        manual_mode = self.sm.get_trading_mode().upper() 
        mode = "SNIPER" 

        if manual_mode != "AUTO":
             mode = manual_mode
        else:
             regime = self.current_regime
             current_price = df_main['close'].iloc[-1]
             ma_val = self.ma.calculate(df_main)
             
             deviation_pct = 0
             if ma_val:
                 deviation_pct = abs(current_price - ma_val) / ma_val * 100
             
             if deviation_pct > 0.3: 
                 if self.log_regime: pass
                 mode = "BREAKOUT_ONLY"
             elif regime == "TRENDING": mode = "TREND_ONLY"
             elif regime == "BREAKOUT": mode = "BREAKOUT_ONLY" 
             elif regime == "RANGING": mode = "SNIPER_ONLY"
             elif regime == "VOLATILE": mode = "BREAKOUT_ONLY" 
             elif regime == "NEUTRAL": mode = "SNIPER_ONLY"
             else: mode = "SNIPER" if session == "asian" else "TREND"

        sigs = {}
        sc = self.signal_config
        s = self.scoring_config
        total_score = 2.0

        # --- 1. INDICATORS ---
        if sc.get('use_atr', True):
            sigs['atr'] = self.atr.calculate(df_main)
            sigs['volatility'] = self.atr.get_volatility_state(df_main)
        
        # --- 2. MAIN TIMEFRAME PATTERN ---
        ma_trend = "NEUTRAL"
        ma_val = self.ma.calculate(df_main)
        current_price = df_main['close'].iloc[-1]
        if ma_val:
            if current_price > ma_val: ma_trend = "BULLISH"
            elif current_price < ma_val: ma_trend = "BEARISH"

        atr_val = sigs.get('atr', 0.0)
        pattern_result = self.cp.analyze(df_main, atr=atr_val, current_trend=ma_trend)
        sigs['pattern'] = pattern_result

        # --- 3. [NEW] HTF PATTERN CHECK ---
        if self.enable_mtf and df_htf is not None and len(df_htf) > 50:
            htf_ma_val = self.ma_htf.calculate(df_htf)
            htf_trend = "NEUTRAL"
            if htf_ma_val:
                htf_price = df_htf['close'].iloc[-1]
                if htf_price > htf_ma_val: htf_trend = "BULLISH"
                elif htf_price < htf_ma_val: htf_trend = "BEARISH"
            
            # Hitung ATR HTF on the fly untuk validasi size candle HTF
            htf_atr = self.atr.calculate(df_htf) or 0.0
            
            htf_pattern_result = self.cp.analyze(df_htf, atr=htf_atr, current_trend=htf_trend)
            sigs['htf_pattern'] = htf_pattern_result # Simpan

        # --- 4. SIGNAL GATHERING (INDICATORS) ---
        if mode in ["SNIPER_ONLY", "SNIPER"]:
            if sc.get('use_rsi', True):
                sigs['rsi'] = self.rsi.get_signal(df_main)
                sigs['rsi_value'] = self.rsi.calculate(df_main)
            if sc.get('use_bb', True):
                sigs['bb'] = self.bb.get_price_position_state(df_main)
            if sc.get('use_stoch', True):
                sigs['stoch'] = self.stoch.get_signal(df_main)
            min_conf_needed = self.min_conf_sniper
            total_score = s.get('sniper_setup_score', 1.5) + s.get('sniper_confirm_score', 1.0)

        elif mode in ["TREND_ONLY", "TREND"]:
            if sc.get('use_ma', True):
                sigs['ma'] = self.ma.get_signal(df_main)
            if sc.get('use_macd', True):
                sigs['macd'] = self.macd.get_state(df_main)
            min_conf_needed = self.min_conf_trend
            total_score = s.get('trend_ma_score', 1.5) + s.get('trend_macd_score', 1.0)

        elif mode == "PULLBACK_ONLY":
            if sc.get('use_ma', True): sigs['ma_long'] = self.ma_long.get_signal(df_main) 
            if sc.get('use_rsi', True): sigs['rsi'] = self.rsi.get_signal(df_main)
            if sc.get('use_stoch', True): sigs['stoch'] = self.stoch.get_signal(df_main)
            min_conf_needed = self.min_conf_pullback
            total_score = s.get('pullback_trend_score', 1.5) + s.get('pullback_rsi_score', 1.0) + s.get('pullback_stoch_score', 1.0)
        
        elif mode == "BREAKOUT_ONLY":
            sigs['regime'] = self.current_regime
            sigs['details'] = self.regime_details
            min_conf_needed = self.min_conf_breakout
            total_score = s.get('breakout_signal_score', 1.5) + s.get('breakout_confirm_score', 1.0)
        else: 
             return None, 0, {}

        # --- 5. SCORING ENGINE ---
        buy_score, sell_score = self._calculate_signal_scores(df_main, sigs, mode, df_htf)

        if total_score <= 0: total_score = 1

        signal_type = None
        confidence = 0.0
        
        if mode in ["SNIPER_ONLY", "SNIPER"]: min_conf_needed = self.min_conf_sniper
        elif mode in ["TREND_ONLY", "TREND"]: min_conf_needed = self.min_conf_trend
        elif mode == "PULLBACK_ONLY": min_conf_needed = self.min_conf_pullback
        elif mode == "BREAKOUT_ONLY": min_conf_needed = self.min_conf_breakout

        if buy_score >= min_conf_needed and buy_score > sell_score:
            signal_type = "BUY"
            confidence = (buy_score / total_score) * 100.0
        elif sell_score >= min_conf_needed and sell_score > buy_score:
            signal_type = "SELL"
            confidence = (sell_score / total_score) * 100.0

        confidence = min(confidence, 99.9)

        details = {
            'signals': sigs,
            'buy_score': buy_score,
            'sell_score': sell_score,
            'confidence': confidence,
            'signal_type': signal_type,
            'strategy_mode': mode,
            'min_conf_used': min_conf_needed 
        }
        return signal_type, confidence, details

    def _get_htf_trend(self, df_htf: pd.DataFrame) -> str:
        if df_htf is None or len(df_htf) < 50: return "NEUTRAL"
        try:
            htf_ma_value = self.ma_htf.calculate(df_htf)
            if htf_ma_value is None: return "NEUTRAL"
            current_price = df_htf['close'].iloc[-1]
            if current_price > htf_ma_value: return "BULLISH"
            elif current_price < htf_ma_value: return "BEARISH"
            return "NEUTRAL"
        except Exception: return "NEUTRAL"

    def _calculate_signal_scores(self, df_main: pd.DataFrame, signals: dict, strategy_mode: str, df_htf: pd.DataFrame):
        buy, sell = 0.0, 0.0
        s = self.scoring_config

        # --- A. MAIN PATTERN ANALYSIS (FIXED) ---
        pattern_data = signals.get('pattern', {})
        pat_score = pattern_data.get('score', 0)
        pat_strength = pattern_data.get('strength', 'LOW') # [FIX] Use strength
        pat_signal = pattern_data.get('signal', 'NEUTRAL')
        is_doji = pattern_data.get('is_doji', False)
        patterns_list = pattern_data.get('patterns', [])

        # [FIX] Scale Bonus by Strength
        strength_mult = 1.5 if pat_strength == 'HIGH' else 1.0
        pattern_bonus = pat_score * 0.5 * strength_mult

        if pattern_bonus > 0: buy += pattern_bonus
        elif pattern_bonus < 0: sell += abs(pattern_bonus)

        # --- B. HTF PATTERN ANALYSIS (NEW) ---
        htf_pat = signals.get('htf_pattern', {})
        htf_score = htf_pat.get('score', 0)
        
        if htf_score > 0: buy += 2.0 # Bonus besar untuk konfirmasi HTF
        elif htf_score < 0: sell += 2.0

        # --- C. CONFLICT DETECTION (VETO POWER) ---
        # 1. LTF vs HTF Conflict (M5 Buy, H1 Sell)
        if (pat_score > 0 and htf_score < 0) or (pat_score < 0 and htf_score > 0):
            print(f"[VETO] Conflict detected! LTF Pattern {pat_score} vs HTF Pattern {htf_score}")
            buy *= 0.5
            sell *= 0.5
        
        # 2. Doji Penalty
        if is_doji:
            buy *= 0.8
            sell *= 0.8

        # --- D. STANDARD INDICATOR SCORING ---
        if strategy_mode in ["SNIPER_ONLY", "SNIPER"]:
            last_candle = df_main.iloc[-1]
            recent_bodies = (df_main['close'].iloc[-11:-1] - df_main['open'].iloc[-11:-1]).abs().mean()
            current_body = abs(last_candle['close'] - last_candle['open'])
            is_panic_candle = current_body > (recent_bodies * 2.5)
            
            # [FIX] Conflict check: Panic Candle vs Reversal Pattern
            # Jika candle merah besar TAPI ada pola reversal Bullish (Morning Star/Hammer) -> valid buy
            is_bullish_reversal = "BULLISH_PINBAR" in patterns_list or "MORNING_STAR" in patterns_list or "BULLISH_ENGULFING" in patterns_list
            is_bearish_reversal = "BEARISH_PINBAR" in patterns_list or "EVENING_STAR" in patterns_list or "BEARISH_ENGULFING" in patterns_list
            
            rsi_sig = signals.get('rsi')
            bb_sig = signals.get('bb')
            stoch_sig = signals.get('stoch')

            overbought_count = 0
            if rsi_sig in ['OVERBOUGHT', 'SELL']: overbought_count += 1
            if bb_sig == 'OVERBOUGHT': overbought_count += 1
            if stoch_sig in ['OVERBOUGHT', 'SELL']: overbought_count += 1
            
            oversold_count = 0
            if rsi_sig in ['OVERSOLD', 'BUY']: oversold_count += 1
            if bb_sig == 'OVERSOLD': oversold_count += 1
            if stoch_sig in ['OVERSOLD', 'BUY']: oversold_count += 1

            if oversold_count >= 1:
                # Allow Buy if Panic AND Bullish Pattern exist
                if is_panic_candle and not is_bullish_reversal:
                    pass # Skip (Falling Knife)
                else:
                    buy += s.get('sniper_setup_score', 1.5) * (oversold_count / 3.0)
                    buy += s.get('sniper_confirm_score', 1.0)

            if overbought_count >= 1:
                if is_panic_candle and not is_bearish_reversal:
                    pass # Skip (Rocket Launch)
                else:
                    sell += s.get('sniper_setup_score', 1.5) * (overbought_count / 3.0)
                    sell += s.get('sniper_confirm_score', 1.0)
        
        elif strategy_mode in ["TREND_ONLY", "TREND"]:
            if signals.get('ma') in ['BUY', 'BULLISH', 'BULLISH_CROSS']: buy += s.get('trend_ma_score', 1.5)
            if signals.get('ma') in ['SELL', 'BEARISH', 'BEARISH_CROSS']: sell += s.get('trend_ma_score', 1.5)

            if signals.get('macd') in ['BUY', 'BULLISH', 'BULLISH_CROSS']: buy += s.get('trend_macd_score', 1.0)
            if signals.get('macd') in ['SELL', 'BEARISH', 'BEARISH_CROSS']: sell += s.get('trend_macd_score', 1.0)

            # [FIX] Gunakan Pattern di Mode Trend untuk Konfirmasi Entry
            if pat_signal in ["BULLISH", "STRONG_BULLISH"]: buy += 1.5
            elif pat_signal in ["BEARISH", "STRONG_BEARISH"]: sell += 1.5

            direction = self.regime_details.get('direction', 'NEUTRAL')
            bb_sig = signals.get('bb')
            if direction == 'BULLISH' and bb_sig == 'OVERSOLD': buy += 3.0 
            elif direction == 'BEARISH' and bb_sig == 'OVERBOUGHT': sell += 3.0

        elif strategy_mode == "PULLBACK_ONLY":
            main_trend = signals.get('ma_long')
            rsi_sig = signals.get('rsi')
            if main_trend in ['BUY', 'BULLISH']:
                buy += s.get('pullback_trend_score', 1.5)
                if rsi_sig in ['BUY', 'OVERSOLD']: buy += s.get('pullback_rsi_score', 1.0)
            elif main_trend in ['SELL', 'BEARISH']:
                sell += s.get('pullback_trend_score', 1.5)
                if rsi_sig in ['SELL', 'OVERBOUGHT']: sell += s.get('pullback_rsi_score', 1.0)
        
        elif strategy_mode == "BREAKOUT_ONLY":
            regime = signals.get('regime')
            details = signals.get('details', {})
            if regime in ["BREAKOUT", "VOLATILE"]:
                direction = details.get('direction', 'NEUTRAL')
                if direction == "BULLISH":
                    buy += s.get('breakout_signal_score', 1.5)
                    buy += s.get('breakout_confirm_score', 1.0)
                elif direction == "BEARISH":
                    sell += s.get('breakout_signal_score', 1.5)
                    sell += s.get('breakout_confirm_score', 1.0)
                
                # Inside Bar Breakout Logic
                if "INSIDE_BAR" in patterns_list:
                     if direction == "BULLISH": buy += 1.5
                     elif direction == "BEARISH": sell += 1.5

        # --- MTF FILTER ---
        if self.enable_mtf and df_htf is not None:
            htf_trend = self._get_htf_trend(df_htf)
            bonus = s.get('mtf_bonus_score', 2.0)
            
            if buy > 0:
                if htf_trend == "BULLISH": buy += bonus 
                elif htf_trend == "BEARISH":
                    if strategy_mode in ["SNIPER", "SNIPER_ONLY"]: buy = 0 
                    elif strategy_mode == "BREAKOUT_ONLY": buy *= 0.8 
                    else: buy *= 0.5 
            
            if sell > 0:
                if htf_trend == "BEARISH": sell += bonus 
                elif htf_trend == "BULLISH":
                    if strategy_mode in ["SNIPER", "SNIPER_ONLY"]: sell = 0 
                    elif strategy_mode == "BREAKOUT_ONLY": sell *= 0.8 
                    else: sell *= 0.5

        return buy, sell

    def update_dynamic_confidence(self, regime: str, details: dict):
        self.current_regime = regime
        self.regime_details = details 
        self.min_conf_sniper = self._base_min_conf_sniper
        self.min_conf_trend  = self._base_min_conf_trend
        self.min_conf_pullback = self._base_min_conf_pullback 
        self.min_conf_breakout = self._base_min_conf_breakout

        if regime == "VOLATILE":
            self.min_conf_sniper += 2.0 
            self.min_conf_breakout = max(1.0, self._base_min_conf_breakout - 0.2)
        elif regime == "TRENDING":
            strength = details.get('strength', 'N/A')
            if strength == 'STRONG':
                self.min_conf_trend = max(1.0, self._base_min_conf_trend - 0.5) 
                self.min_conf_pullback = max(1.0, self._base_min_conf_pullback - 0.5)
                self.min_conf_sniper += 2.0 
        elif regime == "RANGING":
            self.min_conf_sniper = max(1.5, self._base_min_conf_sniper - 0.5)

    def should_close_position(self, position: dict, details: dict):
        signal_type = details.get('signal_type')
        buy_score = float(details.get('buy_score', 0.0))
        sell_score = float(details.get('sell_score', 0.0))
        min_exit_score = self.min_exit_score  

        if position['type'] == 'BUY' and signal_type == 'SELL' and sell_score >= min_exit_score:
            return True, "Strong SELL signal"
        if position['type'] == 'SELL' and signal_type == 'BUY' and buy_score >= min_exit_score:
            return True, "Strong BUY signal"

        rsi_value = details.get('signals', {}).get('rsi_value')
        if rsi_value is not None:
            rsi_ob = self.rsi.overbought
            rsi_os = self.rsi.oversold
            if position['type'] == 'BUY' and rsi_value > (rsi_ob + 15): return True, f"RSI extremely overbought ({rsi_value:.1f})"
            if position['type'] == 'SELL' and rsi_value < (rsi_os - 15): return True, f"RSI extremely oversold ({rsi_value:.1f})"
        
        pattern_data = details.get('signals', {}).get('pattern', {})
        pat_signal = pattern_data.get('signal', 'NEUTRAL')
        
        if position['type'] == 'BUY' and pat_signal == "STRONG_BEARISH":
             return True, f"Exit due to Strong Bearish Pattern ({pattern_data.get('patterns')})"
        if position['type'] == 'SELL' and pat_signal == "STRONG_BULLISH":
             return True, f"Exit due to Strong Bullish Pattern ({pattern_data.get('patterns')})"

        return False, "Hold"

    def get_signal_summary(self, details: dict) -> str:
        sigs = details.get('signals', {})
        parts = []
        if 'pattern' in sigs and sigs['pattern'].get('patterns'):
             pats = ",".join(sigs['pattern']['patterns'])
             parts.append(f"PAT: {pats}")
        
        # [NEW] HTF Pattern Info
        if 'htf_pattern' in sigs and sigs['htf_pattern'].get('patterns'):
             htf_pats = ",".join(sigs['htf_pattern']['patterns'])
             parts.append(f"HTF_PAT: {htf_pats}")

        for k, v in sigs.items():
            if k in ('rsi_value', 'atr', 'volatility', 'details', 'pattern', 'htf_pattern'): continue
            if v and v != 'NEUTRAL': parts.append(f"{k.upper()}: {v}")
        parts.append(f"MODE: {details.get('strategy_mode', 'N/A')}")
        return " | ".join(parts) if parts else "No clear signals"

    def validate_signal(self, signal_type: str, df, symbol_info: dict):
        if len(df) < 100: return False, "Insufficient data"
        return True, "Signal valid"
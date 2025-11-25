import math
from typing import Tuple, Dict, Any, Optional

__all__ = ["RiskManager"]

class RiskManager:

    def __init__(self, sm):
        self.sm = sm
        self._load_or_default()

    def _load_or_default(self):
        self.settings = {}
        try:
            self.settings = self.sm.load_settings()
        except Exception as e:
            print(f"[RiskManager] Warning: failed to load settings ({e}). Using defaults.")

        self.settings.setdefault('trading', {})
        self.settings.setdefault('risk_management', {})
        self.settings.setdefault('debug', {})
        
        self.debug_config = self.settings['debug']
        self.log_calc = self.debug_config.get('log_lot_calculation', False)

        tr = self.settings['trading']
        tr.setdefault('symbol', 'XAUUSD')
        tr.setdefault('max_positions', 5)
        tr.setdefault('max_positions_per_direction', 3)

        rm = self.settings['risk_management']
        rm.setdefault('risk_per_trade_pct', 1.0)
        rm.setdefault('max_total_risk_pct', 5.0)
        rm.setdefault('max_single_position_risk_pct', 2.0) 
        
        rm.setdefault('atr_multiplier_sl', 1.5)
        rm.setdefault('atr_multiplier_tp', 2.5)
        
        rm.setdefault('breakeven_rr', 1.0) 
        rm.setdefault('scale_out_enabled', True)
        rm.setdefault('scale_out_rr1', 1.5) 
        rm.setdefault('scale_out_pct1', 0.5) 
        rm.setdefault('trailing_stop_enabled', True)
        rm.setdefault('trailing_stop_atr_multiplier', 2.0)
        rm.setdefault('trailing_step_points', 50) 
        rm.setdefault('trailing_activation_rr', 1.0) 
        
        rm.setdefault('enable_margin_filter', True)
        rm.setdefault('min_margin_level_pct', 500.0)
        rm.setdefault('daily_loss_limit_pct', 5.0)
        rm.setdefault('drawdown_risk_reduction', True) 

        self.trading = tr
        self.risk = rm

    def reload_settings(self):
        self._load_or_default()

    @staticmethod
    def _get_point(symbol_info: dict) -> float:
        p = float(symbol_info.get('point', 0.0))
        return p if p > 0 else 0.01

    @staticmethod
    def _get_digits(symbol_info: dict) -> int:
        return int(symbol_info.get('digits', 2))

    @staticmethod
    def _get_contract_size(symbol_info: dict) -> float:
        c = float(symbol_info.get('trade_contract_size', 0))
        if c > 0: return c
        name = symbol_info.get('name', '').upper()
        if 'XAU' in name or 'GOLD' in name: return 100.0
        if 'JPY' in name: return 100000.0
        return 100000.0 

    def _normalize_volume(self, vol: float, symbol_info: dict) -> float:
        step = float(symbol_info.get('volume_step', 0.01))
        min_vol = float(symbol_info.get('volume_min', 0.01))
        max_vol = float(symbol_info.get('volume_max', 100.0))
        
        if step == 0: step = 0.01
        
        vol = round(vol / step) * step
        vol = max(min_vol, min(vol, max_vol))
        
        decimals = 0
        if step < 1: decimals = len(str(step).split('.')[1])
        return round(vol, decimals)

    def calculate_sl_tp(self, entry_price: float, signal_type: str, atr_value: float, symbol_info: dict, strategy_mode: str = "AUTO"):
        try:
            if entry_price <= 0 or atr_value <= 0: return None, None

            point = self._get_point(symbol_info)
            digits = self._get_digits(symbol_info)

            base_sl_mult = float(self.risk.get('atr_multiplier_sl', 1.5))
            base_tp_mult = float(self.risk.get('atr_multiplier_tp', 2.5))
            min_rr = float(self.risk.get('min_risk_reward_ratio', 1.0))

            # Dynamic Adjustments
            if "SNIPER" in strategy_mode:
                base_sl_mult *= 0.9 
                base_tp_mult *= 1.0 
            elif "TREND" in strategy_mode:
                base_sl_mult *= 1.2 
                base_tp_mult *= 2.0 
            elif "BREAKOUT" in strategy_mode:
                base_sl_mult *= 1.1
                base_tp_mult *= 1.5

            sl_dist = atr_value * base_sl_mult
            tp_dist = atr_value * base_tp_mult

            # Sanity Check SL Distance
            min_sl_points = 100 * point if "XAU" in symbol_info.get('name', '') else 50 * point
            max_sl_points = 2000 * point 

            sl_dist = max(min_sl_points, min(sl_dist, max_sl_points))
            
            if tp_dist < (sl_dist * min_rr):
                tp_dist = sl_dist * min_rr

            if signal_type == 'BUY':
                sl = entry_price - sl_dist
                tp = entry_price + tp_dist
            elif signal_type == 'SELL':
                sl = entry_price + sl_dist
                tp = entry_price - tp_dist
            else:
                return None, None

            return round(sl, digits), round(tp, digits)

        except Exception as e:
            print(f"[RiskManager] Error calc SL/TP: {e}")
            return None, None

    def calculate_optimal_lot_size(self, balance: float, entry_price: float, sl_price: float, symbol_info: dict) -> float:
        try:
            min_vol = float(symbol_info.get('volume_min', 0.01))
            max_vol = float(symbol_info.get('volume_max', 100.0))
            contract_size = self._get_contract_size(symbol_info)
            
            # --- FLEXIBLE AUTO RISK ENGINE ---
            # Deteksi balance dan tentukan risk profile secara otomatis
            
            if balance < 50.0:
                # LEVEL 1: SURVIVAL (<$50)
                effective_risk_pct = 25.0
                mode_label = "SURVIVAL"
            
            elif balance < 200.0:
                # LEVEL 2: GROWTH ($50 - $200)
                effective_risk_pct = 8.0
                mode_label = "GROWTH"
                
            elif balance < 1000.0:
                # LEVEL 3: STANDARD ($200 - $1000)
                effective_risk_pct = 3.0
                mode_label = "STANDARD"
                
            else:
                # LEVEL 4: PRO (>$1000)
                setting_risk = float(self.risk.get('risk_per_trade_pct', 1.0))
                effective_risk_pct = min(setting_risk, 2.0)
                mode_label = "PRO"

            if self.log_calc:
                print(f"[Risk] Auto-Flex: Balance ${balance:.2f} -> Mode: {mode_label} (Risk {effective_risk_pct}%)")

            # Hitung Lot berdasarkan Risk Profile dinamis tadi
            risk_amount = balance * (effective_risk_pct / 100.0)
            
            sl_dist_price = abs(entry_price - sl_price)
            point = self._get_point(symbol_info)
            
            # Safety SL distance (asumsi minimal 20 pip buat XAU biar hitungan lot gak meledak)
            min_calc_sl = 200 * point if "XAU" in symbol_info.get('name', '') else 50 * point
            effective_sl_dist = max(sl_dist_price, min_calc_sl)

            risk_per_lot = effective_sl_dist * contract_size
            
            if risk_per_lot == 0: return min_vol

            raw_lot = risk_amount / risk_per_lot
            
            # Final Check: Jangan pernah di bawah min_vol kalau di mode Survival/Growth
            if raw_lot < min_vol:
                if balance >= 10.0: # Minimal banget $10
                    raw_lot = min_vol
                else:
                    return 0.0 # Di bawah $10 udah gak selamat

            final_lot = self._normalize_volume(raw_lot, symbol_info)
            return max(min(final_lot, max_vol), 0.0)

        except Exception as e:
            print(f"[Risk] Error calc lot: {e}")
            return 0.01

    def calculate_position_risk(self, entry_price: float, sl_price: float, lot: float, symbol_info: dict) -> float:
        try:
            contract_size = self._get_contract_size(symbol_info)
            sl_dist = abs(entry_price - sl_price)
            return float(lot * sl_dist * contract_size)
        except:
            return 0.0

    def can_open_new_position(self, balance: float, positions: list, new_position_risk: float,
                              signal_type: str, symbol_info: dict):
        try:
            # --- FLEXIBLE AUTO POSITION LIMIT ---
            setting_max_pos = int(self.trading.get('max_positions', 5))
            
            # Override Max Positions berdasarkan Balance
            if balance < 50.0:
                real_max_pos = 1 # Cuma 1 peluru untuk survival
            elif balance < 200.0:
                real_max_pos = min(3, setting_max_pos) # Max 3 peluru
            else:
                real_max_pos = setting_max_pos # Ikuti settingan
            
            # Hitung posisi sekarang
            total_pos = len(positions)
            if total_pos >= real_max_pos:
                return False, f"Max positions limit ({total_pos}/{real_max_pos}) for Balance ${balance:.0f}"

            # Untuk akun < $100, kita bypass margin check yang ribet
            if balance < 100.0:
                return True, "OK (Auto-Flex Entry)"

            # Untuk akun besar, cek margin filter standar
            max_total_risk_pct = float(self.risk.get('max_total_risk_pct', 10.0))
            total_risk_usd_limit = balance * (max_total_risk_pct / 100.0)
            
            current_total_risk = 0.0
            for p in positions:
                sl = p.get('sl', 0.0)
                if sl > 0:
                    current_total_risk += self.calculate_position_risk(p['price_open'], sl, p['volume'], symbol_info)
            
            projected_risk = current_total_risk + new_position_risk
            
            if projected_risk > (total_risk_usd_limit * 1.2): 
                return False, f"Total Risk Limit: ${projected_risk:.2f} > ${total_risk_usd_limit:.2f}"

            return True, "OK"
        except Exception as e:
            return False, f"Error checking limits: {e}"

    def should_move_to_breakeven(self, position: dict, current_price: float, symbol_info: dict) -> Tuple[bool, Optional[float]]:
        try:
            be_rr = float(self.risk.get('breakeven_rr', 1.0))
            if be_rr <= 0: return False, None

            entry_price = position['price_open']
            sl_price = position['sl']
            
            if sl_price == 0.0: return False, None

            point = self._get_point(symbol_info)
            digits = self._get_digits(symbol_info)
            
            risk_dist = abs(entry_price - sl_price)
            if risk_dist < (10 * point): return False, None 

            trigger_dist = risk_dist * be_rr

            spread_buffer = 50 * point 
            if "XAU" in symbol_info.get('name', ''): 
                spread_buffer = max(spread_buffer, entry_price * 0.0003) 

            if position['type'] == 'BUY':
                if (current_price - entry_price) < trigger_dist: return False, None
                new_sl = entry_price + spread_buffer
                if new_sl > sl_price and new_sl < current_price:
                    return True, round(new_sl, digits)
                    
            elif position['type'] == 'SELL':
                if (entry_price - current_price) < trigger_dist: return False, None
                new_sl = entry_price - spread_buffer
                if (sl_price == 0.0 or new_sl < sl_price) and new_sl > current_price:
                    return True, round(new_sl, digits)

            return False, None
        except Exception:
            return False, None

    def calculate_trailing_stop(self, position: dict, current_price: float, atr_value: float, symbol_info: dict) -> Optional[float]:
        try:
            if not self.risk.get('trailing_stop_enabled', True): return None
            
            mult = float(self.risk.get('trailing_stop_atr_multiplier', 2.0))
            activation_rr = float(self.risk.get('trailing_activation_rr', 1.0))
            step_points = float(self.risk.get('trailing_step_points', 50))
            
            if atr_value <= 0: return None
            
            point = self._get_point(symbol_info)
            digits = self._get_digits(symbol_info)
            
            entry_price = position['price_open']
            current_sl = position.get('sl', 0.0)
            
            initial_risk = abs(entry_price - current_sl) if current_sl > 0 else atr_value
            profit_dist = abs(current_price - entry_price)
            
            if profit_dist < (initial_risk * activation_rr): return None

            step = step_points * point
            trail_dist = atr_value * mult

            if position['type'] == 'BUY':
                if current_price <= entry_price: return None 
                candidate_sl = current_price - trail_dist
                
                if candidate_sl < entry_price: return None 
                if candidate_sl <= current_sl: return None 
                if (candidate_sl - current_sl) < step: return None 
                
                return round(candidate_sl, digits)

            elif position['type'] == 'SELL':
                if current_price >= entry_price: return None
                candidate_sl = current_price + trail_dist
                
                if candidate_sl > entry_price: return None
                if current_sl != 0.0 and candidate_sl >= current_sl: return None
                if current_sl != 0.0 and (current_sl - candidate_sl) < step: return None

                return round(candidate_sl, digits)

            return None
        except Exception:
            return None

    def check_scale_out(self, position: dict, current_price: float) -> Tuple[bool, float, float]:
        try:
            if not self.risk.get('scale_out_enabled', True): return False, 0.0, 0.0
            
            rr_trigger = float(self.risk.get('scale_out_rr1', 1.5))
            pct_close = float(self.risk.get('scale_out_pct1', 0.5))
            
            entry = position['price_open']
            sl = position['sl']
            vol = position['volume']
            
            if sl == 0.0: return False, 0.0, 0.0
            risk = abs(entry - sl)
            if risk < 1e-9: return False, 0.0, 0.0 
            
            profit_dist = 0.0
            if position['type'] == 'BUY': profit_dist = current_price - entry
            else: profit_dist = entry - current_price
            
            if profit_dist < (risk * rr_trigger): return False, 0.0, 0.0
                
            raw_close_lot = vol * pct_close
            close_lot = float(int(raw_close_lot * 100) / 100.0) 
            if close_lot < 0.01: close_lot = 0.01
            
            remain = vol - close_lot
            if remain < 0.01: return False, 0.0, 0.0 
                
            return True, close_lot, rr_trigger
            
        except Exception:
            return False, 0.0, 0.0

    def get_position_stats(self, balance: float, positions: list, symbol_info: dict):
        try:
            total = len(positions)
            buys = sum(1 for p in positions if p.get('type') == 'BUY')
            sells = total - buys
            
            risk_usd = 0.0
            for p in positions:
                sl = p.get('sl', 0.0)
                if sl > 0:
                    risk_usd += self.calculate_position_risk(p['price_open'], sl, p['volume'], symbol_info)
            
            risk_pct = (risk_usd / balance * 100) if balance > 0 else 0
            
            return {
                'total_positions': total,
                'buy_positions': buys,
                'sell_positions': sells,
                'total_risk': round(risk_usd, 2),
                'risk_pct': round(risk_pct, 2)
            }
        except:
            return {'total_positions': 0, 'buy_positions': 0, 'sell_positions': 0, 'total_risk': 0.0, 'risk_pct': 0.0}
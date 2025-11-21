import json
import os
from typing import Tuple

class SpreadFilter:
    def __init__(self, sm):
        self.sm = sm
        self._load_settings()

    def _load_settings(self):
        try:
            settings = self.sm.load_settings()
            if not settings:
                settings = {}
            
            self.spread_settings = settings.get('filters', {}).get('spread_settings', None)
            
            if not self.spread_settings:
                print("[SpreadFilter] WARNING: 'spread_settings' not found in config. Using defaults.")
                self._set_default_settings()
            
        except Exception as e:
            print(f"[SpreadFilter] Error loading spread settings: {e}. Using safe defaults.")
            self._set_default_settings()
    
    def _set_default_settings(self):
        self.spread_settings = {
            "default_max": 35,
            "session_multiplier": {
                "asian": 1.2, 
                "london": 1.0, 
                "us": 1.0, 
                "sydney": 1.2
            },
            "overrides": {
                "XAUUSD": 50,
                "XAUEUR": 150,
                "EURUSD": 20,
                "AUDCAD": 30
            }
        }

    def get_dynamic_max_spread(self, symbol: str, session_name: str) -> int:
        overrides = self.spread_settings.get('overrides', {})
        multipliers = self.spread_settings.get('session_multiplier', {})
        
        base_limit = 35 

        if symbol and symbol in overrides:
            base_limit = int(overrides[symbol])
        else:
            base_limit = int(self.spread_settings.get('default_max', 35))
            
        session_key = session_name.lower() if session_name else "unknown"
        multiplier = float(multipliers.get(session_key, 1.0))
        
        dynamic_limit = base_limit * multiplier
        
        return int(dynamic_limit)

    def is_spread_acceptable(self, symbol_info: dict, session_name: str) -> Tuple[bool, str]:
        try:
            if not symbol_info or not isinstance(symbol_info, dict):
                return (False, "SpreadFilter error: Invalid symbol_info (not a dict)")
            
            current_spread = int(symbol_info.get('spread', 0))
            symbol = symbol_info.get('name', 'UNKNOWN')
            
            if current_spread < 0:
                return (False, f"SpreadFilter error: Invalid spread value ({current_spread})")
            
            if not session_name or not isinstance(session_name, str):
                session_name = "unknown"
            
            max_allowed = self.get_dynamic_max_spread(symbol, session_name)
            
            if current_spread > max_allowed:
                reason = f"Spread too high: {current_spread} pts (max: {max_allowed} for {symbol} in {session_name} session)"
                return (False, reason)
            
            return (True, "Spread OK")
            
        except Exception as e:
            error_msg = f"SpreadFilter error: {e}"
            print(f"[SpreadFilter] {error_msg}")
            return (False, error_msg)
    
    def get_spread_info(self, symbol: str, session_name: str) -> dict:
        try:
            max_allowed = self.get_dynamic_max_spread(symbol, session_name)
            
            overrides = self.spread_settings.get('overrides', {})
            multipliers = self.spread_settings.get('session_multiplier', {})
            
            base_limit = overrides.get(symbol, self.spread_settings.get('default_max', 35))
            multiplier = multipliers.get(session_name.lower(), 1.0)
            
            return {
                'symbol': symbol,
                'session': session_name,
                'base_limit': base_limit,
                'session_multiplier': multiplier,
                'final_max_spread': max_allowed,
                'is_override': symbol in overrides
            }
        except Exception as e:
            return {
                'error': str(e)
            }
import json
from datetime import datetime
import pytz

class SessionFilter:
    def __init__(self, sm):
        self.settings = sm.load_settings()
        
        self.config = self.settings['filters']
        self.enabled = self.config['session_filter_enabled']
        self.allowed_sessions = [s.lower() for s in self.config['allowed_sessions']]
        
        self.sessions = {
            'asian': {'start': 0, 'end': 9},    # 00:00 - 09:00 UTC
            'london': {'start': 8, 'end': 17},  # 08:00 - 17:00 UTC
            'us': {'start': 13, 'end': 22},    # 13:00 - 22:00 UTC
            'sydney': {'start': 22, 'end': 7}  # 22:00 - 07:00 UTC (next day)
        }
    
    def get_current_session(self):
        try:
            now_gmt = datetime.now(pytz.UTC)
        except ImportError:
            now_gmt = datetime.utcnow()
            
        current_hour = now_gmt.hour
        
        active_sessions = []
        
        for session_name, session_time in self.sessions.items():
            start = session_time['start']
            end = session_time['end']
            
            if start > end:
                if current_hour >= start or current_hour < end:
                    active_sessions.append(session_name)
            else:
                if start <= current_hour < end:
                    active_sessions.append(session_name)
        
        return active_sessions
    
    def is_trading_allowed(self):
        if not self.enabled:
            return True, "london" 
        
        current_sessions = self.get_current_session()
        
        if not current_sessions:
            return False, "No active session"

        for session in current_sessions:
            if session in ['london', 'us'] and session in self.allowed_sessions:
                return True, session 
        
        for session in current_sessions:
            if session == 'asian' and session in self.allowed_sessions:
                return True, 'asian'

        for session in current_sessions:
            if session in self.allowed_sessions:
                return True, session

        return False, f"Current sessions {current_sessions} not in allowed list"
    
    def get_session_overlap(self):
        current_sessions = self.get_current_session()
        
        if len(current_sessions) > 1:
            return current_sessions, True
        
        return current_sessions, False
    
    def get_next_session_start(self):
        if not self.enabled:
            return None
        
        now_gmt = datetime.now(pytz.UTC)
        current_hour = now_gmt.hour
        
        upcoming_sessions = []
        
        for session_name in self.allowed_sessions:
            if session_name in self.sessions:
                session_start = self.sessions[session_name]['start']
                
                if session_start > current_hour:
                    hours_until = session_start - current_hour
                else:
                    hours_until = (24 - current_hour) + session_start
                
                upcoming_sessions.append({
                    'session': session_name,
                    'hours_until': hours_until
                })
        
        if not upcoming_sessions:
            return None
        
        upcoming_sessions.sort(key=lambda x: x['hours_until'])
        return upcoming_sessions[0]
    
    def is_peak_hours(self):
        now_gmt = datetime.now(pytz.UTC)
        current_hour = now_gmt.hour
        
        if 13 <= current_hour < 17:
            return True, "London-US overlap"
        
        if 8 <= current_hour < 9:
            return True, "Asian-London overlap"
        
        return False, "Not peak hours"
    
    def get_session_info(self):
        current_sessions = self.get_current_session()
        is_allowed, active_session = self.is_trading_allowed()
        is_peak, peak_msg = self.is_peak_hours()
        
        return {
            'current_sessions': current_sessions,
            'is_allowed': is_allowed,
            'active_session_name': active_session if is_allowed else "NONE",
            'is_peak_hours': is_peak,
            'peak_message': peak_msg,
            'allowed_sessions': self.allowed_sessions
        }
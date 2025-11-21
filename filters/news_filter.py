import json
from datetime import datetime, timedelta
import requests
import pytz

class NewsFilter:
    def __init__(self, sm):
        self.settings = sm.load_settings()
        
        self.config = self.settings['filters']
        self.enabled = self.config['news_filter_enabled']
        self.before_minutes = self.config['news_before_minutes']
        self.after_minutes = self.config['news_after_minutes']
        
        self.news_events = []
        self.last_update = None
        
        self.update_news_cache()
    
    def fetch_news_calendar(self):
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        
        print("Fetching news calendar...")
        
        try:
            response = requests.get(url, timeout=10)
            raw_events = response.json()

            processed_events = []
            for event in raw_events:
                impact = event.get('impact', 'Low').upper()
                
                if impact != 'HIGH':
                    continue

                try:
                    event_time_str = event.get('date')
                    event_time_str = event_time_str.replace('Z', '+00:00')
                    event_time = datetime.fromisoformat(event_time_str)
                    
                    event_time = event_time.astimezone(pytz.UTC)
                    
                except Exception as e:
                    print(f"Warning: Could not parse news time '{event.get('date')}': {e}")
                    continue
                
                processed_events.append({
                    'time': event_time,
                    'currency': event.get('country', 'USD'),
                    'impact': impact,
                    'title': event.get('title', 'No Title')
                })
                
            self.news_events = processed_events
            self.last_update = datetime.now(pytz.UTC)
            print(f"News cache updated. {len(self.news_events)} high-impact events loaded.")
            return True
            
        except Exception as e:
            print(f"Error fetching news calendar: {e}")
            return False
    
    def is_news_time(self, symbol='XAUUSD'):
        if not self.enabled:
            return False, "News filter disabled", None
        
        now = datetime.now(pytz.UTC)
        
        relevant_currencies = self._get_relevant_currencies(symbol)
        
        for event in self.news_events:
            if event.get('currency') not in relevant_currencies:
                continue
            
            if event.get('impact') != 'HIGH':
                continue
            
            event_time = event.get('time')
            
            if not isinstance(event_time, datetime):
                continue
            
            start_time = event_time - timedelta(minutes=self.before_minutes)
            end_time = event_time + timedelta(minutes=self.after_minutes)
            
            if start_time <= now <= end_time:
                if now < event_time:
                    minutes_until = (event_time - now).total_seconds() / 60
                    msg = f"High impact {event['currency']} news in {minutes_until:.0f} mins: {event['title']}"
                else:
                    minutes_past = (now - event_time).total_seconds() / 60
                    msg = f"High impact {event['currency']} news {minutes_past:.0f} mins ago: {event['title']}"
                
                return True, msg, event
        
        return False, "No major news upcoming", None
    
    def _get_relevant_currencies(self, symbol):
        currency_map = {
            'XAUUSD': ['USD'], 
            'XAUEUR': ['EUR', 'USD'],
            'EURUSD': ['EUR', 'USD'], 
            'GBPUSD': ['GBP', 'USD'],
            'USDJPY': ['USD', 'JPY'], 
            'AUDUSD': ['AUD', 'USD'], 
            'USDCAD': ['USD', 'CAD'],
            'NZDUSD': ['NZD', 'USD'], 
            'USDCHF': ['USD', 'CHF']
        }
        
        if symbol in currency_map:
            return currency_map[symbol]
        
        if len(symbol) == 6:
            base = symbol[0:3].upper()
            quote = symbol[3:6].upper()
            return [base, quote]
            
        return ['USD']
    
    def should_close_positions_before_news(self, symbol='XAUUSD', minutes_before=5):
        is_news, message, event = self.is_news_time(symbol)
        
        if is_news and event:
            now = datetime.now(pytz.UTC)
            event_time = event['time']
            
            if now < event_time:
                minutes_until = (event_time - now).total_seconds() / 60
                
                if minutes_until <= minutes_before:
                    return True, f"Close positions - {event['title']} imminent ({minutes_until:.0f} mins)"
        
        return False, "No immediate news threat"
    
    def update_news_cache(self):
        now = datetime.now(pytz.UTC)
        if self.last_update is None or \
           (now - self.last_update).total_seconds() > 3600:
            print("News cache expired, fetching new data...")
            return self.fetch_news_calendar()
        
        return True
    
    def clear_old_news(self):
        now = datetime.now(pytz.UTC)
        cutoff = now - timedelta(minutes=self.after_minutes)
        
        self.news_events = [
            event for event in self.news_events
            if isinstance(event.get('time'), datetime) and event['time'] > cutoff
        ]
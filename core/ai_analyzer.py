# File: core/ai_analyzer.py (FILE BARU)

import os
import json
import google.generativeai as genai
from datetime import datetime, timedelta

class AIAnalyzer:
    def __init__(self, settings_path='config/settings.json'):
        with open(settings_path, 'r') as f:
            self.settings = json.load(f)
        
        self.api_key = os.getenv('GEMINI_API_KEY')
        self.enabled = bool(self.api_key)
        self.model = None
        
        if self.enabled:
            try:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel('gemini-1.5-flash')
                print("✓ AI Analyzer (Gemini) initialized.")
            except Exception as e:
                print(f"❌ Error initializing Gemini AI: {e}")
                self.enabled = False
        else:
            print("⚠️  AI Analyzer disabled. (GEMINI_API_KEY not found in .env)")

        # Cache
        self.cache_duration = timedelta(hours=self.settings.get('ai_config', {}).get('cache_duration_hours', 1))
        self.last_sentiment = "NEUTRAL"
        self.last_fetch_time = None
    
    def get_market_sentiment(self, symbol='XAUUSD'):
        """
        Mendapatkan sentimen market. 
        Menggunakan cache untuk efisiensi.
        """
        now = datetime.now()
        
        # 1. Cek Cache
        if self.last_fetch_time and (now - self.last_fetch_time) < self.cache_duration:
            return self.last_sentiment # Balikin data lama jika belum expired

        # 2. Jika cache expired atau tidak ada, fetch baru
        if not self.enabled or not self.model:
            return "NEUTRAL" # Return default jika AI mati

        print("\n[AI Analyzer] Cache expired. Fetching new sentiment from Gemini...")
        
        try:
            # Ini adalah "Prompt Engineering"
            prompt = f"""
            Anda adalah seorang analis pasar keuangan senior di Goldman Sachs yang berspesialisasi dalam komoditas, khususnya Emas (XAUUSD).
            Analisis kondisi pasar global saat ini (berita ekonomi makro, kebijakan The Fed, ketegangan geopolitik, dan data teknikal terbaru).
            
            Berdasarkan analisis Anda, tentukan sentimen jangka pendek (1-4 jam ke depan) untuk XAUUSD.
            
            Jawab HANYA dengan SATU KATA:
            BULLISH (jika Anda yakin harga akan naik)
            BEARISH (jika Anda yakin harga akan turun)
            NEUTRAL (jika Anda ragu atau melihat pasar sideways)
            """
            
            response = self.model.generate_content(prompt)
            text_response = response.text.strip().upper()
            
            # 3. Parsing jawaban AI
            if "BULLISH" in text_response:
                self.last_sentiment = "BULLISH"
            elif "BEARISH" in text_response:
                self.last_sentiment = "BEARISH"
            else:
                self.last_sentiment = "NEUTRAL"
                
            self.last_fetch_time = now
            print(f"[AI Analyzer] New sentiment received: {self.last_sentiment}")
            return self.last_sentiment

        except Exception as e:
            print(f"❌ Error fetching AI sentiment: {e}")
            # Jika error, pake sentimen lama dan coba lagi nanti
            return self.last_sentiment

    def get_cached_sentiment(self):
        """Hanya mengambil data dari cache (untuk backtester)"""
        # Backtester tidak boleh manggil API, jadi dia cuma dapet 'NEUTRAL'
        return self.last_sentiment
# Di risk_manager.py, strategy.py, news_filter.py, dll.
class RiskManager:
    def __init__(self, settings: dict):
        self.settings = settings # <-- INI BENAR (terima data)
        self._load_or_default() # <-- HAPUS FUNGSI INI
        self.risk = self.settings.get('risk_management', {})
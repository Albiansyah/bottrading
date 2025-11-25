import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import os
from dotenv import load_dotenv
import pytz
from math import log10

load_dotenv()

class MT5Connector:
    
    def __init__(self, sm):
        self.sm = sm
        self.settings = self.sm.load_settings()
        
        mt5_config = self.settings.get('mt5_credentials', {})
        
        try:
            login_env = mt5_config.get('login') or os.getenv('MT5_LOGIN')
            self.login = int(login_env) if login_env else 0
        except (ValueError, TypeError) as e:
            print(f"Error: MT5_LOGIN tidak valid di settings.json atau .env. Error: {e}")
            print("Login diatur ke 0, koneksi kemungkinan akan gagal.")
            self.login = 0
            
        self.password = mt5_config.get('password') or os.getenv('MT5_PASSWORD')
        self.server = mt5_config.get('server') or os.getenv('MT5_SERVER')
        self.path = mt5_config.get('path') or os.getenv('MT5_PATH', '')
        self.connected = False
        
        if not self.login or not self.password or not self.server:
            print("Warning: MT5_LOGIN, MT5_PASSWORD, or MT5_SERVER sepertinya belum di-set.")

    def connect(self):
        try:
            if not self.login:
                print("Connection failed: MT5_LOGIN invalid or not set.")
                return False
                
            if self.path:
                if not mt5.initialize(path=self.path, login=self.login, password=self.password, server=self.server):
                    print(f"MT5 initialization failed (with path): {mt5.last_error()}")
                    return False
            else:
                if not mt5.initialize(login=self.login, password=self.password, server=self.server):
                    print(f"MT5 initialization failed (no path): {mt5.last_error()}")
                    return False
            
            account_info = mt5.account_info()
            if account_info is None:
                print(f"Failed to get account info: {mt5.last_error()}")
                mt5.shutdown()
                return False
            
            if account_info.currency != "USD":
                print(f"======================================================")
                print(f"WARNING: Mata uang akun adalah {account_info.currency}, BUKAN USD.")
                print("Bot akan tetap berjalan, tapi pastikan logic trading/risk")
                print("Anda sudah sesuai dengan mata uang ini.")
                print(f"======================================================")
            
            self.connected = True
            
            account_type = "Demo"
            if account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
                account_type = "Real"
            elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
                account_type = "Contest"
            
            print(f"Connected to MT5 - Account: {account_info.login} ({account_type})")
            print(f"Server: {account_info.server}, Leverage: 1:{account_info.leverage}")
            print(f"Balance: {account_info.balance:.2f} {account_info.currency}")
            
            return True
            
        except Exception as e:
            print(f"Error connecting to MT5: {e}")
            return False
    
    def disconnect(self):
        mt5.shutdown()
        self.connected = False
        print("Disconnected from MT5")
    
    def ensure_connected(self):
        if not mt5.terminal_info():
            print("MT5 terminal disconnected! Reconnecting...")
            self.disconnect()
            return self.connect()
        return True
    
    def get_account_info(self):
        if not self.ensure_connected():
            return None
        
        account_info = mt5.account_info()
        if account_info is None:
            print(f"Failed to get account info: {mt5.last_error()}")
            return None
        
        account_type = "Demo"
        if account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
            account_type = "Real"
        elif account_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
            account_type = "Contest"
            
        return {
            'login': account_info.login,
            'server': account_info.server,
            'currency': account_info.currency,
            'account_type': account_type,
            'leverage': account_info.leverage,
            'balance': account_info.balance,
            'equity': account_info.equity,
            'margin': account_info.margin,
            'free_margin': account_info.margin_free,
            'margin_level': account_info.margin_level if account_info.margin > 0 else 0,
            'profit': account_info.profit
        }
    
    def get_symbol_info(self, symbol):
        if not self.ensure_connected():
            return None
        
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            print(f"Symbol {symbol} not found")
            return None
        
        if not symbol_info.visible:
            if not mt5.symbol_select(symbol, True):
                print(f"Failed to select {symbol}")
                return None
            symbol_info = mt5.symbol_info(symbol)
        
        return {
            'name': symbol_info.name,
            'bid': symbol_info.bid,
            'ask': symbol_info.ask,
            'spread': symbol_info.spread,
            'point': symbol_info.point,
            'digits': symbol_info.digits,
            'volume_min': symbol_info.volume_min,
            'volume_max': symbol_info.volume_max,
            'volume_step': symbol_info.volume_step,
            'trade_contract_size': symbol_info.trade_contract_size,
            'trade_mode': symbol_info.trade_mode 
        }
    
    def get_rates(self, symbol, timeframe, count=500):
        if not self.ensure_connected():
            return None
        
        timeframe_map = {
            'M1': mt5.TIMEFRAME_M1, 'M5': mt5.TIMEFRAME_M5, 'M15': mt5.TIMEFRAME_M15,
            'M30': mt5.TIMEFRAME_M30, 'H1': mt5.TIMEFRAME_H1, 'H4': mt5.TIMEFRAME_H4,
            'D1': mt5.TIMEFRAME_D1
        }
        tf = timeframe_map.get(timeframe.upper(), mt5.TIMEFRAME_M5)
        
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            print(f"Failed to get rates for {symbol}")
            return None
        
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df

    def get_price_data(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        if not self.ensure_connected():
            # print("Error: Tidak terhubung ke MT5. Gagal get_price_data.")
            return None
            
        tf_map = {
            'M1': mt5.TIMEFRAME_M1, 'M5': mt5.TIMEFRAME_M5, 'M15': mt5.TIMEFRAME_M15,
            'M30': mt5.TIMEFRAME_M30, 'H1': mt5.TIMEFRAME_H1, 'H4': mt5.TIMEFRAME_H4,
            'D1': mt5.TIMEFRAME_D1,
        }
        mt5_timeframe = tf_map.get(timeframe.upper(), mt5.TIMEFRAME_M5)
        
        try:
            rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, bars)
            if rates is None or len(rates) == 0:
                # print(f"Error: Gagal mengambil data 'rates' untuk {symbol} {timeframe}. (Data: {rates})")
                return None

            data = pd.DataFrame(rates)
            
            data['time'] = pd.to_datetime(data['time'], unit='s')
            
            data.set_index('time', inplace=True)
            
            data.rename(columns={
                'open': 'open', 'high': 'high', 'low': 'low', 
                'close': 'close', 'tick_volume': 'volume'
            }, inplace=True)
            
            return data

        except Exception as e:
            print(f"Exception saat get_price_data: {e}")
            return None

    def get_rates_range(self, symbol, timeframe, start_time, end_time):
        if not self.ensure_connected():
            return None

        timeframe_map = {
            'M1': mt5.TIMEFRAME_M1, 'M5': mt5.TIMEFRAME_M5, 'M15': mt5.TIMEFRAME_M15,
            'M30': mt5.TIMEFRAME_M30, 'H1': mt5.TIMEFRAME_H1, 'H4': mt5.TIMEFRAME_H4,
            'D1': mt5.TIMEFRAME_D1, 'W1': mt5.TIMEFRAME_W1, 'MN1': mt5.TIMEFRAME_MN1
        }
        tf = timeframe_map.get(timeframe.upper(), mt5.TIMEFRAME_M5)
        
        if start_time.tzinfo is None:
            start_time = pytz.utc.localize(start_time)
        if end_time.tzinfo is None:
            end_time = pytz.utc.localize(end_time)

        try:
            rates = mt5.copy_rates_range(symbol, tf, start_time, end_time)
            
            if rates is None or len(rates) == 0:
                print(f"Failed to get rates for {symbol} from {start_time} to {end_time}")
                return None
            
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df.set_index('time', inplace=True) 
            
            print(f"Successfully fetched {len(df)} bars for {symbol} {timeframe}.")
            return df

        except Exception as e:
            print(f"Error in get_rates_range: {e}")
            return None
    
    def get_positions(self, symbol=None):
        if not self.ensure_connected():
            return []
        
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()
        
        if positions is None or len(positions) == 0:
            return []
        
        positions_list = []
        for pos in positions:
            positions_list.append({
                'ticket': pos.ticket,
                'symbol': pos.symbol,
                'type': 'BUY' if pos.type == mt5.ORDER_TYPE_BUY else 'SELL',
                'volume': pos.volume,
                'price_open': pos.price_open,
                'sl': pos.sl,
                'tp': pos.tp,
                'profit': pos.profit,
                'time': datetime.fromtimestamp(pos.time)
            })
        
        return positions_list
    
    def _normalize_volume(self, volume: float, symbol_info: dict) -> float:
        step = symbol_info.get('volume_step', 0.01)
        min_vol = symbol_info.get('volume_min', 0.01)
        max_vol = symbol_info.get('volume_max', 100.0)
        
        if step > 0:
            volume = step * round(volume / step)
        
        volume = max(volume, min_vol)
        volume = min(volume, max_vol)
        
        # Round ke precision yang aman (untuk 0.001 step)
        precision = int(-log10(step)) if step < 1 else 2
        return round(volume, precision)
    
    def _get_deviation(self, symbol_info: dict) -> int:
        spread = symbol_info.get('spread', 0)
        name = symbol_info.get('name', '').upper()
        
        # [REVISI V3] Base deviation jangan pelit
        base_deviation = 20 
        
        # Khusus XAUUSD/GOLD, marketnya liar
        if 'XAU' in name or 'GOLD' in name:
            base_deviation = 50 # Default 5 pip toleransi buat Gold
        
        # Kalau spread melebar (tanda volatilitas), toleransi slippage harus DITAMBAH
        # Logic: Deviation = Base + Spread saat ini
        # Jadi kalau spread 30, deviation 80. Kalau spread 60, deviation 110.
        # Ini memastikan order KEKERJA meskipun harga lari.
        
        total_deviation = base_deviation + spread
        
        # Cap max deviation biar ga kejauhan (misal max 200 points)
        return min(total_deviation, 200)
    
    def send_order(self, symbol, order_type, volume, sl=0.0, tp=0.0, comment=""):
        if not self.ensure_connected():
            return None
        
        symbol_info = self.get_symbol_info(symbol)
        if not symbol_info:
            return None
        
        volume = self._normalize_volume(volume, symbol_info)
        if volume <= 0:
            print(f"Volume setelah normalisasi: {volume}. Order dibatalkan.")
            return None
        
        deviation = self._get_deviation(symbol_info)
        
        trade_type = mt5.ORDER_TYPE_BUY if order_type == "BUY" else mt5.ORDER_TYPE_SELL
        price = symbol_info['ask'] if order_type == "BUY" else symbol_info['bid']
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": trade_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": deviation,
            "magic": 234000,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        # --- SMART FILLING MODE SELECTOR ---
        filling_modes = [
            mt5.ORDER_FILLING_FOK,    # Prioritas 1: Fill or Kill
            mt5.ORDER_FILLING_IOC,    # Prioritas 2: Immediate or Cancel
            mt5.ORDER_FILLING_RETURN  # Prioritas 3: Return
        ]
        
        result = None
        
        for mode in filling_modes:
            request["type_filling"] = mode
            result = mt5.order_send(request)
            
            if result is not None:
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"Order SENT ({mode}): {order_type} {volume} {symbol} @ {result.price}, Ticket: {result.order}")
                    return {
                        'ticket': result.order,
                        'volume': result.volume,
                        'price': result.price,
                        'comment': result.comment
                    }
                elif result.retcode == 10030: # Unsupported filling mode
                    continue # Coba mode berikutnya
                else:
                    print(f"Order failed (Mode {mode}): {result.retcode} - {result.comment}")
                    break
            else:
                print(f"Order send failed (Result None) for mode {mode}")
        
        if result and result.retcode != mt5.TRADE_RETCODE_DONE:
             print(f"All filling modes failed. Last error: {result.comment}")
             
        return None
    
    def close_position(self, ticket):
        if not self.ensure_connected():
            return False
        
        positions = mt5.positions_get(ticket=ticket)
        if positions is None or len(positions) == 0:
            print(f"Position {ticket} not found")
            return False
        
        position = positions[0]
        symbol_info = self.get_symbol_info(position.symbol)
        if not symbol_info:
            return False
        
        trade_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = symbol_info['bid'] if position.type == mt5.ORDER_TYPE_BUY else symbol_info['ask']
        
        deviation = self._get_deviation(symbol_info)
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": trade_type,
            "position": ticket,
            "price": price,
            "deviation": deviation,
            "magic": 234000,
            "comment": "Close position",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        
        # --- SMART FILLING LOOP FOR CLOSE ---
        filling_modes = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
        
        for mode in filling_modes:
            request["type_filling"] = mode
            result = mt5.order_send(request)
            
            if result is not None:
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"Position CLOSED: Ticket {ticket}, Symbol {position.symbol}")
                    return True
                elif result.retcode == 10030:
                    continue
                else:
                    print(f"Close failed: {result.retcode} - {result.comment}")
                    return False
        
        return False
    
    def modify_position(self, ticket, sl=None, tp=None):
        if not self.ensure_connected():
            return False
        
        positions = mt5.positions_get(ticket=ticket)
        if positions is None or len(positions) == 0:
            return False
        
        position = positions[0]
        sl_price = sl if sl is not None else position.sl
        tp_price = tp if tp is not None else position.tp
        
        if sl_price == position.sl and tp_price == position.tp:
            return True 
            
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": position.symbol,
            "position": ticket,
            "sl": sl_price,
            "tp": tp_price,
        }
        
        result = mt5.order_send(request)
        
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            return False
        
        return True

    def partial_close_position(self, ticket, lot_to_close, comment=""):
        if not self.ensure_connected():
            return False
        
        positions = mt5.positions_get(ticket=ticket)
        if positions is None or len(positions) == 0:
            return False
        
        position = positions[0]
        symbol_info = self.get_symbol_info(position.symbol)
        
        lot_to_close = self._normalize_volume(lot_to_close, symbol_info)
        if lot_to_close >= position.volume:
            return self.close_position(ticket)

        deviation = self._get_deviation(symbol_info)
        
        trade_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = symbol_info['bid'] if position.type == mt5.ORDER_TYPE_BUY else symbol_info['ask']
            
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": lot_to_close,
            "type": trade_type,
            "position": ticket, 
            "price": price,
            "deviation": deviation,
            "magic": 234000,
            "comment": comment if comment else f"Partial close of #{ticket}",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        
        # --- SMART FILLING LOOP FOR PARTIAL ---
        filling_modes = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
        
        for mode in filling_modes:
            request["type_filling"] = mode
            result = mt5.order_send(request)
            
            if result is not None:
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"Position PARTIALLY CLOSED: Ticket {ticket}, Closed {lot_to_close} lots")
                    return True
                elif result.retcode == 10030:
                    continue
                else:
                    return False
        
        return False
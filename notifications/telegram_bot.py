import os
import requests
import telebot
from telebot import types
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any
from dotenv import load_dotenv

load_dotenv()

# ============================================
# CONFIG & CONSTANTS
# ============================================
MAX_RATE_LIMIT = 1.0  # Seconds between user commands
RETRY_DELAY = 5       # Seconds before reconnect polling
NOTIF_RATE_LIMIT = 2.0  # Seconds between similar notifications


class TelegramBot:
    def __init__(self, sm, main_bot_instance=None):
        """
        Unified Telegram Bot with Interactive Commands + Rich Notifications
        
        Args:
            sm: SettingsManager instance
            main_bot_instance: Reference to main trading bot for control
        """
        self.sm = sm
        self.settings = sm.load_settings()
        
        # Load configuration
        tg_config = self.settings.get('telegram', {})
        
        self.bot_token = tg_config.get('api_token') or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = str(tg_config.get('chat_id') or os.getenv('TELEGRAM_CHAT_ID', ''))
        
        json_enabled = tg_config.get('enabled')
        if json_enabled is not None:
            self.enabled = bool(json_enabled)
        else:
            self.enabled = bool(self.bot_token and self.chat_id)
        
        # Reference to main bot for control
        self.main_bot = main_bot_instance
        
        # Rate limiting
        self.last_message_time = {}
        self.last_command_time = 0
        self.min_interval = NOTIF_RATE_LIMIT
        
        # Polling state
        self.is_polling = False
        self.bot = None
        
        if not self.enabled:
            print("⚠️  Telegram notifications disabled (check config/settings.json or .env)")
        elif self.bot_token:
            try:
                self.bot = telebot.TeleBot(self.bot_token, threaded=False)
                if self.main_bot:
                    self._setup_handlers()
                print("✅ Telegram bot initialized successfully")
            except Exception as e:
                print(f"❌ Telegram Init Error: {e}")
    
    # ============================================
    # SECURITY & RATE LIMITING
    # ============================================
    
    def _check_auth(self, message) -> bool:
        """Security Check: Authorized User & Rate Limit"""
        user_id = str(message.chat.id)
        
        # Whitelist check
        if user_id != self.chat_id:
            print(f"🚨 UNAUTHORIZED TELEGRAM ACCESS: ID {user_id}")
            return False
        
        # Rate limiting for commands
        now = time.time()
        if (now - self.last_command_time) < MAX_RATE_LIMIT:
            return False
            
        self.last_command_time = now
        return True
    
    def _can_send(self, message_type: str) -> bool:
        """Rate limiting check for outgoing notifications"""
        now = datetime.now()
        if message_type in self.last_message_time:
            time_diff = (now - self.last_message_time[message_type]).total_seconds()
            if time_diff < self.min_interval:
                return False
        
        self.last_message_time[message_type] = now
        return True
    
    # ============================================
    # INTERACTIVE COMMAND SYSTEM
    # ============================================
    
    def start_listening(self):
        
        if not self.bot or not self.enabled:
            return
        
        def listener():
            print("📱 Telegram Command Center: ONLINE")
            self.is_polling = True
            while self.is_polling:
                try:
                    self.bot.infinity_polling(timeout=20, long_polling_timeout=10)
                except Exception as e:
                    print(f"⚠️ Telegram Polling Error: {e}")
                    time.sleep(RETRY_DELAY)
        
        t = threading.Thread(target=listener, daemon=True)
        t.start()
    
    def stop_listening(self):
        """Stop bot polling gracefully"""
        self.is_polling = False
        if self.bot:
            try:
                self.bot.stop_polling()
            except:
                pass
    
    def _setup_handlers(self):
        """Register command and callback handlers"""
        
        @self.bot.message_handler(commands=['start', 'help', 'menu'])
        def send_menu(message):
            if not self._check_auth(message):
                return
            self._send_main_menu(message.chat.id)
        
        @self.bot.message_handler(commands=['status'])
        def send_status(message):
            if not self._check_auth(message):
                return
            self._send_status_report(message.chat.id)
        
        @self.bot.message_handler(commands=['positions'])
        def manage_positions(message):
            if not self._check_auth(message):
                return
            self._send_position_list(message.chat.id)
        
        @self.bot.callback_query_handler(func=lambda call: True)
        def handle_query(call):
            if str(call.message.chat.id) != self.chat_id:
                return
            
            cmd = call.data
            
            try:
                if cmd == "menu_refresh":
                    self._send_status_report(call.message.chat.id, 
                                           update_msg_id=call.message.message_id)
                
                elif cmd == "menu_positions":
                    self._send_position_list(call.message.chat.id)
                
                elif cmd == "bot_pause":
                    self.main_bot.bot_state = "PAUSED_USER"
                    self.bot.answer_callback_query(call.id, "Bot PAUSED ⏸️")
                    self._send_main_menu(call.message.chat.id, "⏸️ *BOT IS PAUSED*")
                
                elif cmd == "bot_resume":
                    self.main_bot.bot_state = "RUNNING"
                    self.bot.answer_callback_query(call.id, "Bot RESUMED ▶️")
                    self._send_main_menu(call.message.chat.id, "▶️ *BOT IS RUNNING*")
                
                elif cmd == "panic_confirm":
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    markup.add(
                        types.InlineKeyboardButton("🔥 YES, CLOSE ALL", 
                                                 callback_data="panic_execute"),
                        types.InlineKeyboardButton("🔙 Cancel", 
                                                 callback_data="menu_main")
                    )
                    self.bot.edit_message_text(
                        "⚠️ *CONFIRMATION REQUIRED*\nClose ALL positions immediately?",
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='Markdown',
                        reply_markup=markup
                    )
                
                elif cmd == "panic_execute":
                    count = self.main_bot.executor.close_all_positions(
                        reason="Telegram Panic"
                    )
                    self.bot.answer_callback_query(call.id, f"Closed {count} positions!")
                    self.bot.send_message(
                        call.message.chat.id,
                        f"✅ *PANIC EXECUTION COMPLETE*\nClosed {count} positions.",
                        parse_mode='Markdown'
                    )
                    self._send_main_menu(call.message.chat.id)
                
                elif cmd.startswith("close_"):
                    ticket = int(cmd.split("_")[1])
                    if self.main_bot.mt5.close_position(ticket):
                        self.bot.answer_callback_query(call.id, "Closed ✅")
                        self._send_position_list(
                            call.message.chat.id,
                            update_msg_id=call.message.message_id
                        )
                    else:
                        self.bot.answer_callback_query(call.id, "❌ Failed")
                
                elif cmd.startswith("mode_"):
                    new_mode = cmd.split("_")[1]
                    self.main_bot.sm.set_trading_mode(new_mode)
                    self.bot.answer_callback_query(call.id, f"Mode: {new_mode}")
                    self._send_main_menu(
                        call.message.chat.id,
                        f"🔄 Mode changed to *{new_mode}*"
                    )
                
                elif cmd == "menu_main":
                    self._send_main_menu(call.message.chat.id)
            
            except Exception as e:
                print(f"Callback Error: {e}")
    
    # ============================================
    # UI BUILDERS
    # ============================================
    
    def _send_main_menu(self, chat_id, title="🎮 *COMMAND CENTER*"):
        """Send interactive main menu"""
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📊 Status", callback_data="menu_refresh"),
            types.InlineKeyboardButton("💼 Positions", callback_data="menu_positions")
        )
        
        if self.main_bot:
            state_icon = "⏸️ Pause" if self.main_bot.bot_state == "RUNNING" else "▶️ Resume"
            state_cb = "bot_pause" if self.main_bot.bot_state == "RUNNING" else "bot_resume"
            
            markup.add(
                types.InlineKeyboardButton(state_icon, callback_data=state_cb),
                types.InlineKeyboardButton("🛑 CLOSE ALL", callback_data="panic_confirm")
            )
            
            markup.add(
                types.InlineKeyboardButton("🤖 Auto", callback_data="mode_AUTO"),
                types.InlineKeyboardButton("🎯 Sniper", callback_data="mode_SNIPER_ONLY"),
                types.InlineKeyboardButton("📈 Trend", callback_data="mode_TREND_ONLY")
            )
        
        try:
            self.bot.send_message(
                chat_id,
                title,
                parse_mode='Markdown',
                reply_markup=markup
            )
        except Exception as e:
            print(f"Error sending main menu: {e}")
    
    def _send_status_report(self, chat_id, update_msg_id=None):
        """Send live status report"""
        if not self.main_bot:
            msg = "⚠️ *Main bot not connected*"
        else:
            acc = self.main_bot.mt5.get_account_info()
            
            if not acc:
                msg = "⚠️ *MT5 Disconnected*"
            else:
                pnl = self.main_bot.ptm.today_profit if hasattr(self.main_bot, 'ptm') else 0
                icon = "🟢" if pnl >= 0 else "🔴"
                
                msg = f"""
📊 *LIVE STATUS*
━━━━━━━━━━━━━━━━
💵 Balance: `${acc['balance']:,.2f}`
💎 Equity: `${acc['equity']:,.2f}`
{icon} Day P/L: `${pnl:+.2f}`

⚙️ *System:*
• Mode: `{self.main_bot.sm.get_trading_mode()}`
• Regime: `{getattr(self.main_bot, 'current_regime', 'N/A')}`
• Session: `{getattr(self.main_bot, 'active_session_label', 'N/A')}`
• State: `{self.main_bot.bot_state}`
"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("🔄 Refresh", callback_data="menu_refresh"),
            types.InlineKeyboardButton("🔙 Menu", callback_data="menu_main")
        )
        
        if update_msg_id:
            try:
                self.bot.edit_message_text(
                    msg,
                    chat_id,
                    update_msg_id,
                    parse_mode='Markdown',
                    reply_markup=markup
                )
            except:
                pass
        else:
            self.bot.send_message(
                chat_id,
                msg,
                parse_mode='Markdown',
                reply_markup=markup
            )
    
    def _send_position_list(self, chat_id, update_msg_id=None):
        """Send list of open positions with close buttons"""
        if not self.main_bot:
            msg = "⚠️ *Main bot not connected*"
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Menu", callback_data="menu_main"))
        else:
            positions = self.main_bot.mt5.get_positions(self.main_bot.symbol)
            
            if not positions:
                msg = "💼 *No Open Positions*"
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🔙 Menu", callback_data="menu_main"))
            else:
                total_pl = sum(p['profit'] for p in positions)
                msg = f"""
💼 *OPEN POSITIONS ({len(positions)})*
Total P/L: `${total_pl:+.2f}`
━━━━━━━━━━━━━━━━
"""
                markup = types.InlineKeyboardMarkup()
                
                for p in positions[:8]:  # Max 8 buttons to avoid limit
                    icon = "🟢" if p['profit'] >= 0 else "🔴"
                    btn_text = f"{icon} #{p['ticket']} {p['type']} (${p['profit']:.2f})"
                    markup.add(
                        types.InlineKeyboardButton(
                            btn_text,
                            callback_data=f"close_{p['ticket']}"
                        )
                    )
                
                if len(positions) > 8:
                    msg += f"\n_... and {len(positions) - 8} more positions_"
                
                markup.add(types.InlineKeyboardButton("🔙 Menu", callback_data="menu_main"))
        
        if update_msg_id:
            try:
                self.bot.edit_message_text(
                    msg,
                    chat_id,
                    update_msg_id,
                    parse_mode='Markdown',
                    reply_markup=markup
                )
            except:
                pass
        else:
            self.bot.send_message(
                chat_id,
                msg,
                parse_mode='Markdown',
                reply_markup=markup
            )
    
    # ============================================
    # CORE MESSAGING
    # ============================================
    
    def send_message(self, message: str, parse_mode: str = 'Markdown',
                     message_type: str = 'general') -> bool:
        """Send message to Telegram with rate limiting"""
        if not self.enabled or not self.bot:
            return False
        
        if message_type != 'critical' and not self._can_send(message_type):
            return False
        
        try:
            self.bot.send_message(
                self.chat_id,
                message,
                parse_mode=parse_mode,
                disable_web_page_preview=True
            )
            return True
        except Exception as e:
            print(f"Telegram send error: {e}")
            return False
    
    # ============================================
    # HELPER FUNCTIONS
    # ============================================
    
    def _format_duration(self, seconds: int) -> str:
        """Format duration in human readable format"""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}m {seconds % 60}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}h {minutes}m"
    
    def _get_progress_bar(self, current: float, target: float, length: int = 10) -> str:
        """Generate progress bar"""
        if target <= 0:
            return "▱" * length
        
        percentage = min(abs(current / target), 1.0)
        filled = int(percentage * length)
        
        if current >= 0:
            bar = "▰" * filled + "▱" * (length - filled)
            return f"{bar} {percentage*100:.0f}%"
        else:
            bar = "▱" * (length - filled) + "▰" * filled
            return f"{bar} {percentage*100:.0f}%"
    
    # ============================================
    # ENHANCED NOTIFICATIONS
    # ============================================
    
    def notify_entry(self, order_info: Dict, signal_context: Optional[Dict] = None,
                     account_info: Optional[Dict] = None):
        """🎯 Enhanced entry notification with full context"""
        try:
            ticket = order_info.get('ticket', 'N/A')
            symbol = order_info.get('symbol', 'N/A')
            order_type = order_info.get('type', 'N/A')
            volume = order_info.get('lot', 0.0)
            entry_price = order_info.get('entry', 0.0)
            sl = order_info.get('sl', 0.0)
            tp = order_info.get('tp', 0.0)
            
            risk_pips = 0.0
            reward_pips = 0.0
            
            if order_type == 'BUY':
                risk_pips = abs(entry_price - sl) if sl > 0 else 0
                reward_pips = abs(tp - entry_price) if tp > 0 else 0
            else:  # SELL
                risk_pips = abs(sl - entry_price) if sl > 0 else 0
                reward_pips = abs(entry_price - tp) if tp > 0 else 0
            
            risk_usd = order_info.get('risk', 0.0)
            reward_usd = (reward_pips / risk_pips) * risk_usd if risk_pips > 0 else 0.0
            rr_ratio = reward_pips / risk_pips if risk_pips > 0 else 0
            
            direction_emoji = "🟢" if order_type == 'BUY' else "🔴"
            
            message = f"""
{direction_emoji} *NEW TRADE EXECUTED*
━━━━━━━━━━━━━━━━━━━

*Trade Details:*
• Symbol: `{symbol}`
• Type: *{order_type}*
• Volume: `{volume} lots`
• Ticket: `#{ticket}`

*Price Levels:*
• Entry: `{entry_price:.5f}`
• Stop Loss: `{sl:.5f}` (-${risk_usd:.2f})
• Take Profit: `{tp:.5f}` (+${reward_usd:.2f})
• Risk:Reward = `1:{rr_ratio:.2f}`
"""
            
            if account_info:
                balance = account_info.get('balance', 0)
                equity = account_info.get('equity', 0)
                risk_percent = (risk_usd / balance * 100) if balance > 0 else 0
                
                message += f"""
*Account Status:*
• Balance: `${balance:.2f}`
• Equity: `${equity:.2f}`
• Risk: `{risk_percent:.2f}%` of balance
"""
            
            if signal_context:
                strategy = signal_context.get('strategy_mode', 'N/A')
                session = signal_context.get('session', 'N/A')
                regime = signal_context.get('regime', 'N/A')
                
                score = signal_context.get('score', 0.0)
                min_conf = signal_context.get('min_conf', 0.0)
                
                score_bar = "⭐" * int(score)
                
                message += f"""
*Signal Context:*
• Strategy: `{strategy}`
• Session: `{session.upper()}`
• Confidence: `{score:.1f} / {min_conf:.1f}` {score_bar}
• Market Regime: `{regime}`
"""
                
                indicators = signal_context.get('indicators', {})
                if indicators:
                    message += "\n*Technical Indicators:*\n"
                    
                    rsi = indicators.get('rsi_value')
                    if rsi is not None:
                        rsi_status = "Oversold" if rsi < 30 else "Overbought" if rsi > 70 else "Neutral"
                        message += f"• RSI: `{rsi:.1f}` ({rsi_status})\n"
                    
                    macd = indicators.get('macd_histogram')
                    if macd is not None:
                        macd_status = "Bullish" if macd > 0 else "Bearish"
                        message += f"• MACD: `{macd:.4f}` ({macd_status})\n"
                    
                    ma_trend = indicators.get('ma_trend')
                    if ma_trend:
                        message += f"• MA Trend: `{ma_trend}`\n"
                    
                    atr = indicators.get('atr')
                    if atr is not None:
                        message += f"• ATR: `{atr:.5f}`\n"
            
            message += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
            
            self.send_message(message, message_type='entry')
            
        except Exception as e:
            print(f"Error in notify_entry: {e}")
            self.notify_error(f"Entry notification error: {str(e)}")
    
    def notify_exit(self, exit_info: Dict, daily_stats: Optional[Dict] = None):
        """💰 Enhanced exit notification with daily progress"""
        try:
            ticket = exit_info.get('ticket', 'N/A')
            profit = exit_info.get('profit', 0.0)
            reason = exit_info.get('reason', 'Unknown')
            duration = exit_info.get('duration', 'N/A')
            
            if isinstance(duration, (int, float)):
                duration = self._format_duration(int(duration))
            
            if profit > 0:
                emoji = "💚"
                status = "WIN"
            elif profit < 0:
                emoji = "❌"
                status = "LOSS"
            else:
                emoji = "⚪"
                status = "BREAKEVEN"
            
            message = f"""
{emoji} *TRADE CLOSED - {status}*
━━━━━━━━━━━━━━━━━━━

• Ticket: `#{ticket}`
• Result: `${profit:+.2f}`
• Duration: `{duration}`
• Reason: `{reason}`
"""
            
            if daily_stats:
                today_pnl = daily_stats.get('today_pnl', 0.0)
                today_trades = daily_stats.get('today_trades', 0)
                win_streak = daily_stats.get('win_streak', 0)
                loss_streak = daily_stats.get('loss_streak', 0)
                
                message += f"""
*Today's Performance:*
• Daily P/L: `${today_pnl:+.2f}`
• Total Trades: `{today_trades}`
"""
                
                if win_streak > 0:
                    message += f"• 🔥 Win Streak: `{win_streak}`\n"
                elif loss_streak > 0:
                    message += f"• ⚠️ Loss Streak: `{loss_streak}`\n"
                
                daily_target = daily_stats.get('daily_target', 0)
                if daily_target > 0:
                    progress_bar = self._get_progress_bar(today_pnl, daily_target)
                    message += f"• Target Progress: {progress_bar}\n"
            
            message += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
            
            self.send_message(message, message_type='exit')
            
        except Exception as e:
            print(f"Error in notify_exit: {e}")
            self.notify_error(f"Exit notification error: {str(e)}")
    
    def notify_daily_update(self, progress: Dict):
        """📊 Daily P/L update with enhanced metrics"""
        try:
            if not progress.get('enabled', False):
                return
                
            current_pnl = progress.get('current', 0.0)
            target = progress.get('target', 0.0)
            trades = progress.get('trades', 0)
            wins = progress.get('wins', 0)
            losses = progress.get('losses', 0)
            status = progress.get('status', 'NEUTRAL')
            
            win_rate = (wins / trades * 100) if trades > 0 else 0
            
            if status == 'PROFIT':
                emoji = "📈"
            elif status == 'LOSS':
                emoji = "📉"
            else:
                emoji = "😐"
            
            message = f"""
{emoji} *DAILY P/L UPDATE*
━━━━━━━━━━━━━━━━━━━

• Today's P/L: `${current_pnl:+.2f}`
• Total Trades: `{trades}` ({wins}W/{losses}L)
• Win Rate: `{win_rate:.1f}%`
• Status: `{status}`
"""
            
            if target > 0:
                progress_bar = self._get_progress_bar(current_pnl, target)
                message += f"• Daily Target: {progress_bar}\n"
                remaining = target - current_pnl
                message += f"• Remaining: `${remaining:+.2f}`\n"
            
            self.send_message(message, message_type='daily_update')
            
        except Exception as e:
            print(f"Error in notify_daily_update: {e}")
    
    def notify_breakeven(self, ticket: int, new_sl: float, locked_profit: float = 0.0):
        """⚖️ Enhanced breakeven notification"""
        try:
            message = f"""
⚖️ *BREAKEVEN ACTIVATED*
━━━━━━━━━━━━━━━━━━━

• Ticket: `#{ticket}`
• New SL: `{new_sl:.5f}`
• Status: `Risk-Free Trade`
"""
            if locked_profit > 0:
                message += f"• Locked Profit: `${locked_profit:.2f}`\n"
            
            message += f"\n⏰ {datetime.now().strftime('%H:%M:%S UTC')}"
            
            self.send_message(message, message_type='breakeven')
            
        except Exception as e:
            print(f"Error in notify_breakeven: {e}")
    
    def notify_trailing_stop(self, ticket: int, new_sl: float, profit_locked: float):
        """🎯 Enhanced trailing stop update"""
        try:
            message = f"""
🎯 *TRAILING STOP UPDATED*
━━━━━━━━━━━━━━━━━━━

• Ticket: `#{ticket}`
• New SL: `{new_sl:.5f}`
• Profit Locked: `${profit_locked:.2f}`
• Status: `Securing gains`

⏰ {datetime.now().strftime('%H:%M:%S UTC')}
"""
            self.send_message(message, message_type='trailing')
            
        except Exception as e:
            print(f"Error in notify_trailing_stop: {e}")
    
    def notify_regime_change(self, old_regime: str, new_regime: str, details: Dict):
        """🔄 Market regime change notification"""
        try:
            regime_emoji = {
                "TRENDING": "📈",
                "RANGING": "↔️",
                "VOLATILE": "⚡",
                "BREAKOUT": "🚀",
                "NEUTRAL": "⚪",
                "UNKNOWN": "❓"
            }
            
            old_emoji = regime_emoji.get(old_regime, "❓")
            new_emoji = regime_emoji.get(new_regime, "❓")
            
            recommendation = details.get('recommendation', {})
            strategy = recommendation.get('strategy', 'N/A')
            lot_mult = recommendation.get('lot_multiplier', 1.0)
            
            message = f"""
🔄 *MARKET REGIME CHANGED*
━━━━━━━━━━━━━━━━━━━

{old_emoji} `{old_regime}` → {new_emoji} `{new_regime}`

*Recommended Adjustments:*
• Strategy: `{strategy}`
• Lot Multiplier: `{lot_mult}x`
• Note: `{recommendation.get('note', 'N/A')}`

*Technical Details:*
• ADX: `{details.get('adx', 'N/A')}`
• ATR Ratio: `{details.get('atr_ratio', 'N/A')}`
• Confidence: `{details.get('confidence', 0)*100:.0f}%`

⏰ {datetime.now().strftime('%H:%M:%S UTC')}
"""
            self.send_message(message, message_type='regime')
            
        except Exception as e:
            print(f"Error in notify_regime_change: {e}")
    
    def notify_risk_alert(self, alert_type: str, details: Dict):
        """🚨 Risk management alerts"""
        try:
            alert_config = {
                'DRAWDOWN': {
                    'emoji': '📉',
                    'title': 'DRAWDOWN ALERT',
                    'color': 'red'
                },
                'LOSING_STREAK': {
                    'emoji': '⚠️',
                    'title': 'LOSING STREAK',
                    'color': 'yellow'
                },
                'MAX_DAILY_LOSS': {
                    'emoji': '🛑',
                    'title': 'DAILY LOSS LIMIT',
                    'color': 'red'
                },
                'MARGIN': {
                    'emoji': '⚡',
                    'title': 'MARGIN WARNING',
                    'color': 'yellow'
                }
            }
            
            config = alert_config.get(alert_type, {'emoji': '⚠️', 'title': 'RISK ALERT'})
            
            message = f"""
{config['emoji']} *{config['title']}*
━━━━━━━━━━━━━━━━━━━

*Alert Details:*
"""
            
            for key, value in details.items():
                message += f"• {key.replace('_', ' ').title()}: `{value}`\n"
            
            message += f"\n⚠️ *Action Required: Review trading parameters*"
            message += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
            
            self.send_message(message, message_type='critical')
            
        except Exception as e:
            print(f"Error in notify_risk_alert: {e}")
    
    def notify_milestone(self, milestone_type: str, details: Dict):
        """💎 Achievement/Milestone notifications"""
        try:
            milestone_config = {
                'PROFIT_TARGET': {'emoji': '🎯', 'title': 'DAILY TARGET REACHED'},
                'WIN_STREAK': {'emoji': '🔥', 'title': 'WIN STREAK'},
                'BEST_DAY': {'emoji': '🏆', 'title': 'NEW BEST DAY'},
                'BALANCE_MILESTONE': {'emoji': '💰', 'title': 'BALANCE MILESTONE'},
            }
            
            config = milestone_config.get(milestone_type, 
                                          {'emoji': '⭐', 'title': 'MILESTONE'})
            
            message = f"""
{config['emoji']} *{config['title']}*
━━━━━━━━━━━━━━━━━━━

"""
            
            for key, value in details.items():
                message += f"• {key.replace('_', ' ').title()}: `{value}`\n"
            
            message += f"\n🎉 *Congratulations!*"
            message += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
            
            self.send_message(message, message_type='milestone')
            
        except Exception as e:
            print(f"Error in notify_milestone: {e}")
    
    def notify_session_summary(self, session: str, stats: Dict):
        """📊 Trading session summary (Asia/London/NY)"""
        try:
            session_emoji = {
                'ASIA': '🌏',
                'LONDON': '🇬🇧',
                'NY': '🗽'
            }
            
            emoji = session_emoji.get(session.upper(), '🌍')
            
            trades = stats.get('trades', 0)
            pnl = stats.get('pnl', 0.0)
            wins = stats.get('wins', 0)
            losses = stats.get('losses', 0)
            win_rate = (wins / trades * 100) if trades > 0 else 0
            
            status_emoji = "✅" if pnl > 0 else "❌" if pnl < 0 else "⚪"
            
            message = f"""
{emoji} *{session.upper()} SESSION SUMMARY*
━━━━━━━━━━━━━━━━━━━

{status_emoji} Session P/L: `${pnl:+.2f}`
• Total Trades: `{trades}` ({wins}W/{losses}L)
• Win Rate: `{win_rate:.1f}%`
• Best Trade: `${stats.get('best_trade', 0):+.2f}`
• Worst Trade: `${stats.get('worst_trade', 0):+.2f}`

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
            self.send_message(message, message_type='session')
            
        except Exception as e:
            print(f"Error in notify_session_summary: {e}")
    
    def notify_daily_summary(self, summary: Dict):
        """📊 Enhanced daily performance summary"""
        try:
            total_trades = summary.get('total_trades', 0)
            wins = summary.get('wins', 0)
            losses = summary.get('losses', 0)
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            
            total_pnl = summary.get('total_pnl', 0.0)
            best_trade = summary.get('best_trade', 0.0)
            worst_trade = summary.get('worst_trade', 0.0)
            
            if total_pnl > 0:
                perf_emoji = "🎉"
                status = "PROFITABLE DAY"
            elif total_pnl < 0:
                perf_emoji = "😔"
                status = "LOSS DAY"
            else:
                perf_emoji = "😐"
                status = "BREAKEVEN DAY"
            
            message = f"""
{perf_emoji} *DAILY SUMMARY - {status}*
━━━━━━━━━━━━━━━━━━━

*Performance:*
• Total P/L: `${total_pnl:+.2f}`
• Win Rate: `{win_rate:.1f}%` ({wins}W/{losses}L)
• Total Trades: `{total_trades}`

*Trade Analysis:*
• Best Trade: `${best_trade:+.2f}`
• Worst Trade: `${worst_trade:+.2f}`
• Avg Win: `${summary.get('avg_win', 0):+.2f}`
• Avg Loss: `${summary.get('avg_loss', 0):+.2f}`

*Risk Metrics:*
• Max Drawdown: `{summary.get('max_drawdown', 0):.2f}%`
• Profit Factor: `{summary.get('profit_factor', 0):.2f}`
• Sharpe Ratio: `{summary.get('sharpe_ratio', 0):.2f}`
"""
            
            sessions = summary.get('sessions', {})
            if sessions:
                message += "\n*Session Breakdown:*\n"
                for session, pnl in sessions.items():
                    emoji = "✅" if pnl > 0 else "❌" if pnl < 0 else "⚪"
                    message += f"• {session}: {emoji} `${pnl:+.2f}`\n"
            
            message += f"\n📅 {datetime.now().strftime('%Y-%m-%d')}"
            
            self.send_message(message, message_type='daily_summary')
            
        except Exception as e:
            print(f"Error in notify_daily_summary: {e}")
    
    def notify_weekly_summary(self, summary: Dict):
        """📈 Weekly performance summary"""
        try:
            total_pnl = summary.get('total_pnl', 0.0)
            total_trades = summary.get('total_trades', 0)
            best_day = summary.get('best_day', 0.0)
            worst_day = summary.get('worst_day', 0.0)
            avg_daily = summary.get('avg_daily_pnl', 0.0)
            
            status_emoji = "🚀" if total_pnl > 0 else "📉" if total_pnl < 0 else "➡️"
            
            message = f"""
{status_emoji} *WEEKLY SUMMARY*
━━━━━━━━━━━━━━━━━━━

*Overall Performance:*
• Weekly P/L: `${total_pnl:+.2f}`
• Total Trades: `{total_trades}`
• Best Day: `${best_day:+.2f}`
• Worst Day: `${worst_day:+.2f}`
• Avg Daily P/L: `${avg_daily:+.2f}`

*Statistics:*
• Win Rate: `{summary.get('win_rate', 0):.1f}%`
• Profit Factor: `{summary.get('profit_factor', 0):.2f}`
• Max Drawdown: `{summary.get('max_drawdown', 0):.2f}%`

📅 Week of {summary.get('week_start', 'N/A')}
"""
            self.send_message(message, message_type='weekly')
            
        except Exception as e:
            print(f"Error in notify_weekly_summary: {e}")
    
    def notify_bot_status(self, status: str, details: str = ''):
        """🤖 Bot status change"""
        try:
            status_emoji = {
                'STARTED': '🟢',
                'STOPPED': '🔴',
                'PAUSED': '⏸️',
                'ERROR': '❌',
                'WARNING': '⚠️',
                'CONNECTED': '✅',
                'DISCONNECTED': '🔌'
            }
            
            emoji = status_emoji.get(status, '❓')
            
            message = f"""
{emoji} *BOT STATUS: {status}*
━━━━━━━━━━━━━━━━━━━

{details}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
            message_type = 'critical' if status in ['ERROR', 'STOPPED'] else 'status'
            self.send_message(message, message_type=message_type)
            
        except Exception as e:
            print(f"Error in notify_bot_status: {e}")
    
    def notify_error(self, error_msg: str, severity: str = 'ERROR'):
        """❌ Error notification with severity levels"""
        try:
            severity_config = {
                'CRITICAL': '🚨',
                'ERROR': '❌',
                'WARNING': '⚠️',
                'INFO': 'ℹ️'
            }
            
            emoji = severity_config.get(severity, '❌')
            
            message = f"""
{emoji} *{severity} DETECTED*
━━━━━━━━━━━━━━━━━━━

`{error_msg}`

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
            self.send_message(message, message_type='critical')
            
        except Exception as e:
            print(f"Error in notify_error: {e}")
            print(f"CRITICAL: Could not send error notification: {error_msg}")
    
    def notify_connection_status(self, is_connected: bool, details: str = ''):
        """🔌 MT5 connection status"""
        try:
            if is_connected:
                emoji = "✅"
                status = "CONNECTED"
            else:
                emoji = "🔴"
                status = "DISCONNECTED"
            
            message = f"""
{emoji} *MT5 {status}*
━━━━━━━━━━━━━━━━━━━

{details if details else f'MT5 connection is {status.lower()}'}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
            self.send_message(message, message_type='critical')
            
        except Exception as e:
            print(f"Error in notify_connection_status: {e}")
    
    def notify_strategy_performance(self, strategy_stats: Dict):
        """📊 Per-strategy performance breakdown"""
        try:
            message = f"""
📊 *STRATEGY PERFORMANCE*
━━━━━━━━━━━━━━━━━━━

"""
            for strategy, stats in strategy_stats.items():
                trades = stats.get('trades', 0)
                pnl = stats.get('pnl', 0.0)
                win_rate = stats.get('win_rate', 0.0)
                
                emoji = "✅" if pnl > 0 else "❌" if pnl < 0 else "⚪"
                
                message += f"""
*{strategy}:*
{emoji} P/L: `${pnl:+.2f}` | Trades: `{trades}` | WR: `{win_rate:.1f}%`
"""
            
            message += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
            
            self.send_message(message, message_type='strategy')
            
        except Exception as e:
            print(f"Error in notify_strategy_performance: {e}")
    
    def notify_market_conditions(self, conditions: Dict):
        """🌐 Market conditions update"""
        try:
            volatility = conditions.get('volatility', 'NORMAL')
            trend = conditions.get('trend', 'NEUTRAL')
            volume = conditions.get('volume', 'NORMAL')
            news_impact = conditions.get('news_impact', 'NONE')
            
            vol_emoji = {
                'HIGH': '⚡',
                'NORMAL': '➡️',
                'LOW': '😴'
            }
            
            trend_emoji = {
                'BULLISH': '📈',
                'BEARISH': '📉',
                'NEUTRAL': '↔️'
            }
            
            message = f"""
🌐 *MARKET CONDITIONS UPDATE*
━━━━━━━━━━━━━━━━━━━

*Current Market State:*
• Volatility: {vol_emoji.get(volatility, '➡️')} `{volatility}`
• Trend: {trend_emoji.get(trend, '↔️')} `{trend}`
• Volume: `{volume}`
• News Impact: `{news_impact}`

*Recommendations:*
{conditions.get('recommendation', 'Trade normally')}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
            self.send_message(message, message_type='market')
            
        except Exception as e:
            print(f"Error in notify_market_conditions: {e}")
    
    def notify_batch_update(self, updates: List[Dict]):
        """📦 Batch multiple updates into one message"""
        try:
            if not updates:
                return
            
            message = f"""
📦 *BATCH UPDATE*
━━━━━━━━━━━━━━━━━━━

"""
            for i, update in enumerate(updates, 1):
                update_type = update.get('type', 'Unknown')
                content = update.get('content', '')
                
                message += f"""
*{i}. {update_type}*
{content}
"""
            
            message += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
            
            self.send_message(message, message_type='batch')
            
        except Exception as e:
            print(f"Error in notify_batch_update: {e}")
    
    def notify_position_overview(self, positions: List[Dict]):
        """📋 Current open positions overview"""
        try:
            if not positions:
                message = f"""
📋 *OPEN POSITIONS*
━━━━━━━━━━━━━━━━━━━

No open positions

⏰ {datetime.now().strftime('%H:%M:%S UTC')}
"""
                self.send_message(message, message_type='positions')
                return
            
            total_profit = sum(p.get('profit', 0) for p in positions)
            total_volume = sum(p.get('volume', 0) for p in positions)
            
            message = f"""
📋 *OPEN POSITIONS ({len(positions)})*
━━━━━━━━━━━━━━━━━━━

*Summary:*
• Total P/L: `${total_profit:+.2f}`
• Total Volume: `{total_volume:.2f} lots`

*Positions:*
"""
            
            for pos in positions[:5]:  # Limit to 5 positions
                ticket = pos.get('ticket', 'N/A')
                symbol = pos.get('symbol', 'N/A')
                type_str = pos.get('type', 'N/A')
                volume = pos.get('volume', 0.0)
                profit = pos.get('profit', 0.0)
                
                emoji = "🟢" if type_str == 'BUY' else "🔴"
                profit_emoji = "💚" if profit > 0 else "❌" if profit < 0 else "⚪"
                
                message += f"""
{emoji} `#{ticket}` {symbol} {type_str} `{volume}` lots
{profit_emoji} P/L: `${profit:+.2f}`
"""
            
            if len(positions) > 5:
                message += f"\n... and {len(positions) - 5} more positions"
            
            message += f"\n⏰ {datetime.now().strftime('%H:%M:%S UTC')}"
            
            self.send_message(message, message_type='positions')
            
        except Exception as e:
            print(f"Error in notify_position_overview: {e}")
    
    def notify_target_reached(self, target_type: str, details: Dict):
        """🎯 Target reached notification (daily/weekly/monthly)"""
        try:
            target_config = {
                'DAILY': {'emoji': '🎯', 'title': 'DAILY TARGET REACHED'},
                'WEEKLY': {'emoji': '🏆', 'title': 'WEEKLY TARGET REACHED'},
                'MONTHLY': {'emoji': '👑', 'title': 'MONTHLY TARGET REACHED'}
            }
            
            config = target_config.get(target_type, {'emoji': '🎯', 'title': 'TARGET REACHED'})
            
            achieved = details.get('achieved', 0.0)
            target = details.get('target', 0.0)
            percentage = (achieved / target * 100) if target > 0 else 0
            
            message = f"""
{config['emoji']} *{config['title']}*
━━━━━━━━━━━━━━━━━━━

🎉 *Congratulations!*

• Target: `${target:.2f}`
• Achieved: `${achieved:.2f}`
• Performance: `{percentage:.1f}%`
• Time Taken: `{details.get('time_taken', 'N/A')}`

*Statistics:*
• Total Trades: `{details.get('trades', 0)}`
• Win Rate: `{details.get('win_rate', 0):.1f}%`
• Best Trade: `${details.get('best_trade', 0):+.2f}`

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
            self.send_message(message, message_type='milestone')
            
        except Exception as e:
            print(f"Error in notify_target_reached: {e}")
    
    def notify_system_health(self, health: Dict):
        """🏥 System health check notification"""
        try:
            status = health.get('status', 'UNKNOWN')
            
            status_config = {
                'HEALTHY': {'emoji': '✅', 'color': 'green'},
                'WARNING': {'emoji': '⚠️', 'color': 'yellow'},
                'CRITICAL': {'emoji': '🚨', 'color': 'red'}
            }
            
            config = status_config.get(status, {'emoji': '❓', 'color': 'gray'})
            
            message = f"""
🏥 *SYSTEM HEALTH CHECK*
━━━━━━━━━━━━━━━━━━━

Status: {config['emoji']} *{status}*

*Components:*
• MT5 Connection: `{health.get('mt5_status', 'Unknown')}`
• Data Feed: `{health.get('data_feed', 'Unknown')}`
• Strategy Engine: `{health.get('strategy_status', 'Unknown')}`
• Risk Manager: `{health.get('risk_status', 'Unknown')}`

*Performance:*
• CPU Usage: `{health.get('cpu_usage', 0):.1f}%`
• Memory Usage: `{health.get('memory_usage', 0):.1f}%`
• Uptime: `{health.get('uptime', 'N/A')}`

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
            
            message_type = 'critical' if status == 'CRITICAL' else 'status'
            self.send_message(message, message_type=message_type)
            
        except Exception as e:
            print(f"Error in notify_system_health: {e}")
    
    def send_custom_alert(self, title: str, message: str, emoji: str = "📢"):
        """📢 Custom alert for flexible notifications"""
        try:
            formatted_message = f"""
{emoji} *{title}*
━━━━━━━━━━━━━━━━━━━

{message}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
            self.send_message(formatted_message, message_type='custom')
            
        except Exception as e:
            print(f"Error in send_custom_alert: {e}")


# ============================================
# HELPER FUNCTIONS
# ============================================

def format_percentage(value: float) -> str:
    """Format percentage with color emoji"""
    if value > 0:
        return f"📈 +{value:.2f}%"
    elif value < 0:
        return f"📉 {value:.2f}%"
    else:
        return f"➡️ {value:.2f}%"


def format_currency(value: float) -> str:
    """Format currency with sign"""
    return f"${value:+,.2f}"


# ============================================
# MAIN TEST
# ============================================

if __name__ == "__main__":
    print("🧪 Telegram Bot Unified Module")
    print("=" * 50)
    print("Run main.py to test the bot with a live SettingsManager.")
    print("\nFeatures included:")
    print("✅ Interactive command system (/menu, /status, /positions)")
    print("✅ Rich notification system (Entry, Exit, Regime, etc.)")
    print("✅ Rate limiting & security")
    print("✅ Auto-reconnect polling")
    print("✅ Inline keyboard controls")
    print("✅ Position management via buttons")
    print("✅ Bot pause/resume controls")
    print("✅ Panic close all positions")
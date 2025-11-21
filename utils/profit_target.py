import json
from datetime import datetime
import os
from typing import Tuple, Dict, Any
from utils.settings_manager import SettingsManager

class ProfitTargetManager:
    def __init__(self, sm: SettingsManager):
        self.sm = sm
        self.settings = {}
        self.stats_file = 'data/daily_stats.json'
        self.enabled = False
        self.daily_target_usd = 20.0
        self.action_when_reached = 'STOP'
        self.reduce_lot_pct = 50.0

        self.today_profit = 0.0
        self.today_trades = 0
        self.target_reached = False
        self.stopped_at = None
        
        self.last_checked_date = None

        self.load_settings()
        self.load_daily_stats()

    def load_settings(self) -> None:
        try:
            self.settings = self.sm.load_settings()
            pt_config = self.settings.get('profit_target', {})
            self.enabled = bool(pt_config.get('enabled', False))
            self.daily_target_usd = float(pt_config.get('daily_target_usd', 20.0))
            self.action_when_reached = str(pt_config.get('action_when_reached', 'STOP')).upper()
            self.reduce_lot_pct = float(pt_config.get('reduce_lot_pct', 50.0))

        except Exception as e:
            print(f"[ProfitTarget] Error loading settings: {e}")

    def load_daily_stats(self) -> None:
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        if self.last_checked_date == today_str:
            return

        self.last_checked_date = today_str
        
        try:
            if not os.path.exists(self.stats_file):
                self._create_stats_file()
                return

            with open(self.stats_file, 'r') as f:
                data = json.load(f)

            if data.get('date') == today_str:
                self.today_profit = float(data.get('profit', 0.0))
                self.today_trades = int(data.get('trades', 0))
                self.target_reached = bool(data.get('target_reached', False))
                self.stopped_at = data.get('stopped_at', None)
            else:
                self._reset_daily_stats()

        except Exception as e:
            print(f"[ProfitTarget] Error loading daily stats: {e}")
            self._reset_daily_stats()

    def _create_stats_file(self) -> None:
        os.makedirs('data', exist_ok=True)
        self._reset_daily_stats()

    def _reset_daily_stats(self) -> None:
        self.today_profit = 0.0
        self.today_trades = 0
        self.target_reached = False
        self.stopped_at = None
        self._save_stats()

    def _save_stats(self) -> None:
        try:
            os.makedirs('data', exist_ok=True)
            data = {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'profit': round(self.today_profit, 2),
                'trades': int(self.today_trades),
                'target_reached': bool(self.target_reached),
                'stopped_at': self.stopped_at
            }
            with open(self.stats_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[ProfitTarget] Error saving daily stats: {e}")

    def add_trade_result(self, profit: float) -> Tuple[bool, str]:
        if not self.enabled:
            return True, "Profit target disabled"

        try:
            self.today_profit += float(profit)
        except Exception:
            pass
        self.today_trades += 1
        self._save_stats()

        if not self.target_reached and self.today_profit >= self.daily_target_usd:
            self.target_reached = True
            self.stopped_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self._save_stats()

            if self.action_when_reached == 'STOP':
                return False, f"🎯 Daily target reached! (${self.today_profit:.2f} / ${self.daily_target_usd:.2f})"
            elif self.action_when_reached == 'REDUCE_LOT':
                return True, f"🎯 Target reached! Reducing lot size to {self.reduce_lot_pct}%"
            else:
                return True, "🎯 Target reached! Continue trading."

        return True, "Trading continues"

    def can_trade(self) -> Tuple[bool, str]:
        if not self.enabled:
            return True, "Profit target disabled"
        
        self.load_daily_stats()

        if self.target_reached and self.action_when_reached == 'STOP':
            return False, f"Daily target reached (${self.today_profit:.2f}). Stopped at {self.stopped_at}"

        return True, "OK"

    def get_lot_multiplier(self) -> float:
        if not self.enabled:
            return 1.0
        
        self.load_daily_stats()

        if self.target_reached and self.action_when_reached == 'REDUCE_LOT':
            try:
                return max(0.01, float(self.reduce_lot_pct) / 100.0)
            except Exception:
                return 1.0

        return 1.0

    def _generate_progress_bar(self, percentage: float, width: int = 10) -> str:
        percentage = max(0.0, min(100.0, percentage))
        filled = int((percentage / 100.0) * width)
        
        if self.today_profit < 0:
            fill_char = '▓' 
            empty_char = '░'
        elif percentage >= 100:
            fill_char = '█' 
            empty_char = '░'
        else:
            fill_char = '█' 
            empty_char = '░'
        
        bar = fill_char * filled + empty_char * (width - filled)
        return f"[{bar}]"

    def _get_status_emoji(self, percentage: float) -> str:
        if self.today_profit < 0:
            return '💀'
        elif self.target_reached and self.action_when_reached == 'STOP':
            return '⏸️'
        elif percentage >= 100:
            return '🏆'
        elif percentage >= 50:
            return '🔥'
        else:
            return '🎯'

    def _get_motivational_message(self, percentage: float) -> str:
        remaining = self.daily_target_usd - self.today_profit
        
        if self.today_profit < 0:
            return f"💪 Stay strong! Down ${abs(self.today_profit):.2f}, trade smart to recover!"
        elif percentage >= 100:
            excess = self.today_profit - self.daily_target_usd
            pct_over = ((self.today_profit / self.daily_target_usd) - 1) * 100 if self.daily_target_usd > 0 else 0
            return f"🎉 TARGET SMASHED! You're up ${excess:.2f} extra (+{pct_over:.1f}% over target)!"
        elif percentage >= 90:
            return f"🔥 SO CLOSE! Only ${remaining:.2f} to glory!"
        elif percentage >= 80:
            return f"💪 Almost there! Keep pushing! ${remaining:.2f} to go!"
        elif percentage >= 50:
            return f"⚡ Halfway there! ${remaining:.2f} more to target!"
        else:
            return f"🎯 Let's go! ${remaining:.2f} to target!"

    def get_progress(self) -> Dict[str, Any]:
        self.load_daily_stats()
        
        if not self.enabled:
            return {
                'enabled': False,
                'target': 0,
                'current': 0,
                'remaining': 0,
                'progress_pct': 0,
                'trades': 0,
                'status': 'DISABLED',
                'progress_bar': '[░░░░░░░░░░]',
                'status_emoji': '⏸️',
                'message': 'Profit target is disabled',
                'percentage_of_target': 0.0
            }

        remaining = self.daily_target_usd - self.today_profit
        progress_pct = (self.today_profit / self.daily_target_usd * 100.0) if self.daily_target_usd > 0 else 0.0
        percentage_of_target = progress_pct 

        if self.target_reached:
            status = 'TARGET_REACHED'
        elif self.today_profit < 0:
            status = 'LOSS'
        elif self.today_profit > 0:
            status = 'PROFIT'
        else:
            status = 'NEUTRAL'

        return {
            'enabled': True,
            'target': round(self.daily_target_usd, 2),
            'current': round(self.today_profit, 2),
            'remaining': round(max(0.0, remaining), 2),
            'progress_pct': round(min(100.0, max(0.0, progress_pct)), 1),
            'trades': int(self.today_trades),
            'status': status,
            'target_reached': bool(self.target_reached),
            'action': self.action_when_reached,
            'progress_bar': self._generate_progress_bar(progress_pct),
            'status_emoji': self._get_status_emoji(progress_pct),
            'message': self._get_motivational_message(progress_pct),
            'percentage_of_target': round(percentage_of_target, 1)
        }

    def get_visual_progress(self) -> str:
        progress = self.get_progress()
        
        if not progress['enabled']:
            return """
╔════════════════════════════════════════════╗
║      PROFIT TARGET: DISABLED ⏸️          ║
╚════════════════════════════════════════════╝
"""

        lines = []
        lines.append("╔════════════════════════════════════════════╗")
        lines.append(f"║  {progress['status_emoji']}  DAILY PROFIT TARGET TRACKER        ║")
        lines.append("╠════════════════════════════════════════════╣")
        
        bar = progress['progress_bar']
        pct = progress['percentage_of_target']
        lines.append(f"║  Progress: {bar} {pct:.1f}%")
        lines.append("║")
        
        curr = progress['current']
        tgt = progress['target']
        lines.append(f"║  💰 Current:  ${curr:+.2f}")
        lines.append(f"║  🎯 Target:   ${tgt:.2f}")
        
        if progress['target_reached']:
            excess = curr - tgt
            lines.append(f"║  ✨ Excess:   ${excess:+.2f}")
        else:
            lines.append(f"║  📊 Remaining: ${progress['remaining']:.2f}")
        
        lines.append("║")
        lines.append(f"║  📈 Trades Today: {progress['trades']}")
        lines.append("║")
        
        if progress['target_reached']:
            lines.append(f"║  ✅ STATUS: TARGET REACHED!")
            if progress['action'] == 'STOP':
                lines.append(f"║  🛑 Action: Trading STOPPED")
            elif progress['action'] == 'REDUCE_LOT':
                lines.append(f"║  📉 Action: Lot reduced to {self.reduce_lot_pct}%")
            else:
                lines.append(f"║  ▶️  Action: Continue trading")
        elif curr < 0:
            lines.append(f"║  ⚠️  STATUS: LOSS (${abs(curr):.2f})")
        else:
            lines.append(f"║  🔄 STATUS: ACTIVE")
        
        lines.append("╠════════════════════════════════════════════╣")
        
        msg = progress['message']
        if len(msg) <= 42:
            lines.append(f"║  {msg}")
        else:
            words = msg.split()
            line = "║  "
            for word in words:
                if len(line + word) <= 44:
                    line += word + " "
                else:
                    lines.append(line.rstrip())
                    line = "║  " + word + " "
            if line.strip() != "║":
                lines.append(line.rstrip())
        
        lines.append("╚════════════════════════════════════════════╝")
        
        return "\n".join(lines)

    def get_summary_text(self) -> str:
        progress = self.get_progress()
        
        if not progress['enabled']:
            return "Profit Target: DISABLED ⏸️"

        lines = []
        
        emoji = progress['status_emoji']
        lines.append(f"{emoji} DAILY PROFIT TARGET")
        lines.append("=" * 45)
        
        bar = progress['progress_bar']
        curr = progress['current']
        tgt = progress['target']
        pct = progress['percentage_of_target']
        
        if curr < 0:
            color_indicator = "🔴"
        elif pct >= 100:
            color_indicator = "🟢"
        elif pct >= 50:
            color_indicator = "🟡"
        else:
            color_indicator = "⚪"
        
        lines.append(f"{color_indicator} Target: {bar} {pct:.1f}% (${curr:+.2f} / ${tgt:.2f})")
        lines.append("")
        
        lines.append(f"💰 Current P/L:  ${curr:+.2f}")
        lines.append(f"🎯 Target:       ${tgt:.2f}")
        
        if progress['target_reached']:
            excess = curr - tgt
            lines.append(f"✨ Excess:       ${excess:+.2f}")
        else:
            lines.append(f"📊 Remaining:    ${progress['remaining']:.2f}")
        
        lines.append(f"📈 Trades:       {progress['trades']}")
        lines.append("")
        
        if progress['target_reached']:
            lines.append("✅ TARGET REACHED!")
            if progress['action'] == 'STOP':
                lines.append("🛑 Trading STOPPED")
            elif progress['action'] == 'REDUCE_LOT':
                lines.append(f"📉 Lot reduced to {self.reduce_lot_pct}%")
            else:
                lines.append("▶️  Continue trading")
        elif curr < 0:
            lines.append(f"⚠️  LOSS: ${abs(curr):.2f}")
        else:
            lines.append("🔄 ACTIVE")
        
        lines.append("")
        lines.append(f"💬 {progress['message']}")
        
        return "\n".join(lines)

    def manual_reset(self) -> bool:
        self._reset_daily_stats()
        return True

    def update_target(self, new_target: float) -> Tuple[bool, str]:
        try:
            new_target = float(new_target)
            if new_target <= 0:
                return False, "Target must be positive"
            
            success = self.sm.update_setting('profit_target.daily_target_usd', new_target)
            if success:
                self.daily_target_usd = new_target
                return True, f"Target updated to ${new_target:.2f}"
            else:
                return False, "Failed to write to settings file"

        except Exception as e:
            return False, f"Failed to update: {e}"

    def update_action(self, action: str) -> Tuple[bool, str]:
        try:
            valid = ['STOP', 'REDUCE_LOT', 'CONTINUE']
            action_up = action.upper()
            if action_up not in valid:
                return False, f"Invalid action. Must be: {', '.join(valid)}"

            success = self.sm.update_setting('profit_target.action_when_reached', action_up)
            if success:
                self.action_when_reached = action_up
                return True, f"Action updated to {action_up}"
            else:
                return False, "Failed to write to settings file"

        except Exception as e:
            return False, f"Failed to update: {e}"

    def toggle_enabled(self) -> Tuple[bool, str]:
        try:
            current = self.enabled
            new_status = not current
            
            success = self.sm.update_setting('profit_target.enabled', new_status)
            if success:
                self.enabled = new_status
                return True, f"Profit target {'ENABLED' if self.enabled else 'DISABLED'}"
            else:
                return False, "Failed to write to settings file"

        except Exception as e:
            return False, f"Failed to toggle: {e}"

    def get_history(self, days: int = 7):
        return []
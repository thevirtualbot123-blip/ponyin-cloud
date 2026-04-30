"""
telegram_bot.py — Bot PONYIN Telegram dengan rate limiting dan error handling.
"""
import asyncio, logging, html, json, traceback
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dataclasses import dataclass
from typing import Dict, Optional
from filter_engine import Token
from decision_engine import DecisionEngine, Decision
from config import AgentConfig

log = logging.getLogger("PONYIN.Telegram")

# Rate limiting constants
RATE_LIMIT_WINDOW = 60  # seconds
MAX_ALERTS_PER_WINDOW = 10
MAX_SUMMARY_PER_WINDOW = 2

@dataclass
class UserSession:
    alerts_sent: int = 0
    summaries_sent: int = 0
    window_start: datetime = None

class TelegramBot:
    def __init__(self, cfg: AgentConfig, decision_engine: DecisionEngine):
        self.cfg = cfg
        self.decision_engine = decision_engine
        self.app = None
        self.sessions: Dict[int, UserSession] = {}
        
        # Lock untuk mencegah race condition saat kirim
        self.send_lock = asyncio.Lock()
        
        # Counter untuk logging
        self.alert_counter = 0

    async def start(self):
        """Start the Telegram bot."""
        if not self.cfg.TELEGRAM_BOT_TOKEN:
            log.error("TELEGRAM_BOT_TOKEN tidak diset. Bot tidak akan start.")
            return
            
        self.app = Application.builder().token(self.cfg.TELEGRAM_BOT_TOKEN).build()
        
        # Register handlers
        self.app.add_handler(CommandHandler("start", self._handle_start))
        self.app.add_handler(CommandHandler("help", self._handle_help))
        self.app.add_handler(CommandHandler("summary", self._handle_summary))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
        
        log.info("Telegram bot starting...")
        await self.app.initialize()
        await self.app.start()

    async def stop(self):
        """Stop the Telegram bot."""
        if self.app:
            await self.app.stop()
            await self.app.shutdown()

    async def send_alert(self, token: Token, decision: Decision, source: str, raw: str):
        """Send alert to Telegram chat with rate limiting."""
        if not self.cfg.TELEGRAM_CHAT_ID:
            log.warning("TELEGRAM_CHAT_ID tidak diset. Alert tidak dikirim.")
            return

        user_id = self.cfg.TELEGRAM_CHAT_ID
        
        # Check rate limit
        now = datetime.now(timezone.utc)
        session = self.sessions.get(user_id, UserSession(window_start=now))
        
        if session.window_start is None:
            session.window_start = now
            
        # Reset window jika lebih dari 60 detik
        if (now - session.window_start).seconds > RATE_LIMIT_WINDOW:
            session.window_start = now
            session.alerts_sent = 0
            
        # Cek apakah sudah melebihi limit
        if session.alerts_sent >= MAX_ALERTS_PER_WINDOW:
            log.warning(f"Rate limit exceeded for user {user_id}. Skipping alert.")
            return
            
        # Update counter
        session.alerts_sent += 1
        self.sessions[user_id] = session
        
        # Buat pesan
        try:
            message = self._format_token_message(token, decision, source, raw)
            
            # Kirim dengan retry logic
            success = await self._send_with_retry(message)
            if success:
                self.alert_counter += 1
                log.info(f"Alert #{self.alert_counter} sent successfully. Total alerts: {self.alert_counter}")
            else:
                log.error("Failed to send alert after retries.")
                
        except Exception as e:
            log.error(f"Error sending alert: {e}")

    def _escape_html(self, text: str) -> str:
        """Escape HTML entities safely for Telegram."""
        if text is None:
            return "N/A"
        # Escape HTML first
        escaped = html.escape(str(text), quote=False)
        # Then handle specific Telegram formatting
        escaped = escaped.replace('<', '&lt;').replace('>', '&gt;')
        return escaped

    def _format_token_message(self, token: Token, decision: Decision, source: str, raw: str) -> str:
        """Format token information into a readable Telegram message."""
        # Escape all fields that might contain HTML
        name_escaped = self._escape_html(token.name)
        symbol_escaped = self._escape_html(token.symbol)
        
        # Format numbers with proper escaping
        mc_str = f"${token.mc:,.0f}" if token.mc > 0 else "N/A"
        liq_str = f"${token.liq:,.0f}" if token.liq > 0 else "N/A"
        vol_str = f"${token.vol1h:,.0f}" if token.vol1h > 0 else "N/A"
        
        # Safely format percentages
        chg_str = f"{token.chg1h:+.1f}%" if token.chg1h is not None else "N/A"
        top10_str = f"{token.top10_pct:.1f}%" if token.top10_pct is not None else "N/A"
        
        # Escape decision reason
        reason_escaped = self._escape_html(decision.reason)
        
        # Build main message
        message_parts = [
            f"🚨 <b>PONYIN ALERT</b> 🚨",
            f"<b>Token:</b> {name_escaped} (${symbol_escaped})",
            f"<b>Action:</b> <code>{decision.action}</code> | <b>Conviction:</b> {decision.conviction}",
            f"<b>Confidence:</b> {decision.confidence:.0%} | <b>Mode:</b> {decision.mode}",
            "",
            f"<b>📊 Metrics:</b>",
            f"• MC: {mc_str} | Liq: {liq_str}",
            f"• Vol1h: {vol_str} | Chg1h: {chg_str}",
            f"• Buys: {token.buys1h} | Sells: {token.sells1h}",
            f"• Top10: {top10_str} | Risk: {token.risk_norm}/10",
            f"• LP Burn: {token.lp_burn:.0f}% | Age: {token.age_hours:.1f}h",
        ]
        
        # Add mint authority status
        if token.mint_auth is not None:
            auth_status = "🟢 Revoked" if token.mint_auth == "revoked" else f"🔴 Active: {self._escape_html(token.mint_auth[:8])}..."
            message_parts.append(f"• Mint Auth: {auth_status}")
        else:
            message_parts.append("• Mint Auth: N/A")
            
        # Add wash trading info if flagged
        if token.wash_trading_flag:
            wt_reason = self._escape_html(token.wash_trading_reason or "Unknown reason")
            message_parts.append(f"⚠️ Wash Trading: {wt_reason}")
            
        # Add decision details
        message_parts.extend([
            "",
            f"<b>💡 Reason:</b> {reason_escaped}",
            f"<b>💰 Sizing:</b> {self._escape_html(decision.sizing_note)}",
        ])
        
        # Add entry plan if available
        if decision.entry_plan:
            message_parts.extend([
                "",
                f"<b>🎯 Entry Plan:</b>",
                f"{self._escape_html(decision.entry_plan)}"
            ])
            
        # Add source and timestamp
        timestamp = datetime.now().strftime("%H:%M:%S")
        message_parts.extend([
            "",
            f"<i>Source: {self._escape_html(source)} | Time: {timestamp}</i>"
        ])
        
        return "\n".join(message_parts)

    async def _send_with_retry(self, message: str, max_retries: int = 3) -> bool:
        """Send message with retry logic."""
        for attempt in range(max_retries):
            try:
                async with self.send_lock:
                    # Kirim pesan
                    await self.app.bot.send_message(
                        chat_id=self.cfg.TELEGRAM_CHAT_ID,
                        text=message,
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )
                    return True
                    
            except Exception as e:
                log.warning(f"Send attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                else:
                    log.error(f"All {max_retries} attempts failed.")
                    
        return False

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        welcome_msg = (
            "🦄 <b>Welcome to PONYIN Bot!</b>\n\n"
            "I'm your Solana token analysis assistant.\n\n"
            "<b>Commands:</b>\n"
            "• /start - Show this message\n"
            "• /help - Show help\n"
            "• /summary - Get trading summary\n\n"
            "I'll send you alerts for promising tokens based on advanced filtering."
        )
        
        await update.effective_message.reply_text(welcome_msg, parse_mode='HTML')

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        help_msg = (
            "📚 <b>PONYIN Bot Help</b>\n\n"
            "<b>How I work:</b>\n"
            "• I analyze Solana tokens using multiple filters\n"
            "• I check for risks like mint authority, top holder concentration\n"
            "• I provide entry plans and risk management suggestions\n\n"
            "<b>Alert Levels:</b>\n"
            "• ENTER: High conviction opportunities\n"
            "• WATCH: Monitor for potential entries\n"
            "• SKIP: Avoid these tokens\n\n"
            "For support, contact the developer."
        )
        
        await update.effective_message.reply_text(help_msg, parse_mode='HTML')

    async def _handle_summary(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /summary command with rate limiting."""
        user_id = update.effective_user.id
        
        # Check rate limit for summaries
        now = datetime.now(timezone.utc)
        session = self.sessions.get(user_id, UserSession(window_start=now))
        
        if session.window_start is None:
            session.window_start = now
            
        # Reset window if more than 60 seconds
        if (now - session.window_start).seconds > RATE_LIMIT_WINDOW:
            session.window_start = now
            session.summaries_sent = 0
            
        # Check if over limit
        if session.summaries_sent >= MAX_SUMMARY_PER_WINDOW:
            await update.effective_message.reply_text(
                "Rate limit exceeded for summaries. Please wait before requesting again."
            )
            return
            
        session.summaries_sent += 1
        self.sessions[user_id] = session
        
        summary = (
            f"📊 <b>PONYIN Trading Summary</b>\n\n"
            f"• Total Alerts Sent: {self.alert_counter}\n"
            f"• Current Mode: {'AI + Rules' if self.cfg.AI_ENABLED else 'Rules Only'}\n"
            f"• Portfolio Size: {self.cfg.PORTFOLIO_SOL} SOL\n"
            f"• Risk Management: TP1={self.cfg.TP1_PCT}%, TP2={self.cfg.TP2_PCT}%, SL={self.cfg.SL_PCT}%\n\n"
            f"<i>Last updated: {datetime.now().strftime('%H:%M:%S')}</i>"
        )
        
        await update.effective_message.reply_text(summary, parse_mode='HTML')

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle regular messages."""
        user_msg = update.effective_message.text.lower()
        
        if 'hello' in user_msg or 'hi' in user_msg:
            await update.effective_message.reply_text("Hello! Use /help to see available commands.")
        else:
            await update.effective_message.reply_text("I'm PONYIN bot. Use /help to see what I can do!")

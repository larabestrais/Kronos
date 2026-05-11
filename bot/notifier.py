import logging
import time
import threading
from typing import Optional

import requests

from .signals import Signal, Action
from .portfolio import Trade, Position

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """
    Envoie des notifications Telegram pour les événements importants du bot.
    Silent-fail si pas configuré (token/chat_id manquants).
    """

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None, parse_mode: str = "HTML"):
        self.bot_token = (bot_token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.parse_mode = parse_mode
        self.enabled = bool(self.bot_token and self.chat_id)
        self._send_lock = threading.Lock()
        self._last_send_at = 0.0
        self._min_interval = 1.0  # rate limit: 1 msg/sec max
        self._error_dedupe: dict[str, float] = {}

        if self.enabled:
            logger.info("[Telegram] Notifier configuré")
        else:
            logger.info("[Telegram] Notifier désactivé (TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID manquant)")

    def send(self, message: str, silent: bool = False) -> bool:
        if not self.enabled:
            return False

        with self._send_lock:
            elapsed = time.time() - self._last_send_at
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)

            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            try:
                r = requests.post(url, json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": self.parse_mode,
                    "disable_notification": silent,
                    "disable_web_page_preview": True,
                }, timeout=8)
                self._last_send_at = time.time()

                if r.status_code != 200:
                    logger.warning(f"[Telegram] HTTP {r.status_code}: {r.text[:200]}")
                    return False
                return True
            except Exception as e:
                logger.error(f"[Telegram] Erreur envoi: {e}")
                return False

    def send_with_inline_keyboard(
        self,
        message: str,
        buttons: list[list[dict]],
        silent: bool = False,
    ) -> Optional[int]:
        """
        Envoie un message avec un clavier inline.
        `buttons` : liste de rangées de boutons. Chaque bouton est un dict
                    {"text": str, "callback_data": str}.
        Retourne le message_id de Telegram (utile pour edit ultérieur), ou None.
        """
        if not self.enabled:
            return None

        with self._send_lock:
            elapsed = time.time() - self._last_send_at
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)

            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            try:
                r = requests.post(url, json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": self.parse_mode,
                    "disable_notification": silent,
                    "disable_web_page_preview": True,
                    "reply_markup": {"inline_keyboard": buttons},
                }, timeout=8)
                self._last_send_at = time.time()

                if r.status_code != 200:
                    logger.warning(f"[Telegram] HTTP {r.status_code}: {r.text[:200]}")
                    return None

                data = r.json()
                return data.get("result", {}).get("message_id")
            except Exception as e:
                logger.error(f"[Telegram] Erreur envoi clavier: {e}")
                return None

    def edit_message(self, message_id: int, new_text: str) -> bool:
        """Edit un message existant (pour confirmer une approbation)."""
        if not self.enabled or not message_id:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/editMessageText"
        try:
            r = requests.post(url, json={
                "chat_id": self.chat_id,
                "message_id": message_id,
                "text": new_text,
                "parse_mode": self.parse_mode,
            }, timeout=8)
            return r.status_code == 200
        except Exception as e:
            logger.error(f"[Telegram] Erreur edit: {e}")
            return False

    def test(self) -> bool:
        """Envoie un message de test pour valider la config."""
        msg = (
            "<b>🤖 KRONOS — Test de connexion</b>\n\n"
            "Si tu vois ce message, les notifications Telegram fonctionnent ✅\n\n"
            "<i>Tu recevras désormais les alertes de trades, stop-loss, take-profit "
            "et résumés de cycles.</i>"
        )
        return self.send(msg)

    def notify_position_opened(self, pos: Position, leverage: float = 1.0):
        emoji = "🟢" if pos.side == "LONG" else "🔴"
        side_fr = "ACHAT (LONG)" if pos.side == "LONG" else "VENTE (COURT)"
        notional = pos.shares * pos.entry_price
        margin = notional / leverage if leverage > 0 else notional

        sl_pct = abs((pos.stop_loss - pos.entry_price) / pos.entry_price) * 100
        tp_pct = abs((pos.take_profit - pos.entry_price) / pos.entry_price) * 100

        msg = (
            f"{emoji} <b>NOUVEAU TRADE</b>\n"
            f"<b>{pos.symbol}</b> · {side_fr}\n\n"
            f"📍 Entrée: <code>${pos.entry_price:.2f}</code>\n"
            f"🛑 Stop-loss: <code>${pos.stop_loss:.2f}</code> (-{sl_pct:.1f}%)\n"
            f"🎯 Take-profit: <code>${pos.take_profit:.2f}</code> (+{tp_pct:.1f}%)\n"
            f"📦 Quantité: <code>{pos.shares:.4f}</code> actions\n"
            f"💰 Notionnel: <code>{notional:.2f}$</code>\n"
            f"🔒 Marge: <code>{margin:.2f}$</code> (levier {leverage:g}x)"
        )
        self.send(msg)

    def notify_position_closed(self, trade: Trade, entry_price: float):
        is_win = trade.pnl > 0
        is_sl = "STOP" in trade.reason.upper()
        is_tp = "TAKE" in trade.reason.upper()
        side = trade.side.replace("CLOSE_", "")

        if is_tp:
            emoji = "🎉"
            title = "TAKE PROFIT TOUCHÉ"
        elif is_sl:
            emoji = "🛑"
            title = "STOP LOSS DÉCLENCHÉ"
        else:
            emoji = "✅" if is_win else "⚠️"
            title = "POSITION FERMÉE"

        pnl_pct = ((trade.price - entry_price) / entry_price) * 100
        if side == "SHORT":
            pnl_pct = -pnl_pct

        pnl_emoji = "📈" if is_win else "📉"

        msg = (
            f"{emoji} <b>{title}</b>\n"
            f"<b>{trade.symbol}</b> · {side}\n\n"
            f"📍 Entrée: <code>${entry_price:.2f}</code>\n"
            f"🚪 Sortie: <code>${trade.price:.2f}</code>\n"
            f"{pnl_emoji} PnL: <b>{trade.pnl:+.2f}$</b> ({pnl_pct:+.2f}%)\n"
            f"💬 Raison: <i>{trade.reason}</i>"
        )
        self.send(msg)

    def notify_cycle_summary(self, summary: dict, signals: list[Signal], force: bool = False):
        """Envoie un résumé après un cycle, seulement s'il y a des signaux non-HOLD ou force=True."""
        non_hold = [s for s in signals if s.action != Action.HOLD]
        if not non_hold and not force:
            return

        pnl = summary.get("pnl_total", 0)
        pnl_pct = summary.get("pnl_total_pct", 0)
        equity = summary.get("valeur_totale", 0)
        positions = summary.get("positions_ouvertes", 0)
        margin_used = summary.get("marge_utilisee", 0)
        leverage = summary.get("leverage", 1)

        pnl_emoji = "📈" if pnl >= 0 else "📉"

        lines = [
            "<b>🤖 KRONOS — Résumé du cycle</b>",
            "",
            f"💼 Portfolio: <code>{equity:.2f}$</code> (cap. init {summary.get('capital_initial', 0):.0f}$)",
            f"{pnl_emoji} PnL total: <b>{pnl:+.2f}$</b> ({pnl_pct:+.2f}%)",
            f"🔓 Positions: {positions} ouverte(s)",
        ]

        if margin_used > 0:
            lines.append(f"🔒 Marge utilisée: <code>{margin_used:.2f}$</code> (levier {leverage:g}x)")

        if signals:
            lines.append("")
            lines.append("<b>Signaux du cycle:</b>")
            for s in signals[:8]:
                if s.action == Action.BUY:
                    em = "🟢"
                    act = "ACHAT"
                elif s.action == Action.SELL:
                    em = "🔴"
                    act = "VENTE"
                else:
                    em = "⏸️"
                    act = "ATTENTE"
                ret_pct = s.predicted_return * 100
                conf_pct = s.confidence * 100
                lines.append(f"{em} <b>{s.symbol}</b> {act} · ret pred {ret_pct:+.1f}% · conf {conf_pct:.0f}%")

        self.send("\n".join(lines), silent=(not non_hold))

    def notify_error(self, error_msg: str, dedupe_key: Optional[str] = None):
        """Envoie une erreur, en évitant les doublons (1 par minute pour le même type)."""
        if dedupe_key:
            now = time.time()
            last = self._error_dedupe.get(dedupe_key, 0)
            if now - last < 60:
                return
            self._error_dedupe[dedupe_key] = now

        msg = f"<b>⚠️ KRONOS — Erreur</b>\n\n<code>{error_msg[:500]}</code>"
        self.send(msg)


def from_env() -> TelegramNotifier:
    """Construit un TelegramNotifier depuis les env vars TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID."""
    import os
    return TelegramNotifier(
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
    )

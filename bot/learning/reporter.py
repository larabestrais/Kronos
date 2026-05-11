"""
DailyReporter — formate le message Telegram quotidien à 22h00.
"""

import logging

from .types import LearningState, ProposedAdjustment, Regime

logger = logging.getLogger(__name__)


class DailyReporter:

    def __init__(self, state: LearningState):
        self.state = state

    def format_daily_message(
        self,
        trades_today: int,
        wins_today: int,
        losses_today: int,
        pnl_today: float,
        equity: float,
        sharpe_30d: float,
        win_rate_30d: float,
        drawdown_30d: float,
        expectancy_30d: float,
        auto_applied: list[ProposedAdjustment],
        pending: list[ProposedAdjustment],
    ) -> str:
        regime_emoji = {
            Regime.TREND_UP: "📈",
            Regime.TREND_DOWN: "📉",
            Regime.RANGING: "〰️",
            Regime.HIGH_VOLATILITY: "⚡",
        }
        emoji = regime_emoji.get(self.state.current_regime, "")

        lines = [
            "🌙 <b>KRONOS — Bilan quotidien</b>",
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "📊 <b>Performance du jour</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"{'🟢' if pnl_today >= 0 else '🔴'} {trades_today} trades ({wins_today}W / {losses_today}L)",
            f"💰 PnL : <b>{pnl_today:+.2f} €</b>",
            f"📈 Equity : <code>{equity:.2f} €</code>",
            f"🎯 Régime : {emoji} <b>{self.state.current_regime.value}</b>",
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "📈 <b>Performance 30j</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Sharpe : <b>{sharpe_30d:.2f}</b> {self._sharpe_emoji(sharpe_30d)}",
            f"Win rate : <b>{win_rate_30d:.0%}</b>",
            f"Drawdown : <b>{drawdown_30d:.1%}</b>",
            f"Expectancy : <b>{expectancy_30d:+.3f}/trade</b>",
        ]

        if auto_applied:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"🤖 <b>Ajustements auto ({len(auto_applied)})</b>")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            for p in auto_applied[:5]:  # max 5 affichés
                short_path = p.param_path.replace("current_params.", "")
                from_v = float(p.from_value) if not isinstance(p.from_value, bool) else int(p.from_value)
                to_v = float(p.to_value) if not isinstance(p.to_value, bool) else int(p.to_value)
                lines.append(
                    f"✓ {short_path} : <code>{from_v:.3f} → {to_v:.3f}</code>"
                )
                lines.append(f"   <i>{p.reason}</i>")

        if pending:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"🔔 <b>Validations requises ({len(pending)})</b>")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            for p in pending[:3]:
                lines.append(
                    f"⚠️ <b>{p.type.replace('_', ' ').title()}</b>"
                )
                lines.append(
                    f"   <code>{p.from_value} → {p.to_value}</code>"
                )
                lines.append(f"   <i>{p.reason}</i>")

        return "\n".join(lines)

    def build_inline_keyboard(
        self, pending: list[ProposedAdjustment]
    ) -> list[list[dict]]:
        """Construit le clavier inline avec 3 boutons par proposition."""
        keyboard = []
        for p in pending[:3]:  # max 3 propositions par message
            keyboard.append([
                {"text": "✅ Valider", "callback_data": f"learning:approve:{p.id}"},
                {"text": "❌ Refuser", "callback_data": f"learning:reject:{p.id}"},
                {"text": "⏸️ Plus tard", "callback_data": f"learning:defer:{p.id}"},
            ])
        return keyboard

    @staticmethod
    def _sharpe_emoji(s: float) -> str:
        if s >= 2.0:
            return "✨"
        if s >= 1.0:
            return "👍"
        if s >= 0:
            return "🤔"
        return "💀"

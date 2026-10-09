"""Compatibility shim redirecting autonomous_futures.notifications to autonomous_futures.notify."""

from __future__ import annotations

import sys

from autonomous_futures.notify import (
    AsyncTelegramNotifierClient,
    TelegramConfig,
    TelegramNotifierClient,
    escape_markdown_v2,
    format_command_help,
    format_portfolio_digest,
    format_risk_alert,
    format_trade_closed_alert,
    format_trade_opened_alert,
    mask_token,
    resolve_telegram_credentials,
    telegram,
)

# Register telegram submodule alias for autonomous_futures.notifications.telegram
sys.modules["autonomous_futures.notifications.telegram"] = telegram

__all__ = [
    "AsyncTelegramNotifierClient",
    "TelegramConfig",
    "TelegramNotifierClient",
    "escape_markdown_v2",
    "format_command_help",
    "format_portfolio_digest",
    "format_risk_alert",
    "format_trade_closed_alert",
    "format_trade_opened_alert",
    "mask_token",
    "resolve_telegram_credentials",
    "telegram",
]

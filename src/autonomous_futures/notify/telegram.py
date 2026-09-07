"""Real-time Telegram notification engine, alert formatters, and client subsystem.

Provides resilient Telegram Bot API delivery with rate limiting, exponential
backoff on HTTP 429 (Retry-After) and 5xx, MarkdownV2 character escaping,
automatic plain-text fallback on HTTP 400 entity parse errors, and strict token
redaction in logs, string representations, and exceptions.
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import UTC, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

logger = logging.getLogger(__name__)

# Reserved MarkdownV2 characters per Telegram API spec
# Characters: _ * [ ] ( ) ~ ` > # + - = | { } . ! \
_MD_V2_RESERVED_PATTERN: re.Pattern[str] = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")

# Token redaction pattern: e.g. "bot123456:ABC-DEF_xyz" -> "bot123456:***"
_BOT_TOKEN_REDACT_PATTERN: re.Pattern[str] = re.compile(
    r"(bot\d+:)[A-Za-z0-9_-]{20,}", re.IGNORECASE
)
_MYT = timezone(timedelta(hours=8), name="MYT")


def _event_value(event: dict[str, Any], *names: str) -> Any:
    """Return the first present value, including numeric zero."""
    for name in names:
        if name in event and event[name] is not None:
            return event[name]
    return None


def _finite_decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def _decimal_text(value: Any, quantum: Decimal, *, trim: bool = False) -> str:
    number = _finite_decimal(value)
    if number is None:
        return "N/A"
    try:
        result = number.quantize(quantum, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return "N/A"
    text = format(result, "f")
    return text.rstrip("0").rstrip(".") if trim and "." in text else text


def _price_text(value: Any) -> str:
    text = _decimal_text(value, Decimal("0.0001"))
    if text == "N/A" or "." not in text:
        return text + ".00" if text != "N/A" else text
    whole, fraction = text.split(".", 1)
    fraction = fraction.rstrip("0")
    return f"{whole}.{fraction.ljust(2, '0')}"


def _money_text(value: str, unit: str = " USDT") -> str:
    return "Unavailable" if value == "N/A" else f"${value}{unit}"


def _myt_text(value: Any) -> str:
    if value is None:
        return datetime.now(UTC).astimezone(_MYT).strftime("%Y-%m-%d %H:%M:%S MYT")
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace(" UTC", "+00:00").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(_MYT).strftime("%Y-%m-%d %H:%M:%S MYT")
    except ValueError:
        return text


def mask_token(token: str | None) -> str:
    """Safely redact a Telegram bot token, preserving only the prefix identifier.

    Example:
        >>> mask_token("123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ1234567")
        '123456789:***'
        >>> mask_token("secret")
        '***'
        >>> mask_token("")
        '<NONE>'
    """
    if not token:
        return "<NONE>"
    if ":" in token:
        prefix = token.split(":", 1)[0]
        return f"{prefix}:***"
    return "***"


def sanitize_telegram_string(text: str, token: str | None = None) -> str:
    """Remove raw bot tokens from log messages, URLs, and exception messages."""
    result = _BOT_TOKEN_REDACT_PATTERN.sub(r"\1***", text)
    if token and token in result:
        result = result.replace(token, mask_token(token))
    return result


def escape_markdown_v2(text: Any) -> str:
    """Escape all Telegram MarkdownV2 reserved characters with a leading backslash."""
    if text is None:
        return ""
    str_val = str(text)
    return _MD_V2_RESERVED_PATTERN.sub(r"\\\1", str_val)


class TelegramConfig(BaseModel):
    """Configuration model for Telegram notification client and sidecar daemon."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    bot_token: SecretStr | str = Field(
        default="",
        description="Telegram bot token obtained from @BotFather",
    )
    chat_id: str = Field(
        default="",
        description="Authorized Telegram chat ID for alert delivery and commands",
    )
    rate_limit_messages_per_second: float = Field(
        default=1.0,
        gt=0.0,
        le=30.0,
        description="Maximum rate of outbound messages per second (chat cap: 1.0, global: 30.0)",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts on transient network or HTTP 5xx/429 errors",
    )
    dry_run: bool = Field(
        default=False,
        description="If True, log alerts locally without making external Telegram HTTP calls",
    )
    parse_mode: str = Field(
        default="MarkdownV2",
        description="Default message formatting style (MarkdownV2, HTML, or empty)",
    )
    timeout_seconds: float = Field(
        default=10.0,
        gt=0.0,
        description="HTTP request timeout in seconds",
    )
    base_url: str = Field(
        default="https://api.telegram.org",
        description="Base Telegram Bot API URL",
    )

    def get_token_secret(self) -> str:
        """Return the unmasked bot token string."""
        if isinstance(self.bot_token, SecretStr):
            return self.bot_token.get_secret_value()
        return str(self.bot_token).strip()

    def mask_token(self) -> str:
        """Return the masked token string for safe logging and representation."""
        return mask_token(self.get_token_secret())

    @property
    def is_configured(self) -> bool:
        """Return True if both bot_token and chat_id are present and non-empty."""
        return bool(self.get_token_secret()) and bool(str(self.chat_id).strip())

    def __repr__(self) -> str:
        return (
            f"TelegramConfig(bot_token={self.mask_token()!r}, "
            f"chat_id={self.chat_id!r}, "
            f"rate_limit_messages_per_second={self.rate_limit_messages_per_second}, "
            f"max_retries={self.max_retries}, "
            f"dry_run={self.dry_run}, "
            f"parse_mode={self.parse_mode!r})"
        )


def _load_env_file_safely(env_path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE file safely without invoking third-party libraries."""
    entries: dict[str, str] = {}
    if not env_path.is_file():
        return entries
    try:
        text = env_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            entries[key] = val
    except OSError:
        pass
    return entries


def resolve_telegram_credentials(
    bot_token: str | None = None,
    chat_id: str | None = None,
    *,
    dry_run: bool = False,
    storage_dir: Path | str | None = None,
) -> TelegramConfig:
    """Resolve Telegram credentials following the strict priority cascade.

    Hierarchy:
    1. Direct CLI / function arguments (bot_token, chat_id).
    2. Process environment variables: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
       (CRITICAL: No API_KEY variables are ever evaluated to maintain safety compliance).
    3. Systemd credentials directory: $CREDENTIALS_DIRECTORY/telegram_bot_token.
    4. Local .env file in storage directory or current working directory.
    5. Fallback: If token or chat_id is missing or dry_run=True, return config with dry_run=True.
    """
    resolved_token = (bot_token or "").strip()
    resolved_chat_id = (chat_id or "").strip()

    # 1. Environment variables
    if not resolved_token:
        resolved_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not resolved_chat_id:
        resolved_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    # 2. Systemd credentials directory
    creds_dir_str = os.environ.get("CREDENTIALS_DIRECTORY", "").strip()
    if creds_dir_str:
        creds_dir = Path(creds_dir_str)
        if creds_dir.is_dir():
            token_file = creds_dir / "telegram_bot_token"
            chat_file = creds_dir / "telegram_chat_id"
            if not resolved_token and token_file.is_file():
                try:
                    resolved_token = token_file.read_text(encoding="utf-8").strip()
                except OSError:
                    pass
            if not resolved_chat_id and chat_file.is_file():
                try:
                    resolved_chat_id = chat_file.read_text(encoding="utf-8").strip()
                except OSError:
                    pass

    # 3. Local .env file
    if not resolved_token or not resolved_chat_id:
        candidate_env_paths: list[Path] = []
        if storage_dir is not None:
            candidate_env_paths.append(Path(storage_dir) / ".env")
        candidate_env_paths.append(Path(".env"))
        candidate_env_paths.append(Path("/opt/autonomous-futures-bot/.env"))

        for env_path in candidate_env_paths:
            env_vars = _load_env_file_safely(env_path)
            if not resolved_token and "TELEGRAM_BOT_TOKEN" in env_vars:
                resolved_token = env_vars["TELEGRAM_BOT_TOKEN"].strip()
            if not resolved_chat_id and "TELEGRAM_CHAT_ID" in env_vars:
                resolved_chat_id = env_vars["TELEGRAM_CHAT_ID"].strip()
            if resolved_token and resolved_chat_id:
                break

    # 4. Determine final dry_run mode
    effective_dry_run = dry_run or (not resolved_token) or (not resolved_chat_id)

    return TelegramConfig(
        bot_token=SecretStr(resolved_token) if resolved_token else "",
        chat_id=resolved_chat_id,
        dry_run=effective_dry_run,
    )


# ---------------------------------------------------------------------------
# Alert Formatters
# ---------------------------------------------------------------------------


def format_trade_opened_alert(event: dict[str, Any]) -> str:
    """Format a paper Trade Opened alert using Telegram MarkdownV2 syntax."""
    symbol = str(event.get("symbol", "UNKNOWN")).upper()
    side = str(event.get("side", "LONG")).upper()
    fill_price = _price_text(_event_value(event, "fill_price"))
    quantity = _decimal_text(_event_value(event, "quantity"), Decimal("0.00000001"), trim=True)
    margin = _decimal_text(
        _event_value(event, "allocated_margin", "margin", "margin_allocated"), Decimal("0.01")
    )
    leverage = _decimal_text(_event_value(event, "leverage"), Decimal("0.1"))
    stop_loss = _price_text(_event_value(event, "stop_loss_price", "stop_loss", "sl"))
    take_profit = _price_text(_event_value(event, "take_profit_price", "take_profit", "tp"))
    conviction = _decimal_text(
        _event_value(event, "conviction_score", "conviction", "score"), Decimal("0.01")
    )
    trade_id = str(event.get("trade_id", "N/A"))
    occurred_at = _myt_text(_event_value(event, "occurred_at"))
    return (
        f"🟢 *PAPER TRADE OPENED* \\| {escape_markdown_v2(symbol)}\n"
        f"─────────────────────────\n"
        f"• *Side*: {escape_markdown_v2(side)}\n"
        f"• *Fill Price*: {escape_markdown_v2(_money_text(fill_price, ''))}\n"
        f"• *Quantity*: {escape_markdown_v2(quantity)}\n"
        f"• *Margin Allocated*: {escape_markdown_v2(_money_text(margin))}\n"
        f"• *Leverage*: {escape_markdown_v2(leverage)}x\n"
        f"• *Dynamic ATR Stop*: {escape_markdown_v2(_money_text(stop_loss, ''))}\n"
        f"• *Take Profit*: {escape_markdown_v2(_money_text(take_profit, ''))}\n"
        f"• *Conviction*: {escape_markdown_v2(conviction)}\n"
        f"• *Trade ID*: `{escape_markdown_v2(trade_id)}`\n"
        f"• *Time*: {escape_markdown_v2(occurred_at)}"
    )


def format_trade_closed_alert(event: dict[str, Any]) -> str:
    """Format a paper Trade Closed alert using Telegram MarkdownV2 syntax."""
    symbol = str(event.get("symbol", "UNKNOWN")).upper()
    side = str(event.get("side", "LONG")).upper()
    exit_reason = str(_event_value(event, "exit_reason", "reason") or "Unavailable")
    entry_price = _price_text(_event_value(event, "entry_price"))
    exit_price = _price_text(_event_value(event, "exit_price", "fill_price"))
    pnl_value = _finite_decimal(_event_value(event, "net_pnl"))
    net_pnl = _decimal_text(
        abs(Decimal(str(pnl_value))) if pnl_value is not None else None, Decimal("0.0001")
    )
    pnl_pct_value = _finite_decimal(_event_value(event, "net_pnl_pct", "pnl_pct"))
    pnl_pct = "" if pnl_pct_value is None else _decimal_text(pnl_pct_value, Decimal("0.01"))
    if pnl_pct_value is not None and Decimal(str(pnl_pct_value)) >= 0:
        pnl_pct = f"+{pnl_pct}"
    total_fees = _decimal_text(_event_value(event, "total_fees", "fees"), Decimal("0.0001"))
    if "total_fees" not in event and "fees" not in event:
        known_fees = [
            _finite_decimal(event[name])
            for name in ("entry_fee", "exit_fee")
            if name in event and event[name] is not None
        ]
        if len(known_fees) == 2 and all(fee is not None for fee in known_fees):
            total_fees = _decimal_text(
                sum((Decimal(str(fee)) for fee in known_fees), Decimal("0")), Decimal("0.0001")
            )
    cash = _decimal_text(_event_value(event, "cumulative_cash", "cash"), Decimal("0.01"))
    equity = _decimal_text(_event_value(event, "cumulative_equity", "equity"), Decimal("0.01"))
    trade_id = str(event.get("trade_id", "N/A"))
    occurred_at = _myt_text(_event_value(event, "occurred_at"))
    try:
        pnl_decimal = Decimal(str(pnl_value)) if pnl_value is not None else None
    except InvalidOperation:
        pnl_decimal = None
    except ValueError:
        pnl_decimal = None
    icon = (
        "🟢"
        if pnl_decimal is not None and pnl_decimal > 0
        else "🔴"
        if pnl_decimal is not None and pnl_decimal < 0
        else "⚪"
    )
    pnl_display = (
        f"-${net_pnl} USDT"
        if pnl_decimal is not None and pnl_decimal < 0
        else f"+${net_pnl} USDT"
        if pnl_decimal is not None
        else "Unavailable"
    )
    if pnl_pct:
        pnl_display += f" ({pnl_pct}%)"
    return (
        f"{icon} *PAPER TRADE CLOSED* \\| {escape_markdown_v2(symbol)}\n"
        f"─────────────────────────\n"
        f"• *Side*: {escape_markdown_v2(side)}\n"
        f"• *Net Realized PnL*: {escape_markdown_v2(pnl_display)}\n"
        f"• *Exit Reason*: `{escape_markdown_v2(exit_reason)}`\n"
        f"• *Entry Price*: {escape_markdown_v2(_money_text(entry_price, ''))}\n"
        f"• *Exit Fill*: {escape_markdown_v2(_money_text(exit_price, ''))}\n"
        f"• *Total Fees*: {escape_markdown_v2(_money_text(total_fees))}\n"
        f"• *Cash Balance*: {escape_markdown_v2(_money_text(cash))}\n"
        f"• *Portfolio Equity*: {escape_markdown_v2(_money_text(equity))}\n"
        f"• *Trade ID*: `{escape_markdown_v2(trade_id)}`\n"
        f"• *Time*: {escape_markdown_v2(occurred_at)}"
    )


def format_risk_alert(alert_type: str, details: dict[str, Any]) -> str:
    """Format a ⚠️ Risk Alert (Circuit Breaker or Margin Warning) in MarkdownV2."""
    time_str = _myt_text(_event_value(details, "occurred_at"))
    alert_lower = alert_type.lower()

    if "margin" in alert_lower or "utilization" in alert_lower:
        util_pct = str(details.get("margin_utilization_pct", "0.0"))
        buffer_pct = str(details.get("reserve_buffer_pct", "100.0"))
        cash = _decimal_text(_event_value(details, "current_cash", "cash"), Decimal("0.01"))
        equity = _decimal_text(_event_value(details, "current_equity", "equity"), Decimal("0.01"))
        warning_msg = str(details.get("message", "Margin utilization threshold exceeded."))

        return (
            f"⚠️ *PORTFOLIO RISK WARNING*\n"
            f"─────────────────────────\n"
            f"• *Event*: Margin Utilization Alert\n"
            f"• *Current Utilization*: {escape_markdown_v2(util_pct)}% "
            f"\\(Warning: 70%, Cap: 80%\\)\n"
            f"• *Reserve Buffer*: {escape_markdown_v2(buffer_pct)}% \\(Floor: 20%\\)\n"
            f"• *Current Cash*: {escape_markdown_v2(_money_text(cash))}\n"
            f"• *Net Equity*: {escape_markdown_v2(_money_text(equity))}\n"
            f"• *Notice*: {escape_markdown_v2(warning_msg)}\n"
            f"• *Time*: {escape_markdown_v2(time_str)}"
        )

    # Circuit Breaker event
    status = str(details.get("status", "HALTED")).upper()
    symbol = str(details.get("symbol", "PORTFOLIO")).upper()
    breaker_type = str(details.get("breaker_type") or details.get("metric_name") or alert_type)
    metric_val = str(details.get("current_value", "N/A"))
    threshold = str(details.get("threshold_value", "N/A"))
    action = str(details.get("action_taken", "New order submissions inhibited."))

    return (
        f"⚠️ *CIRCUIT BREAKER ALERT*\n"
        f"─────────────────────────\n"
        f"• *Status*: *{escape_markdown_v2(status)}*\n"
        f"• *Target*: {escape_markdown_v2(symbol)}\n"
        f"• *Breaker*: `{escape_markdown_v2(breaker_type)}`\n"
        f"• *Value / Threshold*: {escape_markdown_v2(metric_val)} "
        f"\\(Threshold: {escape_markdown_v2(threshold)}\\)\n"
        f"• *Action Enforced*: {escape_markdown_v2(action)}\n"
        f"• *Time*: {escape_markdown_v2(time_str)}"
    )


def format_portfolio_digest(
    health: dict[str, Any], positions: list[dict[str, Any]] | None = None
) -> str:
    """Format a 📊 Periodic Portfolio Digest alert using MarkdownV2 syntax."""
    daemon_status = str(health.get("daemon_status") or health.get("status") or "RUNNING")
    pid = str(health.get("pid", "N/A"))
    uptime_sec = float(health.get("uptime_seconds", 0.0))

    # Format uptime nicely
    hours = int(uptime_sec // 3600)
    minutes = int((uptime_sec % 3600) // 60)
    uptime_str = f"{hours}h {minutes}m"

    equity = _decimal_text(
        _event_value(health, "current_equity_usdt", "current_equity", "equity"), Decimal("0.01")
    )
    cash = _decimal_text(
        _event_value(health, "current_cash_usdt", "current_cash", "cash"), Decimal("0.01")
    )
    realized_pnl = _decimal_text(_event_value(health, "realized_pnl"), Decimal("0.0001"))
    margin_util = str(health.get("margin_utilization_pct", "0.0"))
    reserve_buf = str(health.get("reserve_buffer_pct", "100.0"))
    throughput = str(health.get("feed_throughput_per_sec", "0.0"))
    time_str = _myt_text(_event_value(health, "occurred_at"))

    pos_list = positions or []
    pos_count = len(pos_list)

    msg = (
        f"📊 *PAPER PORTFOLIO DIGEST*\n"
        f"─────────────────────────\n"
        f"• *Net Equity*: {escape_markdown_v2(_money_text(equity))}\n"
        f"• *Cash Balance*: {escape_markdown_v2(_money_text(cash))}\n"
        f"• *Realized PnL*: {escape_markdown_v2(_money_text(realized_pnl))}\n"
        f"• *Margin Utilization*: {escape_markdown_v2(margin_util)}% "
        f"\\(Reserve: {escape_markdown_v2(reserve_buf)}%\\)\n"
        f"• *Active Positions*: {escape_markdown_v2(str(pos_count))}\n"
        f"• *Daemon*: {escape_markdown_v2(daemon_status)} \\(PID {escape_markdown_v2(pid)}\\)\n"
        f"• *Uptime*: {escape_markdown_v2(uptime_str)}\n"
        f"• *Throughput*: {escape_markdown_v2(throughput)} msgs/sec\n"
        f"• *Time*: {escape_markdown_v2(time_str)}"
    )

    if pos_list:
        msg += "\n\n*Open Positions*:\n"
        for p in pos_list[:5]:
            sym = escape_markdown_v2(str(p.get("symbol", "UNKNOWN")))
            sd = escape_markdown_v2(str(p.get("side", "LONG")))
            qty = escape_markdown_v2(
                _decimal_text(_event_value(p, "quantity"), Decimal("0.00000001"), trim=True)
            )
            px = escape_markdown_v2(_price_text(_event_value(p, "entry_price")))
            lev = escape_markdown_v2(
                _decimal_text(_event_value(p, "leverage"), Decimal("0.1"), trim=True)
            )
            msg += f"• {sym}: {sd} {qty} @ ${px} \\({lev}x\\)\n"

    return msg


def format_command_help() -> str:
    """Format the interactive /help command response."""
    return (
        "🤖 *Autonomous Futures Bot — Command Center*\n"
        "─────────────────────────\n"
        "Available Commands:\n"
        "• `/status` — Live daemon health, cash, equity & margin\n"
        "• `/positions` — Currently active paper positions\n"
        "• `/pnl` — Realized PnL summary and trade statistics\n"
        "• `/ping` — Latency probe and health confirmation\n"
        "• `/help` — Show this command reference\n"
        "• `/kill` — Emergency shutdown notice \\(read\\-only\\)"
    )


# ---------------------------------------------------------------------------
# Telegram Exceptions
# ---------------------------------------------------------------------------


class TelegramError(Exception):
    """Base exception for Telegram notifier operations."""


class TelegramHttpError(TelegramError):
    """Raised when Telegram Bot API returns an HTTP error status."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"Telegram API HTTP {status_code}: {message}")


class TelegramRateLimitError(TelegramHttpError):
    """Raised when Telegram Bot API rejects request with HTTP 429 after retries."""

    def __init__(self, retry_after: float, message: str) -> None:
        self.retry_after = retry_after
        super().__init__(429, f"Flood wait of {retry_after}s: {message}")


# ---------------------------------------------------------------------------
# Synchronous TelegramNotifierClient
# ---------------------------------------------------------------------------


class TelegramNotifierClient:
    """Resilient Telegram Bot API client with rate limiting, retries, and fallback."""

    def __init__(
        self,
        config: TelegramConfig | None = None,
        client: httpx.Client | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config or resolve_telegram_credentials()
        self._external_client = client is not None
        if client is not None:
            self._client = client
        else:
            self._client = httpx.Client(
                transport=transport,
                timeout=self.config.timeout_seconds,
            )
        self._last_send_timestamp: float = 0.0

    @property
    def is_dry_run(self) -> bool:
        """Return True if operating in local dry-run / mock mode."""
        return self.config.dry_run or (not self.config.is_configured)

    def _mask_text(self, text: str) -> str:
        """Redact bot token in strings before logging or raising."""
        return sanitize_telegram_string(text, self.config.get_token_secret())

    def _apply_rate_limit(self) -> None:
        """Enforce outbound message rate limiting."""
        min_interval = 1.0 / max(self.config.rate_limit_messages_per_second, 0.1)
        now = time.monotonic()
        elapsed = now - self._last_send_timestamp
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_send_timestamp = time.monotonic()

    def send_message(
        self,
        text: str,
        *,
        parse_mode: str | None = None,
        chat_id: str | None = None,
        disable_web_page_preview: bool = True,
    ) -> dict[str, Any]:
        """Send a message to Telegram with rate limiting, retries, and fallback.

        If parse_mode causes an HTTP 400 bad entity parse error, automatically
        retries sending the unformatted plain text.
        """
        target_chat_id = chat_id or self.config.chat_id
        effective_parse_mode = parse_mode if parse_mode is not None else self.config.parse_mode

        if self.is_dry_run:
            logger.info(
                "[DRY RUN / MOCK] Telegram message to chat_id=%s: %s",
                target_chat_id,
                self._mask_text(text[:120]),
            )
            return {
                "ok": True,
                "dry_run": True,
                "result": {
                    "message_id": 0,
                    "chat": {"id": target_chat_id},
                    "text": text,
                },
            }

        token = self.config.get_token_secret()
        url = f"{self.config.base_url}/bot{token}/sendMessage"

        payload: dict[str, Any] = {
            "chat_id": target_chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if effective_parse_mode:
            payload["parse_mode"] = effective_parse_mode

        retries = 0
        while retries <= self.config.max_retries:
            self._apply_rate_limit()
            try:
                resp = self._client.post(url, json=payload, timeout=self.config.timeout_seconds)

                # HTTP 200: Success
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict):
                        return data
                    return {"ok": True, "result": data}

                # HTTP 400: Potential Markdown parse error -> fallback to plain text
                if resp.status_code == 400:
                    err_msg = self._mask_text(resp.text)
                    if payload.get("parse_mode") and (
                        "can't parse entities" in err_msg.lower()
                        or "bad request" in err_msg.lower()
                    ):
                        logger.warning(
                            "Telegram parse error (HTTP 400). "
                            "Retrying as plain text without %s: %s",
                            payload.get("parse_mode"),
                            err_msg,
                        )
                        payload.pop("parse_mode", None)
                        retries += 1
                        continue
                    raise TelegramHttpError(400, err_msg)

                # HTTP 429: Rate limited
                if resp.status_code == 429:
                    retry_after = 1.0
                    try:
                        resp_json = resp.json()
                        retry_after = float(resp_json.get("parameters", {}).get("retry_after", 1.0))
                    except Exception:
                        retry_after_hdr = resp.headers.get("Retry-After")
                        if retry_after_hdr:
                            try:
                                retry_after = float(retry_after_hdr)
                            except ValueError:
                                retry_after = 1.0

                    sleep_dur = min(retry_after, 15.0)
                    logger.warning(
                        "Telegram HTTP 429 hit. Backing off for %.2fs (attempt %d/%d)",
                        sleep_dur,
                        retries + 1,
                        self.config.max_retries,
                    )
                    time.sleep(sleep_dur)
                    retries += 1
                    continue

                # HTTP 5xx: Server error
                if 500 <= resp.status_code < 600:
                    backoff = 0.5 * (2**retries)
                    logger.warning(
                        "Telegram server error HTTP %d. Backing off for %.2fs (attempt %d/%d)",
                        resp.status_code,
                        backoff,
                        retries + 1,
                        self.config.max_retries,
                    )
                    time.sleep(backoff)
                    retries += 1
                    continue

                # Other HTTP status codes
                raise TelegramHttpError(resp.status_code, self._mask_text(resp.text))

            except httpx.RequestError as exc:
                retries += 1
                if retries > self.config.max_retries:
                    raise TelegramError(
                        f"Network error after {retries} retries: {self._mask_text(str(exc))}"
                    ) from exc
                backoff = 0.5 * (2 ** (retries - 1))
                time.sleep(backoff)

        raise TelegramError(f"Failed to deliver message after {self.config.max_retries} retries.")

    def send_alert(self, alert_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Format an alert and dispatch it to the configured chat."""
        alert_lower = alert_type.lower()
        if alert_lower in ("trade_open", "trade_opened"):
            text = format_trade_opened_alert(payload)
        elif alert_lower in ("trade_close", "trade_closed"):
            text = format_trade_closed_alert(payload)
        elif alert_lower in ("risk_alert", "circuit_breaker", "margin_warning"):
            text = format_risk_alert(alert_type, payload)
        elif alert_lower == "portfolio_digest":
            text = format_portfolio_digest(payload.get("health", {}), payload.get("positions", []))
        else:
            text = str(payload)

        return self.send_message(text)

    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[dict[str, Any]]:
        """Long-poll incoming Telegram updates for interactive commands."""
        if self.is_dry_run:
            return []

        token = self.config.get_token_secret()
        url = f"{self.config.base_url}/bot{token}/getUpdates"
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset

        try:
            resp = self._client.get(
                url, params=params, timeout=float(timeout) + self.config.timeout_seconds
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    result = data.get("result", [])
                    if isinstance(result, list):
                        return result
            return []
        except Exception as exc:
            logger.warning("Error querying Telegram getUpdates: %s", self._mask_text(str(exc)))
            return []

    def close(self) -> None:
        """Close underlying HTTP client session if created internally."""
        if not self._external_client:
            self._client.close()

    def __enter__(self) -> TelegramNotifierClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"TelegramNotifierClient(bot_token={self.config.mask_token()!r}, "
            f"chat_id={self.config.chat_id!r}, "
            f"dry_run={self.is_dry_run})"
        )


# ---------------------------------------------------------------------------
# Asynchronous AsyncTelegramNotifierClient
# ---------------------------------------------------------------------------


class AsyncTelegramNotifierClient:
    """Asynchronous Telegram Bot API client using httpx.AsyncClient."""

    def __init__(
        self,
        config: TelegramConfig | None = None,
        client: httpx.AsyncClient | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config or resolve_telegram_credentials()
        self._external_client = client is not None
        if client is not None:
            self._client = client
        else:
            self._client = httpx.AsyncClient(
                transport=transport,
                timeout=self.config.timeout_seconds,
            )
        self._last_send_timestamp: float = 0.0

    @property
    def is_dry_run(self) -> bool:
        return self.config.dry_run or (not self.config.is_configured)

    def _mask_text(self, text: str) -> str:
        return sanitize_telegram_string(text, self.config.get_token_secret())

    async def _apply_rate_limit(self) -> None:
        min_interval = 1.0 / max(self.config.rate_limit_messages_per_second, 0.1)
        now = time.monotonic()
        elapsed = now - self._last_send_timestamp
        if elapsed < min_interval:
            import asyncio

            await asyncio.sleep(min_interval - elapsed)
        self._last_send_timestamp = time.monotonic()

    async def send_message(
        self,
        text: str,
        *,
        parse_mode: str | None = None,
        chat_id: str | None = None,
        disable_web_page_preview: bool = True,
    ) -> dict[str, Any]:
        """Asynchronously send message with retries and plain-text fallback."""
        target_chat_id = chat_id or self.config.chat_id
        effective_parse_mode = parse_mode if parse_mode is not None else self.config.parse_mode

        if self.is_dry_run:
            logger.info(
                "[DRY RUN / MOCK] Async Telegram message to chat_id=%s: %s",
                target_chat_id,
                self._mask_text(text[:120]),
            )
            return {
                "ok": True,
                "dry_run": True,
                "result": {"message_id": 0, "chat": {"id": target_chat_id}, "text": text},
            }

        token = self.config.get_token_secret()
        url = f"{self.config.base_url}/bot{token}/sendMessage"

        payload: dict[str, Any] = {
            "chat_id": target_chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if effective_parse_mode:
            payload["parse_mode"] = effective_parse_mode

        import asyncio

        retries = 0
        while retries <= self.config.max_retries:
            await self._apply_rate_limit()
            try:
                resp = await self._client.post(
                    url, json=payload, timeout=self.config.timeout_seconds
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict):
                        return data
                    return {"ok": True, "result": data}

                if resp.status_code == 400:
                    err_msg = self._mask_text(resp.text)
                    if payload.get("parse_mode") and (
                        "can't parse entities" in err_msg.lower()
                        or "bad request" in err_msg.lower()
                    ):
                        logger.warning(
                            "Telegram parse error (HTTP 400). Retrying as plain text: %s",
                            err_msg,
                        )
                        payload.pop("parse_mode", None)
                        retries += 1
                        continue
                    raise TelegramHttpError(400, err_msg)

                if resp.status_code == 429:
                    retry_after = 1.0
                    try:
                        retry_after = float(
                            resp.json().get("parameters", {}).get("retry_after", 1.0)
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(min(retry_after, 15.0))
                    retries += 1
                    continue

                if 500 <= resp.status_code < 600:
                    await asyncio.sleep(0.5 * (2**retries))
                    retries += 1
                    continue

                raise TelegramHttpError(resp.status_code, self._mask_text(resp.text))

            except httpx.RequestError as exc:
                retries += 1
                if retries > self.config.max_retries:
                    raise TelegramError(f"Network error: {self._mask_text(str(exc))}") from exc
                await asyncio.sleep(0.5 * (2 ** (retries - 1)))

        raise TelegramError("Exhausted max retries.")

    async def send_alert(self, alert_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Asynchronously format and send an alert."""
        alert_lower = alert_type.lower()
        if alert_lower in ("trade_open", "trade_opened"):
            text = format_trade_opened_alert(payload)
        elif alert_lower in ("trade_close", "trade_closed"):
            text = format_trade_closed_alert(payload)
        elif alert_lower in ("risk_alert", "circuit_breaker", "margin_warning"):
            text = format_risk_alert(alert_type, payload)
        elif alert_lower == "portfolio_digest":
            text = format_portfolio_digest(payload.get("health", {}), payload.get("positions", []))
        else:
            text = str(payload)
        return await self.send_message(text)

    async def get_updates(
        self, offset: int | None = None, timeout: int = 30
    ) -> list[dict[str, Any]]:
        """Asynchronously query Telegram getUpdates."""
        if self.is_dry_run:
            return []
        token = self.config.get_token_secret()
        url = f"{self.config.base_url}/bot{token}/getUpdates"
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset

        try:
            resp = await self._client.get(
                url, params=params, timeout=float(timeout) + self.config.timeout_seconds
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    result = data.get("result", [])
                    if isinstance(result, list):
                        return result
            return []
        except Exception as exc:
            logger.warning("Error querying Telegram getUpdates: %s", self._mask_text(str(exc)))
            return []

    async def aclose(self) -> None:
        """Close async HTTP client session."""
        if not self._external_client:
            await self._client.aclose()

    async def __aenter__(self) -> AsyncTelegramNotifierClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.aclose()

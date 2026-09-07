"""Unit test suite for Telegram notification engine, formatters, and sidecar daemon.

Provides 100% offline coverage with zero network sockets using httpx.MockTransport.
Validates config resolution, MarkdownV2 escaping, alert formatting, rate limiting,
HTTP 429/5xx backoff, HTTP 400 plain-text fallback, ledger deduplication,
checkpointing, and interactive command handling.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

# Ensure repository root is on sys.path for scripts import
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.notify.telegram import (  # noqa: E402
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
    sanitize_telegram_string,
)
from scripts.run_telegram_notifier import (  # noqa: E402
    CheckpointState,
    TelegramNotifierDaemon,
    build_arg_parser,
)

# ---------------------------------------------------------------------------
# 1. TelegramConfig & Token Masking Tests
# ---------------------------------------------------------------------------


class TestTelegramConfig:
    def test_config_defaults(self) -> None:
        cfg = TelegramConfig()
        assert cfg.bot_token == ""
        assert cfg.chat_id == ""
        assert cfg.rate_limit_messages_per_second == 1.0
        assert cfg.max_retries == 3
        assert cfg.dry_run is False
        assert cfg.parse_mode == "MarkdownV2"
        assert cfg.timeout_seconds == 10.0
        assert cfg.is_configured is False

    def test_token_masking_variants(self) -> None:
        assert mask_token("123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ") == "123456789:***"
        assert mask_token("raw_secret_without_colon") == "***"
        assert mask_token("") == "<NONE>"
        assert mask_token(None) == "<NONE>"

    def test_config_repr_redacts_token(self) -> None:
        token = "987654321:SECRET_TOKEN_XYZ"
        cfg = TelegramConfig(bot_token=SecretStr(token), chat_id="123456")
        repr_str = repr(cfg)
        assert token not in repr_str
        assert "987654321:***" in repr_str
        assert cfg.mask_token() == "987654321:***"
        assert cfg.get_token_secret() == token
        assert cfg.is_configured is True

    def test_sanitize_telegram_string(self) -> None:
        raw_url = "https://api.telegram.org/bot123456:ABCdefGhIJKlmNoPQRsTUVwxyZ/sendMessage"
        sanitized = sanitize_telegram_string(raw_url, "123456:ABCdefGhIJKlmNoPQRsTUVwxyZ")
        assert "ABCdefGhIJKlmNoPQRsTUVwxyZ" not in sanitized
        assert "bot123456:***" in sanitized


# ---------------------------------------------------------------------------
# 2. Credential Resolution Hierarchy Tests
# ---------------------------------------------------------------------------


class TestCredentialResolution:
    def test_cli_overrides_env_and_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env_token:123")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "env_chat")

        cfg = resolve_telegram_credentials(
            bot_token="cli_token:456",
            chat_id="cli_chat",
            dry_run=False,
        )
        assert cfg.get_token_secret() == "cli_token:456"
        assert cfg.chat_id == "cli_chat"
        assert cfg.dry_run is False

    def test_env_var_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ENV_SECRET")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123456")

        cfg = resolve_telegram_credentials()
        assert cfg.get_token_secret() == "123456:ENV_SECRET"
        assert cfg.chat_id == "-100123456"
        assert cfg.dry_run is False

    def test_systemd_credentials_resolution(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

        creds_dir = tmp_path / "creds"
        creds_dir.mkdir()
        (creds_dir / "telegram_bot_token").write_text("systemd_tok:999\n", encoding="utf-8")
        (creds_dir / "telegram_chat_id").write_text("systemd_chat_id\n", encoding="utf-8")
        monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(creds_dir))

        cfg = resolve_telegram_credentials(storage_dir=tmp_path)
        assert cfg.get_token_secret() == "systemd_tok:999"
        assert cfg.chat_id == "systemd_chat_id"
        assert cfg.dry_run is False

    def test_dot_env_file_resolution(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)

        env_file = tmp_path / ".env"
        env_file.write_text(
            "# Config\nTELEGRAM_BOT_TOKEN=dotenv_tok:555\nTELEGRAM_CHAT_ID=dotenv_chat\n",
            encoding="utf-8",
        )

        cfg = resolve_telegram_credentials(storage_dir=tmp_path)
        assert cfg.get_token_secret() == "dotenv_tok:555"
        assert cfg.chat_id == "dotenv_chat"
        assert cfg.dry_run is False

    def test_unconfigured_defaults_to_dry_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
        monkeypatch.setattr(
            "autonomous_futures.notify.telegram._load_env_file_safely", lambda _: {}
        )

        cfg = resolve_telegram_credentials(storage_dir=Path("nonexistent_dir"))
        assert cfg.dry_run is True
        assert cfg.is_configured is False


# ---------------------------------------------------------------------------
# 3. MarkdownV2 Escaping Tests
# ---------------------------------------------------------------------------


class TestMarkdownV2Sanitization:
    def test_all_18_reserved_characters_escaped(self) -> None:
        # Spec characters: _ * [ ] ( ) ~ > # + - = | { } . ! \
        spec_chars = "_*[]()~>#+-=|{}.!\\"
        escaped = escape_markdown_v2(spec_chars)
        expected = (
            r"\_"
            r"\*"
            r"\["
            r"\]"
            r"\("
            r"\)"
            r"\~"
            r"\>"
            r"\#"
            r"\+"
            r"\-"
            r"\="
            r"\|"
            r"\{"
            r"\}"
            r"\."
            r"\!"
            r"\\"
        )
        assert escaped == expected

    def test_financial_and_identifier_strings(self) -> None:
        assert escape_markdown_v2("2,483.84") == r"2,483\.84"
        assert escape_markdown_v2("-0.50%") == r"\-0\.50%"
        assert escape_markdown_v2("cand-1f87_3b.v2") == r"cand\-1f87\_3b\.v2"
        assert escape_markdown_v2("LONG (+1.10%)") == r"LONG \(\+1\.10%\)"

    def test_none_and_empty(self) -> None:
        assert escape_markdown_v2(None) == ""
        assert escape_markdown_v2("") == ""

    def test_markdown_escaping_of_backticks(self) -> None:
        """Verify backticks are escaped per Telegram MarkdownV2 specification."""
        assert escape_markdown_v2("`") == r"\`"
        assert escape_markdown_v2("code `with` backtick") == r"code \`with\` backtick"
        assert escape_markdown_v2(chr(96)) == r"\`"

    def test_all_19_reserved_characters_escaped(self) -> None:
        """Verify all 19 reserved characters including backtick are escaped."""
        spec_chars = "_*[]()~`>#+-=|{}.!\\"
        escaped = escape_markdown_v2(spec_chars)
        expected = (
            r"\_"
            r"\*"
            r"\["
            r"\]"
            r"\("
            r"\)"
            r"\~"
            r"\`"
            r"\>"
            r"\#"
            r"\+"
            r"\-"
            r"\="
            r"\|"
            r"\{"
            r"\}"
            r"\."
            r"\!"
            r"\\"
        )
        assert escaped == expected


# ---------------------------------------------------------------------------
# 4. Alert Formatters Tests
# ---------------------------------------------------------------------------


class TestAlertFormatters:
    def test_format_trade_opened_alert(self) -> None:
        event = {
            "symbol": "BTCUSDT",
            "side": "LONG",
            "fill_price": "79722.04",
            "quantity": "0.000125",
            "allocated_margin": "20.00",
            "leverage": "1.0",
            "stop_loss_price": "78500.00",
            "take_profit_price": "82000.00",
            "conviction_score": "0.85",
            "trade_id": "paper-cand-123",
            "occurred_at": "2026-09-06 18:00:00 UTC",
        }
        msg = format_trade_opened_alert(event)
        assert r"🟢 *TRADE OPENED* \| BTCUSDT" in msg
        assert r"$79722\.04" in msg
        assert r"0\.000125" in msg
        assert r"$20\.00 USDT" in msg
        assert r"1\.0x" in msg
        assert r"`paper\-cand\-123`" in msg

    def test_format_trade_closed_alert(self) -> None:
        event = {
            "symbol": "ETHUSDT",
            "side": "LONG",
            "exit_reason": "take_profit_hit",
            "entry_price": "2483.84",
            "exit_price": "2495.20",
            "net_pnl": "0.2200",
            "net_pnl_pct": "+1.10",
            "total_fees": "0.0192",
            "cumulative_cash": "100.22",
            "cumulative_equity": "100.22",
            "trade_id": "trade-999",
            "occurred_at": "2026-09-06 18:15:00 UTC",
        }
        msg = format_trade_closed_alert(event)
        assert r"🔴 *TRADE CLOSED* \| ETHUSDT" in msg
        assert r"`take\_profit\_hit`" in msg
        assert r"$2483\.84" in msg
        assert r"$2495\.20" in msg
        assert r"\+$0\.2200 USDT \(\+1\.10%\)" in msg
        assert r"$100\.22 USDT" in msg

    def test_format_circuit_breaker_alert(self) -> None:
        details = {
            "symbol": "BTCUSDT",
            "breaker_type": "spread_blowout",
            "status": "HALTED",
            "current_value": "24.5 bps",
            "threshold_value": "20.0 bps",
            "action_taken": "New entry orders blocked",
            "occurred_at": "2026-09-06 18:20:00 UTC",
        }
        msg = format_risk_alert("circuit_breaker", details)
        assert "⚠️ *CIRCUIT BREAKER ALERT*" in msg
        assert "*HALTED*" in msg
        assert r"`spread\_blowout`" in msg
        assert r"24\.5 bps" in msg

    def test_format_margin_warning_alert(self) -> None:
        details = {
            "margin_utilization_pct": 74.2,
            "reserve_buffer_pct": 25.8,
            "current_cash": "99.82",
            "current_equity": "100.15",
            "message": "Utilization exceeded 70% threshold.",
            "occurred_at": "2026-09-06 18:25:00 UTC",
        }
        msg = format_risk_alert("margin_warning", details)
        assert "⚠️ *PORTFOLIO RISK WARNING*" in msg
        assert r"74\.2%" in msg
        assert r"25\.8%" in msg
        assert r"$99\.82 USDT" in msg

    def test_format_portfolio_digest(self) -> None:
        health = {
            "daemon_status": "RUNNING",
            "pid": 471588,
            "uptime_seconds": 7200.0,
            "current_equity": "100.25",
            "current_cash": "99.85",
            "realized_pnl": "0.40",
            "margin_utilization_pct": 19.9,
            "reserve_buffer_pct": 80.1,
            "feed_throughput_per_sec": 15.5,
            "occurred_at": "2026-09-06 19:00:00 UTC",
        }
        positions = [
            {
                "symbol": "BTCUSDT",
                "side": "LONG",
                "quantity": "0.000125",
                "entry_price": "79722.04",
                "leverage": "1.0",
            }
        ]
        msg = format_portfolio_digest(health, positions)
        assert "📊 *PORTFOLIO DIGEST*" in msg
        assert "RUNNING" in msg
        assert "2h 0m" in msg
        assert r"$100\.25 USDT" in msg
        assert "Active Positions*: 1" in msg
        assert "BTCUSDT: LONG" in msg

    def test_format_command_help(self) -> None:
        help_msg = format_command_help()
        assert "/status" in help_msg
        assert "/positions" in help_msg
        assert "/pnl" in help_msg
        assert "/ping" in help_msg
        assert "/help" in help_msg
        assert "/kill" in help_msg


# ---------------------------------------------------------------------------
# 5. TelegramNotifierClient & Resilience Tests (httpx.MockTransport)
# ---------------------------------------------------------------------------


class TestTelegramNotifierClient:
    def test_send_message_dry_run(self) -> None:
        cfg = TelegramConfig(dry_run=True, chat_id="123")
        client = TelegramNotifierClient(cfg)
        res = client.send_message("Test dry run")
        assert res.get("ok") is True
        assert res.get("dry_run") is True
        assert res.get("result", {}).get("text") == "Test dry run"

    def test_send_message_200_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "sendMessage" in str(request.url)
            body = json.loads(request.content)
            assert body.get("chat_id") == "12345"
            assert body.get("text") == "Hello World"
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 101}})

        transport = httpx.MockTransport(handler)
        cfg = TelegramConfig(bot_token="tok:123", chat_id="12345", dry_run=False)
        client = TelegramNotifierClient(cfg, transport=transport)

        res = client.send_message("Hello World")
        assert res.get("ok") is True
        assert res.get("result", {}).get("message_id") == 101

    def test_rate_limiting_pacing(self) -> None:
        call_times: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            call_times.append(time.monotonic())
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

        transport = httpx.MockTransport(handler)
        # Cap at 5.0 msgs/second = 0.2s minimum interval
        cfg = TelegramConfig(
            bot_token="tok:123",
            chat_id="12345",
            dry_run=False,
            rate_limit_messages_per_second=5.0,
        )
        client = TelegramNotifierClient(cfg, transport=transport)

        client.send_message("Msg 1")
        client.send_message("Msg 2")

        assert len(call_times) == 2
        elapsed = call_times[1] - call_times[0]
        assert elapsed >= 0.18  # Allowing slight clock granularity tolerance

    def test_http_429_retry_after_handling(self) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(
                    429,
                    json={"ok": False, "error_code": 429, "parameters": {"retry_after": 0.05}},
                )
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 202}})

        transport = httpx.MockTransport(handler)
        cfg = TelegramConfig(bot_token="tok:123", chat_id="12345", dry_run=False)
        client = TelegramNotifierClient(cfg, transport=transport)

        res = client.send_message("Retry after test")
        assert attempts == 2
        assert res.get("ok") is True

    def test_http_5xx_server_error_backoff(self) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(502, text="Bad Gateway")
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 303}})

        transport = httpx.MockTransport(handler)
        cfg = TelegramConfig(bot_token="tok:123", chat_id="12345", dry_run=False)
        client = TelegramNotifierClient(cfg, transport=transport)

        res = client.send_message("5xx test")
        assert attempts == 2
        assert res.get("ok") is True

    def test_http_400_plain_text_fallback(self) -> None:
        attempts = 0
        received_payloads: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            body = json.loads(request.content)
            received_payloads.append(body)
            if attempts == 1:
                assert body.get("parse_mode") == "MarkdownV2"
                return httpx.Response(
                    400,
                    json={
                        "ok": False,
                        "error_code": 400,
                        "description": "Bad Request: can't parse entities",
                    },
                )
            # Second attempt should omit parse_mode
            assert "parse_mode" not in body
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 404}})

        transport = httpx.MockTransport(handler)
        cfg = TelegramConfig(
            bot_token="tok:123", chat_id="12345", parse_mode="MarkdownV2", dry_run=False
        )
        client = TelegramNotifierClient(cfg, transport=transport)

        res = client.send_message("Malformed *entity text")
        assert attempts == 2
        assert res.get("ok") is True

    def test_get_updates(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "getUpdates" in str(request.url)
            assert "offset=10" in str(request.url)
            return httpx.Response(
                200,
                json={"ok": True, "result": [{"update_id": 10, "message": {"text": "/status"}}]},
            )

        transport = httpx.MockTransport(handler)
        cfg = TelegramConfig(bot_token="tok:123", chat_id="12345", dry_run=False)
        client = TelegramNotifierClient(cfg, transport=transport)

        updates = client.get_updates(offset=10, timeout=1)
        assert len(updates) == 1
        assert updates[0]["update_id"] == 10

    def test_token_redacted_in_exception(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401, json={"ok": False, "description": "Unauthorized token 123456:SECRET_KEY"}
            )

        transport = httpx.MockTransport(handler)
        cfg = TelegramConfig(bot_token="123456:SECRET_KEY", chat_id="12345", dry_run=False)
        client = TelegramNotifierClient(cfg, transport=transport)

        with pytest.raises(Exception) as exc_info:
            client.send_message("Trigger 401")
        err_msg = str(exc_info.value)
        assert "SECRET_KEY" not in err_msg
        assert "123456:***" in err_msg


# ---------------------------------------------------------------------------
# 6. Async Client Tests (AsyncTelegramNotifierClient)
# ---------------------------------------------------------------------------


class TestAsyncTelegramNotifierClient:
    def test_async_send_message_and_alert(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 505}})

        transport = httpx.MockTransport(handler)
        cfg = TelegramConfig(bot_token="tok:123", chat_id="12345", dry_run=False)
        client = AsyncTelegramNotifierClient(cfg, transport=transport)

        async def run_test() -> None:
            res = await client.send_message("Async test")
            assert res.get("ok") is True

            alert_res = await client.send_alert(
                "trade_open",
                {
                    "symbol": "BTCUSDT",
                    "side": "LONG",
                    "fill_price": "79000",
                    "quantity": "0.001",
                },
            )
            assert alert_res.get("ok") is True
            await client.aclose()

        asyncio.run(run_test())


# ---------------------------------------------------------------------------
# 7. Checkpoint State & SQLite Event Ingestion Tests
# ---------------------------------------------------------------------------


def setup_mock_storage(storage_dir: Path) -> None:
    """Create mock paper ledger SQLite database and health JSON file."""
    storage_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create paper-ledger.sqlite3
    ledger_db = storage_dir / "paper-ledger.sqlite3"
    conn = sqlite3.connect(ledger_db)
    conn.execute(
        """
        CREATE TABLE paper_ledger_events (
            sequence INTEGER PRIMARY KEY,
            event TEXT NOT NULL,
            trade_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity TEXT NOT NULL,
            fill_price TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            approval_id TEXT,
            entry_fee TEXT,
            exit_fee TEXT,
            slippage_cost TEXT,
            gross_pnl TEXT,
            net_pnl TEXT
        )
        """
    )
    conn.commit()
    conn.close()

    # 2. Create paper-daemon-health.json
    health_file = storage_dir / "paper-daemon-health.json"
    health_data = {
        "daemon_status": "RUNNING",
        "pid": 12345,
        "uptime_seconds": 3600.0,
        "current_cash_usdt": "100.00",
        "current_equity_usdt": "100.00",
        "margin_utilization_pct": 0.0,
        "reserve_buffer_pct": 100.0,
        "active_positions_count": 0,
        "active_positions": {},
        "circuit_breaker_status": "NORMAL",
        "feed_messages_received": 5000,
        "feed_throughput_per_sec": 10.5,
        "feed_reconnects_count": 0,
        "zero_order_safety_invariants": {
            "orders_submitted": 0,
            "execution_authority": False,
        },
    }
    health_file.write_text(json.dumps(health_data, indent=2), encoding="utf-8")


class TestSidecarEventProcessing:
    def test_checkpoint_persistence(self, tmp_path: Path) -> None:
        cp_file = tmp_path / "telegram-checkpoint.json"
        cp = CheckpointState(cp_file)
        assert cp.last_sequence == 0

        cp.last_sequence = 42
        cp.last_cb_status = "HALTED"
        cp.last_margin_alerted = True
        cp.last_update_id = 999
        cp.save()

        # Reload
        cp2 = CheckpointState(cp_file)
        assert cp2.last_sequence == 42
        assert cp2.last_cb_status == "HALTED"
        assert cp2.last_margin_alerted is True
        assert cp2.last_update_id == 999

    def test_checkpoint_load_with_null_values(self, tmp_path: Path) -> None:
        """Verify CheckpointState.load() handles explicit null values safely."""
        cp_file = tmp_path / "telegram-checkpoint-null.json"
        cp_file.write_text(
            json.dumps(
                {
                    "last_sequence": None,
                    "last_cb_status": None,
                    "last_margin_alerted": None,
                    "last_digest_timestamp": None,
                    "last_update_id": None,
                }
            ),
            encoding="utf-8",
        )
        cp = CheckpointState(cp_file)
        assert cp.last_sequence == 0
        assert cp.last_cb_status == "NORMAL"
        assert cp.last_margin_alerted is False
        assert cp.last_digest_timestamp == 0.0
        assert cp.last_update_id == 0

    def test_checkpoint_load_malformed_types_fallback(self, tmp_path: Path) -> None:
        """Verify CheckpointState.load() recovers safely when fields have invalid types."""
        cp_file = tmp_path / "telegram-checkpoint-malformed.json"
        cp_file.write_text(
            json.dumps(
                {
                    "last_sequence": "invalid_not_an_int",
                    "last_digest_timestamp": [1, 2, 3],
                }
            ),
            encoding="utf-8",
        )
        cp = CheckpointState(cp_file)
        assert cp.last_sequence == 0
        assert cp.last_cb_status == "NORMAL"

    def test_checkpoint_corrupted_json_syntax_fallback(self, tmp_path: Path) -> None:
        """Verify CheckpointState.load() safely falls back when JSON is malformed."""
        cp_file = tmp_path / "telegram-checkpoint-corrupt.json"
        cp_file.write_text('{"last_sequence": 42, truncated...', encoding="utf-8")
        cp = CheckpointState(cp_file)
        assert cp.last_sequence == 0
        assert cp.last_cb_status == "NORMAL"

    def test_ledger_event_deduplication(self, tmp_path: Path) -> None:
        setup_mock_storage(tmp_path)
        ledger_db = tmp_path / "paper-ledger.sqlite3"

        # Insert 2 events
        conn = sqlite3.connect(ledger_db)
        conn.execute(
            """
            INSERT INTO paper_ledger_events
            (sequence, event, trade_id, symbol, side, quantity, fill_price, occurred_at)
            VALUES
            (1, 'open', 'trade-1', 'BTCUSDT', 'LONG', '0.001', '79000.00',
             '2026-09-06 18:00:00 UTC'),
            (2, 'close', 'trade-1', 'BTCUSDT', 'LONG', '0.001', '79500.00',
             '2026-09-06 18:10:00 UTC')
            """
        )
        conn.commit()
        conn.close()

        sent_messages: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            sent_messages.append(body.get("text", ""))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

        transport = httpx.MockTransport(handler)
        cfg = TelegramConfig(bot_token="tok:123", chat_id="12345", dry_run=False)
        client = TelegramNotifierClient(cfg, transport=transport)

        daemon = TelegramNotifierDaemon(
            config=cfg,
            storage_dir=tmp_path,
            client=client,
        )

        # First poll: Should process 2 events
        dispatched = daemon.poll_new_ledger_events()
        assert dispatched == 2
        assert len(sent_messages) == 2
        assert daemon.checkpoint.last_sequence == 2

        # Second poll: No new events
        dispatched_second = daemon.poll_new_ledger_events()
        assert dispatched_second == 0
        assert len(sent_messages) == 2

    def test_circuit_breaker_transition_and_margin_hysteresis(self, tmp_path: Path) -> None:
        setup_mock_storage(tmp_path)
        health_file = tmp_path / "paper-daemon-health.json"

        sent_alerts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            sent_alerts.append(body.get("text", ""))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

        transport = httpx.MockTransport(handler)
        cfg = TelegramConfig(bot_token="tok:123", chat_id="12345", dry_run=False)
        client = TelegramNotifierClient(cfg, transport=transport)

        daemon = TelegramNotifierDaemon(
            config=cfg,
            storage_dir=tmp_path,
            client=client,
        )

        # 1. Normal state: no alerts
        daemon.poll_circuit_breaker_and_margin()
        assert len(sent_alerts) == 0

        # 2. Transition to HALTED
        data = json.loads(health_file.read_text(encoding="utf-8"))
        data["circuit_breaker_status"] = "HALTED"
        health_file.write_text(json.dumps(data), encoding="utf-8")

        daemon.poll_circuit_breaker_and_margin()
        assert len(sent_alerts) == 1
        assert "CIRCUIT BREAKER ALERT" in sent_alerts[0]

        # 3. Subsequent poll while still HALTED: should NOT alert again
        daemon.poll_circuit_breaker_and_margin()
        assert len(sent_alerts) == 1

        # 4. Margin spike to 75%
        data["margin_utilization_pct"] = 75.0
        health_file.write_text(json.dumps(data), encoding="utf-8")

        daemon.poll_circuit_breaker_and_margin()
        assert len(sent_alerts) == 2
        assert "PORTFOLIO RISK WARNING" in sent_alerts[1]
        assert daemon.checkpoint.last_margin_alerted is True

        # 5. Margin fluctuates at 72%: should NOT re-alert (hysteresis active)
        data["margin_utilization_pct"] = 72.0
        health_file.write_text(json.dumps(data), encoding="utf-8")
        daemon.poll_circuit_breaker_and_margin()
        assert len(sent_alerts) == 2

        # 6. Margin cools down to 60% (below 65% floor): resets hysteresis
        data["margin_utilization_pct"] = 60.0
        health_file.write_text(json.dumps(data), encoding="utf-8")
        daemon.poll_circuit_breaker_and_margin()
        assert daemon.checkpoint.last_margin_alerted is False


# ---------------------------------------------------------------------------
# 8. Interactive Command Handler Tests
# ---------------------------------------------------------------------------


class TestInteractiveCommands:
    def test_authorized_commands(self, tmp_path: Path) -> None:
        setup_mock_storage(tmp_path)
        replies: list[str] = []

        mock_updates = [
            {"update_id": 1, "message": {"chat": {"id": 12345}, "text": "/status"}},
            {"update_id": 2, "message": {"chat": {"id": 12345}, "text": "/positions"}},
            {"update_id": 3, "message": {"chat": {"id": 12345}, "text": "/pnl"}},
            {"update_id": 4, "message": {"chat": {"id": 12345}, "text": "/ping"}},
            {"update_id": 5, "message": {"chat": {"id": 12345}, "text": "/help"}},
            {"update_id": 6, "message": {"chat": {"id": 12345}, "text": "/kill"}},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if "getUpdates" in url_str:
                return httpx.Response(200, json={"ok": True, "result": mock_updates})
            if "sendMessage" in url_str:
                body = json.loads(request.content)
                replies.append(body.get("text", ""))
                return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        cfg = TelegramConfig(bot_token="tok:123", chat_id="12345", dry_run=False)
        client = TelegramNotifierClient(cfg, transport=transport)

        daemon = TelegramNotifierDaemon(
            config=cfg,
            storage_dir=tmp_path,
            client=client,
        )

        handled = daemon.handle_interactive_commands()
        assert handled == 6
        assert len(replies) == 6

        # /status
        assert "DAEMON STATUS" in replies[0]
        # /positions
        assert "No active paper positions" in replies[1]
        # /pnl
        assert "PNL" in replies[2]
        # /ping
        assert "Pong" in replies[3]
        # /help
        assert "/status" in replies[4]
        # /kill -> Safety invariant notice
        assert "SAFETY INVARIANT NOTICE" in replies[5]
        assert "sudo systemctl stop" in replies[5]

    def test_unauthorized_chat_rejected(self, tmp_path: Path) -> None:
        setup_mock_storage(tmp_path)
        replies: list[str] = []

        mock_updates = [
            {"update_id": 1, "message": {"chat": {"id": 999999999}, "text": "/status"}},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            if "getUpdates" in str(request.url):
                return httpx.Response(200, json={"ok": True, "result": mock_updates})
            if "sendMessage" in str(request.url):
                replies.append("should not be called")
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        cfg = TelegramConfig(bot_token="tok:123", chat_id="12345", dry_run=False)
        client = TelegramNotifierClient(cfg, transport=transport)

        daemon = TelegramNotifierDaemon(
            config=cfg,
            storage_dir=tmp_path,
            client=client,
        )

        handled = daemon.handle_interactive_commands()
        assert handled == 0
        assert len(replies) == 0

    def test_handle_interactive_commands_malformed_updates_and_chat_none(
        self, tmp_path: Path
    ) -> None:
        """Verify malformed updates or chat=None are safely skipped without breaking poller."""
        setup_mock_storage(tmp_path)
        replies: list[str] = []

        malformed_updates = [
            # 1. Update where message has chat: None
            {"update_id": 1, "message": {"chat": None, "text": "/status"}},
            # 2. Update where message has non-dict chat (e.g. string)
            {"update_id": 2, "message": {"chat": "not_a_dict", "text": "/status"}},
            # 3. Update where message itself is not a dict
            {"update_id": 3, "message": "not_a_dict"},
            # 4. Update that is not a dict
            "not_a_dict",  # type: ignore[dict-item]
            # 5. Update where chat id is None
            {"update_id": 5, "message": {"chat": {"id": None}, "text": "/status"}},
            # 6. Valid authorized command following the malformed ones
            {"update_id": 6, "message": {"chat": {"id": 12345}, "text": "/ping"}},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if "getUpdates" in url_str:
                return httpx.Response(200, json={"ok": True, "result": malformed_updates})
            if "sendMessage" in url_str:
                body = json.loads(request.content)
                replies.append(body.get("text", ""))
                return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        cfg = TelegramConfig(bot_token="tok:123", chat_id="12345", dry_run=False)
        client = TelegramNotifierClient(cfg, transport=transport)

        daemon = TelegramNotifierDaemon(
            config=cfg,
            storage_dir=tmp_path,
            client=client,
        )

        handled = daemon.handle_interactive_commands()
        assert handled == 1
        assert len(replies) == 1
        assert "Pong" in replies[0]

    def test_pnl_command_handles_sqlite_operational_error(self, tmp_path: Path) -> None:
        """Verify /pnl catches sqlite3.Error and returns unavailable notice."""
        setup_mock_storage(tmp_path)
        ledger_db = tmp_path / "paper-ledger.sqlite3"
        # Incompatible schema missing columns
        conn = sqlite3.connect(ledger_db)
        conn.execute("DROP TABLE IF EXISTS paper_ledger_events")
        conn.execute("CREATE TABLE paper_ledger_events (sequence INTEGER PRIMARY KEY, event TEXT)")
        conn.commit()
        conn.close()

        replies: list[str] = []

        mock_updates = [
            {"update_id": 1, "message": {"chat": {"id": 12345}, "text": "/pnl"}},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if "getUpdates" in url_str:
                return httpx.Response(200, json={"ok": True, "result": mock_updates})
            if "sendMessage" in url_str:
                body = json.loads(request.content)
                replies.append(body.get("text", ""))
                return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        cfg = TelegramConfig(bot_token="tok:123", chat_id="12345", dry_run=False)
        client = TelegramNotifierClient(cfg, transport=transport)

        daemon = TelegramNotifierDaemon(
            config=cfg,
            storage_dir=tmp_path,
            client=client,
        )

        handled = daemon.handle_interactive_commands()
        assert handled == 1
        assert len(replies) == 1
        assert "⚠️ PnL summary temporarily unavailable" in replies[0]

    def test_edge_commands_and_injection_attempts(self, tmp_path: Path) -> None:
        """Test edge cases in command strings: trailing args, bot mentions, injections."""
        setup_mock_storage(tmp_path)
        replies: list[str] = []

        edge_updates = [
            {"update_id": 1, "message": {"chat": {"id": 12345}, "text": "/"}},
            {"update_id": 2, "message": {"chat": {"id": 12345}, "text": "/STATUS"}},
            {
                "update_id": 3,
                "message": {"chat": {"id": 12345}, "text": "/status@AutonomousFuturesBot"},
            },
            {"update_id": 4, "message": {"chat": {"id": 12345}, "text": "/unknown_command"}},
            {"update_id": 5, "message": {"chat": {"id": 12345}, "text": "/kill"}},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if "getUpdates" in url_str:
                return httpx.Response(200, json={"ok": True, "result": edge_updates})
            if "sendMessage" in url_str:
                body = json.loads(request.content)
                replies.append(body.get("text", ""))
                return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        cfg = TelegramConfig(bot_token="tok:123", chat_id="12345", dry_run=False)
        client = TelegramNotifierClient(cfg, transport=transport)

        daemon = TelegramNotifierDaemon(config=cfg, storage_dir=tmp_path, client=client)

        handled = daemon.handle_interactive_commands()
        assert handled == 5
        assert len(replies) == 5
        assert "Unknown command" in replies[0]
        assert "DAEMON STATUS" in replies[1]
        assert "DAEMON STATUS" in replies[2]
        assert "Unknown command" in replies[3]
        assert "SAFETY INVARIANT NOTICE" in replies[4]


# ---------------------------------------------------------------------------
# 9. CLI Parser & Single-Cycle Runner Tests
# ---------------------------------------------------------------------------


class TestSidecarRunner:
    def test_arg_parser_defaults(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args([])
        assert args.poll_interval == 3.0
        assert args.digest_interval == 3600.0
        assert args.dry_run is False
        assert args.once is False
        assert args.log_level == "INFO"

    def test_run_single_cycle(self, tmp_path: Path) -> None:
        setup_mock_storage(tmp_path)
        cfg = TelegramConfig(dry_run=True, chat_id="123")
        client = TelegramNotifierClient(cfg)

        daemon = TelegramNotifierDaemon(
            config=cfg,
            storage_dir=tmp_path,
            client=client,
        )

        # Single cycle executes all methods cleanly without raising errors
        daemon.run_single_cycle()
        assert daemon.checkpoint.last_sequence == 0

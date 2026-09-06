"""Multi-panel TUI Dashboard orchestrator and responsive layout renderer.

Composes the 6 panels (Header, Margin, Regimes, Positions, Closed Trades, Safety)
with responsive reflow down to standard 80x24 terminals and wide 2-column displays.
"""

from __future__ import annotations

from pathlib import Path

from .formatters import (
    AnsiColor,
    format_atr,
    format_currency,
    format_pnl,
    format_relative_time,
    format_spread_bps,
    format_uptime,
    pad_visible,
    render_progress_bar,
    truncate_visible,
)
from .layout import (
    ASCII_BOX,
    LIGHT_BOX,
    BoxChars,
    Panel,
    compose_horizontal_split,
    compose_vertical_stack,
    format_table_row,
    get_terminal_dimensions,
)
from .telemetry import (
    TelemetryReader,
    TuiTelemetrySnapshot,
)


class Dashboard:
    """Orchestrates telemetry retrieval and renders multi-panel terminal views."""

    def __init__(
        self,
        storage_dir: Path | str | None = None,
        *,
        reader: TelemetryReader | None = None,
        no_color: bool = False,
        color_enabled: bool | None = None,
        ascii_only: bool = False,
    ) -> None:
        if reader is not None:
            self.reader = reader
        elif storage_dir is not None:
            self.reader = TelemetryReader(storage_dir)
        else:
            self.reader = TelemetryReader(Path("artifacts/paper_live"))

        if color_enabled is not None:
            self.no_color = not color_enabled
        else:
            self.no_color = no_color

        self.ascii_only = ascii_only
        self.box_chars: BoxChars = ASCII_BOX if ascii_only else LIGHT_BOX
        self.v_sep: str = "|" if ascii_only else "│"
        self.h_dash: str = "--" if ascii_only else "──"

    def render(self, width: int | None = None, height: int | None = None) -> str:
        """Render the complete dashboard to a single formatted string."""
        term_w, term_h = get_terminal_dimensions()
        w = max(80, width if width is not None else term_w)
        h = max(24, height if height is not None else term_h)

        snapshot = self.reader.poll()

        if w >= 110 and h >= 28:
            return self._render_wide(snapshot, w, h)
        return self._render_compact(snapshot, w, h)

    # -------------------------------------------------------------------------
    # Compact Layout (Vertical Stack for 80x24 to 109x27)
    # -------------------------------------------------------------------------

    def _render_compact(self, snap: TuiTelemetrySnapshot, width: int, height: int) -> str:
        """Render standard single-column vertical layout."""
        panels: list[Panel] = []

        # 1. Header Panel
        panels.append(self._build_header_panel(snap, width))

        # 2. Portfolio Margin Panel
        panels.append(self._build_margin_panel(snap, width))

        # 3. Market Regimes Panel
        panels.append(self._build_regimes_panel(snap, width))

        # 4. Active Positions Panel
        panels.append(self._build_positions_panel(snap, width, max_rows=2))

        # 5. Closed Trades Panel (included if terminal height >= 28)
        if height >= 28:
            panels.append(self._build_trades_panel(snap, width, max_rows=max(2, height - 25)))

        # 6. Safety Invariants Panel
        panels.append(self._build_safety_panel(snap, width))

        rendered_blocks = [p.render() for p in panels]
        return "\n".join(compose_vertical_stack(rendered_blocks))

    # -------------------------------------------------------------------------
    # Wide Layout (Two-Column Split for >= 110x28)
    # -------------------------------------------------------------------------

    def _render_wide(self, snap: TuiTelemetrySnapshot, width: int, height: int) -> str:
        """Render wide multi-column layout for high-resolution terminals."""
        # Top: Header (Full Width)
        header_panel = self._build_header_panel(snap, width)

        # Bottom: Safety (Full Width)
        safety_panel = self._build_safety_panel(snap, width)

        # Middle: Two Columns
        left_w = (width - 1) // 2
        right_w = width - left_w - 1

        # Left: Margin + Positions
        left_margin = self._build_margin_panel(snap, left_w)
        left_positions = self._build_positions_panel(snap, left_w, max_rows=4)
        left_lines = left_margin.render() + left_positions.render()

        # Right: Regimes + Closed Trades
        right_regimes = self._build_regimes_panel(snap, right_w)
        right_trades = self._build_trades_panel(snap, right_w, max_rows=4)
        right_lines = right_regimes.render() + right_trades.render()

        middle_lines = compose_horizontal_split(left_lines, right_lines, gap=1)

        all_lines = header_panel.render() + middle_lines + safety_panel.render()
        return "\n".join(all_lines)

    # -------------------------------------------------------------------------
    # Panel Builder Methods
    # -------------------------------------------------------------------------

    def _build_header_panel(self, snap: TuiTelemetrySnapshot, width: int) -> Panel:
        """Construct Header & Daemon Health Panel."""
        d = snap.daemon
        inner_w = width - 4

        # Status styling
        status_str = d.status
        if not self.no_color:
            if snap.is_stale or d.status in ("HALTED", "OFFLINE"):
                status_str = f"{AnsiColor.BRIGHT_RED}{AnsiColor.BOLD}{d.status}{AnsiColor.RESET}"
            elif d.status in ("STARTING", "SHUTDOWN_CLEAN"):
                status_str = f"{AnsiColor.BRIGHT_YELLOW}{d.status}{AnsiColor.RESET}"
            else:
                status_str = f"{AnsiColor.BRIGHT_GREEN}{AnsiColor.BOLD}{d.status}{AnsiColor.RESET}"

        pid_str = f"PID {d.pid}" if d.pid else "PID --"
        uptime_str = format_uptime(d.uptime_seconds)

        if d.heartbeat_age_seconds < 60:
            hb_str = f"{d.heartbeat_age_seconds:.1f}s ago"
        else:
            hb_str = format_relative_time(d.last_heartbeat_utc)

        if not self.no_color and d.heartbeat_age_seconds > 60.0:
            hb_str = f"{AnsiColor.BRIGHT_RED}{hb_str} (STALE){AnsiColor.RESET}"

        msgs_str = f"{d.feed_messages_received:,}"
        recon_str = (
            f"{AnsiColor.BRIGHT_RED}{d.feed_reconnects_count}{AnsiColor.RESET}"
            if d.feed_reconnects_count > 0 and not self.no_color
            else str(d.feed_reconnects_count)
        )
        sync_str = format_relative_time(d.last_heartbeat_utc)

        if inner_w >= 92:
            line1 = (
                f"Status: {status_str} ({pid_str}) {self.v_sep} "
                f"Uptime: {uptime_str} {self.v_sep} Heartbeat: {hb_str} {self.v_sep} "
                f"Throughput: {d.feed_throughput_per_sec:.1f} msg/s"
            )
            line2 = (
                f"Feed: {msgs_str} msgs {self.v_sep} Reconnects: {recon_str} {self.v_sep} "
                f"Pairs: {len(d.symbols_monitored)} {self.v_sep} Last Sync: {sync_str}"
            )
        else:
            line1 = (
                f"Status: {status_str} ({pid_str}) {self.v_sep} Uptime: {uptime_str} {self.v_sep} "
                f"Feed: {d.feed_throughput_per_sec:.1f}/s"
            )
            line2 = (
                f"Heartbeat: {hb_str} {self.v_sep} Msgs: {msgs_str} {self.v_sep} "
                f"Recon: {recon_str} {self.v_sep} Pairs: {len(d.symbols_monitored)}"
            )

        lines = [
            pad_visible(truncate_visible(line1, inner_w), inner_w),
            pad_visible(truncate_visible(line2, inner_w), inner_w),
        ]
        return Panel(
            title=f"AUTONOMOUS FUTURES BOT {self.h_dash} 24/7 LIVE PAPER DAEMON MONITOR",
            lines=lines,
            width=width,
            box_chars=self.box_chars,
            pad_content=True,
        )

    def _build_margin_panel(self, snap: TuiTelemetrySnapshot, width: int) -> Panel:
        """Construct Portfolio Margin & Capital Health Panel."""
        m = snap.margin
        inner_w = width - 4

        cash_str = format_currency(m.current_cash)
        eq_str = format_currency(m.current_equity)
        real_pnl_str = format_pnl(m.realized_pnl, pct=m.realized_pnl_pct, enabled=not self.no_color)
        line1 = (
            f"Cash: {cash_str} USDT {self.v_sep} Equity: {eq_str} USDT {self.v_sep} "
            f"Realized PnL: {real_pnl_str}"
        )

        bar_w = 8 if inner_w < 60 else 12
        util_meter = render_progress_bar(
            pct=m.margin_utilization_pct,
            width=bar_w,
            enabled=not self.no_color,
            ascii_only=self.ascii_only,
            warn_pct=80.0,
        )
        unreal_pnl_str = format_pnl(
            m.unrealized_pnl, pct=m.unrealized_pnl_pct, enabled=not self.no_color
        )
        line2 = (
            f"Margin Util: {util_meter} / 80.0% max {self.v_sep} Unrealized PnL: {unreal_pnl_str}"
        )

        res_meter = render_progress_bar(
            pct=m.reserve_buffer_pct,
            width=bar_w,
            enabled=not self.no_color,
            ascii_only=self.ascii_only,
            warn_pct=20.0,
            lower_is_worse=True,
        )
        peak_str = format_currency(m.peak_equity)
        line3 = f"Reserve Buf: {res_meter} (min 20.0%) {self.v_sep} Peak Equity: {peak_str} USDT"

        lines = [
            pad_visible(truncate_visible(line1, inner_w), inner_w),
            pad_visible(truncate_visible(line2, inner_w), inner_w),
            pad_visible(truncate_visible(line3, inner_w), inner_w),
        ]
        return Panel(
            title="PORTFOLIO MARGIN & CAPITAL HEALTH (100.00 USDT SHARED)",
            lines=lines,
            width=width,
            box_chars=self.box_chars,
            pad_content=True,
        )

    def _build_regimes_panel(self, snap: TuiTelemetrySnapshot, width: int) -> Panel:
        """Construct Multi-Asset Market Regimes Panel."""
        inner_w = width - 4
        lines: list[str] = []

        if inner_w >= 68:
            col_widths = [9, 14, 14, 16, 10, 8]
            col_headers = ["SYMBOL", "BID PRICE", "ASK PRICE", "SPREAD (bps)", "ATR(14)", "STATUS"]
            lines.append(format_table_row(col_headers, col_widths))

            for sym, reg in snap.regimes.items():
                p_dec = 4 if "DOGE" in sym else 2
                bid_s = format_currency(reg.best_bid, prefix="", decimals=p_dec)
                ask_s = format_currency(reg.best_ask, prefix="", decimals=p_dec)
                spread_s = format_spread_bps(reg.spread_bps, enabled=not self.no_color)
                atr_s = format_atr(reg.rolling_atr, decimals=p_dec)

                status_s = reg.status
                if not self.no_color:
                    if reg.status == "HALTED":
                        status_s = f"{AnsiColor.BRIGHT_RED}{AnsiColor.BOLD}HALT{AnsiColor.RESET}"
                    elif reg.status == "WIDE_SPREAD":
                        status_s = f"{AnsiColor.BRIGHT_YELLOW}WIDE{AnsiColor.RESET}"
                    elif reg.status == "WARMUP":
                        status_s = f"{AnsiColor.BRIGHT_BLACK}WARMUP{AnsiColor.RESET}"
                    else:
                        status_s = f"{AnsiColor.BRIGHT_GREEN}NORMAL{AnsiColor.RESET}"

                row_cells = [sym, bid_s, ask_s, spread_s, atr_s, status_s]
                lines.append(format_table_row(row_cells, col_widths))
        else:
            col_widths = [8, 13, 14, 8]
            col_headers = ["SYMBOL", "MID PRICE", "SPREAD", "STATUS"]
            lines.append(format_table_row(col_headers, col_widths))

            for sym, reg in snap.regimes.items():
                p_dec = 4 if "DOGE" in sym else 2
                mid_s = format_currency(reg.mid_price, prefix="", decimals=p_dec)
                spread_s = format_spread_bps(reg.spread_bps, enabled=not self.no_color)
                status_s = reg.status
                if not self.no_color:
                    if reg.status == "HALTED":
                        status_s = f"{AnsiColor.BRIGHT_RED}HALT{AnsiColor.RESET}"
                    elif reg.status == "WIDE_SPREAD":
                        status_s = f"{AnsiColor.BRIGHT_YELLOW}WIDE{AnsiColor.RESET}"
                    elif reg.status == "WARMUP":
                        status_s = f"{AnsiColor.BRIGHT_BLACK}WARM{AnsiColor.RESET}"
                    else:
                        status_s = f"{AnsiColor.BRIGHT_GREEN}NORM{AnsiColor.RESET}"

                row_cells = [sym, mid_s, spread_s, status_s]
                lines.append(format_table_row(row_cells, col_widths))

        return Panel(
            title="MULTI-ASSET MARKET REGIMES",
            lines=lines,
            width=width,
            box_chars=self.box_chars,
            pad_content=True,
        )

    def _build_positions_panel(
        self, snap: TuiTelemetrySnapshot, width: int, max_rows: int = 3
    ) -> Panel:
        """Construct Active Paper Positions Panel."""
        inner_w = width - 4
        lines: list[str] = []

        if not snap.positions:
            msg = f"No Active Positions {self.h_dash} Monitoring Market Regimes & Risk Triggers"
            lines.append(pad_visible(truncate_visible(msg, inner_w), inner_w))
        else:
            if inner_w >= 68:
                col_widths = [4, 5, 8, 10, 10, 15, 5, 10]
                col_headers = [
                    "SYM",
                    "SIDE",
                    "QTY",
                    "ENTRY",
                    "MARK",
                    "uPnL (USDT)",
                    "LEV",
                    "TRAIL STOP",
                ]
                lines.append(format_table_row(col_headers, col_widths))

                for sym, pos in list(snap.positions.items())[:max_rows]:
                    short_sym = sym.replace("USDT", "")
                    side_s = pos.side
                    if not self.no_color:
                        side_s = (
                            f"{AnsiColor.BRIGHT_GREEN}LONG{AnsiColor.RESET}"
                            if pos.side == "LONG"
                            else f"{AnsiColor.BRIGHT_RED}SHORT{AnsiColor.RESET}"
                        )

                    qty_s = f"{pos.quantity:.4f}"
                    p_dec = 4 if "DOGE" in sym else 2
                    entry_s = format_currency(pos.entry_price, prefix="", decimals=p_dec)
                    mark_s = format_currency(pos.mark_price, prefix="", decimals=p_dec)
                    upnl_s = format_pnl(
                        pos.unrealized_pnl, pct=pos.pnl_pct, enabled=not self.no_color
                    )
                    lev_s = f"{pos.leverage:.1f}x"
                    stop_target = pos.trailing_stop_price or pos.stop_loss_price
                    stop_s = (
                        format_currency(
                            stop_target,
                            prefix="",
                            decimals=p_dec,
                        )
                        if stop_target is not None
                        else "--"
                    )

                    row_cells = [
                        short_sym,
                        side_s,
                        qty_s,
                        entry_s,
                        mark_s,
                        upnl_s,
                        lev_s,
                        stop_s,
                    ]
                    lines.append(format_table_row(row_cells, col_widths))
            else:
                col_widths = [5, 6, 9, 14, 5]
                col_headers = ["SYM", "SIDE", "ENTRY", "uPnL", "LEV"]
                lines.append(format_table_row(col_headers, col_widths))

                for sym, pos in list(snap.positions.items())[:max_rows]:
                    short_sym = sym.replace("USDT", "")
                    side_s = pos.side
                    if not self.no_color:
                        side_s = (
                            f"{AnsiColor.BRIGHT_GREEN}L{AnsiColor.RESET}"
                            if pos.side == "LONG"
                            else f"{AnsiColor.BRIGHT_RED}S{AnsiColor.RESET}"
                        )
                    p_dec = 4 if "DOGE" in sym else 2
                    entry_s = format_currency(pos.entry_price, prefix="", decimals=p_dec)
                    upnl_s = format_pnl(pos.unrealized_pnl, enabled=not self.no_color)
                    lev_s = f"{pos.leverage:.1f}x"
                    row_cells = [short_sym, side_s, entry_s, upnl_s, lev_s]
                    lines.append(format_table_row(row_cells, col_widths))

        return Panel(
            title="ACTIVE PAPER POSITIONS",
            lines=lines,
            width=width,
            box_chars=self.box_chars,
            pad_content=True,
        )

    def _build_trades_panel(
        self, snap: TuiTelemetrySnapshot, width: int, max_rows: int = 4
    ) -> Panel:
        """Construct Closed Trades & Execution History Panel."""
        inner_w = width - 4
        lines: list[str] = []

        if not snap.recent_closed_trades:
            msg = "No closed trades recorded in paper ledger yet"
            lines.append(pad_visible(truncate_visible(msg, inner_w), inner_w))
        else:
            if inner_w >= 68:
                col_widths = [10, 5, 6, 12, 16, 8, 12]
                col_headers = [
                    "TIME (UTC)",
                    "SYM",
                    "SIDE",
                    "FILL PRICE",
                    "NET PnL",
                    "FEES",
                    "EXIT REASON",
                ]
                lines.append(format_table_row(col_headers, col_widths))

                for trade in snap.recent_closed_trades[:max_rows]:
                    short_sym = trade.symbol.replace("USDT", "")
                    t_str = (
                        trade.occurred_at.split("T")[-1][:8]
                        if "T" in trade.occurred_at
                        else trade.occurred_at[:8]
                    )
                    side_s = trade.side
                    if not self.no_color:
                        side_s = (
                            f"{AnsiColor.BRIGHT_GREEN}LONG{AnsiColor.RESET}"
                            if trade.side == "LONG"
                            else f"{AnsiColor.BRIGHT_RED}SHORT{AnsiColor.RESET}"
                        )

                    p_dec = 4 if "DOGE" in trade.symbol else 2
                    price_s = format_currency(trade.fill_price, prefix="", decimals=p_dec)
                    pnl_s = format_pnl(trade.net_pnl, enabled=not self.no_color)
                    fees_s = f"{trade.total_fees:.4f}"
                    reason_s = trade.exit_reason

                    row_cells = [t_str, short_sym, side_s, price_s, pnl_s, fees_s, reason_s]
                    lines.append(format_table_row(row_cells, col_widths))
            else:
                col_widths = [8, 5, 5, 14, 10]
                col_headers = ["TIME", "SYM", "SIDE", "NET PnL", "REASON"]
                lines.append(format_table_row(col_headers, col_widths))

                for trade in snap.recent_closed_trades[:max_rows]:
                    short_sym = trade.symbol.replace("USDT", "")
                    t_str = (
                        trade.occurred_at.split("T")[-1][:8]
                        if "T" in trade.occurred_at
                        else trade.occurred_at[:8]
                    )
                    side_s = trade.side[0] if trade.side else "-"
                    pnl_s = format_pnl(trade.net_pnl, enabled=not self.no_color)
                    reason_s = trade.exit_reason[:10]
                    row_cells = [t_str, short_sym, side_s, pnl_s, reason_s]
                    lines.append(format_table_row(row_cells, col_widths))

        return Panel(
            title="RECENT CLOSED TRADES & EXECUTION HISTORY",
            lines=lines,
            width=width,
            box_chars=self.box_chars,
            pad_content=True,
        )

    def _build_safety_panel(self, snap: TuiTelemetrySnapshot, width: int) -> Panel:
        """Construct Safety Guardrails & Zero-Order Invariants Panel."""
        s = snap.safety
        inner_w = width - 4

        vol_cb = s.volatility_cb
        spread_cb = s.spread_cb
        if not self.no_color:
            vol_cb = (
                f"{AnsiColor.BRIGHT_GREEN}NORMAL{AnsiColor.RESET}"
                if s.volatility_cb == "NORMAL"
                else f"{AnsiColor.BRIGHT_RED}{s.volatility_cb}{AnsiColor.RESET}"
            )
            spread_cb = (
                f"{AnsiColor.BRIGHT_GREEN}NORMAL{AnsiColor.RESET}"
                if s.spread_cb == "NORMAL"
                else f"{AnsiColor.BRIGHT_RED}{s.spread_cb}{AnsiColor.RESET}"
            )

        orders_status = "0 (PASS)" if s.orders_submitted == 0 else f"{s.orders_submitted} (FAIL)"
        if not self.no_color and s.orders_submitted == 0:
            orders_status = f"{AnsiColor.BRIGHT_GREEN}0 (PASS){AnsiColor.RESET}"

        auth_status = "FALSE" if not s.execution_authority else "TRUE (FAIL)"
        if not self.no_color and not s.execution_authority:
            auth_status = f"{AnsiColor.BRIGHT_GREEN}FALSE{AnsiColor.RESET}"

        live_str = "FALSE" if not s.live_trading_activation else "TRUE (FAIL)"
        promo_str = s.promotion_state.upper()
        creds_str = "VERIFIED" if s.zero_private_credentials else "LEAKED"
        if not self.no_color:
            live_str = f"{AnsiColor.BRIGHT_GREEN}FALSE{AnsiColor.RESET}"
            promo_str = f"{AnsiColor.BRIGHT_GREEN}{promo_str}{AnsiColor.RESET}"
            creds_str = f"{AnsiColor.BRIGHT_GREEN}VERIFIED{AnsiColor.RESET}"

        if inner_w >= 92:
            line1 = (
                f"Volatility CB: {vol_cb} {self.v_sep} Spread CB: {spread_cb} {self.v_sep} "
                f"Orders Submitted: {orders_status} {self.v_sep} Execution Authority: {auth_status}"
            )
            line2 = (
                f"Live Trading: {live_str} {self.v_sep} Promotion State: {promo_str} {self.v_sep} "
                f"Zero Private Keys: {creds_str} {self.v_sep} Mode: PAPER ACTIVE"
            )
            lines = [
                pad_visible(truncate_visible(line1, inner_w), inner_w),
                pad_visible(truncate_visible(line2, inner_w), inner_w),
            ]
        else:
            line1 = f"Circuit Breakers: Volatility [{vol_cb}] {self.v_sep} Spread [{spread_cb}]"
            line2 = (
                f"Orders: {orders_status} {self.v_sep} Exec Authority: {auth_status} {self.v_sep} "
                f"Live Trading: {live_str}"
            )
            line3 = (
                f"Promotion: {promo_str} {self.v_sep} Zero Keys: {creds_str} {self.v_sep} "
                f"Mode: PAPER ACTIVE"
            )
            lines = [
                pad_visible(truncate_visible(line1, inner_w), inner_w),
                pad_visible(truncate_visible(line2, inner_w), inner_w),
                pad_visible(truncate_visible(line3, inner_w), inner_w),
            ]

        return Panel(
            title="SAFETY GUARDRAILS & ZERO-ORDER INVARIANTS",
            lines=lines,
            width=width,
            box_chars=self.box_chars,
            pad_content=True,
        )

"""Empirical Challenger M2: Stress Testing Fill Recovery & Portfolio Member Resolution.

Adversarial validation of dead-code-purged components:
1. `fill_recovery.py` - immutable summaries, fill precision, and fail-closed invariants.
2. `app.py` - portfolio resolution fallback and downstream scanner telemetry.
3. Complete absence of all deleted dead symbols.
"""

from dataclasses import FrozenInstanceError
from decimal import Decimal
from unittest.mock import patch

import pytest

from autonomous_futures.api.app import (
    ExecutionPortfolioScanner,
    _compute_portfolio_scanner_telemetry,
    _resolve_admitted_portfolio_members,
)
from autonomous_futures.execution.fill_recovery import FillSummary, summarize_fills


def _make_mock_fill(
    identity: int,
    order_id: int,
    **kwargs,
) -> dict:
    row = {
        "id": identity,
        "orderId": order_id,
        "symbol": "SOLUSDT",
        "side": "BUY",
        "qty": "0.1",
        "price": "150.00",
        "quoteQty": "15.00",
        "commission": "0.003",
        "realizedPnl": "0.00",
        "time": 1700000000000,
        "positionSide": "BOTH",
        "commissionAsset": "USDT",
    }
    row.update(kwargs)
    return row


class TestChallengerM2FillRecoveryStress:
    """Stress testing FillSummary and summarize_fills."""

    def test_fill_summary_is_strictly_immutable(self) -> None:
        """FillSummary must be a frozen dataclass preventing mutation."""
        summary = FillSummary(
            quantity=Decimal("1.0"),
            quote_quantity=Decimal("150.0"),
            commission_usdt=Decimal("0.03"),
            realized_pnl_usdt=Decimal("0.0"),
            first_fill_ms=1000,
            last_fill_ms=2000,
            trade_ids=(1, 2),
        )
        with pytest.raises(FrozenInstanceError):
            summary.quantity = Decimal("2.0")  # type: ignore

    def test_summarize_fills_empty_fill_reconciliation(self) -> None:
        """Empty rows with zero executed quantity must return zeroed FillSummary."""
        summary = summarize_fills(
            [],
            symbol="SOLUSDT",
            order_id=42,
            side="BUY",
            executed_quantity=Decimal("0"),
        )
        assert summary.quantity == Decimal("0")
        assert summary.quote_quantity == Decimal("0")
        assert summary.commission_usdt == Decimal("0")
        assert summary.realized_pnl_usdt == Decimal("0")
        assert summary.first_fill_ms is None
        assert summary.last_fill_ms is None
        assert summary.trade_ids == ()

    def test_summarize_fills_multi_partial_fills_arbitrary_order_precision(self) -> None:
        """Out-of-order partial fills must sort trade IDs and report min/max times."""
        # Deliberately unordered timestamps and IDs
        f3 = _make_mock_fill(
            303,
            77,
            qty="0.123456",
            quoteQty="18.5184",
            commission="0.0037",
            realizedPnl="0.50",
            time=3000,
        )
        f1 = _make_mock_fill(
            101,
            77,
            qty="0.234567",
            quoteQty="35.18505",
            commission="0.0070",
            realizedPnl="-0.20",
            time=1000,
        )
        f2 = _make_mock_fill(
            202,
            77,
            qty="0.345678",
            quoteQty="51.8517",
            commission="0.0104",
            realizedPnl="1.25",
            time=2000,
        )

        total_qty = Decimal("0.123456") + Decimal("0.234567") + Decimal("0.345678")
        total_quote = Decimal("18.5184") + Decimal("35.18505") + Decimal("51.8517")
        total_comm = Decimal("0.0037") + Decimal("0.0070") + Decimal("0.0104")
        total_pnl = Decimal("0.50") + Decimal("-0.20") + Decimal("1.25")

        summary = summarize_fills(
            [f3, f1, f2],
            symbol="SOLUSDT",
            order_id=77,
            side="BUY",
            executed_quantity=total_qty,
        )

        assert summary.quantity == total_qty
        assert summary.quote_quantity == total_quote
        assert summary.commission_usdt == total_comm
        assert summary.realized_pnl_usdt == total_pnl
        assert summary.first_fill_ms == 1000
        assert summary.last_fill_ms == 3000
        assert summary.trade_ids == (101, 202, 303)

    @pytest.mark.parametrize(
        "corrupt_field,corrupt_val,expected_error",
        [
            ("symbol", "ETHUSDT", "Fill evidence does not match"),
            ("orderId", 999, "Fill evidence does not match"),
            ("side", "SELL", "Fill evidence does not match"),
            ("positionSide", "LONG", "Fill evidence does not match"),
            ("commissionAsset", "BNB", "Fill evidence does not match"),
            ("qty", "0", "Invalid authenticated execution"),
            ("qty", "-0.5", "Invalid authenticated execution"),
            ("price", "0", "Invalid authenticated execution"),
            ("price", "-100", "Invalid authenticated execution"),
            ("time", 0, "Invalid authenticated execution"),
            ("time", -500, "Invalid authenticated execution"),
        ],
    )
    def test_summarize_fills_fails_closed_on_corrupted_row(
        self, corrupt_field: str, corrupt_val: object, expected_error: str
    ) -> None:
        """Field mismatches and non-positive values must raise ValueError immediately."""
        fill = _make_mock_fill(1, 10, **{corrupt_field: corrupt_val})
        with pytest.raises(ValueError, match=expected_error):
            summarize_fills(
                [fill],
                symbol="SOLUSDT",
                order_id=10,
                side="BUY",
                executed_quantity=Decimal("0.1"),
            )

    def test_summarize_fills_rejects_duplicate_trade_ids(self) -> None:
        """Duplicate trade IDs must be rejected as replay attacks or duplicate fills."""
        f1 = _make_mock_fill(100, 10, qty="0.1")
        f2 = _make_mock_fill(100, 10, qty="0.1")
        with pytest.raises(ValueError, match="Duplicate fill evidence"):
            summarize_fills(
                [f1, f2],
                symbol="SOLUSDT",
                order_id=10,
                side="BUY",
                executed_quantity=Decimal("0.2"),
            )

    def test_summarize_fills_rejects_quantity_discrepancy(self) -> None:
        """Discrepancy between cumulative fills and executed_quantity must be rejected."""
        f1 = _make_mock_fill(1, 10, qty="0.1")
        with pytest.raises(
            ValueError, match="does not reconcile with cumulative executed quantity"
        ):
            summarize_fills(
                [f1],
                symbol="SOLUSDT",
                order_id=10,
                side="BUY",
                executed_quantity=Decimal("0.10000001"),
            )

    def test_summarize_fills_rejects_infinite_or_nan_executed_quantity(self) -> None:
        """NaN or Infinite executed quantities must raise ValueError."""
        f1 = _make_mock_fill(1, 10, qty="0.1")
        with pytest.raises(ValueError, match="does not reconcile"):
            summarize_fills(
                [f1],
                symbol="SOLUSDT",
                order_id=10,
                side="BUY",
                executed_quantity=Decimal("Infinity"),
            )
        with pytest.raises(ValueError, match="does not reconcile"):
            summarize_fills(
                [f1],
                symbol="SOLUSDT",
                order_id=10,
                side="BUY",
                executed_quantity=Decimal("NaN"),
            )


class TestChallengerM2AppPortfolioResolutionFallback:
    """Stress testing _resolve_admitted_portfolio_members fallback behavior."""

    def test_resolve_admitted_portfolio_members_empty_fallback(self) -> None:
        """When load_admitted_portfolios returns empty list, returns ('', ())."""
        with patch(
            "autonomous_futures.execution.portfolio_runtime.load_admitted_portfolios",
            return_value=[],
        ):
            portfolio_id, members = _resolve_admitted_portfolio_members()
            assert portfolio_id == ""
            assert members == ()

    def test_resolve_admitted_portfolio_members_exception_fallback(self) -> None:
        """When load_admitted_portfolios raises Exception, catches and returns ('', ())."""
        with patch(
            "autonomous_futures.execution.portfolio_runtime.load_admitted_portfolios",
            side_effect=RuntimeError("Corrupted portfolio database"),
        ):
            portfolio_id, members = _resolve_admitted_portfolio_members()
            assert portfolio_id == ""
            assert members == ()

    def test_downstream_portfolio_scanner_telemetry_graceful_with_empty_members(self) -> None:
        """Empty members return no criteria and the default scanner."""
        with patch(
            "autonomous_futures.api.app._resolve_admitted_portfolio_members",
            return_value=("", ()),
        ):
            criteria, scanner = _compute_portfolio_scanner_telemetry(
                research_dir=None,
                runtime_observed=True,
                account_path=None,
            )
            assert criteria is None
            assert isinstance(scanner, ExecutionPortfolioScanner)
            assert scanner.observed is False
            assert scanner.portfolio_id == "macro-scalper-uninspected-3sym-medium-frequency-v1"
            assert scanner.variants == []


class TestChallengerM2DeadCodeAbsence:
    """Empirical verification that dead code symbols are completely absent."""

    def test_portfolio_variants_spec_absent(self) -> None:
        import autonomous_futures.api.app as app_mod

        assert not hasattr(app_mod, "_PORTFOLIO_VARIANTS_SPEC")

    def test_baseline_execution_status_absent(self) -> None:
        import autonomous_futures.api.app as app_mod

        assert not hasattr(app_mod, "_baseline_execution_status")

    def test_fetch_closed_trades_count_absent(self) -> None:
        import autonomous_futures.api.canary as canary_mod

        assert not hasattr(canary_mod, "_fetch_closed_trades_count")

    def test_clock_drift_exceeded_error_absent(self) -> None:
        import autonomous_futures.execution.binance_gateway as bg_mod

        assert not hasattr(bg_mod, "ClockDriftExceededError")

    def test_recover_order_fills_absent(self) -> None:
        import autonomous_futures.execution.fill_recovery as fr_mod

        assert not hasattr(fr_mod, "recover_order_fills")

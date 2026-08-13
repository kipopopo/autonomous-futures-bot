from datetime import UTC, datetime, timedelta
from decimal import Decimal

from autonomous_futures.domain.contracts import PaperExecutionRequest
from autonomous_futures.paper.safety import PaperActionApproval, PaperSafetyEvidence
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger


def _request(**changes: object) -> PaperExecutionRequest:
    payload: dict[str, object] = {
        "candidate_id": "cand-scope-rsi-adx-001",
        "candidate_artifact_hash": "a" * 64,
        "qualified_symbols": ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        "symbol": "BTCUSDT",
        "side": "LONG",
        "mark_price": Decimal("100"),
        "quantity": Decimal("0.1"),
        "fee_rate": Decimal("0.0004"),
        "slippage_bps": Decimal("2"),
    }
    payload.update(changes)
    return PaperExecutionRequest.model_validate(payload)


def _evidence() -> PaperSafetyEvidence:
    return PaperSafetyEvidence(
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        qualification_hash="b" * 64,
        qualification_decision="qualified",
        zero_oos_liquidations=True,
    )


def _approval(
    *, action: str, trade_id: str, approval_id: str, approved_at: datetime | None = None
) -> PaperActionApproval:
    approved_at = approved_at or datetime(2026, 8, 13, tzinfo=UTC)
    return PaperActionApproval(
        approval_id=approval_id,
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        trade_id=trade_id,
        action=action,
        approved_at=approved_at,
        expires_at=approved_at + timedelta(minutes=1),
    )


def test_paper_runtime_opens_one_approved_local_position(tmp_path) -> None:
    from autonomous_futures.paper.runtime import PaperRuntime

    runtime = PaperRuntime(SqlitePaperLedger(tmp_path / "paper-ledger.sqlite3"))
    result = runtime.open(
        _request(),
        _evidence(),
        _approval(action="open", trade_id="paper-001", approval_id="approval-open-001"),
        trade_id="paper-001",
        occurred_at=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert result.status == "opened"
    assert result.paper_activation is False
    assert result.execution_authority is False
    assert result.exchange_access is False
    entry = runtime.ledger.load().open_positions()[0]
    assert entry.fill_price == Decimal("100.0200")
    assert entry.entry_fee == Decimal("0.004000800")
    assert entry.slippage_cost == Decimal("0.00200")
    assert entry.approval_id == "approval-open-001"


def test_paper_runtime_blocks_replayed_or_expired_approval_without_new_write(tmp_path) -> None:
    from autonomous_futures.paper.runtime import PaperRuntime

    runtime = PaperRuntime(SqlitePaperLedger(tmp_path / "paper-ledger.sqlite3"))
    approval = _approval(action="open", trade_id="paper-001", approval_id="approval-open-001")
    first = runtime.open(
        _request(),
        _evidence(),
        approval,
        trade_id="paper-001",
        occurred_at=approval.approved_at,
    )
    second = runtime.open(
        _request(),
        _evidence(),
        approval,
        trade_id="paper-002",
        occurred_at=approval.expires_at,
    )

    assert first.status == "opened"
    assert second.status == "blocked"
    assert runtime.ledger.load().entries == (runtime.ledger.load().entries[0],)


def test_paper_runtime_closes_one_approved_local_position(tmp_path) -> None:
    from autonomous_futures.paper.runtime import PaperRuntime

    runtime = PaperRuntime(SqlitePaperLedger(tmp_path / "paper-ledger.sqlite3"))
    opened_at = datetime(2026, 8, 13, tzinfo=UTC)
    runtime.open(
        _request(),
        _evidence(),
        _approval(action="open", trade_id="paper-001", approval_id="approval-open-001"),
        trade_id="paper-001",
        occurred_at=opened_at,
    )
    closed_at = opened_at + timedelta(minutes=2)
    result = runtime.close(
        _request(),
        _evidence(),
        _approval(
            action="close",
            trade_id="paper-001",
            approval_id="approval-close-001",
            approved_at=closed_at,
        ),
        trade_id="paper-001",
        exit_mark_price=Decimal("110"),
        occurred_at=closed_at,
    )

    assert result.status == "closed"
    assert result.paper_activation is False
    assert result.execution_authority is False
    assert result.exchange_access is False
    closed = runtime.ledger.load().entries[-1]
    assert closed.fill_price == Decimal("109.9780")
    assert closed.exit_fee == Decimal("0.004399120")
    assert closed.gross_pnl == Decimal("0.995800")
    assert closed.net_pnl == Decimal("0.987400080")
    assert closed.approval_id == "approval-close-001"


def test_paper_runtime_blocks_approved_close_without_durable_open_without_write(tmp_path) -> None:
    from autonomous_futures.paper.runtime import PaperRuntime

    path = tmp_path / "paper-ledger.sqlite3"
    runtime = PaperRuntime(SqlitePaperLedger(path))
    occurred_at = datetime(2026, 8, 13, tzinfo=UTC)
    result = runtime.close(
        _request(),
        _evidence(),
        _approval(
            action="close",
            trade_id="paper-001",
            approval_id="approval-close-001",
            approved_at=occurred_at,
        ),
        trade_id="paper-001",
        exit_mark_price=Decimal("110"),
        occurred_at=occurred_at,
    )

    assert result.status == "blocked"
    assert result.reason_codes == ("durable_open_position_missing",)
    assert not path.exists()

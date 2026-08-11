from decimal import Decimal

import pytest
from pydantic import ValidationError

from autonomous_futures.domain.contracts import PaperExecutionRequest


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


def test_paper_execution_request_is_default_blocked_and_non_authoritative() -> None:
    request = _request()

    assert request.activation_state == "blocked"
    assert request.paper_activation is False
    assert request.execution_authority is False
    assert request.exchange_access is False


def test_paper_execution_request_rejects_symbol_outside_qualified_universe() -> None:
    with pytest.raises(ValidationError, match="qualified universe"):
        _request(symbol="XRPUSDT")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mark_price", Decimal("0")),
        ("quantity", Decimal("0")),
        ("fee_rate", Decimal("-0.0001")),
        ("slippage_bps", Decimal("-1")),
    ],
)
def test_paper_execution_request_rejects_invalid_explicit_cost_inputs(
    field: str, value: Decimal
) -> None:
    with pytest.raises(ValidationError):
        _request(**{field: value})


def test_paper_execution_request_rejects_any_activation_or_execution_authority() -> None:
    with pytest.raises(ValidationError):
        _request(paper_activation=True)
    with pytest.raises(ValidationError):
        _request(execution_authority=True)
    with pytest.raises(ValidationError):
        _request(exchange_access=True)

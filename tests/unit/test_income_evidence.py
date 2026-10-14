import pytest

from autonomous_futures.execution.account_evidence import unique_income


def income():
    return {
        "incomeType": "COMMISSION",
        "tranId": 1,
        "asset": "USDT",
        "time": 1000,
        "income": "-0.001",
    }


def test_exact_duplicate_income_is_counted_once():
    original = income()
    assert unique_income([original, dict(original)]) == [original]


@pytest.mark.parametrize("field,value", [("income", "-.002"), ("time", 1001), ("asset", "BNB")])
def test_conflicting_transaction_identity_fails_closed(field, value):
    original = income()
    with pytest.raises(ValueError, match="Conflicting authenticated"):
        unique_income([original, {**original, field: value}])

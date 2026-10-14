import pytest

from autonomous_futures.execution.account_evidence import exchange_bool


@pytest.mark.parametrize(
    "raw,expected", [(True, True), (False, False), ("true", True), ("false", False)]
)
def test_exchange_booleans_are_parsed_without_python_string_truthiness(raw, expected):
    assert exchange_bool(raw) is expected


@pytest.mark.parametrize("raw", [None, 0, 1, "", "FALSE", "unknown"])
def test_unknown_exchange_flags_cannot_default_to_false(raw):
    with pytest.raises(ValueError, match="authenticated exchange boolean"):
        exchange_bool(raw)

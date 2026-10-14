import pytest

from autonomous_futures.feed.closed_history import parse_closed_history


def rows():
    return [[i * 60000, "100", "102", "99", "101", "4", (i + 1) * 60000 - 1] for i in range(1, 252)]


def test_forming_candle_is_excluded_before_strategy_evaluation():
    bars = parse_closed_history(rows(), "1m", 251 * 60000 + 12000)
    assert len(bars) == 250
    assert bars[-1].timestamp_ms == 250 * 60000


@pytest.mark.parametrize("mutation", ["gap", "duplicate", "stale", "geometry", "close"])
def test_invalid_history_cannot_generate_runtime_signals(mutation):
    body = rows()
    if mutation == "gap":
        body.pop(40)
    elif mutation == "duplicate":
        body.insert(40, list(body[40]))
    elif mutation == "stale":
        body.pop(-2)
    elif mutation == "geometry":
        body[40][2] = "98"
    elif mutation == "close":
        body[40][6] += 1
    with pytest.raises(ValueError):
        parse_closed_history(body, "1m", 251 * 60000 + 12000)

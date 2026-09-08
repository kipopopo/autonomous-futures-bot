"""Adversarial stress test for _validate_temperature."""

import argparse
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from scripts.run_autonomous_cycle import _validate_temperature

valid_cases = ["0.0", "0", "1", "1.0", "2.0", "2", "0.00001", "1.99999", "0.7", "1.5"]
for v in valid_cases:
    res = _validate_temperature(v)
    assert 0.0 <= res <= 2.0, f"Expected valid in [0, 2], got {res} for {v}"
    assert math.isfinite(res), f"Expected finite float for {v}"

invalid_cases = [
    "abc", "", " ", "None", "True", "False", "1.2.3", "0x10", "nan", "NaN", "NAN",
    "inf", "-inf", "Infinity", "-Infinity", "-0.0001", "-1.0", "-100", "2.0001",
    "2.1", "10.0", "1e9", "-1e9", "foo_bar", '"1.0"', "NoneType", "null", "\n", "\t",
    "1,5", "--model", "0.0.0", "NaN%", "1e-300", "-0.0"
]
for inv in invalid_cases:
    if inv == "-0.0":
        # -0.0 converts to -0.0 which in Python satisfies 0.0 <= -0.0 <= 2.0
        continue
    if inv == "1e-300":
        # 1e-300 is a positive float <= 2.0
        continue
    try:
        _validate_temperature(inv)
        raise AssertionError(f"Expected ArgumentTypeError for {inv!r}, but it succeeded!")
    except argparse.ArgumentTypeError:
        pass
    except Exception as e:
        raise AssertionError(f"Expected ArgumentTypeError for {inv!r}, but got {type(e).__name__}: {e}")

print("ALL ADVERSARIAL TEMPERATURE TEST CASES PASSED!")

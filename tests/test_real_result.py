"""
tests/test_real_result.py — hermetic checks on real 1X2 resolution.
Run: python -m pytest tests/test_real_result.py -q

The live end-to-end (fetch proven goals + validate on devnet) is
`python -m settle.real_result`; here we pin the pure logic and the key mapping so a
refactor can't flip home/away or mis-resolve a draw.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from settle import real_result as R


def test_key_mapping_and_period_are_the_documented_ones():
    # verified empirically: France 2-0 Morocco → key1=2, key2=0; final outcome at period 100
    assert R.HOME_GOALS_KEY == 1 and R.AWAY_GOALS_KEY == 2
    assert R.FINAL_PERIOD == 100


def test_outcome_from_goals():
    assert R.outcome_from_goals(2, 0) == "1"     # home win
    assert R.outcome_from_goals(1, 2) == "2"     # away win
    assert R.outcome_from_goals(0, 0) == "X"     # goalless draw
    assert R.outcome_from_goals(1, 1) == "X"     # scoring draw
    assert R.outcome_from_goals(3, 2) == "1"


def test_outcome_is_symmetric_inverse():
    # swapping home/away must flip 1<->2 and leave X unchanged
    for h in range(4):
        for a in range(4):
            o, oi = R.outcome_from_goals(h, a), R.outcome_from_goals(a, h)
            assert {o, oi} in ({"1", "2"}, {"X"})


def test_played_fixture_ids_present():
    assert len(R.PLAYED) == len(set(R.PLAYED)) >= 8


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))

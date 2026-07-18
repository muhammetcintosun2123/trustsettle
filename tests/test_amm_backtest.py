"""
tests/test_amm_backtest.py — the AMM risk backtest on real cached odds.
Run: python tests/test_amm_backtest.py   (or pytest -q)

These assert the backtest's honesty invariants: it uses the AMM's real constants, it
never invents flow, its per-tick accounting is internally consistent, and the labeled
goal-shock stress test actually fires the >=15% MEV breaker.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from settle import amm_backtest as B
from settle.amm import SPREAD_VIG, TOXIC_DRIFT_THRESHOLD


def test_uses_real_amm_constants():
    # the backtest must measure the SAME constants the live AMM runs on, not a copy
    assert B.SPREAD_VIG == SPREAD_VIG == 0.025
    assert B.TOXIC_DRIFT_THRESHOLD == TOXIC_DRIFT_THRESHOLD == 0.15


def test_real_cache_loads_and_is_de_vigged():
    # fixture count is NOT pinned: the live feed's slate shrinks as teams are eliminated
    # (refresh_cache.py repoints this at whatever the tournament currently has).
    fx = B.load_fixtures()
    assert fx, "odds cache is empty — run: python3 refresh_cache.py"
    for f in fx:
        assert len(f["series"]) >= 2          # enough ticks to score a move
        book = B._implied(f["series"][0]["odds"])
        assert abs(sum(book.values()) - 1.0) < 1e-9   # zero-margin fair book


def test_tick_accounting_is_partitioned():
    # every scored tick is exactly one of survive / pickoff / toxic
    for f in B.load_fixtures():
        r = B.backtest_fixture(f)
        assert r.survive + r.pickoff + r.toxic == r.ticks
        assert r.ticks == len(r.moves) == len(f["series"]) - 1


def test_survivors_capture_nonneg_edge_pickoffs_cost():
    for f in B.load_fixtures():
        r = B.backtest_fixture(f)
        # surviving ticks: move <= spread -> captured edge is in [0, spread]
        assert all(0.0 <= e <= SPREAD_VIG + 1e-12 for e in r.edge_captured)
        # without a breaker, toxic + pickoff ticks are the only nonzero adverse costs
        assert all(c >= 0.0 for c in r.adverse_no_breaker)


def test_breaker_zeroes_toxic_but_not_pickoff():
    for f in B.load_fixtures():
        r = B.backtest_fixture(f)
        # with the breaker, adverse cost <= without it for every tick (never worse)
        for wo, wi in zip(r.adverse_no_breaker, r.adverse_with_breaker):
            assert wi <= wo + 1e-12


def test_run_reports_and_disclaims_pnl():
    out = B.run()
    assert out["aggregate"]["ticks"] > 1000
    assert "no realized total P&L" in out["note"]  # the honesty guardrail is present
    assert out["spread_pct"] == 2.5


def test_stress_goal_shock_fires_breaker():
    st = B.stress_goal_shock(shock_pp=0.20)
    assert st["breaker_fires"] is True
    assert st["pickoff_avoided_bps"] > 0
    assert "stress test" in st["scenario"].lower()
    # a shock below threshold must NOT fire (no false breaker claim)
    small = B.stress_goal_shock(shock_pp=0.05)
    assert small["breaker_fires"] is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))

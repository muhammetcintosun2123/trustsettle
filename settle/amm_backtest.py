"""
settle/amm_backtest.py — risk backtest of the TrustSettle AMM on REAL World Cup odds.

The AMM (`settle/amm.py`) quotes with a 2.5% spread and pulls quotes on a >=15% toxic
drift (the MEV circuit breaker). Iterations 1-2 labeled that spread "theoretical" and
the AMM quoting loop "simulated". This module upgrades that from *asserted* to
*measured* — on the real, cached, de-vigged TxLINE odds path (France v Morocco, Norway v
England, Spain v Belgium, Argentina v Switzerland; hundreds of real ticks each).

WHAT WE HONESTLY CAN AND CANNOT MEASURE
---------------------------------------
TxLINE publishes a single de-vigged *consensus* — there is no taker order flow, no bet
volume, no per-book lines. So we do NOT (and must not) claim a realized P&L number: that
would require fabricating who lifted which quote and for how much. What the real price
path DOES fully determine is the *per-unit-filled* economics of market making, which is
exactly the risk a desk sizes against:

  A two-sided maker profits when its half-spread survives the adverse fair-value move
  over the quote's lifetime (Glosten-Milgrom / inventory adverse-selection logic).
  Per unit filled, the quote outcome at tick t is:  spread - |Δfair_t|
    * |Δfair_t| <= spread  -> quote survives, edge captured  (+, up to the spread)
    * |Δfair_t|  > spread  -> picked off, adverse-selection loss  (= |Δfair| - spread)

We measure two things off the real path:
  1. SPREAD ADEQUACY — is 2.5% actually calibrated to real World Cup tick volatility?
     (quote-survival rate, median/p95 |Δfair|, mean edge captured per surviving unit)
  2. MEV BREAKER VALUE — the >=15% pull removes the fat tail; we measure the mean
     adverse-selection cost per unit WITH vs WITHOUT the breaker (the loss it avoids).

Everything is a deterministic function of real odds + the AMM's real constants
(SPREAD_VIG, TOXIC_DRIFT_THRESHOLD imported from amm.py). No flow is invented.

  python -m settle.amm_backtest
  python -m settle.amm_backtest --json
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from statistics import median
from typing import Dict, List

from .amm import SPREAD_VIG, TOXIC_DRIFT_THRESHOLD

_HERE = os.path.dirname(os.path.abspath(__file__))
_ODDS_CACHE = os.path.join(_HERE, "..", "odds_cache.json")


def _implied(odds: Dict[str, float]) -> Dict[str, float]:
    """De-vig raw decimal odds into a zero-margin fair-probability book (same math the
    AMM uses in AutoMarketMaker._implied)."""
    raw = {k: 1.0 / v for k, v in odds.items() if v and v > 1}
    s = sum(raw.values())
    return {k: v / s for k, v in raw.items()} if s else {}


def load_fixtures(path: str = _ODDS_CACHE) -> List[dict]:
    with open(path) as f:
        return json.load(f)["fixtures"]


@dataclass
class FixtureResult:
    name: str
    ticks: int = 0                 # consecutive tick transitions scored
    survive: int = 0               # |Δfair| <= spread  (quote not picked off)
    pickoff: int = 0               # spread < |Δfair| < toxic (small adverse selection)
    toxic: int = 0                 # |Δfair| >= toxic  (breaker fires; no fill)
    moves: List[float] = field(default_factory=list)      # |Δfair| per tick
    edge_captured: List[float] = field(default_factory=list)   # per surviving unit
    adverse_no_breaker: List[float] = field(default_factory=list)  # loss/unit if quotes stayed up
    adverse_with_breaker: List[float] = field(default_factory=list)

    def report(self) -> dict:
        n = self.ticks
        return {
            "fixture": self.name,
            "ticks": n,
            "spread_pct": round(SPREAD_VIG * 100, 2),
            "median_move_pct": round(median(self.moves) * 100, 3) if self.moves else 0.0,
            "p95_move_pct": round(_p95(self.moves) * 100, 3) if self.moves else 0.0,
            "quote_survival_pct": round(self.survive / n * 100, 1) if n else 0.0,
            "toxic_events": self.toxic,
            "mean_edge_captured_bps": round(_mean(self.edge_captured) * 1e4, 1),
            "adverse_cost_bps_no_breaker": round(_mean(self.adverse_no_breaker) * 1e4, 1),
            "adverse_cost_bps_with_breaker": round(_mean(self.adverse_with_breaker) * 1e4, 1),
        }


def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _p95(xs: List[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(0.95 * len(s)))]


def backtest_fixture(fixture: dict) -> FixtureResult:
    """Walk one fixture's real de-vigged odds path and score each tick's quote outcome.

    At tick t the AMM has a standing two-sided quote priced off the *last observed* fair
    (fair_{t-1}); the fair then moves to fair_t. Per unit filled, the maker nets
    `spread - |Δfair_t|` on the side the move went against. The MEV breaker pulls quotes
    when |Δfair_t| >= TOXIC_DRIFT_THRESHOLD, so those ticks contribute no fill (loss 0)
    with the breaker, vs the raw `|Δfair| - spread` loss without it.
    """
    res = FixtureResult(name=fixture.get("home", "?") + " v " + fixture.get("away", "?"))
    series = fixture["series"]
    prev = None
    for pt in series:
        cur = _implied(pt["odds"])
        if prev is not None:
            # adverse move = the worst 1X2 leg move over the quote's life (two-sided book)
            dp = max(abs(cur.get(k, 0.0) - prev.get(k, 0.0)) for k in ("1", "X", "2"))
            res.ticks += 1
            res.moves.append(dp)
            if dp >= TOXIC_DRIFT_THRESHOLD:
                res.toxic += 1
                # without a breaker a stale quote is picked off for the full excess move
                res.adverse_no_breaker.append(dp - SPREAD_VIG)
                res.adverse_with_breaker.append(0.0)  # breaker pulled the quote -> no fill
            elif dp > SPREAD_VIG:
                res.pickoff += 1
                res.adverse_no_breaker.append(dp - SPREAD_VIG)
                res.adverse_with_breaker.append(dp - SPREAD_VIG)  # breaker doesn't fire here
            else:
                res.survive += 1
                res.edge_captured.append(SPREAD_VIG - dp)  # spread survived the move
                res.adverse_no_breaker.append(0.0)
                res.adverse_with_breaker.append(0.0)
        prev = cur
    return res


def run(path: str = _ODDS_CACHE) -> dict:
    fixtures = load_fixtures(path)
    per = [backtest_fixture(f) for f in fixtures]
    # aggregate
    agg = FixtureResult(name="ALL FIXTURES (aggregate)")
    for r in per:
        agg.ticks += r.ticks
        agg.survive += r.survive
        agg.pickoff += r.pickoff
        agg.toxic += r.toxic
        agg.moves += r.moves
        agg.edge_captured += r.edge_captured
        agg.adverse_no_breaker += r.adverse_no_breaker
        agg.adverse_with_breaker += r.adverse_with_breaker
    breaker_saving = _mean(agg.adverse_no_breaker) - _mean(agg.adverse_with_breaker)
    return {
        "source": "REAL cached TxLINE World Cup odds (de-vigged consensus)",
        "spread_pct": round(SPREAD_VIG * 100, 2),
        "toxic_threshold_pct": round(TOXIC_DRIFT_THRESHOLD * 100, 2),
        "per_fixture": [r.report() for r in per],
        "aggregate": agg.report(),
        "mev_breaker_saving_bps": round(breaker_saving * 1e4, 1),
        "note": ("Per-unit-filled economics only — TxLINE gives a single de-vigged "
                 "consensus with no taker volume, so no realized total P&L is claimed."),
    }


def stress_goal_shock(shock_pp: float = 0.20, path: str = _ODDS_CACHE) -> dict:
    """LABELED STRESS TEST (not a feed measurement): inject a goal-magnitude shock into a
    real pre-match odds level and show the MEV breaker fire.

    The cached feed is all pre-match, so it contains no in-play goals — yet a scored goal
    is a real, documented effect: it jumps the de-vigged win probability by ~15-40pp in a
    single update. We take a real fixture's last pre-match fair book and apply a +shock_pp
    jump to the leading side. Without the breaker a stale quote is picked off for
    (shock - spread); the >=15% breaker fires first and pulls the quote (loss 0). This
    quantifies the tail the breaker removes; the shock size is a modeled scenario, clearly
    labeled, NOT read from the feed."""
    fx = load_fixtures(path)[0]
    base = _implied(fx["series"][-1]["odds"])
    lead = max(("1", "X", "2"), key=lambda k: base.get(k, 0.0))
    shocked = dict(base)
    shocked[lead] = min(0.99, base[lead] + shock_pp)
    dp = abs(shocked[lead] - base[lead])
    fires = dp >= TOXIC_DRIFT_THRESHOLD
    return {
        "scenario": f"LABELED stress test — +{shock_pp*100:.0f}pp goal shock on {lead} "
                    f"({fx.get('home')} v {fx.get('away')})",
        "shock_pp": round(shock_pp * 100, 1),
        "breaker_threshold_pp": round(TOXIC_DRIFT_THRESHOLD * 100, 1),
        "breaker_fires": fires,
        "pickoff_avoided_bps": round(max(0.0, dp - SPREAD_VIG) * 1e4, 1) if fires else 0.0,
        "note": "Shock magnitude is a modeled in-play scenario, not a feed reading.",
    }


def _fmt(r: dict) -> str:
    return (f"  {r['fixture']:<34} ticks={r['ticks']:>4}  "
            f"survival={r['quote_survival_pct']:>5.1f}%  "
            f"med|Δ|={r['median_move_pct']:>5.3f}%  p95={r['p95_move_pct']:>6.3f}%  "
            f"toxic={r['toxic_events']:>2}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--cache", default=_ODDS_CACHE, help="odds cache path")
    a = ap.parse_args()
    out = run(a.cache)
    if a.json:
        print(json.dumps(out, indent=2))
        return
    print("=" * 78)
    print(" TrustSettle AMM — RISK BACKTEST on REAL World Cup odds")
    print("=" * 78)
    print(f" Spread (vig): {out['spread_pct']}%   MEV breaker at |Δfair| >= "
          f"{out['toxic_threshold_pct']}%")
    print(f" Data: {out['source']}\n")
    print(" Per fixture (quote survival = ticks the 2.5% spread was NOT picked off):")
    for r in out["per_fixture"]:
        print(_fmt(r))
    agg = out["aggregate"]
    print("\n " + "-" * 76)
    print(_fmt(agg))
    print("\n SPREAD ADEQUACY:")
    print(f"   • The 2.5% spread survives the real tick move {agg['quote_survival_pct']}% "
          f"of the time (median tick move {agg['median_move_pct']}%, p95 "
          f"{agg['p95_move_pct']}%).")
    print(f"   • Mean edge captured per surviving unit: "
          f"{agg['mean_edge_captured_bps']} bps.")
    print("\n MEV CIRCUIT-BREAKER VALUE:")
    if agg["toxic_events"]:
        print(f"   • {agg['toxic_events']} toxic drift(s) on the real path would each pick "
              f"off a stale quote.")
        print(f"   • Mean adverse-selection cost/unit  WITHOUT breaker: "
              f"{agg['adverse_cost_bps_no_breaker']} bps  →  WITH breaker: "
              f"{agg['adverse_cost_bps_with_breaker']} bps "
              f"(avoids {out['mev_breaker_saving_bps']} bps).")
    else:
        print("   • The cached feed is all PRE-MATCH, which moves slowly — so it contains "
              "0 toxic drifts and the breaker never needs to fire here (honest: the spread "
              "alone handles pre-match noise).")
        st = stress_goal_shock()
        print(f"   • Stress test — {st['scenario']}:")
        print(f"       shock {st['shock_pp']}pp >= {st['breaker_threshold_pp']}pp threshold "
              f"→ breaker fires: {st['breaker_fires']}; a stale quote would have been "
              f"picked off for {st['pickoff_avoided_bps']} bps, avoided by pulling quotes.")
        print(f"       ({st['note']})")
    print("\n " + out["note"])
    print("=" * 78)


if __name__ == "__main__":
    main()

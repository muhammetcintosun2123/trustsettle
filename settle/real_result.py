"""
settle/real_result.py — resolve a fixture's REAL 1X2 result, cryptographically PROVEN.

The gap this closes: our demos previously refused to resolve outcomes (`real_outcome`
returned None) because parsing goal events off the raw feed was unreliable. It turns out
the clean, PROVABLE source was there all along:

  * TxODDS emits a `game_finalised` scores record at **period 100** (final outcome).
  * At that record's `Seq`, stat **key 1 = participant-1 (home) goals** and **key 2 =
    participant-2 (away) goals** — verified empirically (France 2-0 Morocco → key1=2,key2=0).
  * Those two stats are Merkle-anchored, so we don't just READ them — we PROVE them: fetch
    each via `/api/scores/stat-validation` and validate on-chain with `validate_stat`
    (single-stat V1 is reliable on every record, incl. a 0-0 whose V3 multiproof is empty).

So a settled 1X2 result here is not "we parsed the feed" — it is "TxODDS's own program
confirmed the home and away goal counts against its anchored root, on devnet." That is the
same standard a real desk (and the strongest rival) settles on.

  python -m settle.real_result                 # resolve the known played World Cup fixtures
  python -m settle.real_result --fixture 18209181
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "bounties" / "worldcup" / "sharpedge"))
from txline import live_mainnet as L, live_feed as F
from settle import real_validate as V1

# Real played World Cup fixtures on the devnet feed (start time within the 2-week window).
PLAYED = [18209181, 18213979, 18218149, 18222446, 18179550, 18202783, 18237038, 17952170]

HOME_GOALS_KEY, AWAY_GOALS_KEY = 1, 2
FINAL_PERIOD = 100


def outcome_from_goals(home: int, away: int) -> str:
    """1X2 from a final scoreline. Home win = "1", draw = "X", away win = "2"."""
    return "1" if home > away else ("2" if away > home else "X")


def finalized_seq(fid: int):
    """Seq of the fixture's `game_finalised` scores record, or None if not yet finalised."""
    try:
        recs = F.scores_snapshot(fid)
    except Exception:
        return None
    fin = [r for r in recs if r.get("Action") == "game_finalised"]
    return fin[-1].get("Seq") if fin else None


def resolve(fid: int, prove_on_chain: bool = True) -> dict:
    """Resolve a fixture's real 1X2 outcome from PROVEN home/away goal stats.

    Returns {fixture, finalised, home, away, outcome, seq, proven_onchain}. `outcome` is
    "1"/"X"/"2" or None if the match isn't finalised on the feed yet."""
    seq = finalized_seq(fid)
    if seq is None:
        return {"fixture": fid, "finalised": False, "outcome": None,
                "reason": "no game_finalised record yet (fixture not played / not in window)"}

    # Prove each goal count on its own with V1 single-stat `validate_stat`. V1 is used here
    # (not V3's multiproof) because it is reliable on every record — a 0-0 finalised record
    # returns an empty V3 multiproof, but V1 proves each stat individually every time.
    def proven_goal(key):
        v = F.get(f"/api/scores/stat-validation?fixtureId={fid}&seq={seq}&statKey={key}")
        st = v.get("statToProve")
        if not st:
            return None, None
        ok = None
        if prove_on_chain:
            try:
                err, _, _ = V1.simulate(v)
                ok = err is None
            except Exception:
                ok = None
        return st.get("value"), ok

    home, home_ok = proven_goal(HOME_GOALS_KEY)
    away, away_ok = proven_goal(AWAY_GOALS_KEY)
    if home is None or away is None:
        return {"fixture": fid, "finalised": True, "outcome": None,
                "reason": "goal stats missing at finalised seq"}

    outcome = outcome_from_goals(home, away)
    proven = (home_ok and away_ok) if prove_on_chain else None

    return {"fixture": fid, "finalised": True, "seq": seq,
            "home": home, "away": away, "outcome": outcome,
            "period": FINAL_PERIOD, "proven_onchain": proven}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", type=int, help="one fixture; default = all known played")
    ap.add_argument("--no-chain", action="store_true", help="skip the on-chain proof step")
    a = ap.parse_args()
    L.set_network("devnet")

    print("=" * 74)
    print(" Real 1X2 results — resolved from PROVEN goal stats (key1=home, key2=away,")
    print(" period 100), each goal count validated on-chain via validate_stat.")
    print("=" * 74)
    fixtures = [a.fixture] if a.fixture else PLAYED
    proven_n = 0
    for fid in fixtures:
        r = resolve(fid, prove_on_chain=not a.no_chain)
        if not r["finalised"]:
            print(f"  {fid}: not finalised — {r.get('reason')}")
            continue
        badge = {"1": "HOME win", "X": "DRAW", "2": "AWAY win"}[r["outcome"]]
        mark = ("✅ proven on-chain" if r["proven_onchain"]
                else ("— (chain skipped)" if a.no_chain else "⚠ proof unavailable"))
        proven_n += 1 if r["proven_onchain"] else 0
        print(f"  {fid}: {r['home']}-{r['away']}  → {r['outcome']} ({badge})   {mark}")
    if not a.no_chain:
        print("\n " + "-" * 72)
        print(f"  {proven_n}/{len(fixtures)} results validated against TxODDS's anchored root on devnet.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
settle/live.py — open a prediction market on a REAL TxLINE World Cup fixture.

Pulls real fixtures off the live feed and instantiates a TrustSettle market against a
real fixture_id, ready to settle the moment TxODDS anchors that fixture's scores root on
Solana. Ties the (self-contained, trustless) settlement engine to real World Cup matches.

Prereq: a live api token — `python -m txline.live_mainnet --network devnet --subscribe`.

  python -m settle.live
"""
from __future__ import annotations

import argparse

from .market import Market, MarketIntent, TraderPredicate, Comparison, BinaryExpression

try:
    from txline import live_mainnet as L, live_feed as F
except Exception:
    L = F = None

STAT_GOALS_HOME = 101
STAT_GOALS_AWAY = 102


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--network", choices=["mainnet", "devnet"], default="devnet")
    a = ap.parse_args()
    if F is None:
        print("live feed module unavailable"); return 1
    try:
        L.set_network(a.network)
        fixtures = F.fixtures(72)
    except Exception as e:
        print(f"live feed unavailable ({e}). Run: python -m txline.live_mainnet "
              f"--network {a.network} --subscribe")
        return 1

    print("=" * 64)
    print(" TrustSettle — a market on a REAL TxLINE World Cup fixture")
    print("=" * 64)
    f = fixtures[0]
    fid, name = f["FixtureId"], f"{f['Participant1']} v {f['Participant2']}"
    print(f"\nReal fixture #{fid}: {name}  (start {f['StartTime']})")

    # "Over 2.5 total goals" on the real fixture: home + away goals > 2
    intent = MarketIntent(
        fixture_id=fid, period=0,
        stat_a_key=STAT_GOALS_HOME, stat_b_key=STAT_GOALS_AWAY, op=BinaryExpression.ADD,
        predicate=TraderPredicate(threshold=2, comparison=Comparison.GREATER_THAN),
    )
    # scores_root will be TxODDS's anchored root for this fixture once the match ends;
    # until then the market escrows and waits (settlement needs the proven stats + proof).
    market = Market(intent=intent, maker="Alice", maker_stake=100,
                    scores_root=b"\x00" * 32)
    market.take("Bob", 100)
    print(f"\n  Market: '{f['Participant1']} + {f['Participant2']} total goals > 2'")
    print(f"  Alice (over) vs Bob (under), 100 each — 200 escrowed, trustless.")
    print(f"  Fixture id {fid} is a REAL World Cup fixture from the live feed.")
    print(f"\n  ⏳ Settles automatically once TxODDS anchors fixture {fid}'s scores root:")
    print(f"     submit the proven goal stats + Merkle proofs → engine verifies → pays the winner.")
    print(f"     (No oracle, no admin — the same trustless flow shown in `settle.demo`.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

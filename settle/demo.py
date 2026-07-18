"""
settle/demo.py — end-to-end trustless settlement on a Merkle-proven outcome.

Story: two traders disagree on whether Argentina vs Brazil will have 3+ total goals.
They escrow. The match ends 2-1 (3 goals). TxODDS anchors the scores batch root on
Solana. Anyone can now settle: submit the proven goal stats + their Merkle proofs; the
engine verifies them against the anchored root and pays the winner — trustlessly.

We also show the security property that matters: a FORGED stat cannot settle, because
its Merkle proof will not fold to the anchored root.

  python -m settle.demo
"""
from __future__ import annotations

from .merkle import MerkleTree
from .market import (Market, Pool, MarketIntent, TraderPredicate, Comparison,
                     BinaryExpression, ScoreStat, SettlementError)

STAT_GOALS = 101   # arbitrary demo key for "goals" (mirrors a TxLINE ScoreStat.key)


def show_live_order_book() -> None:
    """Read the REAL prediction-market order book off the deployed devnet program."""
    print("\n⓪ LIVE on-chain order book (deployed txoracle program, devnet):")
    try:
        from .onchain import fetch_order_book
        book = fetch_order_book()
        if not book:
            print("   (no orders returned — network/RPC unavailable, skipping)")
            return
        fixtures = sorted({i.fixture_id for i in book})
        makers = sorted({i.maker for i in book})
        print(f"   {len(book)} real OrderIntent accounts · {len(makers)} makers · "
              f"{len(fixtures)} fixtures — decoded live from chain")
        for i in book[:5]:
            print(f"     #{i.intent_id}  maker {i.maker[:8]}…  fixture {i.fixture_id}  "
                  f"stake {i.deposit_amount/1e6:.2f}  {i.state_name}")
        print("   ↑ these are real trades on-chain; TrustSettle can settle any of them")
        print("     the instant TxODDS anchors that fixture's scores root.")
    except Exception as e:
        print(f"   (skipped: {e})")


def build_scores_batch():
    """Model a TxODDS scores batch: several proven stats under one anchored root.
    Argentina (home) scored 2, Brazil (away) scored 1 → 3 total goals."""
    home_goals = ScoreStat(key=STAT_GOALS, value=2, period=0)   # full match
    away_goals = ScoreStat(key=STAT_GOALS + 1, value=1, period=0)
    # other batch events (padding the tree, as a real batch would have many leaves)
    others = [ScoreStat(key=200 + i, value=i, period=0) for i in range(6)]
    leaves = [home_goals.leaf(), away_goals.leaf()] + [s.leaf() for s in others]
    tree = MerkleTree(leaves)
    return tree, home_goals, away_goals


def main() -> int:
    print("=" * 64)
    print(" TrustSettle — trustless prediction-market settlement (TxLINE)")
    print("=" * 64)

    show_live_order_book()

    tree, home_goals, away_goals = build_scores_batch()
    root = tree.root
    print(f"\n① TxODDS anchors the scores batch root on Solana:\n   root = {root.hex()[:32]}…")

    # Maker: "total goals > 2" (i.e. 3+). Uses stat_a + stat_b combined with Add.
    intent = MarketIntent(
        fixture_id=2001, period=0,
        stat_a_key=home_goals.key, stat_b_key=away_goals.key,
        op=BinaryExpression.ADD,
        predicate=TraderPredicate(threshold=2, comparison=Comparison.GREATER_THAN),
        negation=False,
    )
    m = Market(intent=intent, maker="Alice", maker_stake=100, scores_root=root)
    print("\n② Alice posts an intent: 'Argentina+Brazil total goals > 2' and escrows 100.")
    m.take("Bob", 100)
    print("③ Bob takes the other side, escrows 100. Escrow now holds 200, trustless.")

    # honest settlement with real proofs
    proof_home = tree.proof(0)
    proof_away = tree.proof(1)
    print("\n④ Match ends 2-1. Anyone submits the proven goal stats + Merkle proofs…")
    winner = m.settle(home_goals, proof_home, away_goals, proof_away)
    for line in m.log():
        print("   ·", line)
    print(f"\n   ✅ WINNER: {winner} takes {m.payout}. "
          f"(2+1 = 3 goals > 2 ⇒ maker's predicate holds.)")

    # forgery attempt: claim only 1 goal to flip the result, with a bogus proof
    print("\n⑤ Security check — Bob tries to settle a FORGED stat (fake 0 goals):")
    forged = ScoreStat(key=home_goals.key, value=0, period=0)
    m2 = Market(intent=intent, maker="Alice", maker_stake=100, scores_root=root)
    m2.take("Bob", 100)
    try:
        m2.settle(forged, proof_home, away_goals, proof_away)
        print("   ✗ forged stat settled — THIS SHOULD NOT HAPPEN")
        return 1
    except SettlementError as e:
        print(f"   🛡️  rejected: {e}")
        print("   The forged value's leaf doesn't fold to the anchored root. No trust required.")

    # ⑥ parimutuel pool — the many-sided "wagering pool" the track asks for
    print("\n⑥ Parimutuel pool (many bettors, no house) on the same predicate:")
    pool = Pool(intent=intent, scores_root=root)
    pool.stake_yes("Alice", 100)
    pool.stake_yes("Carol", 50)
    pool.stake_no("Bob", 120)
    pool.stake_no("Dave", 30)
    print(f"   YES pool 150 · NO pool 150 · crowd-implied YES = "
          f"{pool.implied_yes_prob()*100:.0f}%")
    payouts = pool.settle(home_goals, proof_home, away_goals, proof_away)
    for line in pool.log()[-1:]:
        print("   ·", line)
    for who, amt in sorted(payouts.items()):
        print(f"   → {who} collects {amt:.1f}  (staked YES, split the losing NO pool pro-rata)")

    # ⑦ AMM edge — measured on REAL odds, not asserted
    print("\n⑦ AMM edge, measured on REAL World Cup odds (not asserted):")
    try:
        from . import amm_backtest as B
        r = B.run()["aggregate"]
        st = B.stress_goal_shock()
        print(f"   Over {r['ticks']} real de-vigged ticks, the 2.5% spread survives "
              f"{r['quote_survival_pct']}% of market moves")
        print(f"   (median tick move {r['median_move_pct']}%, p95 {r['p95_move_pct']}%) "
              f"→ ~{r['mean_edge_captured_bps']:.0f} bps captured per unit of benign flow.")
        print(f"   MEV breaker (stress test): a {st['shock_pp']:.0f}pp goal shock fires the "
              f"pull, avoiding a {st['pickoff_avoided_bps']:.0f} bps stale-quote pick-off.")
        print("   (Per-unit-filled economics only — no taker volume in a de-vigged "
              "consensus, so no total P&L is claimed.)")
    except Exception as e:
        print(f"   (skipped: {e})")

    # ⑧ settle on a REAL played fixture's PROVEN result (needs the live feed + devnet)
    print("\n⑧ Real result, cryptographically proven (a played World Cup fixture):")
    try:
        from . import real_result as RR
        RR.L.set_network("devnet")
        r = RR.resolve(18209181)      # France v Morocco
        if r.get("finalised") and r.get("outcome"):
            badge = {"1": "HOME win", "X": "DRAW", "2": "AWAY win"}[r["outcome"]]
            print(f"   fixture 18209181 finalised {r['home']}-{r['away']} → {r['outcome']} ({badge})")
            print(f"   home & away goal counts (period 100) proven on devnet: "
                  f"{'✅ validate_stat confirms both' if r['proven_onchain'] else '⚠ chain unavailable'}")
            print("   → a market on this fixture settles on THIS, with no oracle vote. "
                  "(python -m settle.real_result)")
        else:
            print(f"   (fixture not finalised on the feed: {r.get('reason')})")
    except Exception as e:
        print(f"   (skipped — needs live feed + devnet: {e})")

    print("\n" + "=" * 64)
    print(" Settlement is driven only by Merkle-proven, on-chain-anchored data.")
    print(" No oracle, no admin key, no way to settle on a lie.")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

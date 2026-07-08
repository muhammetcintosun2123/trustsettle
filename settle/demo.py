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
from .market import (Market, MarketIntent, TraderPredicate, Comparison,
                     BinaryExpression, ScoreStat, SettlementError)

STAT_GOALS = 101   # arbitrary demo key for "goals" (mirrors a TxLINE ScoreStat.key)


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

    print("\n" + "=" * 64)
    print(" Settlement is driven only by Merkle-proven, on-chain-anchored data.")
    print(" No oracle, no admin key, no way to settle on a lie.")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

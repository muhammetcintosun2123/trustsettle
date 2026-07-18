"""
tests/test_settle_adversarial.py — the settlement gates, exercised adversarially.
Run: python -m pytest tests/test_settle_adversarial.py -q

Happy-path settlement is covered in test_settle.py. This file is the attacker's view:
every way a caller might try to steal a payout or corrupt state must be rejected. A
settlement engine is only as strong as its worst gate.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from settle.merkle import MerkleTree
from settle.market import (Market, Pool, MarketIntent, TraderPredicate, Comparison,
                           BinaryExpression, ScoreStat, SettlementError)


def _market(threshold=2, comparison=Comparison.GREATER_THAN, home=2, away=1):
    """A market on 'home+away goals <cmp> threshold', with the real tree it settles against."""
    hs, as_ = ScoreStat(100, home, 0), ScoreStat(101, away, 0)
    others = [ScoreStat(200 + i, i, 0) for i in range(6)]
    tree = MerkleTree([hs.leaf(), as_.leaf()] + [o.leaf() for o in others])
    intent = MarketIntent(2001, 0, 100, TraderPredicate(threshold, comparison),
                          stat_b_key=101, op=BinaryExpression.ADD)
    m = Market(intent=intent, maker="Alice", maker_stake=100, scores_root=tree.root)
    return m, tree, hs, as_


# ── gate: double-settle ────────────────────────────────────────────────────
def test_cannot_settle_twice():
    m, tree, hs, as_ = _market()
    m.take("Bob", 100)
    m.settle(hs, tree.proof(0), as_, tree.proof(1))
    with pytest.raises(SettlementError, match="already settled"):
        m.settle(hs, tree.proof(0), as_, tree.proof(1))


# ── gate: proof from a DIFFERENT tree (mismatched root) ─────────────────────
def test_proof_against_wrong_root_rejected():
    m, _, hs, as_ = _market()
    other = MerkleTree([ScoreStat(100, 2, 0).leaf(), ScoreStat(101, 1, 0).leaf(),
                        ScoreStat(999, 9, 0).leaf()])   # a different anchored tree
    m.take("Bob", 100)
    with pytest.raises(SettlementError, match="does not verify"):
        m.settle(hs, other.proof(0), as_, other.proof(1))


# ── gate: a leaf's proof used for the WRONG leaf ────────────────────────────
def test_swapped_leaf_proofs_rejected():
    m, tree, hs, as_ = _market()
    m.take("Bob", 100)
    # feed stat_a with stat_b's proof path — must not fold to the root
    with pytest.raises(SettlementError, match="does not verify"):
        m.settle(hs, tree.proof(1), as_, tree.proof(0))


# ── gate: stake matching on take ────────────────────────────────────────────
def test_take_requires_matching_stake():
    m, *_ = _market()
    with pytest.raises(SettlementError, match="must match"):
        m.take("Bob", 99)


def test_cannot_take_twice():
    m, *_ = _market()
    m.take("Bob", 100)
    with pytest.raises(SettlementError, match="already matched"):
        m.take("Carol", 100)


def test_cannot_settle_before_take():
    m, tree, hs, as_ = _market()
    with pytest.raises(SettlementError, match="no taker"):
        m.settle(hs, tree.proof(0), as_, tree.proof(1))


# ── predicate boundaries: the classic off-by-one surface ────────────────────
@pytest.mark.parametrize("cmp,thr,home,away,maker_wins", [
    (Comparison.GREATER_THAN, 3, 2, 1, False),   # 3 > 3 is FALSE (boundary)
    (Comparison.GREATER_THAN, 2, 2, 1, True),    # 3 > 2 TRUE
    (Comparison.LESS_THAN,    3, 1, 1, True),     # 2 < 3 TRUE
    (Comparison.LESS_THAN,    2, 1, 1, False),    # 2 < 2 FALSE (boundary)
    (Comparison.EQUAL_TO,     3, 2, 1, True),     # 3 == 3 TRUE
    (Comparison.EQUAL_TO,     3, 2, 0, False),    # 2 == 3 FALSE
])
def test_predicate_boundaries(cmp, thr, home, away, maker_wins):
    m, tree, hs, as_ = _market(threshold=thr, comparison=cmp, home=home, away=away)
    m.take("Bob", 100)
    winner = m.settle(hs, tree.proof(0), as_, tree.proof(1))
    assert winner == ("Alice" if maker_wins else "Bob")


# ── parimutuel pool: hostile inputs ─────────────────────────────────────────
def _pool(threshold=2, home=2, away=1):
    hs, as_ = ScoreStat(100, home, 0), ScoreStat(101, away, 0)
    others = [ScoreStat(200 + i, i, 0) for i in range(6)]
    tree = MerkleTree([hs.leaf(), as_.leaf()] + [o.leaf() for o in others])
    intent = MarketIntent(2001, 0, 100, TraderPredicate(threshold, Comparison.GREATER_THAN),
                          stat_b_key=101, op=BinaryExpression.ADD)
    return Pool(intent=intent, scores_root=tree.root), tree, hs, as_


def test_pool_rejects_nonpositive_stake():
    pool, *_ = _pool()
    with pytest.raises(SettlementError, match="positive"):
        pool.stake_yes("Mallory", 0)
    with pytest.raises(SettlementError, match="positive"):
        pool.stake_no("Mallory", -50)


def test_pool_cannot_settle_twice():
    pool, tree, hs, as_ = _pool()
    pool.stake_yes("A", 100)
    pool.stake_no("B", 100)
    pool.settle(hs, tree.proof(0), as_, tree.proof(1))
    with pytest.raises(SettlementError, match="already settled"):
        pool.settle(hs, tree.proof(0), as_, tree.proof(1))


def test_pool_one_sided_winners_keep_own_stake():
    # everyone on the winning side, nobody to lose to → each gets their own stake back
    pool, tree, hs, as_ = _pool(threshold=2, home=2, away=1)   # 3 > 2 TRUE → YES wins
    pool.stake_yes("A", 100)
    pool.stake_yes("B", 50)
    payouts = pool.settle(hs, tree.proof(0), as_, tree.proof(1))
    assert payouts.get("A") == 100 and payouts.get("B") == 50


def test_pool_forged_stat_cannot_settle():
    pool, tree, hs, as_ = _pool()
    pool.stake_yes("A", 100)
    pool.stake_no("B", 100)
    forged = ScoreStat(100, 9, 0)                # not the anchored value
    with pytest.raises(SettlementError, match="does not verify"):
        pool.settle(forged, tree.proof(0), as_, tree.proof(1))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

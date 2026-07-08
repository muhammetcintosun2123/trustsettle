"""
tests/test_settle.py — the trust primitive and the settlement logic.
Run: python tests/test_settle.py   (or pytest -q)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from settle.merkle import MerkleTree, ProofNode, verify, keccak256
from settle.market import (Market, Pool, MarketIntent, TraderPredicate, Comparison,
                           BinaryExpression, ScoreStat, SettlementError)
from settle import txoracle
from solders.pubkey import Pubkey


def _tree():
    stats = [ScoreStat(100 + i, i, 0) for i in range(7)]
    return MerkleTree([s.leaf() for s in stats]), stats


def test_merkle_roundtrip_all_indices():
    tree, stats = _tree()
    for i, s in enumerate(stats):
        assert verify(s.leaf(), tree.proof(i), tree.root)


def test_merkle_rejects_wrong_leaf():
    tree, stats = _tree()
    bad = ScoreStat(999, 999, 0)
    assert not verify(bad.leaf(), tree.proof(0), tree.root)


def test_merkle_rejects_tampered_proof():
    tree, stats = _tree()
    proof = tree.proof(2)
    tampered = [ProofNode(keccak256(b"evil"), p.is_right_sibling) for p in proof[:1]] + proof[1:]
    assert not verify(stats[2].leaf(), tampered, tree.root)


def test_predicate_semantics():
    gt = TraderPredicate(2, Comparison.GREATER_THAN)
    assert gt.holds(3) and not gt.holds(2)
    lt = TraderPredicate(2, Comparison.LESS_THAN)
    assert lt.holds(1) and not lt.holds(2)
    eq = TraderPredicate(2, Comparison.EQUAL_TO)
    assert eq.holds(2) and not eq.holds(3)


def test_combined_stat_add():
    intent = MarketIntent(2001, 0, 100, TraderPredicate(2, Comparison.GREATER_THAN),
                          stat_b_key=101, op=BinaryExpression.ADD)
    a, b = ScoreStat(100, 2, 0), ScoreStat(101, 1, 0)
    assert intent.evaluate(a, b) is True          # 2+1=3 > 2


def test_settlement_pays_winner_with_valid_proof():
    home, away = ScoreStat(100, 2, 0), ScoreStat(101, 1, 0)
    tree = MerkleTree([home.leaf(), away.leaf(), ScoreStat(102, 0, 0).leaf()])
    intent = MarketIntent(2001, 0, 100, TraderPredicate(2, Comparison.GREATER_THAN),
                          stat_b_key=101, op=BinaryExpression.ADD)
    m = Market(intent, "Alice", 100, tree.root)
    m.take("Bob", 100)
    winner = m.settle(home, tree.proof(0), away, tree.proof(1))
    assert winner == "Alice" and m.payout == 200 and m.settled


def test_settlement_rejects_forged_stat():
    home, away = ScoreStat(100, 2, 0), ScoreStat(101, 1, 0)
    tree = MerkleTree([home.leaf(), away.leaf(), ScoreStat(102, 0, 0).leaf()])
    intent = MarketIntent(2001, 0, 100, TraderPredicate(2, Comparison.GREATER_THAN),
                          stat_b_key=101, op=BinaryExpression.ADD)
    m = Market(intent, "Alice", 100, tree.root)
    m.take("Bob", 100)
    forged = ScoreStat(100, 0, 0)                 # claim 0 goals to flip the result
    try:
        m.settle(forged, tree.proof(0), away, tree.proof(1))
        assert False, "forged stat must not settle"
    except SettlementError:
        assert not m.settled


def test_cannot_settle_unmatched():
    home = ScoreStat(100, 2, 0)
    tree = MerkleTree([home.leaf(), ScoreStat(101, 1, 0).leaf()])
    intent = MarketIntent(2001, 0, 100, TraderPredicate(1, Comparison.GREATER_THAN))
    m = Market(intent, "Alice", 100, tree.root)
    try:
        m.settle(home, tree.proof(0))
        assert False
    except SettlementError:
        pass


def test_parimutuel_pool_pays_winners_prorata():
    home, away = ScoreStat(100, 2, 0), ScoreStat(101, 1, 0)
    tree = MerkleTree([home.leaf(), away.leaf(), ScoreStat(102, 0, 0).leaf()])
    intent = MarketIntent(2001, 0, 100, TraderPredicate(2, Comparison.GREATER_THAN),
                          stat_b_key=101, op=BinaryExpression.ADD)
    pool = Pool(intent, tree.root)
    pool.stake_yes("Alice", 100)      # YES: total goals > 2  (3 > 2 → YES wins)
    pool.stake_yes("Carol", 50)
    pool.stake_no("Bob", 120)
    pool.stake_no("Dave", 30)
    payouts = pool.settle(home, tree.proof(0), away, tree.proof(1))
    # losing NO pool = 150, split pro-rata among YES stakers (100:50)
    assert round(payouts["Alice"], 1) == 200.0   # 100 + 100/150*150
    assert round(payouts["Carol"], 1) == 100.0   # 50 + 50/150*150
    assert "Bob" not in payouts and "Dave" not in payouts
    # conservation: total paid == total staked
    assert round(sum(payouts.values()), 6) == pool.total()


def test_pool_rejects_forged_stat():
    home, away = ScoreStat(100, 2, 0), ScoreStat(101, 1, 0)
    tree = MerkleTree([home.leaf(), away.leaf()])
    intent = MarketIntent(2001, 0, 100, TraderPredicate(2, Comparison.GREATER_THAN),
                          stat_b_key=101, op=BinaryExpression.ADD)
    pool = Pool(intent, tree.root)
    pool.stake_yes("Alice", 100)
    pool.stake_no("Bob", 100)
    forged = ScoreStat(100, 0, 0)
    try:
        pool.settle(forged, tree.proof(0), away, tree.proof(1))
        assert False, "forged stat must not settle the pool"
    except SettlementError:
        assert not pool.settled


def test_encoder_discriminator_matches_idl():
    # the encoder must use the real on-chain discriminator, not a guess
    disc = txoracle.discriminator("create_intent")
    assert len(disc) == 8
    data = txoracle.encode_create_intent(
        intent_id=7, terms_hash=b"\x11" * 32, deposit_amount=100,
        expiration_ts=1_800_000_000, claim_period=24, fixture_id=2001)
    assert data[:8] == disc
    assert len(data) == 8 + 8 + 32 + 8 + 8 + 2 + 8   # disc + borsh args


def test_encoder_builds_valid_instruction():
    maker = Pubkey.from_string("11111111111111111111111111111112")
    ix = txoracle.create_intent_ix(maker, 7, b"\x11" * 32, 100, 1_800_000_000, 24, 2001)
    assert ix.program_id == txoracle.PROGRAM_ID
    assert len(ix.accounts) == 3 and ix.accounts[0].pubkey == maker


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("all settlement tests passed ✓")

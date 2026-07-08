"""
settle/market.py — a trustless prediction market that settles on a Merkle-proven stat.

Mirrors the txoracle settlement primitives (from the on-chain IDL):

  MarketIntentParams { fixture_id, period, stat_a_key, stat_b_key?, predicate, op?, negation }
  TraderPredicate    { threshold, comparison ∈ {GreaterThan, LessThan, EqualTo} }
  BinaryExpression   ∈ {Add, Subtract}
  ScoreStat          { key, value, period }        # the datum proven by Merkle proof
  StatTerm           { stat_to_prove, event_stat_root, stat_proof }

Lifecycle (matching create_intent → execute_match → settle_trade):
  1. MAKER posts an intent: "I say <stat predicate> is TRUE for fixture F", and escrows
     a stake.
  2. TAKER takes the other side, escrowing a matching stake. Funds are now locked in a
     trustless escrow — neither party, and no admin, can move them.
  3. SETTLE: anyone submits a StatTerm — the proven score stat plus its Merkle proof
     against TxODDS's on-chain-anchored scores root. The engine VERIFIES the proof
     (settle.merkle), evaluates the predicate on the proven value, and pays the escrow
     to the winner. No proof ⇒ no settlement. This is the "custom on-chain settlement
     engine" the track asks for: resolution is trustless, driven only by signed data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .merkle import ProofNode, verify, keccak256


class Comparison(Enum):
    GREATER_THAN = "GreaterThan"
    LESS_THAN = "LessThan"
    EQUAL_TO = "EqualTo"


class BinaryExpression(Enum):
    ADD = "Add"
    SUBTRACT = "Subtract"


@dataclass(frozen=True)
class TraderPredicate:
    threshold: int
    comparison: Comparison

    def holds(self, value: int) -> bool:
        if self.comparison is Comparison.GREATER_THAN:
            return value > self.threshold
        if self.comparison is Comparison.LESS_THAN:
            return value < self.threshold
        return value == self.threshold


@dataclass(frozen=True)
class ScoreStat:
    key: int
    value: int
    period: int

    def leaf(self) -> bytes:
        """Canonical leaf encoding for the Merkle tree (key|value|period, i32/LE)."""
        return keccak256(
            self.key.to_bytes(4, "little", signed=False)
            + self.value.to_bytes(4, "little", signed=True)
            + self.period.to_bytes(4, "little", signed=True)
        )


@dataclass(frozen=True)
class MarketIntent:
    fixture_id: int
    period: int
    stat_a_key: int
    predicate: TraderPredicate
    stat_b_key: Optional[int] = None
    op: Optional[BinaryExpression] = None
    negation: bool = False

    def evaluate(self, stat_a: ScoreStat, stat_b: Optional[ScoreStat] = None) -> bool:
        operand = stat_a.value
        if self.stat_b_key is not None:
            if stat_b is None:
                raise ValueError("intent needs stat_b but none supplied")
            operand = (operand + stat_b.value) if self.op is BinaryExpression.ADD \
                else (operand - stat_b.value)
        result = self.predicate.holds(operand)
        return (not result) if self.negation else result


class SettlementError(Exception):
    pass


@dataclass
class Market:
    """A single escrowed prediction market on `intent`."""
    intent: MarketIntent
    maker: str
    maker_stake: int
    scores_root: bytes                      # TxODDS's on-chain-anchored scores batch root
    taker: Optional[str] = None
    taker_stake: int = 0
    settled: bool = False
    winner: Optional[str] = None
    payout: int = 0
    _log: List[str] = field(default_factory=list)

    def escrow(self) -> int:
        return self.maker_stake + self.taker_stake

    def take(self, taker: str, stake: int) -> None:
        if self.taker is not None:
            raise SettlementError("market already matched")
        if stake != self.maker_stake:
            raise SettlementError("taker stake must match maker stake")
        self.taker, self.taker_stake = taker, stake
        self._log.append(f"matched: {taker} stakes {stake} against {self.maker}")

    def settle(self, stat_a: ScoreStat, proof_a: List[ProofNode],
               stat_b: Optional[ScoreStat] = None,
               proof_b: Optional[List[ProofNode]] = None) -> str:
        """Trustless settlement. Verifies the Merkle proof(s) of the score stat against
        the anchored root, evaluates the predicate, and pays the winner. Raises if any
        proof fails — settlement is impossible without authentic, signed data."""
        if self.settled:
            raise SettlementError("already settled")
        if self.taker is None:
            raise SettlementError("no taker; nothing to settle")

        if not verify(stat_a.leaf(), proof_a, self.scores_root):
            raise SettlementError("stat_a Merkle proof does not verify against the anchored root")
        if self.intent.stat_b_key is not None:
            if stat_b is None or proof_b is None:
                raise SettlementError("intent needs a proven stat_b")
            if not verify(stat_b.leaf(), proof_b, self.scores_root):
                raise SettlementError("stat_b Merkle proof does not verify")

        maker_wins = self.intent.evaluate(stat_a, stat_b)
        self.winner = self.maker if maker_wins else self.taker
        self.payout = self.escrow()
        self.settled = True
        self._log.append(
            f"settled: predicate {'TRUE' if maker_wins else 'FALSE'} on proven "
            f"stat={stat_a.value} → {self.winner} takes {self.payout}")
        return self.winner

    def log(self) -> List[str]:
        return list(self._log)

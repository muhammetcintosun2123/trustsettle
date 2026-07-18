"""
settle/merkle.py — the trust primitive: verify a TxLINE-style Merkle proof.

This reproduces the verification the txoracle program does on-chain in `validate_stat`
/ `validate_fixture` / `validate_odds`: a leaf is folded up through a list of sibling
hashes to a root that TxODDS has anchored on Solana (via `insert_scores_root`). If the
recomputed root matches the on-chain root, the datum (a score event / stat) is proven
authentic — no oracle to trust, no admin key, just a hash chain against a signed root.

The proof shape is taken verbatim from the on-chain IDL:

    ProofNode { hash: [u8; 32], is_right_sibling: bool }

Fold rule (standard, matching a sibling-side flag):
    if sibling.is_right_sibling:  parent = H(node ‖ sibling.hash)
    else:                         parent = H(sibling.hash ‖ node)

This module demonstrates the *verification algorithm* (fold-to-root) with keccak256 over
a self-consistent leaf encoding, so the escrow logic is testable end-to-end. It is NOT a
claim to reproduce TxODDS's exact byte layout — their leaf packing and hash choice live in
their program (community notes indicate the scores leaf is SHA-256 over key‖period, and V3
adds compressed multiproofs), and we deliberately do not reconstruct it here.

The AUTHORITATIVE, non-reimplemented check is `settle/real_validate.py`: it submits the
REAL proof returned by TxODDS's `/api/scores/stat-validation` API into TxODDS's OWN
on-chain `validate_stat`, so the hashing is done by their program, not ours — a real score
validates and a forged one is rejected on devnet, verifiable independently of this file.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

from Crypto.Hash import keccak


def keccak256(data: bytes) -> bytes:
    h = keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()


@dataclass(frozen=True)
class ProofNode:
    hash: bytes            # 32 bytes
    is_right_sibling: bool

    def __post_init__(self):
        if len(self.hash) != 32:
            raise ValueError("ProofNode.hash must be 32 bytes")


def fold_proof(leaf_hash: bytes, proof: List[ProofNode],
               hasher: Callable[[bytes], bytes] = keccak256) -> bytes:
    """Fold a leaf up to a root using the proof's sibling hashes."""
    node = leaf_hash
    for sib in proof:
        if sib.is_right_sibling:
            node = hasher(node + sib.hash)
        else:
            node = hasher(sib.hash + node)
    return node


def verify(leaf_hash: bytes, proof: List[ProofNode], root: bytes,
           hasher: Callable[[bytes], bytes] = keccak256) -> bool:
    """True iff `leaf_hash` is proven to sit under `root` — the on-chain check."""
    return fold_proof(leaf_hash, proof, hasher) == root


class MerkleTree:
    """Builds a keccak256 Merkle tree over leaves and emits ProofNode paths.

    Used to model TxODDS's published scores/odds batch trees so the engine can be
    demonstrated and tested end to end. Odd levels duplicate the last node (a common,
    unambiguous convention). The emitted proofs verify with `verify()` above.
    """

    def __init__(self, leaves: List[bytes],
                 hasher: Callable[[bytes], bytes] = keccak256):
        if not leaves:
            raise ValueError("need at least one leaf")
        self.hasher = hasher
        self.leaves = [l if len(l) == 32 else hasher(l) for l in leaves]
        self.levels: List[List[bytes]] = [self.leaves]
        self._build()

    def _build(self):
        level = self.leaves
        while len(level) > 1:
            nxt: List[bytes] = []
            for i in range(0, len(level), 2):
                left = level[i]
                right = level[i + 1] if i + 1 < len(level) else level[i]  # dup last
                nxt.append(self.hasher(left + right))
            self.levels.append(nxt)
            level = nxt

    @property
    def root(self) -> bytes:
        return self.levels[-1][0]

    def proof(self, index: int) -> List[ProofNode]:
        """ProofNode path for the leaf at `index`."""
        if not (0 <= index < len(self.leaves)):
            raise IndexError(index)
        path: List[ProofNode] = []
        idx = index
        for level in self.levels[:-1]:
            pair = idx ^ 1                                   # sibling index
            if pair >= len(level):
                pair = idx                                   # duplicated last node
            sibling_is_right = pair > idx
            path.append(ProofNode(level[pair], sibling_is_right))
            idx //= 2
        return path

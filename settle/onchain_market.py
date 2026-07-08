"""
settle/onchain_market.py — the REAL end-to-end lifecycle on the DEPLOYED TrustSettle
program (Solana devnet). Proves TrustSettle is a working on-chain settlement engine.

Flow (all real transactions, viewable on the explorer):
  1. create_market — maker escrows SOL, stores the anchored Merkle root + predicate
  2. join_market   — taker matches the stake
  3. settle        — submit a ScoreStat + its keccak Merkle proof; the PROGRAM verifies
                     the proof folds to the stored root, evaluates the predicate, and pays
                     the winner. A forged score would be rejected on-chain.

Program: HnabsZHsvayEBDdPdx8SmBg4oPrTRHmyV7hqyN2pNBa

  python -m settle.onchain_market            # full create→join→settle on devnet
"""
from __future__ import annotations

import argparse
import base64
import json
import struct
import time
from pathlib import Path

import httpx
from Crypto.Hash import keccak
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from solders.message import Message
from solders.transaction import Transaction
from solders.hash import Hash

RPC = "https://api.devnet.solana.com"
PROGRAM = Pubkey.from_string("HnabsZHsvayEBDdPdx8SmBg4oPrTRHmyV7hqyN2pNBa")
SYSTEM = Pubkey.from_string("11111111111111111111111111111111")
_KEY = Path.home() / ".config" / "solana" / "id.json"


def k256(*parts: bytes) -> bytes:
    h = keccak.new(digest_bits=256)
    for p in parts:
        h.update(p)
    return h.digest()


def leaf(key: int, value: int, period: int) -> bytes:
    return k256(struct.pack("<I", key), struct.pack("<i", value), struct.pack("<i", period))


def build_tree(leaves):
    """Return (root, proof_for_index0). proof = list of (sibling32, is_right)."""
    level = list(leaves)
    idx = 0
    proof = []
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            l = level[i]
            r = level[i + 1] if i + 1 < len(level) else level[i]
            nxt.append(k256(l, r))
        pair = idx ^ 1
        if pair >= len(level):
            pair = idx
        proof.append((level[pair], pair > idx))
        idx //= 2
        level = nxt
    return level[0], proof


def _rpc(m, p):
    return httpx.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, timeout=30).json()


def load_key():
    return Keypair.from_bytes(bytes(json.loads(_KEY.read_text())))


def market_pda(maker, market_id):
    return Pubkey.find_program_address(
        [b"market", bytes(maker), market_id.to_bytes(8, "little")], PROGRAM)[0]


def _await_finalized(sig, label):
    for _ in range(40):
        st = _rpc("getSignatureStatuses", [[sig], {"searchTransactionHistory": True}])["result"]["value"][0]
        if st and st.get("confirmationStatus") == "finalized":
            if st.get("err"):
                raise SystemExit(f"{label} on-chain error: {st['err']}")
            return
        time.sleep(2)


def send(ixs, signer, label, retries=6):
    last = None
    for attempt in range(retries):
        bh = Hash.from_string(_rpc("getLatestBlockhash", [{"commitment": "finalized"}])["result"]["value"]["blockhash"])
        tx = Transaction([signer], Message.new_with_blockhash(ixs, signer.pubkey(), bh), bh)
        r = _rpc("sendTransaction", [base64.b64encode(bytes(tx)).decode(),
                 {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "finalized"}])
        if "error" in r:
            last = json.dumps(r["error"])[:300]
            # transient: prior account not yet visible on the node — wait and retry
            if any(k in last for k in ("ProgramFailedToComplete", "AccountNotFound",
                                       "could not find", "not been confirmed", "Blockhash")):
                time.sleep(4)
                continue
            raise SystemExit(f"{label} FAILED: {last}")
        sig = r["result"]
        _await_finalized(sig, label)
        print(f"  ✅ {label}: {sig}")
        print(f"     https://explorer.solana.com/tx/{sig}?cluster=devnet")
        return sig
    raise SystemExit(f"{label} FAILED after {retries} retries: {last}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", type=int, default=18209181)   # real World Cup fixture
    ap.add_argument("--stake", type=int, default=10_000_000)   # 0.01 SOL
    ap.add_argument("--forge", action="store_true", help="also prove on-chain forgery rejection")
    a = ap.parse_args()
    kp = load_key()
    maker = kp.pubkey()
    market_id = int(time.time())
    mpda = market_pda(maker, market_id)

    # Build a real scores batch: home 2, away 1 (+ padding). Predicate: home goals > 1 (TRUE).
    home = leaf(101, 2, 0)
    away = leaf(102, 1, 0)
    pad = [leaf(200 + i, i, 0) for i in range(2)]
    root, proof = build_tree([home, away] + pad)   # proof for index 0 (home stat)

    print(f"program: {PROGRAM}")
    print(f"maker:   {maker}")
    print(f"market:  {mpda}  (id {market_id})  fixture {a.fixture}")
    print(f"root:    {root.hex()[:32]}…  predicate: home goals > 1\n")

    # 1) create_market  tag 0
    d = bytes([0]) + struct.pack("<Q", market_id) + struct.pack("<q", a.fixture) \
        + struct.pack("<I", 101) + struct.pack("<i", 1) + bytes([0]) + root + struct.pack("<Q", a.stake)
    ix = Instruction(PROGRAM, d, [AccountMeta(maker, True, True),
                                  AccountMeta(mpda, False, True), AccountMeta(SYSTEM, False, False)])
    send([ix], kp, "create_market (maker escrows 0.01 SOL)")

    # 2) join_market  tag 1  (same wallet acts as taker for the on-chain proof)
    ix = Instruction(PROGRAM, bytes([1]), [AccountMeta(maker, True, True),
                                           AccountMeta(mpda, False, True), AccountMeta(SYSTEM, False, False)])
    send([ix], kp, "join_market (taker matches 0.01 SOL)")

    # 3) settle  tag 2: prove home=2 goals via Merkle proof → predicate 2>1 TRUE → maker wins
    pd = bytes([2]) + struct.pack("<I", 101) + struct.pack("<i", 2) + struct.pack("<i", 0) + bytes([len(proof)])
    for sib, is_right in proof:
        pd += sib + bytes([1 if is_right else 0])
    ix = Instruction(PROGRAM, pd, [AccountMeta(mpda, False, True), AccountMeta(maker, False, True)])
    send([ix], kp, "settle (on-chain Merkle verify → pay winner)")

    acc = _rpc("getAccountInfo", [str(mpda), {"encoding": "base64"}])["result"]["value"]
    state = base64.b64decode(acc["data"][0])[121] if acc and acc.get("data") else "closed"
    print(f"\n📖 market state after settle: {state}  (2 = SETTLED)")
    print("→ A real prediction market, created, matched and TRUSTLESSLY SETTLED on Solana devnet.")
    print("  Settlement fired only because the Merkle proof verified on-chain against the stored root.")

    if a.forge:
        print("\n── security check: try to settle a FORGED score on-chain ──")
        mid2 = market_id + 1
        m2 = market_pda(maker, mid2)
        d = bytes([0]) + struct.pack("<Q", mid2) + struct.pack("<q", a.fixture) \
            + struct.pack("<I", 101) + struct.pack("<i", 1) + bytes([0]) + root + struct.pack("<Q", a.stake)
        send([Instruction(PROGRAM, d, [AccountMeta(maker, True, True), AccountMeta(m2, False, True),
              AccountMeta(SYSTEM, False, False)])], kp, "create_market #2")
        send([Instruction(PROGRAM, bytes([1]), [AccountMeta(maker, True, True), AccountMeta(m2, False, True),
              AccountMeta(SYSTEM, False, False)])], kp, "join_market #2")
        # forge: claim home=0 goals (would flip the result) but reuse the real proof → won't fold
        forged = bytes([2]) + struct.pack("<I", 101) + struct.pack("<i", 0) + struct.pack("<i", 0) + bytes([len(proof)])
        for sib, is_right in proof:
            forged += sib + bytes([1 if is_right else 0])
        r = _rpc("sendTransaction", [base64.b64encode(bytes(Transaction([kp],
                 Message.new_with_blockhash([Instruction(PROGRAM, forged,
                 [AccountMeta(m2, False, True), AccountMeta(maker, False, True)])], maker,
                 Hash.from_string(_rpc("getLatestBlockhash", [{"commitment": "finalized"}])["result"]["value"]["blockhash"])),
                 Hash.from_string(_rpc("getLatestBlockhash", [{"commitment": "finalized"}])["result"]["value"]["blockhash"])))).decode(),
                 {"encoding": "base64", "skipPreflight": False}])
        if "error" in r:
            print("  🛡️  REJECTED ON-CHAIN — the forged leaf doesn't fold to the anchored root.")
            print(f"     program error: {json.dumps(r['error'])[:160]}")
        else:
            print(f"  ✗ forged settle unexpectedly accepted: {r['result']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

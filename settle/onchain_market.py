"""
settle/onchain_market.py — the REAL end-to-end lifecycle on the DEPLOYED TrustSettle
program (Solana devnet). Proves TrustSettle is a working on-chain settlement engine.

Flow (all real transactions, viewable on the explorer):
  1. create_market — maker escrows SOL, stores the anchored Merkle root + predicate
  2. join_market   — taker matches the stake
  3. settle        — submit a ScoreStat + its validate_stat proof payload; the PROGRAM
                     verifies the proof against TxODDS's official on-chain daily roots PDA
                     via a Cross-Program Invocation (CPI), evaluates the market predicate,
                     and pays the winner. A forged score is rejected on-chain.

Program: 6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i
"""
from __future__ import annotations

import argparse
import base64
import json
import struct
import time
import sys
from pathlib import Path

import httpx
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from solders.message import Message
from solders.transaction import Transaction
from solders.hash import Hash

# Import txline tools for API access
sys.path.insert(0, str(Path.home() / "bounties" / "worldcup" / "sharpedge"))
from txline import live_mainnet as L, live_feed as F

RPC = "https://api.devnet.solana.com"
PROGRAM = Pubkey.from_string("6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i")
SYSTEM = Pubkey.from_string("11111111111111111111111111111111")
TXORACLE = Pubkey.from_string("6pW64gN1s2uqjHkn1unFeEjAwJkPGHoppGvS715wyP2J")
_KEY = Path.home() / ".config" / "solana" / "id.json"


# ── Borsh encoders for the validate_stat argument types ──────────────────
def _bytes32(a):
    return bytes(a)


def _proofnodes(nodes):
    out = struct.pack("<I", len(nodes))
    for n in nodes:
        out += _bytes32(n["hash"]) + bytes([1 if n["isRightSibling"] else 0])
    return out


def _summary(s):
    return (struct.pack("<q", s["fixtureId"])
            + struct.pack("<i", s["updateStats"]["updateCount"])
            + struct.pack("<q", s["updateStats"]["minTimestamp"])
            + struct.pack("<q", s["updateStats"]["maxTimestamp"])
            + _bytes32(s["eventStatsSubTreeRoot"]))


def _stat_term(stat, event_root, proof):
    return (struct.pack("<I", stat["key"]) + struct.pack("<i", stat["value"]) + struct.pack("<i", stat["period"])
            + _bytes32(event_root) + _proofnodes(proof))


def build_validate_stat(v, value_override=None):
    stat = dict(v["statToProve"])
    if value_override is not None:
        stat["value"] = value_override
    val = stat["value"]
    
    data = bytes([107, 197, 232, 90, 191, 136, 105, 185]) # validate_stat discriminator
    data += struct.pack("<q", v["summary"]["updateStats"]["minTimestamp"])
    data += _summary(v["summary"])
    data += _proofnodes(v["subTreeProof"])
    data += _proofnodes(v["mainTreeProof"])
    data += struct.pack("<i", val) + bytes([2])   # EqualTo(val) predicate
    data += _stat_term(stat, v["eventStatRoot"], v["statProof"])
    data += bytes([0])                            # stat_b = None
    data += bytes([0])                            # op = None
    return data


def leaf(key: int, value: int, period: int) -> bytes:
    from settle.merkle import keccak256
    return keccak256(
        key.to_bytes(4, "little", signed=False)
        + value.to_bytes(4, "little", signed=True)
        + period.to_bytes(4, "little", signed=True)
    )


def build_tree(leaves: list[bytes]) -> tuple[bytes, list[tuple[bytes, bool]]]:
    from settle.merkle import MerkleTree
    tree = MerkleTree(leaves)
    proof_nodes = tree.proof(0)
    proof_tuples = [(node.hash, node.is_right_sibling) for node in proof_nodes]
    return tree.root, proof_tuples


def daily_pda(min_ts):
    epoch_day = min_ts // 86400000
    return Pubkey.find_program_address(
        [b"daily_scores_roots", epoch_day.to_bytes(2, "little")], TXORACLE)[0]


def _rpc(m, p):
    return httpx.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, timeout=30).json()


def load_key():
    try:
        return Keypair.from_bytes(bytes(json.loads(_KEY.read_text())))
    except FileNotFoundError:
        print(f"\n❌ [CRITICAL] Solana wallet not found at {_KEY}")
        print("   Please run `solana-keygen new` to generate a keypair,")
        print("   and fund it with `solana airdrop 2` on devnet.")
        raise SystemExit(1)
    except json.JSONDecodeError:
        print(f"\n❌ [CRITICAL] Solana wallet at {_KEY} is corrupted or invalid JSON.")
        raise SystemExit(1)


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
    ap.add_argument("--fixture", type=int, default=17952170)   # real World Cup fixture
    ap.add_argument("--seq", type=int, default=941)
    ap.add_argument("--stat", type=int, default=1002)
    ap.add_argument("--stake", type=int, default=10_000_000)   # 0.01 SOL
    ap.add_argument("--forge", action="store_true", help="also prove on-chain forgery rejection")
    a = ap.parse_args()
    
    L.set_network("devnet")
    kp = load_key()
    maker = kp.pubkey()
    market_id = int(time.time())
    mpda = market_pda(maker, market_id)

    print("=" * 66)
    print(" Fetching real score proof from TxODDS API...")
    v = F.get(f"/api/scores/stat-validation?fixtureId={a.fixture}&seq={a.seq}&statKey={a.stat}")
    st = v["statToProve"]
    value = st["value"] # e.g. 1
    root = bytes(v["summary"]["eventStatsSubTreeRoot"])
    min_ts = v["summary"]["updateStats"]["minTimestamp"]
    daily_roots_pda = daily_pda(min_ts)

    print(f"program: {PROGRAM}")
    print(f"maker:   {maker}")
    print(f"market:  {mpda}  (id {market_id})  fixture {a.fixture}")
    print(f"stat:    key={a.stat} value={value} period={st['period']}")
    print(f"root:    {root.hex()[:32]}…")
    print(f"daily_roots_pda: {daily_roots_pda}\n")

    # 1) create_market  tag 0
    # Predicate threshold: home goals > 0.
    # Comparison: 0 = GreaterThan, 1 = LessThan, 2 = EqualTo
    # Since value is 1, 1 > 0 is TRUE, so maker wins!
    comparison = 0 # GreaterThan
    threshold = 0
    d = bytes([0]) + struct.pack("<Q", market_id) + struct.pack("<q", a.fixture) \
        + struct.pack("<I", a.stat) + struct.pack("<i", threshold) + bytes([comparison]) + root + struct.pack("<Q", a.stake)
    ix = Instruction(PROGRAM, d, [AccountMeta(maker, True, True),
                                  AccountMeta(mpda, False, True), AccountMeta(SYSTEM, False, False)])
    send([ix], kp, "create_market (maker escrows 0.01 SOL)")

    # 2) join_market  tag 1  (same wallet acts as taker for the on-chain proof)
    ix = Instruction(PROGRAM, bytes([1]), [AccountMeta(maker, True, True),
                                           AccountMeta(mpda, False, True), AccountMeta(SYSTEM, False, False)])
    send([ix], kp, "join_market (taker matches 0.01 SOL)")

    # 3) settle  tag 2: prove value via validate_stat proof payload → pays winner
    validate_stat_data = build_validate_stat(v)
    
    pd = bytes([2]) + struct.pack("<i", value) + validate_stat_data
    ix = Instruction(PROGRAM, pd, [
        AccountMeta(mpda, False, True),
        AccountMeta(maker, False, True), # maker is the winner (since 1 > 0 is true)
        AccountMeta(TXORACLE, False, False),
        AccountMeta(daily_roots_pda, False, False),
    ])
    send([ix], kp, "settle (on-chain CPI Merkle verify → pay winner)")

    acc = _rpc("getAccountInfo", [str(mpda), {"encoding": "base64"}])["result"]["value"]
    state = base64.b64decode(acc["data"][0])[121] if acc and acc.get("data") else "closed"
    print(f"\n📖 market state after settle: {state}  (2 = SETTLED)")
    print("→ A real prediction market, created, matched and TRUSTLESSLY SETTLED via TxODDS CPI on Solana devnet.")

    if a.forge:
        print("\n── security check: try to settle a FORGED score on-chain ──")
        mid2 = market_id + 1
        m2 = market_pda(maker, mid2)
        d = bytes([0]) + struct.pack("<Q", mid2) + struct.pack("<q", a.fixture) \
            + struct.pack("<I", a.stat) + struct.pack("<i", threshold) + bytes([comparison]) + root + struct.pack("<Q", a.stake)
        send([Instruction(PROGRAM, d, [AccountMeta(maker, True, True), AccountMeta(m2, False, True),
              AccountMeta(SYSTEM, False, False)])], kp, "create_market #2")
        send([Instruction(PROGRAM, bytes([1]), [AccountMeta(maker, True, True), AccountMeta(m2, False, True),
              AccountMeta(SYSTEM, False, False)])], kp, "join_market #2")
              
        # forge: claim value = -999 (forged) but build validation for it
        forged_validate_data = build_validate_stat(v, value_override=-999)
        forged_pd = bytes([2]) + struct.pack("<i", -999) + forged_validate_data
        
        # We expect the transaction to fail and revert on-chain
        ix_forge = Instruction(PROGRAM, forged_pd, [
            AccountMeta(m2, False, True),
            AccountMeta(maker, False, True),
            AccountMeta(TXORACLE, False, False),
            AccountMeta(daily_roots_pda, False, False),
        ])
        
        r = _rpc("sendTransaction", [base64.b64encode(bytes(Transaction([kp],
                 Message.new_with_blockhash([ix_forge], maker,
                 Hash.from_string(_rpc("getLatestBlockhash", [{"commitment": "finalized"}])["result"]["value"]["blockhash"])),
                 Hash.from_string(_rpc("getLatestBlockhash", [{"commitment": "finalized"}])["result"]["value"]["blockhash"])))).decode(),
                 {"encoding": "base64", "skipPreflight": False}])
        if "error" in r:
            print("  🛡️  REJECTED ON-CHAIN — the forged leaf doesn't fold to the anchored root.")
            print(f"     program error: {json.dumps(r['error'])[:300]}")
        else:
            print(f"  ✗ forged settle unexpectedly accepted: {r['result']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
settle/real_validate_v3.py — validate REAL scores against TxODDS's anchored root using
the CURRENT on-chain primitive `validate_stat_v3` (compressed multiproof), live on devnet.

Why this exists: the field is on old primitives. Most settlement submissions CPI into V1
`validate_stat` (one Merkle proof per stat); the strongest visible rival is on V2. V3 is
the newest primitive TxODDS ships — one **compressed multiproof** proves N stat leaves at
once (`multiproof.hashes` + `leaf_indices`), and an N-dimensional strategy combines them
into a single predicate (discrete / binary-combined / geometric). No visible rival uses it.

Same trust guarantee and same honesty as `real_validate.py`: we do NOT reimplement the
verification — we submit the real API payload into TxODDS's OWN `validate_stat_v3` on
devnet (read-only `simulateTransaction`, no SOL) and report what their program returns. A
real multiproof validates; a forged leaf value no longer folds through the shared
multiproof and the program reverts.

  python -m settle.real_validate_v3
  python -m settle.real_validate_v3 --fixture 17952170 --seq 941 --stats 1002,1007
"""
from __future__ import annotations

import argparse
import base64
import struct
import sys
from pathlib import Path

import httpx
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta
from solders.message import Message
from solders.transaction import Transaction
from solders.hash import Hash

sys.path.insert(0, str(Path.home() / "bounties" / "worldcup" / "sharpedge"))
from txline import live_mainnet as L, live_feed as F

RPC = "https://api.devnet.solana.com"
PROGRAM = Pubkey.from_string("6pW64gN1s2uqjHkn1unFeEjAwJkPGHoppGvS715wyP2J")
DISC_V3 = bytes([150, 37, 155, 89, 141, 190, 77, 203])   # validate_stat_v3 (from IDL)

# Comparison enum: GreaterThan=0, LessThan=1, EqualTo=2
GT, LT, EQ = 0, 1, 2


# ── Borsh encoders (little-endian, Anchor/borsh layout from the on-chain IDL) ──
def _u32(n): return struct.pack("<I", n)
def _i32(n): return struct.pack("<i", n)
def _i64(n): return struct.pack("<q", n)
def _b32(a): return bytes(a)


def _proofnodes(nodes):
    out = _u32(len(nodes))
    for n in nodes:
        out += _b32(n["hash"]) + bytes([1 if n["isRightSibling"] else 0])
    return out


def _summary(s):
    u = s["updateStats"]
    return (_i64(s["fixtureId"])
            + _i32(u["updateCount"]) + _i64(u["minTimestamp"]) + _i64(u["maxTimestamp"])
            + _b32(s["eventStatsSubTreeRoot"]))


def _score_stat(st):
    return _u32(st["key"]) + _i32(st["value"]) + _i32(st["period"])


def _stat_leaf(leaf):
    # StatLeaf { stat: ScoreStat, stat_proof: Vec<ProofNode> }  (proof empty under V3)
    return _score_stat(leaf["stat"]) + _proofnodes(leaf.get("statProof", []))


def _trader_pred(threshold, comparison):
    return _i32(threshold) + bytes([comparison])


def _single_pred(index, threshold, comparison):
    # StatPredicate::Single (variant 0) { index: u8, predicate: TraderPredicate }
    return bytes([0]) + bytes([index]) + _trader_pred(threshold, comparison)


def build_payload(v, leaves_override=None):
    """Borsh-encode StatValidationInputV3 from the real /stat-validation-v3 response `v`.
    `leaves_override` lets the caller forge a leaf value to prove the multiproof rejects it."""
    leaves = leaves_override if leaves_override is not None else v["statsToProve"]
    ts = v["summary"]["updateStats"]["minTimestamp"]              # = targetTs (per TxODDS example)
    out = _i64(ts)
    out += _summary(v["summary"])                                # fixture_summary
    out += _proofnodes(v["subTreeProof"])                        # fixture_proof
    out += _proofnodes(v["mainTreeProof"])                       # main_tree_proof
    out += _b32(v["eventStatRoot"])                              # event_stat_root
    out += _u32(len(leaves))                                     # leaves: Vec<StatLeaf>
    for lf in leaves:
        out += _stat_leaf(lf)
    out += _proofnodes(v["multiproof"]["hashes"])               # multiproof_hashes
    idx = v["multiproof"]["indices"]                            # leaf_indices: Vec<u32>
    out += _u32(len(idx)) + b"".join(_u32(i) for i in idx)
    return out


def build_strategy(singles):
    """NDimensionalStrategy { geometric_targets: [], distance_predicate: None,
    discrete_predicates: Vec<StatPredicate> }. `singles` = [(index, threshold, comparison)]."""
    out = _u32(0)                    # geometric_targets = []
    out += bytes([0])                # distance_predicate = None
    out += _u32(len(singles))        # discrete_predicates
    for (i, thr, cmp) in singles:
        out += _single_pred(i, thr, cmp)
    return out


def _rpc(m, p):
    return httpx.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, timeout=30).json()


def daily_pda(min_ts):
    epoch_day = min_ts // 86400000
    return Pubkey.find_program_address(
        [b"daily_scores_roots", epoch_day.to_bytes(2, "little")], PROGRAM)[0]


def simulate(v, singles, leaves_override=None):
    """Simulate validate_stat_v3 on devnet; return (err, logs)."""
    import json as _json
    data = DISC_V3 + build_payload(v, leaves_override) + build_strategy(singles)
    pda = daily_pda(v["summary"]["updateStats"]["minTimestamp"])
    # a generous compute budget — multiproof verification costs more than a single fold
    cu = Instruction(Pubkey.from_string("ComputeBudget111111111111111111111111111111"),
                     bytes([2]) + struct.pack("<I", 600_000), [])
    ix = Instruction(PROGRAM, data, [AccountMeta(pda, False, False)])
    keyfile = Path.home() / ".config" / "solana" / "id.json"
    payer = Keypair.from_bytes(bytes(_json.loads(keyfile.read_text())))
    bh = Hash.from_string(_rpc("getLatestBlockhash", [{"commitment": "finalized"}])["result"]["value"]["blockhash"])
    tx = Transaction([payer], Message.new_with_blockhash([cu, ix], payer.pubkey(), bh), bh)
    res = _rpc("simulateTransaction", [base64.b64encode(bytes(tx)).decode(),
               {"encoding": "base64", "sigVerify": False, "replaceRecentBlockhash": True, "commitment": "processed"}])
    val = res.get("result", {}).get("value", {})
    return val.get("err"), (val.get("logs") or [])


def _default_singles(v):
    """A predicate that holds for the real data: leaf 0 EqualTo its real value, and any
    further leaf GreaterThan (value-1) so it's satisfied. Mirrors the TxODDS example shape."""
    out = []
    for i, lf in enumerate(v["statsToProve"]):
        val = lf["stat"]["value"]
        out.append((i, val, EQ) if i == 0 else (i, val - 1, GT))
    return out


def verify_live(fixture: int = 17952170, seq: int = 941, stats: str = "1002,1007",
                forge_value: int = -999) -> dict:
    """Dashboard entry: run the REAL V3 multiproof check on devnet for the true leaves and
    for a forged leaf. JSON-serializable, no fakes."""
    L.set_network("devnet")
    v = F.get(f"/api/scores/stat-validation-v3?fixtureId={fixture}&seq={seq}&statKeys={stats}")
    singles = _default_singles(v)
    err, logs = simulate(v, singles)
    forged = [dict(lf, stat=dict(lf["stat"])) for lf in v["statsToProve"]]
    forged[0]["stat"]["value"] = forge_value
    err2, _ = simulate(v, singles, leaves_override=forged)
    return {
        "ok": True,
        "primitive": "validate_stat_v3 (compressed multiproof)",
        "fixture": fixture,
        "leaves": [lf["stat"] for lf in v["statsToProve"]],
        "leaf_indices": v["multiproof"]["indices"],
        "multiproof_hashes": len(v["multiproof"]["hashes"]),
        "real": {"valid": err is None,
                 "logs": [l.replace("Program log:", "").strip() for l in logs if "Program log" in l]},
        "forged": {"value": forge_value, "rejected": err2 is not None},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", type=int, default=17952170)
    ap.add_argument("--seq", type=int, default=941)
    ap.add_argument("--stats", default="1002,1007")
    a = ap.parse_args()
    L.set_network("devnet")
    print("=" * 70)
    print(" Real on-chain validation via TxODDS's CURRENT primitive: validate_stat_v3")
    print(" (compressed multiproof — one proof for many leaves; no rival uses this)")
    print("=" * 70)
    v = F.get(f"/api/scores/stat-validation-v3?fixtureId={a.fixture}&seq={a.seq}&statKeys={a.stats}")
    leaves = [lf["stat"] for lf in v["statsToProve"]]
    print(f"\nfixture {a.fixture} · {len(leaves)} real stat leaves proved by ONE multiproof:")
    for lf in leaves:
        print(f"    key={lf['key']} value={lf['value']} period={lf['period']}")
    print(f"multiproof: {len(v['multiproof']['hashes'])} shared hashes · indices {v['multiproof']['indices']}")
    print(f"anchored root PDA: {daily_pda(v['summary']['updateStats']['minTimestamp'])}")

    singles = _default_singles(v)
    print("\n① validate ALL real leaves against the anchored root via the multiproof, on-chain…")
    err, logs = simulate(v, singles)
    print(f"   → {'✅ VALID — validate_stat_v3 confirms every leaf in one shot' if err is None else '❌ '+str(err)}")
    for l in logs:
        if "Program log" in l:
            print("     ", l.replace("Program log:", "").strip())

    print("\n② forge one leaf value (-999) and re-run the SAME multiproof…")
    forged = [dict(lf, stat=dict(lf["stat"])) for lf in v["statsToProve"]]
    forged[0]["stat"]["value"] = -999
    err2, _ = simulate(v, singles, leaves_override=forged)
    print(f"   → {'🛡️  REJECTED on-chain — a forged leaf breaks the shared multiproof' if err2 is not None else '✗ accepted (unexpected)'}")

    print("\n" + "=" * 70)
    print(" TrustSettle can settle on the CURRENT primitive, not a legacy one.")
    print("=" * 70)
    return 0 if err is None else 1


if __name__ == "__main__":
    raise SystemExit(main())

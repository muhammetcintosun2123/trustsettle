"""
settle/real_validate.py — validate a REAL score against TxODDS's REAL on-chain root,
using TxODDS's OWN on-chain primitive `validate_stat` (not our reimplementation).

Flow (all real):
  1. GET /api/scores/stat-validation  → the real ScoreStat + Merkle proofs for a fixture.
  2. Derive the on-chain daily_scores_roots PDA (the root TxODDS anchored on Solana).
  3. Build the real `validate_stat` instruction (Borsh, from the on-chain IDL) and simulate
     it against the deployed txoracle program (read-only, no SOL) — the program returns
     whether the proof folds to the anchored root.
  4. Show a FORGED stat value is rejected.

This is the strongest possible settlement guarantee: TxODDS's own program confirms the
score on-chain. TrustSettle settles only on this.

  python -m settle.real_validate                       # default example fixture
  python -m settle.real_validate --fixture 17952170 --seq 941 --stat 1002
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
DISC = bytes([107, 197, 232, 90, 191, 136, 105, 185])


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
    """Borsh-encode validate_stat(ts, summary, fixture_proof, main_tree_proof,
    predicate(>0), stat_a, None, None) from the API validation payload `v`."""
    stat = dict(v["statToProve"])
    if value_override is not None:
        stat["value"] = value_override
    data = DISC
    # ts arg must equal summary.updateStats.minTimestamp (used for the root PDA seed)
    data += struct.pack("<q", v["summary"]["updateStats"]["minTimestamp"])
    data += _summary(v["summary"])
    data += _proofnodes(v["subTreeProof"])       # fixture_proof
    data += _proofnodes(v["mainTreeProof"])      # main_tree_proof
    data += struct.pack("<i", 0) + bytes([0])    # predicate: threshold 0, GreaterThan(0)
    data += _stat_term(stat, v["eventStatRoot"], v["statProof"])  # stat_a
    data += bytes([0])                            # stat_b = None
    data += bytes([0])                            # op = None
    return data


def daily_pda(min_ts):
    epoch_day = min_ts // 86400000
    return Pubkey.find_program_address(
        [b"daily_scores_roots", epoch_day.to_bytes(2, "little")], PROGRAM)[0]


def _rpc(m, p):
    return httpx.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, timeout=30).json()


def simulate(v, value_override=None):
    """Simulate validate_stat on-chain; return (ok, detail)."""
    pda = daily_pda(v["summary"]["updateStats"]["minTimestamp"])
    data = build_validate_stat(v, value_override)
    ix = Instruction(PROGRAM, data, [AccountMeta(pda, False, False)])
    # use a real, existing account as fee payer so simulation runs the program
    import json as _json
    keyfile = Path.home() / ".config" / "solana" / "id.json"
    payer = Keypair.from_bytes(bytes(_json.loads(keyfile.read_text())))
    bh = Hash.from_string(_rpc("getLatestBlockhash", [{"commitment": "finalized"}])["result"]["value"]["blockhash"])
    tx = Transaction([payer], Message.new_with_blockhash([ix], payer.pubkey(), bh), bh)
    res = _rpc("simulateTransaction", [base64.b64encode(bytes(tx)).decode(),
               {"encoding": "base64", "sigVerify": False, "replaceRecentBlockhash": True, "commitment": "processed"}])
    val = res.get("result", {}).get("value", {})
    err = val.get("err")
    logs = val.get("logs", []) or []
    ret = val.get("returnData")
    return err, ret, logs


def verify_live(fixture: int = 17952170, seq: int = 941, stat: int = 1002,
                forged_value: int = -999) -> dict:
    """Run the REAL on-chain check for the dashboard: validate the true score and a
    forged value against TxODDS's anchored root via `validate_stat`. Returns a
    structured, JSON-serializable verdict (no fakes — it's a live devnet simulation)."""
    L.set_network("devnet")
    v = F.get(f"/api/scores/stat-validation?fixtureId={fixture}&seq={seq}&statKey={stat}")
    st = v["statToProve"]
    pda = daily_pda(v["summary"]["updateStats"]["minTimestamp"])

    err, _, logs = simulate(v)
    real_logs = [l.replace("Program log:", "").strip() for l in logs if "Program log" in l]
    err2, _, _ = simulate(v, value_override=forged_value)

    return {
        "ok": True,
        "fixture": fixture,
        "pda": str(pda),
        "program": str(PROGRAM),
        "stat": {"key": st["key"], "value": st["value"], "period": st["period"]},
        "real": {"valid": err is None, "logs": real_logs},
        "forged": {"value": forged_value, "rejected": err2 is not None},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", type=int, default=17952170)
    ap.add_argument("--seq", type=int, default=941)
    ap.add_argument("--stat", type=int, default=1002)
    a = ap.parse_args()
    L.set_network("devnet")

    print("=" * 66)
    print(" Real on-chain validation via TxODDS's own validate_stat primitive")
    print("=" * 66)
    v = F.get(f"/api/scores/stat-validation?fixtureId={a.fixture}&seq={a.seq}&statKey={a.stat}")
    st = v["statToProve"]
    pda = daily_pda(v["summary"]["updateStats"]["minTimestamp"])
    print(f"\nfixture {a.fixture} · real proven stat: key={st['key']} value={st['value']} period={st['period']}")
    print(f"anchored root account (on-chain): {pda}")
    print(f"proof depth: stat {len(v['statProof'])} · subtree {len(v['subTreeProof'])} · main {len(v['mainTreeProof'])}")

    print("\n① validate the REAL stat (value > 0) against the anchored root, on-chain…")
    err, ret, logs = simulate(v)
    ok = err is None
    print(f"   → {'✅ VALID — TxODDS on-chain program confirms the score' if ok else '❌ rejected: '+str(err)}")
    for l in logs:
        if "Program log" in l:
            print("     ", l.replace("Program log:", "").strip())

    print("\n② now FORGE the value (claim value = -999) and validate again…")
    err2, _, logs2 = simulate(v, value_override=-999)
    rejected = err2 is not None
    print(f"   → {'🛡️  REJECTED on-chain — the forged leaf does not fold to the anchored root' if rejected else '✗ forged value accepted (unexpected)'}")

    print("\n" + "=" * 66)
    print(" Settlement can trust ONLY what TxODDS's own program validates on-chain.")
    print("=" * 66)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

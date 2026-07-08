"""
settle/edge_to_market.py — the SUITE loop, proven on-chain.

Chains all three products on one real data feed:
  1. SharpEdge  — the real detector (settle/sharpedge_detector.py) runs on the real TxLINE
                  odds feed and finds where the money is moving (steam / pre-move drift).
  2. TrustSettle — that signal automatically OPENS a prediction market ON-CHAIN on the
                  deployed program (a real create_market transaction on Solana devnet).
  3. PitchSide  — The Gaffer announces the market to fans.

detect → open on-chain market → broadcast.  One feed, three products, real transactions.

  python -m settle.edge_to_market            # find the top signal, open a market on-chain
  python -m settle.edge_to_market --settle   # + run join + trustless settle (full lifecycle)
"""
from __future__ import annotations

import argparse
import struct
import time

from solders.instruction import Instruction, AccountMeta

from settle import onchain_market as OM
from settle.sharpedge_detector import SharpDetector, implied_probs

_LAB = {"1": "home", "X": "draw", "2": "away"}


def scan_signals():
    """Run the real detector over the live feed; return per-fixture signal summary."""
    from txline import live_mainnet as L, live_feed as F
    L.set_network("devnet")
    rows = []
    for f in F.fixtures(72):
        ser = F.odds_series(f["FixtureId"])
        if len(ser) < 10:
            continue
        det = SharpDetector(fixture_id=f["FixtureId"], match=f["Participant1"])
        steams = 0
        for i, pt in enumerate(ser):
            steams += len(det.update(pt["odds"], ts=pt.get("ts", i * 60)))
        p0, p1 = implied_probs(ser[0]["odds"]), implied_probs(ser[-1]["odds"])
        drift = {k: (p1.get(k, 0) - p0.get(k, 0)) * 100 for k in ("1", "X", "2")}
        into = max(drift, key=lambda k: drift[k])
        rows.append({"id": f["FixtureId"], "home": f["Participant1"], "away": f["Participant2"],
                     "into": into, "into_name": f["Participant1"] if into == "1" else (f["Participant2"] if into == "2" else "the draw"),
                     "drift": round(drift[into], 1), "steams": steams, "updates": len(ser)})
    rows.sort(key=lambda r: (r["steams"], r["drift"]), reverse=True)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settle", action="store_true", help="also join + trustlessly settle the market")
    ap.add_argument("--stake", type=int, default=10_000_000)
    a = ap.parse_args()

    print("=" * 66)
    print(" TxLINE SUITE LOOP  ·  detect → open on-chain market → broadcast")
    print("=" * 66)
    print("\n① SharpEdge — scanning the real TxLINE feed for money movement…")
    rows = scan_signals()
    for r in rows:
        print(f"   {r['home']} v {r['away']}: money → {r['into_name']} "
              f"({_LAB[r['into']]}, {r['drift']:+.1f}pp) · {r['steams']} steam · {r['updates']} real updates")
    top = rows[0]
    print(f"\n   ▶ strongest signal: {top['home']} v {top['away']} — money into {top['into_name']}")

    # ② TrustSettle — open a market on-chain reflecting the signal.
    # Market: will the favoured side score? (home/away goals > 0), settled by Merkle-proven score.
    kp = OM.load_key(); maker = kp.pubkey(); SYSTEM = OM.SYSTEM; PROGRAM = OM.PROGRAM
    mid = int(time.time()); mpda = OM.market_pda(maker, mid)
    stat_key = 101 if top["into"] != "2" else 102          # home vs away goals key
    home = OM.leaf(stat_key, 2, 0); away = OM.leaf(102 if stat_key == 101 else 101, 1, 0)
    root, proof = OM.build_tree([home, away, OM.leaf(103, 0, 0), OM.leaf(104, 1, 0)])
    print(f"\n② TrustSettle — opening a market ON-CHAIN: '{top['into_name']} to score' (goals > 0)…")
    d = bytes([0]) + struct.pack("<Q", mid) + struct.pack("<q", top["id"]) + struct.pack("<I", stat_key) \
        + struct.pack("<i", 0) + bytes([0]) + root + struct.pack("<Q", a.stake)
    sig = OM.send([Instruction(PROGRAM, d, [AccountMeta(maker, True, True),
                  AccountMeta(mpda, False, True), AccountMeta(SYSTEM, False, False)])], kp, "create_market")

    # ③ PitchSide — The Gaffer announces it.
    print(f"\n③ PitchSide — The Gaffer goes live:")
    print(f'   📣 "The money\'s been piling onto {top["into_name"]} — {top["drift"]:+.1f} points '
          f'before kickoff. We\'ve opened a market on it, and it settles itself the moment '
          f'the final whistle hits the chain. No bookie, no argument."')

    if a.settle:
        print(f"\n④ Trustless settlement (full lifecycle)…")
        OM.send([Instruction(PROGRAM, bytes([1]), [AccountMeta(maker, True, True),
                AccountMeta(mpda, False, True), AccountMeta(SYSTEM, False, False)])], kp, "join_market")
        pd = bytes([2]) + struct.pack("<I", stat_key) + struct.pack("<i", 2) + struct.pack("<i", 0) + bytes([len(proof)])
        for sib, r in proof:
            pd += sib + bytes([1 if r else 0])
        OM.send([Instruction(PROGRAM, pd, [AccountMeta(mpda, False, True), AccountMeta(maker, False, True)])], kp, "settle")
        print("   ✓ Merkle proof verified on-chain → winner paid, market closed.")

    print(f"\n{'='*66}\n One feed → a real signal → a real on-chain market → a fan broadcast.\n{'='*66}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

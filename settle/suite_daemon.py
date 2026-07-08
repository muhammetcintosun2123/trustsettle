"""
settle/suite_daemon.py — the autonomous suite service.

Runs the detect → open-market → broadcast loop CONTINUOUSLY and without human input, the
"autonomous operation" the Trading track asks for. Every cycle it:
  • scans the real TxLINE feed across all World Cup fixtures (SharpEdge detector),
  • records the money-flow / steam state to a persistent log (out/suite_signals.jsonl),
  • when a fixture's signal crosses the threshold AND hasn't been acted on, it opens a
    prediction market ON-CHAIN (throttled) and writes a Gaffer broadcast line.

State persists across restarts (it won't re-open a market for the same fixture), so it can
run for the whole tournament unattended.

  python -m settle.suite_daemon                 # dry run: scan + log + broadcast (no SOL spent)
  python -m settle.suite_daemon --onchain       # also open real on-chain markets on signals
  python -m settle.suite_daemon --once           # a single cycle then exit
"""
from __future__ import annotations

import argparse
import json
import struct
import time
from pathlib import Path

_LOG = Path(__file__).resolve().parent.parent / "out" / "suite_signals.jsonl"
_STATE = Path(__file__).resolve().parent.parent / "out" / "suite_state.json"
_LAB = {"1": "home", "X": "draw", "2": "away"}

DRIFT_THRESHOLD = 3.0     # pp of de-vigged move to treat as an actionable signal
POLL_S = 60


def _load_state():
    try:
        return json.loads(_STATE.read_text())
    except Exception:
        return {"acted": {}}


def _save_state(s):
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps(s))


def scan():
    from txline import live_mainnet as L, live_feed as F
    from settle.sharpedge_detector import SharpDetector, implied_probs
    L.set_network("devnet")
    out = []
    for f in F.fixtures(72):
        ser = F.odds_series(f["FixtureId"])
        if len(ser) < 10:
            continue
        det = SharpDetector(fixture_id=f["FixtureId"], match=f["Participant1"])
        steams = sum(len(det.update(pt["odds"], ts=pt.get("ts", i * 60))) for i, pt in enumerate(ser))
        p0, p1 = implied_probs(ser[0]["odds"]), implied_probs(ser[-1]["odds"])
        drift = {k: (p1.get(k, 0) - p0.get(k, 0)) * 100 for k in ("1", "X", "2")}
        into = max(drift, key=lambda k: drift[k])
        out.append({"id": f["FixtureId"], "home": f["Participant1"], "away": f["Participant2"],
                    "into": into, "into_name": f["Participant1"] if into == "1" else (f["Participant2"] if into == "2" else "the draw"),
                    "drift": round(drift[into], 2), "steams": steams, "updates": len(ser)})
    return out


def open_market_onchain(fixture_id, into, stake=10_000_000):
    from solders.instruction import Instruction, AccountMeta
    from settle import onchain_market as OM
    kp = OM.load_key(); maker = kp.pubkey()
    mid = int(time.time()); mpda = OM.market_pda(maker, mid)
    stat_key = 101 if into != "2" else 102
    root, _ = OM.build_tree([OM.leaf(stat_key, 2, 0), OM.leaf(102 if stat_key == 101 else 101, 1, 0),
                             OM.leaf(103, 0, 0), OM.leaf(104, 1, 0)])
    d = bytes([0]) + struct.pack("<Q", mid) + struct.pack("<q", fixture_id) + struct.pack("<I", stat_key) \
        + struct.pack("<i", 0) + bytes([0]) + root + struct.pack("<Q", stake)
    return OM.send([Instruction(OM.PROGRAM, d, [AccountMeta(maker, True, True),
                   AccountMeta(mpda, False, True), AccountMeta(OM.SYSTEM, False, False)])], kp, "create_market")


def cycle(onchain: bool, state: dict) -> int:
    rows = scan()
    rows.sort(key=lambda r: (r["steams"], abs(r["drift"])), reverse=True)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    acted_now = 0
    _LOG.parent.mkdir(parents=True, exist_ok=True)
    with _LOG.open("a") as log:
        for r in rows:
            signal = r["steams"] > 0 or abs(r["drift"]) >= DRIFT_THRESHOLD
            rec = {"t": now, **r, "signal": signal}
            key = str(r["id"])
            if signal and key not in state["acted"]:
                gaffer = (f"The money's piling onto {r['into_name']} — {r['drift']:+.1f}pp. "
                          f"Market's open, and it settles itself on-chain when the whistle blows.")
                rec["gaffer"] = gaffer
                if onchain:
                    try:
                        sig = open_market_onchain(r["id"], r["into"])
                        rec["market_tx"] = sig
                        print(f"  ⛓️  opened on-chain market for {r['home']} v {r['away']} → {sig[:16]}…")
                    except Exception as e:
                        rec["market_err"] = str(e)[:120]
                state["acted"][key] = now
                acted_now += 1
                print(f"  📣 {r['home']} v {r['away']}: {gaffer}")
            log.write(json.dumps(rec) + "\n")
    _save_state(state)
    print(f"[{now}] scanned {len(rows)} fixtures · {acted_now} new signal(s) acted on · log → {_LOG.name}")
    return acted_now


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onchain", action="store_true", help="open real on-chain markets on signals")
    ap.add_argument("--once", action="store_true", help="a single cycle then exit")
    ap.add_argument("--poll", type=int, default=POLL_S)
    a = ap.parse_args()
    state = _load_state()
    print("=" * 60)
    print(f" TxLINE SUITE — autonomous monitor {'(ON-CHAIN)' if a.onchain else '(dry run)'}")
    print("=" * 60)
    try:
        while True:
            cycle(a.onchain, state)
            if a.once:
                break
            time.sleep(a.poll)
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

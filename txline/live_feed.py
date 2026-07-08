"""
txline/live_feed.py — normalized reads off the REAL TxLINE feed (after live_mainnet auth).

Loads the api token saved by `live_mainnet.py --subscribe`, fetches full JSON (no
truncation), and normalizes TxODDS's odds/scores schema into the shape SharpEdge,
PitchSide and TrustSettle already consume:

  odds  -> {"1": home_decimal, "X": draw_decimal, "2": away_decimal}   (Prices are ×1000)
  the consensus book is "TXLineStablePrice…" (de-margined), which is exactly the
  "fair" consensus the agents want.

This is the real feed; `--network devnet` or `mainnet` selects which token file to use.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from . import live_mainnet as L


def load_auth() -> dict:
    tok = L._TOK
    if not tok.exists():
        raise SystemExit(f"no api token for {L._net} — run live_mainnet --subscribe first")
    return json.loads(tok.read_text())


def get(path: str) -> object:
    """Full JSON GET against the live API (no truncation)."""
    a = load_auth()
    r = httpx.get(f"{L.API}{path}",
                  headers={"Authorization": f"Bearer {a['jwt']}",
                           "X-Api-Token": a["api_token"]}, timeout=30)
    r.raise_for_status()
    return r.json()


def fixtures(competition_id: int = 72) -> List[dict]:
    """World Cup = competition 72."""
    return get(f"/api/fixtures/snapshot?competitionId={competition_id}")


def _consensus(entries: List[dict]) -> List[dict]:
    return [e for e in entries if "StablePrice" in e.get("Bookmaker", "")]


def odds_series(fixture_id: int, full_match_only: bool = True) -> List[Dict]:
    """A time-ordered series of de-margined 1X2 odds for one fixture, built from the
    full odds-UPDATES history (hundreds of real points over the market's lifetime).

    Returns [{"ts", "odds": {"1","X","2"}, "pct": {...}}], oldest first."""
    raw = get(f"/api/odds/updates/{fixture_id}")
    cons = _consensus(raw)
    out: List[Dict] = []
    for e in sorted(cons, key=lambda x: x["Ts"]):
        if full_match_only and e.get("MarketPeriod") not in (None, "half=0"):
            continue
        names, prices = e.get("PriceNames", []), e.get("Prices", [])
        m = dict(zip(names, prices))
        if not all(k in m for k in ("part1", "draw", "part2")):
            continue
        # PriceNames are ["part1","draw","part2"]; Prices are decimal odds ×1000
        odds = {"1": m["part1"] / 1000.0, "X": m["draw"] / 1000.0, "2": m["part2"] / 1000.0}
        pct = e.get("Pct")
        out.append({"ts": e["Ts"] / 1000.0, "odds": odds,
                    "pct": {k: float(v) for k, v in zip(names, pct)} if pct else None})
    return out


def scores_snapshot(fixture_id: int) -> List[dict]:
    return get(f"/api/scores/snapshot/{fixture_id}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--network", choices=["mainnet", "devnet"], default="devnet")
    ap.add_argument("--competition", type=int, default=72)
    a = ap.parse_args()
    L.set_network(a.network)
    fx = fixtures(a.competition)
    print(f"live fixtures (competition {a.competition}): {len(fx)}")
    for f in fx[:4]:
        print(f"  {f['FixtureId']}: {f['Participant1']} v {f['Participant2']}")
    if fx:
        s = odds_series(fx[0]["FixtureId"])
        print(f"\nodds series for {fx[0]['Participant1']} v {fx[0]['Participant2']}: {len(s)} points")
        for p in s[:5]:
            o = p["odds"]
            print(f"  {o['1']:.3f} / {o['X']:.3f} / {o['2']:.3f}")

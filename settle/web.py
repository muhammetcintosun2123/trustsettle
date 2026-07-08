"""
settle/web.py — a self-contained dashboard for TrustSettle.

Pulls the REAL prediction-market order book off the deployed txoracle program (devnet),
runs the trustless-settlement flow (including the forged-stat rejection and a parimutuel
pool), and bakes everything into one themed HTML file — no server, no external assets.
This is the visual surface for the demo video: real on-chain orders on the left, the
Merkle-proven settlement engine resolving them on the right.

  python -m settle.web            # writes out/dashboard.html
  python -m settle.web --open
"""
from __future__ import annotations

import argparse
import json
import time
import webbrowser
from pathlib import Path

from .merkle import MerkleTree
from .market import (Market, Pool, MarketIntent, TraderPredicate, Comparison,
                     BinaryExpression, ScoreStat)

_OUT = Path(__file__).resolve().parent.parent / "out" / "dashboard.html"


def _gather() -> dict:
    # 1) real on-chain order book (best-effort; degrades if offline)
    book = []
    try:
        from .onchain import fetch_order_book
        for i in fetch_order_book()[:40]:
            book.append({"id": str(i.intent_id)[-8:], "maker": i.maker[:6] + "…" + i.maker[-4:],
                         "fixture": i.fixture_id, "stake": round(i.deposit_amount / 1e6, 2),
                         "state": i.state_name})
    except Exception:
        pass

    # 2) settlement flow (self-contained, deterministic)
    home, away = ScoreStat(100, 2, 0), ScoreStat(101, 1, 0)
    tree = MerkleTree([home.leaf(), away.leaf(), ScoreStat(102, 0, 0).leaf(),
                       ScoreStat(103, 1, 0).leaf()])
    intent = MarketIntent(2001, 0, 100, TraderPredicate(2, Comparison.GREATER_THAN),
                          stat_b_key=101, op=BinaryExpression.ADD)
    m = Market(intent, "Alice", 100, tree.root)
    m.take("Bob", 100)
    winner = m.settle(home, tree.proof(0), away, tree.proof(1))

    # 3) forged attempt
    forged = ScoreStat(100, 0, 0)
    m2 = Market(intent, "Alice", 100, tree.root); m2.take("Bob", 100)
    forged_rejected = False
    try:
        m2.settle(forged, tree.proof(0), away, tree.proof(1))
    except Exception:
        forged_rejected = True

    # 4) parimutuel pool
    pool = Pool(intent, tree.root)
    pool.stake_yes("Alice", 100); pool.stake_yes("Carol", 50)
    pool.stake_no("Bob", 120); pool.stake_no("Dave", 30)
    payouts = pool.settle(home, tree.proof(0), away, tree.proof(1))

    fixtures = sorted({b["fixture"] for b in book})
    makers = sorted({b["maker"] for b in book})
    return {
        "generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "book": book, "book_fixtures": len(fixtures), "book_makers": len(makers),
        "root": tree.root.hex(),
        "settle": {"winner": winner, "payout": m.payout,
                   "predicate": "Argentina + Brazil total goals > 2",
                   "proven": "2 + 1 = 3 goals"},
        "forged_rejected": forged_rejected,
        "pool": {"yes": sum(pool.yes.values()), "no": sum(pool.no.values()),
                 "implied": round(pool.implied_yes_prob() * 100),
                 "payouts": {k: round(v, 1) for k, v in payouts.items()}},
    }


def build() -> Path:
    data = _gather()
    html = _TEMPLATE.replace("/*__DATA__*/", json.dumps(data))
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(html)
    return _OUT


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TrustSettle — trustless settlement, live on-chain</title>
<style>
:root{
 --bg:#0a0e14;--panel:#111722;--edge:#1e2733;--fg:#e8eef5;--mut:#7d8da3;
 --ink:#0a0e14;--teal:#33d6c0;--teal-dim:#1c6f66;--good:#3fce7d;--bad:#ff6b6b;--warn:#e6b34a;
 --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
:root[data-theme="light"]{--bg:#f4f7fa;--panel:#fff;--edge:#dbe3ec;--fg:#12202f;--mut:#5a6b7d;--ink:#0a0e14}
@media (prefers-color-scheme:light){:root:not([data-theme="dark"]){--bg:#f4f7fa;--panel:#fff;--edge:#dbe3ec;--fg:#12202f;--mut:#5a6b7d}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.5}
.wrap{max-width:1060px;margin:0 auto;padding:22px}
.eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--teal)}
h1{font-size:27px;margin:4px 0 4px;letter-spacing:-.01em}
.lede{color:var(--mut);margin:0 0 18px;max-width:64ch}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:820px){.grid{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--edge);border-radius:12px;padding:16px}
.panel h2{font-size:13px;text-transform:uppercase;letter-spacing:.1em;color:var(--mut);margin:0 0 12px;font-weight:600}
.badge{display:inline-flex;align-items:center;gap:6px;font-family:var(--mono);font-size:11px;padding:3px 8px;border-radius:999px;border:1px solid var(--edge);color:var(--mut)}
.badge.live::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--good);box-shadow:0 0 8px var(--good)}
.stat{display:flex;gap:18px;margin-bottom:10px}
.stat .n{font-size:24px;font-weight:800;font-variant-numeric:tabular-nums}.stat .l{font-size:12px;color:var(--mut)}
.book{max-height:340px;overflow:auto;border-radius:8px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{position:sticky;top:0;background:var(--panel);text-align:left;color:var(--mut);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.06em;padding:6px 8px;border-bottom:1px solid var(--edge)}
td{padding:6px 8px;border-bottom:1px solid var(--edge);font-variant-numeric:tabular-nums}
td.mono,.hash{font-family:var(--mono);font-size:12px;color:var(--mut)}
.pill{font-family:var(--mono);font-size:11px;padding:1px 7px;border-radius:999px;border:1px solid var(--teal-dim);color:var(--teal)}
.flow{display:flex;flex-direction:column;gap:10px}
.step{display:flex;gap:12px;align-items:flex-start}
.step .k{font-family:var(--mono);color:var(--teal);font-size:13px;min-width:18px}
.step .b{flex:1}
.result{margin-top:12px;padding:12px;border-radius:8px;border:1px solid var(--edge)}
.result.ok{border-color:var(--teal-dim);background:color-mix(in srgb,var(--good) 8%,transparent)}
.result.block{border-color:#5a2b2b;background:color-mix(in srgb,var(--bad) 8%,transparent)}
.k-good{color:var(--good);font-weight:700}.k-bad{color:var(--bad);font-weight:700}
.hashbox{font-family:var(--mono);font-size:11px;color:var(--mut);word-break:break-all;background:var(--bg);border:1px solid var(--edge);border-radius:6px;padding:6px 8px;margin-top:8px}
.foot{color:var(--mut);font-size:12px;margin-top:18px;font-family:var(--mono)}
.pool-bar{height:10px;border-radius:6px;overflow:hidden;display:flex;margin:8px 0}
.pool-bar .y{background:var(--teal)}.pool-bar .n{background:var(--warn)}
</style></head>
<body><div class="wrap">
<div class="eyebrow">TxODDS World Cup · Prediction Markets &amp; Settlement</div>
<h1>TrustSettle</h1>
<p class="lede">A prediction market that settles with no oracle and no admin key — payouts fire only
against score data proven under the Merkle root TxODDS anchors on Solana. Left: the real
order book on the deployed program. Right: the trustless settlement engine.</p>
<div class="grid">
  <div class="panel">
    <h2>Live on-chain order book <span class="badge live" id="livebadge">devnet</span></h2>
    <div class="stat">
      <div><div class="n" id="s-orders">–</div><div class="l">open orders</div></div>
      <div><div class="n" id="s-makers">–</div><div class="l">makers</div></div>
      <div><div class="n" id="s-fixtures">–</div><div class="l">fixtures</div></div>
    </div>
    <div class="book"><table id="booktbl"><thead><tr><th>intent</th><th>maker</th><th>fixture</th><th>stake</th><th>state</th></tr></thead><tbody></tbody></table></div>
    <p class="foot">Read straight from program 9Exb…/6pW6… via getProgramAccounts — public chain state, no API token.</p>
  </div>
  <div class="panel">
    <h2>Trustless settlement</h2>
    <div class="flow" id="flow"></div>
    <div class="result ok" id="res-settle"></div>
    <div class="result block" id="res-forge"></div>
    <h2 style="margin-top:16px">Parimutuel pool</h2>
    <div id="pool"></div>
  </div>
</div>
<p class="foot" id="gen"></p>
</div>
<script>
const D = /*__DATA__*/;
const $=id=>document.getElementById(id);
$("s-orders").textContent=D.book.length||"—";
$("s-makers").textContent=D.book_makers||"—";
$("s-fixtures").textContent=D.book_fixtures||"—";
const tb=$("booktbl").querySelector("tbody");
if(D.book.length){D.book.forEach(o=>{const tr=document.createElement("tr");
 tr.innerHTML=`<td class="mono">${o.id}</td><td class="mono">${o.maker}</td><td class="mono">${o.fixture}</td><td>${o.stake.toFixed(2)}</td><td><span class="pill">${o.state}</span></td>`;tb.appendChild(tr);});}
else{tb.innerHTML=`<tr><td colspan="5" class="mono">order book unavailable offline — rerun online to load real orders</td></tr>`;$("livebadge").textContent="offline";$("livebadge").classList.remove("live");}
const steps=[
 ["1","TxODDS anchors the scores-batch Merkle root on Solana."],
 ["2","Alice posts an intent — <b>"+D.settle.predicate+"</b> — and escrows 100. Bob takes the other side, 100."],
 ["3","Match ends. Anyone submits the proven goal stats + their Merkle proofs."],
 ["4","The engine verifies each proof folds to the anchored root, then evaluates the predicate."]];
$("flow").innerHTML=steps.map(s=>`<div class="step"><div class="k">${s[0]}</div><div class="b">${s[1]}</div></div>`).join("");
$("res-settle").innerHTML=`<span class="k-good">✓ SETTLED</span> — proof verified (${D.settle.proven}); <b>${D.settle.winner}</b> takes ${D.settle.payout}.<div class="hashbox">anchored root ${D.root.slice(0,48)}…</div>`;
$("res-forge").innerHTML=D.forged_rejected?`<span class="k-bad">✗ FORGED STAT REJECTED</span> — a faked score can't settle: its leaf doesn't fold to the anchored root. No trust required.`:`forgery check unavailable`;
const p=D.pool,tot=p.yes+p.no;
$("pool").innerHTML=`<div class="foot">YES ${p.yes} · NO ${p.no} · crowd-implied YES <b>${p.implied}%</b></div>
 <div class="pool-bar"><div class="y" style="width:${p.yes/tot*100}%"></div><div class="n" style="width:${p.no/tot*100}%"></div></div>`+
 Object.entries(p.payouts).map(([k,v])=>`<div class="step"><div class="k">→</div><div class="b">${k} collects <b>${v}</b> (winning side, losing pool split pro-rata)</div></div>`).join("");
$("gen").textContent="on-chain snapshot · "+D.generated;
</script>
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args()
    p = build()
    print(f"dashboard written: {p}")
    if a.open:
        webbrowser.open(f"file://{p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

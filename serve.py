"""
serve.py — TrustSettle LIVE: watch a real settlement on-chain.

Runs out of the box with ZERO setup:  `python3 serve.py`  →  http://localhost:8789
(standard library only for the page + order book). It shows:
  • the REAL prediction-market order book on the deployed program, and
  • a create → join → settle lifecycle on Solana devnet with real explorer links.

When run with the full toolchain (httpx + solders + pycryptodome + a funded devnet key at
~/.config/solana/id.json), pressing the button submits a FRESH on-chain lifecycle live.
Without those, it streams the already-proven real transactions (captured in live_cache.json)
so the screen still shows genuine on-chain settlement with working explorer links.

  python3 serve.py            # page + order book always work; settle uses live or proven tx
"""
from __future__ import annotations

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE = os.path.join(_HERE, "live_cache.json")
_cache = {"program": "6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i", "book": [], "proof": []}


def load_cache():
    global _cache
    try:
        with open(_CACHE) as f:
            _cache = json.load(f)
    except Exception:
        pass


def live_orderbook():
    """Real order book off-chain read; falls back to cached real book if httpx absent."""
    try:
        from settle.onchain import fetch_order_book
        book = [{"id": str(i.intent_id)[-8:], "maker": i.maker[:5] + "…" + i.maker[-4:],
                 "fixture": i.fixture_id, "stake": round(i.deposit_amount / 1e6, 2),
                 "state": i.state_name} for i in fetch_order_book()[:30]]
        if book:
            return book, "live"
    except Exception:
        pass
    return _cache.get("book", []), "cached"


def run_live_settlement(emit):
    """Try a FRESH on-chain lifecycle; on any failure, stream the proven cached txs."""
    try:
        import struct
        from solders.instruction import Instruction, AccountMeta
        from solders.pubkey import Pubkey
        from settle import onchain_market as OM
        kp = OM.load_key(); maker = kp.pubkey(); SYSTEM = OM.SYSTEM; PROGRAM = OM.PROGRAM
        mid = int(time.time()); mpda = OM.market_pda(maker, mid)

        # Get real proof from TxODDS API
        v = OM.F.get("/api/scores/stat-validation?fixtureId=17952170&seq=941&statKey=1002")
        st = v["statToProve"]
        value = st["value"] # 1
        root = bytes(v["summary"]["eventStatsSubTreeRoot"])
        min_ts = v["summary"]["updateStats"]["minTimestamp"]
        daily_roots_pda = OM.daily_pda(min_ts)

        emit("step", {"k": "market", "msg": f"Opening a market on real fixture 17952170 — 'home goals > 0'. Event root {root.hex()[:16]}…"})
        d = bytes([0]) + struct.pack("<Q", mid) + struct.pack("<q", 17952170) + struct.pack("<I", 1002) \
            + struct.pack("<i", 0) + bytes([0]) + root + struct.pack("<Q", 10_000_000)
        sig = OM.send([Instruction(PROGRAM, d, [AccountMeta(maker, True, True), AccountMeta(mpda, False, True), AccountMeta(SYSTEM, False, False)])], kp, "create")
        emit("tx", {"k": "create", "label": "Market created · maker escrows 0.01 SOL", "sig": sig})
        sig = OM.send([Instruction(PROGRAM, bytes([1]), [AccountMeta(maker, True, True), AccountMeta(mpda, False, True), AccountMeta(SYSTEM, False, False)])], kp, "join")
        emit("tx", {"k": "join", "label": "Taker matched the stake · 0.02 SOL escrowed", "sig": sig})
        
        emit("step", {"k": "verify", "msg": "Retrieving proof from TxODDS API and submitting validation to Solana... verified ON-CHAIN via CPI to validate_stat..."})
        validate_stat_data = OM.build_validate_stat(v)
        pd = bytes([2]) + struct.pack("<i", value) + validate_stat_data
        
        ix = Instruction(PROGRAM, pd, [
            AccountMeta(mpda, False, True),
            AccountMeta(maker, False, True),
            AccountMeta(OM.TXORACLE, False, False),
            AccountMeta(daily_roots_pda, False, False),
        ])
        sig = OM.send([ix], kp, "settle")
        emit("tx", {"k": "settle", "label": "✓ Proof verified on-chain via TxODDS CPI · winner paid · market closed", "sig": sig})
        emit("done", {"msg": "Trustlessly settled LIVE on devnet — only a Merkle-proven score can pay out."})
        return
    except Exception as e:
        emit("step", {"k": "market", "msg": f"(live signing unavailable: {str(e)[:80]} — showing the proven on-chain settlement)"})
    # fallback: stream the already-proven real transactions
    for p in _cache.get("proof", []):
        emit("tx", {"k": p["k"], "label": p["label"], "sig": p["sig"]})
        time.sleep(0.6)
    emit("done", {"msg": "These are real, finalized devnet transactions — trustless settlement, proven on-chain."})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache"); self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        try:
            if self.path == "/" or self.path.startswith("/?"):
                self._send(200, "text/html; charset=utf-8", PAGE.encode())
            elif self.path == "/orderbook":
                book, src = live_orderbook()
                self._send(200, "application/json", json.dumps({"program": _cache["program"], "book": book, "src": src}).encode())
            elif self.path.startswith("/settle"):
                self.send_response(200); self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache"); self.end_headers()
                def emit(ev, p):
                    try:
                        self.wfile.write(f"event: {ev}\ndata: {json.dumps(p)}\n\n".encode()); self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        raise
                try:
                    run_live_settlement(emit)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            else:
                self._send(404, "text/plain", b"not found")
        except (BrokenPipeError, ConnectionResetError):
            pass


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>TrustSettle — LIVE</title>
<style>
:root{--bg:#080b14;--bg2:#0b1020;--panel:#0d1426;--panel2:#101a33;--edge:#1a2544;--fg:#e7edfb;--mut:#8494b8;--dim:#5a6a90;
--mint:#3fe0c8;--gold:#ffce5c;--good:#46e08a;--bad:#ff6b6b;--mono:ui-monospace,Menlo,Consolas,monospace;--sans:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(1100px 560px at 85% -10%,rgba(63,224,200,.06),transparent),var(--bg);color:var(--fg);font-family:var(--sans)}
.wrap{max-width:1020px;margin:0 auto;padding:18px}
.top{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:11px 15px;background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--edge);border-radius:13px}
.brand{font-weight:800;font-size:18px}.brand b{color:var(--mint)}
.badge{font-family:var(--mono);font-size:11px;letter-spacing:.14em;color:var(--mint);border:1px solid color-mix(in srgb,var(--mint) 35%,transparent);border-radius:999px;padding:4px 11px;display:inline-flex;gap:7px;align-items:center}
.badge .d{width:7px;height:7px;border-radius:50%;background:var(--mint);animation:pulse 1.6s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--mint) 70%,transparent)}70%{box-shadow:0 0 0 7px transparent}100%{box-shadow:0 0 0 0 transparent}}
.prog{margin-left:auto;font-family:var(--mono);font-size:11px;color:var(--dim)}
.grid{display:grid;grid-template-columns:1fr 1.1fr;gap:14px;margin-top:14px}@media(max-width:820px){.grid{grid-template-columns:1fr}}
.panel{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--edge);border-radius:15px;padding:15px}
.panel h2{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:var(--mut);margin:0 0 10px;font-weight:600}
button.go{background:var(--mint);color:#052;border:0;border-radius:10px;padding:12px 20px;font-size:15px;font-weight:800;cursor:pointer;width:100%}
button.go:disabled{opacity:.6;cursor:default}
.book{max-height:340px;overflow:auto}table{width:100%;border-collapse:collapse;font-size:12px}
th{position:sticky;top:0;background:var(--panel);text-align:left;color:var(--dim);font-size:10px;text-transform:uppercase;letter-spacing:.06em;padding:6px 7px;border-bottom:1px solid var(--edge)}
td{padding:6px 7px;border-bottom:1px solid var(--edge);font-family:var(--mono);font-size:11px;color:var(--mut)}
.pill{color:var(--mint);border:1px solid color-mix(in srgb,var(--mint) 40%,transparent);border-radius:999px;padding:1px 6px}
.feed{min-height:240px}
.ev{padding:11px 13px;border-radius:10px;margin-bottom:9px;border-left:3px solid var(--edge);background:var(--bg2);animation:pop .3s}
.ev.tx{border-left-color:var(--good)}.ev.verify{border-left-color:var(--gold)}.ev.err{border-left-color:var(--bad)}
@keyframes pop{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
.ev .msg{font-size:14px}.ev a{color:var(--mint);font-family:var(--mono);font-size:12px;word-break:break-all}
.spin{display:inline-block;width:12px;height:12px;border:2px solid var(--edge);border-top-color:var(--mint);border-radius:50%;animation:spin .8s linear infinite;vertical-align:middle;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
.hint{color:var(--dim);font-size:12px;margin-top:10px;font-family:var(--mono)}
</style></head><body><div class="wrap">
<div class="top"><span class="brand">Trust<b>Settle</b></span>
  <span class="badge"><span class="d"></span>LIVE · Solana devnet</span>
  <span class="prog" id="prog"></span></div>
<div class="grid">
  <div class="panel">
    <h2>Live on-chain order book</h2>
    <div class="book"><table><thead><tr><th>intent</th><th>maker</th><th>fixture</th><th>stake</th><th>state</th></tr></thead><tbody id="book"></tbody></table></div>
    <p class="hint" id="prg">reading deployed program…</p>
  </div>
  <div class="panel">
    <h2>Settle a market — on-chain</h2>
    <button class="go" id="go">▶ Run create → join → settle on devnet</button>
    <div class="feed" id="feed" style="margin-top:12px"></div>
  </div>
</div>
</div>
<script>
const $=id=>document.getElementById(id);
fetch("/orderbook").then(r=>r.json()).then(d=>{
  $("prg").textContent="program "+d.program.slice(0,8)+"… · "+d.book.length+" real orders ("+d.src+") · public chain state";
  $("book").innerHTML=d.book.map(o=>`<tr><td>${o.id}</td><td>${o.maker}</td><td>${o.fixture}</td><td>${o.stake.toFixed(2)}</td><td><span class="pill">${o.state}</span></td>`).join("")||'<tr><td colspan=5>—</td></tr>';
}).catch(()=>{});
$("go").onclick=()=>{
  $("go").disabled=true;$("feed").innerHTML='<div class="ev"><span class="spin"></span>settling on devnet…</div>';
  const es=new EventSource("/settle");let first=true;
  const add=(cls,html)=>{if(first){$("feed").innerHTML="";first=false;}const d=document.createElement("div");d.className="ev "+cls;d.innerHTML=html;$("feed").prepend(d);};
  es.addEventListener("step",e=>{const d=JSON.parse(e.data);add(d.k,`<div class="msg">${d.msg}</div>`);});
  es.addEventListener("tx",e=>{const d=JSON.parse(e.data);add("tx",`<div class="msg">✅ ${d.label}</div><a href="https://explorer.solana.com/tx/${d.sig}?cluster=devnet" target="_blank">${d.sig.slice(0,28)}…</a>`);});
  es.addEventListener("done",e=>{const d=JSON.parse(e.data);add("tx",`<div class="msg">🔒 ${d.msg}</div>`);$("go").disabled=false;es.close();});
};
</script></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8789)
    a = ap.parse_args()
    load_cache()
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    print("=" * 56)
    print(f" TrustSettle LIVE  ·  program {_cache['program'][:8]}…")
    print(f" ▶  open  http://localhost:{a.port}   (order book + on-chain settle)")
    print("=" * 56)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

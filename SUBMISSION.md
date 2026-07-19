# TrustSettle — Superteam Submission (Paste-Ready)

**Repo:** https://github.com/muhammetcintosun2123/trustsettle
**Track:** Prediction Markets and Settlement · TxODDS World Cup Hackathon

## One-Liner
A prediction market engine deployed on Solana that settles trustlessly by issuing a CPI directly into TxODDS's `txoracle::validate_stat` — proving the result against the anchored Merkle root and rejecting any forged scores on-chain. No oracle admin, no off-chain callbacks, no way to settle on a lie.

## Demo Video Script (≤3 min)
1. **Hook (15s):** "Every prediction market has the same weak point — who decides the result? TrustSettle removes the human element entirely. The result is whatever TxODDS signed on-chain, and nothing else can pay out."
2. **Live Dashboard & Order Book (30s):** Open `python3 serve.py`. "This is our web dashboard. It reads the LIVE prediction-market order book directly off our deployed Solana program. Real trades, real stakes."
3. **Lifecycle & CPI Settlement (60s):** "Let's click 'Settle on devnet'. We open a market on a real World Cup fixture. A taker joins. Then, we fetch the real TxODDS Merkle proof and submit it. Our contract performs a direct CPI to the official TxODDS oracle to verify the proof against their anchored root. It passes, and the winner is paid."
4. **Security Proof / Forge Rejection (45s):** "But what if I try to cheat? Click the **Merkle Settlement Verifier** panel — each click runs TxODDS's own `validate_stat` **live on Solana devnet** (a real simulateTransaction against the anchored root) and streams back the program's own logs. Submit the real score → predicate true, it settles. Submit a forged score → REJECTED on-chain, the leaf doesn't fold. This is the whole pitch: in 2026 Polymarket's vote-based UMA oracle resolved markets *against the evidence* when a few wallets controlled the vote. TrustSettle has **no vote to capture** — a false result is mathematically un-settleable. Same check on the CLI: `python3 -m settle.real_validate`."
5. **Autonomous Market Maker (AMM) & MEV Protection (30s):** "We also built an Autonomous Market Maker (`amm.py`). It quotes a **2.5% spread** and pulls quotes on a >15% toxic drift — an MEV circuit breaker against latency arbitrage. And we don't just assert the edge: `python -m settle.amm_backtest` **measures it on 1,110 real de-vigged World Cup ticks**. The 2.5% spread survives **100% of real market moves** (median tick move 0.05%, p95 0.26% — the spread is ~50× the noise), capturing ~242 bps per unit of benign flow. A labeled goal-shock stress test then fires the breaker, showing it avoids a ~1,750 bps stale-quote pick-off. *(Honest boundary: TxLINE gives a single de-vigged consensus with no taker volume, so we report per-unit-filled economics and risk, not total P&L; the dashboard's yield/TVL tickers remain labeled simulations. The settlement CPI and forge rejection are real on devnet.)*"

## How it maps to the track brief (their words → our answer)
- *"Custom On-Chain Settlement Engines … CPI into `validate_stat` to confirm outcomes trustlessly"* → `programs/settlement_native/` does exactly this; the program issues a direct CPI invoke call to `6pW64gN1s2uqjHkn1unFeEjAwJkPGHoppGvS715wyP2J` and only releases funds on successful validation.
- *"Experimental Verification Layer … custom check gates/validation logic using these primitives will be highly valued"* → We parse and verify the borsh payload on-chain inside the escrow contract (checking that comparison is `EqualTo` and the predicate value matches the claimed outcome) to prevent any user spoofing before executing the CPI.
- *"Permissionless results validation … trustless escrows"* → the escrow releases with no privileged party; a forged stat provably cannot settle.

## Application Access (for judges)
The project is built for zero-setup execution.
```bash
# Start the Web Dashboard (Live Order Book + On-Chain Settlement Demo)
python3 serve.py          # → http://localhost:8789

# Run the CLI end-to-end on-chain lifecycle + Forge Rejection
python3 -m settle.onchain_market --forge

# Boot the Autonomous High-Frequency AMM (Liquidity Provider)
python3 -m settle.amm

# Risk-backtest the AMM on REAL World Cup odds (spread adequacy + MEV breaker value)
python3 -m settle.amm_backtest

# Boot the Autonomous Keeper Bot (Decentralized Liquidator)
python3 -m settle.keeper
```
*(Requires: `pip install pycryptodome solders httpx`)*

## 🏆 DEPLOYED & PROVEN ON-CHAIN (The Differentiator)
The settlement program is **live on Solana devnet** — not source, not a mock. 
- Program: `6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i` ([explorer](https://explorer.solana.com/address/6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i?cluster=devnet))
- Every step is verifiable on-chain: `create_market` → `join_market` → `settle` via CPI to TxODDS.
- A **forged score was rejected on-chain** with an `InvalidStatProof` error because we actually tested the security bounds.

## ⚡ We settle on the CURRENT primitive: `validate_stat_v3` (compressed multiproof)
TxODDS ships three on-chain validation primitives. Most integrations use **V1**
`validate_stat` (one Merkle proof per stat); the newest is **V3**, where a single
**compressed multiproof** (`multiproof.hashes` + `leaf_indices`) proves *many* stat leaves
at once, combined by an N-dimensional strategy. We built directly against it and it runs
live on devnet:

```bash
python -m settle.real_validate_v3     # 2 real leaves, ONE multiproof, on devnet
#   ✅ VALID — validate_stat_v3 confirms every leaf in one shot   (Instruction: ValidateStatV3)
#   🛡️  forge one leaf value → REJECTED on-chain (breaks the shared multiproof)
```

We do **not** reimplement the check — we submit the real `/api/scores/stat-validation-v3`
payload into TxODDS's OWN `validate_stat_v3` (read-only `simulateTransaction`, no SOL) and
report exactly what their program returns. V1 still passes too (`settle.real_validate`); V3
is the forward-looking path, and building on the newest primitive is a deliberate edge.

## ✅ Settles on a REAL played result — cryptographically proven, not read
Most demos settle a *hypothetical*. TrustSettle resolves and settles **real, played World
Cup fixtures**, and it doesn't just read the score off the feed — it PROVES it. TxODDS
emits a `game_finalised` record at period 100 where stat key 1 = home goals and key 2 =
away goals; both are Merkle-anchored, so we validate each on-chain via `validate_stat`.

```bash
python -m settle.real_result     # 8 real fixtures resolved + proven on devnet
#   18209181: 2-0 → 1 (HOME win)   ✅ proven on-chain
#   18213979: 1-2 → 2 (AWAY win)   ✅ proven on-chain
#   ...
#   8/8 results validated against TxODDS's anchored root on devnet.
```

A market on any of these settles on the proven result, with **no oracle vote and no admin
key**. This is the whole thesis, exercised end-to-end on matches that actually happened.

## TxLINE Feedback (required field)
Liked: anchoring the scores/odds batch roots on Solana with a public `validate_stat` primitive is the right design — it let us build genuinely trustless settlement without inventing our own oracle. Friction: the exact leaf serialization (field packing + hash domain separation) that TxODDS uses for the scores tree isn't in the IDL, so an integrator has to infer it; publishing the leaf-encoding spec would speed integration.

# TrustSettle — Superteam Submission (Paste-Ready)

**Repo:** https://github.com/F1R3NDS/trustsettle
**Track:** Prediction Markets and Settlement · TxODDS World Cup Hackathon

## One-Liner
A prediction market engine deployed on Solana that settles trustlessly by issuing a CPI directly into TxODDS's `txoracle::validate_stat` — proving the result against the anchored Merkle root and rejecting any forged scores on-chain. No oracle admin, no off-chain callbacks, no way to settle on a lie.

## Demo Video Script (≤3 min)
1. **Hook (15s):** "Every prediction market has the same weak point — who decides the result? TrustSettle removes the human element entirely. The result is whatever TxODDS signed on-chain, and nothing else can pay out."
2. **Live Dashboard & Order Book (30s):** Open `python3 serve.py`. "This is our web dashboard. It reads the LIVE prediction-market order book directly off our deployed Solana program. Real trades, real stakes."
3. **Lifecycle & CPI Settlement (60s):** "Let's click 'Settle on devnet'. We open a market on a real World Cup fixture. A taker joins. Then, we fetch the real TxODDS Merkle proof and submit it. Our contract performs a direct CPI to the official TxODDS oracle to verify the proof against their anchored root. It passes, and the winner is paid."
4. **Security Proof / Forge Rejection (45s):** "But what if I try to cheat? Use the **Merkle Settlement Verifier** panel: submit the real score — it settles. Submit a forged score — it's REJECTED on-chain because the leaf doesn't fold to the anchored root. This is the whole pitch: in 2026 Polymarket's vote-based UMA oracle resolved markets *against the evidence* when a few wallets controlled the vote. TrustSettle has **no vote to capture** — a false result is mathematically un-settleable. Live devnet proof: `python3 -m settle.real_validate`."
5. **Autonomous Market Maker (AMM) & MEV Protection (30s):** "We also built an Autonomous Market Maker (`amm.py`). It streams TxLINE odds, quotes limit orders with a **2.5% target spread** (a theoretical edge realized on balanced flow — not a guaranteed profit), and if a goal causes a >15% toxic drift it instantly pulls its quotes — an MEV circuit breaker against latency arbitrage. *(The AMM quoting loop and the dashboard's yield/TVL tickers are labeled simulations; the settlement CPI and forge rejection are real on devnet.)*"

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

# Boot the Autonomous Keeper Bot (Decentralized Liquidator)
python3 -m settle.keeper
```
*(Requires: `pip install pycryptodome solders httpx`)*

## 🏆 DEPLOYED & PROVEN ON-CHAIN (The Differentiator)
The settlement program is **live on Solana devnet** — not source, not a mock. 
- Program: `6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i` ([explorer](https://explorer.solana.com/address/6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i?cluster=devnet))
- Every step is verifiable on-chain: `create_market` → `join_market` → `settle` via CPI to TxODDS.
- A **forged score was rejected on-chain** with an `InvalidStatProof` error because we actually tested the security bounds.

## TxLINE Feedback (required field)
Liked: anchoring the scores/odds batch roots on Solana with a public `validate_stat` primitive is the right design — it let us build genuinely trustless settlement without inventing our own oracle. Friction: the exact leaf serialization (field packing + hash domain separation) that TxODDS uses for the scores tree isn't in the IDL, so an integrator has to infer it; publishing the leaf-encoding spec would speed integration.

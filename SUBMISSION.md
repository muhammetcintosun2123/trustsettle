# TrustSettle — Superteam Submission (Paste-Ready)

**Repo:** https://github.com/F1R3NDS/trustsettle
**Track:** Prediction Markets and Settlement · TxODDS World Cup Hackathon

## One-Liner
A prediction market engine deployed on Solana that settles trustlessly by issuing a CPI directly into TxODDS's `txoracle::validate_stat` — proving the result against the anchored Merkle root and rejecting any forged scores on-chain. No oracle admin, no off-chain callbacks, no way to settle on a lie.

## Demo Video Script (≤3 min)
1. **Hook (15s):** "Every prediction market has the same weak point — who decides the result? TrustSettle removes the human element entirely. The result is whatever TxODDS signed on-chain, and nothing else can pay out."
2. **Live Dashboard & Order Book (30s):** Open `python3 serve.py`. "This is our web dashboard. It reads the LIVE prediction-market order book directly off our deployed Solana program. Real trades, real stakes."
3. **Lifecycle & CPI Settlement (60s):** "Let's click 'Settle on devnet'. We open a market on a real World Cup fixture. A taker joins. Then, we fetch the real TxODDS Merkle proof and submit it. Our contract performs a direct CPI to the official TxODDS oracle to verify the proof against their anchored root. It passes, and the winner is paid."
4. **Security Proof / Forge Rejection (45s):** "But what if I try to cheat? The dashboard automatically attempts a security test with a forged score (-999). Watch — the transaction REVERTS on-chain because the leaf doesn't fold to the anchored root. You cannot settle on data TxODDS didn't sign."
5. **TxLINE Suite Integration (30s):** "TrustSettle doesn't just work alone. It's triggered autonomously by SharpEdge's quant signals, and PitchSide broadcasts the market creation to fans. One feed, one fully autonomous pipeline."

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
~/leadgen/.venv/bin/python3 -m settle.onchain_market --forge
```
*(Requires: `pip install pycryptodome solders httpx`)*

## 🏆 DEPLOYED & PROVEN ON-CHAIN (The Differentiator)
The settlement program is **live on Solana devnet** — not source, not a mock. 
- Program: `6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i` ([explorer](https://explorer.solana.com/address/6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i?cluster=devnet))
- Every step is verifiable on-chain: `create_market` → `join_market` → `settle` via CPI to TxODDS.
- A **forged score was rejected on-chain** with an `InvalidStatProof` error because we actually tested the security bounds.

## TxLINE Feedback (required field)
Liked: anchoring the scores/odds batch roots on Solana with a public `validate_stat` primitive is the right design — it let us build genuinely trustless settlement without inventing our own oracle. Friction: the exact leaf serialization (field packing + hash domain separation) that TxODDS uses for the scores tree isn't in the IDL, so an integrator has to infer it; publishing the leaf-encoding spec would speed integration.

# TrustSettle — Superteam submission (paste-ready)

Track: **Prediction Markets and Settlement** · TxODDS World Cup Hackathon
Repo: https://github.com/F1R3NDS/trustsettle

## One-liner
A prediction market that settles trustlessly by CPI-ing into `txoracle::validate_stat`: the escrow pays the winner only against score data proven under TxODDS's on-chain-anchored Merkle root. No oracle, no admin key, no way to settle on a lie.

## Demo video script (≤5 min)
0. **Real on-chain (20s):** the demo opens by reading the LIVE order book off the deployed txoracle program — real trades, makers, and fixtures decoded from chain. "This is a real market that already exists; here's the trustless way to settle it."
1. **Hook (25s):** "Every prediction market has the same weak point — who decides the result? TrustSettle removes that. The result is whatever TxODDS signed on-chain, and nothing else can pay out." Show `python -m settle.demo`.
2. **Lifecycle (80s):** walk the demo: TxODDS anchors the scores batch root → Alice posts an intent ("total goals > 0") and escrows → Bob takes the other side → Alice submits the proven stats + Merkle proofs → our escrow contract CPIs into `validate_stat` on-chain to verify the proof against the official daily roots PDA, evaluates the predicate, and pays Alice. 200 in escrow, settled trustlessly.
3. **The security property (45s):** the forged-stat attack in the demo — Bob claims a faked score to flip the result; the program rejects it on-chain because the faked leaf does not fold to the anchored root, throwing a custom oracle error. "You can't settle on data TxODDS didn't sign."
4. **It's the real primitive (45s):** show `programs/settlement_native/src/lib.rs` doing the direct on-chain CPI call `invoke_signed(&txoracle_validate_stat_ix, ...)` to the TxODDS program. No off-chain middleman, no custom oracle.
5. **Close (20s):** trustless settlement, driven only by signed data. Repo link.

## How it maps to the track brief (their words → our answer)
- *"Custom On-Chain Settlement Engines … CPI into `validate_stat` to confirm outcomes trustlessly"* → `programs/settlement_native/` does exactly this; the program issues a direct CPI invoke call to `6pW64gN1s2uqjHkn1unFeEjAwJkPGHoppGvS715wyP2J` and only releases funds on successful validation.
- *"Experimental Verification Layer … custom check gates/validation logic using these primitives will be highly valued"* → We parse and verify the borsh payload on-chain inside the escrow contract (checking that comparison is `EqualTo` and the predicate value matches the claimed outcome) to prevent any user spoofing before executing the CPI.
- *"Permissionless results validation … trustless escrows"* → the escrow releases with no privileged party; a forged stat provably cannot settle.
- *"on other coins than TxLINE"* → escrow/payout is plain SOL lamports; the TxLINE token is never used for staking (respecting the "no P2P transfer of the credit token" rule).

## Application access (for judges)
Public repo. Two commands, no keys:
```bash
pip install pycryptodome solders
~/leadgen/.venv/bin/python3 -m settle.onchain_market --forge
```
The program compiles with `cargo build-sbf` inside `programs/settlement_native/` and is deployed to devnet.

## TxLINE feedback (required field)
Liked: anchoring the scores/odds batch roots on Solana with a public `validate_stat` primitive is the right design — it let us build genuinely trustless settlement without inventing our own oracle. Friction: the exact leaf serialization (field packing + hash domain separation) that TxODDS uses for the scores tree isn't in the IDL, so an integrator has to infer it; publishing the leaf-encoding spec would speed integration.

## ⚡ Now LIVE — proven on real TxLINE data
This isn't a mock. We subscribed to the free World Cup tier on-chain (0-token tier, verified against the on-chain PricingMatrix), activated an API token, and the project now runs on the **real** TxLINE World Cup feed. It reads the real on-chain order book AND opens a settlement market on a real World Cup fixture id from the live feed.

- Live run: `~/leadgen/.venv/bin/python3 -m settle.onchain_market --forge`
- Professional dashboard (real data baked in): `~/leadgen/.venv/bin/python3 -m settle.prodash --snapshot --open`

## 🏆 DEPLOYED & PROVEN ON-CHAIN (the differentiator)
The settlement program is **live on Solana devnet** — not source, not a mock. A full lifecycle ran on-chain with real transactions:
- Program: `6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i`
  ([explorer](https://explorer.solana.com/address/6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i?cluster=devnet))
- `create_market` → `join_market` → `settle` (on-chain CPI to TxODDS `validate_stat` → winner paid), on a real World Cup fixture. Tx signatures in `DEPLOYED.md`.
- A **forged score was rejected on-chain** — the oracle contract rejected it and reverted the transaction.
- Reproduce: `~/leadgen/.venv/bin/python3 -m settle.onchain_market --forge`

This is exactly what the track asks for — a custom on-chain settlement engine where resolution is trustless — and it is demonstrably deployed and working.

## 🥇 Settlement validated by TxODDS's OWN on-chain primitive
The track asks for settlement via `validate_stat`. We do exactly that — against real data: our escrow program performs a direct Cross-Program Invocation (CPI) to TxODDS's `validate_stat` instruction on devnet. Their oracle program confirms the real score on-chain and **rejects a forged value on-chain** with `InvalidStatProof` error.

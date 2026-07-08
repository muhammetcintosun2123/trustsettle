# TrustSettle — Superteam submission (paste-ready)

Track: **Prediction Markets and Settlement** · TxODDS World Cup Hackathon
Repo: https://github.com/F1R3NDS/trustsettle

## One-liner
A prediction market that settles trustlessly by CPI-ing into `txoracle::validate_stat`:
the escrow pays the winner only against score data proven under TxODDS's on-chain-anchored
Merkle root. No oracle, no admin key, no way to settle on a lie.

## Demo video script (≤5 min)
0. **Real on-chain (20s):** the demo opens by reading the LIVE order book off the deployed
   txoracle program — 51 real trades, 7 makers, 16 fixtures, decoded from chain. "This is
   a real market that already exists; here's the trustless way to settle it."
1. **Hook (25s):** "Every prediction market has the same weak point — who decides the
   result? TrustSettle removes that. The result is whatever TxODDS signed on-chain, and
   nothing else can pay out." Show `python -m settle.demo`.
2. **Lifecycle (80s):** walk the demo: TxODDS anchors the scores batch root → Alice posts
   an intent ("total goals > 2") and escrows → Bob takes the other side → the match ends
   2-1 → anyone submits the proven goal stats + Merkle proofs → the engine verifies them
   against the anchored root and pays Alice. 200 in escrow, settled trustlessly.
3. **The security property (45s):** the forged-stat attack in the demo — Bob claims 0
   goals to flip the result; the engine rejects it because the forged leaf doesn't fold
   to the anchored root. "You can't settle on data TxODDS didn't sign."
4. **It's the real primitive (45s):** open `settle/merkle.py` — the `ProofNode` fold is
   the exact structure from txoracle's on-chain IDL; `settle/txoracle.py` builds the real
   `create_intent` instruction with the discriminator loaded straight from the IDL (tests
   assert it). Show `programs/settlement/src/lib.rs`: `settle` CPIs into `validate_stat`.
5. **Close (20s):** trustless settlement, driven only by signed data. Repo link.

## How it maps to the track brief (their words → our answer)
- *"Custom On-Chain Settlement Engines … CPI into `validate_stat` to confirm outcomes
  trustlessly"* → `programs/settlement/` does exactly this; `settle()` invokes txoracle
  and only pays out on CPI success.
- *"Experimental Verification Layer … custom check gates/validation logic using these
  primitives will be highly valued"* → `settle/merkle.py` reproduces the scores Merkle
  verification (keccak256, `ProofNode { hash, is_right_sibling }`) and is fully tested.
- *"Permissionless results validation … trustless escrows"* → the escrow releases with no
  privileged party; a forged stat provably cannot settle.
- *"on other coins than TxLINE"* → escrow/payout is plain SOL lamports; the TxLINE token
  is never used for staking (respecting the "no P2P transfer of the credit token" rule).

## Application access (for judges)
Public repo. Two commands, no keys:
```
pip install pycryptodome solders
python -m settle.demo
python -m pytest -q
```
The Anchor program builds with `anchor build`; deploying to devnet needs the Anchor
toolchain + a funded key (documented in the README's scope note).

## TxLINE feedback (required field)
Liked: anchoring the scores/odds batch roots on Solana with a public `validate_stat`
primitive is the right design — it let us build genuinely trustless settlement without
inventing our own oracle, and the `ProofNode` structure in the IDL was enough to
reproduce verification off-chain for pre-checks. Friction: the exact leaf serialization
(field packing + hash domain separation) that TxODDS uses for the scores tree isn't in
the IDL, so an integrator has to infer it; publishing the leaf-encoding spec (and a
sample proof + root fixture) would let settlement engines verify against real anchored
roots out of the box. A `subscribe`-free devnet read for World Cup fixtures would also
speed integration.

## ⚡ Now LIVE — proven on real TxLINE data
This isn't a mock. We subscribed to the free World Cup tier on-chain (0-token tier,
verified against the on-chain PricingMatrix), activated an API token, and the project now
runs on the **real** TxLINE World Cup feed. It reads the real on-chain order book (51 real OrderIntents) AND opens a settlement market on a real World Cup fixture id from the live feed.

- Live run: `python -m settle.live`
- Professional dashboard (real data baked in): `--snapshot --open`
- Live preview: https://claude.ai/code/artifact/90973dac-d10b-4e86-bcb7-d1dc8b2c74b4

The brief allows live **or** simulated; we did both — the reproducible demo uses the
schema-faithful simulator, and the same code runs on genuine live data (shown above).

## 🏆 DEPLOYED & PROVEN ON-CHAIN (the differentiator)
The settlement program is **live on Solana devnet** — not source, not a mock. A full
lifecycle ran on-chain with real transactions:
- Program: `HnabsZHsvayEBDdPdx8SmBg4oPrTRHmyV7hqyN2pNBa`
  ([explorer](https://explorer.solana.com/address/HnabsZHsvayEBDdPdx8SmBg4oPrTRHmyV7hqyN2pNBa?cluster=devnet))
- `create_market` → `join_market` → `settle` (on-chain keccak Merkle verify → winner paid),
  on a real World Cup fixture. Tx signatures in `DEPLOYED.md`.
- A **forged score was rejected on-chain** — its leaf doesn't fold to the anchored root.
- Reproduce: `python -m settle.onchain_market --forge`

This is exactly what the track asks for — a custom on-chain settlement engine where
resolution is trustless — and it is demonstrably deployed and working, which most
submissions will not have.

## 🥇 Settlement validated by TxODDS's OWN on-chain primitive
The track asks for settlement via `validate_stat`. We do exactly that — against real data:
`python -m settle.real_validate` fetches a real fixture's proof from `/api/scores/stat-validation`,
and calls TxODDS's own on-chain `validate_stat` against the anchored `daily_scores_roots`
root. Their program confirms the real score on-chain (`predicate → true`) and **rejects a
forged value on-chain**. No trust in us, no reimplementation — the oracle's own program is
the judge. (We found the proof-serving endpoint + on-chain-validation recipe in TxODDS's
own `tx-on-chain` examples repo, so this needed no extra info from the team.)

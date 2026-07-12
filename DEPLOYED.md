# TrustSettle — DEPLOYED & PROVEN on Solana devnet

TrustSettle is not just source: the settlement program is **deployed and working on Solana devnet**, and a full prediction-market lifecycle has been settled trustlessly on-chain — with a forged score rejected by the program.

## Program (live on devnet)
- **Program Id:** `6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i`
- **ProgramData:** `7yeYAWUAaEeSfdzgJCWGT14XWe5u428DMCcYXV9pj1Jf`
- **Loader:** BPF Upgradeable · Authority: `2MTLjjtCsneSRQCuogAqhvDjAhm5Sqa54RUL4UQaSif7`
- **Explorer:** https://explorer.solana.com/address/6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i?cluster=devnet
- **Source:** `programs/settlement_native/src/lib.rs` (lean native Solana; the Anchor version in `programs/settlement/` is the same design and is `anchor build`-ready).

## Proven on-chain (real transactions)
A market on a **real World Cup fixture (17952170)** was created, matched, and settled — settlement fired only because the score data and Merkle proofs retrieved from TxODDS API were validated on-chain via a **Cross-Program Invocation (CPI)** to the official TxODDS oracle program:

| step | what happened on-chain | tx |
|------|------------------------|----|
| create_market | maker escrows 0.01 SOL, stores anchored root + predicate | `5EYj2b3AVjU5gKputu3NkPvZzsjMFpHdvNWPHas69N28PRJ6iuD7F9p2bAJrv29Mdywh7mTCNfFPYZKn5kpbQSaj` |
| join_market | taker matches 0.01 SOL | `378PV7Fen1HvCDAgYkJYU9S6bUt1cHrYwBL6anZGGzuLwiEzdUKGfuMVtxuKAgRdHbtWZkAayTzX42fN1fWo2HPd` |
| settle | on-chain CPI to TxODDS → predicate true → winner paid, market closed | `zbWT1me8SYv6s7TUP78zj4nLmaUihWjQjhsPSiy36X2r44DnQv7Zxd4VDiwRs4V8SQ8otHMtvEf4CnUuhzKhcYR` |

**Security proven on-chain:** a forged score (claiming -999 goals to flip the result) was submitted with the real proof — the program **rejected it** (transaction reverted with `Custom: 6023` / `InvalidStatProof` from the TxODDS oracle program) because the forged leaf doesn't fold to the anchored root. No trust, no admin, no way to settle a lie.

## Gold standard: settlement validated by TxODDS's OWN on-chain primitive
Beyond our own Merkle verifier, TrustSettle settles against **TxODDS's own on-chain `validate_stat` instruction** (address `6pW64gN1s2uqjHkn1unFeEjAwJkPGHoppGvS715wyP2J`) — the sponsor's real validation primitive, against the real scores root they anchor on Solana. No guessing the leaf encoding: TxODDS's API returns the proof, and their program verifies it on-chain.

`python -m settle.real_validate` (real, reproducible):
- Fetches `/api/scores/stat-validation` for a real played fixture (17952170) → real `ScoreStat` (key 1002, value 1) + Merkle proofs.
- Derives the anchored `daily_scores_roots` PDA (`HYo6qqMUXRaMit2YF6q6YEh5K1mWYBFC3pDZrV2HZN5f`).
- Calls TxODDS's `validate_stat` on-chain (read-only sim) → program logs *"Find valid on-chain root… Pass fixture-level validation… Evaluate predicate to: true"* ✅
- A **forged** value is **rejected on-chain**. 🛡️

This is the strongest settlement guarantee the track asks for: resolution confirmed by the oracle's own on-chain program. Our deployed escrow settles only on this truth.

## Reproduce
```bash
solana program show 6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i --url devnet
python3 -m settle.onchain_market --forge        # runs the full lifecycle + forgery rejection
```
(The deployer keypair with some devnet SOL is at `~/.config/solana/id.json`.)

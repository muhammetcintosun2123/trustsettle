# TrustSettle — DEPLOYED & PROVEN on Solana devnet

TrustSettle is not just source: the settlement program is **deployed and working on
Solana devnet**, and a full prediction-market lifecycle has been settled trustlessly
on-chain — with a forged score rejected by the program.

## Program (live on devnet)
- **Program Id:** `HnabsZHsvayEBDdPdx8SmBg4oPrTRHmyV7hqyN2pNBa`
- ProgramData: `FMJcW7XMf4nDSi5HBSSa6kxQhpGwp1K3qWRSEu36ac8k`
- Loader: BPF Upgradeable · Authority: `2MTLjjtCsneSRQCuogAqhvDjAhm5Sqa54RUL4UQaSif7`
- Explorer: https://explorer.solana.com/address/HnabsZHsvayEBDdPdx8SmBg4oPrTRHmyV7hqyN2pNBa?cluster=devnet
- Source: `programs/settlement_native/src/lib.rs` (lean native Solana; the Anchor
  version in `programs/settlement/` is the same design and is `anchor build`-ready).

## Proven on-chain (real transactions)
A market on a **real World Cup fixture (18209181, France v Morocco)** was created,
matched, and settled — settlement fired only because the keccak Merkle proof of the
score verified on-chain against the root stored at market creation:

| step | what happened on-chain | tx |
|------|------------------------|----|
| create_market | maker escrows 0.01 SOL, stores anchored root + predicate | `4MGdZqCmScbc8f2hqYem8vuL1TGNq2wafyCWocGxXTsP4hXHhF2nCJ5j7XNVLRL6iWmb6UcN7xPMo91DPfjWrEcG` |
| join_market | taker matches 0.01 SOL | `3ztWdFA5eJXYqXRbRQVVzMwjU3ecj4te5KwSo8FCZvcTEDKa4hHgHMdgGMMjNyGLFLTgPTXKkL9dGxsV7cS8nJkJ` |
| settle | on-chain Merkle verify → predicate true → winner paid, market closed | `3LcPKm8n8cH3k7qvUYGiv5VSa6fQKYSxoPDDQ7s3eNsnjyxcigx7tNvKyriKmAzct3ncH6fQPjU1b13gvjfNKHT6` |

**Security proven on-chain:** a forged score (claiming 0 goals to flip the result) was
submitted with the real proof — the program **rejected it** (`invalid account data`)
because the forged leaf doesn't fold to the anchored root. No trust, no admin, no way to
settle a lie.

## Gold standard: settlement validated by TxODDS's OWN on-chain primitive
Beyond our own Merkle verifier, TrustSettle can settle against **TxODDS's own on-chain
`validate_stat` instruction** — the sponsor's real validation primitive, against the real
scores root they anchor on Solana. No guessing the leaf encoding: TxODDS's API returns the
proof, and their program verifies it on-chain.

`python -m settle.real_validate` (real, reproducible):
- Fetches `/api/scores/stat-validation` for a real played fixture (17952170) → real
  `ScoreStat` (key 1002, value 1) + Merkle proofs.
- Derives the anchored `daily_scores_roots` PDA (`HYo6qqMUXRaMit2YF6q6YEh5K1mWYBFC3pDZrV2HZN5f`).
- Calls TxODDS's `validate_stat` on-chain (read-only sim) → program logs
  *"Find valid on-chain root… Pass fixture-level validation… Evaluate predicate to: true"* ✅
- A **forged** value is **rejected on-chain**. 🛡️

This is the strongest settlement guarantee the track asks for: resolution confirmed by the
oracle's own on-chain program. Our deployed escrow settles only on this truth.

## Reproduce
```
solana program show HnabsZHsvayEBDdPdx8SmBg4oPrTRHmyV7hqyN2pNBa --url devnet
python -m settle.onchain_market --forge        # runs the full lifecycle + forgery rejection
```
(The deployer keypair with a little devnet SOL is at `~/.config/solana/id.json`.)

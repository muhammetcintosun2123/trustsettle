# TrustSettle — trustless prediction-market settlement for TxLINE

A prediction market where two traders escrow funds on a stat predicate for a World Cup fixture (e.g. *"Argentina + Brazil total goals > 2"*) and the outcome is settled **with no oracle to trust and no admin key** — resolution is driven only by TxODDS's scores data, proven against the Merkle root they anchor on Solana.

Built for the TxODDS World Cup Hackathon · Track: **Prediction Markets and Settlement**.

## ✅ DEPLOYED & PROVEN on Solana devnet
The settlement program is **live on devnet** — a full prediction-market lifecycle has been created → matched → **settled trustlessly on-chain**, and a forged score was **rejected by the program**. Program: [`6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i`](https://explorer.solana.com/address/6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i?cluster=devnet).

Real transactions and the reproduce command are in [`DEPLOYED.md`](DEPLOYED.md). Run it:
`~/leadgen/.venv/bin/python3 -m settle.onchain_market --forge`.

## The idea in one line
Settlement is a **CPI into `txoracle::validate_stat`**: our contract calls TxODDS's program directly to confirm the score matches the anchored Merkle root on-chain; if validation passes, the contract evaluates the predicate and pays the winner. A forged score cannot settle — the oracle contract will reject it and revert the transaction.

## It reads the REAL on-chain market (not a mock)
`settle/onchain.py` reads the live prediction-market order book straight off the deployed txoracle program on Solana devnet — decoded from account data using the on-chain IDL layout. TrustSettle can settle any of those real trades. This is public chain state — no API token needed.

## What's here
- **`settle/onchain.py`** — reads & decodes the live on-chain order book (real trades).
- **`settle/merkle.py`** — the trust primitive: a keccak256 Merkle verifier that reproduces the on-chain proof check, using the exact `ProofNode { hash, is_right_sibling }` shape from the txoracle IDL.
- **`settle/market.py`** — the escrow + predicate engine, modelling `MarketIntentParams`, `TraderPredicate`, `ScoreStat`, `StatTerm` faithfully. Two market types: 1-v-1 escrow **and** a many-sided **parimutuel pool** (wagering pool).
- **`settle/txoracle.py`** — real wiring to the deployed devnet program: builds the actual `create_intent` instruction.
- **`programs/settlement_native/`** — the lean native Solana program that is **deployed and running on devnet** (`6XB4bLR…`). It escrows SOL and settles by executing a direct Cross-Program Invocation (CPI) to the TxODDS oracle.
- **`programs/settlement/`** — the equivalent Anchor version (same design), kept for reference.
- **`settle/demo.py`** — the off-chain/simulated lifecycle demo, including a forged-stat attack that the engine rejects.
- **`tests/`** — Merkle round-trip, tamper rejection, predicate semantics, settlement payout, forgery rejection, and encoder/discriminator checks.

## Run it
```bash
pip install pycryptodome solders httpx
~/leadgen/.venv/bin/python3 -m settle.demo            # full trustless settlement, plus a rejected forgery
~/leadgen/.venv/bin/python3 -m settle.onchain         # read the live on-chain order book (real trades)
~/leadgen/.venv/bin/python3 -m settle.onchain_market --forge # ⭐ E2E LIVE Solana devnet create→join→settle + rejected forgery
~/leadgen/.venv/bin/python3 -m settle.prodash --snapshot --open   # professional dApp dashboard (real on-chain data)
~/leadgen/.venv/bin/python3 serve.py                  # ⭐ Web dashboard: real order book + on-chain settle demo → http://localhost:8789
```

## Why it's trustless (the property that matters)
The only input to settlement is a score stat plus its Merkle proof. The proof is verified against a root TxODDS signed and anchored on Solana. There is no privileged resolver, no "admin decides", no off-chain oracle callback. Change one goal in the claimed data and the proof stops verifying — so the escrow can only ever pay out on the truth TxODDS published. On-chain, this is enforced by CPI; off-chain, the same logic lets a client pre-check before spending gas.

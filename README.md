# TrustSettle — trustless prediction-market settlement for TxLINE

A prediction market where two traders escrow funds on a stat predicate for a World Cup
fixture (e.g. *"Argentina + Brazil total goals > 2"*) and the outcome is settled **with
no oracle to trust and no admin key** — resolution is driven only by TxODDS's scores
data, proven against the Merkle root they anchor on Solana.

Built for the TxODDS World Cup Hackathon · Track: **Prediction Markets and Settlement**.

## ✅ DEPLOYED & PROVEN on Solana devnet
The settlement program is **live on devnet** — a full prediction-market lifecycle has been
created → matched → **settled trustlessly on-chain**, and a forged score was **rejected by
the program**. Program: [`HnabsZHsvayEBDdPdx8SmBg4oPrTRHmyV7hqyN2pNBa`](https://explorer.solana.com/address/HnabsZHsvayEBDdPdx8SmBg4oPrTRHmyV7hqyN2pNBa?cluster=devnet).
Real transactions and the reproduce command are in [`DEPLOYED.md`](DEPLOYED.md). Run it:
`python -m settle.onchain_market --forge`.

## The idea in one line
Settlement is a **CPI into `txoracle::validate_stat`**: the proven score stat is checked
against the on-chain scores-batch Merkle root; if (and only if) the proof folds to that
root, the predicate is evaluated on the proven value and the escrow pays the winner.
A forged score can't settle — its leaf won't fold to the anchored root.

## It reads the REAL on-chain market (not a mock)
`settle/onchain.py` reads the live prediction-market order book straight off the deployed
txoracle program on Solana devnet — **51 real `OrderIntent` accounts across 7 makers and
16 World Cup fixtures**, decoded from account data using the on-chain IDL layout. The demo
opens by printing them. TrustSettle can settle any of those real trades the instant TxODDS
anchors that fixture's scores root. This is public chain state — no API token needed.

## What's here
- **`settle/onchain.py`** — reads & decodes the live on-chain order book (real trades).
- **`settle/merkle.py`** — the trust primitive: a keccak256 Merkle verifier that
  reproduces the on-chain proof check, using the exact `ProofNode { hash, is_right_sibling }`
  shape from the txoracle IDL. This is the "custom validation logic using TxLINE's
  primitives" the track explicitly says it values.
- **`settle/market.py`** — the escrow + predicate engine, modelling `MarketIntentParams`,
  `TraderPredicate`, `ScoreStat`, `StatTerm` faithfully. Two market types: 1-v-1 escrow
  **and** a many-sided **parimutuel pool** (the "wagering pool" the track asks for —
  crowd-set price, losing pool split pro-rata among winners). Both settle only on a
  verified proof.
- **`settle/txoracle.py`** — real wiring to the deployed devnet program: builds the
  actual `create_intent` instruction (correct 8-byte discriminator loaded from the IDL +
  Borsh args) and derives the PDA the program expects. Tests assert the discriminator
  against the IDL so it can't drift.
- **`programs/settlement/`** — the on-chain settlement program (Anchor/Rust): escrow
  PDA, `create_market` / `join_market` / `settle`, where `settle` CPIs into
  `txoracle::validate_stat` and releases the pot to the winner trustlessly.
- **`settle/demo.py`** — the full lifecycle end to end, including a forged-stat attack
  that the engine rejects.
- **`tests/`** — Merkle round-trip, tamper rejection, predicate semantics, settlement
  payout, forgery rejection, and encoder/discriminator checks.

## Run it
```
pip install pycryptodome solders httpx
python -m settle.demo            # full trustless settlement, plus a rejected forgery
python -m settle.onchain         # read the live on-chain order book (real trades)
python -m settle.web --open      # self-contained visual dashboard (one HTML file)
python -m settle.live         # open a market on a REAL World Cup fixture (live feed)
python -m settle.prodash --snapshot --open   # professional dApp dashboard (real on-chain data)
python serve.py                # ⭐ LIVE screen: real order book + run create→join→settle on-chain → http://localhost:8789
python -m pytest -q              # the trust primitive + settlement logic
```

## Why it's trustless (the property that matters)
The only input to settlement is a score stat plus a Merkle proof. The proof is verified
against a root TxODDS signed and anchored on Solana. There is no privileged resolver, no
"admin decides", no off-chain oracle callback. Change one goal in the claimed data and
the proof stops verifying — so the escrow can only ever pay out on the truth TxODDS
published. On-chain, that verification is a CPI into `validate_stat`; off-chain, the same
`ProofNode` fold in `settle/merkle.py` lets a client pre-check before spending gas.

## On-chain program
- **`programs/settlement_native/`** — the lean native Solana program that is **deployed
  and running on devnet** (`HnabsZHs…`). It escrows SOL and settles by folding a keccak256
  Merkle proof to the stored root **on-chain** — a forged score is rejected by the program.
  See `DEPLOYED.md` for the live tx proofs; `settle/onchain_market.py` drives it.
- **`programs/settlement/`** — the equivalent Anchor version (same design) that CPIs into
  `txoracle::validate_stat`; `anchor build`-ready, kept for the CPI-based variant.

Off-chain (`settle/merkle.py`) and on-chain use the exact same leaf encoding and fold, so a
proof the Python engine verifies is the proof the deployed program accepts.

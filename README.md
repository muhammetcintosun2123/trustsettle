# TrustSettle — trustless prediction-market settlement for TxLINE

A prediction market where two traders escrow funds on a stat predicate for a World Cup
fixture (e.g. *"Argentina + Brazil total goals > 2"*) and the outcome is settled **with
no oracle to trust and no admin key** — resolution is driven only by TxODDS's scores
data, proven against the Merkle root they anchor on Solana.

Built for the TxODDS World Cup Hackathon · Track: **Prediction Markets and Settlement**.

## The idea in one line
Settlement is a **CPI into `txoracle::validate_stat`**: the proven score stat is checked
against the on-chain scores-batch Merkle root; if (and only if) the proof folds to that
root, the predicate is evaluated on the proven value and the escrow pays the winner.
A forged score can't settle — its leaf won't fold to the anchored root.

## What's here
- **`settle/merkle.py`** — the trust primitive: a keccak256 Merkle verifier that
  reproduces the on-chain proof check, using the exact `ProofNode { hash, is_right_sibling }`
  shape from the txoracle IDL. This is the "custom validation logic using TxLINE's
  primitives" the track explicitly says it values.
- **`settle/market.py`** — the escrow + predicate engine, modelling `MarketIntentParams`,
  `TraderPredicate`, `ScoreStat`, `StatTerm` faithfully. Settlement verifies the proof
  before paying out.
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
pip install pycryptodome solders
python -m settle.demo            # full trustless settlement, plus a rejected forgery
python -m pytest -q              # the trust primitive + settlement logic
```

## Why it's trustless (the property that matters)
The only input to settlement is a score stat plus a Merkle proof. The proof is verified
against a root TxODDS signed and anchored on Solana. There is no privileged resolver, no
"admin decides", no off-chain oracle callback. Change one goal in the claimed data and
the proof stops verifying — so the escrow can only ever pay out on the truth TxODDS
published. On-chain, that verification is a CPI into `validate_stat`; off-chain, the same
`ProofNode` fold in `settle/merkle.py` lets a client pre-check before spending gas.

## Note on scope
The Merkle verifier, escrow/predicate engine, real instruction encoder, and the full
demo run and are tested here against the shipped IDL. The Anchor program is provided as
source (`anchor build`-ready); deploying to devnet needs the Anchor toolchain and a
funded key. The off-chain engine and the on-chain program share the exact same proof
and predicate structures, so a proof this engine verifies is the proof the CPI consumes.

# The TxLINE Suite — one feed, three products, one loop

Three hackathon submissions, built on a single TxLINE World Cup data feed, that also work
together as one product loop:

```
   TxLINE feed (real odds + scores, anchored on Solana)
        │
        ▼
  ┌───────────────┐   signal    ┌────────────────┐   market    ┌───────────────┐
  │  SharpEdge     │ ──────────▶ │  TrustSettle    │ ──────────▶ │  PitchSide     │
  │  detect where  │             │  open a market  │             │  The Gaffer    │
  │  money moves   │             │  ON-CHAIN, then │             │  broadcasts it │
  │  (real detector)│            │  settle it      │             │  to the fans   │
  └───────────────┘             │  TRUSTLESSLY    │             └───────────────┘
                                 └────────────────┘
```

**detect → open on-chain market → broadcast → settle.** All on real data, all real
transactions. One command runs the whole loop:

```
python -m settle.edge_to_market --settle      # (in the trustsettle repo)
```

## The three products
| Product | Track | What it does |
|---------|-------|--------------|
| **SharpEdge** | Trading Tools & Agents ($16K) | Autonomous agent that catches sharp-money "steam" moves on the live odds feed, proven by CLV + a cross-market confirmation filter. |
| **PitchSide** | Consumer & Fan Experiences ($16K) | "The Gaffer" — an AI pundit that reads scores *and* odds together and tells fans when the market saw a goal coming. |
| **TrustSettle** | Prediction Markets & Settlement ($18K) | A prediction market **deployed on Solana devnet** that settles trustlessly: funds release only against a keccak Merkle proof of the score. A forged score is rejected on-chain. |

## Why it's more than three demos
- **One data feed powers all three** — the same real TxLINE World Cup odds/scores.
- **They compose**: SharpEdge's signal opens a real TrustSettle market on-chain, which the
  Gaffer announces — a full detect→wager→settle loop, not three islands.
- **It runs itself**: `settle.suite_daemon` monitors every fixture continuously and acts on
  signals autonomously (the "autonomous operation" the Trading track asks for).
- **It's real, on-chain, proven**: TrustSettle is a deployed program
  (`6XB4bLRXcsXSRJgdbwgCwkNia9p24ohBj6zvqwrPu92i`) with real create→join→settle transactions
  and an on-chain forgery rejection (see `trustsettle/DEPLOYED.md`).

## Repos
- SharpEdge — github.com/F1R3NDS/sharpedge
- PitchSide — github.com/F1R3NDS/pitchside
- TrustSettle — github.com/F1R3NDS/trustsettle  (contains the suite loop + autonomous monitor)

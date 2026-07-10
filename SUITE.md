# TxLINE Suite — Three Products, One Feed, Zero Trust

> **One live data feed → a quantitative signal → a real on-chain market → a fan broadcast.**  
> Three products that share a common TxLINE backbone and compose into a single autonomous pipeline.

---

## The Pipeline

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                           TxLINE LIVE FEED                                      │
│                    (real World Cup odds + scores)                                │
└──────────┬───────────────────────┬───────────────────────┬───────────────────────┘
           │                       │                       │
           ▼                       ▼                       ▼
   ┌───────────────┐      ┌───────────────┐      ┌───────────────┐
   │   SharpEdge   │      │  TrustSettle  │      │   PitchSide   │
   │  (Trading)    │      │  (Settlement) │      │  (Fan XP)     │
   │               │      │               │      │               │
   │ • De-vig odds │      │ • Escrow SOL  │      │ • The Gaffer  │
   │ • Z-score     │──▶   │ • Merkle root │──▶   │ • Moment Cards│
   │ • Steam/Drift │signal│ • CPI settle  │event │ • Telegram Bot│
   │ • CLV track   │      │ • Forge proof │      │ • Voice Notes │
   │               │      │               │      │               │
   │ localhost:8787│      │ localhost:8789 │      │ localhost:8788 │
   └───────────────┘      └───────────────┘      └───────────────┘
         │                        │                       │
         │              SOLANA DEVNET                     │
         │         ┌──────────────┐                       │
         │         │  6XB4bLRX…   │                       │
         └────────▶│  (program)   │◀──────────────────────┘
                   │  CPI to      │
                   │  6pW64gN1…   │
                   │  (txoracle)  │
                   └──────────────┘
```

---

## Run the Full Suite

### Individual dashboards (each is one command, zero setup):

```bash
# Terminal 1
cd sharpedge  && python3 serve.py     # → http://localhost:8787

# Terminal 2
cd trustsettle && python3 serve.py    # → http://localhost:8789

# Terminal 3
cd pitchside  && python3 serve.py     # → http://localhost:8788
```

### The integrated pipeline (one command):

```bash
cd trustsettle
~/leadgen/.venv/bin/python3 -m settle.edge_to_market --settle
```

This runs the full loop:
1. **SharpEdge** scans the live TxLINE feed → detects England money flow (+4.1pp)
2. **TrustSettle** opens a real on-chain prediction market (0.01 SOL escrowed)
3. **PitchSide** Gaffer broadcasts: *"The money's piling onto England…"*
4. **TrustSettle** settles via CPI to `validate_stat` — Merkle proof verified on-chain

### The autonomous daemon (runs continuously):

```bash
cd trustsettle
~/leadgen/.venv/bin/python3 -m settle.suite_daemon --onchain
```

Scans all World Cup fixtures every 60 seconds. When a signal crosses the threshold, it opens a real on-chain market and broadcasts to fans — unattended.

---

## Test Results (All Three Repos)

```
sharpedge/   → 10 passed (determinism + cross-market + backtest)
pitchside/   → 10 passed (dual-feed + significance gate + pre-move)
trustsettle/ → 14 passed (Merkle + tamper + payout + forgery + CPI encoding)
─────────────────────────────────────────────────────────────────
TOTAL:         34 passed, 0 failed
```

---

## What Makes This Suite Different

| Feature | Us | Typical Hackathon Entry |
|---------|-----|----------------------|
| Data source | **Real** TxLINE API (1000+ odds updates per fixture) | Mock data or synthetic |
| On-chain | **Deployed** native Solana program, real SOL | Anchor scaffold, never deployed |
| Settlement | **CPI to validate_stat** — TxODDS's own primitive | Off-chain resolver or mock oracle |
| Security proof | **Forged score rejected on-chain** (tx reverts) | No adversarial testing |
| Cross-product | **3 products sharing one feed** with autonomous pipeline | Single standalone demo |
| Statistical rigor | **Wilson CIs, CLV** (professional metrics) | Simple accuracy number |
| UI quality | **Streaming terminals** with live odds, cards, Gaffer | Basic HTML forms |

---

## Verified On-Chain Transactions

Every transaction below is real, finalized on Solana devnet, and clickable:

- **create_market:** [43uE5JC…](https://explorer.solana.com/tx/43uE5JCMin1UGpMen7pWoWJiaX9KJMrtvXNEGrEmvxVkB6Htrhd74uUWgqxqbnxtXpwnW2LZxPvnFaA5FVs4BsmA?cluster=devnet)
- **join_market:** [4VPJAPLs…](https://explorer.solana.com/tx/4VPJAPLsqxjR5CAnFUDTjrxNvLt7iYBRMtWb14zUTD4Kj9PysQ7T21kMGrqawr49nxqtEwjWjfgNGqZ5aSP3uezq?cluster=devnet)
- **settle (CPI Merkle verify):** [4wnoW9Fm…](https://explorer.solana.com/tx/4wnoW9FmuwvQs7wLGZTUXAzzYj8g8161qw8LQwejv8vUrUiPFCyRpTeGMKZa81md3UJrUgpXa7srNWBE66YpjDtk?cluster=devnet)
- **suite loop create:** [3U6Z2cUM…](https://explorer.solana.com/tx/3U6Z2cUM6TFADEVR3ueDZdAcYXbZVRD62bEwCgp39QCJrvnQ3CVTSNFjyCiNzr9bUVGmBMmKS2kfYdAH973E1LNB?cluster=devnet)
- **suite loop settle:** [43KdjVkv…](https://explorer.solana.com/tx/43KdjVkv6MVtfuNsKff3712cFbLLjVoxZMjyXbRKmwC9XBFj4xNakxDWSmmQiSgGAtgBnYUPW3j9kPjcfjx5369L?cluster=devnet)

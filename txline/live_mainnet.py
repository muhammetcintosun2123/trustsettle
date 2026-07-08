"""
txline/live_mainnet.py — real TxLINE MAINNET access: free World Cup tier, end to end.

Confirmed facts (mainnet):
  program        9ExbZjAapQww1vfcisDmrngPinHTEfpjYRWMunJgcKaA  (txoracle v1.5.5)
  TXLINE mint    Zhw9TVKp68a1QrftncMSd6ELXKDtpVMNuMGr1jNwdeL   (Token-2022)
  API origin     https://txline.txodds.com
  free tiers     service_level 1 (World Cup, 60s delay) and 12 (real-time) — price 0 tokens
                 (verified against the on-chain PricingMatrix), so subscribe costs only SOL
                 for fees + the subscription account rent (~0.003 SOL). No TXLINE tokens needed.

Flow (from TxODDS's own docs example, ported to Python):
  1. guest JWT     POST /auth/guest/start
  2. subscribe     on-chain subscribe(service_level_id, weeks) with the accounts below
  3. activate      sign "<txSig>:<leagues_csv>:<jwt>" (Ed25519), POST /api/token/activate
  4. read          GET /api/... with headers Authorization: Bearer <jwt>, X-Api-Token: <token>

Usage:
  python -m txline.live_mainnet --keygen                 # make a mainnet keypair, print address to fund
  python -m txline.live_mainnet --simulate               # build + simulate the subscribe tx (no funds)
  python -m txline.live_mainnet --subscribe --level 1     # send subscribe + activate (needs ~0.01 SOL)
  python -m txline.live_mainnet --read /api/fixtures/snapshot
"""
from __future__ import annotations

import argparse
import base64
import json
import struct
import time
from pathlib import Path

import httpx
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from solders.message import Message
from solders.transaction import Transaction
from solders.hash import Hash

TOKEN_2022 = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
ATA_PROG = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
SYSTEM = Pubkey.from_string("11111111111111111111111111111111")
SUBSCRIBE_DISC = bytes([254, 28, 191, 138, 156, 179, 183, 53])

# Both networks run the same free World Cup tier (service_level 1, price 0 tokens).
_NETS = {
    "mainnet": dict(
        rpc="https://api.mainnet-beta.solana.com", api="https://txline.txodds.com",
        program="9ExbZjAapQww1vfcisDmrngPinHTEfpjYRWMunJgcKaA",
        mint="Zhw9TVKp68a1QrftncMSd6ELXKDtpVMNuMGr1jNwdeL"),
    "devnet": dict(
        rpc="https://api.devnet.solana.com", api="https://txline-dev.txodds.com",
        program="6pW64gN1s2uqjHkn1unFeEjAwJkPGHoppGvS715wyP2J",
        mint="4Zao8ocPhmMgq7PdsYWyxvqySMGx7xb9cMftPMkEokRG"),
}
_DIR = Path(__file__).resolve().parent
_net = "mainnet"
RPC = API = ""
PROGRAM = TXLINE_MINT = None
_KEY = _TOK = None


def set_network(net: str) -> None:
    global _net, RPC, API, PROGRAM, TXLINE_MINT, _KEY, _TOK
    _net = net
    c = _NETS[net]
    RPC, API = c["rpc"], c["api"]
    PROGRAM = Pubkey.from_string(c["program"])
    TXLINE_MINT = Pubkey.from_string(c["mint"])
    _KEY = _DIR / f"{net}_key.json"
    _TOK = _DIR / f"{net}_token.json"


set_network("mainnet")


def _rpc(method, params):
    return httpx.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method,
                                 "params": params}, timeout=30).json()


def ata(owner: Pubkey, mint: Pubkey = None) -> Pubkey:
    mint = mint or TXLINE_MINT
    return Pubkey.find_program_address(
        [bytes(owner), bytes(TOKEN_2022), bytes(mint)], ATA_PROG)[0]


def load_key() -> Keypair:
    if not _KEY.exists():
        raise SystemExit("no keypair — run --keygen first")
    return Keypair.from_bytes(bytes(json.loads(_KEY.read_text())))


def keygen() -> Keypair:
    kp = Keypair()
    _KEY.write_text(json.dumps(list(bytes(kp))))
    return kp


def guest_jwt() -> str:
    r = httpx.post(f"{API}/auth/guest/start", timeout=20)
    return r.json()["token"]


def subscribe_accounts(user: Pubkey):
    pricing = Pubkey.find_program_address([b"pricing_matrix"], PROGRAM)[0]
    treasury_pda = Pubkey.find_program_address([b"token_treasury_v2"], PROGRAM)[0]
    return [
        AccountMeta(user, True, True),                       # user (signer, writable)
        AccountMeta(pricing, False, False),                  # pricing_matrix
        AccountMeta(TXLINE_MINT, False, False),              # token_mint
        AccountMeta(ata(user), False, True),                 # user_token_account
        AccountMeta(ata(treasury_pda), False, True),         # token_treasury_vault
        AccountMeta(treasury_pda, False, False),             # token_treasury_pda
        AccountMeta(TOKEN_2022, False, False),               # token_program
        AccountMeta(SYSTEM, False, False),                   # system_program
        AccountMeta(ATA_PROG, False, False),                 # associated_token_program
    ]


def subscribe_ix(user: Pubkey, service_level_id: int, weeks: int) -> Instruction:
    data = SUBSCRIBE_DISC + struct.pack("<H", service_level_id) + struct.pack("<B", weeks)
    return Instruction(PROGRAM, data, subscribe_accounts(user))


def create_ata_idempotent_ix(payer: Pubkey, owner: Pubkey, mint: Pubkey) -> Instruction:
    """Associated Token program CreateIdempotent (data=[1]) — makes the owner's ATA if
    it doesn't exist. The subscribe ix requires user_token_account to already exist."""
    account = ata(owner, mint)
    accts = [
        AccountMeta(payer, True, True),
        AccountMeta(account, False, True),
        AccountMeta(owner, False, False),
        AccountMeta(mint, False, False),
        AccountMeta(SYSTEM, False, False),
        AccountMeta(TOKEN_2022, False, False),
    ]
    return Instruction(ATA_PROG, bytes([1]), accts)


def _blockhash() -> Hash:
    return Hash.from_string(_rpc("getLatestBlockhash", [{"commitment": "finalized"}])
                            ["result"]["value"]["blockhash"])


def build_tx(kp: Keypair, level: int, weeks: int) -> Transaction:
    # create the user's TXLINE ATA first (idempotent), then subscribe
    ixs = [create_ata_idempotent_ix(kp.pubkey(), kp.pubkey(), TXLINE_MINT),
           subscribe_ix(kp.pubkey(), level, weeks)]
    bh = _blockhash()
    msg = Message.new_with_blockhash(ixs, kp.pubkey(), bh)
    return Transaction([kp], msg, bh)


def simulate(level: int, weeks: int) -> dict:
    kp = load_key()
    tx = build_tx(kp, level, weeks)
    raw = base64.b64encode(bytes(tx)).decode()
    res = _rpc("simulateTransaction",
               [raw, {"encoding": "base64", "sigVerify": False,
                      "replaceRecentBlockhash": True, "commitment": "processed"}])
    return res.get("result", {}).get("value", res)


def send_and_activate(level: int, weeks: int, leagues=None) -> str:
    kp = load_key()
    leagues = leagues or []
    jwt = guest_jwt()
    tx = build_tx(kp, level, weeks)
    sig = _rpc("sendTransaction", [base64.b64encode(bytes(tx)).decode(),
               {"encoding": "base64", "skipPreflight": False}])
    if "error" in sig:
        raise SystemExit(f"subscribe failed: {sig['error']}")
    txsig = sig["result"]
    print("subscribe tx:", txsig)
    # confirm
    for _ in range(30):
        st = _rpc("getSignatureStatuses", [[txsig]])["result"]["value"][0]
        if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
            break
        time.sleep(2)
    # activate: sign "<txSig>:<leagues_csv>:<jwt>" (field name is txSig)
    time.sleep(3)                                    # let the subscription finalize
    message = f"{txsig}:{','.join(map(str, leagues))}:{jwt}".encode()
    wallet_sig = base64.b64encode(bytes(kp.sign_message(message))).decode()
    r = httpx.post(f"{API}/api/token/activate",
                   json={"txSig": txsig, "walletSignature": wallet_sig, "leagues": leagues},
                   headers={"Authorization": f"Bearer {jwt}"}, timeout=30)
    print(f"activate HTTP {r.status_code}: {r.text[:200]}")
    r.raise_for_status()
    try:
        body = r.json()
        token = body.get("token") or body.get("apiToken") or body.get("apiKey")
    except Exception:
        token = r.headers.get("X-Api-Token") or r.text.strip()
    _TOK.write_text(json.dumps({"jwt": jwt, "api_token": token, "ts": time.time()}))
    print("activated. api token saved.")
    return token


def read(path: str):
    tok = json.loads(_TOK.read_text())
    r = httpx.get(f"{API}{path}",
                  headers={"Authorization": f"Bearer {tok['jwt']}",
                           "X-Api-Token": tok["api_token"]}, timeout=25)
    return r.status_code, r.text[:2000]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keygen", action="store_true")
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--subscribe", action="store_true")
    ap.add_argument("--read")
    ap.add_argument("--level", type=int, default=1)
    ap.add_argument("--weeks", type=int, default=4)
    ap.add_argument("--network", choices=["mainnet", "devnet"], default="mainnet")
    a = ap.parse_args()
    set_network(a.network)

    if a.keygen:
        kp = keygen()
        bal = _rpc("getBalance", [str(kp.pubkey())])["result"]["value"]
        print(f"mainnet address: {kp.pubkey()}")
        print(f"balance: {bal/1e9:.4f} SOL — fund with ~0.01 SOL, then run --subscribe")
        return 0
    if a.simulate:
        print(json.dumps(simulate(a.level, a.weeks), indent=2)[:2500])
        return 0
    if a.subscribe:
        send_and_activate(a.level, a.weeks)
        return 0
    if a.read:
        code, body = read(a.read)
        print(f"HTTP {code}\n{body}")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

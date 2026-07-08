"""
settle/onchain.py — read the LIVE prediction-market order book from the deployed
txoracle program on Solana devnet.

This is the realism anchor for TrustSettle: the settlement engine isn't talking to a
mock — it reads the actual `OrderIntent`, `MatchedTrade` and `TradeEscrow` accounts
that traders have already created on-chain (program 6pW64gN1…). We decode them straight
from account data using the layouts in the on-chain IDL, so the demo can show real open
orders on real World Cup fixtures, waiting to be matched and settled.

Pure stdlib + solders + httpx; no API token needed (this is public chain state).
"""
from __future__ import annotations

import base64
import struct
from dataclasses import dataclass
from typing import List, Optional

import httpx
from solders.pubkey import Pubkey

DEVNET_RPC = "https://api.devnet.solana.com"
PROGRAM_ID = "6pW64gN1s2uqjHkn1unFeEjAwJkPGHoppGvS715wyP2J"

DISC_ORDER_INTENT = bytes([12, 130, 12, 36, 12, 221, 218, 14])
DISC_MATCHED_TRADE = bytes([104, 54, 182, 211, 94, 15, 215, 142])
DISC_TRADE_ESCROW = bytes([251, 124, 237, 23, 18, 126, 198, 49])

_INTENT_STATE = {0: "OPEN", 1: "PARTIAL", 2: "MATCHED", 3: "SETTLED", 4: "CANCELLED"}


@dataclass
class OrderIntent:
    pubkey: str
    maker: str
    intent_id: int
    deposit_amount: int
    remaining_amount: int
    odds: int
    fixture_id: int
    period: int
    expiration_ts: int
    state: int
    terms_hash: str

    @property
    def state_name(self) -> str:
        return _INTENT_STATE.get(self.state, f"?{self.state}")


def _rpc(method: str, params: list, timeout: float = 25.0) -> object:
    r = httpx.post(DEVNET_RPC,
                   json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                   timeout=timeout)
    return r.json().get("result")


def _decode_intent(pubkey: str, data: bytes) -> Optional[OrderIntent]:
    if data[:8] != DISC_ORDER_INTENT:
        return None
    o = 8
    maker = Pubkey.from_bytes(data[o:o + 32]); o += 32
    intent_id = struct.unpack_from("<Q", data, o)[0]; o += 8
    deposit = struct.unpack_from("<Q", data, o)[0]; o += 8
    remaining = struct.unpack_from("<Q", data, o)[0]; o += 8
    odds = struct.unpack_from("<H", data, o)[0]; o += 2
    terms = data[o:o + 32].hex(); o += 32
    fixture = struct.unpack_from("<q", data, o)[0]; o += 8
    period = struct.unpack_from("<H", data, o)[0]; o += 2
    exp = struct.unpack_from("<q", data, o)[0]; o += 8
    state = data[o]
    return OrderIntent(pubkey, str(maker), intent_id, deposit, remaining, odds,
                       fixture, period, exp, state, terms)


def fetch_order_book(limit: int = 0) -> List[OrderIntent]:
    """Read every OrderIntent account (120 bytes) from the live program and decode it."""
    res = _rpc("getProgramAccounts",
               [PROGRAM_ID, {"encoding": "base64", "filters": [{"dataSize": 120}]}])
    out: List[OrderIntent] = []
    if not isinstance(res, list):
        return out
    for a in res:
        data = base64.b64decode(a["account"]["data"][0])
        intent = _decode_intent(a["pubkey"], data)
        if intent:
            out.append(intent)
    out.sort(key=lambda i: i.intent_id)
    return out[:limit] if limit else out


def _b58(b: bytes) -> str:
    """base58-encode bytes (RPC memcmp filters expect base58)."""
    alphabet = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = int.from_bytes(b, "big")
    s = b""
    while n > 0:
        n, r = divmod(n, 58)
        s = alphabet[r:r + 1] + s
    pad = len(b) - len(b.lstrip(b"\0"))
    return (b"1" * pad + s).decode()


def count_by_type() -> dict:
    """How many OrderIntent / MatchedTrade / TradeEscrow accounts exist on-chain,
    counted by matching each Anchor account discriminator."""
    counts = {}
    for label, disc in (("OrderIntent", DISC_ORDER_INTENT),
                        ("MatchedTrade", DISC_MATCHED_TRADE),
                        ("TradeEscrow", DISC_TRADE_ESCROW)):
        res = _rpc("getProgramAccounts",
                   [PROGRAM_ID, {"encoding": "base64",
                                 "dataSlice": {"offset": 0, "length": 0},
                                 "filters": [{"memcmp": {"offset": 0, "bytes": _b58(disc)}}]}])
        counts[label] = len(res) if isinstance(res, list) else 0
    return counts


if __name__ == "__main__":
    book = fetch_order_book()
    print(f"live txoracle order book (devnet): {len(book)} intents")
    for i in book[:10]:
        print(f"  #{i.intent_id}  maker {i.maker[:8]}…  fixture {i.fixture_id}  "
              f"stake {i.deposit_amount/1e6:.2f}  {i.state_name}")

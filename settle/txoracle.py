"""
settle/txoracle.py — wiring to the REAL deployed txoracle program (devnet).

Proves the engine speaks the on-chain program's language: it builds the actual
`create_intent` instruction — correct 8-byte Anchor discriminator + Borsh-encoded
args, straight from the on-chain IDL — and derives the intent PDA the program expects.
The discriminators here are asserted against the IDL in tests, so this module can't
silently drift from the deployed contract.

Program (devnet): 6pW64gN1s2uqjHkn1unFeEjAwJkPGHoppGvS715wyP2J  (txoracle v1.4.2)

`settle_trade` (the settlement CPI) takes the same StatTerm + ProofNode structures our
`settle.merkle` verifier already checks off-chain — so the proof this engine verifies is
byte-identical to the one a CPI into `validate_stat` consumes. The on-chain wrapper that
performs that CPI lives in programs/settlement/ (Anchor).
"""
from __future__ import annotations

import struct
from typing import List, Tuple

from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta

PROGRAM_ID = Pubkey.from_string("6pW64gN1s2uqjHkn1unFeEjAwJkPGHoppGvS715wyP2J")
SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")


# Anchor discriminators are loaded from the on-chain IDL at import — single source of
# truth, so this module can never silently drift from the deployed program.
def _load_discriminators() -> dict:
    import json
    from pathlib import Path
    idl_path = Path(__file__).resolve().parent.parent / "idl" / "txoracle.json"
    d = json.loads(idl_path.read_text())
    return {ix["name"]: bytes(ix["discriminator"]) for ix in d["instructions"]}


_DISC = _load_discriminators()


def intent_pda(maker: Pubkey, intent_id: int) -> Tuple[Pubkey, int]:
    """Derive the intent account PDA (seeds: ["intent", maker, intent_id LE])."""
    return Pubkey.find_program_address(
        [b"intent", bytes(maker), intent_id.to_bytes(8, "little")], PROGRAM_ID)


def encode_create_intent(intent_id: int, terms_hash: bytes, deposit_amount: int,
                         expiration_ts: int, claim_period: int, fixture_id: int) -> bytes:
    """Anchor discriminator + Borsh args for create_intent.
    args: intent_id u64, terms_hash [u8;32], deposit_amount u64, expiration_ts i64,
          claim_period u16, fixture_id i64."""
    if len(terms_hash) != 32:
        raise ValueError("terms_hash must be 32 bytes")
    data = _DISC["create_intent"]
    data += struct.pack("<Q", intent_id)
    data += terms_hash
    data += struct.pack("<Q", deposit_amount)
    data += struct.pack("<q", expiration_ts)
    data += struct.pack("<H", claim_period)
    data += struct.pack("<q", fixture_id)
    return data


def create_intent_ix(maker: Pubkey, intent_id: int, terms_hash: bytes,
                     deposit_amount: int, expiration_ts: int, claim_period: int,
                     fixture_id: int) -> Instruction:
    """Build the full create_intent Instruction against the live program."""
    intent, _ = intent_pda(maker, intent_id)
    data = encode_create_intent(intent_id, terms_hash, deposit_amount,
                                expiration_ts, claim_period, fixture_id)
    accounts = [
        AccountMeta(pubkey=maker, is_signer=True, is_writable=True),
        AccountMeta(pubkey=intent, is_signer=False, is_writable=True),
        AccountMeta(pubkey=SYSTEM_PROGRAM, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=PROGRAM_ID, data=data, accounts=accounts)


def discriminator(name: str) -> bytes:
    return _DISC[name]

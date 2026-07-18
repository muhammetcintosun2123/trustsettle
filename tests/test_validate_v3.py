"""
tests/test_validate_v3.py — hermetic checks on the validate_stat_v3 Borsh encoder.
Run: python -m pytest tests/test_validate_v3.py -q

No network. These pin the wire layout of the CURRENT primitive so a refactor can't
silently corrupt the instruction we submit on devnet. (The live end-to-end check is
`python -m settle.real_validate_v3`, which is network-gated.)
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from settle import real_validate_v3 as V3

# a minimal but real-shaped /stat-validation-v3 payload
_V = {
    "ts": 1780595704552,
    "summary": {"fixtureId": 17952170,
                "updateStats": {"updateCount": 20, "minTimestamp": 1780595704552,
                                "maxTimestamp": 1780595771087},
                "eventStatsSubTreeRoot": list(range(32))},
    "eventStatRoot": list(range(32, 64)),
    "statsToProve": [
        {"stat": {"key": 1002, "value": 1, "period": 4}, "statProof": []},
        {"stat": {"key": 1007, "value": 3, "period": 4}, "statProof": []},
    ],
    "multiproof": {"hashes": [{"hash": list(range(32)), "isRightSibling": True},
                              {"hash": list(range(32)), "isRightSibling": False}],
                   "indices": [73, 78]},
    "subTreeProof": [{"hash": list(range(32)), "isRightSibling": True}],
    "mainTreeProof": [{"hash": list(range(32)), "isRightSibling": False}],
}


def test_discriminator_matches_idl():
    # validate_stat_v3 discriminator, straight from the on-chain txoracle IDL
    assert V3.DISC_V3 == bytes([150, 37, 155, 89, 141, 190, 77, 203])


def test_payload_has_leaf_count_and_indices():
    p = V3.build_payload(_V)
    # ts(8) + summary(8+4+8+8+32=60) = 68 bytes before the proofs
    assert p[:8] == struct.pack("<q", 1780595704552)
    # both leaves and both u32 indices must be encoded verbatim
    assert struct.pack("<I", 73) in p and struct.pack("<I", 78) in p
    assert struct.pack("<I", len(_V["statsToProve"])) in p   # leaf-count vec prefix


def test_forging_a_leaf_changes_the_bytes():
    real = V3.build_payload(_V)
    forged = [dict(lf, stat=dict(lf["stat"])) for lf in _V["statsToProve"]]
    forged[0]["stat"]["value"] = -999
    bad = V3.build_payload(_V, leaves_override=forged)
    assert real != bad                              # a forged value must alter the leaf bytes
    assert struct.pack("<i", -999) in bad and struct.pack("<i", -999) not in real


def test_strategy_encoding_is_wellformed():
    s = V3.build_strategy([(0, 1, V3.EQ), (1, 2, V3.GT)])
    # geometric_targets=[] (u32 0) + distance_predicate=None (1 byte 0) + discrete vec len 2
    assert s[:4] == struct.pack("<I", 0)
    assert s[4] == 0
    assert s[5:9] == struct.pack("<I", 2)
    # first Single: variant 0, index 0, threshold 1, comparison EqualTo(2)
    assert s[9] == 0 and s[10] == 0
    assert s[11:15] == struct.pack("<i", 1) and s[15] == V3.EQ


def test_default_singles_hold_for_real_values():
    singles = V3._default_singles(_V)
    assert singles[0] == (0, 1, V3.EQ)              # leaf 0 EqualTo its real value
    assert singles[1] == (1, 2, V3.GT)              # leaf 1 (value 3) GreaterThan 2


def test_proofnodes_roundtrip_length():
    b = V3._proofnodes(_V["multiproof"]["hashes"])
    # 4-byte vec len + 2 * (32 hash + 1 flag)
    assert b[:4] == struct.pack("<I", 2)
    assert len(b) == 4 + 2 * 33


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))

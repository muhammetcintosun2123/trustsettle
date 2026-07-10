"""
trustsettle/settle/keeper.py

Autonomous Settlement Keeper (Liquidator) for TrustSettle.

In real DeFi protocols, smart contracts cannot wake themselves up. When a prediction
market is matched and the fixture concludes, someone must submit the Merkle proof
to trigger the CPI payout.

This Keeper bot runs continuously in the background. It:
1. Scans Solana devnet for all active TrustSettle Market accounts using getProgramAccounts.
2. Identifies markets that are MATCHED (both maker and taker have escrowed).
3. Queries the TxODDS API for the official score of the fixture.
4. If the score is finalized and the Merkle proof is available, the Keeper autonomously
   builds the CPI settlement transaction and pays the winner.

This proves that TrustSettle is a fully decentralized, permissionless DeFi primitive
where any Keeper can run the crank.
"""
import time
import base64
import struct
import json
from typing import List

from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from solders.message import Message
from solders.transaction import Transaction as SolTx
from solders.hash import Hash as SolHash

from settle import onchain_market as OM

def fetch_active_markets() -> List[dict]:
    """Fetch all TrustSettle market accounts on devnet."""
    print("📡 [Keeper] Scanning devnet for active TrustSettle markets...")
    # The TrustSettle program ID
    program_id = str(OM.PROGRAM)
    
    # We use getProgramAccounts to fetch all state accounts owned by the program.
    resp = OM._rpc("getProgramAccounts", [
        program_id,
        {
            "encoding": "base64",
            "filters": [
                {"dataSize": 53} # TrustSettle market state account size
            ]
        }
    ])
    
    markets = []
    if not resp or "error" in resp or "result" not in resp:
        return markets
        
    for account in resp["result"]:
        pubkey = account["pubkey"]
        data = base64.b64decode(account["account"]["data"][0])
        
        # Parse the TrustSettle native layout:
        # state(u8), market_id(u64), fixture_id(i64), stat_key(u32), threshold(i32)
        # comparison(u8), event_root(32), total_pool(u64)
        if len(data) >= 53:
            state = data[0]
            market_id = struct.unpack_from("<Q", data, 1)[0]
            fixture_id = struct.unpack_from("<q", data, 9)[0]
            stat_key = struct.unpack_from("<I", data, 17)[0]
            
            markets.append({
                "pubkey": pubkey,
                "state": state,
                "market_id": market_id,
                "fixture_id": fixture_id,
                "stat_key": stat_key
            })
            
    return markets

def run_keeper_loop():
    """Run the continuous Keeper crank."""
    print("==================================================================")
    print(" 🛡️  TrustSettle Autonomous Keeper (Liquidator) started")
    print("     Scanning for matches awaiting settlement...")
    print("==================================================================")
    
    OM.L.set_network("devnet")
    kp = OM.load_key()
    maker = kp.pubkey()
    
    while True:
        try:
            markets = fetch_active_markets()
            matched_markets = [m for m in markets if m["state"] == 1] # 1 = MATCHED in our layout
            
            print(f"📊 [Keeper] Found {len(markets)} total markets. {len(matched_markets)} are matched and awaiting settlement.")
            
            for m in matched_markets:
                print(f"   ▶ Found awaiting market: {m['pubkey']} (Fixture {m['fixture_id']}, Stat {m['stat_key']})")
                
                # Fetch proof from TxODDS
                print(f"   ⏳ Querying TxODDS API for fixture {m['fixture_id']} score proof...")
                v = OM.F.get(f"/api/scores/stat-validation?fixtureId={m['fixture_id']}&seq=941&statKey={m['stat_key']}")
                
                if not v or "statToProve" not in v:
                    print("   ❌ Proof not yet available. Waiting for TxODDS to finalize.")
                    continue
                    
                print("   ✅ Proof available! Building autonomous settlement transaction...")
                
                value = v["statToProve"]["value"]
                min_ts = v["summary"]["updateStats"]["minTimestamp"]
                daily_roots_pda = OM.daily_pda(min_ts)
                
                validate_stat_data = OM.build_validate_stat(v)
                pd = bytes([2]) + struct.pack("<i", value) + validate_stat_data
                
                ix = Instruction(OM.PROGRAM, pd, [
                    AccountMeta(Pubkey.from_string(m["pubkey"]), False, True),
                    AccountMeta(maker, False, True), # Keeper receives the bounty/funds
                    AccountMeta(OM.TXORACLE, False, False),
                    AccountMeta(daily_roots_pda, False, False),
                ])
                
                try:
                    sig = OM.send([ix], kp, "keeper_settle")
                    print(f"   🎯 SUCCESSFULLY SETTLED MARKET ON-CHAIN!")
                    print(f"   🔗 Transaction: https://explorer.solana.com/tx/{sig}?cluster=devnet")
                except Exception as e:
                    print(f"   ⚠️ Settlement failed (perhaps already settled or invalid state): {e}")
                    
        except Exception as e:
            print(f"⚠️ [Keeper Error]: {e}")
            
        print("💤 [Keeper] Sleeping for 60 seconds before next scan...\n")
        time.sleep(60)

if __name__ == "__main__":
    run_keeper_loop()

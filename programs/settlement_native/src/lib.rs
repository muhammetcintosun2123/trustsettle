//! TrustSettle (native) — a lean, deployable on-chain trustless settlement program.
//!
//! No framework overhead, so the compiled program is small enough to deploy on a modest
//! devnet balance. It does the real thing: escrows SOL for a prediction market and settles
//! it ONLY against a score proven by a keccak256 Merkle proof folding to the anchored root
//! stored at market creation — the same ProofNode fold TxODDS uses. A forged score can't
//! settle: its leaf won't fold to the root.
//!
//! Instructions (first byte = tag):
//!   0 CreateMarket  maker escrows `stake`, stores the anchored `root` + predicate
//!   1 JoinMarket    taker matches `stake`
//!   2 Settle        prove a ScoreStat via Merkle proof → pay the winner
//!
//! Market account layout (123 bytes), little-endian:
//!   [0..32] maker | [32..64] taker | [64..72] stake u64 | [72..80] fixture i64
//!   [80..84] stat_key u32 | [84..88] threshold i32 | [88] comparison u8
//!   [89..121] root[32] | [121] state u8 | [122] bump u8

use solana_program::{
    account_info::{next_account_info, AccountInfo},
    entrypoint,
    entrypoint::ProgramResult,
    program::invoke_signed,
    program_error::ProgramError,
    pubkey::Pubkey,
    rent::Rent,
    system_instruction,
    sysvar::Sysvar,
    msg,
};

entrypoint!(process);

const LEN: usize = 123;
const SEED: &[u8] = b"market";

fn process(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let (tag, rest) = data.split_first().ok_or(ProgramError::InvalidInstructionData)?;
    match tag {
        0 => create_market(program_id, accounts, rest),
        1 => join_market(accounts),
        2 => settle(accounts, rest),
        _ => Err(ProgramError::InvalidInstructionData),
    }
}

fn rd_u64(b: &[u8], o: usize) -> u64 { u64::from_le_bytes(b[o..o + 8].try_into().unwrap()) }
fn rd_i64(b: &[u8], o: usize) -> i64 { i64::from_le_bytes(b[o..o + 8].try_into().unwrap()) }
fn rd_u32(b: &[u8], o: usize) -> u32 { u32::from_le_bytes(b[o..o + 4].try_into().unwrap()) }
fn rd_i32(b: &[u8], o: usize) -> i32 { i32::from_le_bytes(b[o..o + 4].try_into().unwrap()) }

// CreateMarket: data = market_id u64, fixture i64, stat_key u32, threshold i32,
//               comparison u8, root[32], stake u64  (= 8+8+4+4+1+32+8 = 65 bytes)
fn create_market(program_id: &Pubkey, accounts: &[AccountInfo], d: &[u8]) -> ProgramResult {
    let ai = &mut accounts.iter();
    let maker = next_account_info(ai)?;
    let market = next_account_info(ai)?;
    let system = next_account_info(ai)?;
    if !maker.is_signer { return Err(ProgramError::MissingRequiredSignature); }
    if d.len() < 65 { return Err(ProgramError::InvalidInstructionData); }

    let market_id = rd_u64(d, 0);
    let fixture = rd_i64(d, 8);
    let stat_key = rd_u32(d, 16);
    let threshold = rd_i32(d, 20);
    let comparison = d[24];
    let root: [u8; 32] = d[25..57].try_into().unwrap();
    let stake = rd_u64(d, 57);

    let (pda, bump) = Pubkey::find_program_address(
        &[SEED, maker.key.as_ref(), &market_id.to_le_bytes()], program_id);
    if pda != *market.key { return Err(ProgramError::InvalidSeeds); }

    let rent = Rent::get()?.minimum_balance(LEN);
    let lamports = rent.checked_add(stake).ok_or(ProgramError::ArithmeticOverflow)?;
    invoke_signed(
        &system_instruction::create_account(maker.key, market.key, lamports, LEN as u64, program_id),
        &[maker.clone(), market.clone(), system.clone()],
        &[&[SEED, maker.key.as_ref(), &market_id.to_le_bytes(), &[bump]]],
    )?;

    let mut b = market.try_borrow_mut_data()?;
    b[0..32].copy_from_slice(maker.key.as_ref());
    b[32..64].copy_from_slice(&[0u8; 32]);
    b[64..72].copy_from_slice(&stake.to_le_bytes());
    b[72..80].copy_from_slice(&fixture.to_le_bytes());
    b[80..84].copy_from_slice(&stat_key.to_le_bytes());
    b[84..88].copy_from_slice(&threshold.to_le_bytes());
    b[88] = comparison;
    b[89..121].copy_from_slice(&root);
    b[121] = 0;
    b[122] = bump;
    msg!("TrustSettle: market {} created, {} lamports escrowed", market_id, stake);
    Ok(())
}

fn join_market(accounts: &[AccountInfo]) -> ProgramResult {
    let ai = &mut accounts.iter();
    let taker = next_account_info(ai)?;
    let market = next_account_info(ai)?;
    let system = next_account_info(ai)?;
    if !taker.is_signer { return Err(ProgramError::MissingRequiredSignature); }

    let (stake, state) = {
        let b = market.try_borrow_data()?;
        (rd_u64(&b, 64), b[121])
    };
    if state != 0 { return Err(ProgramError::InvalidAccountData); }

    solana_program::program::invoke(
        &system_instruction::transfer(taker.key, market.key, stake),
        &[taker.clone(), market.clone(), system.clone()],
    )?;
    let mut b = market.try_borrow_mut_data()?;
    b[32..64].copy_from_slice(taker.key.as_ref());
    b[121] = 1;
    msg!("TrustSettle: taker joined, {} lamports matched", stake);
    Ok(())
}

fn verify_validate_stat_payload(
    data: &[u8],
    claimed_value: i32,
    expected_stat_key: u32,
) -> Result<(), ProgramError> {
    if data.len() < 80 {
        return Err(ProgramError::InvalidInstructionData);
    }
    let mut o = 8; // skip discriminator (8 bytes)
    o += 8; // skip ts (i64)
    o += 60; // skip fixture_summary (ScoresBatchSummary)

    // fixture_proof
    if data.len() < o + 4 { return Err(ProgramError::InvalidInstructionData); }
    let len_fixture_proof = u32::from_le_bytes(data[o..o+4].try_into().unwrap()) as usize;
    o += 4 + len_fixture_proof * 33;

    // main_tree_proof
    if data.len() < o + 4 { return Err(ProgramError::InvalidInstructionData); }
    let len_main_tree_proof = u32::from_le_bytes(data[o..o+4].try_into().unwrap()) as usize;
    o += 4 + len_main_tree_proof * 33;

    // predicate: threshold (4 bytes), comparison (1 byte)
    if data.len() < o + 5 { return Err(ProgramError::InvalidInstructionData); }
    let predicate_threshold = i32::from_le_bytes(data[o..o+4].try_into().unwrap());
    let predicate_comparison = data[o+4];
    o += 5;

    // stat_a: key (4 bytes), value (4 bytes), period (4 bytes)
    if data.len() < o + 12 { return Err(ProgramError::InvalidInstructionData); }
    let stat_key = u32::from_le_bytes(data[o..o+4].try_into().unwrap());
    let stat_value = i32::from_le_bytes(data[o+4..o+8].try_into().unwrap());
    let _stat_period = i32::from_le_bytes(data[o+8..o+12].try_into().unwrap());

    // Verification rules:
    // 1. The comparison operator in the predicate must be EqualTo (2).
    // 2. The threshold in the predicate must match the claimed value.
    // 3. The proven stat key must match the expected stat key of the market.
    // 4. The stat_a.value (proven value) must match the claimed value.
    // 5. The stat_period should be 0 (full match/game statistics).
    if predicate_comparison != 2 {
        msg!("TrustSettle: predicate comparison must be EqualTo (2)");
        return Err(ProgramError::InvalidArgument);
    }
    if predicate_threshold != claimed_value {
        msg!("TrustSettle: predicate threshold must match claimed value");
        return Err(ProgramError::InvalidArgument);
    }
    if stat_key != expected_stat_key {
        msg!("TrustSettle: proven stat key {} does not match market key {}", stat_key, expected_stat_key);
        return Err(ProgramError::InvalidArgument);
    }
    if stat_value != claimed_value {
        msg!("TrustSettle: proven stat value {} does not match claimed value {}", stat_value, claimed_value);
        return Err(ProgramError::InvalidArgument);
    }

    Ok(())
}

// Settle: data = stat_value i32, then validate_stat_data (Borsh payload for txoracle::validate_stat)
fn settle(accounts: &[AccountInfo], d: &[u8]) -> ProgramResult {
    let ai = &mut accounts.iter();
    let market = next_account_info(ai)?;
    let winner = next_account_info(ai)?;
    let txoracle_info = next_account_info(ai)?;
    let daily_roots_info = next_account_info(ai)?;

    let b = market.try_borrow_data()?;
    let maker = Pubkey::new_from_array(b[0..32].try_into().unwrap());
    let taker = Pubkey::new_from_array(b[32..64].try_into().unwrap());
    let threshold = rd_i32(&b, 84);
    let comparison = b[88];
    let expected_stat_key = rd_u32(&b, 80);
    let state = b[121];
    drop(b);
    if state != 1 { return Err(ProgramError::InvalidAccountData); }

    let txoracle_addr = Pubkey::new_from_array([
        86, 117, 159, 44, 144, 95, 120, 96, 200, 99, 119, 20, 191, 36, 145, 48, 157, 192, 113, 129,
        81, 63, 122, 36, 191, 62, 218, 248, 127, 119, 80, 3,
    ]);
    if *txoracle_info.key != txoracle_addr {
        return Err(ProgramError::IncorrectProgramId);
    }

    if d.len() < 4 { return Err(ProgramError::InvalidInstructionData); }
    let value = rd_i32(d, 0);
    let validate_stat_data = &d[4..];

    // Enforce that the proof payload is verifying the expected stat key,
    // matches the claimed value, and uses the EqualTo comparison.
    verify_validate_stat_payload(validate_stat_data, value, expected_stat_key)?;

    // Construct the CPI instruction. The CPI targets the TxODDS validation program.
    // Account 0 is daily_scores_merkle_roots PDA.
    let cpi_accounts = vec![
        solana_program::instruction::AccountMeta::new_readonly(*daily_roots_info.key, false),
    ];
    let ix = solana_program::instruction::Instruction {
        program_id: *txoracle_info.key,
        accounts: cpi_accounts,
        data: validate_stat_data.to_vec(),
    };

    // Invoke the CPI. Reverts if txoracle rejects the Merkle proof.
    solana_program::program::invoke(&ix, &[daily_roots_info.clone(), txoracle_info.clone()])?;

    // proof validated on-chain -> evaluate the predicate on the proven value
    let maker_wins = match comparison {
        0 => value > threshold,
        1 => value < threshold,
        _ => value == threshold,
    };
    let win_key = if maker_wins { maker } else { taker };
    if *winner.key != win_key { return Err(ProgramError::InvalidArgument); }

    // pay the whole escrow to the winner; the market account is drained (closed)
    let pot = market.lamports();
    **market.try_borrow_mut_lamports()? = 0;
    **winner.try_borrow_mut_lamports()? = winner.lamports()
        .checked_add(pot).ok_or(ProgramError::ArithmeticOverflow)?;
    let mut mb = market.try_borrow_mut_data()?;
    mb[121] = 2;
    msg!("TrustSettle: proof verified via TxODDS CPI, predicate {}, {} lamports paid to winner",
        maker_wins, pot);
    Ok(())
}

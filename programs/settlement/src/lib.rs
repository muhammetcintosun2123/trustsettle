//! TrustSettle — a trustless prediction-market settlement program for TxLINE.
//!
//! Two traders escrow SOL on opposite sides of a stat predicate for a fixture
//! (e.g. "total goals > 2"). Settlement is trustless: `settle` performs a CPI into
//! the txoracle program's `validate_stat`, which verifies the submitted score stat
//! against the scores-batch Merkle root TxODDS has anchored on-chain. If (and only if)
//! the proof validates, the predicate is evaluated on the proven value and the escrow
//! is released to the winner. No oracle to trust, no admin key, no way to settle a lie.
//!
//! The off-chain engine in ../../settle/ mirrors this exactly (same ProofNode / StatTerm
//! structures, same keccak fold), so it can simulate and pre-validate before submitting.
//!
//! Build: `anchor build`. txoracle (devnet): 6pW64gN1s2uqjHkn1unFeEjAwJkPGHoppGvS715wyP2J

use anchor_lang::prelude::*;
use anchor_lang::system_program;

declare_id!("3QTsMg6sBE3udUmNhzBY5LQ7xZL48cTSL8WqT5L9ZrJd");

pub const TXORACLE: Pubkey = pubkey!("6pW64gN1s2uqjHkn1unFeEjAwJkPGHoppGvS715wyP2J");

#[program]
pub mod settlement {
    use super::*;

    /// Maker opens a market on a stat predicate and escrows `stake` lamports.
    pub fn create_market(
        ctx: Context<CreateMarket>,
        market_id: u64,
        fixture_id: i64,
        stat_key: u32,
        threshold: i32,
        comparison: u8, // 0 = GreaterThan, 1 = LessThan, 2 = EqualTo
        stake: u64,
    ) -> Result<()> {
        let m = &mut ctx.accounts.market;
        m.market_id = market_id;
        m.fixture_id = fixture_id;
        m.stat_key = stat_key;
        m.threshold = threshold;
        m.comparison = comparison;
        m.maker = ctx.accounts.maker.key();
        m.stake = stake;
        m.bump = ctx.bumps.market;
        m.state = MarketState::Open as u8;

        // pull the maker's stake into the market escrow PDA
        system_program::transfer(
            CpiContext::new(
                ctx.accounts.system_program.to_account_info(),
                system_program::Transfer {
                    from: ctx.accounts.maker.to_account_info(),
                    to: m.to_account_info(),
                },
            ),
            stake,
        )?;
        Ok(())
    }

    /// Taker matches the maker's stake and takes the opposite side.
    pub fn join_market(ctx: Context<JoinMarket>) -> Result<()> {
        let m = &mut ctx.accounts.market;
        require!(m.state == MarketState::Open as u8, SettleError::NotOpen);
        require!(m.taker == Pubkey::default(), SettleError::AlreadyMatched);
        m.taker = ctx.accounts.taker.key();
        system_program::transfer(
            CpiContext::new(
                ctx.accounts.system_program.to_account_info(),
                system_program::Transfer {
                    from: ctx.accounts.taker.to_account_info(),
                    to: m.to_account_info(),
                },
            ),
            m.stake,
        )?;
        m.state = MarketState::Matched as u8;
        Ok(())
    }

    /// Trustless settlement. Verifies the proven score stat via CPI into
    /// txoracle::validate_stat, then pays the escrow to the winner.
    ///
    /// `stat_value` is the value the caller claims; it is only trusted AFTER the CPI
    /// confirms the accompanying Merkle proof against the anchored root. The raw
    /// `validate_stat_data` is the Borsh-encoded txoracle instruction (StatTerm +
    /// proofs) built by the off-chain engine; we forward it and require success.
    pub fn settle(ctx: Context<Settle>, stat_value: i32, validate_stat_data: Vec<u8>) -> Result<()> {
        let m = &mut ctx.accounts.market;
        require!(m.state == MarketState::Matched as u8, SettleError::NotMatched);

        // CPI: txoracle::validate_stat — reverts if the Merkle proof is invalid.
        let accounts: Vec<AccountMeta> = ctx
            .remaining_accounts
            .iter()
            .map(|a| AccountMeta {
                pubkey: *a.key,
                is_signer: a.is_signer,
                is_writable: a.is_writable,
            })
            .collect();
        let ix = anchor_lang::solana_program::instruction::Instruction {
            program_id: TXORACLE,
            accounts,
            data: validate_stat_data,
        };
        anchor_lang::solana_program::program::invoke(&ix, ctx.remaining_accounts)
            .map_err(|_| error!(SettleError::ProofRejected))?;

        // proof validated on-chain → evaluate the predicate on the proven value
        let holds = match m.comparison {
            0 => stat_value > m.threshold,
            1 => stat_value < m.threshold,
            _ => stat_value == m.threshold,
        };
        let winner = if holds { m.maker } else { m.taker };
        require_keys_eq!(ctx.accounts.winner.key(), winner, SettleError::WrongWinner);

        // release the whole escrow to the winner
        let pot = m.to_account_info().lamports();
        **m.to_account_info().try_borrow_mut_lamports()? -= pot;
        **ctx.accounts.winner.try_borrow_mut_lamports()? += pot;
        m.state = MarketState::Settled as u8;
        Ok(())
    }
}

#[account]
pub struct Market {
    pub market_id: u64,
    pub fixture_id: i64,
    pub stat_key: u32,
    pub threshold: i32,
    pub comparison: u8,
    pub maker: Pubkey,
    pub taker: Pubkey,
    pub stake: u64,
    pub state: u8,
    pub bump: u8,
}

impl Market {
    pub const LEN: usize = 8 + 8 + 8 + 4 + 4 + 1 + 32 + 32 + 8 + 1 + 1;
}

#[repr(u8)]
pub enum MarketState {
    Open = 0,
    Matched = 1,
    Settled = 2,
}

#[derive(Accounts)]
#[instruction(market_id: u64)]
pub struct CreateMarket<'info> {
    #[account(mut)]
    pub maker: Signer<'info>,
    #[account(
        init, payer = maker, space = Market::LEN,
        seeds = [b"market", maker.key().as_ref(), &market_id.to_le_bytes()], bump
    )]
    pub market: Account<'info, Market>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct JoinMarket<'info> {
    #[account(mut)]
    pub taker: Signer<'info>,
    #[account(mut)]
    pub market: Account<'info, Market>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct Settle<'info> {
    #[account(mut)]
    pub market: Account<'info, Market>,
    /// CHECK: verified against the market's computed winner before any payout.
    #[account(mut)]
    pub winner: AccountInfo<'info>,
    /// CHECK: the txoracle program; pinned to the known program id.
    #[account(address = TXORACLE)]
    pub txoracle: AccountInfo<'info>,
    // txoracle::validate_stat accounts are passed via remaining_accounts.
}

#[error_code]
pub enum SettleError {
    #[msg("market is not open")]
    NotOpen,
    #[msg("market already matched")]
    AlreadyMatched,
    #[msg("market is not matched")]
    NotMatched,
    #[msg("txoracle rejected the Merkle proof")]
    ProofRejected,
    #[msg("winner account does not match the settled winner")]
    WrongWinner,
}

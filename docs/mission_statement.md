# Mission Statement & Strategic Plan

## Nexus Alpha — AI-Driven Quantitative Trading Operation

---

## Mission

Build a self-improving, AI-managed portfolio that generates consistent monthly income across US equities, options, and crypto — with capital preservation as the primary constraint and compounding growth as the engine.

The system is designed so that one person (the CEO) can operate it without writing code, by directing a team of specialized AI agents that research, build, test, and monitor systematic trading strategies.

---

## Core Principles

### 1. Don't lose money
Capital preservation comes first, always. A 50% drawdown requires a 100% return to recover. At under $25K starting capital, every dollar lost is disproportionately painful. The system is designed to be paranoid about risk before it is ambitious about returns.

### 2. Compound, don't gamble
The goal is not to find one big trade. The goal is to find repeatable edges that compound over months and years. A 2% monthly return sounds boring. It's 26.8% annualized. That's elite hedge fund territory.

### 3. Let AI do the work, human makes the calls
AI agents research, code, test, and monitor. The CEO sets direction, reviews output, and makes every capital allocation decision. No agent can deploy money. No agent runs unsupervised in live markets.

### 4. Earn the right to scale
Start small. Prove the system works on paper. Prove it works with real money at small size. Only then increase allocation. Impatience is the biggest risk at this capital level.

### 5. Multi-asset diversification is the edge
Most retail quant traders focus on one asset class. Running systematic strategies across equities/ETFs, options, and crypto creates diversification that reduces drawdowns and smooths income — because these markets don't move in lockstep.

---

## Strategic Reality Check

### What $25K means

With under $25K, there are real constraints to work within honestly:

**Pattern Day Trader rule (PDT):** Under $25K in a margin account, you're limited to 3 day trades per 5 rolling business days in US equities/options. This means the system must favor swing trades (multi-day holds) or use a cash account (which has settlement delays but no PDT limit). Crypto is exempt from PDT.

**Position sizing:** With $25K total, risking 1% per trade means $250 max loss per position. This limits position sizes and filters out strategies that require large notional exposure.

**Options constraints:** Small accounts can sell cash-secured puts and covered calls, but capital-intensive strategies (iron condors, straddles) tie up significant buying power. Focus on defined-risk strategies.

**Crypto advantage:** No PDT rules, 24/7 markets, many exchanges allow small position sizes. This is where the system can be most active in the early phase.

**Commission impact:** Even "zero commission" brokers have spreads and options contract fees ($0.50-0.65/contract). At small sizes, these costs matter. The system must model them accurately.

---

## Target Performance Metrics

| Metric | Target | Why |
|--------|--------|-----|
| Monthly return | 1.5 - 3.0% | Consistent income goal; 18-36% annualized |
| Max drawdown | < 10% | Capital preservation priority; at $25K, a 10% drawdown = $2,500 loss |
| Sharpe ratio | > 1.5 | Risk-adjusted returns above market benchmarks |
| Win rate | > 55% | Slight edge, compounded over many trades |
| Max single-trade loss | 1% of capital | $250 max loss per position at $25K |
| Monthly trade count | 15 - 40 | Enough for statistical significance, not so many that costs eat returns |
| Correlation between strategies | < 0.4 | True diversification across asset classes |
| Time to first live dollar | 90 days | System validation before any real capital deployed |

---

## Asset Class Strategy

### Tier 1: US Equities & ETFs (40% allocation target)

**Why:** Most liquid, most data available, best backtesting infrastructure. The knowledge base is deepest here (Quantopian patterns, academic literature).

**Strategy focus:**
- Swing momentum (5-20 day holds) to avoid PDT constraints
- Sector rotation across ETFs (XLF, XLE, XLK, XLV, etc.)
- Volatility-scaled position sizing
- Mean reversion on liquid large-caps (3-5 day holds)

**Constraints:**
- PDT-aware: max 3 round trips per week if margin account
- Minimum $10 stock price, 500K avg daily volume
- No earnings-week entries (binary risk too high at this capital level)

### Tier 2: Options (30% allocation target)

**Why:** Defined risk, income generation potential, leverage without margin. Options are the primary income engine for a small account.

**Strategy focus:**
- Cash-secured puts on high-quality ETFs (SPY, QQQ, IWM) — collect premium, acquire at discount
- Covered calls on equity positions — enhance yield on holdings
- Credit spreads (put spreads, call spreads) — defined risk, consistent premium collection
- Wheel strategy (sell put → get assigned → sell calls → get called away → repeat)

**Constraints:**
- Only defined-risk strategies (no naked options)
- Max 20% of capital in any single underlying
- Minimum 30 DTE (days to expiration) for premium selling — avoids gamma risk
- Close at 50% profit or 21 DTE, whichever comes first

### Tier 3: Crypto (30% allocation target)

**Why:** No PDT rules, 24/7 markets, high volatility creates more opportunities for systematic strategies, lower correlation with equities.

**Strategy focus:**
- Momentum/trend following on BTC and ETH (the only assets with enough liquidity and history)
- Mean reversion on BTC/ETH during range-bound periods
- Funding rate arbitrage (on perpetual futures, if exchange allows)
- Volatility breakout strategies

**Constraints:**
- Only BTC and ETH for systematic trading (altcoins lack reliable data and liquidity)
- Tighter stops (2% max per trade) — crypto volatility is 3-5x equities
- No leverage above 2x
- Exchange risk: keep only trading capital on exchange, rest in cold storage or stablecoin

---

## Phased Roadmap

### Phase 0: Foundation (Weeks 1-2)
**CEO focus:** Set up infrastructure, hire first agents

Milestones:
- [ ] Set up broker accounts (equities/options + crypto exchange)
- [ ] Install orchestrator and seed knowledge base with 6 Quantopian patterns
- [ ] Create system prompts for core agents (Research Director, Strategy Coder, Backtest Runner, Overfit Detector)
- [ ] Run first 5 automated iterations to verify the loop works
- [ ] Verify data feeds (yfinance for equities, exchange API for crypto)

**Capital deployed: $0**

### Phase 1: Backtest Discovery (Weeks 3-6)
**CEO focus:** Direct research, review iterations, learn what works

Milestones:
- [ ] Run 30-50 iterations across all three asset classes
- [ ] Identify 3-5 strategies that pass Gate 1 (backtest qualification)
- [ ] Build walk-forward and parameter sensitivity analysis into the pipeline
- [ ] First knowledge base review — what patterns are emerging?
- [ ] Add Market Regime agent

**Capital deployed: $0**

**CEO review cadence:** Daily 10-min iteration review, weekly strategy direction meeting

### Phase 2: Paper Validation (Weeks 7-14)
**CEO focus:** Monitor paper trading, compare to backtest expectations

Milestones:
- [ ] Deploy 2-3 passing strategies to paper trading (Alpaca for equities/options, exchange testnet for crypto)
- [ ] Minimum 30 days paper trading per strategy
- [ ] Compare paper results to backtest expectations (within 1 standard deviation)
- [ ] Add Execution Quality agent
- [ ] Gate 2 reviews: decide which strategies earn live capital

**Capital deployed: $0**

**CEO review cadence:** Daily paper trading check, weekly performance comparison

### Phase 3: Small Live (Months 4-6)
**CEO focus:** First real money, tight monitoring, prove the system in live markets

Milestones:
- [ ] Deploy first strategy with 5% of capital ($1,250) per strategy
- [ ] Maximum 3 live strategies simultaneously in this phase
- [ ] Establish daily P&L monitoring routine
- [ ] 60 days minimum at small allocation before scaling
- [ ] Gate 3 reviews: decide which strategies earn full allocation
- [ ] Add Portfolio Monitor agent with automated alerts

**Capital deployed: $3,750 max (15% of $25K across 3 strategies)**

**CEO review cadence:** Daily P&L check, weekly strategy review, monthly full portfolio review

### Phase 4: Scale to Target (Months 7-12)
**CEO focus:** Grow allocations, add strategies, build toward target income

Milestones:
- [ ] Scale proven strategies to target allocation (15-25% each)
- [ ] Portfolio of 3-5 uncorrelated live strategies across all three asset classes
- [ ] Automated monitoring and alerting fully operational
- [ ] Monthly income hitting $375-$750/month target (1.5-3% of $25K)
- [ ] Knowledge base has 50+ learnings
- [ ] First portfolio rebalance based on strategy correlation analysis

**Capital deployed: up to 80% of $25K ($20,000)**

**CEO review cadence:** Daily automated briefing, bi-weekly strategy review, monthly portfolio optimization

### Phase 5: Compound & Expand (Year 2+)
**CEO focus:** Reinvest profits, expand to new strategies, potentially increase capital base

Milestones:
- [ ] Reinvest 80% of profits, withdraw 20% as income
- [ ] Cross $50K account value (doubles starting capital)
- [ ] Explore additional asset classes or strategy complexity (spreads, multi-leg options)
- [ ] Consider adding external capital (friends/family fund structure) if performance warrants
- [ ] The system should largely run itself with CEO making gate decisions only

**Target:** $50K+ portfolio generating $750-$1,500/month

---

## Risk Management Constitution

These rules cannot be overridden by any agent. Only the CEO can modify them, and only after a formal review.

1. **No single trade can lose more than 1% of total capital.** At $25K, that's $250.
2. **No single strategy can hold more than 25% of total capital.**
3. **Total portfolio exposure never exceeds 80%.** 20% stays in cash or stablecoins.
4. **No strategy goes live without passing all three gates** (backtest → paper → small live).
5. **Any strategy that hits 1.5x its backtest max drawdown is automatically demoted to paper.**
6. **No leverage above 2x on any position, any asset class.**
7. **No new strategy deployment during the first or last 30 minutes of US market hours** (highest volatility, worst fills).
8. **Monthly risk review is mandatory.** If the CEO skips it, all live strategies pause until the review is completed.
9. **If total portfolio drawdown exceeds 8%, pause all live trading for 48 hours** and conduct a full review before resuming.
10. **No agent can execute a live trade.** All live order routing requires explicit CEO approval or a pre-approved automated rule that the CEO has reviewed and signed off on.

---

## Success Metrics by Timeframe

| Timeframe | What success looks like |
|-----------|------------------------|
| 30 days | Orchestrator running, first 20 iterations complete, learning loop works |
| 90 days | 2-3 strategies in paper trading, paper results match backtest within reason |
| 6 months | First strategies live with real money, generating small but consistent returns |
| 12 months | Portfolio of 3-5 live strategies, monthly income of $375-$750, max drawdown under 10% |
| 24 months | Portfolio grown to $50K+ through compounding, system is self-sustaining with minimal CEO time |

---

## What This Is Not

This is not a get-rich-quick scheme. This is not a way to turn $25K into $1M in a year. This is a systematic, disciplined approach to building a compounding income machine — where the AI does the research and the human makes the judgment calls.

The edge isn't in any single strategy. The edge is in the system: the ability to research, test, deploy, monitor, and iterate faster than a human could alone, while maintaining the discipline that most retail traders lack.

The CEO's most important job is patience.

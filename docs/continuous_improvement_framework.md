# Continuous Improvement Framework

## Purpose

This document defines the feedback loop architecture that turns a one-off backtesting exercise into a self-improving system. It covers the iteration cycle, overfitting safeguards, performance tracking, promotion pipeline, and long-term maintenance practices.

---

## The Five-Stage Feedback Loop

```
    ┌──────────────────────────────────────────────────────┐
    │                                                      │
    ▼                                                      │
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐  │   ┌──────────┐
│ PROPOSE │───▶│  TEST   │───▶│ EVALUATE│───▶│  LEARN  │──┘   │  DEPLOY  │
│         │    │         │    │         │    │         │──────▶│ (gated)  │
└─────────┘    └─────────┘    └─────────┘    └─────────┘       └──────────┘
  Claude         VectorBT       Claude        Knowledge        Paper → Live
  generates      backtests      analyzes      base updated     with criteria
  strategy       IS + OOS       results       iteration log
```

---

## Stage 1: Propose

**Owner:** Claude (via Anthropic API)

**Inputs:**
- Strategy knowledge base (seeded patterns + accumulated learnings)
- Last 5-10 iteration summaries (what was tried, what happened)
- Current acceptance criteria
- Available data universe and time periods

**Process:**
Claude proposes a strategy with the following requirements:
- Must state a falsifiable hypothesis (not "this might work" but "short-term RSI extremes revert within 5 days because of liquidity provider behavior")
- Must explain what changed from the prior iteration and why
- Must declare parameter count (reject if > max allowed)
- Must generate executable backtest code

**Key Constraint:** Claude should NOT randomly explore the strategy space. Each proposal should logically follow from prior learnings. If the last 3 momentum strategies failed, don't try a 4th momentum variant — pivot to mean reversion or factor-based approaches.

**Anti-Patterns to Avoid:**
- Proposing the same strategy with slightly tweaked parameters (that's overfitting, not learning)
- Increasing complexity to chase better in-sample numbers
- Ignoring prior failure analysis

---

## Stage 2: Test

**Owner:** Automated (VectorBT or Backtrader)

**Process:**

### Primary Backtest
Run the strategy on two separate data windows:
- **In-Sample (IS):** The training period (e.g., 2018-2022). This is what Claude "knows about" when designing the strategy.
- **Out-of-Sample (OOS):** The validation period (e.g., 2023-2024). This tests whether the pattern generalizes.

### Standard Metrics to Capture
| Metric | What It Tells You |
|--------|-------------------|
| Sharpe Ratio | Risk-adjusted return (target: > 1.0 IS, > 0.7 OOS) |
| Max Drawdown | Worst peak-to-trough loss (target: < 20%) |
| Calmar Ratio | Annual return / max drawdown |
| Total Trades | Statistical significance (target: > 50-100) |
| Win Rate | Percentage of winning trades |
| Profit Factor | Gross profit / gross loss (target: > 1.5) |
| Average Trade Duration | Holding period |
| Turnover | How often the portfolio changes (affects transaction costs) |
| IS/OOS Sharpe Gap | Overfitting indicator (target: < 0.5 gap) |

### Walk-Forward Analysis (for strategies that pass initial screening)
Instead of a single IS/OOS split, roll the windows forward:

```
Window 1: Train 2015-2017, Test 2018 H1
Window 2: Train 2015.5-2018, Test 2018 H2
Window 3: Train 2016-2019, Test 2019 H1
... and so on
```

This produces a distribution of OOS Sharpe ratios rather than a single number. A strategy with consistent OOS performance across windows is far more trustworthy.

### Parameter Sensitivity Analysis (for strategies that pass walk-forward)
Vary each parameter +/- 20% from its chosen value. If the Sharpe ratio changes drastically, the strategy is likely overfit to specific parameter values. Robust strategies show a "plateau" — performance stays in a reasonable range across parameter variations.

### Transaction Cost Modeling
Always include realistic estimates:
- Commission: depends on broker (Alpaca = $0, IBKR = $0.005/share)
- Slippage: 0.05-0.10% per trade for liquid names, more for small-caps
- Short borrowing: 1-5% annualized for general collateral, much more for hard-to-borrow
- Market impact: relevant for strategies trading > $1M notional

---

## Stage 3: Evaluate

**Owner:** Claude (via Anthropic API)

**Inputs:**
- All metrics from Stage 2
- The original hypothesis
- Prior iteration context

**Process:**
Claude evaluates along these dimensions:

### Pass/Fail Against Criteria
Binary check against the acceptance thresholds. But passing criteria alone isn't sufficient — see below.

### Overfitting Assessment

| Signal | Risk Level | Action |
|--------|-----------|--------|
| IS Sharpe 2.5, OOS Sharpe 0.5 | High | Reject — huge degradation |
| IS Sharpe 1.5, OOS Sharpe 1.2 | Low | Promising — small gap |
| Walk-forward OOS Sharpe std > 0.5 | High | Inconsistent across periods |
| Strategy works only with exact params | High | Reject — not robust |
| Fewer than 50 OOS trades | Medium | Insufficient evidence |
| Strategy has 6+ parameters | Medium | Complexity penalty |

### Hypothesis Validation
Did the results actually support the hypothesis? Example:
- Hypothesis: "Volume-confirmed Bollinger Band touches revert more reliably"
- Result: Win rate improved from 52% to 58%, but Sharpe only marginally better
- Assessment: Hypothesis partially supported. Volume filter helps accuracy but reduces trade frequency enough that total profit didn't improve much.

### Comparison to Baselines
Every strategy should be compared to simple baselines:
- Buy and hold SPY
- 60/40 portfolio
- Equal-weight monthly rebalance
- Random entry with same position sizing

If a sophisticated strategy can't meaningfully beat equal-weight buy-and-hold, the complexity isn't justified.

---

## Stage 4: Learn

**Owner:** Orchestrator + Claude

**Outputs:**
- Iteration log entry (SQLite)
- Knowledge base learning entry (JSON)
- Updated strategy patterns if applicable

### What Gets Recorded

**For every iteration (pass or fail):**
- Full metrics
- The hypothesis and whether it was supported
- What was tried and what happened
- Implications for future iterations
- Suggested next direction

**For passing strategies:**
- Complete strategy code
- Parameter values and sensitivity results
- Walk-forward distribution
- Promotion recommendation

### Negative Knowledge Is Valuable
Failed iterations are as important as successes. Examples of useful negative knowledge:
- "Adding a volume filter to mean reversion reduced trades but didn't improve risk-adjusted returns — volume doesn't add information for liquid ETFs"
- "Momentum with lookback < 3 months on ETFs is pure noise — not enough trend persistence at that timeframe"
- "Pairs trading on tech stocks broke down in 2020-2021 — regime change invalidated historical cointegration"

### Knowledge Base Evolution
Over time, the knowledge base should develop:
- A map of which strategy categories work for which market regimes
- Empirical bounds on parameter ranges that tend to be robust
- A list of "dead ends" (approaches that have been thoroughly tested and rejected)
- Insights about which alpha factors are orthogonal vs. redundant

---

## Stage 5: Deploy (Gated Promotion Pipeline)

Deployment is not automatic. It follows a strict promotion pipeline with human oversight at each gate.

### Gate 1: Backtest Qualification
```
Requirements:
  ✓ Passes all acceptance criteria (Sharpe, drawdown, trade count)
  ✓ OOS Sharpe within 50% of IS Sharpe
  ✓ Walk-forward analysis shows consistency (OOS Sharpe std < 0.5)
  ✓ Parameter sensitivity: Sharpe doesn't drop > 30% with ±20% param change
  ✓ Beats buy-and-hold SPY Sharpe by > 0.3

→ Promoted to: Paper Trading
```

### Gate 2: Paper Trading Validation
```
Requirements:
  ✓ Minimum 30 days of paper trading
  ✓ Paper results within 1 standard deviation of backtest expectations
  ✓ No unexpected drawdowns (> 1.5x backtest max drawdown)
  ✓ Execution quality acceptable (slippage within modeled assumptions)
  ✓ Human review of trade log (sanity check)

→ Promoted to: Small Live Allocation
```

### Gate 3: Live Scaling
```
Requirements:
  ✓ Minimum 60 days live with small allocation (e.g., 5% of trading capital)
  ✓ Live Sharpe within acceptable range of paper/backtest
  ✓ No operational issues (API failures, order rejections, margin calls)
  ✓ Human review and approval for scaling

→ Promoted to: Target Allocation
```

### Demotion Rules
Strategies can be demoted (moved back a stage or retired) when:
- Live drawdown exceeds 1.5x the backtest max drawdown
- Live Sharpe falls below 50% of backtest Sharpe for 30+ consecutive days
- Market regime changes fundamentally (as identified by regime detection)
- Correlation with existing live strategies exceeds 0.7 (diversification violation)

---

## Overfitting Prevention Framework

This section consolidates all anti-overfitting measures into a single reference.

### Data Hygiene
1. **Never look at OOS data during strategy design.** Claude's proposal prompt includes only IS-period information.
2. **Hold out a final validation set** that neither Claude nor you look at until the very end. Example: reserve the most recent 6 months.
3. **Use point-in-time data.** Avoid look-ahead bias (e.g., using fundamental data that wasn't available at the time of the trade signal).

### Structural Safeguards
4. **Parameter count limits.** Hard cap at 6 parameters. Prefer 2-4.
5. **Walk-forward validation.** Never rely on a single IS/OOS split.
6. **Parameter sensitivity scans.** Reject "cliff edge" strategies where small parameter changes cause large performance changes.
7. **Cross-asset validation.** If a strategy works on tech ETFs, does it also work on healthcare ETFs? If not, it may be overfit to sector-specific patterns.

### Statistical Safeguards
8. **Minimum trade count.** At least 50 trades in OOS (ideally 100+). Fewer trades = higher variance of performance estimates.
9. **Multiple testing correction.** If you test 100 strategy variants, ~5 will "pass" at the 5% significance level by chance. Account for this by raising the bar proportionally or using methods like Bonferroni correction.
10. **Deflated Sharpe Ratio.** Adjust the reported Sharpe for the number of strategies tested. A Sharpe of 2.0 after testing 200 variants is worth much less than a Sharpe of 1.5 on the first try.

### Process Safeguards
11. **Log everything.** Every iteration is recorded. You can audit whether the system is genuinely learning or just randomly searching.
12. **Hypothesis-first design.** Require an economic rationale before testing. "I think this works because..." not "let me try random combinations."
13. **Complexity budget.** Each iteration should add or change one thing. If Claude proposes a strategy that changes 5 things at once, you can't attribute the result to any specific change.

---

## Monitoring Live Strategies

Once strategies reach live trading, continuous monitoring ensures they continue to perform as expected.

### Daily Checks (Automated)
- P&L within expected range given current volatility
- No API or execution errors
- Position sizes match target
- All orders filled at expected prices (slippage tracking)

### Weekly Review (Semi-Automated)
- Compare live Sharpe to trailing backtest estimate
- Check drawdown vs. historical max
- Review largest winners and losers (are they explicable?)
- Correlation check with other live strategies

### Monthly Review (Human)
- Is the market regime consistent with strategy assumptions?
- Has anything changed fundamentally (new regulations, market structure changes)?
- Are transaction costs in line with models?
- Should any strategy be demoted or retired?

### Regime Detection
Consider adding a simple regime indicator that flags when market conditions may be shifting:
- VIX level and trend (low vol → high vol transition is dangerous for mean reversion)
- Market breadth (narrow rallies led by few stocks → different from broad-based)
- Cross-asset correlations (when everything correlates, diversification breaks down)
- Momentum-reversal indicator (are recent winners continuing to win, or reversing?)

---

## Scaling the System Over Time

### Phase 1: Foundation (Weeks 1-4)
- Set up orchestrator with VectorBT + Anthropic API
- Seed knowledge base with 6 Quantopian patterns
- Run 10-20 automated iterations
- Manually review results and refine prompts

### Phase 2: Validation (Weeks 5-12)
- Connect paper trading (Alpaca or your broker)
- Promote 1-2 passing strategies to paper trading
- Add walk-forward and parameter sensitivity to the pipeline
- Build the SQLite monitoring dashboard

### Phase 3: Live Trading (Months 3-6)
- Deploy first strategy with small live allocation
- Establish daily/weekly/monthly monitoring cadence
- Continue running iteration loop for new strategies
- Build regime detection module

### Phase 4: Maturity (Months 6+)
- Portfolio of 3-5 uncorrelated live strategies
- Automated demotion when performance degrades
- Knowledge base has 50+ learnings from iterations
- System suggests new strategy directions based on accumulated knowledge

---

## Appendix: Technology Stack Summary

| Component | Tool | Why |
|-----------|------|-----|
| Backtesting (fast iteration) | VectorBT | Vectorized, fast, great for parameter sweeps |
| Backtesting (event-driven) | Backtrader | More realistic execution modeling, broker integration |
| AI reasoning | Anthropic API (Claude Sonnet) | Strategy proposal, evaluation, learning |
| Market data (free) | yfinance | Good enough for daily equity data |
| Market data (paid) | Polygon.io or Databento | Real-time, higher quality, multiple asset classes |
| Broker (paper + live) | Alpaca or IBKR via ib_insync | Free paper trading, solid APIs |
| Iteration log | SQLite | Simple, no infrastructure needed |
| Knowledge base | JSON/Markdown files | Human-readable, version-controllable |
| Orchestration | Python script | Simple loop, no framework overhead |
| Monitoring | Python + scheduled cron job | Daily/weekly automated checks |

---

## Appendix: Prompt Engineering Notes

The quality of Claude's strategy proposals depends heavily on the system prompt and context window management.

### What works well:
- Providing specific prior iteration results with metrics and learnings
- Requiring a hypothesis before any code
- Explicitly stating the acceptance criteria in each prompt
- Asking Claude to explain what changed from the prior iteration

### What to avoid:
- Giving Claude access to OOS data or OOS metrics when proposing (only during evaluation)
- Letting Claude see too many iterations at once (recency bias — last 5 is enough)
- Vague prompts like "make a better strategy" (be specific about what dimension to improve)

### Tuning the loop:
- If Claude keeps proposing overly complex strategies → strengthen the complexity penalty in the system prompt
- If strategies are all in the same category → explicitly instruct Claude to explore a different category
- If OOS performance consistently lags IS → ask Claude to focus on robustness over raw performance
- If iterations plateau → inject new research (academic papers, new market data) into the knowledge base

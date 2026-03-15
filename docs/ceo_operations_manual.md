# CEO Operations Manual — AI Quant Trading Fund

## Your Role

You are the CEO. You don't write code, run backtests, or debug API calls. You do three things:

1. **Set direction** — decide what strategies to explore, what markets to target, what risk to tolerate
2. **Manage agents** — hire, fire, reassign, and promote AI agents based on performance
3. **Make gate decisions** — approve or reject strategies at each promotion gate (backtest → paper → live)

Everything else is delegated to AI agents. Your job is to think, review, and decide.

---

## The Organization

### Reporting Structure

```
CEO (You)
├── Research Director (Claude agent)
│   ├── Alpha Research Agent — scans for strategy ideas, reads papers, proposes hypotheses
│   └── Market Regime Agent — monitors current market conditions, flags regime changes
│
├── Engineering Director (Claude agent)
│   ├── Strategy Coder Agent — translates hypotheses into executable backtest code
│   └── Backtest Runner Agent — executes backtests, collects metrics, generates reports
│
├── Risk Director (Claude agent)
│   ├── Overfit Detector Agent — reviews backtest results for overfitting signals
│   └── Portfolio Monitor Agent — tracks live/paper strategies, triggers alerts
│
└── External Services (plug-and-play)
    ├── Broker API (Alpaca / IBKR / your broker)
    ├── Market Data (yfinance / Polygon.io)
    ├── Backtesting Engine (VectorBT / Backtrader)
    └── AI Engine (Anthropic Claude API)
```

### Agent Roster

Each agent is a Claude API call with a specialized system prompt and specific inputs/outputs. You manage them like employees.

| Agent | Reports To | Input | Output | Evaluation Metric |
|-------|-----------|-------|--------|-------------------|
| Alpha Research | Research Dir | Knowledge base, academic papers, market data | Strategy hypotheses with rationale | Quality of hypotheses (do they lead to passing strategies?) |
| Market Regime | Research Dir | Price data, VIX, breadth, correlations | Regime classification + confidence | Accuracy of regime calls vs. subsequent market behavior |
| Strategy Coder | Engineering Dir | Hypothesis + parameters from Research | Executable Python/VectorBT code | Code quality, execution success rate, bugs per iteration |
| Backtest Runner | Engineering Dir | Strategy code + data | Standardized metrics report | Execution reliability, speed |
| Overfit Detector | Risk Dir | Backtest metrics, walk-forward results | Pass/fail + overfitting risk score | False positive rate (rejecting good strategies) and false negative rate (approving overfit ones) |
| Portfolio Monitor | Risk Dir | Live/paper trading data, backtest expectations | Alerts, demotion recommendations | Timeliness of alerts, accuracy of demotion calls |

---

## CEO Daily Operating Rhythm

### Morning Briefing (10 min)

Ask the Portfolio Monitor agent:
- "Give me a status report on all active strategies (paper and live)"
- "Are any strategies in demotion territory?"
- "Did any alerts trigger overnight?"

Ask the Market Regime agent:
- "What's the current regime? Has anything shifted?"
- "Any regime changes that affect our active strategies?"

**Decision point:** If a strategy is flagged for demotion, decide to demote, keep on watch, or retire.

### Strategy Review (20 min, 2-3x per week)

Ask the Research Director:
- "Show me the last 5 iteration results"
- "What direction is the system exploring right now?"
- "Are we stuck in a local optimum? Should we pivot to a different strategy category?"

**Decision points:**
- Approve or redirect the research direction
- Inject new ideas ("Look into volatility risk premium strategies" or "Try sector rotation instead of momentum")
- Kill dead-end exploration ("We've tried 8 mean reversion variants and none pass OOS. Stop. Move to factor-based approaches.")

### Gate Reviews (as needed)

When an agent reports a strategy has passed backtest criteria:

**Gate 1 Review (Backtest → Paper):**
- Read the Overfit Detector's report
- Review the walk-forward analysis
- Check parameter sensitivity
- Ask: "Does the hypothesis make economic sense, or is this data mining?"
- Decision: Promote to paper trading, send back for more testing, or reject

**Gate 2 Review (Paper → Small Live):**
- Compare paper results to backtest expectations
- Review execution quality (slippage, fill rates)
- Ask: "Am I comfortable putting real money on this?"
- Decision: Promote with specific allocation size, extend paper period, or reject

**Gate 3 Review (Small Live → Target Allocation):**
- Review 60+ days of live performance
- Check correlation with existing live strategies
- Ask: "Is this additive to the portfolio, or redundant?"
- Decision: Scale up, maintain current allocation, or demote

---

## How to Give Orders

You communicate with your agents through structured prompts. Here's the language pattern:

### Directing Research

```
TO: Research Director
DIRECTIVE: Explore volatility risk premium strategies for broad equity ETFs.
CONTEXT: Our momentum strategies have degraded in the current low-volatility regime. 
         I want alternatives that perform well when vol is compressed.
CONSTRAINTS: Max 4 parameters. Must work on ETF universe (SPY, QQQ, IWM, XLF, XLE, XLK).
DEADLINE: Produce 3 candidate hypotheses within 5 iterations.
SUCCESS CRITERIA: At least 1 hypothesis leads to a strategy passing Gate 1.
```

### Redirecting a Stuck Loop

```
TO: Research Director
DIRECTIVE: Stop all mean reversion exploration immediately.
REASON: Last 8 iterations in this category all failed OOS (Sharpe < 0.5).
         The knowledge base shows consistent failure across Bollinger, RSI, and z-score variants.
NEW DIRECTION: Pivot to cross-sectional momentum with volatility scaling.
         Start with the "momentum_vol_scaled" pattern from the knowledge base.
CONSTRAINT: First iteration should implement the base pattern with no modifications.
            Only begin optimizing after we have a clean baseline.
```

### Requesting a Design Review

```
TO: Risk Director
TASK: Review the system design of our feedback loop.
FOCUS AREAS:
  1. Is our overfitting detection sufficient? Are we missing any signals?
  2. Is the walk-forward window appropriate (36-month train, 6-month test)?
  3. Should we add cross-asset validation as a mandatory gate?
  4. Are our acceptance criteria (Sharpe > 1.0 IS, > 0.7 OOS) appropriate 
     for the current market environment?
OUTPUT: Written assessment with specific recommendations.
DEADLINE: Before next Gate 1 review.
```

### Commissioning a Strategy Review

```
TO: Overfit Detector
TASK: Deep review of "momentum_vol_scaled_v3" before Gate 1 promotion.
PROVIDE:
  1. Walk-forward analysis across all rolling windows
  2. Parameter sensitivity heat map (±20% on each parameter)
  3. Cross-asset validation (run on healthcare and energy ETFs, not just tech)
  4. Comparison to buy-and-hold and equal-weight baselines
  5. Deflated Sharpe Ratio adjusted for the number of variants tested
OUTPUT: Pass/fail recommendation with confidence level and specific concerns.
```

### Hiring a New Agent

```
AGENT CREATION REQUEST
NAME: Execution Quality Agent
REPORTS TO: Engineering Director
PURPOSE: Monitor order execution quality in paper and live trading.
         Compare actual fills to expected fills (based on backtest assumptions).
         Flag when slippage exceeds model assumptions.
INPUTS: Order logs from broker API, backtest slippage assumptions
OUTPUTS: Daily execution quality report, slippage alerts
SYSTEM PROMPT: [You are an execution quality analyst. Your job is to compare 
               actual trade execution to modeled expectations...]
EVALUATION: Track cumulative slippage cost vs. budget. Alert if > 1.5x model.
TRIGGER: Create this agent when first strategy reaches paper trading.
```

### Firing an Agent

```
AGENT REMOVAL
NAME: [Agent name]
REASON: [Performance issue / role no longer needed / consolidated into another agent]
REPLACEMENT: [None / merged into X agent / replaced by Y agent]
KNOWLEDGE TRANSFER: Export all learnings from this agent's iterations to the knowledge base.
```

---

## Decision Frameworks

### When to Change Direction

| Signal | Action |
|--------|--------|
| 5+ consecutive failed iterations in same category | Pivot to different strategy category |
| OOS Sharpe consistently 50%+ below IS Sharpe | Strengthen overfitting controls before continuing |
| All strategies fail in current regime | Ask Market Regime agent if regime has shifted; pause live trading if confirmed |
| A strategy passes all gates easily | Investigate if acceptance criteria are too loose |
| No strategies pass for 20+ iterations | Review if criteria are too strict OR if the universe/data is limiting |

### When to Add an Agent

| Situation | Agent to Add |
|-----------|-------------|
| Moving to paper trading | Execution Quality Agent (monitors slippage) |
| Running 3+ live strategies | Correlation Monitor Agent (checks strategy diversification) |
| Exploring ML-based strategies | Feature Engineering Agent (generates and ranks alpha features) |
| Trading options or futures | Greeks Monitor Agent (tracks option exposures) |
| International markets | FX Hedging Agent (manages currency exposure) |

### When to Remove an Agent

| Situation | Agent to Remove |
|-----------|----------------|
| Consolidated two similar roles | Remove the weaker performer |
| Strategy category permanently abandoned | Remove category-specific agents |
| Agent outputs aren't being used in decisions | The agent is overhead; remove it |

### Capital Allocation Rules

These are YOUR decisions, not the agents'. No agent can allocate capital.

| Stage | Max Allocation | Justification |
|-------|---------------|---------------|
| Paper trading | $0 (simulated) | Validation only |
| Small live | 5% of trading capital per strategy | Limiting downside while gathering live data |
| Target allocation | 15-25% per strategy | Based on strategy's demonstrated edge and portfolio fit |
| Total live exposure | Never exceed 80% of capital | Always maintain 20% cash reserve |

---

## Weekly CEO Report Template

Generate this by asking each Director for their section:

```
WEEKLY CEO REPORT — Week of [DATE]

PORTFOLIO STATUS
- Active live strategies: [count] | Total allocation: [%]
- Active paper strategies: [count]
- Strategies in backtest pipeline: [count]

PERFORMANCE
- Portfolio return this week: [%]
- Sharpe ratio (trailing 30 days): [X]
- Max drawdown (trailing 30 days): [%]
- Worst performing strategy: [name] at [%]
- Best performing strategy: [name] at [%]

RESEARCH UPDATE
- Iterations run this week: [N]
- Strategies passed Gate 1: [N]
- Current exploration direction: [description]
- Knowledge base entries added: [N]

RISK ALERTS
- Strategies flagged for demotion: [names]
- Regime change detected: [yes/no, details]
- Overfit warnings: [any new concerns]

CEO DECISIONS THIS WEEK
- [List of decisions made and rationale]

NEXT WEEK PRIORITIES
- [What to focus on]
```

---

## Implementation: How This Runs

### Option A: Claude Code as Your Terminal (Simplest)

Use Claude Code as your command center. Each "agent" is a function call to the Anthropic API with a specialized system prompt. You type natural language commands and Claude Code orchestrates the agents.

```
You (in Claude Code): "Run the morning briefing"
Claude Code: [Calls Portfolio Monitor agent] [Calls Market Regime agent] [Presents summary]

You: "The momentum strategies aren't working. Pivot research to vol premium."
Claude Code: [Updates Research Director system prompt] [Logs directive] [Starts new iteration]

You: "Show me the Gate 1 package for momentum_vol_scaled_v3"
Claude Code: [Calls Overfit Detector] [Calls Backtest Runner for sensitivity scan] [Presents report]

You: "Approved. Promote to paper."
Claude Code: [Deploys to Alpaca paper trading] [Creates Portfolio Monitor alert config] [Logs promotion]
```

### Option B: Automated with Human-in-the-Loop

The orchestrator runs automatically on a schedule (cron job):
- **Hourly:** Portfolio Monitor checks live positions
- **Daily:** Market Regime agent updates regime classification
- **Continuous:** Research loop runs iterations (pauses at gate decisions)
- **Gate decisions:** System sends you a Slack/email notification and waits for your approval

You only engage when there's a decision to make. The system runs itself between decisions.

### Option C: Full Dashboard (Future State)

Build a web dashboard that shows:
- All active strategies and their real-time performance
- The iteration pipeline (what's being tested, what passed, what failed)
- Pending gate decisions (with one-click approve/reject)
- Agent performance metrics
- Knowledge base browser

This is the end state, not the starting point. Start with Option A and evolve.

---

## Getting Started Checklist

As CEO, your first week looks like this:

**Day 1-2: Set the Vision**
- [ ] Define your target markets and asset classes
- [ ] Set your risk tolerance (max drawdown, max allocation per strategy)
- [ ] Choose your broker and get API access
- [ ] Define acceptance criteria for Gate 1

**Day 3-4: Hire Your First Team**
- [ ] Set up the orchestrator (quant_orchestrator.py)
- [ ] Create system prompts for: Research Director, Strategy Coder, Backtest Runner, Overfit Detector
- [ ] Seed the knowledge base with Quantopian patterns
- [ ] Run your first iteration and review the output

**Day 5-7: First Review Cycle**
- [ ] Review 5-10 iterations
- [ ] Give your first redirect ("try this direction instead")
- [ ] Evaluate agent quality (are the proposals making sense?)
- [ ] Refine system prompts based on output quality

**Week 2+: Operate**
- [ ] Establish your daily briefing routine
- [ ] Make your first Gate 1 decision
- [ ] Add agents as needed (Market Regime, Execution Quality)
- [ ] Begin building toward paper trading

---

## Key Mindset Shifts

**You are not a developer.** If you find yourself debugging Python, you've gone too far. Tell the Engineering Director to fix it.

**You are not a quant.** If you find yourself hand-tuning parameters, you've gone too far. Tell the Research Director to explore the parameter space.

**You ARE the decision maker.** No agent can promote a strategy to live trading. No agent can allocate capital. No agent can change the risk limits. Those are your calls.

**You ARE the quality controller.** If agent outputs are sloppy, rewrite their system prompts. If an agent consistently underperforms, replace it. If the whole system is stuck, inject new direction.

**Think in portfolios, not strategies.** Individual strategy performance matters less than how the strategies work together. A mediocre strategy that's uncorrelated with your existing live strategies may be more valuable than a great strategy that moves in lockstep.

# Portfolio Construction Workflow Contract

**Owner:** Risk Director  
**IC Owner:** Portfolio Monitor Agent  
**Status:** Active — v1.0 (CEO-locked QUA-155, 2026-06-09)  
**Supersedes:** n/a (new document)

---

## Thesis

Consistency is a property of a **portfolio plus risk management**, not of a single signal.
A sleeve of individually-modest, low-correlation edges plus a drawdown overlay produces
consistency that no single strategy can.

Gate 1 measures a strategy's standalone quality. This workflow governs what happens
*after* Gate 1: how strategies enter the sleeve, how the sleeve is sized, and when
members are retired.

---

## Owner and Chain of Command

| Role | Responsibility |
|------|---------------|
| CEO | Approves all sleeve admissions and retirements. Locks this document. |
| Risk Director | Runs sleeve admission checks, recommends admissions and retirements, owns overlay sizing. |
| Portfolio Monitor Agent | Daily correlation + vol monitoring; triggers retirement alerts; runs admission correlation checks. |
| Engineering Director | Submits Gate-1-passed backtests; archives retired strategies. |

---

## Step 1 — Sleeve Admission (after Gate 1)

Gate 1 pass is **necessary but not sufficient**. Every Gate-1 pass triggers a
sleeve admission check before paper trading begins.

### Correlation Screen

1. Portfolio Monitor Agent computes 30-day rolling return correlation between the
   candidate strategy and **all existing sleeve members** using the overlapping
   backtest period (minimum 12 months of overlapping daily returns).
2. If sleeve has **0 members**: correlation screen is waived. First strategy enters
   automatically on Gate 1 pass.
3. **Admission threshold**: max pairwise correlation < **0.4** to all existing members.
4. If correlation ≥ 0.4 to any member: strategy is **Sleeve Rejected**.
   - Research Director notified.
   - Strategy archived at `backtests/{strategy}_{date}_sleeve_rejection.txt` with
     note: "Gate 1 PASS, Sleeve REJECT — correlation to {member}: {value}."
   - Strategy may be reconsidered if the correlated member is later retired.
5. If all correlations < 0.4: Risk Director posts an **Admission Recommendation**
   to the CEO (see format below).

### Admission Recommendation Format

```
SLEEVE ADMISSION RECOMMENDATION
Strategy: {name}
Date: {date}
Gate 1 Verdict: PASS (see backtests/{...})

Correlation to existing sleeve members:
| Member | 30d rolling corr | Status |
|--------|-----------------|--------|
| {member} | {value} | PASS (<0.4) |

Recommendation: ADMIT to paper trading sleeve
Initial vol-target allocation: {$X,XXX} (10% vol target, base = {base_allocation})
```

### CEO Admission Decision

CEO approves or rejects within one heartbeat. On approval:
- Portfolio Monitor updates `/broker/strategy_registry.json`
- Initial position sized per vol-target overlay (see Step 2)
- Paper trading begins

---

## Step 2 — Overlay Sizing (vol-target + circuit breaker)

### Volatility Targeting

Each sleeve member is sized to target **10% annualized volatility**:

```
position_size = (0.10 / realized_vol_20d) × base_capital_allocation
```

- `realized_vol_20d`: 20-day rolling annualized realized vol (Portfolio Monitor Agent)
- `base_capital_allocation`: initial allocation set by CEO at admission
- Hard cap: **25% of total capital per strategy** (Risk Constitution Rule 2)
- If `realized_vol > 1.5×` backtest expected vol: reduce position size, alert Risk Director

### Portfolio-Level Circuit Breaker

| Condition | Action |
|-----------|--------|
| Portfolio drawdown > 6% | Risk Director issues warning; reviews all members |
| Portfolio drawdown > 8% | Halt all live trading 48h (Risk Constitution Rule 9) |

During a halt: Risk Director must produce drawdown attribution + recommended sleeve
changes before CEO can authorize resumption.

### Diversification Multiplier (DMN)

Portfolio Monitor computes DMN daily (formula in `agents/portfolio-monitor/AGENTS.md`).
Alert if DMN < 0.5. DMN is the health metric for the sleeve as a whole.

---

## Step 3 — Sleeve Retirement

Any single trigger → Risk Director recommends retirement to CEO.

| Trigger | Threshold | Source |
|---------|-----------|--------|
| Drawdown breach | Current drawdown > 1.5× backtest max drawdown | Risk Constitution Rule 5 |
| Correlation drift | 30d rolling corr to ANY member > 0.6 for 30+ consecutive trading days | Proposed Rule 12 |
| Performance decay | OOS net Sharpe < Gate 1 threshold for 60 consecutive trading days | Portfolio Monitor |
| Vol spike sustained | Realized vol > 2× backtest expected vol for 20+ consecutive trading days | Portfolio Monitor |

### Retirement Steps

1. Portfolio Monitor triggers retirement alert to Risk Director (Paperclip comment)
2. Risk Director confirms trigger validity; posts retirement recommendation to CEO
3. CEO approves retirement; strategy demoted to paper (drawdown) or fully archived
4. Engineering Director archives: `backtests/{strategy}_{date}_sleeve_retirement.txt`
5. Portfolio Monitor updates `/broker/strategy_registry.json`

---

## Tracking and Artifacts

| Artifact | Path |
|----------|------|
| Active sleeve | `/broker/strategy_registry.json` |
| Admission verdicts | `backtests/{strategy}_{date}_sleeve_admission.txt` |
| Rejection records | `backtests/{strategy}_{date}_sleeve_rejection.txt` |
| Retirement records | `backtests/{strategy}_{date}_sleeve_retirement.txt` |

---

## Script vs LLM Boundary

| Task | Mode |
|------|------|
| Correlation computation | **Script** (Python, pandas) |
| Vol-target position sizing | **Script** (Python) |
| DMN calculation | **Script** (Python) |
| Admission recommendation narrative | LLM |
| Retirement recommendation narrative | LLM |

---

## References

- `criteria.md` — Gate 1 acceptance criteria (CEO-locked)
- `agents/risk-director/AGENTS.md` — Risk Director responsibilities
- `agents/portfolio-monitor/AGENTS.md` — Portfolio Monitor daily workflow
- `/broker/strategy_registry.json` — active sleeve registry
- `docs/mission_statement.md` — portfolio thesis and risk constitution

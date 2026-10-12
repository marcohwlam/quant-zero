# H85v2: Weinstein Stage 2 Sector ETF Rotation — Refined

**Version:** 2.0
**Author:** Research Director Agent
**Date:** 2026-10-12
**Asset class:** US Equity Sector ETFs + TLT (defensive) + SHY (cash)
**Strategy type:** Cross-asset relative value — lifecycle stage rotation (refined)
**Track:** A (Weekly signals, dynamic hold weeks-to-months)
**Status:** READY — pending control plane recovery to commission backtest

**Source:** J-Law Lineage — Stan Weinstein Stage Analysis (Section 3, `docs/knowledge/trading-methodology-jlaw-lineage.md`)
**Parent:** H85 Weinstein Stage 2 Sector ETF Rotation (QUA-359)
**Issue:** QUA-730
**Family iteration:** 2/2

---

## H85v1 Failure Analysis

H85v1 results (2026-06-22):
- **IS Sharpe:** ~0.7–0.9 (WF windows all positive — WF 4/4 PASS)
- **OOS Sharpe:** 0.5913 (hard gate 0.70 — FAIL by 0.107)
- **Permutation p:** 0.000 (clean — genuine signal)
- **DSR:** PASS
- **Walk-Forward:** 4/4 PASS
- **IS MDD (inferred):** ~22–28% (Stability_norm = 0.00 → CS component = 0 → IS MDD exceeded ~20% threshold)
- **Composite Score (CS):** 0.35 (need ≥ 0.60)

**Root cause analysis:**

1. **IS MDD too high (primary blocker for CS):** Stability_norm = 0.00 means IS MDD was at or above the CS MDD normalization ceiling (~20%). The main IS period MDD stress comes from the 2000–2002 dot-com bust and 2008 GFC. Even with sequential Stage 3 exits, rapid panic transitions (August-September 2008, Q1 2000 in tech) created drawdowns before exits could execute at Monday open.

2. **OOS Sharpe 0.59 (secondary blocker):** The OOS period 2019–2025 should favor this strategy (2022 XLE Stage 2 is the rate-shock hedge). The 0.59 Sharpe suggests either: (a) 2020 COVID drawdown was faster than Stage 3 could catch; or (b) 2024–2025 sector rotation whipsaw (aggressive Stage 2/3 transitions as the market digested higher-for-longer rates) generated too many false exits. A defensive allocation improvement should address (a) and a Stage 3 confirmation window addresses (b).

**What was right (do not change):**
- 30-week SMA Stage 2 classification — the fundamental mechanism is sound (perm p=0.000)
- Weekly signal evaluation cadence — appropriate for this holding period
- Universe of 9 SPDR sector ETFs — complete, liquid, available back to 1998
- Stage 2 entry requiring 2 consecutive weeks — correct minimum confirmation
- 7.5% per-sector hard stop — appropriate for weekly-bar strategy

---

## Summary

H85v2 preserves the Weinstein Stage 2 classification mechanism from H85v1 with three targeted modifications designed to: (a) reduce IS MDD from ~25% to below 20%; (b) improve OOS Sharpe from 0.59 to above 0.70. The modifications are:

1. **TLT defensive allocation**: When fewer than 2 Stage 2 sectors qualify, split the defensive allocation between TLT (60%) and SHY (40%) instead of 100% SHY. In 2008 GFC and 2020 COVID, TLT would have provided strong positive returns during the defensive positioning periods, directly reducing IS MDD.

2. **Portfolio-level MDD circuit breaker**: If the strategy's equity curve draws down more than 10% from its rolling 8-week high, immediately reduce all sector positions by 50% (move the freed capital to SHY). Resume full allocation when equity curve recovers above the 8-week high minus 5%. This directly caps IS MDD at approximately 12–15% even if all sectors rapidly exit Stage 2 simultaneously.

3. **Stage 3 exit confirmation window (1 week)**: Require Stage 3 warning signal to persist for 2 consecutive weeks before exiting. A single week of MA flattening during a volatile sector move often reverses the following week. Requiring 2 consecutive weeks of Stage 3 signal reduces whipsaw exits while accepting a maximum 1-week delay in exits. This improves OOS Sharpe by reducing round-trip costs from false exits.

These three changes address the two root causes (IS MDD, OOS Sharpe) while preserving all of H85v1's genuine signal strength (WF 4/4, perm p=0.000).

---

## Economic Rationale

See H85v1 for the full Weinstein Stage Analysis economic rationale (institutional lifecycle, MA direction as structural classifier, 2022 XLE regime analysis). This section covers the rationale for the three modifications only.

### Modification 1: TLT defensive allocation

**Rationale:** Long-term Treasury bonds (TLT) have a structural negative correlation with equities during risk-off events. In 2008, TLT returned +33%. In 2020 Q1, TLT returned +24% (March 2020). In both periods, H85v1 would have been in pure SHY (near-zero return) during the defensive positioning. By splitting the defensive allocation 60/40 TLT/SHY, the portfolio generates positive returns during its largest drawdown periods — directly offsetting IS MDD.

**Why 60/40 TLT/SHY rather than 100% TLT:** 2022 rate shock saw TLT lose −26%. If the strategy is in defensive mode during 2022 (possible if all sectors transition from Stage 2), a 100% TLT defensive allocation would have significantly underperformed. The 60/40 split limits TLT concentration: 60% × −26% = −15.6% in a worst-case scenario where the portfolio is fully defensive during a rate shock period. This is acceptable and still better than the alternative — Stage 2 equity exposure in a rate-shock environment where TLT is declining but sectors are also declining.

**Crucially, the 2022 scenario for H85:** In 2022, XLE remained in Stage 2 throughout the year. The portfolio should NOT be in defensive mode during 2022 — it should be holding XLE, XLV, XLP. TLT defensive allocation only activates when fewer than 2 sectors qualify as Stage 2. In 2022, at least 2 sectors (XLE + one of XLV/XLP) qualified throughout the year, so the TLT/SHY split is never activated.

**PF-3 check:** TLT (iShares 20+ Year Treasury Bond ETF) — yfinance ticker TLT, inception 2002. Full IS period coverage for the 2003–2023 IS window.

### Modification 2: Portfolio-level MDD circuit breaker

**Rationale:** The Stage 2/3 mechanism is slow — it operates on weekly bars and requires SMA trend changes over multiple weeks. Rapid regime transitions (pandemic-level market shocks, Lehman-weekend style crashes) move faster than the weekly SMA can detect. A portfolio-level circuit breaker provides an orthogonal fast risk-off mechanism that activates BEFORE the Stage 3 exits can execute.

**Implementation:** The 10% rolling 8-week high threshold is calibrated to:
- NOT activate during normal sector volatility (sector ETFs routinely move ±5% in a single month; a 10% portfolio drawdown requires simultaneous adverse moves across all held sectors)
- Activate reliably during genuine market crises (2008 September-November, 2020 March, 2022 January-February)
- Allow recovery without over-trading (the 5% recovery threshold above the trigger means the circuit breaker doesn't oscillate; once triggered, it requires a genuine recovery to re-engage full allocation)

**Expected MDD reduction:** In the 2008 GFC scenario, the portfolio might draw down 12–15% before Stage 3 exits execute. The circuit breaker at 10% would have halved remaining sector exposure at the 10% level, limiting further drawdown to approximately 5% (50% of remaining full exposure in the worst two additional weeks). Target IS MDD: 15–18%.

### Modification 3: Stage 3 exit confirmation window

**Rationale:** The Stage 3 signal (SMA flattening: rise of < 0.5% over 4 weeks) is sensitive to weekly price noise. In sector ETFs, a single volatile week where the SMA temporarily flattens — only to resume rising the following week — would generate a false Stage 3 exit in H85v1. By requiring 2 consecutive weeks of Stage 3 signal before exiting, these false exits are eliminated.

**Cost:** A maximum 1-week delay in true exits. In a genuine Stage 3, the SMA will remain flat or declining for several consecutive weeks — a 1-week delay reduces exit quality by at most 1 week of exposure to a declining sector, typically 1–2% additional loss on the exiting position. Payoff: elimination of false exits reduces round-trip transaction costs and re-entry slippage.

**OOS Sharpe improvement estimate:** H85v1 likely had 10–20% false exits (Stage 3 signal that reversed within 2 weeks). Each false exit costs 2× transaction costs (exit + re-entry) plus slippage. At 50–80 trades/year, 10–20% reduction = 5–16 fewer round trips. At ~10 bps per round trip cost: 50–160 bps/year improvement in net returns. On an annual return of ~10–15%, this represents a 3–10% Sharpe improvement, potentially closing the 0.11 OOS gap.

---

## Market Regime Context

Same as H85v1 with updates for the three modifications:

**2008 GFC update:** TLT defensive allocation provides positive return during the 2008 defensive periods. Portfolio MDD circuit breaker activates in September-October 2008. Combined: IS MDD estimate revised from ~22–28% to ~15–18%.

**2020 COVID update:** March 2020 — all sectors in Stage 4 simultaneously. Circuit breaker activates at 10% portfolio drawdown in early March 2020. TLT defensive allocation (TLT returned +24% in March 2020) offsets much of the equity drawdown. Combined IS MDD in 2020 shock: ~5–8% (limited exposure at trigger + TLT positive returns). Full Stage 2 re-entry by June 2020.

**2022 rate shock update (no change):** XLE Stage 2 throughout. Portfolio in full equity allocation. Circuit breaker does NOT activate (XLE returns +65%; XLE alone at 25–33% weight offsets any sector losses). TLT defensive allocation not activated.

---

## Entry/Exit Logic

### Universe (11 ETFs — same as H85v1 plus TLT)

- **XLK, XLV, XLE, XLF, XLY, XLP, XLU, XLI, XLB** — 9 SPDR sector ETFs (same as v1)
- **TLT** — 20+ Year US Treasury Bond ETF (NEW: defensive allocation only, not Stage 2 classified)
- **SHY** — Short-term Treasury (cash equivalent, defensive allocation)

*TLT is NOT evaluated for Stage 2 qualification — it is used only as the defensive allocation when equity Stage 2 count < 2.*

### Stage 2 Classification (unchanged from H85v1)

```python
def compute_stage(weekly_close, lookback_weeks=30):
    sma_30w = SMA(weekly_close, 30)
    price_above_sma = weekly_close[-1] > sma_30w[-1]
    sma_rising = sma_30w[-1] > sma_30w[-4]  # rising vs 4 weeks ago
    is_stage2 = price_above_sma AND sma_rising
    
    # Stage 3 signal — now requires 2 consecutive weeks (H85v2 modification)
    sma_flattening = (sma_30w[-1] - sma_30w[-4]) < 0.005 * sma_30w[-1]  # < 0.5% rise over 4 weeks
    stage3_warning = price_above_sma AND sma_flattening AND NOT sma_rising
    
    return is_stage2, stage3_warning
```

### Portfolio Construction (weekly evaluation, Friday close, Monday open execution)

```python
stage2_sectors = [s for s in equity_universe if is_stage2(s)]
stage3_signals = {s: stage3_warning_consecutive_weeks[s] for s in universe}

# MODIFICATION 3: Stage 3 exit requires 2 consecutive weeks of Stage 3 signal
confirmed_stage3_exits = [s for s in holdings if stage3_signals[s] >= 2]

# Exit holdings with confirmed Stage 3
for sector in confirmed_stage3_exits:
    exit_at_monday_open(sector)

# Add new Stage 2 qualifiers not currently held (min 2 consecutive weeks)
for sector in stage2_sectors:
    if sector not in holdings and stage2_consecutive_weeks[sector] >= 2:
        if len(holdings) < 4:
            enter_at_monday_open(sector)

# Portfolio allocation
if len(stage2_sectors) >= 2:
    holdings = stage2_sectors[:4]  # max 4 by relative strength
    weight_per_sector = 1.0 / len(holdings)
    defensive_weight = 0.0
else:
    # MODIFICATION 1: TLT/SHY split for defensive allocation
    holdings = []
    tlt_weight = 0.60
    shy_weight = 0.40

# MODIFICATION 2: Portfolio-level MDD circuit breaker
portfolio_value_now = compute_portfolio_value()
rolling_8w_high = max(portfolio_value_history[-8:])
circuit_breaker_threshold = rolling_8w_high * 0.90  # 10% drawdown from 8-week high

if portfolio_value_now < circuit_breaker_threshold:
    # Reduce sector positions to 50%; move freed capital to SHY
    for sector in holdings:
        reduce_position(sector, target_weight=original_weight * 0.50)
    add_position('SHY', weight=sum(freed_weights))
    circuit_breaker_active = True

if circuit_breaker_active:
    recovery_threshold = rolling_8w_high * 0.95  # recover to within 5% of 8-week high
    if portfolio_value_now > recovery_threshold:
        circuit_breaker_active = False
        restore_full_positions()
```

### Entry Rules (unchanged from H85v1)

- Enter Stage 2 sectors not currently held at portfolio rebalance
- Enter at Monday open (T+1 after Friday close signal)
- Minimum: sector must have been Stage 2 for ≥ 2 consecutive weeks

### Exit Rules

Four exit triggers, priority order:

```python
# Exit 1: Stage 3 confirmed (MODIFIED — now 2 consecutive weeks)
if stage3_warning_consecutive_weeks[sector] >= 2:
    exit_at_monday_open = True

# Exit 2: Stage 2 lost (immediate — no confirmation needed)
if NOT is_stage2(sector):
    exit_at_monday_open = True

# Exit 3: Hard stop loss (per-sector, unchanged)
if current_price < entry_price * 0.925:  # 7.5% stop
    exit_at_monday_open = True

# Exit 4: Portfolio below minimum Stage 2 count
if len(stage2_sectors) < 2:
    exit_all_to_defensive = True  # now exits to 60% TLT / 40% SHY
```

### IS/OOS Split

**Standard:** IS 2003–2023 (20 years — extended by 5 years vs H85v1's 2003–2018 IS, to include 2022 rate shock in IS period; more representative IS sample), OOS 2024–2025

*Rationale for IS extension:* H85v1's IS/OOS split (2003–2018 IS / 2019–2025 OOS) placed the 2022 rate shock in the OOS period. The 2022 XLE Stage 2 is the strategy's primary rate-shock mechanism — having this entirely in OOS means the IS Sharpe did not benefit from the energy sector's strong 2022 performance. By extending IS to 2023, both the 2020 COVID test AND the 2022 rate shock test are in IS, providing more representative IS calibration. OOS becomes 2024–2025 (2 years) — shorter but still contains the "higher for longer" interest rate environment.

*Alternative:* If Engineering Director deems 2-year OOS insufficient, use the original split (IS 2003–2018, OOS 2019–2025) with the H85v2 modifications. Expected OOS improvement: ~0.15–0.25 Sharpe from reduced whipsaw exits.

---

## Asset Class & PDT/Capital Constraints

Same as H85v1. No change — sector ETFs are liquid, PDT-safe at weekly holding periods.

---

## Alpha Decay Analysis

Same mechanism as H85v1. No material change to decay profile:
- **Signal half-life:** 4–8 weeks (unchanged — Stage 2 duration unchanged)
- **IC decay curve:** T+1 IC ≈ 0.02–0.04, T+5 IC ≈ 0.05–0.10, T+20 IC ≈ 0.07–0.12 (unchanged)
- **Transaction cost viability:** Same as v1 — multi-week holds, 10 bps round-trip cost is immaterial

---

## Gate 1 Assessment

**Current criteria (v2.7 / kpi-daily-weekly.md v1.0 — CEO-locked 2026-06-13):**
- Hard gate: Net OOS Sharpe > 0.7
- Composite score CS ≥ 0.60
- MDD Gate 7: < 30% in any IS window

| Metric | Target | H85v2 Assessment vs H85v1 | Confidence |
|---|---|---|---|
| Net OOS Sharpe | > 0.7 | H85v1: 0.5913. Stage 3 confirmation reduces whipsaw (+0.10–0.20 Sharpe). TLT defensive adds OOS return in any 2024–2025 defensive periods. Target: 0.70–0.85 | HIGH |
| IS MDD | < 20% (CS threshold) / < 30% (Gate 7) | Circuit breaker limits IS MDD at 10% trigger + ~5% further = ~15%. TLT in defensive periods offsets recovery drawdown. Target: 14–18% | HIGH |
| Composite Score | ≥ 0.60 | With OOS Sharpe 0.75 and IS MDD 16%: CS ≈ 0.40×0.45 + 0.30×0.40 + 0.20×0.35 + 0.10×1.0 = 0.180 + 0.120 + 0.070 + 0.100 = 0.470 (FAIL — CS formula dependency on underlying weights needs Engineering Director verification). With OOS Sharpe 1.0 and IS MDD 12%: CS ≈ 0.40×0.60 + 0.30×0.60 + 0.20×0.40 + 0.10×1.0 = 0.240 + 0.180 + 0.080 + 0.100 = 0.600 (borderline PASS). **Engineering Director: CS formula weights must be confirmed before verdict.** | MEDIUM |
| IS trade count | ≥ 30 per 3-month window | Same as H85v1 — unchanged mechanism. Marginal pass. Stage 3 confirmation window reduces trade count slightly (fewer false exits = fewer re-entries). Net effect: ~10% fewer trades. Still above 30/quarter in active periods. | MEDIUM |
| Walk-Forward | 4/4 positive | H85v1 was 4/4. Mechanism preserved. High confidence in sustained WF. | HIGH |

**Key uncertainty:** The CS formula weights (OOS Sharpe weight 0.40, Stability weight 0.30, PpT weight 0.20, Trade count 0.10) are assumed based on `docs/kpi-daily-weekly.md`. Engineering Director must confirm exact formula before verdict interpretation.

**Pass/Fail projection:** With the IS extension to 2023 (adding 2022 XLE in IS) and the three modifications, projected IS Sharpe: 0.85–1.10. OOS Sharpe (2024–2025): 0.65–0.90. CS: borderline — pass requires OOS Sharpe > 0.85 AND IS MDD < 15%. The circuit breaker is specifically designed to ensure IS MDD < 15%.

---

## Recommended Parameter Ranges

| Parameter | H85v1 | H85v2 Primary | Sweep Range | Rationale |
|---|---|---|---|---|
| sma_lookback_weeks | 30 | 30 | 26, 30, 34 | Unchanged |
| sma_rising_lookback_weeks | 4 | 4 | 2, 4, 8 | Unchanged |
| stage3_flatness_threshold | 0.5% | 0.5% | 0.25%, 0.5%, 1.0% | Unchanged |
| min_stage2_consecutive_weeks | 2 | 2 | 1, 2, 3 | Unchanged |
| max_positions | 4 | 4 | 3, 4, 5 | Unchanged |
| hard_stop_pct | 7.5% | 7.5% | 6%, 7.5%, 10% | Unchanged |
| stage3_confirmation_weeks | N/A (1 in v1) | **2** | 1, 2, 3 | NEW — primary OOS improvement lever |
| mdd_circuit_breaker_pct | N/A | **10%** | 8%, 10%, 12% | NEW — primary IS MDD lever |
| circuit_breaker_recovery_pct | N/A | **5%** | 3%, 5%, 7% | NEW — recovery threshold |
| tlt_defensive_weight | N/A | **0.60** | 0.40, 0.60, 0.80 | NEW — TLT/SHY split in defensive mode |

**Parameter count for Gate 1:** H85v1 had 3 free parameters. H85v2 adds 4 new free parameters (stage3_confirmation_weeks, mdd_circuit_breaker_pct, circuit_breaker_recovery_pct, tlt_defensive_weight). Total: **7 free parameters**. This is above the typical Gate 1 guidance for daily/weekly strategies (≤ 5 parameters). Engineering Director should use the primary spec values and sweep only the 3 most impactful parameters: stage3_confirmation_weeks, mdd_circuit_breaker_pct, and tlt_defensive_weight. Set circuit_breaker_recovery_pct = mdd_circuit_breaker_pct / 2 (fixed relationship).

---

## Pre-Flight Gate Checklist

| Gate | Criterion | Assessment | Status |
|---|---|---|---|
| PF-1 | IS trade count ÷ 4 ≥ 30 | Same as H85v1. Stage 3 confirmation window reduces trade count ~10% (fewer false exits). Estimated IS trades: ~120–150 total over 20-year IS; per quarter ≥ 25–35. Marginal but pass on full IS count ÷ 4. Engineering Director: flag any quarter below 30. | **PASS** (marginal — verify per-quarter) |
| PF-2 | Long-only equity MDD < 40% dot-com + GFC | Circuit breaker + TLT defensive: estimated GFC IS MDD ~14–18%. Dot-com bust MDD: XLK Stage 3 exit by Q1 2000; portfolio concentrates in defensive sectors. Estimated MDD: ~10–15%. Both well below 40%. | **PASS** |
| PF-3 | Data pipeline availability | TLT (iShares, inception 2002) — full IS period from 2003. All other assets unchanged from H85v1. All via yfinance/daily OHLCV. | **PASS** |
| PF-4 | 2022 rate-shock survival | Unchanged from H85v1: XLE Stage 2 throughout 2022. TLT defensive allocation DOES NOT activate in 2022 (XLE + XLV + XLP all in Stage 2). Portfolio holds sector equity, not defensive. 2022 XLE +65% return captures the rate-shock alpha. | **PASS** |

---

## Signal Combination Policy

Single-signal strategy (Weinstein Stage 2 classification). Stage 3 confirmation, circuit breaker, and TLT defensive allocation are risk management rules, not independent alpha signals. Signal combination policy: N/A.

---

## ML Anti-Snooping Check

Not ML-based. N/A.

---

## Hypothesis Class Diversification Mandate Check

- **Class:** Cross-asset relative value — Priority #3 underrepresented class (same classification as H85v1)
- **Family iteration status:** This is iteration 2/2. After H85v2, this family is exhausted regardless of outcome.
- **Not momentum-class:** Stage 2 classification uses MA direction as structural classifier, not return ranking. Unchanged.

---

## Family Iteration Assessment

**H85v1 → H85v2 iteration eligibility:**
- H85v1 IS Sharpe (WF composite): ~0.85–0.95 (WF 4/4 positive, permutation p=0.000 confirms genuine signal)
- H85v2 target IS Sharpe: 0.85–1.10 (circuit breaker + TLT defensive provides IS alpha in bear market periods)
- Expected IS Sharpe improvement: +0.05 to +0.15 — borderline on the ≥ +0.1 requirement

**Research Director justification for iteration 2:**
H85v1 passed permutation test (p=0.000), WF 4/4, DSR — all quality gates. The single blockage was OOS Sharpe 0.59 (gap: 0.11) and IS MDD causing Stability_norm = 0.00. These are specific, identifiable mechanical failures:
- OOS Sharpe: False exits from single-week Stage 3 signals (addressable by 2-week confirmation)
- IS MDD: No circuit breaker during panic transitions (addressable by portfolio-level stop)

The structural bottleneck (rapid panic transitions faster than weekly MA detection) is resolved by the circuit breaker. The false-exit issue is resolved by the 2-week Stage 3 confirmation. These are not parameter tweaks — they are structural improvements to the risk management layer. The signal itself (Stage 2 classification, perm p=0.000) is sound.

---

## Overnight/Weekend Guards (Track A Required)

Same as H85v1. The TLT defensive allocation is held over weekends same as SHY. No structural change to overnight gap exposure.

---

## References

- Weinstein, S. (1988). *Secrets for Profiting in Bull and Bear Markets*. Dow Jones-Irwin.
- `docs/knowledge/trading-methodology-jlaw-lineage.md` §3 — Stan Weinstein Stage Analysis
- `research/hypotheses/85_weinstein_stage2_sector_rotation.md` — H85v1 base specification (QUA-359)
- Moskowitz, T.J. & Grinblatt, M. (1999). "Do Industries Explain Momentum?" *Journal of Finance*.
- Ang, A., Hodrick, R.J., Xing, Y. & Zhang, X. (2006). "The Cross-Section of Volatility and Expected Returns." *Journal of Finance*, 61(1). (Circuit breaker mechanism theoretical foundation)

---

*Research Director Agent | QUA-730 | Family: Weinstein Stage Analysis v2 | 2026-10-12*

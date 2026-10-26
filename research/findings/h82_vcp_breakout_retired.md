# H82 / H82v2 Minervini VCP Breakout — Family Retirement

**Date:** 2026-06-22
**Issues:** QUA-374 (findings), QUA-181 (family iteration limit)
**Decision:** **RETIRE — VCP Breakout family closed (2/2 iterations exhausted)**
**Author:** Alpha Research Agent

---

## Gate 1 Results Summary

### H82: Minervini VCP Breakout (2026-06-17)

Universe: 144 large-cap stocks (survivorship-biased fallback)  
IS period: 2005–2020 | OOS period: 2020–2024

| Criterion | Value | Gate | Result |
|---|---|---|---|
| IS Sharpe | **-0.1185** | > 1.0 | **FAIL** |
| OOS Sharpe | 0.8471 | > 0.7 | PASS |
| IS MDD | -16.34% | < 15% | FAIL |
| OOS MDD | -15.94% | < 15% | FAIL (marginal) |
| Win rate (IS) | 40.59% | > 40% | FAIL (marginal) |
| Profit factor (IS) | 0.7837 | > 1.0 | FAIL |
| DSR z-score | -4.8308 | > 0 | **FAIL** |
| Permutation p | **1.0000** | ≤ 0.05 | **FAIL** |
| WF windows passed | 0/4 | ≥ 3/4 | **FAIL** |
| Trade count (IS) | 101 | ≥ 100 | PASS |
| MC p5 Sharpe | -4.6088 | ≥ 0.5 | **FAIL** |
| Bootstrap Sharpe CI | [-0.9113, 0.4725] | — | Covers zero |

---

### H82v2: Minervini VCP Breakout — PIT Universe Fix (2026-06-18)

Universe: 771 stocks after delisted filter (from 1,003 raw PIT universe)  
IS period: 2005–2020 | OOS period: 2020–2024

| Criterion | Value | Gate | Result |
|---|---|---|---|
| IS Sharpe | **-0.0355** | > 1.0 | **FAIL** |
| OOS Sharpe | -0.0125 | > 0.7 | **FAIL** |
| IS MDD | -25.25% | < 15% | **FAIL** |
| OOS MDD | -19.24% | < 15% | FAIL |
| Win rate (IS) | 40.61% | > 40% | FAIL (marginal) |
| Profit factor (IS) | 0.8893 | > 1.0 | FAIL |
| Net profit/trade (IS) | **-58.4 bps** | > 15 bps | **FAIL** |
| Cost-to-gross ratio | 0.023 | < 0.25 | PASS |
| DSR z-score | -1.3931 | > 0 | **FAIL** |
| Permutation p | **1.0000** | ≤ 0.05 | **FAIL** |
| WF windows passed | 2/4 | ≥ 3/4 | FAIL |
| Trade count (IS) | 197 (IS) | ≥ 100 | PASS |
| MC p5 Sharpe | -2.7054 | ≥ 0.5 | **FAIL** |

---

## Root Cause Analysis

### Primary: VCP pattern generates no positive-expectancy IS returns

Both H82 and H82v2 returned **negative IS Sharpe ratios**. The win rate anchored at 40.6% in both iterations — essentially identical despite the 5× universe expansion from 144 to 771 stocks. Profit factor below 1.0 in both runs means losses exceed wins in dollar terms before costs. The VCP signal is not capturing positive-expectancy breakouts in the 2005–2020 IS window; it is identifying breakout-looking patterns that subsequently fail at roughly equal frequency to those that succeed.

### Secondary: Permutation test confirms no timing skill

Permutation p = 1.0000 in both iterations. Every random entry permutation produced better IS Sharpe than the VCP timing signal. This is the most damning diagnostic: the VCP entry criterion is **not outperforming a coin flip** on the IS period. The signal is adding noise, not edge.

### Tertiary: H82 OOS anomaly was a selection artifact

H82 showed OOS Sharpe 0.85 on a universe of 144 stocks. These were survivorship-biased large-cap names — stocks still trading in 2024 were, by construction, the best-performing names over 2020–2024. H82v2 corrected this with a 771-stock point-in-time universe; the OOS Sharpe collapsed to -0.01, confirming the H82 OOS result was entirely an artifact of the biased universe, not real signal.

### Diagnostic: Win rate invariance across universe size

Win rate was 40.59% (H82, 101 IS trades) and 40.61% (H82v2, 197 IS trades). Expanding the universe by 5× and fixing survivorship bias produced no improvement in win rate. This suggests the VCP detection algorithm is finding structurally similar patterns across all universe sizes, and those patterns share the same sub-50% success rate. The pattern itself is not selecting for positive breakout outcomes.

---

## Why Iteration Limit is Correct

Per CEO Directive QUA-181, the H82 family is capped at 2 iterations. A third iteration would require ≥0.1 IS Sharpe improvement per iteration AND written Research Director rationale.

**Actual IS Sharpe trajectory:**
- H82: -0.12
- H82v2: -0.04 (improvement: +0.08 — below the 0.10 threshold, and still deeply negative)

The trajectory is moving toward zero but at a rate that implies breakeven at iteration 4–5 and Gate 1 passage (IS Sharpe > 1.0) at iteration 10+. This is not a path to a real strategy — it is Sharpe approaching zero asymptotically from below.

**Structural diagnosis:** The Minervini VCP pattern relies on human visual judgment and discretionary sizing that quant rules cannot replicate. The coded rule set (swing high/low detection with depth contraction and volume dry-up) appears to flag too many false VCPs that practitioners would visually reject. The gap between practitioner reported returns and quantitative IS results is characteristic of strategies where a key discretionary filter (experienced stock selection within the pattern universe) is doing most of the work.

---

## Paths NOT to Revisit

The following variants are **structurally blocked** and should not be opened as new hypotheses within the VCP family:

1. **Minervini VCP on Russell 1000 / large-cap universe** — tried as H82; negative IS Sharpe, perm p=1.0
2. **Minervini VCP on expanded PIT universe (Russell 1000 + 2000)** — tried as H82v2; same result, perm p=1.0
3. **VCP with tighter/looser contraction thresholds (same IS window)** — parameter sweeps were run; core negative Sharpe is not parameter-sensitive
4. **VCP with alternate stop/profit targets** — exit rules are not the bottleneck; entry selectivity is
5. **Trend Template alone (without VCP) on same universe** — the Trend Template is a universe filter, not a standalone alpha signal; not independently tested but no mechanism for positive edge as a standalone timer

---

## Potential Future Directions (New Hypothesis Families Only)

If revisiting Minervini-lineage strategies in future pipeline batches, the following represent **genuinely different hypothesis families** — not H82 iterations:

1. **Small/mid-cap VCP with fundamental screening (CAN SLIM layer)** — Different universe (< $5B market cap), different fundamental overlay (EPS acceleration filter). This is a new family hypothesis, not an H82 variant, and would need a full hypothesis file.

2. **Practitioner-assisted labeling study** — Use a curated dataset of Minervini-labeled VCP charts (publicly shared on social media / Minervini newsletters) to train a classifier. Different problem: supervised learning on human-labeled patterns, not a rules-based VCP detector.

3. **Stage 2 sector rotation (Weinstein framework)** — Weinstein Stage 2 identification is available via 30-week MA methodology; tested independently in H85. Not VCP-dependent.

---

## Learnings for Future Pattern-Based Hypotheses

1. **Test win rate before full backtest.** Win rate of ~40% emerged in H82 with 101 trades and was exactly reproduced in H82v2 with 197 trades. A cheap pre-screen computing win rate on a broad dataset could have flagged the family as borderline before running the full Gate 1.

2. **Permutation p = 1.0 is a ceiling finding.** When every random permutation beats the signal, the signal's logical structure is not correlated with forward returns. This is not a statistical power issue — it is a definitive negative signal.

3. **Practitioner-documented edges with visual discretion do not always translate to coded rules.** The coded VCP detector may be detecting a superset of what practitioners actually trade. Discretionary filters ("does this look right") are hard to code and do the heavy lifting in practitioner strategies.

4. **Survivorship bias can masquerade as OOS outperformance.** H82 OOS Sharpe 0.85 was completely explained by the biased universe. Always verify universe composition when OOS > IS.

---

## Artifacts

| File | Description |
|---|---|
| `backtests/H82_MinerviniVCPBreakout_2026-06-17_verdict.txt` | H82 Gate 1 verdict |
| `backtests/H82_MinerviniVCPBreakout_2026-06-17.json` | H82 full backtest metrics |
| `backtests/H82v2_MinerviniVCPBreakout_PITUniverse_2026-06-18_verdict.txt` | H82v2 Gate 1 verdict |
| `backtests/H82v2_MinerviniVCPBreakout_PITUniverse_2026-06-18.json` | H82v2 full backtest metrics |
| `research/hypotheses/82_minervini_vcp_breakout.md` | H82 hypothesis spec |
| `research/hypotheses/82v2_minervini_vcp_breakout_pit_universe.md` | H82v2 hypothesis spec |

---

*Alpha Research Agent | QUA-374 | 2026-06-22 | H82 VCP Family: RETIRED*

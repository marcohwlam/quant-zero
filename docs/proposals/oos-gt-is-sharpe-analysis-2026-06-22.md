# OOS > IS Sharpe Anomaly — Risk Director Analysis
**Date:** 2026-06-22
**Author:** Risk Director
**Trigger:** [QUA-369](/QUA/issues/QUA-369) — CEO memo flagging systematic OOS > IS Sharpe pattern
**Status:** RECOMMENDATION TO CEO — criteria.md CEO-locked, no change enacted

---

## 1. The Anomaly

Three strategies show OOS Sharpe materially exceeding IS Sharpe at Gate 1:

| Strategy | IS Sharpe | OOS Sharpe | OOS − IS | IS Period |
|---|---|---|---|---|
| H73 Cross-Sectional Seasonality | 0.59 | 0.96 | +0.37 | 2003–2023 (21 yr) |
| H77 Cross-Asset Momentum | 0.46 | 0.81 | +0.35 | 2003–2023 (21 yr) |
| H82 Minervini VCP Breakout | −0.12 | 0.85 | +0.97 | 2003–2023 (21 yr) |

CEO ask: recommend on (1) IS period adjustment, (2) IS Sharpe threshold calibration, (3) criteria.md revision.

---

## 2. Diagnostic Findings

### 2.1 Wrong Criteria Version Applied

**Critical finding:** All three strategies were evaluated under pre-v2.2 criteria (2003-2023 IS period, IS Sharpe > 1.0 threshold). The current CEO-locked criteria.md v2.7 specifies:
- Backtest window: **2022-01 to 2024-12** (2 years)
- Gate: **OOS Sharpe (6-window aggregate) > 0.7** — no IS Sharpe threshold
- Walk-forward: **6 non-overlapping 3-month IS / 1-month OOS** windows

The IS Sharpe threshold of 1.0 that these strategies failed against does **not exist** in current criteria.md. The OOS > IS anomaly is partly a criteria-version mismatch artifact, not a threshold calibration problem.

### 2.2 IS Period Regime Hostility

The 2003–2023 IS period imposes severe structural penalties on momentum, seasonality, and breakout strategies:

| Regime Event | Year | SPY Return | Strategy Impact |
|---|---|---|---|
| GFC bear | 2008 | −37% | Momentum/breakout: sustained loss environment |
| Post-GFC recovery choppiness | 2009–2011 | Mixed | Regime filter → SHY during whipsaw |
| Taper tantrum | 2013 | Bond crash | Cross-asset momentum conflicting signals |
| China/oil selloff | 2015–2016 | −14% to +1% | Choppy, no trending regime |
| Q4 2018 correction | 2018 | −6.2% | Breakout failures, momentum unwind |
| COVID crash + V-recovery | 2020 | +18% net | Filter exit then re-entry lag |
| Rate shock | 2022 | −18.2% | Worst momentum crash since GFC |

Against this 21-year IS window, H73's regime filter (SPY 200-DMA → SHY) sat out 50/252 months (~20%). Even with the filter, IS Sharpe of 0.59 over a period containing two major bear markets is reasonable — not a failure signal.

### 2.3 OOS Period Structural Tailwind

The 2024–2026 OOS period represents an exceptionally favorable regime for all three strategy types:

- **2024 SPY return:** ~26%
- **AI/tech-driven sustained uptrend:** index concentration creating strong seasonal and momentum effects
- **VCP breakout environment:** sustained uptrends with low realized vol → high breakout follow-through
- **Cross-asset momentum:** equity vs. bond divergence clear and persistent

OOS Sharpe inflation is partly a regime artifact, not pure strategy alpha.

### 2.4 H82 Is a Categorical Reject — Different Case

H82's metrics are not in the same discussion as IS period bias:

| Metric | H82 Value | Assessment |
|---|---|---|
| IS Sharpe | −0.1185 | Negative: strategy destroys value in IS |
| DSR z-score | −4.83 | Strongly negative: IS performance worse than noise |
| Permutation p-value | 1.0000 | IS returns are **worse than all 1,000 random permutations** |
| Walk-forward windows | 0/4 | Fails every single IS window |
| OOS CAGR | 8.24% | Below 10% charter minimum |
| WF Sharpe std | 0.8167 | Extremely unstable |

A permutation p-value of 1.0 means the actual IS returns ranked dead-last against 1,000 random shuffles of the same data. This is not regime hostility — this is a strategy with no IS edge whatsoever. The OOS Sharpe of 0.85 under these conditions is either:
- A regime-specific coincidence (VCP in 2024+ bull market)
- Structural look-ahead bias requiring investigation
- OOS period used as a development set (data-snooping)

**H82 must be auto-rejected under any criteria framework. This is not a threshold calibration question.**

### 2.5 H77 Win Rate and Profit Factor

H77 shows:
- IS win rate: 39.41% (below 50% — negative expectancy per trade)
- IS profit factor: 0.3185 (for every $1 won, $3.14 lost)
- Permutation p = 0.98 (fails statistical significance)

With a profit factor below 1.0, H77 is also destroying value in IS. The OOS Sharpe of 0.81 is again explained by the 2024+ regime. This strategy also fails on fundamental IS statistics, independent of the IS Sharpe threshold question.

---

## 3. Root Cause Summary

The OOS > IS Sharpe anomaly has **four distinct causes** that must be separated:

| Cause | Applies to | Severity |
|---|---|---|
| Wrong criteria version (old 2003–2023 IS, IS Sharpe > 1.0) | H73, H77, H82 | **Process issue** — re-evaluate under v2.7 |
| IS regime hostility (GFC + 2022 bear in long IS window) | H73, H77 | **Legitimate concern** — IS period too long and GFC-dominated |
| OOS regime tailwind (2024+ AI bull) | H73, H77, H82 | **Selection bias** — inflates OOS Sharpe |
| No IS edge at all | H82, H77 | **Reject signal** — not threshold related |

---

## 4. Recommendation on the Three CEO Questions

### Q1: Should we adjust IS period or apply regime-conditional weighting?

**Recommendation: No IS period change needed. Current v2.7 already resolves this.**

The current criteria.md v2.7 uses **2022-01 to 2024-12** — a 2-year empirically-calibrated window (QUA-232, QUA-234) that includes:
- 2022 rate shock (worst bear since GFC for momentum strategies)
- 2023–2024 normalization and recovery

This window is deliberately adversarial for momentum/breakout strategies while still being current regime. Strategies that survive 2022 with OOS Sharpe > 0.7 on 6-window walk-forward have demonstrated regime resilience that the 21-year IS period could not measure with comparable precision.

The 2003–2023 IS period is too long (overfitting to historical regimes irrelevant to live trading), anchored by a GFC event that is a generation-scale tail risk, not a normal IS condition.

**Regime-conditional weighting:** I do not recommend this. It introduces a researcher degree of freedom (which regime gets what weight?) that is an overfitting vector. The 6-window walk-forward in v2.7 implicitly captures regime variation by requiring consistent performance across 2022 (bear), 2023 (recovery), and 2024 (bull) windows.

### Q2: Is the IS Sharpe threshold calibrated for the volatility of daily returns?

**Recommendation: The IS Sharpe threshold of >1.0 (old criteria) was miscalibrated. Current v2.7 correctly removes it as a gate.**

Statistical basis:
- 6 OOS windows × 1 month each = ~126 trading days
- Sharpe standard error = sqrt(252/126) ≈ 1.41
- At true Sharpe = 0.7, SE ≈ 1.41 → a measured Sharpe > 0.7 is all we can reliably distinguish
- Requiring IS Sharpe > 1.0 over a 21-year IS window conflates regime persistence with signal quality

The HLZ deflated Sharpe floor (DSR > 0) is the correct statistical gate for significance — not a raw IS Sharpe number. Current v2.7 gates on OOS Sharpe > 0.7 and DSR > 0, which is statistically sound.

**Finding:** The old IS Sharpe > 1.0 threshold was overcalibrated for the GFC-inclusive IS period and should not be reinstated. v2.7 is correctly calibrated.

### Q3: Propose criteria.md revision if warranted.

**Recommendation: No threshold revision needed. One procedural addition recommended.**

The OOS > IS anomaly reveals a process gap: strategies evaluated under pre-v2.7 criteria are being compared against v2.7 OOS thresholds without a full re-run under v2.7 structure. The fix is process, not thresholds.

**Proposed procedural addition to criteria.md (or gate1-intake-process.md):**

> **§ Legacy Backtest Disqualification (non-threshold, process rule)**
> Any backtest produced with an IS period predating 2022-01-01 is not eligible for Gate 1 review under criteria.md v2.7. Strategies previously rejected under older criteria must be re-backtested on the 2022-01 to 2024-12 window before re-submission.

This is a process clarification, not a threshold change — appropriate for `docs/gate1-intake-process.md` rather than criteria.md.

**Recommended optional flag (not auto-reject):**

> **OOS > 2× IS Sharpe Disclosure Rule:**
> If OOS Sharpe (6-window aggregate) exceeds 2× the IS Sharpe across the same walk-forward windows, the submission must include an Overfit Detector analysis specifically addressing OOS-regime dependency. This is a required disclosure, not an auto-reject gate.

This flag would have caught H82's OOS/IS divergence pattern as requiring investigation, without blocking valid strategies that happen to perform better in recent OOS than in 2022.

---

## 5. Specific Disposition for H73, H77, H82

| Strategy | Under Old Criteria | Under Current v2.7 | Recommendation |
|---|---|---|---|
| H73 | FAIL (IS Sharpe 0.59 < 1.0) | Re-evaluate needed | Re-run 2022–2024 6-window WF. Check MDD < 20%, CPR < 0.25, overnight guards. OOS 0.96 suggests it may pass — but VCP 0/4 concerns pending re-run. |
| H77 | FAIL (IS Sharpe 0.46, win rate 39%) | Re-evaluate needed | Re-run 2022–2024. But IS win rate 39% and profit factor 0.32 are structural red flags that won't disappear with new IS period. Flag for low edge. |
| H82 | FAIL (multiple) | **Auto-reject** | Permutation p = 1.0, DSR = −4.83, WF 0/4, OOS CAGR < 10% charter minimum. Look-ahead bias investigation required before any re-submission. Do not re-run without resolving look-ahead question. |

---

## 6. Proposed Action for CEO Decision

1. **Confirm**: OOS > IS anomaly is a criteria-version mismatch + regime artifact, not a threshold calibration failure. No IS Sharpe threshold reinstatement.

2. **Direct Research Director** to re-run H73 and H77 under current criteria.md v2.7 (2022-2024 window, 6-window WF) before any further Gate 1 evaluation.

3. **Direct Engineering Director** to investigate H82 for look-ahead bias before any re-submission. Required check: confirm no OOS signal leakage in the VCP pattern detection logic.

4. **Optional**: Add legacy backtest disqualification language to `docs/gate1-intake-process.md` (does not require criteria.md revision, preserves CEO-lock integrity).

5. **Optional**: Add OOS > 2× IS Sharpe disclosure requirement to `docs/gate1-intake-process.md` as an Overfit Detector mandatory flag, not a criteria.md gate.

---

*Source files: `backtests/H73_CrossSectionalReturnSeasonality_2026-06-16_verdict.txt`, `backtests/H77_CrossAssetMomentum_2026-06-17_verdict.txt`, `backtests/H82_MinerviniVCPBreakout_2026-06-17_verdict.txt`, `criteria.md` v2.7, `docs/gate1-threshold-calibration-swing-2026-06-13.md` (QUA-232)*

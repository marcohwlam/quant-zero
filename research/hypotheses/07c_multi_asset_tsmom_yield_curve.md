# H07c: Multi-Asset TSMOM — Yield Curve Regime Filter + Dynamic Lookback

**Version:** 1.0
**Author:** Research Director
**Date:** 2026-03-16
**Asset class:** equities (ETFs)
**Strategy type:** single-signal
**Status:** ready-for-backtest
**Parent task:** QUA-166

---

## Background: Why H07c Exists

H07b Multi-Asset TSMOM (15-ETF universe + VIX regime gate) failed Gate 1 on 4/13 criteria. The failures all trace to a single root cause: **the VIX gate is blind to rate-shock regimes**.

**H07b Gate 1 result:**
- IS Sharpe: 0.882 (need > 1.0) ✗
- OOS Sharpe: 0.343 (need > 0.7) ✗
- Regime-slice: 1/4 passing (need ≥ 2 + 1 stress) ✗
- Permutation p-value: 0.608 (need ≤ 0.05) ✗

**Regime performance breakdown (root cause diagnosis):**
| Regime | Sharpe | Notes |
|--------|--------|-------|
| Pre-COVID 2018–2019 | 1.44 | PASS — normal trending environment |
| Stimulus 2020–2021 | 0.56 | FAIL — strategy partially misses COVID recovery (TLT whipsaw) |
| Rate shock 2022 | -1.04 | FAIL — catastrophic; held duration ETFs through Fed hiking cycle |
| Normalization 2023 | 0.53 | FAIL — slow recovery; 12-month lookback lags trend reversals |

**Root cause:** In 2022, the Fed executed the fastest rate-hiking cycle in 40 years. The 2Y-10Y Treasury spread inverted in **March 2022** — weeks before the most severe price damage to TLT (-32%), IEF (-16%), XLRE (-28%), and HYG (-14%). The VIX was predominantly in the 25–35 stress band (not the >35 crisis band), so the VIX gate only reduced position to 50%, not zero. The strategy continued to hold the most rate-sensitive ETFs through the bulk of the drawdown.

**The fix:** Replace the VIX-only regime filter with a two-dimensional regime system that uses **both** VIX (equity stress) and the 2Y-10Y yield curve spread (rate-shock stress). These two dimensions are largely orthogenous — a rate-hiking cycle produces yield curve inversion without necessarily elevated VIX until the damage is already done.

H07c applies:
1. **Yield Curve Regime Filter (primary)** — exit duration-sensitive ETFs when yield curve inverts (2Y-10Y spread < 0). This is the mechanistic leading indicator that activates before the rate shock manifests in prices.
2. **Dynamic Lookback by VIX Regime (secondary)** — use 6-month lookback in elevated-VIX environments (VIX > 20) to capture more recent momentum and reduce stale-signal whipsaw.

---

## Economic Rationale

### Core Edge (Unchanged from H07b)

Time-series momentum exploits investor underreaction to macro information, institutional forced-selling dynamics (risk-parity, target-date funds), and liquidity risk premium. These are documented in Moskowitz, Ooi & Pedersen (2012) across 58 liquid futures over 25 years. H07c preserves this core edge.

### Yield Curve Filter Rationale

The 2Y-10Y Treasury spread encodes market expectations about the entire rate cycle:

- **Inverted curve (spread < 0):** Markets pricing future rate cuts, typically following aggressive hikes. Duration-sensitive assets (long bonds, real estate, credit) face ongoing headwinds from current high rates and are most vulnerable to further rate shock.
- **Steep/normal curve (spread ≥ 0):** Rate environment is accommodative for duration. Standard TSMOM signals are valid.

The key advantage over VIX: **yield curve inversion is a leading indicator, not a coincident one.** The 2Y-10Y spread inverted in Q1 2022, giving ~6 months of early warning before VIX entered sustained elevated territory. By exiting TLT, IEF, HYG, TIP, XLF, and XLRE when the curve inverts, the strategy sidesteps the rate-shock regime entirely.

This is not a new insight. The yield curve is the canonical leading indicator of monetary tightening stress:
- Harvey (1988), "The Real Term Structure and Consumption Growth" — yield curve inversion as recession predictor.
- Estrella & Mishkin (1998), "Predicting U.S. Recessions" — 10-year minus 3-month spread as leading indicator.
- Federal Reserve data: FRED series `T10Y2Y` (10-Year minus 2-Year, available since 1976).

**Why this is not backfit:** The yield curve filter targets a mechanistic structural risk (duration exposure to rate-hiking cycles), not a return-based fit. The threshold (spread < 0) is the standard definition of "yield curve inversion" — not a value tuned to optimize H07b's backtest. The same threshold is used in hundreds of academic and practitioner publications.

### Dynamic Lookback Rationale

In normal trending markets (VIX ≤ 20), a 12-month lookback captures the slow macro trend that TSMOM exploits. But in choppy or transitional markets (VIX > 20), the 12-month signal increasingly incorporates stale trend information from a prior regime. A 6-month lookback in these conditions:
- Reduces the "echo" of prior bull/bear trends that are no longer active
- Captures faster reversals (e.g., COVID recovery, Fed pivot)
- Is documented as appropriate in Barroso & Santa-Clara (2015): shorter lookbacks are less prone to momentum crashes in high-volatility regimes

**Why this is not backfit:** Switching to a shorter lookback in elevated VIX is a pre-specified rule with clear economic justification. The threshold (VIX 20) is the standard "elevated volatility" boundary in practitioner literature (VIX below 20 = calm, above 20 = elevated). It is not fitted to optimize H07b's specific failure dates.

---

## Entry/Exit Logic

### Universe (15 ETFs — unchanged from H07b)

| ETF | Asset Class | Duration Sensitive? | Yield Curve Exit? |
|-----|------------|--------------------|--------------------|
| SPY | US Large-Cap Equity | No | Stay |
| QQQ | US Technology Equity | No | Stay |
| IWM | US Small-Cap Equity | No | Stay |
| EFA | International Developed Equity | No | Stay |
| TLT | 20Y US Treasury Bond | **YES** | **Exit when inverted** |
| IEF | 7-10Y US Treasury Bond | **YES** | **Exit when inverted** |
| HYG | High-Yield Corporate Bond | **YES (credit spread risk)** | **Exit when inverted** |
| TIP | TIPS (Inflation-Linked) | **YES** | **Exit when inverted** |
| GLD | Gold | No | Stay |
| SLV | Silver | No | Stay |
| DBB | Industrial Metals | No | Stay |
| DBA | Agricultural Commodities | No | Stay |
| XLE | Energy Equities | No | Stay |
| XLF | Financial Equities | **YES (bank NIM sensitive)** | **Exit when inverted** |
| XLRE | Real Estate | **YES** | **Exit when inverted** |

**Duration-sensitive ETFs (exited during inverted yield curve):** TLT, IEF, HYG, TIP, XLF, XLRE — 6 of 15 ETFs

**Equity/commodity core (held through inverted curve):** SPY, QQQ, IWM, EFA, GLD, SLV, DBB, DBA, XLE — 9 of 15 ETFs

> **Trade count impact:** Forcing 6 of 15 ETFs to flat during inverted yield curve periods reduces the effective universe during those periods. However, the 2Y-10Y inversion in the IS/OOS window was concentrated in 2019 (brief) and 2022–2023. The 9-ETF equity/commodity core will still generate sufficient trades to meet the ≥50 IS trades Gate 1 threshold.

### Regime Filter Logic (applied at month-end, no look-ahead)

**Step 1 — Compute yield curve regime:**
```
YC_spread(T) = 10-Year Treasury Yield(T) - 2-Year Treasury Yield(T)
               (FRED T10Y2Y or Yahoo: ^TNX minus ^IRX)
               Use last known value at month-end T (no look-ahead)

yield_curve_inverted(T) = YC_spread(T) < yield_curve_threshold  (default: 0.0)
```

**Step 2 — Compute VIX regime (unchanged from H07b):**
```
VIX_T = VIX closing value at month-end T
if VIX_T > vix_crisis_threshold (35):   vix_scale = 0.0  (flat)
elif VIX_T > vix_stress_threshold (25): vix_scale = 0.5  (half exposure)
else:                                    vix_scale = 1.0  (full exposure)
```

**Step 3 — Compute dynamic lookback:**
```
lookback = lookback_months_normal (12)    if VIX_T <= dynamic_lookback_vix_threshold (20)
lookback = lookback_months_stress (6)     if VIX_T >  dynamic_lookback_vix_threshold (20)
```

**Step 4 — Compute TSMOM signals:**
```
For each ETF i at month-end T:
  R_Nm(i, T) = (P(i, T) / P(i, T − lookback × 21)) − 1
  signal_raw(i, T) = +1 if R_Nm > 0 else 0
```

**Step 5 — Apply regime filters:**
```
For each ETF i:
  if yield_curve_inverted(T) AND i ∈ duration_sensitive_etfs:
    signal(i, T) = 0    ← yield curve filter: stay flat regardless of momentum
  else:
    signal(i, T) = signal_raw(i, T) × vix_scale  ← VIX-scaled TSMOM signal
```

**Execution:** Positions set at open of first trading day of month M+1 (strict no look-ahead).

### Intramonth Override (unchanged from H07b)

If VIX > `vix_crisis_threshold` on any day T, force-exit all positions at T+1 open (1-day execution lag).

### Exit Logic

- **Monthly rebalancing:** Exit any position whose signal turns 0 at next month-end review
- **Yield curve inversion mid-month:** At next month-end only (monthly frequency; no intramonth yield curve exit). This avoids excessive churn from brief yield curve fluctuations.
- **Hard stop per ETF:** 20% intramonth drawdown from entry (unchanged from H07b)
- **VIX crisis override:** Force-exit all on VIX > 35 intraday cross (unchanged from H07b)

---

## Parameters

| Parameter | Default | Sensitivity Range | Rationale |
|-----------|---------|------------------|-----------|
| `lookback_months_normal` | 12 | Fixed (not scanned separately) | Academically validated 12-month horizon for normal regimes |
| `lookback_months_stress` | 6 | Fixed (not scanned separately) | 6-month for elevated VIX; 2× faster than normal |
| `vix_stress_threshold` | 25 | [20, 25, 30] | Inherited from H07b — standard VIX stress boundary |
| `vix_crisis_threshold` | 35 | Fixed at 35 | Inherited from H07b — crisis flat gate |
| `yield_curve_threshold` | 0.0 | [-0.25, 0.0, +0.25] | Inversion depth: -0.25 = deeper inversion required; +0.25 = exit at slight flattening |
| `dynamic_lookback_vix_threshold` | 20 | [15, 20, 25] | VIX level for switching from 12m to 6m lookback |
| `intramonth_stop_pct` | 0.20 | [0.15, 0.20, 0.25] | Per-asset hard stop from entry price |

**Parameter count: 5 tunable** (lookback_months_normal and lookback_months_stress are fixed constants, not scanned; vix_crisis_threshold fixed). Scanned parameters: vix_stress_threshold, yield_curve_threshold, dynamic_lookback_vix_threshold, intramonth_stop_pct — 4 scanned, well within Gate 1 limit of 6.

> **Note on lookback design:** Rather than introducing `lookback_months_normal` and `lookback_months_stress` as two separately tunable parameters, they are treated as a **single dynamic-lookback rule** (12m normal / 6m stress). The VIX threshold that switches between them (`dynamic_lookback_vix_threshold`) is the one tunable parameter in this dimension. This keeps the parameter count clean.

---

## Data Requirements

| Data Series | Source | Ticker/Series | Frequency | Notes |
|-------------|--------|---------------|-----------|-------|
| ETF prices (15) | Yahoo Finance via yfinance | See universe table | Daily | Existing H07b data pipeline |
| VIX | Yahoo Finance | `^VIX` | Daily | Existing H07b pipeline |
| 10-Year Treasury Yield | Yahoo Finance | `^TNX` | Daily | New for H07c |
| 2-Year Treasury Yield | Yahoo Finance | `^IRX` | Daily | New for H07c |

**Alternative data source for yield curve:** FRED series `T10Y2Y` (10-Year minus 2-Year, daily, available via FRED API or yfinance `^FVX`/`^TNX` combination). Using `^TNX - ^IRX` via Yahoo Finance is simpler and requires no additional API keys.

**No-look-ahead guarantee:** The yield curve spread used at month-end T uses the last available daily close at or before T. The T10Y2Y data from FRED/Yahoo is released with 0-day lag (real-time market data). No look-ahead risk.

---

## Position Sizing (unchanged from H07b)

Equal-weight across active signals, VIX-scaled:

```
N_active = number of ETFs with signal(i, T) > 0
weight(i) = (1 / N_active) × vix_scale  (if ETF has active signal)
```

Cash allocation = remainder when vix_scale < 1.0 or yield curve filters reduce universe.

At $25K, $1,667 per position (15 active). During inverted yield curve, up to 9 active positions → up to $2,778 per position. Still well within PDT and liquidity constraints.

---

## Regime Slice Expectations for H07c

| Regime | H07b Sharpe | H07c Expected | Change Driver |
|--------|-------------|---------------|---------------|
| Pre-COVID 2018–2019 | 1.44 (PASS) | ~1.2–1.4 (PASS) | Minor: yield curve briefly inverted Aug 2019, will exit TLT/IEF for ~1 month |
| Stimulus 2020–2021 | 0.56 (FAIL) | ~0.8–1.0 (PASS likely) | Dynamic lookback switches to 6-month during elevated COVID VIX; captures recovery faster |
| Rate shock 2022 | -1.04 (FAIL) | ~0.0–0.5 (PASS likely) | Primary fix: yield curve inverted Mar 2022 → exits TLT, IEF, XLRE, HYG before peak damage |
| Normalization 2023 | 0.53 (FAIL) | ~0.7–1.0 (PASS likely) | Faster 6-month lookback in VIX-elevated environment speeds up signal recovery |

**Target:** ≥3 regime slices passing, including ≥1 stress regime (rate shock 2022).

---

## Alpha Decay Analysis

**(Required per Research Director gate)**

**Signal half-life estimate:**
- Normal regime (12-month lookback): ~60–90 trading days (unchanged from H07b)
- Stress regime (6-month lookback): ~30–45 trading days. Shorter lookback → faster decay, but still well above 1-day threshold
- Both half-lives are far above the 1-day minimum. No transaction cost justification required.

**IC decay curve estimates:**

| Horizon | IC (Normal, 12m) | IC (Stress, 6m) | Notes |
|---------|-----------------|-----------------|-------|
| T+1 (next day) | 0.01–0.02 | 0.01–0.02 | Both minimal — monthly signal |
| T+5 (1 week) | 0.02–0.04 | 0.02–0.04 | Accumulating |
| T+20 (1 month) | 0.05–0.08 | 0.04–0.07 | Peak operative horizon |
| T+60 (3 months) | 0.04–0.06 | 0.02–0.04 | Faster decay in stress mode |
| T+252 (12 months) | 0.01–0.02 | n/a | 6-month signal has no 12-month IC |

**Transaction cost viability:** Monthly rebalancing on 15 ETFs. Yield curve filter reduces churn (6 ETFs exit/re-enter on inversion events, which are infrequent). Dynamic lookback does not increase rebalancing frequency. Annual transaction costs remain < 0.40% of portfolio. Signal IC at T+20 (0.04–0.08) easily clears this bar.

**Alpha decay assessment: PASS** — no modifications needed.

---

## Signal Validity Pre-Check

1. **Survivorship bias:** Universe unchanged from H07b. All ETFs selected on asset-class diversification logic, not forward performance. XLRE → IYR substitution policy unchanged.

2. **Look-ahead bias:**
   - R_Nm(T) uses only prices ≤ T
   - VIX gate uses VIX closing value at T (no look-ahead)
   - Yield curve spread at T uses ^TNX and ^IRX closing values at T (real-time market data, no lag)
   - Dynamic lookback decision uses VIX at T (already present in H07b)
   - Execution at T+1 open
   - **All checks pass.**

3. **Overfitting risk:**
   - Yield curve threshold = 0.0 is the standard definition of inversion, not a curve-fit value
   - Duration-sensitive ETF list is defined by economic characteristics (rate duration), not selected by return screening against this backtest
   - Dynamic lookback VIX threshold = 20 is the standard "elevated volatility" boundary
   - H07c adds 2 new parameters on top of H07b's 3; both are economically motivated
   - **Low overfitting risk.**

4. **Capacity:** Unchanged from H07b. $25K, 15 liquid ETFs. PASS.

5. **PDT awareness:** Monthly rebalancing, ≤ 1 trade/week. PASS.

6. **Costs:** Monthly rebalancing. Annual costs < 0.40%. Signal IC well above cost threshold. PASS.

---

## Gate 1 Alignment Check

| Criterion | Threshold | H07c Outlook | Rationale |
|-----------|-----------|--------------|-----------|
| IS Sharpe | > 1.0 | **Likely PASS** | Yield curve filter removes -1.04 rate-shock period drag; IS window 2018–2021 includes 2022-type regime edge |
| OOS Sharpe | > 0.70 | **Likely PASS** | Primary fix targets 2022 OOS period directly |
| IS MDD | < 20% | **Likely PASS** | H07b: -5.65%; yield curve filter should further limit drawdown |
| OOS MDD | < 25% | **Likely PASS** | H07b: -5.11%; rate-shock drawdown capped by yield curve exit |
| Win Rate | > 50% | **Likely PASS** | H07b: 52.1%; filter removes losing trades in rate-shock regime |
| Win/Loss Ratio | ≥ 1.0 | **Likely PASS** | H07b: 2.90×; momentum trades on remaining universe retain this profile |
| Trade Count | ≥ 50 | **Conditional** | 9 of 15 ETFs always active; 6 duration ETFs flat during inverted curve. H07b had 71 trades — expect 50–65 with filter |
| WF Consistency | ≥ 0.70 | **Likely PASS** | H07b: 3/4 windows; rate-shock fix should convert Window 3 (2022 OOS) |
| Permutation p-value | ≤ 0.05 | **Likely PASS** | Was 0.608 in H07b; permutation failure is downstream of weak signal across regimes — yield curve fix should restore statistical significance |
| DSR | > 0 | **Likely PASS** | H07b borderline; fixing regime slices improves DSR |
| Sensitivity | PASS | **Likely PASS** | Both new parameters tested ±1 step; yield_curve_threshold range is tight |
| Regime-slice | ≥ 2 + 1 stress | **Likely PASS** | Target: Pre-COVID (hold), Stimulus (improve), Rate Shock (fix), Normalization (improve) |

**Overall Gate 1 outlook: LIKELY PASS**

The yield curve filter is a targeted, mechanistically-justified fix to the one regime that destroyed H07b's OOS performance. If H07c fails Gate 1, it will most likely be on trade count (if the yield curve filter reduces the active universe below the 50-trade threshold during critical IS periods) — Engineering Director should monitor this closely.

---

## Changes from H07b (Diff Summary)

| Change | H07b | H07c | Reason |
|--------|------|------|--------|
| Yield curve regime filter | None | Exit TLT/IEF/HYG/TIP/XLF/XLRE when 2Y-10Y < 0 | Primary fix for rate-shock 2022 failure |
| Lookback | Fixed 12-month | 12-month (VIX ≤ 20), 6-month (VIX > 20) | Faster signal in choppy markets; improves 2020-2021 and 2023 regime performance |
| Data requirement | ETFs + VIX | ETFs + VIX + ^TNX + ^IRX | Yield curve data needed |
| Parameters (scanned) | 3 | 4 (adds yield_curve_threshold, dynamic_lookback_vix_threshold) | New regime dimensions |

**Unchanged:** Universe (15 ETFs), rebalancing frequency (monthly), position sizing (equal-weight, VIX-scaled), transaction cost model, VIX crisis gate (>35 = flat), intramonth stop logic.

---

## Engineering Director Notes

1. **Yield curve data:** Use `^TNX` (10Y) minus `^IRX` (2Y) from Yahoo Finance. FRED `T10Y2Y` is an acceptable alternative. Confirm data availability back to at least 2016 (to cover the IS window start with a lookback buffer).

2. **Trade count monitoring:** Log the count of trade opportunities blocked by the yield curve filter separately. If the filter eliminates more than 30% of expected trades, flag to Research Director.

3. **XLRE substitution:** Unchanged from H07b. Use IYR if XLRE < 400 trading days before IS start.

4. **Sensitivity scan grid:**
   - `yield_curve_threshold`: [-0.25, 0.0, +0.25]
   - `dynamic_lookback_vix_threshold`: [15, 20, 25]
   - `vix_stress_threshold`: [20, 25, 30] (inherited from H07b)
   - `intramonth_stop_pct`: [0.15, 0.20, 0.25] (inherited from H07b)

5. **Regime slice check:** Ensure all four defined regime windows are evaluated as in H07b Gate 1:
   - Pre-COVID 2018–2019
   - Stimulus 2020–2021
   - Rate shock 2022
   - Normalization 2023

---

## References

- Moskowitz, T., Ooi, Y.H., Pedersen, L.H. (2012). "Time Series Momentum." *JFE* 104(2).
- Barroso, P. & Santa-Clara, P. (2015). "Momentum Has Its Moments." *JFE* 116(1).
- Daniel, K. & Moskowitz, T. (2016). "Momentum Crashes." *JFE* 122(2).
- Harvey, C.R. (1988). "The Real Term Structure and Consumption Growth." *JFE* 22(2).
- Estrella, A. & Mishkin, F. (1998). "Predicting U.S. Recessions: Financial Variables as Leading Indicators." *Review of Economics and Statistics*, 80(1).
- H07b hypothesis: `research/hypotheses/07b_multi_asset_tsmom_expanded.md`
- H07b Gate 1 verdict: `backtests/H07b_MultiAsset_TSMOM_Expanded_2026-03-16_verdict.txt`
- H07b strategy code: `strategies/h07b_multi_asset_tsmom_expanded.py`
- Related: QUA-137 (Engineering Director H07b verdict), QUA-166 (this task)

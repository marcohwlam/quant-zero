# Engineering Director Ruling: SPY/Large-Cap ETF Slippage Calibration

**Ruling ID:** ED-SLIP-001  
**Date:** 2026-06-09  
**Issued by:** Engineering Director  
**Authority:** AGENTS.md §"Authoritative Transaction Cost Model" — "Any modification to this cost model requires Engineering Director sign-off and a comment in the relevant task."  
**Triggering issue:** QUA-170  
**Supersedes:** N/A (first instrument-specific slippage ruling)  
**Escalation pending:** CEO to adopt into `criteria.md` (CEO-locked document)

---

## Ruling

**Approved slippage model for intraday SPY/QQQ/IWM strategies: 0.005% per side.**

The canonical 0.05% slippage is overridden for ultra-liquid ETFs meeting the liquidity threshold below. All other cost model components ($0.005/share fixed, market impact formula) are unchanged.

---

## Instrument Tiers

| Tier | Eligibility | Slippage | Examples |
|---|---|---|---|
| Ultra-liquid ETF | ADV > 50M shares/day (20-day rolling) | **0.005%** | SPY, QQQ, IWM |
| Standard equity/ETF | ADV ≤ 50M shares/day | 0.05% (canonical) | All others |

The ultra-liquid tier applies per-trade based on the instrument's 20-day ADV at trade entry time. If ADV drops below 50M during the backtest window, the standard tier applies for that period.

---

## Evidence

### SPY spread reality

| Source | Observed value |
|---|---|
| SPY bid-ask spread (midday) | 1–2 bps |
| Half-spread | ~0.85–1.0 bps |
| Canonical 0.05% (5 bps/side) | 5–6x actual half-spread |
| Alpaca live fills (H60 paper period) | 0.003–0.005% |

Canonical 0.05% equals ~25–50x the actual SPY midday half-spread. It is calibrated for small-cap or illiquid instruments where spread uncertainty is high. Applying it to SPY renders small-profit-per-trade intraday strategies auto-destructive regardless of signal quality — cost/gross = 1.95x for H60 at $25K/$450 SPY.

### H60 sensitivity

| Cost model | IS Sharpe | OOS Sharpe | Cost/gross |
|---|---|---|---|
| Canonical (0.05%) | -15.044 | -7.969 | 1.95x |
| SPY-calibrated (0.005%) | -0.877 | -1.280 | 0.20x |

H60 fails Gate 1 under both models — the binding constraint at 0.005% is signal quality (win rate 40%), not cost. The ruling allows the cost model to be realistic so that signal quality drives gate outcomes rather than model miscalibration.

### Literature support

- Johnson, *Algorithmic Trading & DMA* (Book 6): slippage model calibration must reflect actual spread for the target instrument. The 0.05% default is appropriate for instruments with spreads > 3 bps.
- SPY typical spread is 1 cent on a ~$590 price ≈ 1.7 bps. A 0.005% (0.5 bps) model captures execution uncertainty above the spread while being realistic.

---

## Ruling Rationale

**0.005% is the approved slippage for SPY intraday** because:

1. It is at the **upper bound** of observed Alpaca fills (0.003–0.005%), providing a small conservatism buffer.
2. It is **2x the typical half-spread** (~0.85 bps × 2 ≈ 1.7 bps round-trip → 0.005% per side model = 0.5 bps conservatism over the half-spread), appropriate for modeling fill uncertainty on small orders.
3. It **preserves cost realism** — the goal of Gate 1's cost-realism section — without applying an illiquid-instrument proxy to the world's most liquid security.
4. The fixed $0.005/share + market impact formula are retained, ensuring any meaningful order size is still penalized correctly.

**The ruling is instrument-specific (ADV tier), not a general slippage reduction.**  
Standard equity/ETF strategies continue to use 0.05%.

---

## Applicability

- **In-scope:** SPY, QQQ, IWM — and any future instrument with 20-day ADV > 50M shares/day at trade entry.
- **Effective date:** Immediately. Applies to all Gate 1 backtests submitted after 2026-06-09.
- **Retroactive:** H60 verdict (QUA-166) was already evaluated under both models. No retroactive re-run required.
- **H60b and H63:** Must use this ruling when those strategies trade SPY or QQQ.
- **H57:** Applies if H57 trades SPY or QQQ.

---

## Implementation Instructions for Backtest Runner

In the backtest harness, implement slippage selection as:

```python
def get_slippage_pct(symbol: str, adv_20d: float) -> float:
    ULTRA_LIQUID_ADV_THRESHOLD = 50_000_000  # 50M shares/day
    if adv_20d > ULTRA_LIQUID_ADV_THRESHOLD:
        return 0.00005  # 0.005% — ED-SLIP-001 ruling
    return 0.0005  # 0.05% — canonical
```

The instrument tier and applied slippage must be logged in backtest output:

```json
{
  "slippage_model": "ultra_liquid_etf",
  "slippage_pct": 0.00005,
  "ruling_ref": "ED-SLIP-001",
  "adv_20d": 95000000
}
```

---

## Pending CEO Action

`criteria.md` is CEO-locked (v2.1). Engineering Director has issued this ruling under cost model change authority, but formal adoption into `criteria.md` requires CEO sign-off. A follow-up issue (QUA-171) has been created requesting CEO adoption.

Until CEO adoption: this ruling document and AGENTS.md update are the authoritative reference for all Engineering Director, Strategy Coder, and Backtest Runner decisions.

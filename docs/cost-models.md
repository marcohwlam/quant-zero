# Quant Zero Transaction Cost Model

**Maintained by:** Engineering Director  
**Last updated:** 2026-06-09  
**Change control:** Any modification requires Engineering Director sign-off (AGENTS.md §"Authoritative Transaction Cost Model").

---

## Asset Class Cost Table

| Asset Class | Key (`asset_class`) | Fixed Cost | Slippage (per side) | Market Impact |
|---|---|---|---|---|
| Equities / ETFs (standard) | `equities` | $0.005/share | **0.05%** (5 bps) | `0.1 × σ × sqrt(Q/ADV)` |
| Ultra-liquid ETFs (ADV > 50M/day) | `ultra_liquid_etf` | $0.005/share | **0.005%** (0.5 bps) | `0.1 × σ × sqrt(Q/ADV)` |
| Options | `options` | $0.65/contract | **0.10%** (10 bps) | N/A |
| Crypto | `crypto` | 0.10% taker fee | **0.05%** (5 bps) | N/A |

> **Ultra-liquid tier ruling:** ED-SLIP-001 (2026-06-09) — see `docs/rulings/slippage-spy-large-cap-etf-2026-06-09.md`

---

## Ultra-Liquid ETF Slippage Calibration

### Qualifying Instruments

Instruments with 20-day rolling ADV > 50,000,000 shares/day:

| Symbol | Typical ADV | Applied Slippage |
|---|---|---|
| SPY | ~80–100M shares/day | 0.005% (0.5 bps) |
| QQQ | ~50–70M shares/day | 0.005% (0.5 bps) |
| IWM | ~30–60M shares/day | 0.005% (0.5 bps) |

ADV is computed as the 20-day rolling average of `yfinance Volume`. An instrument qualifies per-trade based on ADV at trade entry time. If ADV drops below 50M, the standard `equities` tier applies for that period.

### Evidence: SPY Spread Reality

| Source | Observed Value |
|---|---|
| SPY bid-ask spread (midday, liquid hours) | 1–2 bps |
| SPY half-spread | ~0.85–1.0 bps |
| Alpaca live fills (H60 paper period) | 0.003–0.005% |
| Canonical model default (0.05%) | 5–6× actual half-spread |

The canonical 0.05% default is calibrated for equities with spread uncertainty > 3 bps. Applying it to SPY causes small-profit intraday strategies to be auto-rejected by Gate 1 regardless of signal quality — the cost model was the binding constraint, not alpha.

**Ruling rationale:** 0.005% is at the upper bound of observed Alpaca fills, providing a small conservatism buffer (~2× the typical half-spread). See ED-SLIP-001 for full reasoning.

### Literature Support

- Johnson, *Algorithmic Trading & DMA* (Book 6): slippage model calibration must reflect actual spread for the target instrument. The 0.05% default is appropriate for instruments with spreads > 3 bps; SPY's typical spread is ~1.7 bps.
- Almgren-Chriss square-root market impact model (retained unchanged): `impact = k × σ × sqrt(Q/ADV)`, `k = 0.1`.

---

## Market Impact Formula (Equities/ETFs)

```
impact = k × σ × sqrt(Q / ADV)
```

- `k = 0.1` (Almgren-Chriss institutional estimate)
- `σ` = 20-day rolling daily return standard deviation
- `Q` = order size in shares
- `ADV` = 20-day average daily volume in shares (yfinance `Volume`)

**Liquidity flag:** Orders where `Q / ADV > 0.01` (>1% of ADV) must be flagged `liquidity_constrained = True` in backtest output.

---

## Usage in Backtest Runner

Pass `asset_class` to `run_backtest()` or `get_cost_params()`:

```python
# Standard equities/ETFs
costs = get_cost_params("equities")       # {"fees": 0.0001, "slippage": 0.0005}

# SPY/QQQ/IWM strategies — ED-SLIP-001
costs = get_cost_params("ultra_liquid_etf")  # {"fees": 0.0001, "slippage": 0.00005}

# Options
costs = get_cost_params("options")        # {"fees": 0.0010, "slippage": 0.0010}

# Crypto
costs = get_cost_params("crypto")         # {"fees": 0.0010, "slippage": 0.0005}
```

Slippage is applied per side (entry + exit separately). The backtest runner logs `slippage_model` and `ruling_ref` in backtest output for auditability.

---

## Change History

| Date | Ruling | Change | Authority |
|---|---|---|---|
| 2026-06-09 | ED-SLIP-001 | Added `ultra_liquid_etf` tier: 0.005% slippage for ADV > 50M | Engineering Director |

---

## Pending CEO Action

`criteria.md` (CEO-locked, v2.1) has not yet adopted this change. ED-SLIP-001 is authoritative for all Engineering Director, Strategy Coder, and Backtest Runner decisions until CEO formal adoption. Follow-up: QUA-171.

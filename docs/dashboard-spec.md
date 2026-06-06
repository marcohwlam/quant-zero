# Quant Zero Dashboard — Specification v1.0

**Author:** Risk Director  
**Date:** 2026-06-06  
**Status:** LOCKED — canonical data formats. Engineering must implement without deviation.  
**Review:** CEO approval required before any format change.

---

## 1. Purpose

The Quant Zero Dashboard gives the CEO a single-pane-of-glass view of every promoted strategy's health. It surfaces the leaderboard, equity curves, staleness, and alert states. No live order routing. Read-only.

---

## 2. Dashboard Sections

### 2.1 Portfolio Summary Bar (top of page)

| Field | Source | Format |
|-------|--------|--------|
| Total capital | `promoted/registry.json → portfolio.total_capital` | `$XX,XXX` |
| Deployed capital | sum of `capital_allocated` for active strategies | `$XX,XXX (XX%)` |
| Cash buffer | total\_capital − deployed | `$XX,XXX (XX%)` |
| Portfolio drawdown | computed from master equity curve | `X.X%` |
| Alert state | derived from thresholds | `OK / WARN / HALT` |
| As-of timestamp | latest `meta.json → last_update` across all strategies | ISO 8601 UTC |

**Alert state rules:**
- `OK` — portfolio drawdown < 6%
- `WARN` — portfolio drawdown ≥ 6% (Rule 9 warn threshold)
- `HALT` — portfolio drawdown ≥ 8% (Rule 9 pause threshold — all live trading halts)

### 2.2 Promoted Strategy Leaderboard

One row per strategy in `promoted/registry.json` with status `paper` or `live`.

| Column | Source | Notes |
|--------|--------|-------|
| Strategy ID | `strat_id` | e.g. `h10_crypto_eql_reversal_v2` |
| Name | `name` | Human-readable |
| Status | `status` | `paper` / `live` / `retired` |
| Asset class | `asset_class` | `equities` / `crypto` / `futures` |
| Capital allocated | `capital_allocated` | dollars |
| IS Sharpe | `gate1.is_sharpe` | backtest IS |
| OOS Sharpe | `gate1.oos_sharpe` | backtest OOS |
| Paper Sharpe (live-computed) | from `paper_trading/<strat_id>/equity.csv` | rolling since paper start |
| Backtest MDD | `gate1.is_max_drawdown` | absolute value, % |
| Current drawdown | `paper_trading/<strat_id>/meta.json → current_drawdown` | % |
| Demotion threshold | `demotion_drawdown_threshold` | 1.5× backtest MDD |
| Alert | derived | see §2.4 |
| Last update | `paper_trading/<strat_id>/meta.json → last_update` | staleness indicator |
| Stale? | derived | see §2.3 |

Sort order: active first (paper → live), then retired. Within active: sort by alert severity DESC, then paper Sharpe DESC.

### 2.3 Equity Curve Panel

One chart per active strategy showing:
- Cumulative P&L curve from `paper_trading/<strat_id>/equity.csv`
- Backtest OOS equity curve overlay (if available in `gate1.oos_equity_csv`)
- Drawdown subplot below main equity chart
- Horizontal line at demotion threshold (1.5× backtest MDD)
- Horizontal line at warning threshold (1.0× backtest MDD)

X-axis: date. Y-axis: cumulative return %. Stale strategies shown with grey overlay and "STALE" badge.

### 2.4 Alert Thresholds

| Alert | Trigger condition | Severity | Action |
|-------|-------------------|----------|--------|
| Strategy stale | `last_update` older than staleness threshold (§3) | WARNING | Badge row yellow; surface in alert feed |
| Approaching demotion | `current_drawdown` ≥ 1.0× backtest MDD | WARNING | Badge row orange |
| Demotion threshold hit | `current_drawdown` ≥ 1.5× backtest MDD | CRITICAL | Badge row red; Portfolio Monitor alerts Risk Director |
| Portfolio warn | portfolio drawdown ≥ 6% | WARNING | Alert bar orange |
| Portfolio halt | portfolio drawdown ≥ 8% | CRITICAL | Alert bar red; all live strategies pause per Rule 9 |
| Paper vs backtest divergence | paper Sharpe < 0.7× OOS Sharpe | WARNING | Flag for Risk Director review |
| Vol ratio breach (Rule 11 proposed) | `realized_vol / target_vol` > 1.5 | WARNING | Portfolio Monitor reports; position size must decrease |

### 2.5 Trade Feed (bottom panel)

Last 50 trade records across all strategies from `paper_trading/<strat_id>/trades.csv`, merged and sorted by `timestamp` DESC.

Columns: timestamp, strategy, ticker, action, qty, price, notional, pnl.

---

## 3. Staleness Thresholds

A strategy is **stale** when `meta.json → last_update` is older than:

| Asset class | Staleness threshold | Rationale |
|-------------|---------------------|-----------|
| `crypto` | 2 hours | Crypto runners operate 24/7; silence > 2h implies failure |
| `equities` | 26 hours | US market days only; allows overnight gap without false alarm |
| `futures` | 4 hours | Session-based; silence within session indicates failure |

`last_update` is the UTC timestamp of the most recent successful runner execution that produced at least one signal evaluation, regardless of whether a trade was placed.

The dashboard build script must compute `is_stale = (now_utc - last_update) > threshold_hours` and surface it as a boolean field in the rendered output.

---

## 4. Data Formats (Canonical)

### 4.1 `promoted/registry.json`

Location: `promoted/registry.json` (repo root subfolder, version-controlled).

**Schema:**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12",
  "description": "Quant Zero promoted strategy registry. One record per Gate1-passing strategy.",
  "type": "object",
  "required": ["strategies", "portfolio", "schema_version"],
  "properties": {
    "schema_version": { "type": "string", "const": "1.0" },
    "portfolio": {
      "type": "object",
      "required": ["total_capital", "cash_buffer_minimum", "max_total_exposure", "max_strategy_concentration", "portfolio_drawdown_warn", "portfolio_drawdown_pause"],
      "properties": {
        "total_capital":              { "type": "number", "description": "Total capital in USD (e.g. 25000)" },
        "cash_buffer_minimum":        { "type": "number", "description": "Minimum cash fraction (0.20 = 20%)" },
        "max_total_exposure":         { "type": "number", "description": "Max portfolio exposure fraction (0.80)" },
        "max_strategy_concentration": { "type": "number", "description": "Max single-strategy allocation fraction (0.25)" },
        "portfolio_drawdown_warn":    { "type": "number", "description": "Warn threshold fraction (0.06)" },
        "portfolio_drawdown_pause":   { "type": "number", "description": "Halt threshold fraction (0.08)" }
      }
    },
    "strategies": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "strat_id", "name", "version", "status", "asset_class",
          "capital_allocated", "gate1", "demotion_drawdown_threshold",
          "warning_drawdown_threshold", "paper_start_date",
          "strategy_file", "paper_runner"
        ],
        "properties": {
          "strat_id": {
            "type": "string",
            "description": "Stable snake_case identifier. Used as paper_trading/<strat_id>/ folder name.",
            "pattern": "^[a-z0-9_]+$",
            "examples": ["h10_crypto_eql_reversal_v2", "bollinger_band_mean_reversion_v1"]
          },
          "name": { "type": "string", "description": "Human-readable name" },
          "version": { "type": "string", "description": "Semver string, e.g. 'v2.0'" },
          "status": {
            "type": "string",
            "enum": ["paper", "live", "retired"],
            "description": "Current deployment status"
          },
          "asset_class": {
            "type": "string",
            "enum": ["equities", "crypto", "futures"],
            "description": "Primary asset class"
          },
          "assets": {
            "type": "array",
            "items": { "type": "string" },
            "description": "List of tickers/symbols traded (e.g. ['BTC-USD', 'ETH-USD'])"
          },
          "capital_allocated": {
            "type": "number",
            "description": "USD amount currently allocated to this strategy"
          },
          "demotion_drawdown_threshold": {
            "type": "number",
            "description": "Max drawdown fraction that triggers demotion (1.5× backtest MDD). E.g. 0.18"
          },
          "warning_drawdown_threshold": {
            "type": "number",
            "description": "Drawdown fraction that triggers monitoring warning (1.0× backtest MDD). E.g. 0.12"
          },
          "paper_start_date": {
            "type": "string",
            "format": "date",
            "description": "ISO 8601 date when paper trading began (e.g. '2026-03-16')"
          },
          "live_start_date": {
            "type": ["string", "null"],
            "format": "date",
            "description": "ISO 8601 date when live trading began. Null if still in paper."
          },
          "gate1": {
            "type": "object",
            "required": [
              "approval_date", "approval_issue",
              "is_sharpe", "oos_sharpe",
              "is_max_drawdown", "oos_max_drawdown",
              "win_rate", "deflated_sharpe",
              "kelly_fraction", "kelly_position_cap_usd",
              "backtest_results_file", "verdict_file"
            ],
            "properties": {
              "approval_date":        { "type": "string", "format": "date" },
              "approval_issue":       { "type": "string", "description": "Paperclip issue identifier, e.g. 'QUA-152'" },
              "is_period":            { "type": "string", "description": "In-sample period, e.g. '2018-01-01 to 2022-12-31'" },
              "oos_period":           { "type": "string", "description": "Out-of-sample period" },
              "is_sharpe":            { "type": "number" },
              "oos_sharpe":           { "type": "number" },
              "is_max_drawdown":      { "type": "number", "description": "Positive fraction, e.g. 0.107 means 10.7% MDD" },
              "oos_max_drawdown":     { "type": "number" },
              "win_rate":             { "type": "number", "description": "Fraction, e.g. 0.614" },
              "deflated_sharpe":      { "type": "number", "description": "Deflated Sharpe Ratio (must be > 0)" },
              "kelly_fraction":       { "type": "number", "description": "f* = mu/sigma^2 from IS metrics" },
              "kelly_position_cap_usd": { "type": "number", "description": "25% Kelly × total_capital at time of approval" },
              "look_ahead_certified": { "type": "boolean", "description": "True = no look-ahead bias detected" },
              "backtest_results_file":{ "type": "string", "description": "Repo-relative path to .json results" },
              "verdict_file":         { "type": "string", "description": "Repo-relative path to verdict .txt or .md" },
              "oos_equity_csv":       { "type": ["string","null"], "description": "Repo-relative path to OOS equity CSV for overlay chart (optional)" }
            }
          },
          "ceo_paper_approval_issue": {
            "type": ["string", "null"],
            "description": "Paperclip issue where CEO approved paper trading start"
          },
          "ceo_live_approval_issue": {
            "type": ["string", "null"],
            "description": "Paperclip issue where CEO approved live trading start"
          },
          "strategy_file": {
            "type": "string",
            "description": "Repo-relative path to strategy Python file"
          },
          "paper_runner": {
            "type": "string",
            "description": "Repo-relative path to paper trading runner script"
          },
          "notes": {
            "type": ["string", "null"],
            "description": "Free-text notes about constraints, exceptions, or CEO decisions"
          },
          "retired_date": {
            "type": ["string", "null"],
            "format": "date",
            "description": "ISO 8601 date when strategy was retired. Null if active."
          },
          "retired_reason": {
            "type": ["string", "null"],
            "description": "Why retired (e.g. 'demotion threshold hit', 'CEO decision')"
          }
        }
      }
    }
  }
}
```

**Constraints:**
- `strat_id` must be unique across all entries.
- `strat_id` must match the folder name in `paper_trading/<strat_id>/`.
- `capital_allocated` for all active strategies must not exceed `portfolio.max_total_exposure × portfolio.total_capital`.
- Any single strategy's `capital_allocated` must not exceed `portfolio.max_strategy_concentration × portfolio.total_capital` (Rule 2).
- `demotion_drawdown_threshold` = 1.5 × `gate1.is_max_drawdown`. Engineering must validate this on write.
- `warning_drawdown_threshold` = 1.0 × `gate1.is_max_drawdown`.
- Retired strategies remain in the registry with `status: "retired"` — never delete entries.

**Example entry (abridged):**

```json
{
  "strat_id": "h10_crypto_eql_reversal_v2",
  "name": "H10 Crypto EQL/EQH Reversal",
  "version": "v2.0",
  "status": "paper",
  "asset_class": "crypto",
  "assets": ["BTC-USD", "ETH-USD"],
  "capital_allocated": 5000,
  "demotion_drawdown_threshold": 0.161,
  "warning_drawdown_threshold": 0.107,
  "paper_start_date": "2026-03-16",
  "live_start_date": null,
  "gate1": {
    "approval_date": "2026-03-16",
    "approval_issue": "QUA-152",
    "is_period": "2018-01-01 to 2022-12-31",
    "oos_period": "2023-01-01 to 2023-12-31",
    "is_sharpe": 1.20,
    "oos_sharpe": 1.44,
    "is_max_drawdown": 0.107,
    "oos_max_drawdown": 0.095,
    "win_rate": 0.614,
    "deflated_sharpe": 0.82,
    "kelly_fraction": 0.41,
    "kelly_position_cap_usd": 2562,
    "look_ahead_certified": true,
    "backtest_results_file": "backtests/H10_CryptoEQLReversal_v2_2026-03-16.json",
    "verdict_file": "backtests/H10_CryptoEQLReversal_v2_2026-03-16_verdict.txt",
    "oos_equity_csv": null
  },
  "ceo_paper_approval_issue": "QUA-160",
  "ceo_live_approval_issue": null,
  "strategy_file": "strategies/h10_crypto_eql_reversal.py",
  "paper_runner": "broker/paper_trading/h10_paper_runner.py",
  "notes": "Long-only EQL zones (BTC/ETH). Short leg not approved."
}
```

---

### 4.2 `paper_trading/<strat_id>/` Directory Format

Each promoted strategy gets a dedicated subfolder: `paper_trading/<strat_id>/`

The `<strat_id>` must exactly match `strat_id` in `promoted/registry.json`.

Three files are required:

#### 4.2.1 `equity.csv`

One row per trading session (daily for equities/futures) or per UTC calendar day (crypto). The paper runner appends one row per run. The dashboard build script reads this file to compute the equity curve.

**Columns (required, in order):**

| Column | Type | Description |
|--------|------|-------------|
| `date` | `YYYY-MM-DD` | Calendar date (UTC for crypto, exchange date for equities) |
| `portfolio_value` | float | Total strategy portfolio value in USD at end of day |
| `cash` | float | Uninvested cash held by this strategy in USD |
| `invested` | float | Current notional in open positions in USD |
| `daily_pnl` | float | P&L for this date in USD (positive = gain) |
| `cumulative_pnl` | float | Total P&L since paper start in USD |
| `cumulative_return_pct` | float | `(portfolio_value / initial_capital - 1) × 100` |
| `drawdown_pct` | float | Current drawdown from peak in % (always ≥ 0; e.g. `5.2` means 5.2%) |
| `peak_value` | float | Running maximum of `portfolio_value` since paper start |
| `trade_count_today` | int | Number of fills executed today (0 if no trades) |
| `signal_count_today` | int | Number of signal evaluations today |

**Constraints:**
- First row: `portfolio_value` = `capital_allocated`, `cumulative_pnl` = 0, `drawdown_pct` = 0.
- `portfolio_value` = `cash` + `invested` (must hold within $0.01 floating point tolerance).
- `drawdown_pct` = `(1 - portfolio_value / peak_value) × 100` when `portfolio_value < peak_value`, else 0.
- File is append-only. One row per day. Dedup on `date` if runner fires multiple times in one day — latest value wins.
- No header changes across versions. Add new columns only by appending to the right (old readers skip unknowns).

**Example:**
```
date,portfolio_value,cash,invested,daily_pnl,cumulative_pnl,cumulative_return_pct,drawdown_pct,peak_value,trade_count_today,signal_count_today
2026-03-16,5000.00,5000.00,0.00,0.00,0.00,0.00,0.00,5000.00,0,2
2026-03-17,5032.50,2532.50,2500.00,32.50,32.50,0.65,0.00,5032.50,1,4
2026-03-18,4990.00,2490.00,2500.00,-42.50,-10.00,-0.20,0.84,5032.50,0,4
```

#### 4.2.2 `trades.csv`

One row per trade fill. The paper runner appends one row per executed fill. Rows are ordered by `timestamp` ascending.

**Columns (required, in order):**

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | `YYYY-MM-DD HH:MM:SS` UTC | When the fill occurred |
| `ticker` | string | Symbol traded (e.g. `BTC-USD`, `SPY`) |
| `action` | string | `buy` / `sell` / `flat` |
| `qty` | float | Units filled (shares, coins, contracts) |
| `price` | float | Fill price per unit in USD |
| `notional` | float | `qty × price` in USD |
| `commission` | float | Estimated commission in USD (0 if not applicable) |
| `slippage_est` | float | Estimated slippage cost in USD (0 if unknown) |
| `signal` | string | Signal that triggered trade (strategy-defined string, e.g. `eql_long`, `momentum_buy`) |
| `order_id` | string | Broker order ID or `dry_run` if no live order |
| `dry_run` | bool | `true` if no real fill was sent to broker |
| `pnl_realized` | float | Realized P&L from this fill closing a position (0 if opening) |
| `position_after` | float | Net position in this ticker after fill (signed; negative = short) |

**Constraints:**
- File is append-only. Never rewrite historical rows.
- `dry_run=true` rows are included — the dashboard distinguishes them visually.
- `notional` for `flat` / zero-size actions = 0.
- `commission` and `slippage_est` are best-effort estimates; use 0 when unavailable.

**Example:**
```
timestamp,ticker,action,qty,price,notional,commission,slippage_est,signal,order_id,dry_run,pnl_realized,position_after
2026-03-17 09:31:00,QQQ,buy,12.5,200.10,2501.25,0.00,1.25,momentum_buy,dry_run,true,0.00,12.5
2026-03-19 15:58:00,QQQ,sell,12.5,203.50,2543.75,0.00,1.28,momentum_exit,dry_run,true,41.22,0.0
```

#### 4.2.3 `meta.json`

Written (overwritten) by the paper runner on every successful execution. The dashboard reads this for staleness and current health state.

**Schema:**

```json
{
  "strat_id": "h10_crypto_eql_reversal_v2",
  "last_update": "2026-06-06T14:32:10Z",
  "runner_version": "1.0.0",
  "paper_start_date": "2026-03-16",
  "initial_capital": 5000.00,
  "current_portfolio_value": 5214.37,
  "current_cash": 2714.37,
  "current_invested": 2500.00,
  "cumulative_pnl": 214.37,
  "cumulative_return_pct": 4.29,
  "current_drawdown_pct": 0.00,
  "peak_value": 5214.37,
  "max_drawdown_since_paper_start_pct": 2.14,
  "demotion_threshold_pct": 16.05,
  "warning_threshold_pct": 10.70,
  "total_trades": 18,
  "total_signal_evaluations": 142,
  "days_in_paper": 82,
  "rolling_sharpe_30d": 1.31,
  "rolling_sharpe_since_start": 1.18,
  "status": "ok",
  "alert": null,
  "open_positions": [
    {
      "ticker": "BTC-USD",
      "qty": 0.038,
      "avg_entry_price": 65780.00,
      "current_price": 65900.00,
      "unrealized_pnl": 4.56,
      "position_value": 2504.22
    }
  ],
  "last_signal_evaluation": {
    "timestamp": "2026-06-06T14:32:10Z",
    "signals": { "BTC-USD": "flat", "ETH-USD": "flat" }
  }
}
```

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `strat_id` | string | Must match registry |
| `last_update` | ISO 8601 UTC | Timestamp of this runner execution |
| `runner_version` | string | Semver of the paper runner script |
| `paper_start_date` | `YYYY-MM-DD` | When paper trading began |
| `initial_capital` | float | Capital allocated at paper start |
| `current_portfolio_value` | float | Current total strategy value |
| `current_cash` | float | Uninvested cash |
| `current_invested` | float | Notional in open positions |
| `cumulative_pnl` | float | Total P&L since paper start |
| `cumulative_return_pct` | float | Return since paper start |
| `current_drawdown_pct` | float | Current drawdown from peak (≥ 0) |
| `peak_value` | float | Running maximum portfolio value |
| `max_drawdown_since_paper_start_pct` | float | Worst drawdown ever observed since paper start |
| `demotion_threshold_pct` | float | Drawdown % at which demotion triggers (= 1.5× backtest MDD × 100) |
| `warning_threshold_pct` | float | Drawdown % at which warning triggers |
| `total_trades` | int | Cumulative fill count |
| `total_signal_evaluations` | int | Cumulative signal evaluation count |
| `days_in_paper` | int | Calendar days since paper_start_date |
| `rolling_sharpe_30d` | float or null | 30-day rolling Sharpe (null if < 30 days in paper) |
| `rolling_sharpe_since_start` | float or null | Sharpe since paper start (null if < 20 days) |
| `status` | string | `ok` / `warn` / `demotion_alert` / `stale` / `error` |
| `alert` | string or null | Human-readable alert message, null when status = ok |
| `open_positions` | array | Current open positions (see sub-schema above) |
| `last_signal_evaluation` | object or null | Latest signal output |

**`status` derivation (runner sets this):**

```
if current_drawdown_pct >= demotion_threshold_pct:  "demotion_alert"
elif current_drawdown_pct >= warning_threshold_pct:  "warn"
elif (now - last_update) > staleness_threshold:      "stale"   # set by dashboard, not runner
else:                                                 "ok"
```

The runner sets `stale` only on restart-after-long-gap detection. The dashboard build script always recomputes staleness independently using the threshold table in §3.

---

## 5. Build Script Contract (`scripts/build_dashboard.py`)

The dashboard build script reads the canonical formats above and produces output for the UI. This section defines what Engineering must build.

### Inputs

- `promoted/registry.json` — strategy registry
- `paper_trading/<strat_id>/equity.csv` — equity history per strategy
- `paper_trading/<strat_id>/trades.csv` — trade history per strategy
- `paper_trading/<strat_id>/meta.json` — live state per strategy

### Outputs

```
docs/dashboard/
  index.html          # rendered dashboard (standalone, no server required)
  data/
    portfolio.json    # portfolio summary (§2.1 fields)
    leaderboard.json  # leaderboard rows (§2.2 fields)
    equity/<strat_id>.json   # equity curve data for chart rendering
    alerts.json       # all active alerts
```

### Staleness computation

```python
from datetime import datetime, timezone, timedelta

STALENESS_HOURS = {
    "crypto":   2,
    "equities": 26,
    "futures":  4,
}

def is_stale(meta: dict, asset_class: str, now_utc: datetime) -> bool:
    last_update = datetime.fromisoformat(meta["last_update"].replace("Z", "+00:00"))
    threshold = timedelta(hours=STALENESS_HOURS[asset_class])
    return (now_utc - last_update) > threshold
```

### Demotion threshold validation

On every build, the script must verify:
```
abs(registry_entry.demotion_drawdown_threshold - 1.5 * registry_entry.gate1.is_max_drawdown) < 0.001
```
Log a warning (not error) if mismatch — drift may be intentional CEO override.

### Paper Sharpe computation

```python
import numpy as np, pandas as pd

def rolling_sharpe(equity_csv_path: str, window_days: int = None) -> float | None:
    df = pd.read_csv(equity_csv_path, parse_dates=["date"])
    df = df.sort_values("date")
    returns = df["daily_pnl"] / df["portfolio_value"].shift(1)
    if window_days:
        returns = returns.tail(window_days)
    if len(returns.dropna()) < 20:
        return None
    return float(returns.mean() / returns.std() * np.sqrt(252))
```

### Update frequency

The build script runs on-demand (triggered by CEO or Portfolio Monitor) and may be scheduled (e.g. after each paper runner execution). It does not run continuously. Target build time: < 10 seconds for ≤ 10 strategies.

---

## 6. Directory Layout

```
quant-zero/
  promoted/
    registry.json                   # canonical strategy registry (this spec §4.1)
  paper_trading/
    h10_crypto_eql_reversal_v2/
      equity.csv                    # §4.2.1
      trades.csv                    # §4.2.2
      meta.json                     # §4.2.3
    bollinger_band_mean_reversion_v1/
      equity.csv
      trades.csv
      meta.json
    ...
  scripts/
    build_dashboard.py              # §5
  docs/
    dashboard/
      index.html                    # generated output (gitignored or committed)
      data/
        portfolio.json
        leaderboard.json
        equity/
          h10_crypto_eql_reversal_v2.json
        alerts.json
    dashboard-spec.md               # this file
```

**Note:** The current `broker/strategy_registry.json` and `broker/paper_trading/*.json` are the legacy format. Engineering must migrate them to this canonical layout when implementing `build_dashboard.py`. The legacy files remain until migration is verified.

---

## 7. Migration Notes (legacy → canonical)

| Legacy path | Canonical path | Action |
|-------------|----------------|--------|
| `broker/strategy_registry.json` | `promoted/registry.json` | Engineering migrates; adds missing `strat_id`, `gate1.*` sub-object, `schema_version` |
| `broker/paper_trading/h10_trade_log.json` | `paper_trading/h10_crypto_eql_reversal_v2/trades.csv` | Engineering converts JSON array → CSV; maps fields per §4.2.2 |
| `broker/paper_trading/testmomentum_trade_log.json` | `paper_trading/bollinger_band_mean_reversion_v1/trades.csv` | Same conversion |
| Existing paper runners | Update to write equity.csv + meta.json | Engineering updates runners to emit canonical files |

`strat_id` assignments for existing strategies:
- H10 → `h10_crypto_eql_reversal_v2`
- TestMomentum (BollingerBand) → `bollinger_band_mean_reversion_v1`

---

## 8. Governance

- This spec is authored by the Risk Director and requires CEO review before Engineering implementation begins.
- Format changes require a versioned update to this document (increment version in title) and CEO approval.
- `promoted/registry.json` is version-controlled and treated as a source-of-truth artifact — no agent may modify it without an explicit CEO-approved workflow.
- Engineering Director implements; Risk Director reviews the PR before merge.

---

*End of Quant Zero Dashboard Specification v1.0*

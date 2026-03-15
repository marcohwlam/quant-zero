# Knowledge Base

This directory contains the firm's accumulated strategy knowledge. Each file documents a strategy pattern with a standardized schema that agents can read, reference, and build upon during the research-evaluate-learn cycle.

## Schema

Every strategy entry follows this structure:

| Field | Type | Description |
|-------|------|-------------|
| `strategy_name` | string | snake_case identifier |
| `category` | string | `momentum`, `mean_reversion`, `factor`, `statistical_arbitrage`, `volatility`, `trend_following` |
| `source` | string | `quantopian_lectures`, `quantopian_contest`, `academic_paper`, `iteration_N`, `manual` |
| `hypothesis` | string | Falsifiable statement of WHY this strategy generates alpha |
| `market_regime` | string | `trending`, `mean-reverting`, `high-vol`, `low-vol`, `all` |
| `asset_class` | string | `equities`, `etfs`, `futures`, `options`, `crypto` |
| `universe` | string | Asset universe description |
| `entry_logic` | string | Entry signal conditions |
| `exit_logic` | string | Exit conditions (profit target, stop loss, time) |
| `position_sizing` | string | Sizing methodology |
| `risk_management` | string | Stop losses, max position, sector limits |
| `parameters` | object | Named params with `value`, `range`, and `sensitivity` |
| `num_parameters` | int | Count of free parameters (fewer = less overfitting risk) |
| `known_failure_modes` | array | Documented conditions where the strategy breaks |
| `historical_performance` | object | `sharpe`, `max_drawdown`, `period`, `notes` |
| `references` | array | Source citations |
| `related_strategies` | array | Names of related KB entries |

## Directory Structure

```
knowledge_base/
├── README.md                          # This file
├── <strategy_name>.json               # Seed and iteration strategies
└── learnings/                         # Post-backtest learnings (auto-generated)
    └── <date>_<strategy_name>_learnings.md
```

## Current Entries (Seed Strategies)

| File | Category | Sharpe (IS) | Regime |
|------|----------|-------------|--------|
| `dual_moving_average_crossover.json` | trend_following | 0.6 | trending |
| `bollinger_band_mean_reversion.json` | mean_reversion | 1.1 | mean-reverting |
| `multi_factor_long_short.json` | factor | 1.8 | all |
| `pairs_trading_cointegration.json` | statistical_arbitrage | 1.3 | mean-reverting |
| `momentum_vol_scaled.json` | momentum | 1.4 | trending |
| `rsi_short_term_reversal.json` | mean_reversion | 1.2 | mean-reverting |

## Maintenance Rules

1. **Never delete failed strategies** — they contain negative knowledge that prevents repeating mistakes.
2. **Tag all entries with source** — distinguish between seeded patterns and iteration-generated learnings.
3. **Update `historical_performance`** if you re-run a strategy on new data.
4. **Link `related_strategies`** — helps agents find connections between approaches.
5. **Review quarterly** — mark strategies as `"deprecated"` in a `status` field if the market regime has changed fundamentally.
6. **Learnings go in `learnings/`** — format: `YYYY-MM-DD_<strategy_name>_learnings.md`.

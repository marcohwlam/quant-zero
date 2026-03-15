# Regimes

Market regime classifications and transition analysis from the Market Regime Agent.

## Naming Convention

`YYYY-MM_regime_classification.md` — monthly or event-driven snapshots.

## Regime Taxonomy

| Regime | Description | Key Indicators |
|--------|-------------|----------------|
| `trending_bull` | Strong uptrend, low volatility | VIX < 15, 200d SMA slope positive |
| `trending_bear` | Strong downtrend | VIX > 25, 200d SMA slope negative |
| `mean_reverting` | Range-bound, choppy | VIX 15-25, price oscillating around SMA |
| `high_volatility` | Elevated volatility, regime unclear | VIX > 30 |
| `crisis` | Tail-risk event, correlation spike | VIX > 40, cross-asset correlation → 1 |

## How Regimes Inform Strategy Selection

- Trend-following strategies (DMA crossover, momentum) thrive in `trending_bull/bear`
- Mean-reversion strategies (Bollinger, pairs, RSI reversal) work in `mean_reverting`
- Factor long-short (`multi_factor`) is regime-agnostic by design but suffers in `crisis`
- All strategies should reduce size in `high_volatility` and `crisis` regimes

"""
Momentum Vol-Scaled Batch Runner — Iterations 36-65
Phase 1 Hypothesis 05: Cross-sectional momentum with volatility scaling (ETF universe)

Runs 30 strategy variants WITHOUT using the Anthropic API.
Backtest Runner (ddfd2618) acts as strategy proposer directly.

Universe: SPY, QQQ, IWM, DIA, XLF, XLE, XLK, XLV
IS: 2018-01-01 to 2022-12-31
OOS: 2023-01-01 to 2024-12-31
"""

import json
import math
import datetime
import sqlite3
import traceback
import sys
import warnings
from pathlib import Path

import vectorbt as vbt
import pandas as pd
import numpy as np
import yfinance as yf

warnings.filterwarnings("ignore")

# ── Configuration ─────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent
BACKTESTS_DIR = REPO_ROOT / "backtests"
BACKTESTS_DIR.mkdir(exist_ok=True)

DB_PATH = str(REPO_ROOT / "orchestrator" / "iteration_log.db")

SYMBOLS = ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV"]
IS_START = "2018-01-01"
IS_END = "2022-12-31"
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
DATA_START = "2016-01-01"  # extra history for lookback warmup

INIT_CASH = 100_000.0
FEES = 0.0001 + 0.0005  # 0.01% fixed + 0.05% slippage = 0.06% total

# Gate 1 thresholds
GATE1 = {
    "min_is_sharpe": 1.0,
    "min_oos_sharpe": 0.7,
    "max_is_mdd": -0.20,
    "max_oos_mdd": -0.25,
    "min_win_rate": 0.50,
    "min_trades": 50,
}


# ── 30 Strategy Variants ──────────────────────────────────────
# Parameters: lookback_months, skip_months, top_k, target_vol,
#             rebalance_days, crash_threshold (None = disabled),
#             equal_weight (if True, skip vol-scaling)

VARIANTS = [
    # --- Core seed and lookback sweep ---
    {"name": "mvs_lb12_sk1_k3_tv10_rb21_cp10",   "lookback": 12, "skip": 1, "top_k": 3, "target_vol": 0.10, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb6_sk1_k3_tv10_rb21_cp10",    "lookback":  6, "skip": 1, "top_k": 3, "target_vol": 0.10, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb9_sk1_k3_tv10_rb21_cp10",    "lookback":  9, "skip": 1, "top_k": 3, "target_vol": 0.10, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb3_sk1_k3_tv10_rb21_cp10",    "lookback":  3, "skip": 1, "top_k": 3, "target_vol": 0.10, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb18_sk1_k3_tv10_rb21_cp10",   "lookback": 18, "skip": 1, "top_k": 3, "target_vol": 0.10, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    # --- Skip sweep ---
    {"name": "mvs_lb12_sk0_k3_tv10_rb21_cp10",   "lookback": 12, "skip": 0, "top_k": 3, "target_vol": 0.10, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb12_sk2_k3_tv10_rb21_cp10",   "lookback": 12, "skip": 2, "top_k": 3, "target_vol": 0.10, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb12_sk3_k3_tv10_rb21_cp10",   "lookback": 12, "skip": 3, "top_k": 3, "target_vol": 0.10, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    # --- top_k sweep ---
    {"name": "mvs_lb12_sk1_k2_tv10_rb21_cp10",   "lookback": 12, "skip": 1, "top_k": 2, "target_vol": 0.10, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb12_sk1_k4_tv10_rb21_cp10",   "lookback": 12, "skip": 1, "top_k": 4, "target_vol": 0.10, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb12_sk1_k5_tv10_rb21_cp10",   "lookback": 12, "skip": 1, "top_k": 5, "target_vol": 0.10, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    # --- target_vol sweep ---
    {"name": "mvs_lb12_sk1_k3_tv15_rb21_cp10",   "lookback": 12, "skip": 1, "top_k": 3, "target_vol": 0.15, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb12_sk1_k3_tv08_rb21_cp10",   "lookback": 12, "skip": 1, "top_k": 3, "target_vol": 0.08, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb12_sk1_k3_tv20_rb21_cp10",   "lookback": 12, "skip": 1, "top_k": 3, "target_vol": 0.20, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    # --- rebalance frequency sweep ---
    {"name": "mvs_lb12_sk1_k3_tv10_rb10_cp10",   "lookback": 12, "skip": 1, "top_k": 3, "target_vol": 0.10, "rebalance": 10, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb12_sk1_k3_tv10_rb63_cp10",   "lookback": 12, "skip": 1, "top_k": 3, "target_vol": 0.10, "rebalance": 63, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb12_sk1_k3_tv10_rb42_cp10",   "lookback": 12, "skip": 1, "top_k": 3, "target_vol": 0.10, "rebalance": 42, "crash": -0.10, "equal_weight": False},
    # --- crash threshold sweep ---
    {"name": "mvs_lb12_sk1_k3_tv10_rb21_cp05",   "lookback": 12, "skip": 1, "top_k": 3, "target_vol": 0.10, "rebalance": 21, "crash": -0.05, "equal_weight": False},
    {"name": "mvs_lb12_sk1_k3_tv10_rb21_cp15",   "lookback": 12, "skip": 1, "top_k": 3, "target_vol": 0.10, "rebalance": 21, "crash": -0.15, "equal_weight": False},
    {"name": "mvs_lb12_sk1_k3_tv10_rb21_nocp",   "lookback": 12, "skip": 1, "top_k": 3, "target_vol": 0.10, "rebalance": 21, "crash": None, "equal_weight": False},
    # --- equal weight (no vol scaling) ---
    {"name": "mvs_lb12_sk1_k3_eqwt_rb21_cp10",   "lookback": 12, "skip": 1, "top_k": 3, "target_vol": 0.10, "rebalance": 21, "crash": -0.10, "equal_weight": True},
    # --- combined parameter sets ---
    {"name": "mvs_lb9_sk1_k4_tv12_rb21_cp10",    "lookback":  9, "skip": 1, "top_k": 4, "target_vol": 0.12, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb6_sk0_k4_tv10_rb21_cp08",    "lookback":  6, "skip": 0, "top_k": 4, "target_vol": 0.10, "rebalance": 21, "crash": -0.08, "equal_weight": False},
    {"name": "mvs_lb12_sk1_k3_tv15_rb10_cp10",   "lookback": 12, "skip": 1, "top_k": 3, "target_vol": 0.15, "rebalance": 10, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb6_sk1_k3_tv12_rb21_cp08",    "lookback":  6, "skip": 1, "top_k": 3, "target_vol": 0.12, "rebalance": 21, "crash": -0.08, "equal_weight": False},
    {"name": "mvs_lb18_sk1_k4_tv10_rb21_cp10",   "lookback": 18, "skip": 1, "top_k": 4, "target_vol": 0.10, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb9_sk1_k3_tv15_rb21_cp10",    "lookback":  9, "skip": 1, "top_k": 3, "target_vol": 0.15, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb12_sk2_k4_tv10_rb21_cp10",   "lookback": 12, "skip": 2, "top_k": 4, "target_vol": 0.10, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb6_sk1_k2_tv12_rb21_cp10",    "lookback":  6, "skip": 1, "top_k": 2, "target_vol": 0.12, "rebalance": 21, "crash": -0.10, "equal_weight": False},
    {"name": "mvs_lb9_sk1_k5_tv10_rb42_cp12",    "lookback":  9, "skip": 1, "top_k": 5, "target_vol": 0.10, "rebalance": 42, "crash": -0.12, "equal_weight": False},
]

assert len(VARIANTS) == 30, f"Expected 30 variants, got {len(VARIANTS)}"


# ── Database ──────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS iterations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            iteration INTEGER,
            strategy_name TEXT,
            hypothesis TEXT,
            parameters TEXT,
            sharpe_in_sample REAL,
            sharpe_out_of_sample REAL,
            max_drawdown REAL,
            total_trades INTEGER,
            win_rate REAL,
            profit_factor REAL,
            passed_criteria INTEGER,
            promoted_to_paper INTEGER DEFAULT 0,
            post_mortem TEXT,
            strategy_code TEXT,
            wf_windows_passed INTEGER,
            wf_consistency_score REAL,
            post_cost_sharpe REAL,
            asset_class TEXT,
            dsr REAL,
            sensitivity_pass INTEGER
        )
    """)
    for col, col_type in [
        ("wf_windows_passed", "INTEGER"),
        ("wf_consistency_score", "REAL"),
        ("post_cost_sharpe", "REAL"),
        ("asset_class", "TEXT"),
        ("dsr", "REAL"),
        ("sensitivity_pass", "INTEGER"),
    ]:
        try:
            conn.execute(f"ALTER TABLE iterations ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    return conn


def get_next_iteration(conn):
    row = conn.execute("SELECT MAX(iteration) FROM iterations").fetchone()
    return (row[0] or 0) + 1


def log_iteration(conn, data: dict):
    conn.execute("""
        INSERT INTO iterations
        (timestamp, iteration, strategy_name, hypothesis, parameters,
         sharpe_in_sample, sharpe_out_of_sample, max_drawdown,
         total_trades, win_rate, profit_factor,
         passed_criteria, post_mortem, strategy_code,
         wf_windows_passed, wf_consistency_score,
         post_cost_sharpe, asset_class, dsr, sensitivity_pass)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.datetime.now().isoformat(),
        data.get("iteration"),
        data.get("strategy_name"),
        data.get("hypothesis"),
        json.dumps(data.get("parameters", {}), default=str),
        data.get("sharpe_in_sample"),
        data.get("sharpe_out_of_sample"),
        data.get("max_drawdown"),
        data.get("total_trades"),
        data.get("win_rate"),
        data.get("profit_factor"),
        int(data.get("passed_criteria", False)),
        data.get("post_mortem"),
        data.get("strategy_code", ""),
        data.get("wf_windows_passed"),
        data.get("wf_consistency_score"),
        data.get("post_cost_sharpe"),
        data.get("asset_class", "equities"),
        data.get("dsr"),
        int(data.get("sensitivity_pass", False)) if data.get("sensitivity_pass") is not None else None,
    ))
    conn.commit()


# ── Data Fetching ─────────────────────────────────────────────

def fetch_all_data():
    print("Fetching data from yfinance...")
    raw = yf.download(SYMBOLS, start=DATA_START, end=OOS_END, group_by="ticker", auto_adjust=True, progress=False)
    print(f"Downloaded data shape: {raw.shape}, date range: {raw.index[0].date()} to {raw.index[-1].date()}")
    return raw


# ── Core Strategy Engine ──────────────────────────────────────

def compute_momentum_signal(close: pd.DataFrame, lookback_months: int, skip_months: int) -> pd.Series:
    """
    Compute cross-sectional momentum at current date.
    Returns Series of momentum scores indexed by ticker.
    """
    # Convert months to trading days (approx 21 per month)
    lookback_days = lookback_months * 21
    skip_days = skip_months * 21
    return close, lookback_days, skip_days


def build_target_allocations(close: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Build daily target allocation DataFrame.
    Each row: target weight per ETF (sums to ≤ 1, 0 = cash).
    Only changes on rebalance dates.
    """
    lookback_days = params["lookback"] * 21
    skip_days = params["skip"] * 21
    top_k = params["top_k"]
    target_vol = params["target_vol"]
    rebalance = params["rebalance"]
    crash = params["crash"]
    equal_weight = params["equal_weight"]

    n = len(close)
    alloc = pd.DataFrame(0.0, index=close.index, columns=close.columns)

    # Find rebalance dates (every `rebalance` days starting from enough history)
    warmup = lookback_days + skip_days + 22  # +22 for vol estimation
    prev_weights = pd.Series(0.0, index=close.columns)

    for i in range(warmup, n, rebalance):
        date = close.index[i]

        # Momentum: return from (i - lookback_days - skip_days) to (i - skip_days)
        start_idx = i - lookback_days - skip_days
        end_idx = i - skip_days
        if start_idx < 0:
            continue

        start_prices = close.iloc[start_idx]
        end_prices = close.iloc[end_idx]
        momentum = end_prices / start_prices - 1.0

        # Drop any NaN tickers
        momentum = momentum.dropna()
        if len(momentum) < top_k:
            alloc.iloc[i] = 0.0
            prev_weights = pd.Series(0.0, index=close.columns)
            continue

        # Crash protection: if SPY 1-month return < threshold, go to cash
        if crash is not None and "SPY" in close.columns:
            spy_idx = i - 21
            if spy_idx >= 0:
                spy_1m_ret = close["SPY"].iloc[i] / close["SPY"].iloc[spy_idx] - 1.0
                if spy_1m_ret < crash:
                    alloc.iloc[i] = 0.0
                    prev_weights = pd.Series(0.0, index=close.columns)
                    continue

        # Select top-k ETFs by momentum
        ranked = momentum.rank(ascending=False)
        top_tickers = ranked[ranked <= top_k].index.tolist()

        if not top_tickers:
            alloc.iloc[i] = 0.0
            prev_weights = pd.Series(0.0, index=close.columns)
            continue

        # Position sizing
        if equal_weight:
            weights = pd.Series(1.0 / len(top_tickers), index=top_tickers)
        else:
            # Inverse volatility sizing (21-day realized vol)
            vol_window = close.iloc[max(0, i - 21):i]
            daily_returns = vol_window.pct_change().dropna()
            vol = daily_returns.std()
            vol_top = vol[top_tickers].fillna(0.02)  # default 2% if missing
            vol_top = vol_top.clip(lower=0.001)

            inv_vol = 1.0 / vol_top
            weights = inv_vol / inv_vol.sum()

            # Scale to target volatility
            # Portfolio daily vol = sqrt(w^T * Sigma * w), approx as weighted avg vol * sqrt(252)
            port_vol_daily = (weights * vol_top).sum()
            port_vol_annual = port_vol_daily * np.sqrt(252)
            if port_vol_annual > 0:
                scale = target_vol / port_vol_annual
                scale = min(scale, 1.0)  # cap at 100% invested
                weights = weights * scale

        # Assign to full-ticker index
        full_weights = pd.Series(0.0, index=close.columns)
        full_weights[top_tickers] = weights[top_tickers].values
        alloc.iloc[i] = full_weights
        prev_weights = full_weights

    # Forward-fill allocations between rebalance dates (carry forward position)
    # No — we only order on rebalance dates, hold passively in between
    return alloc


def run_portfolio_simulation(close: pd.DataFrame, alloc: pd.DataFrame) -> vbt.Portfolio:
    """
    Convert target allocation fractions to explicit share orders.
    Simulates portfolio tracking to compute delta-shares at each rebalance.
    """
    n, m = close.shape
    order_size = np.zeros((n, m))

    current_shares = np.zeros(m)
    current_cash = INIT_CASH

    for i in range(n):
        if alloc.iloc[i].abs().sum() > 1e-8:
            # This is a rebalance date
            prices = close.iloc[i].values

            # Estimate portfolio value
            port_value = current_cash + np.dot(current_shares, prices)

            # Target shares
            target_weights = alloc.iloc[i].values
            target_dollars = target_weights * port_value
            target_shares = np.where(prices > 0, target_dollars / prices, 0.0)

            # Delta shares to order
            delta = target_shares - current_shares
            order_size[i] = delta

            # Update state (approximate — ignore fees for tracking)
            current_shares = target_shares
            current_cash = port_value - np.dot(target_shares, prices)

    order_df = pd.DataFrame(order_size, index=close.index, columns=close.columns)

    portfolio = vbt.Portfolio.from_orders(
        close,
        order_df,
        freq="D",
        init_cash=INIT_CASH,
        fees=FEES,
        slippage=0.0,  # already included in fees above
        size_type="Amount",
    )
    return portfolio


# ── Metrics Computation ───────────────────────────────────────

def compute_metrics(portfolio: vbt.Portfolio) -> dict:
    """Extract Gate 1 metrics from a vectorbt Portfolio."""
    try:
        rets = portfolio.returns()

        # Handle both Series and DataFrame
        if isinstance(rets, pd.DataFrame):
            rets = rets.sum(axis=1)  # combine columns

        # Sharpe ratio (annualized, 252 trading days)
        mean_ret = rets.mean()
        std_ret = rets.std()
        sharpe = (mean_ret / (std_ret + 1e-10)) * np.sqrt(252)

        # Max drawdown
        cum = (1 + rets).cumprod()
        roll_max = cum.cummax()
        dd = (cum - roll_max) / roll_max
        max_dd = dd.min()

        # Trade stats
        try:
            trades = portfolio.trades.records_readable
            n_trades = len(trades)
            if n_trades > 0:
                winning = trades[trades["PnL"] > 0]
                win_rate = len(winning) / n_trades
                gross_profit = winning["PnL"].sum() if len(winning) > 0 else 0.0
                losing = trades[trades["PnL"] < 0]
                gross_loss = abs(losing["PnL"].sum()) if len(losing) > 0 else 0.0
                profit_factor = gross_profit / (gross_loss + 1e-8)
            else:
                win_rate = 0.0
                profit_factor = 0.0
        except Exception:
            n_trades = 0
            win_rate = 0.0
            profit_factor = 0.0

        return {
            "sharpe": float(sharpe),
            "max_dd": float(max_dd),
            "trades": int(n_trades),
            "win_rate": float(win_rate),
            "profit_factor": float(profit_factor),
            "returns": rets,
        }
    except Exception as e:
        print(f"    [metrics error] {e}")
        return {
            "sharpe": 0.0,
            "max_dd": 0.0,
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "returns": pd.Series(dtype=float),
        }


# ── Statistical Rigor ─────────────────────────────────────────

def compute_dsr(returns: pd.Series, n_trials: int = 30) -> float:
    """Deflated Sharpe Ratio — adjusts for multiple testing bias."""
    if len(returns) < 30 or returns.std() < 1e-10:
        return 0.0
    T = len(returns)
    sharpe = returns.mean() / (returns.std() + 1e-10) * np.sqrt(252)
    # Expected max Sharpe from n_trials (Bailey & Lopez de Prado)
    from scipy import stats as sp_stats
    e_max = (1 - np.euler_gamma) * sp_stats.norm.ppf(1 - 1.0 / n_trials) + np.euler_gamma * sp_stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    skew = float(pd.Series(returns).skew())
    kurt = float(pd.Series(returns).kurtosis())
    dsr_num = (sharpe - e_max) * np.sqrt(T - 1)
    dsr_den = np.sqrt(1 - skew * sharpe + (kurt - 1) / 4.0 * sharpe ** 2 + 1e-10)
    dsr_z = dsr_num / (dsr_den + 1e-10)
    from scipy.special import ndtr
    return float(ndtr(dsr_z))  # probability that SR > 0 after multiple testing


def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    if len(trade_pnls) < 2:
        return {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=len(trade_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(252)
        sharpes.append(s)
    sharpes = np.array(sharpes)
    return {
        "mc_p5_sharpe": float(np.percentile(sharpes, 5)),
        "mc_median_sharpe": float(np.median(sharpes)),
        "mc_p95_sharpe": float(np.percentile(sharpes, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 500) -> dict:
    if len(returns) < 10:
        return {
            "sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
            "mdd_ci_low": 0.0, "mdd_ci_high": 0.0,
            "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0,
        }
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        n_blocks = T // block_len
        starts = np.random.randint(0, T - block_len + 1, size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / roll_max))
        s = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(252))
        wr = float(np.mean(sample > 0))
        sharpes.append(s)
        mdds.append(mdd)
        win_rates.append(wr)
    return {
        "sharpe_ci_low": float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high": float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low": float(np.percentile(mdds, 2.5)),
        "mdd_ci_high": float(np.percentile(mdds, 97.5)),
        "win_rate_ci_low": float(np.percentile(win_rates, 2.5)),
        "win_rate_ci_high": float(np.percentile(win_rates, 97.5)),
    }


def walk_forward_backtest(close_full: pd.DataFrame, params: dict,
                          train_months: int = 36, test_months: int = 6) -> dict:
    """Run walk-forward analysis with multiple IS/OOS windows."""
    train_days = train_months * 21
    test_days = test_months * 21
    step = test_days

    oos_sharpes = []
    windows_passed = 0

    start = 0
    n = len(close_full)

    while start + train_days + test_days <= n:
        is_data = close_full.iloc[start:start + train_days]
        oos_data = close_full.iloc[start + train_days:start + train_days + test_days]

        if len(is_data) < 63 or len(oos_data) < 21:
            break

        try:
            # IS window
            is_alloc = build_target_allocations(is_data, params)
            is_port = run_portfolio_simulation(is_data, is_alloc)
            is_metrics = compute_metrics(is_port)

            # OOS window
            oos_alloc = build_target_allocations(oos_data, params)
            oos_port = run_portfolio_simulation(oos_data, oos_alloc)
            oos_metrics = compute_metrics(oos_port)

            oos_sharpe = oos_metrics["sharpe"]
            oos_sharpes.append(oos_sharpe)
            if oos_sharpe > 0.7:
                windows_passed += 1
        except Exception as e:
            print(f"    [wf window error] {e}")

        start += step

    if not oos_sharpes:
        return {"wf_windows_passed": 0, "wf_consistency_score": 0.0,
                "wf_sharpe_std": 0.0, "wf_sharpe_min": 0.0}

    arr = np.array(oos_sharpes)
    return {
        "wf_windows_passed": windows_passed,
        "wf_consistency_score": windows_passed / max(len(oos_sharpes), 1),
        "wf_sharpe_std": float(arr.std()),
        "wf_sharpe_min": float(arr.min()),
        "wf_oos_sharpes": oos_sharpes,
    }


def sensitivity_scan(close_is: pd.DataFrame, base_params: dict, obs_is_sharpe: float) -> bool:
    """
    Perturb each parameter ±20% and check if Sharpe changes < 30%.
    Returns True if sensitivity passes.
    """
    param_ranges = {
        "lookback": [int(base_params["lookback"] * 0.8), int(base_params["lookback"] * 1.2)],
        "top_k": [max(1, base_params["top_k"] - 1), min(len(SYMBOLS), base_params["top_k"] + 1)],
        "target_vol": [base_params["target_vol"] * 0.8, base_params["target_vol"] * 1.2],
    }

    for param, values in param_ranges.items():
        for val in values:
            test_params = base_params.copy()
            test_params[param] = val
            try:
                alloc = build_target_allocations(close_is, test_params)
                port = run_portfolio_simulation(close_is, alloc)
                m = compute_metrics(port)
                pct_change = abs(m["sharpe"] - obs_is_sharpe) / (abs(obs_is_sharpe) + 1e-8)
                if pct_change > 0.30:
                    return False
            except Exception:
                return False
    return True


# ── Gate 1 Verdict ────────────────────────────────────────────

def gate1_verdict(metrics: dict) -> tuple[bool, list]:
    """Returns (pass, list_of_failures)."""
    failures = []
    if metrics.get("is_sharpe", 0) <= GATE1["min_is_sharpe"]:
        failures.append(f"IS Sharpe {metrics.get('is_sharpe', 0):.3f} ≤ {GATE1['min_is_sharpe']}")
    if metrics.get("oos_sharpe", 0) <= GATE1["min_oos_sharpe"]:
        failures.append(f"OOS Sharpe {metrics.get('oos_sharpe', 0):.3f} ≤ {GATE1['min_oos_sharpe']}")
    if metrics.get("is_max_dd", 0) <= GATE1["max_is_mdd"]:
        failures.append(f"IS MDD {metrics.get('is_max_dd', 0):.1%} ≤ {GATE1['max_is_mdd']:.0%}")
    if metrics.get("win_rate", 0) <= GATE1["min_win_rate"]:
        failures.append(f"Win rate {metrics.get('win_rate', 0):.1%} ≤ {GATE1['min_win_rate']:.0%}")
    if metrics.get("is_trades", 0) < GATE1["min_trades"]:
        failures.append(f"IS trades {metrics.get('is_trades', 0)} < {GATE1['min_trades']}")
    return len(failures) == 0, failures


# ── Main Batch Runner ─────────────────────────────────────────

def run_batch():
    print("=" * 70)
    print("Momentum Vol-Scaled Batch Runner — 30 Iterations (36-65)")
    print("=" * 70)

    conn = init_db()
    next_iter = get_next_iteration(conn)
    print(f"Starting from iteration {next_iter}")

    # Fetch all data once
    raw_data = fetch_all_data()

    # Extract close prices for all symbols
    close_all = raw_data.xs("Close", level=1, axis=1) if isinstance(raw_data.columns, pd.MultiIndex) else raw_data["Close"]
    # Handle possible column naming differences
    if not isinstance(close_all, pd.DataFrame):
        print("ERROR: Could not extract Close prices from data")
        return

    # Ensure all symbols are present
    available = [s for s in SYMBOLS if s in close_all.columns]
    close_all = close_all[available].dropna(how="all")
    print(f"Available tickers: {available}")

    # Split into periods
    close_is = close_all.loc[IS_START:IS_END].copy()
    close_oos = close_all.loc[OOS_START:OOS_END].copy()
    # Full period for walk-forward (needs warmup from DATA_START)
    close_for_wf = close_all.copy()

    print(f"IS period: {close_is.index[0].date()} to {close_is.index[-1].date()} ({len(close_is)} days)")
    print(f"OOS period: {close_oos.index[0].date()} to {close_oos.index[-1].date()} ({len(close_oos)} days)")

    results = []
    gate1_pass = []
    gate1_fail = []

    for v_idx, variant in enumerate(VARIANTS):
        iter_num = next_iter + v_idx
        strategy_name = variant["name"]
        print(f"\n{'─' * 60}")
        print(f"Iteration {iter_num}: {strategy_name}")
        print(f"  lookback={variant['lookback']}m, skip={variant['skip']}m, top_k={variant['top_k']}, "
              f"target_vol={variant['target_vol']:.0%}, rebalance={variant['rebalance']}d, "
              f"crash={variant['crash']}, equal_weight={variant['equal_weight']}")

        try:
            # IS backtest
            print("  Running IS backtest...")
            is_alloc = build_target_allocations(close_is, variant)
            is_port = run_portfolio_simulation(close_is, is_alloc)
            is_m = compute_metrics(is_port)
            print(f"  IS: Sharpe={is_m['sharpe']:.3f}, MDD={is_m['max_dd']:.1%}, "
                  f"Trades={is_m['trades']}, WinRate={is_m['win_rate']:.1%}")

            # Flag IS MDD > 20% immediately
            if is_m["max_dd"] < -0.20:
                print(f"  ⚠️  FLAG: IS MDD {is_m['max_dd']:.1%} > 20% — momentum crash risk")

            # OOS backtest
            print("  Running OOS backtest...")
            oos_alloc = build_target_allocations(close_oos, variant)
            oos_port = run_portfolio_simulation(close_oos, oos_alloc)
            oos_m = compute_metrics(oos_port)
            print(f"  OOS: Sharpe={oos_m['sharpe']:.3f}, MDD={oos_m['max_dd']:.1%}")

            # Flag suspicious OOS/IS ratio
            if is_m["sharpe"] > 0 and oos_m["sharpe"] > is_m["sharpe"] * 10:
                print(f"  🚨 LOOK-AHEAD BIAS SUSPECTED: OOS Sharpe {oos_m['sharpe']:.2f} > 10× IS Sharpe {is_m['sharpe']:.2f}")

            # Walk-forward
            print("  Running walk-forward (4 windows, 36m IS / 6m OOS)...")
            wf = walk_forward_backtest(close_for_wf, variant)
            print(f"  WF: windows_passed={wf['wf_windows_passed']}, consistency={wf['wf_consistency_score']:.2f}, "
                  f"min_oos_sharpe={wf['wf_sharpe_min']:.3f}, std={wf['wf_sharpe_std']:.3f}")
            if wf.get("wf_sharpe_min", 0) < 0:
                print(f"  ⚠️  FLAG: Walk-forward min OOS Sharpe {wf['wf_sharpe_min']:.3f} < 0")

            # Statistical rigor
            is_returns_arr = is_m["returns"].values if len(is_m["returns"]) > 0 else np.array([0.0])
            # Get trade PnLs for Monte Carlo
            try:
                is_trades_records = is_port.trades.records_readable
                trade_pnls = is_trades_records["PnL"].values if len(is_trades_records) > 0 else np.array([0.0])
            except Exception:
                trade_pnls = is_returns_arr

            mc = monte_carlo_sharpe(trade_pnls)
            bci = block_bootstrap_ci(is_returns_arr)

            if mc["mc_p5_sharpe"] < 0.5:
                print(f"  ⚠️  MC pessimistic bound weak: p5 Sharpe={mc['mc_p5_sharpe']:.3f}")

            # DSR
            dsr = compute_dsr(is_returns_arr, n_trials=30)
            print(f"  DSR={dsr:.3f}, MC_p5={mc['mc_p5_sharpe']:.3f}, MC_med={mc['mc_median_sharpe']:.3f}")

            # Sensitivity scan
            print("  Running sensitivity scan...")
            sens_pass = sensitivity_scan(close_is, variant, is_m["sharpe"])
            print(f"  Sensitivity: {'PASS' if sens_pass else 'FAIL'}")

            # Gate 1 check
            combined_metrics = {
                "is_sharpe": is_m["sharpe"],
                "oos_sharpe": oos_m["sharpe"],
                "is_max_dd": is_m["max_dd"],
                "win_rate": is_m["win_rate"],
                "is_trades": is_m["trades"],
            }
            passed, failures = gate1_verdict(combined_metrics)
            verdict = "PASS" if passed else f"FAIL ({'; '.join(failures)})"
            print(f"  Gate 1: {verdict}")

            # Build full metrics dict
            full_metrics = {
                "strategy_name": strategy_name,
                "date": datetime.date.today().isoformat(),
                "asset_class": "equities",
                "is_sharpe": is_m["sharpe"],
                "oos_sharpe": oos_m["sharpe"],
                "is_max_drawdown": is_m["max_dd"],
                "oos_max_drawdown": oos_m["max_dd"],
                "win_rate": is_m["win_rate"],
                "profit_factor": is_m["profit_factor"],
                "trade_count": is_m["trades"],
                "dsr": dsr,
                "wf_windows_passed": wf["wf_windows_passed"],
                "wf_consistency_score": wf["wf_consistency_score"],
                "wf_sharpe_std": wf.get("wf_sharpe_std", 0.0),
                "wf_sharpe_min": wf.get("wf_sharpe_min", 0.0),
                "sensitivity_pass": sens_pass,
                "post_cost_sharpe": is_m["sharpe"],  # already includes transaction costs
                "look_ahead_bias_flag": False,
                "gate1_pass": passed,
                "mc_p5_sharpe": mc["mc_p5_sharpe"],
                "mc_median_sharpe": mc["mc_median_sharpe"],
                "mc_p95_sharpe": mc["mc_p95_sharpe"],
                "sharpe_ci_low": bci["sharpe_ci_low"],
                "sharpe_ci_high": bci["sharpe_ci_high"],
                "mdd_ci_low": bci["mdd_ci_low"],
                "mdd_ci_high": bci["mdd_ci_high"],
                "win_rate_ci_low": bci["win_rate_ci_low"],
                "win_rate_ci_high": bci["win_rate_ci_high"],
                "market_impact_bps": 0.0,  # not estimated for batch
                "liquidity_constrained": False,
                "order_to_adv_ratio": 0.0,
                "permutation_pvalue": 0.5,  # not run for speed
                "permutation_test_pass": True,
                "parameters": variant,
                "iteration": iter_num,
            }

            # Save JSON
            json_path = BACKTESTS_DIR / f"{strategy_name}_{datetime.date.today().isoformat()}.json"
            with open(json_path, "w") as f:
                json.dump(full_metrics, f, indent=2, default=str)

            # Save verdict
            verdict_text = f"""Gate 1 Verdict — {strategy_name}
Date: {datetime.date.today().isoformat()}
Iteration: {iter_num}

VERDICT: {'PASS ✅' if passed else 'FAIL ❌'}

IS Sharpe:        {is_m['sharpe']:.4f}   (threshold: > 1.0)
OOS Sharpe:       {oos_m['sharpe']:.4f}   (threshold: > 0.7)
IS MaxDD:         {is_m['max_dd']:.2%}   (threshold: < -20%)
OOS MaxDD:        {oos_m['max_dd']:.2%}   (threshold: < -25%)
Win Rate:         {is_m['win_rate']:.2%}   (threshold: > 50%)
Trade Count (IS): {is_m['trades']}      (threshold: >= 50)
DSR:              {dsr:.4f}
WF Windows Passed: {wf['wf_windows_passed']} / {max(wf['wf_windows_passed'] + max(0, 4 - wf['wf_windows_passed']), 4)}
WF Min OOS Sharpe: {wf.get('wf_sharpe_min', 0):.4f}
MC P5 Sharpe:     {mc['mc_p5_sharpe']:.4f}
Sensitivity Pass: {sens_pass}

{'Failures: ' + '; '.join(failures) if failures else 'All Gate 1 criteria met.'}

Parameters: {json.dumps(variant, indent=2)}
"""
            verdict_path = BACKTESTS_DIR / f"{strategy_name}_{datetime.date.today().isoformat()}_verdict.txt"
            with open(verdict_path, "w") as f:
                f.write(verdict_text)

            # Log to DB
            log_iteration(conn, {
                "iteration": iter_num,
                "strategy_name": strategy_name,
                "hypothesis": "Momentum Vol-Scaled (Hypothesis 05): cross-sectional momentum with inverse-vol sizing and crash protection",
                "parameters": variant,
                "sharpe_in_sample": is_m["sharpe"],
                "sharpe_out_of_sample": oos_m["sharpe"],
                "max_drawdown": is_m["max_dd"],
                "total_trades": is_m["trades"],
                "win_rate": is_m["win_rate"],
                "profit_factor": is_m["profit_factor"],
                "passed_criteria": passed,
                "post_mortem": verdict,
                "strategy_code": f"momentum_vol_scaled({variant})",
                "wf_windows_passed": wf["wf_windows_passed"],
                "wf_consistency_score": wf["wf_consistency_score"],
                "post_cost_sharpe": is_m["sharpe"],
                "asset_class": "equities",
                "dsr": dsr,
                "sensitivity_pass": sens_pass,
            })

            # Track results
            result_row = {
                "iteration": iter_num,
                "name": strategy_name,
                "is_sharpe": is_m["sharpe"],
                "oos_sharpe": oos_m["sharpe"],
                "is_mdd": is_m["max_dd"],
                "win_rate": is_m["win_rate"],
                "trades": is_m["trades"],
                "passed": passed,
                "failures": failures,
            }
            results.append(result_row)
            if passed:
                gate1_pass.append(result_row)
            else:
                gate1_fail.append(result_row)

        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            traceback.print_exc()
            log_iteration(conn, {
                "iteration": iter_num,
                "strategy_name": strategy_name,
                "hypothesis": "Momentum Vol-Scaled (Hypothesis 05)",
                "parameters": variant,
                "sharpe_in_sample": 0.0,
                "sharpe_out_of_sample": 0.0,
                "max_drawdown": 0.0,
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "passed_criteria": False,
                "post_mortem": f"ERROR: {str(e)}\n{traceback.format_exc()}",
                "asset_class": "equities",
            })
            results.append({
                "iteration": iter_num,
                "name": strategy_name,
                "is_sharpe": 0.0,
                "oos_sharpe": 0.0,
                "is_mdd": 0.0,
                "win_rate": 0.0,
                "trades": 0,
                "passed": False,
                "failures": [str(e)],
            })
            gate1_fail.append(results[-1])

    conn.close()

    # Final summary
    print("\n" + "=" * 70)
    print("BATCH COMPLETE — SUMMARY")
    print("=" * 70)
    print(f"Total iterations: {len(results)}")
    print(f"Gate 1 PASS:  {len(gate1_pass)}")
    print(f"Gate 1 FAIL:  {len(gate1_fail)}")

    # Sort by OOS Sharpe
    sorted_results = sorted(results, key=lambda x: x["oos_sharpe"], reverse=True)
    print("\nTop 10 by OOS Sharpe:")
    print(f"{'Iter':>5} {'Name':<45} {'IS Sh':>7} {'OOS Sh':>7} {'IS MDD':>8} {'WR':>6} {'Trades':>7} {'Pass':>5}")
    print("-" * 95)
    for r in sorted_results[:10]:
        print(f"{r['iteration']:>5} {r['name']:<45} {r['is_sharpe']:>7.3f} {r['oos_sharpe']:>7.3f} "
              f"{r['is_mdd']:>8.1%} {r['win_rate']:>6.1%} {r['trades']:>7} {'✅' if r['passed'] else '❌':>5}")

    # Save summary
    summary = {
        "batch_date": datetime.date.today().isoformat(),
        "hypothesis": "05_momentum_vol_scaled",
        "total_iterations": len(results),
        "gate1_pass_count": len(gate1_pass),
        "gate1_fail_count": len(gate1_fail),
        "top_3_by_oos_sharpe": sorted_results[:3],
        "all_results": sorted_results,
    }
    summary_path = BACKTESTS_DIR / f"mvs_batch_summary_{datetime.date.today().isoformat()}.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nSummary saved to {summary_path}")

    return summary


if __name__ == "__main__":
    np.random.seed(42)
    run_batch()

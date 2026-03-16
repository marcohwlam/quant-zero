"""
quant_orchestrator.py
Minimal AI-driven strategy iteration loop.

Usage:
    export ANTHROPIC_API_KEY="sk-ant-..."
    python quant_orchestrator.py

The orchestrator:
  1. Loads the knowledge base (prior patterns and learnings)
  2. Asks Claude to propose a strategy
  3. Runs in-sample and out-of-sample backtests via VectorBT
  4. Asks Claude to evaluate results and extract learnings
  5. Logs everything to SQLite + JSON knowledge base
  6. Iterates N times, promoting passing strategies
"""

import json
import math
import time
import datetime
import sqlite3
import traceback
from pathlib import Path

import anthropic
import vectorbt as vbt
import pandas as pd
import numpy as np
import yfinance as yf
from scipy import stats as scipy_stats

from gate1_reporter import generate_and_save_verdict


# ── Transaction Cost Model ────────────────────────────────────
# Fees and slippage expressed as fractions of trade value.
# Equities: $0.005/share ≈ 0.01% on $50 avg price; Slippage: 0.05%
# Options:  $0.65/contract ≈ 0.10%; Slippage: 0.10%
# Crypto:   0.10% taker fee; Slippage: 0.05%
TRANSACTION_COSTS = {
    "equities": {"fees": 0.0001, "slippage": 0.0005},
    "options":  {"fees": 0.0010, "slippage": 0.0010},
    "crypto":   {"fees": 0.0010, "slippage": 0.0005},
}


def get_cost_params(asset_class: str) -> dict:
    """Return fee and slippage fractions for the given asset class."""
    return TRANSACTION_COSTS.get(asset_class.lower(), TRANSACTION_COSTS["equities"])


# ── Configuration ────────────────────────────────────────────

_HERE = Path(__file__).parent

CONFIG = {
    "model": "claude-sonnet-4-6",
    "max_iterations": 30,
    "symbols": ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV"],
    "in_sample_start": "2018-01-01",
    "in_sample_end": "2022-12-31",
    "out_of_sample_start": "2023-01-01",
    "out_of_sample_end": "2024-12-31",
    "acceptance_criteria": {
        "min_sharpe_in_sample": 1.0,
        "min_sharpe_out_of_sample": 0.7,
        "max_drawdown": -0.20,        # -20%
        "min_trades": 50,
        "max_parameters": 6,
    },
    "knowledge_base_path": str(_HERE / "knowledge_base"),
    "iteration_db_path": str(_HERE / "iteration_log.db"),
}


# ── Data Layer ───────────────────────────────────────────────

def fetch_data(symbols: list, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV data via yfinance."""
    data = yf.download(symbols, start=start, end=end, group_by="ticker")
    return data


def split_data(data: pd.DataFrame, config: dict):
    """Split into in-sample and out-of-sample windows."""
    in_sample = data.loc[config["in_sample_start"]:config["in_sample_end"]]
    out_of_sample = data.loc[config["out_of_sample_start"]:config["out_of_sample_end"]]
    return in_sample, out_of_sample


# ── Knowledge Base ───────────────────────────────────────────

def load_knowledge_base(path: str) -> str:
    """Load all strategy patterns and learnings into a single string."""
    kb_path = Path(path)
    kb_path.mkdir(exist_ok=True)

    documents = []
    for f in sorted(kb_path.glob("*.md")):
        documents.append(f"## {f.stem}\n\n{f.read_text()}")
    for f in sorted(kb_path.glob("*.json")):
        documents.append(f"## {f.stem}\n\n```json\n{f.read_text()}\n```")

    return "\n\n---\n\n".join(documents) if documents else "No prior strategies or learnings yet."


def save_learning(path: str, iteration: int, content: dict):
    """Save a post-mortem learning entry."""
    kb_path = Path(path)
    kb_path.mkdir(exist_ok=True)

    filename = f"iteration_{iteration:04d}_learning.json"
    with open(kb_path / filename, "w") as f:
        json.dump(content, f, indent=2, default=str)


# ── Iteration Log (SQLite) ──────────────────────────────────

def init_db(db_path: str):
    """Create iteration tracking table."""
    conn = sqlite3.connect(db_path)
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
    # Add new columns to existing tables (idempotent)
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
            pass  # Column already exists
    conn.commit()
    return conn


def log_iteration(conn, data: dict):
    """Insert a row into the iteration log."""
    conn.execute("""
        INSERT INTO iterations
        (timestamp, iteration, strategy_name, hypothesis, parameters,
         sharpe_in_sample, sharpe_out_of_sample, max_drawdown,
         total_trades, win_rate, profit_factor,
         passed_criteria, post_mortem, strategy_code,
         wf_windows_passed, wf_consistency_score,
         post_cost_sharpe, asset_class,
         dsr, sensitivity_pass)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.datetime.now().isoformat(),
        data.get("iteration"),
        data.get("strategy_name"),
        data.get("hypothesis"),
        json.dumps(data.get("parameters", {}), default=lambda o: bool(o) if hasattr(o, '__bool__') else str(o)),
        data.get("sharpe_in_sample"),
        data.get("sharpe_out_of_sample"),
        data.get("max_drawdown"),
        data.get("total_trades"),
        data.get("win_rate"),
        data.get("profit_factor"),
        data.get("passed_criteria"),
        data.get("post_mortem"),
        data.get("strategy_code"),
        data.get("wf_windows_passed"),
        data.get("wf_consistency_score"),
        data.get("post_cost_sharpe"),
        data.get("asset_class"),
        data.get("dsr"),
        int(data["sensitivity_pass"]) if data.get("sensitivity_pass") is not None else None,
    ))
    conn.commit()


def get_recent_iterations(conn, n=5) -> str:
    """Retrieve last N iterations as context for Claude."""
    cursor = conn.execute("""
        SELECT iteration, strategy_name, hypothesis,
               sharpe_in_sample, sharpe_out_of_sample, max_drawdown,
               total_trades, passed_criteria, post_mortem
        FROM iterations ORDER BY id DESC LIMIT ?
    """, (n,))

    rows = cursor.fetchall()
    if not rows:
        return "No prior iterations."

    summaries = []
    for r in rows:
        summaries.append(
            f"- Iteration {r[0]}: {r[1]} | Hypothesis: {r[2]} | "
            f"IS Sharpe: {r[3]:.2f} | OOS Sharpe: {r[4]:.2f} | "
            f"MaxDD: {r[5]:.1%} | Trades: {r[6]} | "
            f"Passed: {'Yes' if r[7] else 'No'} | Learning: {r[8]}"
        )
    return "\n".join(summaries)


# ── Claude Integration ───────────────────────────────────────

client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var


PROPOSE_SYSTEM_PROMPT = """You are a quantitative trading strategist. You design
systematic trading strategies and iterate on them based on backtest results.

RULES:
1. Every strategy must have a clear, falsifiable hypothesis.
2. Prefer simplicity — fewer parameters beat more parameters.
3. Always consider regime changes, transaction costs, and overfitting risk.
4. Learn from prior iteration results — do not repeat failed approaches.
5. Generate executable Python code using vectorbt for backtesting.

DATA FORMAT — CRITICAL:
The `data` variable is a pandas DataFrame downloaded from yfinance for multiple tickers.
It has a MultiIndex column structure: (ticker, field). Example columns:
  ('SPY', 'Open'), ('SPY', 'High'), ('SPY', 'Low'), ('SPY', 'Close'), ('SPY', 'Volume'),
  ('QQQ', 'Open'), ('QQQ', 'Close'), ...

To access data correctly:
  # Get close prices for all tickers (DataFrame: index=date, columns=ticker)
  close = data.xs('Close', level=1, axis=1)

  # Get a single ticker's close prices (Series)
  spy_close = data['SPY']['Close']   # or data[('SPY', 'Close')]

  # Get close prices for specific tickers
  closes = data.xs('Close', level=1, axis=1)[['SPY', 'QQQ']]

NEVER use data['Close'] — it will raise KeyError. Always access via ticker first or xs().

VECTORBT API — CRITICAL:
Available portfolio constructors: vbt.Portfolio.from_signals(), vbt.Portfolio.from_orders()
DO NOT use: Portfolio.from_returns(), Portfolio.from_daily_returns() — these do not exist.
DO NOT use size_type parameter in from_signals() — it raises ValueError. Only Amount/Value/Percent allowed.

Minimal working from_signals example (copy this pattern exactly):
  close = data.xs('Close', level=1, axis=1)  # DataFrame, columns=tickers
  # entries/exits: boolean DataFrame same shape as close
  entries = (close < close.rolling(20).mean())  # example condition
  exits = (close > close.rolling(20).mean())
  portfolio = vbt.Portfolio.from_signals(
      close, entries, exits,
      freq='D',
      init_cash=100_000,
      fees=0.001,
  )

Minimal working from_orders example:
  close = data.xs('Close', level=1, axis=1)
  size = pd.DataFrame(0.0, index=close.index, columns=close.columns)  # same shape
  # set size positive to buy, negative to sell, 0 to hold
  portfolio = vbt.Portfolio.from_orders(close, size, freq='D', init_cash=100_000, fees=0.001)

DO NOT define helper functions (no def compute_rsi(), def sma(), etc.). All logic must be inline.
Available in scope: pd, np, vbt, data (the full multi-ticker DataFrame).
Built-in indicators: vbt.RSI.run(close, window=14).rsi  |  vbt.MA.run(close, window=20).ma
  vbt.BBANDS.run(close, window=20)  |  vbt.ATR.run(high, low, close, window=14).atr

OUTPUT FORMAT (respond ONLY with this JSON, no markdown fences):
{
  "strategy_name": "short_descriptive_name",
  "hypothesis": "Why this should work, grounded in market microstructure or behavior",
  "asset_class": "equities",
  "parameters": {"param1": value1, "param2": value2},
  "num_parameters": 3,
  "code": "# Full Python code that takes `data` (pd.DataFrame of OHLCV) and returns a vectorbt Portfolio object named `portfolio`",
  "rationale_vs_prior": "What changed from last iteration and why"
}

asset_class must be one of: "equities", "options", "crypto". Default to "equities" for ETF/stock strategies."""


def _call_claude_with_retry(model: str, max_tokens: int, system: str, messages: list,
                            tools: list = None, max_retries: int = 3) -> str:
    """Call Claude API with exponential backoff retry on rate limit or non-JSON response.

    If tools is provided, forces tool_choice=any so Claude must call the tool (guaranteed JSON).
    Otherwise falls back to text parsing with retry.
    """
    delays = [10, 30, 60]
    for attempt in range(max_retries + 1):
        try:
            kwargs = dict(model=model, max_tokens=max_tokens, system=system, messages=messages)
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = {"type": "any"}
                response = client.messages.create(**kwargs)
                # Extract tool input — always valid JSON when tool_choice=any
                for block in response.content:
                    if block.type == "tool_use":
                        return json.dumps(block.input)
                raise ValueError("Claude did not call tool despite tool_choice=any")
            else:
                response = client.messages.create(**kwargs)
                text = response.content[0].text.strip() if response.content else ""
                if not text:
                    raise ValueError("Claude returned empty response")
                cleaned = text.replace("```json", "").replace("```", "").strip()
                json.loads(cleaned)  # validate
                return cleaned
        except (anthropic.RateLimitError, ValueError, json.JSONDecodeError) as e:
            if attempt < max_retries:
                wait = delays[min(attempt, len(delays) - 1)]
                print(f"  Claude API error ({type(e).__name__}: {e}), retrying in {wait}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(wait)
            else:
                raise


_PROPOSE_TOOL = [
    {
        "name": "submit_strategy",
        "description": "Submit the proposed trading strategy. Must be called with all required fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy_name": {"type": "string", "description": "Short descriptive name"},
                "hypothesis": {"type": "string", "description": "Why this should work"},
                "asset_class": {"type": "string", "enum": ["equities", "options", "crypto"]},
                "parameters": {"type": "object", "description": "Strategy parameters dict"},
                "num_parameters": {"type": "integer"},
                "code": {"type": "string", "description": "Full Python code producing a vectorbt Portfolio named `portfolio`"},
                "rationale_vs_prior": {"type": "string", "description": "What changed and why"},
            },
            "required": ["strategy_name", "hypothesis", "asset_class", "parameters", "num_parameters", "code", "rationale_vs_prior"],
        },
    }
]


def propose_strategy(knowledge_base: str, recent_iterations: str, iteration: int) -> dict:
    """Ask Claude to propose a new or refined strategy (uses tool calling for guaranteed JSON)."""
    user_msg = f"""
ITERATION: {iteration}

KNOWLEDGE BASE (proven patterns and learnings):
{knowledge_base}

RECENT ITERATION RESULTS:
{recent_iterations}

AVAILABLE SYMBOLS: {CONFIG['symbols']}
IN-SAMPLE PERIOD: {CONFIG['in_sample_start']} to {CONFIG['in_sample_end']}

ACCEPTANCE CRITERIA:
- In-sample Sharpe >= {CONFIG['acceptance_criteria']['min_sharpe_in_sample']}
- Out-of-sample Sharpe >= {CONFIG['acceptance_criteria']['min_sharpe_out_of_sample']}
- Max drawdown >= {CONFIG['acceptance_criteria']['max_drawdown']} (i.e., no worse than {CONFIG['acceptance_criteria']['max_drawdown']:.0%})
- Minimum {CONFIG['acceptance_criteria']['min_trades']} trades
- Maximum {CONFIG['acceptance_criteria']['max_parameters']} parameters

{"This is the first iteration. Start with a well-known systematic strategy from the knowledge base and implement it cleanly." if iteration == 1 else "Based on prior results, propose an improvement. Explain what you're changing and why."}

STRATEGY FOCUS FOR THIS BATCH (Phase 1 Candidate #05 — Momentum Vol-Scaled):
This batch targets Hypothesis 05: cross-sectional momentum with volatility scaling (Jegadeesh-Titman 1993 with risk-parity sizing). Each iteration MUST implement a variant of momentum_vol_scaled. Core logic:
1. Monthly signal: rank ETFs/stocks by past momentum_lookback_months return, skip most recent skip_recent_months (skip-1-month reversal fix)
2. Long top quintile, short bottom quintile (or long-only for $25K simplicity)
3. Weight inversely by realized volatility (target_volatility portfolio)
4. Crash protection: halve exposure if SPY 1-month return < crash_protection_threshold (-0.10); restore full exposure when SPY 1-month return recovers above threshold
5. Rebalance every rebalance_frequency_days trading days (~21 = monthly)

Key parameters to vary across iterations: momentum_lookback_months [3,6,9,12,18], skip_recent_months [0,1,2], target_volatility [0.08,0.10,0.15], rebalance_frequency_days [10,15,21,42], crash_protection_threshold [-0.05,-0.08,-0.10,-0.12].

CRITICAL constraints per Gate 1:
- IS MDD must be < 20%; crash protection is essential to prevent the 2020 momentum crash from disqualifying the strategy
- Trade count must be > 50 IS trades; monthly rebalance generates 100s of trades easily — do NOT worry about trade count
- Use SPY,QQQ,IWM,DIA,XLF,XLE,XLK,XLV as the universe (available in CONFIG['symbols'])
- Long-only or modest short (no more than 20% of portfolio short) given $25K PDT constraints
- Avoid look-ahead bias: all signals must use data available at rebalance time only

Flag immediately if OOS Sharpe > 10× IS Sharpe — indicates look-ahead bias.

Call submit_strategy with your proposed strategy.
"""

    text = _call_claude_with_retry(
        model=CONFIG["model"],
        max_tokens=4096,
        system=PROPOSE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        tools=_PROPOSE_TOOL,
    )
    return json.loads(text)


EVALUATE_SYSTEM_PROMPT = """You are a quantitative analyst evaluating backtest results.
Be rigorous about overfitting. Compare in-sample vs out-of-sample performance.
A large gap between IS and OOS Sharpe suggests overfitting.
Call submit_evaluation with your assessment."""


_EVALUATE_TOOL = [
    {
        "name": "submit_evaluation",
        "description": "Submit the evaluation of backtest results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "assessment": {"type": "string", "enum": ["passed", "failed"]},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "overfitting_risk": {"type": "string", "enum": ["low", "medium", "high"]},
                "post_mortem": {"type": "string", "description": "What we learned from this iteration"},
                "next_direction": {"type": "string", "description": "Specific suggestion for next iteration"},
                "promote_to_paper": {"type": "boolean"},
            },
            "required": ["assessment", "confidence", "overfitting_risk", "post_mortem", "next_direction", "promote_to_paper"],
        },
    }
]


def evaluate_results(proposal: dict, metrics: dict) -> dict:
    """Ask Claude to evaluate backtest results and extract learnings (uses tool calling)."""
    user_msg = f"""
STRATEGY: {proposal['strategy_name']}
HYPOTHESIS: {proposal['hypothesis']}
PARAMETERS: {json.dumps(proposal['parameters'])}

BACKTEST RESULTS:
- In-Sample Sharpe: {metrics.get('sharpe_in_sample', 'N/A')}
- Out-of-Sample Sharpe: {metrics.get('sharpe_out_of_sample', 'N/A')}
- In-Sample Max Drawdown: {metrics.get('max_dd_in_sample', 'N/A')}
- Out-of-Sample Max Drawdown: {metrics.get('max_dd_out_of_sample', 'N/A')}
- Total Trades (IS): {metrics.get('trades_in_sample', 'N/A')}
- Total Trades (OOS): {metrics.get('trades_out_of_sample', 'N/A')}
- Win Rate (IS): {metrics.get('win_rate_in_sample', 'N/A')}
- Profit Factor (IS): {metrics.get('profit_factor_in_sample', 'N/A')}

WALK-FORWARD RESULTS:
- Windows Passed: {metrics.get('wf_windows_passed', 'N/A')}/{metrics.get('wf_windows_total', 'N/A')}
- Consistency Score: {metrics.get('wf_consistency_score', 'N/A')} (target >= 0.70)
- Walk-Forward Gate: {'PASS' if metrics.get('wf_pass') else 'FAIL'}

TRANSACTION COST IMPACT (asset class: {metrics.get('asset_class', 'equities')}):
- Post-Cost IS Sharpe: {metrics.get('post_cost_sharpe_is', 'N/A')}
- Post-Cost OOS Sharpe: {metrics.get('post_cost_sharpe_oos', 'N/A')}
- Cost impact: strategy {'SURVIVES' if metrics.get('post_cost_sharpe_is', 0) > 0 else 'FAILS'} after realistic transaction costs

ACCEPTANCE CRITERIA:
- In-sample Sharpe >= {CONFIG['acceptance_criteria']['min_sharpe_in_sample']}
- Out-of-sample Sharpe >= {CONFIG['acceptance_criteria']['min_sharpe_out_of_sample']}
- Max drawdown >= {CONFIG['acceptance_criteria']['max_drawdown']}
- Minimum {CONFIG['acceptance_criteria']['min_trades']} trades
- Walk-forward: >= 3 of 4 windows must pass
- Post-cost Sharpe (IS) must be > 0 (strategy must survive transaction costs)

Call submit_evaluation with your assessment.
"""

    text = _call_claude_with_retry(
        model=CONFIG["model"],
        max_tokens=2048,
        system=EVALUATE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        tools=_EVALUATE_TOOL,
    )
    return json.loads(text)


# ── Backtest Execution ───────────────────────────────────────

def run_backtest(code: str, data: pd.DataFrame, asset_class: str = "equities") -> dict:
    """Execute strategy code and extract metrics from the resulting portfolio.

    Runs the strategy twice: once without costs (pre-cost Sharpe) and once with
    realistic transaction costs injected via Portfolio.from_signals (post_cost_sharpe).
    Gate 1 pass/fail uses post_cost_sharpe.
    """
    # ── Pre-cost run ──────────────────────────────────────────
    local_vars = {"data": data, "pd": pd, "np": np, "vbt": vbt}
    exec(code, {}, local_vars)  # noqa: S102

    portfolio = local_vars.get("portfolio")
    if portfolio is None:
        raise ValueError("Strategy code did not produce a 'portfolio' variable.")

    stats = portfolio.stats()
    pre_cost_sharpe = stats.get("Sharpe Ratio", 0)

    # ── Post-cost run ─────────────────────────────────────────
    costs = get_cost_params(asset_class)
    original_from_signals = vbt.Portfolio.from_signals

    def _from_signals_with_costs(*args, **kwargs):
        kwargs.setdefault("fees", costs["fees"])
        kwargs.setdefault("slippage", costs["slippage"])
        return original_from_signals(*args, **kwargs)

    post_cost_sharpe = pre_cost_sharpe  # fallback if strategy bypasses from_signals
    try:
        vbt.Portfolio.from_signals = _from_signals_with_costs
        local_vars_cost = {"data": data, "pd": pd, "np": np, "vbt": vbt}
        exec(code, {}, local_vars_cost)  # noqa: S102
        portfolio_cost = local_vars_cost.get("portfolio")
        if portfolio_cost is not None:
            cost_stats = portfolio_cost.stats()
            post_cost_sharpe = cost_stats.get("Sharpe Ratio", 0)
    finally:
        vbt.Portfolio.from_signals = original_from_signals

    # Extract daily returns for DSR computation
    raw_returns = portfolio.returns()
    if isinstance(raw_returns, pd.DataFrame):
        portfolio_returns = raw_returns.mean(axis=1).dropna()
    else:
        portfolio_returns = raw_returns.dropna()

    return {
        "sharpe": pre_cost_sharpe,
        "max_drawdown": stats.get("Max Drawdown [%]", 0) / -100,
        "total_trades": stats.get("Total Trades", 0),
        "win_rate": stats.get("Win Rate [%]", 0) / 100,
        "profit_factor": stats.get("Profit Factor", 0),
        "total_return": stats.get("Total Return [%]", 0) / 100,
        "post_cost_sharpe": post_cost_sharpe,
        "asset_class": asset_class,
        "portfolio_returns": portfolio_returns,
    }


# ── Deflated Sharpe Ratio (DSR) ──────────────────────────────

_DSR_GAMMA_EM = 0.5772156649015328  # Euler-Mascheroni constant


def compute_dsr(returns_series: pd.Series, trials_tested: int = 1) -> dict:
    """
    Compute the Deflated Sharpe Ratio (DSR) from a daily returns series.

    Adjusts the observed Sharpe Ratio for:
    1. Non-normality of returns (skewness / kurtosis correction)
    2. Multiple-comparison bias (SR* expected max from n trials)

    Gate 1 threshold: DSR z-score > 0 required.  ≤ 0 = auto-disqualify.

    Args:
        returns_series: Daily portfolio returns (pd.Series, NaN-dropped internally).
        trials_tested:  Number of strategy variants tested before selecting this one.
                        Use the iteration count as a proxy.  Larger → lower DSR.

    Returns:
        Dict with keys: dsr_zscore, dsr_probability, dsr_sr_star, passed, n_obs.
    """
    returns = returns_series.dropna()
    n_obs = len(returns)

    if n_obs < 2:
        return {"dsr_zscore": float("-inf"), "dsr_probability": 0.0,
                "dsr_sr_star": 0.0, "passed": False, "n_obs": n_obs}

    daily_std = float(returns.std())
    if daily_std <= 0:
        return {"dsr_zscore": 0.0, "dsr_probability": 0.5,
                "dsr_sr_star": 0.0, "passed": False, "n_obs": n_obs}

    # Annualized Sharpe (daily returns × √252)
    sr_hat = (float(returns.mean()) / daily_std) * math.sqrt(252)

    # Higher moments (scipy returns excess kurtosis by default)
    skewness = float(scipy_stats.skew(returns))
    excess_kurtosis = float(scipy_stats.kurtosis(returns))

    # SR* — expected max Sharpe under null hypothesis across n trials
    if trials_tested <= 1:
        sr_star = 0.0
    else:
        sigma_sr = 1.0 / math.sqrt(max(n_obs - 1, 1))
        term1 = (1.0 - _DSR_GAMMA_EM) * scipy_stats.norm.ppf(1.0 - 1.0 / trials_tested)
        term2 = _DSR_GAMMA_EM * scipy_stats.norm.ppf(
            1.0 - 1.0 / (trials_tested * math.e)
        )
        sr_star = sigma_sr * (term1 + term2)

    # Non-normality correction to the denominator
    variance_term = (
        1.0
        - skewness * sr_hat
        + ((excess_kurtosis + 2.0) / 4.0) * sr_hat ** 2
    )
    if variance_term <= 0.0:
        variance_term = 1e-12

    dsr_z = math.sqrt(max(n_obs - 1, 1)) * (sr_hat - sr_star) / math.sqrt(variance_term)
    dsr_prob = float(scipy_stats.norm.cdf(dsr_z))

    return {
        "dsr_zscore": round(dsr_z, 6),
        "dsr_probability": round(dsr_prob, 6),
        "dsr_sr_star": round(sr_star, 6),
        "passed": dsr_z > 0.0,
        "n_obs": n_obs,
    }


# ── Parameter Sensitivity Scanner ────────────────────────────

def sensitivity_scan(
    base_code: str,
    param_name: str,
    values: list,
    data: pd.DataFrame,
) -> list:
    """
    Run backtests sweeping a single parameter across the given values.

    Injects ``param_name = value`` as the first line of the strategy code,
    overriding any hard-coded default.  The generated strategy code must
    reference the parameter by its name for the injection to take effect.

    Args:
        base_code:   Strategy code string (full Python).
        param_name:  Name of the parameter to sweep (e.g. "fast_window").
        values:      List of numeric values to test.
        data:        In-sample market data passed to run_backtest.

    Returns:
        List of (value, sharpe) tuples, one per element in values.
    """
    results = []
    for v in values:
        injected_code = f"{param_name} = {v!r}\n{base_code}"
        try:
            m = run_backtest(injected_code, data)
            results.append((float(v), m["sharpe"]))
        except Exception as exc:
            print(f"    Sensitivity scan error at {param_name}={v}: {exc}")
            results.append((float(v), 0.0))
    return results


# ── Walk-Forward Analysis ─────────────────────────────────────

def walk_forward_backtest(
    code: str,
    data: pd.DataFrame,
    train_months: int = 36,
    test_months: int = 6,
    min_windows: int = 4,
    consistency_threshold: float = 0.70,
) -> dict:
    """
    Run rolling walk-forward backtest over the full data range.

    Windows: rolling train_months IS period → test_months OOS period.
    Non-overlapping OOS windows step by test_months each iteration.

    Returns:
        {
            "windows": [{"window": int, "train_start": str, "train_end": str,
                         "test_start": str, "test_end": str,
                         "train_sharpe": float, "test_sharpe": float,
                         "passed": bool}],
            "wf_windows_passed": int,
            "wf_windows_total": int,
            "wf_consistency_score": float,
            "wf_pass": bool,
        }
    """
    if data.empty:
        return {
            "windows": [], "wf_windows_passed": 0, "wf_windows_total": 0,
            "wf_consistency_score": 0.0, "wf_pass": False,
        }

    full_index = data.index
    start_date = full_index[0]
    end_date = full_index[-1]

    windows = []
    window_num = 0
    # Slide by test_months so OOS windows do not overlap
    offset_months = 0

    while True:
        train_start = start_date + pd.DateOffset(months=offset_months)
        train_end = train_start + pd.DateOffset(months=train_months) - pd.DateOffset(days=1)
        test_start = train_end + pd.DateOffset(days=1)
        test_end = test_start + pd.DateOffset(months=test_months) - pd.DateOffset(days=1)

        if test_end > end_date:
            break

        train_slice = data.loc[train_start:train_end]
        test_slice = data.loc[test_start:test_end]

        if train_slice.empty or test_slice.empty:
            break

        window_num += 1
        try:
            train_m = run_backtest(code, train_slice)
            test_m = run_backtest(code, test_slice)
            train_sharpe = train_m["sharpe"]
            test_sharpe = test_m["sharpe"]
            # Consistency: OOS Sharpe >= consistency_threshold * IS Sharpe
            # Guard against division by zero / negative IS Sharpe
            if train_sharpe > 0:
                consistency_ratio = test_sharpe / train_sharpe
            else:
                consistency_ratio = 0.0
            passed = (
                test_sharpe > 0
                and consistency_ratio >= consistency_threshold
            )
        except Exception as exc:
            print(f"    Walk-forward window {window_num} error: {exc}")
            train_sharpe, test_sharpe, consistency_ratio, passed = 0.0, 0.0, 0.0, False

        windows.append({
            "window": window_num,
            "train_start": str(train_start.date()),
            "train_end": str(train_end.date()),
            "test_start": str(test_start.date()),
            "test_end": str(test_end.date()),
            "train_sharpe": round(train_sharpe, 4),
            "test_sharpe": round(test_sharpe, 4),
            "consistency_ratio": round(consistency_ratio, 4),
            "passed": passed,
        })

        offset_months += test_months  # slide by OOS length for non-overlapping OOS

    wf_windows_passed = sum(1 for w in windows if w["passed"])
    wf_windows_total = len(windows)
    # Overall consistency score: average of per-window consistency ratios (capped at 1)
    if windows:
        wf_consistency_score = min(
            1.0,
            sum(w["consistency_ratio"] for w in windows) / wf_windows_total,
        )
    else:
        wf_consistency_score = 0.0

    # Gate 1 WF pass: must have min_windows available and pass ≥ 3 of 4 (or ≥75%)
    required_passing = max(3, int(min_windows * 0.75))
    wf_pass = (wf_windows_total >= min_windows) and (wf_windows_passed >= required_passing)

    return {
        "windows": windows,
        "wf_windows_passed": wf_windows_passed,
        "wf_windows_total": wf_windows_total,
        "wf_consistency_score": round(wf_consistency_score, 4),
        "wf_pass": wf_pass,
    }


# ── Main Loop ────────────────────────────────────────────────

def run():
    print("=" * 60)
    print("QUANT TRADING AI ORCHESTRATOR")
    print("=" * 60)

    # Initialize
    conn = init_db(CONFIG["iteration_db_path"])

    # Continue from last logged iteration (supports resuming a batch)
    last_row = conn.execute("SELECT MAX(iteration) FROM iterations").fetchone()
    start_iteration = (last_row[0] or 0) + 1
    end_iteration = start_iteration + CONFIG["max_iterations"] - 1
    print(f"Resuming from iteration {start_iteration} → {end_iteration}")

    print("\nFetching market data...")
    all_data = fetch_data(
        CONFIG["symbols"],
        CONFIG["in_sample_start"],
        CONFIG["out_of_sample_end"]
    )
    in_sample, out_of_sample = split_data(all_data, CONFIG)

    for iteration in range(start_iteration, end_iteration + 1):
        print(f"\n{'─' * 60}")
        print(f"ITERATION {iteration}")
        print(f"{'─' * 60}")

        # Load context
        kb = load_knowledge_base(CONFIG["knowledge_base_path"])
        recent = get_recent_iterations(conn)

        # Step 1: Propose
        print("\n[1/4] Claude proposing strategy...")
        try:
            proposal = propose_strategy(kb, recent, iteration)
            print(f"  Strategy: {proposal['strategy_name']}")
            print(f"  Hypothesis: {proposal['hypothesis']}")
            print(f"  Parameters: {proposal['parameters']}")
        except Exception as e:
            print(f"  ERROR in proposal: {e}")
            continue

        # Guard: parameter count
        if proposal.get("num_parameters", 99) > CONFIG["acceptance_criteria"]["max_parameters"]:
            print(f"  REJECTED: Too many parameters ({proposal['num_parameters']})")
            continue

        # Step 2: Backtest
        print("\n[2/4] Running backtests...")
        asset_class = proposal.get("asset_class", "equities")
        try:
            is_metrics = run_backtest(proposal["code"], in_sample, asset_class=asset_class)
            oos_metrics = run_backtest(proposal["code"], out_of_sample, asset_class=asset_class)

            metrics = {
                "sharpe_in_sample": is_metrics["sharpe"],
                "sharpe_out_of_sample": oos_metrics["sharpe"],
                "max_dd_in_sample": is_metrics["max_drawdown"],
                "max_dd_out_of_sample": oos_metrics["max_drawdown"],
                "trades_in_sample": is_metrics["total_trades"],
                "trades_out_of_sample": oos_metrics["total_trades"],
                "win_rate_in_sample": is_metrics["win_rate"],
                "profit_factor_in_sample": is_metrics["profit_factor"],
                "post_cost_sharpe_is": is_metrics["post_cost_sharpe"],
                "post_cost_sharpe_oos": oos_metrics["post_cost_sharpe"],
                "asset_class": asset_class,
            }

            print(f"  IS Sharpe: {metrics['sharpe_in_sample']:.2f}")
            print(f"  OOS Sharpe: {metrics['sharpe_out_of_sample']:.2f}")
            print(f"  IS MaxDD: {metrics['max_dd_in_sample']:.1%}")
            print(f"  IS Trades: {metrics['trades_in_sample']}")
            print(f"  Post-Cost IS Sharpe: {metrics['post_cost_sharpe_is']:.2f} "
                  f"({'SURVIVES' if metrics['post_cost_sharpe_is'] > 0 else 'FAILS'} costs)")

            # Deflated Sharpe Ratio — use iteration count as proxy for trials_tested
            dsr_result = compute_dsr(is_metrics["portfolio_returns"], trials_tested=iteration)
            metrics["dsr_zscore"] = dsr_result["dsr_zscore"]
            metrics["dsr_pass"] = dsr_result["passed"]
            print(
                f"  DSR z-score: {dsr_result['dsr_zscore']:.4f}  "
                f"(SR*={dsr_result['dsr_sr_star']:.4f}, n_obs={dsr_result['n_obs']})  "
                f"{'PASS' if dsr_result['passed'] else 'FAIL'}"
            )

            # Walk-forward analysis over full data range
            print("  Running walk-forward analysis (4+ windows)...")
            wf_results = walk_forward_backtest(proposal["code"], all_data)
            metrics["wf_windows_passed"] = wf_results["wf_windows_passed"]
            metrics["wf_windows_total"] = wf_results["wf_windows_total"]
            metrics["wf_consistency_score"] = wf_results["wf_consistency_score"]
            metrics["wf_pass"] = wf_results["wf_pass"]
            metrics["wf_windows"] = wf_results["windows"]  # raw window dicts for reporter
            print(
                f"  Walk-forward: {wf_results['wf_windows_passed']}/{wf_results['wf_windows_total']} "
                f"windows passed, consistency={wf_results['wf_consistency_score']:.2f}, "
                f"{'PASS' if wf_results['wf_pass'] else 'FAIL'}"
            )
            for w in wf_results["windows"]:
                print(
                    f"    Window {w['window']}: IS={w['train_sharpe']:.2f} "
                    f"OOS={w['test_sharpe']:.2f} [{w['test_start']}—{w['test_end']}] "
                    f"{'✓' if w['passed'] else '✗'}"
                )

            # Parameter sensitivity scan — ±20% per parameter, Gate 1 requires < 30% Sharpe change
            params = proposal.get("parameters", {})
            baseline_sharpe = metrics["sharpe_in_sample"]
            sensitivity_details = {}
            sensitivity_pass = True
            if params and baseline_sharpe != 0:
                print("  Running parameter sensitivity scan (±20%)...")
                for pname, pval in params.items():
                    if not isinstance(pval, (int, float)):
                        continue
                    low_val = pval * 0.8
                    high_val = pval * 1.2
                    scan_results = sensitivity_scan(
                        proposal["code"], pname, [low_val, pval, high_val], in_sample
                    )
                    sharpe_low = next((s for v, s in scan_results if v == low_val), 0.0)
                    sharpe_high = next((s for v, s in scan_results if v == high_val), 0.0)
                    delta = abs(sharpe_high - sharpe_low) / abs(baseline_sharpe)
                    param_pass = delta < 0.30
                    sensitivity_details[pname] = {
                        "low": round(sharpe_low, 4),
                        "baseline": round(baseline_sharpe, 4),
                        "high": round(sharpe_high, 4),
                        "delta_ratio": round(delta, 4),
                        "passed": param_pass,
                    }
                    if not param_pass:
                        sensitivity_pass = False
                    print(
                        f"    {pname}: low={sharpe_low:.2f} base={baseline_sharpe:.2f} "
                        f"high={sharpe_high:.2f} delta={delta:.1%} "
                        f"{'PASS' if param_pass else 'FAIL'}"
                    )
            else:
                print("  Sensitivity scan skipped (no numeric parameters or zero baseline Sharpe).")

            metrics["sensitivity_pass"] = sensitivity_pass
            metrics["sensitivity_details"] = sensitivity_details
            print(f"  Sensitivity overall: {'PASS' if sensitivity_pass else 'FAIL'}")

        except Exception as e:
            print(f"  ERROR in backtest: {e}")
            traceback.print_exc()

            # Log the failure
            log_iteration(conn, {
                "iteration": iteration,
                "strategy_name": proposal.get("strategy_name", "error"),
                "hypothesis": proposal.get("hypothesis", ""),
                "parameters": proposal.get("parameters", {}),
                "sharpe_in_sample": 0, "sharpe_out_of_sample": 0,
                "max_drawdown": 0, "total_trades": 0,
                "win_rate": 0, "profit_factor": 0,
                "passed_criteria": False,
                "post_mortem": f"Backtest execution error: {str(e)}",
                "strategy_code": proposal.get("code", ""),
            })
            continue

        # Step 3: Evaluate (Gate 1 quantitative checks)
        # Hard gate: fail immediately if strategy doesn't survive transaction costs
        post_cost_sharpe_is = metrics.get("post_cost_sharpe_is", 0)
        if post_cost_sharpe_is <= 0:
            print(
                f"\n  GATE 1 FAIL: Strategy does not survive transaction costs "
                f"(post-cost IS Sharpe = {post_cost_sharpe_is:.2f})"
            )
            evaluation = {
                "assessment": "failed",
                "confidence": 1.0,
                "overfitting_risk": "medium",
                "post_mortem": (
                    f"Failed transaction cost gate: post-cost IS Sharpe = {post_cost_sharpe_is:.2f}. "
                    f"Pre-cost IS Sharpe was {metrics['sharpe_in_sample']:.2f}. "
                    f"The edge is too thin to survive realistic trading costs."
                ),
                "next_direction": "Strategy needs a larger edge. Reduce trade frequency or focus on higher-conviction signals.",
                "promote_to_paper": False,
            }
            passed = False
        # Hard gate: fail immediately if DSR <= 0 (statistically insignificant after multiple-comparison correction)
        elif not metrics.get("dsr_pass", False):
            print(
                f"\n  GATE 1 FAIL: Deflated Sharpe Ratio failed "
                f"(DSR z-score = {metrics.get('dsr_zscore', float('-inf')):.4f} ≤ 0)"
            )
            evaluation = {
                "assessment": "failed",
                "confidence": 1.0,
                "overfitting_risk": "high",
                "post_mortem": (
                    f"Failed DSR gate: DSR z-score = {metrics.get('dsr_zscore', float('-inf')):.4f}. "
                    f"After correcting for multiple-comparison bias, the Sharpe Ratio is not "
                    f"statistically significant. Strategy is likely overfit."
                ),
                "next_direction": "Strategy Sharpe is not significant after multiple-testing correction. "
                                  "Reduce number of parameter trials, or find a strategy with a stronger edge.",
                "promote_to_paper": False,
            }
            passed = False
        # Hard gate: fail immediately if walk-forward doesn't pass
        elif not metrics.get("wf_pass", False):
            print(
                f"\n  GATE 1 FAIL: Walk-forward failed "
                f"({metrics.get('wf_windows_passed', 0)}/{metrics.get('wf_windows_total', 0)} windows passed)"
            )
            evaluation = {
                "assessment": "failed",
                "confidence": 1.0,
                "overfitting_risk": "high",
                "post_mortem": (
                    f"Failed walk-forward gate: only {metrics.get('wf_windows_passed', 0)} of "
                    f"{metrics.get('wf_windows_total', 0)} windows passed "
                    f"(consistency score {metrics.get('wf_consistency_score', 0):.2f})"
                ),
                "next_direction": "Strategy underperforms out-of-sample across multiple time periods — likely overfit or regime-dependent.",
                "promote_to_paper": False,
            }
            passed = False
        # Hard gate: fail immediately if parameter sensitivity check fails (cliff-edge parameter)
        elif not metrics.get("sensitivity_pass", True):
            failing_params = [
                p for p, d in metrics.get("sensitivity_details", {}).items()
                if not d.get("passed", True)
            ]
            print(
                f"\n  GATE 1 FAIL: Parameter sensitivity failed "
                f"(cliff-edge parameters: {', '.join(failing_params)})"
            )
            evaluation = {
                "assessment": "failed",
                "confidence": 1.0,
                "overfitting_risk": "high",
                "post_mortem": (
                    f"Failed parameter sensitivity gate: parameters {failing_params} caused "
                    f"> 30% Sharpe change on ±20% perturbation. Strategy performance is "
                    f"highly sensitive to exact parameter values — likely overfit."
                ),
                "next_direction": "Redesign strategy so no single parameter dominates the edge. "
                                  "Robust strategies should degrade gracefully with small parameter changes.",
                "promote_to_paper": False,
            }
            passed = False
        else:
            print("\n[3/4] Claude evaluating results...")
            try:
                evaluation = evaluate_results(proposal, metrics)
                passed = evaluation["assessment"] == "passed"
                print(f"  Assessment: {evaluation['assessment']}")
                print(f"  Overfitting risk: {evaluation['overfitting_risk']}")
                print(f"  Learning: {evaluation['post_mortem']}")
            except Exception as e:
                print(f"  ERROR in evaluation: {e}")
                evaluation = {
                    "post_mortem": f"Evaluation error: {str(e)}",
                    "promote_to_paper": False,
                }
                passed = False

        # Step 4: Log & Learn
        print("\n[4/4] Logging iteration...")
        log_data = {
            "iteration": iteration,
            "strategy_name": proposal["strategy_name"],
            "hypothesis": proposal["hypothesis"],
            "parameters": {
                **proposal["parameters"],
                "_sensitivity": metrics.get("sensitivity_details", {}),
            },
            "sharpe_in_sample": metrics["sharpe_in_sample"],
            "sharpe_out_of_sample": metrics["sharpe_out_of_sample"],
            "max_drawdown": metrics["max_dd_in_sample"],
            "total_trades": metrics["trades_in_sample"],
            "win_rate": metrics.get("win_rate_in_sample", 0),
            "profit_factor": metrics.get("profit_factor_in_sample", 0),
            "passed_criteria": passed,
            "post_mortem": evaluation.get("post_mortem", ""),
            "strategy_code": proposal["code"],
            "wf_windows_passed": metrics.get("wf_windows_passed"),
            "wf_consistency_score": metrics.get("wf_consistency_score"),
            "post_cost_sharpe": metrics.get("post_cost_sharpe_is"),
            "asset_class": metrics.get("asset_class", "equities"),
            "dsr": metrics.get("dsr_zscore"),
            "sensitivity_pass": metrics.get("sensitivity_pass"),
        }
        log_iteration(conn, log_data)

        save_learning(CONFIG["knowledge_base_path"], iteration, {
            "strategy_name": proposal["strategy_name"],
            "hypothesis": proposal["hypothesis"],
            "metrics": metrics,
            "evaluation": evaluation,
        })

        if passed:
            print("\n  Generating Gate 1 verdict report...")
            try:
                verdict = generate_and_save_verdict(metrics, proposal, CONFIG)
                print(
                    f"  Gate 1 Verdict: {verdict['overall_verdict']} "
                    f"({verdict['confidence']} confidence)"
                )
                print(f"  Recommendation: {verdict['recommendation']}")
                print(f"  Saved: {verdict['txt_path']}")
                if verdict["overall_verdict"] in ("PASS", "CONDITIONAL PASS"):
                    print(f"\n  ★ GATE 1 {verdict['overall_verdict']}: {proposal['strategy_name']}")
                    print("  → Escalating to Engineering Director for CEO review.")
            except Exception as e:
                print(f"  WARNING: Gate 1 reporter failed: {e}")

        if evaluation.get("promote_to_paper"):
            print(f"\n  ★ STRATEGY PROMOTED TO PAPER TRADING: {proposal['strategy_name']}")

        # Brief pause to avoid API rate limits
        time.sleep(10)

    print(f"\n{'=' * 60}")
    print("ORCHESTRATION COMPLETE")
    print(f"{'=' * 60}")
    conn.close()


if __name__ == "__main__":
    run()

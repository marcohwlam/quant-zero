# Quant Trading AI Orchestrator

## Overview

A lightweight Python orchestrator that connects Claude to a backtesting engine in a continuous improvement loop. The system proposes strategies, tests them, analyzes results, and iterates — all driven by Claude's reasoning against a persistent knowledge base.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Orchestrator                    │
│                                                  │
│  ┌───────────┐   ┌───────────┐   ┌───────────┐  │
│  │  Claude    │──▶│ Backtest  │──▶│  Evaluate  │ │
│  │  Propose   │   │  Execute  │   │  & Learn   │ │
│  └───────────┘   └───────────┘   └───────────┘  │
│       ▲                               │          │
│       └───────────────────────────────┘          │
│                                                  │
│  ┌──────────────────────────────────────────┐    │
│  │         Knowledge Base (JSON/MD)         │    │
│  └──────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────┐    │
│  │         Iteration Log (SQLite)           │    │
│  └──────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

---

## Dependencies

```bash
pip install anthropic vectorbt yfinance pandas numpy sqlalchemy
```

---

## Core Orchestrator Code

```python
"""
quant_orchestrator.py
Minimal AI-driven strategy iteration loop.
"""

import json
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


# ── Configuration ────────────────────────────────────────────

CONFIG = {
    "model": "claude-sonnet-4-20250514",
    "max_iterations": 10,
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
    "knowledge_base_path": "knowledge_base/",
    "iteration_db_path": "iteration_log.db",
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
            strategy_code TEXT
        )
    """)
    conn.commit()
    return conn


def log_iteration(conn, data: dict):
    """Insert a row into the iteration log."""
    conn.execute("""
        INSERT INTO iterations 
        (timestamp, iteration, strategy_name, hypothesis, parameters,
         sharpe_in_sample, sharpe_out_of_sample, max_drawdown, 
         total_trades, win_rate, profit_factor,
         passed_criteria, post_mortem, strategy_code)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.datetime.now().isoformat(),
        data.get("iteration"),
        data.get("strategy_name"),
        data.get("hypothesis"),
        json.dumps(data.get("parameters", {})),
        data.get("sharpe_in_sample"),
        data.get("sharpe_out_of_sample"),
        data.get("max_drawdown"),
        data.get("total_trades"),
        data.get("win_rate"),
        data.get("profit_factor"),
        data.get("passed_criteria"),
        data.get("post_mortem"),
        data.get("strategy_code"),
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

OUTPUT FORMAT (respond ONLY with this JSON, no markdown fences):
{
  "strategy_name": "short_descriptive_name",
  "hypothesis": "Why this should work, grounded in market microstructure or behavior",
  "parameters": {"param1": value1, "param2": value2},
  "num_parameters": 3,
  "code": "# Full Python code that takes `data` (pd.DataFrame of OHLCV) and returns a vectorbt Portfolio object named `portfolio`",
  "rationale_vs_prior": "What changed from last iteration and why"
}"""


def propose_strategy(knowledge_base: str, recent_iterations: str, iteration: int) -> dict:
    """Ask Claude to propose a new or refined strategy."""
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
"""
    
    response = client.messages.create(
        model=CONFIG["model"],
        max_tokens=4096,
        system=PROPOSE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    
    text = response.content[0].text.strip()
    # Clean potential markdown fences
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


EVALUATE_SYSTEM_PROMPT = """You are a quantitative analyst evaluating backtest results.
Be rigorous about overfitting. Compare in-sample vs out-of-sample performance.
A large gap between IS and OOS Sharpe suggests overfitting.

OUTPUT FORMAT (respond ONLY with this JSON, no markdown fences):
{
  "assessment": "passed" or "failed",
  "confidence": 0.0-1.0,
  "overfitting_risk": "low" / "medium" / "high",
  "post_mortem": "What we learned from this iteration",
  "next_direction": "Specific suggestion for next iteration",
  "promote_to_paper": true/false
}"""


def evaluate_results(proposal: dict, metrics: dict) -> dict:
    """Ask Claude to evaluate backtest results and extract learnings."""
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

ACCEPTANCE CRITERIA:
- In-sample Sharpe >= {CONFIG['acceptance_criteria']['min_sharpe_in_sample']}
- Out-of-sample Sharpe >= {CONFIG['acceptance_criteria']['min_sharpe_out_of_sample']}
- Max drawdown >= {CONFIG['acceptance_criteria']['max_drawdown']}
- Minimum {CONFIG['acceptance_criteria']['min_trades']} trades
"""
    
    response = client.messages.create(
        model=CONFIG["model"],
        max_tokens=2048,
        system=EVALUATE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    
    text = response.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


# ── Backtest Execution ───────────────────────────────────────

def run_backtest(code: str, data: pd.DataFrame) -> dict:
    """Execute strategy code and extract metrics from the resulting portfolio."""
    local_vars = {"data": data, "pd": pd, "np": np, "vbt": vbt}
    
    exec(code, {}, local_vars)
    
    portfolio = local_vars.get("portfolio")
    if portfolio is None:
        raise ValueError("Strategy code did not produce a 'portfolio' variable.")
    
    stats = portfolio.stats()
    
    return {
        "sharpe": stats.get("Sharpe Ratio", 0),
        "max_drawdown": stats.get("Max Drawdown [%]", 0) / -100,
        "total_trades": stats.get("Total Trades", 0),
        "win_rate": stats.get("Win Rate [%]", 0) / 100,
        "profit_factor": stats.get("Profit Factor", 0),
        "total_return": stats.get("Total Return [%]", 0) / 100,
    }


# ── Main Loop ────────────────────────────────────────────────

def run():
    print("=" * 60)
    print("QUANT TRADING AI ORCHESTRATOR")
    print("=" * 60)
    
    # Initialize
    conn = init_db(CONFIG["iteration_db_path"])
    
    print("\nFetching market data...")
    all_data = fetch_data(
        CONFIG["symbols"],
        CONFIG["in_sample_start"],
        CONFIG["out_of_sample_end"]
    )
    in_sample, out_of_sample = split_data(all_data, CONFIG)
    
    for iteration in range(1, CONFIG["max_iterations"] + 1):
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
        try:
            is_metrics = run_backtest(proposal["code"], in_sample)
            oos_metrics = run_backtest(proposal["code"], out_of_sample)
            
            metrics = {
                "sharpe_in_sample": is_metrics["sharpe"],
                "sharpe_out_of_sample": oos_metrics["sharpe"],
                "max_dd_in_sample": is_metrics["max_drawdown"],
                "max_dd_out_of_sample": oos_metrics["max_drawdown"],
                "trades_in_sample": is_metrics["total_trades"],
                "trades_out_of_sample": oos_metrics["total_trades"],
                "win_rate_in_sample": is_metrics["win_rate"],
                "profit_factor_in_sample": is_metrics["profit_factor"],
            }
            
            print(f"  IS Sharpe: {metrics['sharpe_in_sample']:.2f}")
            print(f"  OOS Sharpe: {metrics['sharpe_out_of_sample']:.2f}")
            print(f"  IS MaxDD: {metrics['max_dd_in_sample']:.1%}")
            print(f"  IS Trades: {metrics['trades_in_sample']}")
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
        
        # Step 3: Evaluate
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
            "parameters": proposal["parameters"],
            "sharpe_in_sample": metrics["sharpe_in_sample"],
            "sharpe_out_of_sample": metrics["sharpe_out_of_sample"],
            "max_drawdown": metrics["max_dd_in_sample"],
            "total_trades": metrics["trades_in_sample"],
            "win_rate": metrics.get("win_rate_in_sample", 0),
            "profit_factor": metrics.get("profit_factor_in_sample", 0),
            "passed_criteria": passed,
            "post_mortem": evaluation.get("post_mortem", ""),
            "strategy_code": proposal["code"],
        }
        log_iteration(conn, log_data)
        
        save_learning(CONFIG["knowledge_base_path"], iteration, {
            "strategy_name": proposal["strategy_name"],
            "hypothesis": proposal["hypothesis"],
            "metrics": metrics,
            "evaluation": evaluation,
        })
        
        if evaluation.get("promote_to_paper"):
            print(f"\n  ★ STRATEGY PROMOTED TO PAPER TRADING: {proposal['strategy_name']}")
        
        # Brief pause to avoid API rate limits
        time.sleep(2)
    
    print(f"\n{'=' * 60}")
    print("ORCHESTRATION COMPLETE")
    print(f"{'=' * 60}")
    conn.close()


if __name__ == "__main__":
    run()
```

---

## Running the Orchestrator

```bash
# Set your API key
export ANTHROPIC_API_KEY="sk-ant-..."

# Seed the knowledge base first (see strategy_knowledge_base.md)
mkdir -p knowledge_base/

# Run
python quant_orchestrator.py
```

---

## Extending the Orchestrator

### Adding Broker Paper Trading (Alpaca Example)

```python
from alpaca_trade_api import REST

alpaca = REST(
    key_id="YOUR_KEY",
    secret_key="YOUR_SECRET",
    base_url="https://paper-api.alpaca.markets"  # Paper trading
)

def promote_to_paper(strategy_code: str, symbols: list):
    """Deploy a passing strategy to Alpaca paper trading."""
    # Parse strategy signals from the code
    # Submit orders via alpaca.submit_order()
    # Log deployment timestamp and parameters
    pass
```

### Adding Walk-Forward Analysis

```python
def walk_forward_backtest(code: str, data: pd.DataFrame, 
                          train_months=36, test_months=6):
    """Rolling walk-forward to detect overfitting."""
    results = []
    start = data.index[0]
    
    while start + pd.DateOffset(months=train_months + test_months) <= data.index[-1]:
        train_end = start + pd.DateOffset(months=train_months)
        test_end = train_end + pd.DateOffset(months=test_months)
        
        train_data = data.loc[start:train_end]
        test_data = data.loc[train_end:test_end]
        
        train_metrics = run_backtest(code, train_data)
        test_metrics = run_backtest(code, test_data)
        
        results.append({
            "window_start": str(start.date()),
            "train_sharpe": train_metrics["sharpe"],
            "test_sharpe": test_metrics["sharpe"],
            "degradation": train_metrics["sharpe"] - test_metrics["sharpe"],
        })
        
        start += pd.DateOffset(months=test_months)
    
    return pd.DataFrame(results)
```

### Parameter Sensitivity Scan

```python
def sensitivity_scan(base_code: str, param_name: str, 
                     values: list, data: pd.DataFrame):
    """Test how sensitive a strategy is to a single parameter."""
    results = []
    for val in values:
        modified_code = base_code.replace(
            f"{param_name} = ", f"{param_name} = {val}  # "
        )
        try:
            metrics = run_backtest(modified_code, data)
            results.append({"value": val, **metrics})
        except:
            results.append({"value": val, "sharpe": None})
    
    return pd.DataFrame(results)
```

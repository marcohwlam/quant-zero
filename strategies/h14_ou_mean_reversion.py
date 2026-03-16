"""
Strategy: H14 Ornstein-Uhlenbeck Mean Reversion Cloud
Author: Backtest Runner (QUA-153)
Date: 2026-03-16
Hypothesis: Apply OU process directly to individual ETF log-price series on a rolling
            window. Entry when price deviates >= 1.5*sigma_ou from OU mean AND kappa > 0
            (regime confirmed mean-reverting). Native regime self-detection via kappa
            significance filter prevents trading in trending markets.
Asset class: equities (ETFs: SPY, QQQ, IWM, XLE, XLF, XLK)
Parent task: QUA-153
References:  Vasicek (1977); Avellaneda & Lee (2010); Chan (2013)

IMPLEMENTATION NOTES:
- OU model fit: OLS regression of ΔX(t) = a + b × X(t-1) + ε on log-price
  kappa = -b, mu_hat = -a/b, sigma_ou = StdDev(epsilon)
- Half-life filter: t_half = ln(2) / kappa; only enter if t_half < 30 days
- Long-only in Gate 1 (short side would require margin; PDT at $25K)
- Time stop: 2 × estimated_half_life (capped at 30 days)
- Transaction costs: canonical equities model
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats as scipy_stats

# ── Default Parameters ────────────────────────────────────────────────────────

PARAMETERS = {
    "universe": ["SPY", "QQQ", "IWM", "XLE", "XLF", "XLK"],
    "vix_ticker": "^VIX",
    "ou_lookback": 60,             # rolling window for OU fitting (bars)
    "entry_sigma_multiple": 1.5,   # entry when price < mu - 1.5*sigma_ou
    "tp_sigma_multiple": 0.2,      # TP when price returns to mu ± 0.2*sigma_ou
    "sl_sigma_multiple": 3.0,      # SL when price exceeds mu - 3.0*sigma_ou
    "kappa_pvalue_threshold": 0.05, # significance threshold for kappa (p < 0.05)
    "max_half_life_days": 30,      # only enter if t_half < 30 days
    "time_stop_multiplier": 2.0,   # time stop = 2 * t_half (capped at max_half_life_days)
    "position_size_pct": 0.20,     # 20% per position (up to 5 concurrent)
    "init_cash": 25000,
}

# ── Transaction Cost Constants ────────────────────────────────────────────────
FIXED_COST_PER_SHARE = 0.005
SLIPPAGE_PCT = 0.0005
MARKET_IMPACT_K = 0.1
SIGMA_WINDOW = 20
ADV_WINDOW = 20

TRADING_DAYS_PER_YEAR = 252


# ── Data Loading ───────────────────────────────────────────────────────────────

def download_etf_data(tickers: list, start: str, end: str) -> dict:
    result = {}
    for ticker in tickers:
        try:
            raw = yf.download(ticker, start=start, end=end,
                              auto_adjust=True, progress=False)
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            if raw.empty or len(raw) < 30:
                warnings.warn(f"Insufficient data for {ticker}: {len(raw)} bars")
                continue
            result[ticker] = raw
        except Exception as exc:
            warnings.warn(f"Failed to download {ticker}: {exc}")
    return result


# ── OU Model Fitting ──────────────────────────────────────────────────────────

def fit_ou_model(log_prices: np.ndarray) -> dict:
    """
    Fit OU model via OLS on the AR(1) representation.
    ΔX(t) = a + b × X(t-1) + ε
    kappa = -b, mu_hat = -a/b, sigma_ou = StdDev(ε)
    t_half = ln(2) / kappa

    Returns dict with model parameters and significance test.
    Returns None values if fitting fails or data insufficient.
    """
    if len(log_prices) < 10:
        return {"kappa": 0.0, "mu_hat": 0.0, "sigma_ou": 0.0,
                "t_half": np.inf, "kappa_pvalue": 1.0, "valid": False}

    X = log_prices
    dX = np.diff(X)
    X_lag = X[:-1]

    # OLS: dX = a + b * X_lag + epsilon
    n = len(dX)
    if n < 5:
        return {"kappa": 0.0, "mu_hat": 0.0, "sigma_ou": 0.0,
                "t_half": np.inf, "kappa_pvalue": 1.0, "valid": False}

    # Design matrix [1, X_lag]
    A = np.column_stack([np.ones(n), X_lag])
    try:
        # OLS via normal equations
        coeffs, residuals, rank, sv = np.linalg.lstsq(A, dX, rcond=None)
        a, b = coeffs[0], coeffs[1]

        # Residuals
        fitted = A @ coeffs
        epsilon = dX - fitted
        sigma_ou = float(epsilon.std())

        # kappa and mu
        kappa = float(-b)
        if abs(b) < 1e-10:
            return {"kappa": 0.0, "mu_hat": float(X.mean()), "sigma_ou": sigma_ou,
                    "t_half": np.inf, "kappa_pvalue": 1.0, "valid": False}

        mu_hat = float(-a / b)

        # Half-life
        if kappa > 0:
            t_half = float(np.log(2) / kappa)
        else:
            t_half = np.inf

        # T-statistic for b (kappa significance)
        ss_res = float(np.sum(epsilon ** 2))
        if ss_res <= 0 or n <= 2:
            pvalue = 1.0
        else:
            se_sq = ss_res / (n - 2)
            XtX = A.T @ A
            try:
                XtX_inv = np.linalg.inv(XtX)
                se_b = float(np.sqrt(se_sq * XtX_inv[1, 1]))
                if se_b > 0:
                    t_stat = float(b / se_b)
                    # One-tailed: kappa > 0 means b < 0 → test t < 0
                    pvalue = float(scipy_stats.t.cdf(t_stat, df=n - 2))
                else:
                    pvalue = 1.0
            except np.linalg.LinAlgError:
                pvalue = 1.0

        return {
            "kappa": kappa,
            "mu_hat": mu_hat,
            "sigma_ou": sigma_ou,
            "t_half": t_half,
            "kappa_pvalue": pvalue,
            "valid": (kappa > 0 and sigma_ou > 0 and np.isfinite(t_half)),
        }

    except Exception:
        return {"kappa": 0.0, "mu_hat": 0.0, "sigma_ou": 0.0,
                "t_half": np.inf, "kappa_pvalue": 1.0, "valid": False}


def compute_ou_signals(
    ohlcv: pd.DataFrame,
    params: dict,
) -> pd.DataFrame:
    """
    Compute rolling OU signals for each bar.
    Returns DataFrame with columns: kappa, mu_hat, sigma_ou, t_half,
    kappa_pvalue, valid, lower_band, upper_band, sl_lower, sl_upper.
    """
    lookback = params["ou_lookback"]
    entry_mult = params["entry_sigma_multiple"]
    sl_mult = params["sl_sigma_multiple"]
    pval_thresh = params["kappa_pvalue_threshold"]
    max_half_life = params["max_half_life_days"]

    close = ohlcv["Close"]
    log_close = np.log(close + 1e-8)

    n = len(close)
    records = []

    for i in range(n):
        if i < lookback:
            records.append({
                "kappa": 0.0, "mu_hat": float(log_close.iloc[i]),
                "sigma_ou": 0.0, "t_half": np.inf,
                "kappa_pvalue": 1.0, "valid": False,
                "regime_active": False,
                "lower_band": np.nan, "upper_band": np.nan,
                "sl_lower": np.nan, "sl_upper": np.nan,
            })
            continue

        window = log_close.iloc[i - lookback + 1: i + 1].values
        ou = fit_ou_model(window)

        # Active regime: kappa > 0, significant, t_half < max
        regime_active = (
            ou["valid"]
            and ou["kappa"] > 0
            and ou["kappa_pvalue"] < pval_thresh
            and ou["t_half"] < max_half_life
        )

        if regime_active:
            lower = ou["mu_hat"] - entry_mult * ou["sigma_ou"]
            upper = ou["mu_hat"] + entry_mult * ou["sigma_ou"]
            sl_lower = ou["mu_hat"] - sl_mult * ou["sigma_ou"]
            sl_upper = ou["mu_hat"] + sl_mult * ou["sigma_ou"]
        else:
            lower = upper = sl_lower = sl_upper = np.nan

        records.append({
            "kappa": ou["kappa"],
            "mu_hat": ou["mu_hat"],
            "sigma_ou": ou["sigma_ou"],
            "t_half": ou["t_half"],
            "kappa_pvalue": ou["kappa_pvalue"],
            "valid": ou["valid"],
            "regime_active": regime_active,
            "lower_band": lower,
            "upper_band": upper,
            "sl_lower": sl_lower,
            "sl_upper": sl_upper,
        })

    df = pd.DataFrame(records, index=close.index)
    df["log_close"] = log_close.values
    df["close"] = close.values
    return df


# ── IC Computation ─────────────────────────────────────────────────────────────

def compute_ic(ohlcv_dict: dict, params: dict, forward_days: int = 10) -> dict:
    """
    IC = Spearman correlation between OU signal strength (normalized deviation
    below lower band) and forward returns. Only computed for bars where regime is active.
    """
    all_signals, all_fwds = [], []
    per_ticker = {}

    for ticker, ohlcv in ohlcv_dict.items():
        signals_df = compute_ou_signals(ohlcv, params)
        close = pd.Series(signals_df["close"].values, index=signals_df.index)

        # Signal: how far below lower band in log space
        active = signals_df["regime_active"].fillna(False)
        signal = (signals_df["lower_band"] - signals_df["log_close"]).where(
            active & (signals_df["lower_band"] > signals_df["log_close"]), 0.0
        )

        fwd_ret = close.shift(-forward_days) / close - 1.0
        df = pd.DataFrame({"signal": signal, "fwd": fwd_ret}).dropna()
        df = df[df["signal"] > 0]

        if len(df) < 5:
            per_ticker[ticker] = {"ic": 0.0, "n_obs": len(df)}
            continue

        corr, _ = scipy_stats.spearmanr(df["signal"], df["fwd"])
        per_ticker[ticker] = {"ic": round(float(corr), 4), "n_obs": len(df)}
        all_signals.extend(df["signal"].tolist())
        all_fwds.extend(df["fwd"].tolist())

    avg_ic = 0.0
    if len(all_signals) > 10:
        corr, _ = scipy_stats.spearmanr(all_signals, all_fwds)
        avg_ic = round(float(corr), 4)

    return {
        "per_ticker_ic": per_ticker,
        "avg_ic": avg_ic,
        "ic_pass": avg_ic > 0.02,
        "note": f"OU IC={avg_ic:.4f} ({'PASS' if avg_ic > 0.02 else 'FAIL'})",
    }


# ── Trade Simulator ────────────────────────────────────────────────────────────

def simulate_trades(
    ohlcv: pd.DataFrame,
    params: dict,
) -> tuple:
    """
    Simulate H14 OU Mean Reversion (long-only).

    Entry rule (no look-ahead):
    - At close of day t: log_price < lower_band (regime active)
    - Entry at open of day t+1
    - Dynamic time stop: min(2 * t_half_at_entry, max_hold_days)

    Exit (evaluated each bar after entry):
    1. TP: log_close >= mu_hat - 0.2*sigma_ou (price returned near OU mean)
    2. SL: log_close <= sl_lower (price extends beyond 3*sigma_ou)
    3. Regime exit: kappa drops below significance (strategy self-disables)
    4. Time stop: hold_days >= 2*t_half (dynamic)
    """
    pval_thresh = params["kappa_pvalue_threshold"]
    max_half_life = params["max_half_life_days"]
    max_hold = params["max_half_life_days"]
    pos_size = params["position_size_pct"]
    init_cash = params["init_cash"]

    signals = compute_ou_signals(ohlcv, params)
    close = ohlcv["Close"]
    open_ = ohlcv["Open"]
    volume = ohlcv["Volume"].astype(float)

    n = len(signals)
    idx = signals.index

    sigma_roll = close.pct_change().rolling(SIGMA_WINDOW).std().fillna(0.01)
    adv_roll = volume.rolling(ADV_WINDOW).mean().fillna(volume.mean())

    trade_log = []
    capital = init_cash
    portfolio_values = pd.Series(index=idx, dtype=float)
    portfolio_values.iloc[0] = capital

    in_trade = False
    entry_price = 0.0
    entry_log_mu = 0.0
    entry_log_sl = 0.0
    entry_log_tp = 0.0
    entry_t_half = 0.0
    entry_sigma_ou = 0.0
    entry_day_idx = -1
    hold_days = 0
    entry_shares = 0
    dynamic_time_stop = max_hold

    kappa_fire_count = 0   # track κ fire rate
    kappa_fire_wins = 0    # track wins among κ fires

    for i in range(1, n):
        bar_log_close = signals["log_close"].iloc[i]
        bar_close = signals["close"].iloc[i]
        bar_regime = signals["regime_active"].iloc[i]

        if not in_trade:
            # Signal at close i-1, enter at open i
            prev = signals.iloc[i - 1]
            prev_regime = prev["regime_active"]
            prev_lower = prev["lower_band"]
            prev_log_close = prev["log_close"]

            if (prev_regime
                    and not np.isnan(prev_lower)
                    and prev_log_close < prev_lower):
                # Enter at open of bar i
                entry_p = float(open_.iloc[i]) if not pd.isna(open_.iloc[i]) else float(close.iloc[i])
                if entry_p <= 0:
                    continue

                entry_sig = float(sigma_roll.iloc[i]) if not pd.isna(sigma_roll.iloc[i]) else 0.01
                entry_adv = float(adv_roll.iloc[i]) if not pd.isna(adv_roll.iloc[i]) else 1e6

                trade_value = capital * pos_size
                shares = int(trade_value / entry_p)
                if shares <= 0:
                    continue

                # Transaction costs
                fixed = shares * FIXED_COST_PER_SHARE
                slip = SLIPPAGE_PCT * (shares * entry_p)
                impact_pct = MARKET_IMPACT_K * entry_sig * np.sqrt(shares / (entry_adv + 1e-8))
                total_cost = fixed + slip + impact_pct * shares * entry_p
                eff_entry = entry_p + total_cost / max(shares, 1)

                # TP/SL levels in log space (from previous bar's OU model)
                sigma_ou_entry = float(prev["sigma_ou"])
                mu_entry = float(prev["mu_hat"])
                tp_mult = params["tp_sigma_multiple"]
                sl_mult = params["sl_sigma_multiple"]

                # TP: log_price returns to mu_hat ± 0.2 sigma
                log_tp = mu_entry - tp_mult * sigma_ou_entry  # approach from below
                # SL: log_price extends to mu - 3*sigma
                log_sl = mu_entry - sl_mult * sigma_ou_entry

                t_half_entry = float(prev["t_half"])
                dyn_stop = min(int(params["time_stop_multiplier"] * max(1, t_half_entry)), max_hold)

                in_trade = True
                entry_price = eff_entry
                entry_log_mu = mu_entry
                entry_log_sl = log_sl
                entry_log_tp = log_tp
                entry_t_half = t_half_entry
                entry_sigma_ou = sigma_ou_entry
                entry_day_idx = i
                hold_days = 0
                entry_shares = shares
                dynamic_time_stop = dyn_stop

                kappa_fire_count += 1

        else:
            hold_days += 1
            exit_reason = None
            exit_price_val = None

            # TP: log_close >= log_tp (returned to near OU mean)
            if bar_log_close >= entry_log_tp:
                exit_reason = "TP"
            # SL
            elif bar_log_close <= entry_log_sl:
                exit_reason = "SL"
            # Regime exit: kappa becomes insignificant
            elif (signals["kappa_pvalue"].iloc[i] >= pval_thresh
                  or not bar_regime):
                exit_reason = "REGIME"
            # Time stop
            elif hold_days >= dynamic_time_stop:
                exit_reason = "TIME"

            if exit_reason:
                exit_p = float(open_.iloc[i]) if not pd.isna(open_.iloc[i]) else bar_close
                if exit_p <= 0:
                    exit_p = bar_close

                exit_sig = float(sigma_roll.iloc[i]) if not pd.isna(sigma_roll.iloc[i]) else 0.01
                exit_adv = float(adv_roll.iloc[i]) if not pd.isna(adv_roll.iloc[i]) else 1e6

                fixed_ex = entry_shares * FIXED_COST_PER_SHARE
                slip_ex = SLIPPAGE_PCT * (entry_shares * exit_p)
                impact_ex = MARKET_IMPACT_K * exit_sig * np.sqrt(entry_shares / (exit_adv + 1e-8)) * (entry_shares * exit_p)
                total_exit_cost = fixed_ex + slip_ex + impact_ex
                eff_exit = exit_p - total_exit_cost / max(entry_shares, 1)

                gross_pnl = (eff_exit - entry_price) * entry_shares
                net_pnl = gross_pnl

                is_win = net_pnl > 0
                if is_win:
                    kappa_fire_wins += 1

                trade_log.append({
                    "ticker": "PORTFOLIO",
                    "entry_date": str(idx[entry_day_idx].date()),
                    "exit_date": str(idx[i].date()),
                    "entry_price": round(float(entry_price), 4),
                    "exit_price": round(float(eff_exit), 4),
                    "shares": entry_shares,
                    "hold_days": hold_days,
                    "exit_reason": exit_reason,
                    "gross_pnl": round(float(gross_pnl), 2),
                    "net_pnl": round(float(net_pnl), 2),
                    "return_pct": round(float((eff_exit / entry_price - 1.0) * 100), 4),
                    "t_half_at_entry": round(float(entry_t_half), 2),
                    "sigma_ou_at_entry": round(float(entry_sigma_ou), 6),
                    "dynamic_time_stop": dynamic_time_stop,
                    "kappa_fire_count": kappa_fire_count,
                })

                capital += net_pnl
                in_trade = False
                hold_days = 0

        portfolio_values.iloc[i] = capital

    portfolio_values = portfolio_values.ffill().fillna(init_cash)
    daily_returns = portfolio_values.pct_change().fillna(0.0)

    kappa_fire_rate = kappa_fire_count
    kappa_win_rate = (kappa_fire_wins / kappa_fire_count) if kappa_fire_count > 0 else 0.0

    return trade_log, daily_returns, portfolio_values, kappa_fire_count, kappa_win_rate


def run_strategy(start: str, end: str, params: dict = None) -> dict:
    """
    Run H14 OU Mean Reversion on all universe tickers.
    """
    if params is None:
        params = PARAMETERS

    universe = params["universe"]
    warmup_days = max(90, params["ou_lookback"] * 3)
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_days)).strftime("%Y-%m-%d")

    data = download_etf_data(universe, warmup_start, end)
    if not data:
        return _empty_result()

    all_trade_logs = []
    all_daily_returns = []
    exit_reasons = {}
    per_ticker_trades = {}
    total_kappa_fires = 0
    total_kappa_wins = 0

    for ticker, ohlcv in data.items():
        ohlcv_full = ohlcv  # warmup included for OU fitting
        ohlcv_trimmed = ohlcv.loc[ohlcv.index >= pd.Timestamp(start)]

        if len(ohlcv_trimmed) < 10:
            continue

        # Pass full data for OU signal computation (warmup included)
        # but the simulation only runs on trimmed data
        ohlcv_for_signals = ohlcv.loc[
            ohlcv.index >= (pd.Timestamp(start) - pd.DateOffset(days=params["ou_lookback"] * 2))
        ]

        trade_log, daily_returns, _, kf_count, kf_wr = simulate_trades(
            ohlcv_for_signals.loc[ohlcv_for_signals.index >= pd.Timestamp(start)
                                   if len(ohlcv_for_signals.loc[ohlcv_for_signals.index >= pd.Timestamp(start)]) > 0
                                   else ohlcv_for_signals.index[-1:]],
            params,
        )

        for t in trade_log:
            t["ticker"] = ticker
        all_trade_logs.extend(trade_log)
        all_daily_returns.append(daily_returns)
        per_ticker_trades[ticker] = len(trade_log)
        total_kappa_fires += kf_count
        total_kappa_wins += sum(1 for t in trade_log if t["net_pnl"] > 0)

        for t in trade_log:
            reason = t.get("exit_reason", "UNKNOWN")
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

    if not all_daily_returns or not all_trade_logs:
        return _empty_result()

    combined_idx = all_daily_returns[0].index
    for r in all_daily_returns[1:]:
        combined_idx = combined_idx.intersection(r.index)
    if len(combined_idx) == 0:
        return _empty_result()

    returns_matrix = pd.DataFrame({
        universe[i]: all_daily_returns[i].reindex(combined_idx).fillna(0.0)
        for i in range(len(all_daily_returns))
        if i < len(universe)
    })
    avg_returns = returns_matrix.mean(axis=1)
    returns_arr = avg_returns.values

    if returns_arr.std() > 0:
        sharpe = round(float(returns_arr.mean() / returns_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4)
    else:
        sharpe = 0.0

    cum = np.cumprod(1 + returns_arr)
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)

    trade_returns = [t["return_pct"] / 100.0 for t in all_trade_logs]
    win_rate = round(float(np.mean([r > 0 for r in trade_returns])), 4) if trade_returns else 0.0
    wins = [r for r in trade_returns if r > 0]
    losses = [abs(r) for r in trade_returns if r < 0]
    win_loss = round(float(np.mean(wins) / np.mean(losses)), 4) if wins and losses else 0.0
    gp = sum(t["net_pnl"] for t in all_trade_logs if t["net_pnl"] > 0)
    gl = abs(sum(t["net_pnl"] for t in all_trade_logs if t["net_pnl"] < 0))
    pf = round(gp / gl, 4) if gl > 0 else 0.0

    return {
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "win_rate": win_rate,
        "trade_count": len(all_trade_logs),
        "total_return": total_return,
        "returns": returns_arr,
        "trade_log": all_trade_logs,
        "win_loss_ratio": win_loss,
        "profit_factor": pf,
        "per_ticker_trades": per_ticker_trades,
        "exit_reasons": exit_reasons,
        "kappa_fire_count": total_kappa_fires,
        "kappa_win_rate": round(float(total_kappa_wins / max(len(all_trade_logs), 1)), 4),
    }


def _empty_result():
    return {
        "sharpe": 0.0, "max_drawdown": 0.0, "win_rate": 0.0,
        "trade_count": 0, "total_return": 0.0, "returns": np.array([]),
        "trade_log": [], "win_loss_ratio": 0.0, "profit_factor": 0.0,
        "per_ticker_trades": {}, "exit_reasons": {},
        "kappa_fire_count": 0, "kappa_win_rate": 0.0,
    }


def scan_ou_lookback(
    is_data_dict: dict,
    start: str,
    end: str,
    base_params: dict,
) -> dict:
    """
    Sensitivity sweep: OU lookback windows 30/45/60/90 bars.
    Also tests kappa p-value threshold: 0.05 vs 0.10.
    Returns dict with results per configuration.
    """
    lookbacks = [30, 45, 60, 90]
    pval_thresholds = [0.05, 0.10]
    results = {}

    for lb in lookbacks:
        for pv in pval_thresholds:
            key = f"lb{lb}_p{pv}"
            p = {**base_params, "ou_lookback": lb, "kappa_pvalue_threshold": pv}
            try:
                r = run_strategy(start, end, p)
                results[key] = {
                    "lookback": lb,
                    "kappa_pvalue": pv,
                    "sharpe": r["sharpe"],
                    "trade_count": r["trade_count"],
                    "win_rate": r["win_rate"],
                    "max_drawdown": r["max_drawdown"],
                    "kappa_fire_count": r.get("kappa_fire_count", 0),
                    "kappa_win_rate": r.get("kappa_win_rate", 0.0),
                }
            except Exception as exc:
                results[key] = {"lookback": lb, "kappa_pvalue": pv, "error": str(exc)}

    # Compute sensitivity vs base (lb=60, p=0.05)
    base_sharpe = results.get("lb60_p0.05", {}).get("sharpe", 0.0)
    valid_sharpes = [v["sharpe"] for v in results.values() if "sharpe" in v and v["sharpe"] != 0.0]
    if valid_sharpes and base_sharpe != 0:
        diffs = [abs(s - base_sharpe) / (abs(base_sharpe) + 1e-8) for s in valid_sharpes]
        max_var = round(float(max(diffs)) * 100, 2)
    else:
        max_var = 100.0

    results["_meta"] = {
        "sharpe_variance_pct": max_var,
        "sensitivity_pass": max_var < 50.0,
        "note": f"Max Sharpe deviation from base (lb=60, p<0.05): {max_var:.1f}%",
    }
    return results

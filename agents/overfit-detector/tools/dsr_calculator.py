"""
dsr_calculator.py
Deflated Sharpe Ratio (DSR) Calculator for Gate 1 Overfitting Detection

Implements the Deflated Sharpe Ratio from Bailey & López de Prado (2014).
Adjusts the observed Sharpe Ratio for multiple-comparison bias introduced
by testing many strategy variants.

Gate 1 threshold: DSR z-score > 0 required; ≤ 0 = auto-disqualify.

Usage:
    from dsr_calculator import compute_dsr, DSRResult

    result = compute_dsr(
        sr_hat=1.5,       # observed annualized Sharpe
        n_trials=20,      # number of strategy variants tested
        n_obs=1260,       # number of daily return observations
        skewness=-0.5,    # skewness of return series
        kurtosis=4.0,     # (excess) kurtosis of return series
    )
    print(result.passed)       # True / False
    print(result.dsr_zscore)   # z-score; > 0 required
    print(result.summary)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# ── Gate 1 threshold (from criteria.md, CEO-locked) ────────────────────────

DSR_ZSCORE_THRESHOLD = 0.0  # DSR z-score must be > 0; ≤ 0 = auto-disqualify


# ── Data class ──────────────────────────────────────────────────────────────

@dataclass
class DSRResult:
    """Result of the Deflated Sharpe Ratio calculation."""
    sr_hat: float          # observed annualized Sharpe Ratio
    sr_star: float         # expected max Sharpe under null (multiple-comparison adjusted)
    dsr_zscore: float      # DSR z-score; > 0 means SR_hat beats expected max by chance
    dsr_probability: float # Φ(dsr_zscore) ∈ [0, 1]; > 0.5 iff z-score > 0
    passed: bool           # True iff dsr_zscore > DSR_ZSCORE_THRESHOLD
    n_trials: int
    n_obs: int
    skewness: float
    kurtosis: float        # excess kurtosis (normal = 0)

    @property
    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"DSR: {status}  "
            f"z-score={self.dsr_zscore:.4f}, p={self.dsr_probability:.4f}, "
            f"SR_hat={self.sr_hat:.3f}, SR*={self.sr_star:.4f} "
            f"(n_trials={self.n_trials}, n_obs={self.n_obs})"
        )


# ── Math helpers ────────────────────────────────────────────────────────────

# Rational approximation for the standard normal CDF (Abramowitz & Stegun 26.2.17)
# Max error ≈ 7.5e-8 — sufficient for financial use.
_A1 = 0.319381530
_A2 = -0.356563782
_A3 = 1.781477937
_A4 = -1.821255978
_A5 = 1.330274429
_P = 0.2316419


def _norm_cdf(x: float) -> float:
    """Standard normal CDF, Φ(x)."""
    if math.isinf(x):
        return 1.0 if x > 0 else 0.0
    if math.isnan(x):
        return float("nan")

    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + _P * x)
    poly = t * (_A1 + t * (_A2 + t * (_A3 + t * (_A4 + t * _A5))))
    cdf = 1.0 - (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x * x) * poly
    return cdf if sign == 1 else 1.0 - cdf


def _norm_ppf(p: float) -> float:
    """
    Standard normal percent-point function (inverse CDF), Φ⁻¹(p).

    Uses the Beasley-Springer-Moro rational approximation.
    Clamps p to (1e-10, 1 - 1e-10) to avoid ±inf.
    """
    p = max(1e-10, min(1.0 - 1e-10, p))

    # Coefficients
    a = [2.50662823884, -18.61500062529, 41.39119773534, -25.44106049637]
    b = [-8.47351093090, 23.08336743743, -21.06224101826, 3.13082909833]
    c = [
        0.3374754822726147, 0.9761690190917186, 0.1607979714918209,
        0.0276438810333863, 0.0038405729373609, 0.0003951896511349,
        0.0000321767881768, 0.0000002888167364, 0.0000003960315187,
    ]

    q = p - 0.5
    if abs(q) <= 0.42:
        r = q * q
        num = q * (a[0] + r * (a[1] + r * (a[2] + r * a[3])))
        den = 1.0 + r * (b[0] + r * (b[1] + r * (b[2] + r * b[3])))
        return num / den

    r = math.sqrt(-math.log(p if q < 0 else 1.0 - p))
    result = (
        c[0] + r * (c[1] + r * (c[2] + r * (c[3] + r * (
            c[4] + r * (c[5] + r * (c[6] + r * (c[7] + r * c[8])))
        ))))
    )
    return -result if q < 0 else result


# ── DSR core calculation ────────────────────────────────────────────────────

# Euler-Mascheroni constant
_GAMMA_EM = 0.5772156649015328


def _expected_max_sharpe(n_trials: int, n_obs: int) -> float:
    """
    Compute SR* — the expected maximum Sharpe Ratio from n_trials independent
    strategies, each estimated on n_obs observations under the null hypothesis
    that all true Sharpes are zero.

    Formula (Bailey & López de Prado 2014, eq. 8):
        SR* = σ_SR × [(1 − γ) Φ⁻¹(1 − 1/N) + γ Φ⁻¹(1 − 1/(N·e))]

    where σ_SR ≈ 1/√(T−1) is the standard deviation of the IID Sharpe
    estimator under the null (no skew, Gaussian returns, annualization
    folded into the caller's SR_hat convention).

    Special case: n_trials = 1 → SR* = 0 (no correction needed).
    """
    if n_trials <= 1:
        return 0.0

    sigma_sr = 1.0 / math.sqrt(max(n_obs - 1, 1))
    term1 = (1.0 - _GAMMA_EM) * _norm_ppf(1.0 - 1.0 / n_trials)
    term2 = _GAMMA_EM * _norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    return sigma_sr * (term1 + term2)


def compute_dsr(
    sr_hat: float,
    n_trials: int,
    n_obs: int,
    skewness: float = 0.0,
    kurtosis: float = 0.0,
) -> DSRResult:
    """
    Compute the Deflated Sharpe Ratio (DSR) for a strategy.

    The DSR adjusts the observed Sharpe Ratio for:
    1. Non-normality of returns (via skewness/kurtosis correction)
    2. Multiple-comparison bias (via SR* from n_trials)

    Args:
        sr_hat:    Observed annualized Sharpe Ratio (pre-cost, same
                   annualization as the walk-forward evaluation).
        n_trials:  Number of independent strategy variants that were
                   tested/optimized before selecting this one.
                   Use 1 if no parameter search was performed.
                   Larger values → higher SR* → harder to pass.
        n_obs:     Number of return observations used to estimate SR_hat.
                   For daily data over 5 years ≈ 1260.
        skewness:  Skewness of the return series (γ₃ in the formula).
                   Negative skew (left-tail risk) makes the denominator
                   larger and DSR lower.  Default: 0.0 (Gaussian).
        kurtosis:  **Excess** kurtosis of the return series (γ₄ − 3 in
                   standard notation; 0.0 = normal distribution).
                   Fat tails increase denominator and lower DSR.
                   Default: 0.0 (Gaussian).

    Returns:
        DSRResult with z-score, probability, and PASS/FAIL.

    Raises:
        ValueError: If n_obs < 2 or n_trials < 1.

    Notes:
        - The formula uses excess kurtosis internally:
              denominator = √(1 − skew·SR + excess_kurtosis/4 · SR²)
          where excess_kurtosis = kurtosis parameter passed here.
        - DSR z-score > 0 ↔ SR_hat > SR* ↔ probability > 0.5.
        - The Gate 1 auto-disqualification threshold is DSR z-score ≤ 0.

    Example:
        result = compute_dsr(sr_hat=1.5, n_trials=20, n_obs=1260,
                             skewness=-0.3, kurtosis=1.0)
        assert result.passed  # z-score > 0
    """
    if n_obs < 2:
        raise ValueError(f"n_obs must be >= 2, got {n_obs}")
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")

    sr_star = _expected_max_sharpe(n_trials, n_obs)

    # Denominator variance correction for non-normality (PSR denominator)
    # Uses excess kurtosis: term is (γ₄ - 1) / 4 where γ₄ is total kurtosis
    # Our `kurtosis` parameter IS excess kurtosis, so total = kurtosis + 3
    # (γ₄ - 1) / 4 = (excess_kurtosis + 3 - 1) / 4 = (excess_kurtosis + 2) / 4
    excess_kurtosis = kurtosis  # caller passes excess kurtosis directly
    variance_term = 1.0 - skewness * sr_hat + ((excess_kurtosis + 2.0) / 4.0) * sr_hat ** 2

    # Guard against degenerate denominator (can happen with large kurtosis + large SR)
    if variance_term <= 0.0:
        variance_term = 1e-12

    denominator = math.sqrt(variance_term)

    # DSR z-score
    t_minus_1 = max(n_obs - 1, 1)
    numerator = math.sqrt(t_minus_1) * (sr_hat - sr_star)
    dsr_z = numerator / denominator

    dsr_prob = _norm_cdf(dsr_z)
    passed = dsr_z > DSR_ZSCORE_THRESHOLD

    return DSRResult(
        sr_hat=sr_hat,
        sr_star=sr_star,
        dsr_zscore=dsr_z,
        dsr_probability=dsr_prob,
        passed=passed,
        n_trials=n_trials,
        n_obs=n_obs,
        skewness=skewness,
        kurtosis=excess_kurtosis,
    )


# ── Unit tests (run via: python dsr_calculator.py) ─────────────────────────

def _run_tests() -> None:
    """Inline unit tests for DSR calculator."""
    import traceback
    passed_count = 0
    failed_count = 0

    def check(name: str, condition: bool, msg: str = "") -> None:
        nonlocal passed_count, failed_count
        if condition:
            print(f"  PASS  {name}")
            passed_count += 1
        else:
            print(f"  FAIL  {name}" + (f": {msg}" if msg else ""))
            failed_count += 1

    print("=== DSR Calculator Unit Tests ===\n")

    # ── Test 1: High SR, single trial → should pass easily
    r1 = compute_dsr(sr_hat=1.5, n_trials=1, n_obs=1260)
    check("T1 single trial z>0", r1.dsr_zscore > 0)
    check("T1 single trial passed", r1.passed)
    check("T1 SR* ~0 for single trial", abs(r1.sr_star) < 1e-6)
    check("T1 probability > 0.5", r1.dsr_probability > 0.5)
    print(f"  {r1.summary}\n")

    # ── Test 2: Low SR after many trials → may fail (SR* is inflated)
    r2 = compute_dsr(sr_hat=0.5, n_trials=100, n_obs=1260)
    check("T2 many trials reduces DSR", r2.dsr_zscore < r2.sr_hat * math.sqrt(1259))
    print(f"  {r2.summary}\n")

    # ── Test 3: High SR survives many trials
    r3 = compute_dsr(sr_hat=2.0, n_trials=50, n_obs=1260)
    check("T3 high SR survives 50 trials", r3.passed)
    print(f"  {r3.summary}\n")

    # ── Test 4: Non-normality lowers DSR
    r4_normal = compute_dsr(sr_hat=1.5, n_trials=10, n_obs=1260, skewness=0.0, kurtosis=0.0)
    r4_fat    = compute_dsr(sr_hat=1.5, n_trials=10, n_obs=1260, skewness=-0.5, kurtosis=2.0)
    check("T4 negative skew + fat tail lowers DSR", r4_fat.dsr_zscore < r4_normal.dsr_zscore)
    print(f"  Normal: {r4_normal.summary}")
    print(f"  Fat:    {r4_fat.summary}\n")

    # ── Test 5: More observations increase DSR
    r5_short = compute_dsr(sr_hat=1.2, n_trials=10, n_obs=250)
    r5_long  = compute_dsr(sr_hat=1.2, n_trials=10, n_obs=1260)
    check("T5 more obs → higher DSR", r5_long.dsr_zscore > r5_short.dsr_zscore)
    print(f"  Short: {r5_short.summary}")
    print(f"  Long:  {r5_long.summary}\n")

    # ── Test 6: n_obs < 2 raises ValueError
    try:
        compute_dsr(sr_hat=1.0, n_trials=1, n_obs=1)
        check("T6 n_obs<2 raises ValueError", False, "expected ValueError")
    except ValueError:
        check("T6 n_obs<2 raises ValueError", True)

    # ── Test 7: n_trials < 1 raises ValueError
    try:
        compute_dsr(sr_hat=1.0, n_trials=0, n_obs=100)
        check("T7 n_trials<1 raises ValueError", False, "expected ValueError")
    except ValueError:
        check("T7 n_trials<1 raises ValueError", True)

    # ── Test 8: SR_hat equal to SR* → z-score ~0, borderline
    # Construct SR_hat ≈ SR* exactly
    sr_star_approx = _expected_max_sharpe(n_trials=10, n_obs=1260)
    r8 = compute_dsr(sr_hat=sr_star_approx, n_trials=10, n_obs=1260)
    check("T8 SR_hat == SR* → z-score ~0", abs(r8.dsr_zscore) < 0.01,
          f"z={r8.dsr_zscore:.4f}")
    print(f"  {r8.summary}\n")

    # ── Summary
    print(f"\n{'='*40}")
    print(f"Results: {passed_count} passed, {failed_count} failed")
    if failed_count > 0:
        raise AssertionError(f"{failed_count} test(s) failed")
    print("All tests passed.")


if __name__ == "__main__":
    _run_tests()

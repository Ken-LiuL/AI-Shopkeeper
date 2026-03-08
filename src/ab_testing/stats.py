"""统计显著性检验 — 纯标准库实现，无 scipy 依赖。"""

from __future__ import annotations

import math
import statistics
from typing import Sequence


# ──────────────────────────────────────────────────────────────
# 内部工具
# ──────────────────────────────────────────────────────────────

def _t_distribution_cdf(t: float, df: float) -> float:
    """Student's t 分布的 CDF（双尾 p-value 的一半）。
    
    使用正则化不完全贝塔函数的级数展开近似。
    对于 df > 2 的情况精度较好（适合常见样本量）。
    """
    if df <= 0:
        raise ValueError("Degrees of freedom must be positive.")
    x = df / (df + t * t)
    # 正则化不完全 beta 函数 I_x(df/2, 1/2)
    p = _regularized_incomplete_beta(x, df / 2.0, 0.5)
    return p / 2.0  # 单尾


def _regularized_incomplete_beta(x: float, a: float, b: float, max_iter: int = 200) -> float:
    """正则化不完全贝塔函数 I_x(a, b) 的连分数展开近似（Lentz 算法）。"""
    if x < 0 or x > 1:
        raise ValueError("x must be in [0, 1].")
    if x == 0:
        return 0.0
    if x == 1:
        return 1.0

    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a

    # 连分数展开（Continued Fraction, modified Lentz）
    def _cf() -> float:
        tiny = 1e-30
        f = tiny
        C = f
        D = 0.0
        for m in range(0, max_iter):
            for i in range(2):
                if i == 0:
                    if m == 0:
                        d = 1.0
                    else:
                        d = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
                else:
                    d = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
                D = 1.0 + d * D
                if abs(D) < tiny:
                    D = tiny
                D = 1.0 / D
                C = 1.0 + d / C
                if abs(C) < tiny:
                    C = tiny
                f *= C * D
                if abs(C * D - 1.0) < 1e-10:
                    return f
        return f

    return front * _cf()


def _normal_cdf(z: float) -> float:
    """标准正态分布 CDF。"""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _normal_ppf(p: float) -> float:
    """标准正态分布分位数（近似，Beasley-Springer-Moro 算法）。"""
    # Rational approximation (Abramowitz and Stegun 26.2.17)
    a = [0, -3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [0, -5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
          4.374664141464968e+00,  2.938163982698783e+00]
    d = [7.784695709041462e-03,  3.224671290700398e-01,
          2.445134137142996e+00,  3.754408661907416e+00]

    p_low = 0.02425
    p_high = 1 - p_low

    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[1] * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * r + a[6]) * q / \
               (((((b[1] * r + b[2]) * r + b[3]) * r + b[4]) * r + b[5]) * r + 1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


# ──────────────────────────────────────────────────────────────
# 公开 API
# ──────────────────────────────────────────────────────────────

def t_test(
    control_values: Sequence[float],
    treatment_values: Sequence[float],
    alpha: float = 0.05,
) -> tuple[float, bool]:
    """独立样本双尾 t 检验（Welch's）。

    Returns:
        (p_value, significant)
    """
    n1, n2 = len(control_values), len(treatment_values)
    if n1 < 2 or n2 < 2:
        return 1.0, False

    mean1 = statistics.mean(control_values)
    mean2 = statistics.mean(treatment_values)
    var1 = statistics.variance(control_values)
    var2 = statistics.variance(treatment_values)

    se = math.sqrt(var1 / n1 + var2 / n2)
    if se == 0:
        return 1.0, False

    t_stat = (mean1 - mean2) / se

    # Welch–Satterthwaite 自由度
    num = (var1 / n1 + var2 / n2) ** 2
    den = (var1 / n1) ** 2 / (n1 - 1) + (var2 / n2) ** 2 / (n2 - 1)
    df = num / den if den > 0 else n1 + n2 - 2

    # 双尾 p-value
    p_one_tail = _t_distribution_cdf(abs(t_stat), df)
    p_value = min(2.0 * p_one_tail, 1.0)

    return p_value, p_value < alpha


def chi_square_test(
    control_counts: Sequence[int],
    treatment_counts: Sequence[int],
    alpha: float = 0.05,
) -> tuple[float, bool]:
    """卡方检验（2×k 列联表）。

    Args:
        control_counts:   对照组各类别计数，如 [成功数, 失败数]
        treatment_counts: 实验组各类别计数

    Returns:
        (p_value, significant)
    """
    if len(control_counts) != len(treatment_counts):
        raise ValueError("control_counts and treatment_counts must have same length.")

    k = len(control_counts)
    n1 = sum(control_counts)
    n2 = sum(treatment_counts)
    n_total = n1 + n2

    if n1 == 0 or n2 == 0:
        return 1.0, False

    chi2 = 0.0
    for i in range(k):
        col_total = control_counts[i] + treatment_counts[i]
        exp1 = n1 * col_total / n_total
        exp2 = n2 * col_total / n_total
        if exp1 > 0:
            chi2 += (control_counts[i] - exp1) ** 2 / exp1
        if exp2 > 0:
            chi2 += (treatment_counts[i] - exp2) ** 2 / exp2

    df = k - 1
    if df <= 0:
        return 1.0, False

    # 卡方分布的生存函数（SF = 1 - CDF）用不完全 Gamma 函数近似
    p_value = _chi2_sf(chi2, df)
    return p_value, p_value < alpha


def _chi2_sf(chi2: float, df: int) -> float:
    """卡方分布生存函数（1 - CDF）。"""
    if chi2 <= 0:
        return 1.0
    # chi2 分布 = Gamma(df/2, 2)，SFusingregularized upper incomplete gamma
    return _upper_incomplete_gamma_regularized(df / 2.0, chi2 / 2.0)


def _upper_incomplete_gamma_regularized(a: float, x: float) -> float:
    """正则化上不完全 Gamma 函数 Q(a, x) = 1 - P(a, x)。"""
    if x < 0:
        return 1.0
    if x == 0:
        return 1.0
    # 级数展开 P(a, x)（当 x < a+1 时收敛快）
    if x < a + 1:
        return 1.0 - _gamma_series(a, x)
    else:
        return _gamma_continued_fraction(a, x)


def _gamma_series(a: float, x: float, max_iter: int = 300) -> float:
    """正则化下不完全 Gamma 函数 P(a,x) 的级数展开。"""
    if x <= 0:
        return 0.0
    ap = a
    delta = 1.0 / a
    total = delta
    for _ in range(max_iter):
        ap += 1
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * 1e-12:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_continued_fraction(a: float, x: float, max_iter: int = 300) -> float:
    """正则化上不完全 Gamma 函数 Q(a,x) 的连分数展开。"""
    tiny = 1e-30
    b = x + 1.0 - a
    C = 1.0 / tiny
    D = 1.0 / b
    f = D
    for i in range(1, max_iter + 1):
        an = -i * (i - a)
        b += 2.0
        D = an * D + b
        if abs(D) < tiny:
            D = tiny
        C = b + an / C
        if abs(C) < tiny:
            C = tiny
        D = 1.0 / D
        delta = D * C
        f *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * f


def calculate_confidence_interval(
    values: Sequence[float],
    confidence: float = 0.95,
) -> tuple[float, float]:
    """计算置信区间（t 分布）。

    Returns:
        (lower, upper)
    """
    n = len(values)
    if n < 2:
        m = values[0] if n == 1 else 0.0
        return m, m

    mean = statistics.mean(values)
    se = statistics.stdev(values) / math.sqrt(n)

    alpha = 1.0 - confidence
    # t 临界值（用正态近似，df 较大时误差可忽略；精确版本需 t_ppf）
    # 对于 df > 30，t ≈ z；使用正态分位数作为保守近似
    if n > 30:
        z = _normal_ppf(1 - alpha / 2)
    else:
        # 用 Brent 方法对 t CDF 求逆（简化版：二分法）
        z = _t_ppf(1 - alpha / 2, df=n - 1)

    margin = z * se
    return mean - margin, mean + margin


def _t_ppf(p: float, df: float) -> float:
    """t 分布分位数函数（二分法求根）。"""
    lo, hi = 0.0, 1e6
    for _ in range(100):
        mid = (lo + hi) / 2
        cdf_val = 1.0 - _t_distribution_cdf(mid, df)  # 上尾
        # 我们需要找 t 使得 P(T ≤ t) = p，即上尾 = 1-p
        target_tail = 1.0 - p
        if cdf_val > target_tail:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-10:
            break
    return (lo + hi) / 2


def calculate_sample_size(
    baseline_rate: float,
    mde: float,
    alpha: float = 0.05,
    power: float = 0.8,
) -> int:
    """计算所需样本量（两组比例检验）。

    Args:
        baseline_rate: 对照组基线转化率（0~1）
        mde:           最小可检测效应（绝对值，如 0.02 代表 2 个百分点）
        alpha:         显著性水平（默认 0.05）
        power:         统计功效（默认 0.8）

    Returns:
        每组所需样本量 n（向上取整）
    """
    p1 = baseline_rate
    p2 = baseline_rate + mde

    # z 分位数
    z_alpha = _normal_ppf(1 - alpha / 2)
    z_beta = _normal_ppf(power)

    # 标准公式：n = (z_alpha * sqrt(2*p_bar*(1-p_bar)) + z_beta * sqrt(p1*(1-p1)+p2*(1-p2)))^2 / mde^2
    p_bar = (p1 + p2) / 2
    numerator = (
        z_alpha * math.sqrt(2 * p_bar * (1 - p_bar))
        + z_beta * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    ) ** 2
    denominator = mde ** 2
    n = numerator / denominator

    return math.ceil(n)

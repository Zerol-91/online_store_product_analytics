"""User-clustered delta-method intervals for episode conversion ratios."""

import numpy as np
from scipy.stats import norm


def _arrays(conversions, episodes):
    y, n = np.asarray(conversions, dtype=float), np.asarray(episodes, dtype=float)
    if y.shape != n.shape or y.ndim != 1 or not np.all(np.isfinite(y)) or not np.all(np.isfinite(n)):
        raise ValueError("Counts must be equal-length finite vectors.")
    if np.any(n < 0) or np.any(y < 0) or np.any(y > n) or np.any(n != np.floor(n)) or np.any(y != np.floor(y)):
        raise ValueError("Require integer counts with 0 <= conversions <= episodes.")
    return y, n


def _interval(estimate, influence, alpha):
    clusters = len(influence)
    if clusters < 2:
        return {"standard_error": None, "ci_low": None, "ci_high": None, "p_value": None,
                "inference_status": "insufficient_clusters"}
    variance = clusters / (clusters - 1) * float(influence @ influence)
    if variance <= 0:
        return {"standard_error": 0.0, "ci_low": None, "ci_high": None, "p_value": None,
                "inference_status": "degenerate_variance"}
    se = variance ** 0.5
    critical = norm.ppf(1 - alpha / 2)
    return {"standard_error": se, "ci_low": estimate - critical * se,
            "ci_high": estimate + critical * se,
            "p_value": float(2 * norm.sf(abs(estimate / se))), "inference_status": "estimated"}


def cluster_rate(conversions, episodes, alpha=0.05):
    if not 0 < alpha < 1:
        raise ValueError("Use alpha between zero and one.")
    y, n = _arrays(conversions, episodes)
    selected = n > 0
    y, n = y[selected], n[selected]
    total = float(n.sum())
    estimate = float(y.sum() / total) if total else None
    result = {"estimate": estimate, "clusters": len(n), "episodes": int(total),
              "conversions": int(y.sum()), "confidence_level": 1 - alpha,
              "max_cluster_episode_share": float(n.max() / total) if total else None}
    if not total:
        return result | {"standard_error": None, "ci_low": None, "ci_high": None,
                         "inference_status": "no_observations"}
    interval = _interval(estimate, (y - estimate * n) / total, alpha)
    interval.pop("p_value")
    return result | interval


def cluster_difference(y_a, n_a, y_b, n_b, alpha=0.05, family_size=2):
    y_a, n_a = _arrays(y_a, n_a)
    y_b, n_b = _arrays(y_b, n_b)
    if y_a.shape != y_b.shape or not 0 < alpha < 1 or family_size < 1:
        raise ValueError("Use aligned users, valid alpha, and a positive family size.")
    selected = n_a + n_b > 0
    y_a, n_a, y_b, n_b = (v[selected] for v in (y_a, n_a, y_b, n_b))
    total_a, total_b = float(n_a.sum()), float(n_b.sum())
    if not total_a or not total_b:
        return {"estimate": None, "clusters": len(n_a), "standard_error": None,
                "ci_low": None, "ci_high": None, "p_value": None, "adjusted_p_value": None,
                "confidence_level": 1 - alpha / family_size, "inference_status": "missing_group"}
    rate_a, rate_b = float(y_a.sum() / total_a), float(y_b.sum() / total_b)
    influence = (y_b - rate_b * n_b) / total_b - (y_a - rate_a * n_a) / total_a
    estimate = rate_b - rate_a
    interval = _interval(estimate, influence, alpha / family_size)
    return {"estimate": estimate, "clusters": len(n_a), "rate_a": rate_a, "rate_b": rate_b,
            "confidence_level": 1 - alpha / family_size,
            "adjusted_p_value": min(1.0, family_size * interval["p_value"]) if interval["p_value"] is not None else None,
            **interval}


def analyze_segments(connection, alpha=0.05, family_size=2):
    points = []
    for family, segment in connection.execute("SELECT family, segment FROM cart_segment_summary ORDER BY family, segment").fetchall():
        values = connection.execute("SELECT conversions, episodes FROM cart_segment_users WHERE family=? AND segment=?", [family, segment]).fetchnumpy()
        points.append({"family": family, "segment": segment,
                       **cluster_rate(values["conversions"], values["episodes"], alpha)})
    contrasts = []
    for family, a, b in (("visitor_type", "first_observed", "returning"), ("price_band", "low", "high")):
        values = connection.execute("""
            SELECT user_id,
                COALESCE(SUM(conversions) FILTER(WHERE segment=?),0)::BIGINT AS y_a,
                COALESCE(SUM(episodes) FILTER(WHERE segment=?),0)::BIGINT AS n_a,
                COALESCE(SUM(conversions) FILTER(WHERE segment=?),0)::BIGINT AS y_b,
                COALESCE(SUM(episodes) FILTER(WHERE segment=?),0)::BIGINT AS n_b
            FROM cart_segment_users WHERE family=? AND segment IN (?,?) GROUP BY user_id
        """, [a, a, b, b, family, a, b]).fetchnumpy()
        contrasts.append({"family": family, "group_a": a, "group_b": b,
                          **cluster_difference(values["y_a"], values["n_a"], values["y_b"], values["n_b"], alpha, family_size)})
    return {"estimates": points, "contrasts": contrasts,
            "method": "User-clustered ratio delta method; G/(G-1) correction; normal approximation; Bonferroni for two planned contrasts."}

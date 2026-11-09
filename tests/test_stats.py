"""Direct tests of app/core/stats.py on small inputs whose answers are known in advance."""
import math

import numpy as np
import pytest

from app.core import stats


def _constructed_sites(n_per_arm: int = 40, effect: float = 0.4):
    """Counts where treated sites change by exactly `effect` log points more than comparison sites.

    Counts are positive reals (the offset is added to both sides), so the log ratio is exact:
    comparison sites go 10 -> 10, treated sites go 10 -> (10.5 * e^effect - 0.5).
    """
    before = np.full(2 * n_per_arm, 10.0)
    treated = np.arange(2 * n_per_arm) < n_per_arm
    after = np.where(treated, (10.0 + stats.LOG_RATIO_OFFSET) * math.exp(effect) - stats.LOG_RATIO_OFFSET, 10.0)
    return before, after, treated


def test_percentile_ci_brackets_the_middle_of_known_samples():
    samples = np.arange(1, 1001, dtype=float)                   # 1..1000
    interval = stats.percentile_ci(samples, 0.95)
    assert interval["low"] == pytest.approx(np.percentile(samples, 2.5))
    assert interval["high"] == pytest.approx(np.percentile(samples, 97.5))
    assert interval["n_failed"] == 0
    wider, narrower = stats.percentile_ci(samples, 0.99), stats.percentile_ci(samples, 0.50)
    assert wider["low"] < interval["low"] < narrower["low"] < narrower["high"] < interval["high"] < wider["high"]


def test_percentile_ci_gives_nan_when_too_many_replicates_failed():
    samples = np.concatenate([np.full(20, np.nan), np.arange(80, dtype=float)])
    interval = stats.percentile_ci(samples)
    assert interval["n_failed"] == 20 and math.isnan(interval["low"]) and math.isnan(interval["high"])
    few_failed = stats.percentile_ci(np.concatenate([np.full(5, np.nan), np.arange(95, dtype=float)]))
    assert not math.isnan(few_failed["low"])


def test_bootstrap_p_value_known_cases():
    assert stats.bootstrap_p_value([]) != stats.bootstrap_p_value([])           # NaN for nothing to test
    assert stats.bootstrap_p_value([float("nan")]) != 0                         # still NaN, not an error
    all_positive = stats.bootstrap_p_value(np.linspace(1, 2, 999))
    assert all_positive == pytest.approx(2 * 1 / 1000)                          # the floor: never exactly zero
    straddling = stats.bootstrap_p_value(np.linspace(-1, 1, 1001))
    assert straddling == 1.0


def test_bootstrap_interval_covers_a_known_mean():
    rng = np.random.default_rng(7)
    sample = rng.normal(size=400)
    sample = 5.0 + 2.0 * (sample - sample.mean()) / sample.std()          # mean exactly 5
    result = stats.bootstrap_ci(lambda values: values.mean(), sample, n_boot=500)
    assert result["low"] < 5.0 < result["high"]
    assert result["estimate"] == pytest.approx(sample.mean())
    assert result["low"] < result["estimate"] < result["high"]
    assert result["n"] == 400 and result["n_clusters"] == 400 and result["n_failed"] == 0


def test_clustered_bootstrap_is_wider_than_row_bootstrap_for_correlated_rows():
    cluster_means = np.random.default_rng(3).normal(0, 3, size=20)
    values = np.repeat(cluster_means, 10) + np.random.default_rng(4).normal(0, 0.1, size=200)
    clusters = np.repeat(np.arange(20), 10)
    by_row = stats.bootstrap_ci(np.mean, values, n_boot=400)
    by_cluster = stats.bootstrap_ci(np.mean, values, clusters=clusters, n_boot=400)
    assert by_cluster["n_clusters"] == 20
    assert by_cluster["high"] - by_cluster["low"] > 2 * (by_row["high"] - by_row["low"])


def test_did_log_ratio_recovers_the_constructed_effect():
    before, after, treated = _constructed_sites(effect=0.4)
    result = stats.did_log_ratio(before, after, treated, n_boot=200)
    assert result["estimate"] == pytest.approx(0.4)
    assert result["percent_change"] == pytest.approx(100 * math.expm1(0.4))
    assert result["treated_change"] == pytest.approx(0.4) and result["control_change"] == pytest.approx(0.0)
    assert (result["n_treated"], result["n_control"], result["n_strata"]) == (40, 40, 1)
    assert result["n_treated_dropped"] == 0 and result["n_control_dropped"] == 0


def test_did_log_ratio_with_no_effect_is_zero():
    before, after, treated = _constructed_sites(effect=0.0)
    result = stats.did_log_ratio(before, after, treated, n_boot=100)
    assert result["estimate"] == pytest.approx(0.0, abs=1e-12) and result["percent_change"] == pytest.approx(0.0, abs=1e-9)


def test_a_stratum_with_no_comparison_is_dropped():
    # Stratum "a" has both arms (effect 0.4); stratum "b" has treated sites only and must not count.
    before = np.full(12, 10.0)
    treated = np.array([True] * 4 + [False] * 4 + [True] * 4)
    strata = np.array(["a"] * 8 + ["b"] * 4)
    after = np.where(treated, 10.5 * math.exp(0.4) - 0.5, 10.0)
    after[8:] = 10.5 * math.exp(5.0) - 0.5                       # an absurd change that would show if "b" leaked in
    result = stats.did_log_ratio(before, after, treated, strata=strata, n_boot=50)
    assert result["estimate"] == pytest.approx(0.4)
    assert (result["n_treated"], result["n_control"], result["n_strata"]) == (4, 4, 1)
    assert result["n_treated_dropped"] == 4 and result["n_control_dropped"] == 0


def test_stratified_difference_weights_strata_by_treated_counts():
    change = np.array([1.0, 0.0, 3.0, 0.0, 0.0])                  # stratum 0: treated 1.0 vs 0.0; stratum 1: 3.0 vs 0.0 and 0.0
    treated = np.array([True, False, True, False, False])
    codes = np.array([0, 0, 1, 1, 1])
    result = stats.stratified_difference(change, treated, codes, 2)
    assert result["estimate"] == pytest.approx(0.5 * 1.0 + 0.5 * 3.0)
    assert result["n_treated"] == 2 and result["n_control"] == 3 and result["n_strata"] == 2


def test_the_same_seed_gives_the_same_result_and_a_different_seed_does_not():
    before, after, treated = _constructed_sites()
    noisy = after + np.random.default_rng(1).normal(0, 1.0, size=after.size)
    first = stats.did_log_ratio(before, noisy, treated, n_boot=100, seed=5)
    again = stats.did_log_ratio(before, noisy, treated, n_boot=100, seed=5)
    other = stats.did_log_ratio(before, noisy, treated, n_boot=100, seed=6)
    assert (first["low"], first["high"], first["p_value"]) == (again["low"], again["high"], again["p_value"])
    assert (first["low"], first["high"]) != (other["low"], other["high"])
    assert first["estimate"] == other["estimate"]                  # the point estimate does not use the seed


def test_empty_and_degenerate_input_does_not_crash():
    nothing = np.array([], dtype=float)
    empty = stats.stratified_difference(nothing, np.array([], dtype=bool), np.array([], dtype=np.int64), 1)
    assert math.isnan(empty["estimate"]) and empty["n_treated"] == 0 and empty["n_strata"] == 0
    assert stats.log_ratio(nothing, nothing).size == 0
    assert math.isnan(stats.bootstrap_p_value(nothing))
    # Only treated sites: nothing to compare with, so the estimate and interval are NaN rather than an error.
    only_treated = stats.did_log_ratio(np.full(6, 5.0), np.full(6, 8.0), np.ones(6, dtype=bool), n_boot=20)
    assert math.isnan(only_treated["estimate"]) and math.isnan(only_treated["low"])
    assert only_treated["n_treated_dropped"] == 6


def test_log_ratio_and_percent_conversion():
    assert stats.log_ratio([0], [0])[0] == 0.0                     # zero crashes both times: no change, finite
    assert stats.log_ratio([0], [9.5])[0] == pytest.approx(math.log(20))
    assert stats.log_points_to_percent(math.log(2)) == pytest.approx(100.0)
    assert stats.log_points_to_percent(0.0) == 0.0


def test_spearman_and_mean_percentile_excess():
    assert stats.spearman_rho([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert stats.spearman_rho([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert stats.spearman_rho([1, 2, 3, 4, 5], [1, 4, 9, 16, 25]) == pytest.approx(1.0)   # monotone, not linear
    assert stats.mean_percentile_excess(np.array([60.0, 70.0])) == pytest.approx(15.0)


def test_type_contrast_recovers_two_constructed_effects():
    n = 30
    arm = np.repeat([0, 1, 2], n)
    before = np.full(3 * n, 10.0)
    effects = np.select([arm == 1, arm == 2], [0.3, 0.1], 0.0)
    after = 10.5 * np.exp(effects) - 0.5
    result = stats.type_contrast(before, after, arm, np.zeros(3 * n, dtype=int), None)
    assert result["first"]["percent_change"] == pytest.approx(100 * math.expm1(0.3))
    assert result["second"]["percent_change"] == pytest.approx(100 * math.expm1(0.1))
    assert result["first"]["n_treated"] == n and result["difference"]["n_treated"] == 2 * n
    assert result["difference"]["n_control"] == n

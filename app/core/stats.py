"""Shared statistics: cluster bootstrap, difference-in-differences and the event-study profile.

This file is the single home of this code. The notebook pastes it into Section 7 (see
pipeline/notebook/assemble.py) and the website imports it, so both compute every interval with the
same resampling scheme, seed and order of random draws. Pure numpy and pandas.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

# BEGIN SHARED CONSTANTS: the one definition. pipeline/notebook/assemble.py pastes this block into Section 1.
N_BOOT = 1000                 # bootstrap resamples behind every interval
CI_LEVEL = 0.95
SEED = 42                     # one seed, so every random step is repeatable
# END SHARED CONSTANTS
LOG_RATIO_OFFSET = 0.5        # crashes added to both counts, so a site with zero crashes keeps a finite ratio
MAX_FAILED_SHARE = 0.10       # no interval is reported when more replicates than this share fail
PERCENT = 100
PRE_PERIOD_INDEX = 100        # the mean of the pre-completion years is set to 100 in the event chart
NEUTRAL_PERCENTILE = 50       # mean percentile that sites would have if they were typical streets


def level_text(level: float) -> str:
    """An interval level as it is printed everywhere: 95%, 98.75%, 99.44%."""
    return f"{round(PERCENT * level, 2):g}%"


def percentile_ci(samples, level: float = CI_LEVEL) -> dict:
    """Percentile interval of bootstrap replicates (rows); NaN where too many replicates failed."""
    values = np.asarray(samples, dtype=float)
    n_failed = np.isnan(values).sum(axis=0)
    tail_pct = PERCENT * (1 - level) / 2
    with warnings.catch_warnings():          # an all-NaN column warns; its NaN is the wanted answer
        warnings.simplefilter("ignore", category=RuntimeWarning)
        low = np.nanpercentile(values, tail_pct, axis=0)
        high = np.nanpercentile(values, PERCENT - tail_pct, axis=0)
    too_many_failed = n_failed > MAX_FAILED_SHARE * values.shape[0]
    low, high = np.where(too_many_failed, np.nan, low), np.where(too_many_failed, np.nan, high)
    if values.ndim == 1:
        return {"low": float(low), "high": float(high), "n_failed": int(n_failed)}
    return {"low": low, "high": high, "n_failed": n_failed}


def bootstrap_p_value(replicates, null_value: float = 0.0) -> float:
    """Two-sided bootstrap p-value: twice the smaller share of replicates on either side of the null."""
    values = np.asarray(replicates, dtype=float)
    values = values[~np.isnan(values)]
    if values.size == 0:
        return float("nan")
    at_or_below = int((values <= null_value).sum())
    at_or_above = int((values >= null_value).sum())
    # One is added to count and total so the p-value is never exactly zero (floor about 2 / N_BOOT).
    return float(min(1.0, 2 * (min(at_or_below, at_or_above) + 1) / (values.size + 1)))


def cluster_layout(clusters, n_rows: int):
    """(order, starts, sizes): cluster j owns rows order[starts[j]:starts[j] + sizes[j]]."""
    if clusters is None:                     # every row is its own cluster
        return np.arange(n_rows), np.arange(n_rows), np.ones(n_rows, dtype=np.int64)
    codes, _ = pd.factorize(np.asarray(clusters))
    assert len(codes) == n_rows and (codes >= 0).all(), "one non-missing cluster label per row"
    order = np.argsort(codes, kind="stable")
    sizes = np.bincount(codes)
    return order, np.cumsum(sizes) - sizes, sizes


def draw_rows(generator, layout) -> np.ndarray:
    """Row numbers of one resample: clusters drawn with replacement, their rows kept together."""
    order, starts, sizes = layout
    picked = generator.integers(0, len(sizes), len(sizes))
    picked_sizes = sizes[picked]
    # Without a Python loop: picked cluster j contributes positions starts[j] .. starts[j] + size - 1.
    block_ends = np.cumsum(picked_sizes)
    position_in_block = np.arange(block_ends[-1]) - np.repeat(block_ends - picked_sizes, picked_sizes)
    return order[np.repeat(starts[picked], picked_sizes) + position_in_block]


def bootstrap_ci(statistic, *arrays, clusters=None, n_boot: int = N_BOOT, seed: int = SEED,
                 level: float = CI_LEVEL) -> dict:
    """Percentile bootstrap of `statistic(*arrays)`, resampling rows or whole clusters.

    Returns estimate, low, high, p_value (against zero), n, n_clusters, n_failed, replicates.
    """
    arrays = [np.asarray(array) for array in arrays]
    n_rows = len(arrays[0])
    assert n_rows > 0 and all(len(array) == n_rows for array in arrays), "row-aligned, non-empty arrays"
    layout = cluster_layout(clusters, n_rows)
    generator = np.random.default_rng(seed)  # a fresh generator: results do not depend on call order
    with np.errstate(invalid="ignore", divide="ignore"):
        estimate = np.asarray(statistic(*arrays), dtype=float)
        replicates = np.full((n_boot,) + estimate.shape, np.nan)
        for replicate in range(n_boot):
            rows = draw_rows(generator, layout)
            replicates[replicate] = statistic(*[array[rows] for array in arrays])
    interval = percentile_ci(replicates, level)
    if estimate.ndim == 0:
        estimate, p_value = float(estimate), bootstrap_p_value(replicates)
    else:
        p_value = np.array([bootstrap_p_value(column) for column in replicates.T])
    return {"estimate": estimate, "low": interval["low"], "high": interval["high"], "p_value": p_value,
            "n": int(n_rows), "n_clusters": int(len(layout[2])), "n_failed": interval["n_failed"],
            "replicates": replicates}


def log_points_to_percent(log_points):
    """A difference in logs as a percentage change: 100 * (exp(x) - 1)."""
    return PERCENT * np.expm1(log_points)


def log_ratio(before, after) -> np.ndarray:
    """log((after + 0.5) / (before + 0.5)) for counts, element by element."""
    before, after = np.asarray(before, dtype=float), np.asarray(after, dtype=float)
    return np.log((after + LOG_RATIO_OFFSET) / (before + LOG_RATIO_OFFSET))


def stratified_difference(change, treated, strata_codes, n_strata: int) -> dict:
    """Treated-minus-control mean of `change`, compared inside strata and weighted by treated counts.

    Strata lacking either arm are dropped from both sides; the counts are of the units used.
    """
    treated_n = np.bincount(strata_codes[treated], minlength=n_strata)
    control_n = np.bincount(strata_codes[~treated], minlength=n_strata)
    treated_sum = np.bincount(strata_codes[treated], weights=change[treated], minlength=n_strata)
    control_sum = np.bincount(strata_codes[~treated], weights=change[~treated], minlength=n_strata)
    comparable = (treated_n > 0) & (control_n > 0)
    if not comparable.any():
        return {"estimate": float("nan"), "treated_change": float("nan"), "control_change": float("nan"),
                "n_treated": 0, "n_control": 0, "n_strata": 0}
    weights = treated_n[comparable] / treated_n[comparable].sum()
    treated_change = float((weights * treated_sum[comparable] / treated_n[comparable]).sum())
    control_change = float((weights * control_sum[comparable] / control_n[comparable]).sum())
    return {"estimate": treated_change - control_change, "treated_change": treated_change,
            "control_change": control_change, "n_treated": int(treated_n[comparable].sum()),
            "n_control": int(control_n[comparable].sum()), "n_strata": int(comparable.sum())}


def did_log_ratio(before, after, treated, strata=None, clusters=None, n_boot: int = N_BOOT,
                  seed: int = SEED, level: float = CI_LEVEL) -> dict:
    """Difference-in-differences of the log after/before ratio, strata weighted, clusters resampled.

    Returns estimate, low, high (log points), percent_change, percent_low, percent_high, p_value,
    treated_change, control_change, n_treated, n_control, n_strata (all as used), n_treated_dropped,
    n_control_dropped, n_clusters and n_failed.
    """
    change = log_ratio(before, after)
    treated = np.asarray(treated, dtype=bool)
    if strata is None:
        strata_codes, n_strata = np.zeros(len(change), dtype=np.int64), 1
    else:
        strata_codes, strata_labels = pd.factorize(np.asarray(strata))
        n_strata = len(strata_labels)
    point = stratified_difference(change, treated, strata_codes, n_strata)

    def did_estimate(change_rows, treated_rows, strata_rows):
        return stratified_difference(change_rows, treated_rows, strata_rows, n_strata)["estimate"]

    boot = bootstrap_ci(did_estimate, change, treated, strata_codes, clusters=clusters,
                        n_boot=n_boot, seed=seed, level=level)
    return {**point, "low": boot["low"], "high": boot["high"], "p_value": boot["p_value"],
            "percent_change": float(log_points_to_percent(point["estimate"])),
            "percent_low": float(log_points_to_percent(boot["low"])),
            "percent_high": float(log_points_to_percent(boot["high"])),
            "n_treated_dropped": int(treated.sum()) - point["n_treated"],
            "n_control_dropped": int((~treated).sum()) - point["n_control"],
            "n_clusters": boot["n_clusters"], "n_failed": boot["n_failed"]}


def used_sizes(site_ids, treated, strata=None, clusters=None) -> dict:
    """Rows, unique sites and clusters behind a comparison, leaving out strata that lack an arm.

    A comparison site serves every cohort it qualifies for, so it has one row per cohort: rows and
    sites are different counts, and only sites may be called sites. `n_clusters` counts every cluster
    in the sample, which is what the bootstrap resamples; `n_treated_clusters` those that hold a used
    treated row, the clusters that can move the treated mean.
    """
    site_ids, treated = np.asarray(site_ids), np.asarray(treated, dtype=bool)
    if strata is None:
        strata_codes, n_strata = np.zeros(len(site_ids), dtype=np.int64), 1
    else:
        strata_codes, strata_labels = pd.factorize(np.asarray(strata))
        n_strata = len(strata_labels)
    has_both = ((np.bincount(strata_codes[treated], minlength=n_strata) > 0)
                & (np.bincount(strata_codes[~treated], minlength=n_strata) > 0))
    used = has_both[strata_codes]
    sizes = {"n_treated": int((used & treated).sum()), "n_control": int((used & ~treated).sum()),
             "n_treated_sites": int(pd.unique(site_ids[used & treated]).size),
             "n_comparison_sites": int(pd.unique(site_ids[used & ~treated]).size)}
    if clusters is not None:
        clusters = np.asarray(clusters)
        sizes["n_clusters"] = int(pd.unique(clusters).size)
        sizes["n_treated_clusters"] = int(pd.unique(clusters[used & treated]).size)
    return sizes


def type_contrast(before, after, arm, strata, clusters) -> dict:
    """DiD for two treated arms against one shared comparison arm, and their difference.

    arm: 0 = comparison, 1 and 2 = the two treated types. One joint bootstrap, so the shared
    comparison sites are the same in both estimates and the difference is paired. Returns three
    dicts (`first`, `second`, `difference`) in percent; their counts are of the rows used, so a
    stratum without comparison rows does not count as used.
    """
    change = log_ratio(before, after)
    arm = np.asarray(arm)
    strata_codes, strata_labels = pd.factorize(np.asarray(strata))
    n_strata = len(strata_labels)

    def type_estimates(change_rows, arm_rows, strata_rows):
        by_type = []
        for treated_arm in (1, 2):
            rows = (arm_rows == 0) | (arm_rows == treated_arm)
            by_type.append(stratified_difference(change_rows[rows], arm_rows[rows] == treated_arm,
                                                 strata_rows[rows], n_strata)["estimate"])
        return np.array([by_type[0], by_type[1], by_type[0] - by_type[1]])

    boot = bootstrap_ci(type_estimates, change, arm, strata_codes, clusters=clusters)
    used = []
    for treated_arm in (1, 2):
        rows = (arm == 0) | (arm == treated_arm)
        used.append(stratified_difference(change[rows], arm[rows] == treated_arm, strata_codes[rows], n_strata))
    # The difference uses the comparison rows of every stratum that at least one treated type could use.
    in_a_used_stratum = (np.bincount(strata_codes[arm != 0], minlength=n_strata) > 0)[strata_codes]
    n_treated = [used[0]["n_treated"], used[1]["n_treated"], used[0]["n_treated"] + used[1]["n_treated"]]
    n_control = [used[0]["n_control"], used[1]["n_control"], int(((arm == 0) & in_a_used_stratum).sum())]
    n_all_treated = [int((arm == 1).sum()), int((arm == 2).sum()), int((arm != 0).sum())]
    names = ["first", "second", "difference"]
    return {name: {"percent_change": float(log_points_to_percent(boot["estimate"][position])),
                   "percent_low": float(log_points_to_percent(boot["low"][position])),
                   "percent_high": float(log_points_to_percent(boot["high"][position])),
                   "p_value": float(boot["p_value"][position]), "n_treated": n_treated[position],
                   "n_control": n_control[position],
                   "n_treated_dropped": n_all_treated[position] - n_treated[position],
                   "n_control_dropped": int((arm == 0).sum()) - n_control[position],
                   "n_clusters": boot["n_clusters"]}
            for position, name in enumerate(names)}


def event_profile(counts, treated, cohorts, clusters, n_pre: int, site_ids=None) -> dict:
    """Mean crashes per site by relative year, indexed to the pre-completion mean, for both groups.

    counts: (rows, relative years). Both groups are averaged cohort by cohort and the cohorts are
    weighted by the treated counts, so the two lines describe the same mix of calendar years.
    Returns {"treated": {...}, "comparison": {...}}, each with `index`, `low`, `high` (arrays over
    relative years), `n_rows` and, given `site_ids`, `n_sites`. Each group is resampled on its own,
    so the overlap of the two bands is not the comparison: the interval to read for the difference
    is the joint one of `did_log_ratio`.
    """
    counts = np.asarray(counts, dtype=float)
    treated = np.asarray(treated, dtype=bool)
    cohort_codes, cohort_labels = pd.factorize(np.asarray(cohorts))
    clusters = np.asarray(clusters)
    sites = None if site_ids is None else np.asarray(site_ids)
    n_cohorts = len(cohort_labels)
    cohort_weights = np.bincount(cohort_codes[treated], minlength=n_cohorts).astype(float)

    def indexed_means(count_rows, codes):
        sizes = np.bincount(codes, minlength=n_cohorts)
        present = (sizes > 0) & (cohort_weights > 0)
        if not present.any():
            return np.full(count_rows.shape[1], np.nan)
        sums = np.column_stack([np.bincount(codes, weights=count_rows[:, column], minlength=n_cohorts)
                                for column in range(count_rows.shape[1])])
        cohort_means = sums[present] / sizes[present, None]
        yearly = (cohort_weights[present] / cohort_weights[present].sum()) @ cohort_means
        baseline = yearly[:n_pre].mean()
        # No crash before completion leaves no base for the index: NaN (not infinity) lets the
        # bootstrap count the replicate as failed.
        if baseline <= 0:
            return np.full(count_rows.shape[1], np.nan)
        return PRE_PERIOD_INDEX * yearly / baseline

    profile = {}
    for is_treated, group in [(True, "treated"), (False, "comparison")]:
        rows = treated == is_treated
        boot = bootstrap_ci(indexed_means, counts[rows], cohort_codes[rows], clusters=clusters[rows])
        profile[group] = {"index": boot["estimate"], "low": boot["low"], "high": boot["high"],
                          "n_rows": int(rows.sum()),
                          "n_sites": None if sites is None else int(pd.unique(sites[rows]).size)}
    return profile


def mean_percentile_excess(percentiles) -> float:
    """Mean percentile minus 50: zero when the places rank like typical streets."""
    return float(percentiles.mean() - NEUTRAL_PERCENTILE)


def one_vote_per_cluster(percentiles, clusters, min_clusters: int = 0) -> dict:
    """RQ7 with every cluster of linked sites counted once: the excess of the mean of cluster means.

    A site-weighted mean answers "where is the average building", and three chained clusters hold
    most of the buildings. This answers "where is the average place". Replicates draw clusters, each
    a single value here. With fewer than `min_clusters` clusters no statistic is given (NaN).
    """
    means = pd.Series(np.asarray(percentiles, dtype=float)).groupby(np.asarray(clusters)).mean().to_numpy()
    result = {"estimate": float("nan"), "low": float("nan"), "high": float("nan"), "n_clusters": int(means.size),
              "share_above_pct": float("nan")}
    if means.size >= max(min_clusters, 1):
        boot = bootstrap_ci(mean_percentile_excess, means)
        result.update(estimate=boot["estimate"], low=boot["low"], high=boot["high"],
                      share_above_pct=float(PERCENT * (means > NEUTRAL_PERCENTILE).mean()))
    return result


def spearman_rho(first, second) -> float:
    """Spearman rank correlation (average ranks for ties); NaN for under 3 pairs or a constant side."""
    first_ranks = pd.Series(np.asarray(first, dtype=float)).rank().to_numpy()
    second_ranks = pd.Series(np.asarray(second, dtype=float)).rank().to_numpy()
    if len(first_ranks) < 3 or first_ranks.std() == 0 or second_ranks.std() == 0:
        return float("nan")
    return float(np.corrcoef(first_ranks, second_ranks)[0, 1])

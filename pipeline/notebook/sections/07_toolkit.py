# %% [markdown]
# ## 7. Analysis toolkit
#
# The research questions reuse a few statistical steps, so they are written once here as small
# functions on numpy arrays. Nothing in this section touches the housing or crash data, and 7.5
# checks the functions on tiny inputs whose answer is known.
#
# Three ideas shape the section. Crashes near the same building or in the same ZIP are not
# independent, so every interval resamples whole clusters (sites or ZIPs), never single
# crashes; resampling crashes would make any difference look real. Every function reports how
# many units it used. And the data are observational, so the wording helper only ever describes
# associations.

# %% [markdown]
# ### 7.1 Shared statistics (also used by the website)
#
# The cell below is the file `app/stats.py`, pasted in when the notebook is built, so the
# notebook and the website compute every interval with the same code, seed and order of draws.
#
# - `bootstrap_ci` recomputes any statistic on `N_BOOT` resamples. With `clusters`, whole clusters
#   are drawn with replacement and their rows travel together. Each call starts its own generator
#   from `SEED`, so a result does not depend on which cells ran before it.
# - `percentile_ci` reads the interval off the replicates. A replicate that cannot be computed
#   (say, a resample without a control site) is NaN; if more than `MAX_FAILED_SHARE` fail, no
#   interval is reported, because silently dropping them would make an unstable estimate look
#   stable. `bootstrap_p_value` is the share of replicates beyond zero, used only where several
#   results are adjusted together (7.4); its floor is about `2 / N_BOOT`.
# - `log_ratio` measures a site's change as log((after + 0.5) / (before + 0.5)). The half-crash
#   offset (`LOG_RATIO_OFFSET`) keeps sites with a zero count; dropping them (the alternative)
#   would remove exactly the quiet sites. Logs make a site going from 4 to 2 crashes count like one
#   going from 40 to 20, where levels would let a few busy avenues decide.
# - `did_log_ratio` is the difference-in-differences: treated mean log ratio minus control mean
#   log ratio over the same calendar years, compared inside strata (for example cohorts) and
#   averaged with treated counts as weights. A stratum without both arms is dropped and counted.
#   `type_contrast` does this for two treated types against one shared control group in a single
#   bootstrap, so their difference is paired. `event_profile` gives the indexed yearly means
#   behind the event charts. `used_sizes` counts the rows, unique sites and clusters behind a
#   comparison: a comparison site has one row per cohort it serves, so rows are not sites.
# - `one_vote_per_cluster` repeats the mean percentile of RQ7 with each cluster of linked sites
#   counted once. `level_text` prints an interval level (95%, 98.75%, 99.44%).

# %%
# INLINE: app/stats.py

# %% [markdown]
# ### 7.2 Notebook-only constants and the rank correlation
#
# Spearman's rho is used instead of Pearson's because unit and crash counts are heavily skewed,
# and ranks are not driven by the few largest ZIPs. Fewer than `MIN_GROUP_N` pairs give no
# estimate. `group_adjusted_spearman_ci` removes each group's (borough's) mean from both variables
# before ranking, so a correlation that only reflects differences between boroughs disappears; the
# group means are recomputed in every resample, and single-member groups are left out.

# %%
FALSE_DISCOVERY_RATE = 0.05   # share of flagged results allowed to be false alarms (Benjamini-Hochberg)


def empty_result(n, **extra):
    """Result dict used when there are too few units to estimate anything."""
    return {"estimate": float("nan"), "low": float("nan"), "high": float("nan"),
            "p_value": float("nan"), "n": int(n), "n_clusters": 0, "n_failed": 0, **extra}


def demean_by_group(values, group_codes, n_groups):
    """Subtract from each value the mean of its group (codes 0..n_groups-1)."""
    sums = np.bincount(group_codes, weights=values, minlength=n_groups)
    sizes = np.bincount(group_codes, minlength=n_groups)
    return values - (sums / np.maximum(sizes, 1))[group_codes]   # empty groups are never indexed


def spearman_ci(x, y, clusters=None, min_n=MIN_GROUP_N, n_boot=N_BOOT, seed=SEED, level=CI_LEVEL):
    """Spearman's rho with a (cluster) bootstrap interval over the complete pairs."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    complete = ~(np.isnan(x) | np.isnan(y))
    if complete.sum() < min_n:
        return empty_result(complete.sum())
    kept_clusters = None if clusters is None else np.asarray(clusters)[complete]
    result = bootstrap_ci(spearman_rho, x[complete], y[complete], clusters=kept_clusters,
                          n_boot=n_boot, seed=seed, level=level)
    del result["replicates"]
    return result


def group_adjusted_spearman_ci(x, y, groups, clusters=None, min_n=MIN_GROUP_N,
                               n_boot=N_BOOT, seed=SEED, level=CI_LEVEL):
    """Spearman's rho after removing group means from x and y; adds `n_groups` to spearman_ci's dict."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    group_codes, group_labels = pd.factorize(np.asarray(groups))
    usable = ~(np.isnan(x) | np.isnan(y)) & (group_codes >= 0)
    # Sizes are counted after incomplete rows are removed: a group left with one row would demean to 0.
    usable_sizes = np.bincount(group_codes[usable], minlength=len(group_labels))
    usable &= usable_sizes[np.maximum(group_codes, 0)] >= 2
    n_groups = int(len(np.unique(group_codes[usable])))
    if usable.sum() < min_n:
        return empty_result(usable.sum(), n_groups=n_groups)

    def within_group_rho(x_rows, y_rows, code_rows):
        return spearman_rho(demean_by_group(x_rows, code_rows, len(group_labels)),
                            demean_by_group(y_rows, code_rows, len(group_labels)))

    kept_clusters = None if clusters is None else np.asarray(clusters)[usable]
    result = bootstrap_ci(within_group_rho, x[usable], y[usable], group_codes[usable],
                          clusters=kept_clusters, n_boot=n_boot, seed=seed, level=level)
    del result["replicates"]
    return {**result, "n_groups": n_groups}


def linear_slope(x, y):
    """Least-squares slope of y on x; NaN when x does not vary."""
    x_centred = x - x.mean()
    spread = (x_centred ** 2).sum()
    return float((x_centred * (y - y.mean())).sum() / spread) if spread > 0 else float("nan")


# %% [markdown]
# ### 7.3 Within-ZIP slopes in a panel
#
# For a balanced ZIP-by-year matrix, `two_way_demean` removes each ZIP's mean and each year's
# mean, so whatever is fixed for a ZIP (size, street layout) and whatever hit all ZIPs in a year
# (the 2020 reporting drop) is gone. `within_slope` regresses the demeaned outcome on one or
# several demeaned regressors (the two-way fixed-effects estimate) and resamples whole ZIPs, so
# a ZIP's years stay together; the demeaning is redone in every resample.
#
# `lead_lag_panel` shifts one regressor to build leads and lags. A lead is a future value:
# future housing cannot affect today's crashes, so a lead slope away from zero warns that ZIPs
# were already on different paths. The slopes still rest on the assumption that ZIPs would
# otherwise have moved in parallel, which the leads can question but not prove.

# %%
def two_way_demean(matrix):
    """matrix - row means - column means + grand mean, for a balanced unit-by-period matrix."""
    values = np.asarray(matrix, dtype=float)
    assert values.ndim == 2 and not np.isnan(values).any(), "the panel must be balanced"
    return values - values.mean(axis=1, keepdims=True) - values.mean(axis=0, keepdims=True) + values.mean()


def within_coefficients(outcome, regressor_stack):
    """Least-squares slopes of the demeaned outcome (units, periods) on a (units, k, periods) stack."""
    n_regressors = regressor_stack.shape[1]
    design = np.column_stack([two_way_demean(regressor_stack[:, k, :]).ravel() for k in range(n_regressors)])
    coefficients, _, rank, _ = np.linalg.lstsq(design, two_way_demean(outcome).ravel(), rcond=None)
    return coefficients if rank == n_regressors else np.full(n_regressors, np.nan)   # collinear: no answer


def within_slope(outcome, regressors, n_boot=N_BOOT, seed=SEED, level=CI_LEVEL):
    """Two-way fixed-effects slopes with a unit bootstrap.

    regressors: one matrix shaped like `outcome`, or {name: matrix} for joint slopes. Returns a
    DataFrame indexed by name: estimate, low, high, p_value, n_units, n_periods, n_failed.
    """
    named = regressors if isinstance(regressors, dict) else {"regressor": regressors}
    outcome = np.asarray(outcome, dtype=float)
    stack = np.stack([np.asarray(matrix, dtype=float) for matrix in named.values()], axis=1)
    assert stack.shape[::2] == outcome.shape, "every regressor must have the shape of the outcome"
    result = bootstrap_ci(within_coefficients, outcome, stack, n_boot=n_boot, seed=seed, level=level)
    return pd.DataFrame({"estimate": result["estimate"], "low": result["low"], "high": result["high"],
                         "p_value": result["p_value"], "n_units": outcome.shape[0],
                         "n_periods": outcome.shape[1], "n_failed": result["n_failed"]},
                        index=pd.Index(list(named), name="regressor"))


def shift_name(shift):
    """Label of a shifted regressor: negative shifts are leads, positive shifts are lags."""
    if shift < 0:
        return f"lead {-shift}"
    return "same year" if shift == 0 else f"lag {shift}"


def lead_lag_panel(outcome, regressor, shifts):
    """(trimmed outcome, {name: shifted regressor}, kept column positions), furthest lead first.

    Shift s > 0 pairs the outcome in period t with the regressor in t - s (a lag); s < 0 with t + |s|.
    """
    outcome, regressor = np.asarray(outcome, dtype=float), np.asarray(regressor, dtype=float)
    kept_columns = np.arange(max(max(shifts), 0), outcome.shape[1] - max(-min(shifts), 0))
    assert len(kept_columns) >= 2, "the leads and lags leave fewer than two usable periods"
    shifted = {shift_name(shift): regressor[:, kept_columns - shift] for shift in sorted(shifts)}
    return outcome[:, kept_columns], shifted, kept_columns


# %% [markdown]
# ### 7.4 Several tests at once, forecasts, and wording
#
# `benjamini_hochberg` adjusts p-values read together so that, among results below
# `FALSE_DISCOVERY_RATE`, at most that share is expected to be false alarms. It is less strict
# than Bonferroni, which suits a handful of related tests where missing a real pattern also costs.
#
# `time_split_evaluation` fits one model per feature list on the years before a cut-off and scores
# it on the later years. Splitting by time, not at random, keeps a ZIP's future out of training.
# The first list is the baseline; each other list gets its paired difference in mean absolute
# error, with an interval from resampling test ZIPs (fitted models held fixed, so fitting
# uncertainty is not included).
#
# `describe_effect` writes the result sentence from the numbers, so text cannot drift from the
# chart. It never uses causal words: an interval including the reference value is reported as
# such and nothing more is concluded.

# %%
def benjamini_hochberg(p_values):
    """Benjamini-Hochberg adjusted p-values in input order (NaN stays NaN and is not counted)."""
    p_values = np.asarray(p_values, dtype=float)
    adjusted = np.full(p_values.shape, np.nan)
    valid = ~np.isnan(p_values)
    n_tests = int(valid.sum())
    if n_tests == 0:
        return adjusted
    order = np.argsort(p_values[valid])
    scaled = p_values[valid][order] * n_tests / np.arange(1, n_tests + 1)
    monotone = np.minimum.accumulate(scaled[::-1])[::-1]   # a larger p may not get a smaller adjusted p
    in_input_order = np.empty(n_tests)
    in_input_order[order] = np.minimum(monotone, 1.0)
    adjusted[valid] = in_input_order
    return adjusted


def mean_gap(first, second):
    """Difference of two means (the paired difference in absolute errors)."""
    return float(first.mean() - second.mean())


def time_split_evaluation(frame, target, feature_sets, time_column, first_test_period,
                          cluster_column=None, make_model=LinearRegression):
    """Fit before `first_test_period`, score from it on, and compare feature sets with the first.

    Returns (summary, predictions). summary is indexed by feature-set name: mae,
    mae_minus_baseline, low, high, p_value, n_features, n_train, n_test, n_test_clusters.
    predictions holds the test rows with one prediction column per feature set.
    """
    is_test = (frame[time_column] >= first_test_period).to_numpy()
    train, test = frame[~is_test], frame[is_test]
    assert len(train) and len(test), "the cut-off leaves an empty training or test set"
    predictions = test[[time_column, target] + ([cluster_column] if cluster_column else [])].copy()
    for name, columns in feature_sets.items():
        model = make_model().fit(train[columns].to_numpy(dtype=float), train[target].to_numpy(dtype=float))
        predictions[name] = model.predict(test[columns].to_numpy(dtype=float))

    actual = test[target].to_numpy(dtype=float)
    test_clusters = test[cluster_column].to_numpy() if cluster_column else None
    baseline = next(iter(feature_sets))
    baseline_errors = np.abs(actual - predictions[baseline].to_numpy())
    rows = []
    for name, columns in feature_sets.items():
        errors = np.abs(actual - predictions[name].to_numpy())
        row = {"feature_set": name, "mae": float(errors.mean()), "mae_minus_baseline": 0.0,
               "low": float("nan"), "high": float("nan"), "p_value": float("nan"),
               "n_features": len(columns), "n_train": len(train), "n_test": len(test),
               "n_test_clusters": len(test) if test_clusters is None else len(pd.unique(test_clusters))}
        if name != baseline:
            # Both error vectors are indexed by the same resampled rows: a paired comparison.
            gap = bootstrap_ci(mean_gap, errors, baseline_errors, clusters=test_clusters)
            row.update(mae_minus_baseline=gap["estimate"], low=gap["low"], high=gap["high"],
                       p_value=gap["p_value"])
        rows.append(row)
    return pd.DataFrame(rows).set_index("feature_set"), predictions


def describe_effect(estimate, low, high, unit, n, subject="The estimate", n_unit="observations",
                    above=None, below=None, null_value=0.0, digits=2, level=CI_LEVEL):
    """One associational sentence: estimate, interval, n, and which side of `null_value` it lies on.

    above / below: what an interval entirely above / below the null fits ("which fits ...").
    """
    sample = f"n = {n:,} {n_unit}"
    if any(np.isnan(value) for value in (estimate, low, high)):
        return f"{subject} could not be estimated reliably ({sample}), so nothing is concluded from it."
    reference = "zero" if null_value == 0 else f"{null_value:g}"
    unit_text = f" {unit}" if unit else ""
    opening = (f"{subject} is {estimate:+.{digits}f}{unit_text} ({level_text(level)} interval "
               f"{low:+.{digits}f} to {high:+.{digits}f}, {sample})")
    if low <= null_value <= high:
        return f"{opening}. The interval includes {reference}."
    side = "above" if low > null_value else "below"
    meaning = (above if side == "above" else below) or f"a value {side} {reference}"
    return f"{opening}. The interval lies {side} {reference}, which fits {meaning}."


# %% [markdown]
# ### 7.5 Self-test
#
# Each check runs a function on a tiny made-up input whose answer is exact (a constant, copies
# inside clusters, sites whose crashes exactly double, a panel built from known slopes), and
# stops the notebook if the answer is wrong. Fewer resamples are used, since only correctness is
# checked.

# %%
SELF_TEST_BOOT = 200          # resamples per check; enough to exercise the code path
SELF_TEST_TOLERANCE = 1e-9


def check(description, condition):
    """Stop on a failed self-test, otherwise print one line."""
    assert condition, f"self-test failed: {description}"
    print(f"ok  {description}")


def close(value, expected):
    """True when value equals expected up to floating-point noise."""
    return bool(np.allclose(value, expected, atol=SELF_TEST_TOLERANCE, equal_nan=True))


def run_self_tests():
    """Run the checks; the temporaries stay local so no later cell can pick one up."""
    rng = np.random.default_rng(SEED)
    constant = bootstrap_ci(np.mean, np.full(40, 5.0), n_boot=SELF_TEST_BOOT)
    check("bootstrap_ci: a constant input gives that constant with a zero-width interval",
          close([constant["estimate"], constant["low"], constant["high"]], [5, 5, 5]))

    values, labels = np.repeat(rng.normal(size=20), 50), np.repeat(np.arange(20), 50)   # 20 clusters of copies
    by_row = bootstrap_ci(np.mean, values, n_boot=SELF_TEST_BOOT)
    by_cluster = bootstrap_ci(np.mean, values, clusters=labels, n_boot=SELF_TEST_BOOT)
    check("bootstrap_ci: copies inside a cluster add no information, so the cluster interval is far wider",
          by_cluster["high"] - by_cluster["low"] > 3 * (by_row["high"] - by_row["low"]))

    treated = np.r_[np.ones(8, dtype=bool), np.zeros(8, dtype=bool)]
    doubled = did_log_ratio(np.ones(16), np.r_[np.full(8, 2.5), np.ones(8)], treated, n_boot=SELF_TEST_BOOT)
    check("did_log_ratio: treated counts double ((2.5 + 0.5) / (1 + 0.5)), controls do not, so DiD = log 2",
          close([doubled["estimate"], doubled["low"], doubled["percent_change"]], [np.log(2), np.log(2), 100]))

    # Stratum A: 2 treated (x2) and 3 controls; B: 6 treated (x4) and 2 controls; C: 3 treated, no control.
    strata = np.array(["A"] * 5 + ["B"] * 8 + ["C"] * 3)
    in_arm = np.array([True, True, False, False, False] + [True] * 6 + [False] * 2 + [True] * 3)
    after = np.where(in_arm, np.where(strata == "A", 2.5, 5.5), 1.0)
    weighted = did_log_ratio(np.ones(16), after, in_arm, strata=strata, n_boot=SELF_TEST_BOOT)
    check("did_log_ratio: strata weighted by treated counts, the stratum without a control dropped",
          close(weighted["estimate"], (2 * np.log(2) + 6 * np.log(4)) / 8)
          and (weighted["n_treated"], weighted["n_strata"], weighted["n_treated_dropped"]) == (8, 2, 3))

    unit_effect, year_effect = rng.normal(size=(15, 1)), rng.normal(size=(1, 8))
    first, second = rng.normal(size=(15, 8)), rng.normal(size=(15, 8))
    slopes = within_slope(unit_effect + year_effect + 2 * first - 3 * second, {"a": first, "b": second},
                          n_boot=SELF_TEST_BOOT)
    check("within_slope: recovers slopes 2 and -3 through unit and year effects",
          close(slopes["estimate"], [2, -3]) and close(slopes["low"], [2, -3]))

    lagged = np.zeros((15, 8))
    lagged[:, 1:] = 4 * first[:, :-1]                                      # outcome follows last year's value
    trimmed, shifted, kept = lead_lag_panel(lagged, first, [-1, 0, 1])
    check("lead_lag_panel: an outcome that follows last year's regressor loads on 'lag 1' only",
          list(shifted) == ["lead 1", "same year", "lag 1"] and list(kept) == [1, 2, 3, 4, 5, 6]
          and close(within_slope(trimmed, shifted, n_boot=SELF_TEST_BOOT)["estimate"], [0, 0, 4]))

    check("benjamini_hochberg: [0.005, 0.5, nan, 0.02] becomes [0.015, 0.5, nan, 0.03]",
          close(benjamini_hochberg([0.005, 0.5, np.nan, 0.02]), [0.015, 0.5, np.nan, 0.03]))

    frame = pd.DataFrame({"unit": np.repeat(np.arange(12), 6), "year": np.tile(np.arange(2000, 2006), 12),
                          "x": rng.normal(size=72), "z": rng.normal(size=72)})
    frame["y"] = 2 * frame["x"] + 3 * frame["z"]
    summary, _ = time_split_evaluation(frame, "y", {"x": ["x"], "x + z": ["x", "z"]}, "year", 2004, "unit")
    check("time_split_evaluation: trains on the 48 earlier rows, tests on the 24 later rows of 12 units",
          (summary["n_train"] == 48).all() and (summary["n_test"] == 24).all()
          and (summary["n_test_clusters"] == 12).all() and close(summary.loc["x + z", "mae"], 0))


run_self_tests()

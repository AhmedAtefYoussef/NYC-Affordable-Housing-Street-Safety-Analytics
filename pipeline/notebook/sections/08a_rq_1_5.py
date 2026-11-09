# %% [markdown]
# ## 8. Research questions
#
# All ten questions relate a housing variable to a crash variable, and they share three rules.
#
# - The outcome is the **injury crash** (at least one person injured or killed). Property-damage
#   reports collapsed in 2020 (Section 3), so all crashes are not comparable across that year.
# - Every interval is a `CI_LEVEL` bootstrap interval that resamples whole groups (a ZIP with all
#   its years, or a cluster of neighbouring sites), and every result prints the units it rests on.
# - The data are observational, so a difference is an association. An interval that includes zero
#   means the data cannot tell a difference from none, not that there is none.
#
# Each question ends in one sentence written from the numbers by `describe_effect` and stored in
# `RESULTS` for the summary table of Section 10 (the helper `report` does both for every question
# except RQ9, which builds its two-outcome sentence by hand).

# %%
RESULTS = {}                 # one entry per research question

FORECAST_LAGS = 2            # years of history per forecast feature; each extra lag costs one of ten study years
UNITS_PER_STEP = 100         # RQ2 slopes are per 100 affordable units, about one mid-sized building
LEAD_LAG_SHIFTS = [-2, -1, 0, 1, 2]   # years; negative = units not completed yet (placebo leads)
PRE_YEARS = list(range(-EVENT_WINDOW, 0))        # event years before completion
POST_YEARS = list(range(1, EVENT_WINDOW + 1))    # after it; the completion year is left out (opens part-way)
REL_YEARS = PRE_YEARS + [0] + POST_YEARS
NEW_CONSTRUCTION = "New Construction"
PRESERVATION = "Preservation"
DOSE_GRID_POINTS = 40        # points of the fitted RQ4 line and its band
RATIO_TICKS = [0.125, 0.25, 0.5, 1, 2, 4, 8]     # after / before ratios labelled on RQ4's log axis


def store_result(key, question, estimate, low, high, n, sentence, unit, level=CI_LEVEL, adjusted_p=None):
    """Keep one question's headline for the summary table in Section 10."""
    RESULTS[key] = {"question": question, "estimate": float(estimate), "ci_low": float(low),
                    "ci_high": float(high), "n": int(n), "unit": unit, "sentence": sentence,
                    "level": float(level), "adjusted_p": None if adjusted_p is None else float(adjusted_p)}


def report(key, question, stored_unit, estimate, low, high, n, extra="", level=CI_LEVEL, adjusted_p=None, **wording):
    """describe_effect -> say -> store_result: the one result sentence of a question.

    `level` (an interval widened for several tests) and `adjusted_p` go to the sentence and the stored row.
    """
    sentence = describe_effect(estimate, low, high, n=n, level=level, **wording)
    store_result(key, question, estimate, low, high, n, sentence, stored_unit, level=level, adjusted_p=adjusted_p)
    say(f"{sentence} {extra}".strip())


def cohort_unit_table(panel, columns, keep_contaminated=False):
    """One row per (site, cohort) of an event table: site_id, cohort, group, treated and `columns`.

    Rows failing the screen of Section 5.4 are left out unless `keep_contaminated`. A comparison
    site appears once for every cohort it serves.
    """
    is_unit = (panel["rel_year"] == 0).to_numpy()
    if not keep_contaminated:
        is_unit &= ~panel["contaminated"].to_numpy()
    units = panel.loc[is_unit, ["site_id", "cohort", "group", *columns]].reset_index(drop=True)
    units["treated"] = (units["group"] == "treated").to_numpy()
    assert not units.duplicated(["site_id", "cohort"]).any()
    return units


# %% [markdown]
# ### 8.1 RQ1. Does knowing a ZIP's affordable-housing completions improve a forecast of its injury crashes? (M1)
#
# Each model is a linear regression fitted on the years before `FIRST_TEST_YEAR` and scored on the
# later years it never saw (a random split would let it learn from a ZIP's future). The baseline
# knows only the ZIP's injury crashes in the previous two years; three richer models add last
# years' completions, the stock of completed units, or both. The score is the mean absolute error
# (MAE); all models are scored on the same ZIP-years, so differences are paired and ZIPs are
# resampled. A linear model suits a few hundred training rows and was preferred to a tree model,
# since the question is whether housing adds information, not how flexible a model can be.
# One leak is accepted: which ZIPs enter the panel and the ZIPs recovered for crashes without one
# (Section 6.1) were both decided with crashes that include the test years.

# %%
HISTORY_FEATURES = [f"injury_crashes_lag{lag}" for lag in range(1, FORECAST_LAGS + 1)]
COMPLETION_FEATURES = [f"affordable_units_lag{lag}" for lag in range(1, FORECAST_LAGS + 1)]
FORECAST_FEATURE_SETS = {
    "Crash history only": HISTORY_FEATURES,
    "History + completions": HISTORY_FEATURES + COMPLETION_FEATURES,
    "History + stock": HISTORY_FEATURES + ["affordable_stock_lag1"],
    "History + completions + stock": HISTORY_FEATURES + COMPLETION_FEATURES + ["affordable_stock_lag1"],
}
FORECAST_BASELINE = next(iter(FORECAST_FEATURE_SETS))
FORECAST_FULL = list(FORECAST_FEATURE_SETS)[-1]


def build_forecast_frame(panel, n_lags=FORECAST_LAGS):
    """One row per ZIP and year: the target and features shifted inside the ZIP (earlier years only)."""
    ordered = panel.sort_values(["zip", "year"]).reset_index(drop=True)
    by_zip = ordered.groupby("zip", sort=False)
    frame = ordered[["zip", "year", "borough", "injury_crashes"]].copy()
    for lag in range(1, n_lags + 1):
        frame[f"injury_crashes_lag{lag}"] = by_zip["injury_crashes"].shift(lag)
        frame[f"affordable_units_lag{lag}"] = by_zip["affordable_units_completed"].shift(lag)
    frame["affordable_stock_lag1"] = by_zip["cum_affordable_units"].shift(1)
    frame = frame.dropna().reset_index(drop=True)          # the first n_lags years have no history
    assert len(frame) == panel["zip"].nunique() * (panel["year"].nunique() - n_lags)
    return frame


def forecast_comparison(frame):
    """(summary, predictions) of the out-of-time comparison; adds the gap as % of the baseline MAE."""
    summary, predictions = time_split_evaluation(frame, "injury_crashes", FORECAST_FEATURE_SETS, "year",
                                                 FIRST_TEST_YEAR, cluster_column="zip")
    summary["difference_pct"] = PERCENT * summary["mae_minus_baseline"] / summary.loc[FORECAST_BASELINE, "mae"]
    return summary, predictions


forecast_frame = build_forecast_frame(zip_year)
forecast_summary, forecast_predictions = forecast_comparison(forecast_frame)
rq1 = forecast_summary.loc[FORECAST_FULL]
gaps = forecast_summary.drop(index=FORECAST_BASELINE)

fig, ax = plt.subplots(figsize=(9, 3.4))
interval_rows(ax, list(gaps.index), gaps["mae_minus_baseline"], gaps["low"], gaps["high"], color=PALETTE["housing"],
              title=f"RQ1: change in forecast error when housing is added ({FIRST_TEST_YEAR}-{YEAR_END})",
              xlabel=f"MAE minus the MAE of crash history only (injury crashes per ZIP per year, "
                     f"{CI_LEVEL:.0%} interval)\nright of zero = larger error than crash history alone")
show(fig)

report("RQ1", "Does knowing a ZIP's affordable-housing completions improve an out-of-time forecast of its "
       "injury crashes?", "MAE difference (injury crashes per ZIP per year)",
       rq1["mae_minus_baseline"], rq1["low"], rq1["high"], int(rq1["n_test_clusters"]),
       unit="injury crashes per ZIP per year", n_unit="ZIP codes",
       subject="The change in out-of-time forecast error from adding affordable-housing completions and stock",
       above="a forecast that housing did not improve", below="a forecast that housing improved",
       extra=f"Fitted on {int(rq1['n_train']):,} ZIP-years ({forecast_frame['year'].min()}-{FIRST_TEST_YEAR - 1}) "
             f"and scored on {int(rq1['n_test']):,}; crash history alone misses by "
             f"{forecast_summary.loc[FORECAST_BASELINE, 'mae']:.2f} injury crashes against an average of "
             f"{forecast_predictions['injury_crashes'].mean():.0f}, so the change is "
             f"{rq1['difference_pct']:+.1f}% of the baseline error.")

# %% [markdown]
# Housing features did not improve the forecast in this split; the extra coefficients may simply
# be fitted to noise in a few hundred ZIP-years (not tested). The interval keeps the fitted models
# fixed, so it understates fitting uncertainty, and the result rests on one split and one linear
# model. Section 9.6 repeats it on crashes with a reported ZIP only, and a ZIP-level result counts
# as kept only if its interval excludes zero on both versions. A ZIP is large, so this says little
# about the blocks next to a building, which RQ3 looks at directly.

# %% [markdown]
# ### 8.2 RQ2. Within a ZIP over time, do injury crashes move as its stock of affordable units grows? (M1)
#
# A two-way fixed-effects regression of log injury crashes on the cumulative units completed
# (7.3): ZIP effects remove what is fixed about a ZIP, year effects remove citywide shocks such as
# the 2020 break, and whole ZIPs are resampled. The headline is the stock slope, in % per
# `UNITS_PER_STEP` units. A single slope cannot show timing, so a second regression enters the
# yearly completions at leads and lags; the two leads are placebos (future units cannot affect
# crashes). Benjamini-Hochberg (7.4) is applied to the three lags only, which are the tests read
# as findings; the leads are diagnostics.

# %%
def panel_matrix(panel, column):
    """ZIP-by-year matrix of one panel column (balanced)."""
    matrix = panel.pivot(index="zip", columns="year", values=column)
    assert matrix.notna().all().all(), "the ZIP by year panel must be balanced"
    return matrix.to_numpy(dtype=float)


def stock_regression(panel, completions_column="affordable_units_completed"):
    """(stock_slope, timing): slope on the cumulative stock, and joint lead/lag slopes on yearly completions.

    Both in percent change of injury crashes per UNITS_PER_STEP units; timing has one row per shift.
    """
    log_injury = np.log(panel_matrix(panel, "injury_crashes") + LOG_RATIO_OFFSET)
    stock = panel_matrix(panel, "cum_affordable_units") / UNITS_PER_STEP
    completions = panel_matrix(panel, completions_column) / UNITS_PER_STEP
    stock_slope = within_slope(log_injury, {"cumulative stock": stock}).iloc[0].copy()
    trimmed_outcome, shifted, kept_columns = lead_lag_panel(log_injury, completions, LEAD_LAG_SHIFTS)
    timing = within_slope(trimmed_outcome, shifted)
    timing["shift"] = sorted(LEAD_LAG_SHIFTS)
    timing["first_year"], timing["last_year"] = STUDY_YEARS[kept_columns[0]], STUDY_YEARS[kept_columns[-1]]
    is_lag = timing["shift"] >= 0
    timing["p_adjusted"] = np.nan
    timing.loc[is_lag, "p_adjusted"] = benjamini_hochberg(timing.loc[is_lag, "p_value"].to_numpy())
    for table in (stock_slope, timing):
        for column in ["estimate", "low", "high"]:
            table[f"{column}_pct"] = log_points_to_percent(table[column])
    stock_slope["zips_with_growth"] = int((stock[:, -1] > stock[:, 0]).sum())
    return stock_slope, timing


stock_slope, timing_slopes = stock_regression(zip_year)
same_year_by_kind = {kind: stock_regression(zip_year, column)[1].loc[shift_name(0)]
                     for kind, column in [("new construction", "new_construction_units"),
                                          ("preservation", "preservation_units")]}

# One chart: the headline stock slope on top, the timing slopes below it, on the same % scale.
timing_labels = [f"Units {-s} yr before completion (placebo)" if s < 0 else
                 ("Units completed that year" if s == 0 else f"Units completed {s} yr earlier")
                 for s in timing_slopes["shift"]]
fig, ax = plt.subplots(figsize=(9, 4.2))
interval_rows(ax, ["Cumulative stock (headline)"] + timing_labels,
              np.r_[stock_slope["estimate_pct"], timing_slopes["estimate_pct"]],
              np.r_[stock_slope["low_pct"], timing_slopes["low_pct"]],
              np.r_[stock_slope["high_pct"], timing_slopes["high_pct"]], color=PALETTE["housing"],
              title=f"RQ2: injury crashes in a ZIP as affordable units are added\n"
                    f"({int(stock_slope['n_units'])} ZIPs, ZIP and year effects removed)",
              xlabel=f"Change in injury crashes per {UNITS_PER_STEP} units (%, {CI_LEVEL:.0%} interval, ZIPs resampled)")
ax.axhline(len(timing_labels) - 0.5, color=PALETTE["before"], linewidth=0.8)
ax.get_yticklabels()[0].set_fontweight("bold")
show(fig)

same_year = timing_slopes.loc[shift_name(0)]
leads, lags = timing_slopes[timing_slopes["shift"] < 0], timing_slopes[timing_slopes["shift"] >= 0]
report("RQ2", "Within a ZIP over time, do injury crashes move as the cumulative stock of completed affordable "
       "units grows?", f"% change in injury crashes per {UNITS_PER_STEP} units",
       stock_slope["estimate_pct"], stock_slope["low_pct"], stock_slope["high_pct"], int(stock_slope["n_units"]),
       unit=f"percent per {UNITS_PER_STEP} units", n_unit="ZIP codes",
       subject="The within-ZIP change in injury crashes as the stock of completed affordable units grows",
       above="more injury crashes in the years with a larger stock",
       below="fewer injury crashes in the years with a larger stock",
       extra=f"The stock grew in {int(stock_slope['zips_with_growth'])} ZIPs over {int(stock_slope['n_periods'])} "
             f"years. {int((leads['high'] < 0).sum() + (leads['low'] > 0).sum())} of {len(leads)} placebo leads "
             f"exclude zero; {int((lags['p_adjusted'] < FALSE_DISCOVERY_RATE).sum())} of {len(lags)} lags pass "
             f"Benjamini-Hochberg at {FALSE_DISCOVERY_RATE:.2f}. The completion-year slope is "
             f"{fmt_ci(same_year['estimate_pct'], same_year['low_pct'], same_year['high_pct'], 2, '%')} "
             f"(adjusted p = {same_year['p_adjusted']:.3f}); by kind of project it is "
             + "; ".join(f"{kind} {fmt_ci(row['estimate_pct'], row['low_pct'], row['high_pct'], 2, '%')}"
                         for kind, row in same_year_by_kind.items()) + " (unadjusted).")

# %% [markdown]
# The headline slope cannot be told apart from zero, and the placebo leads sit near zero, so there
# is no sign that ZIPs about to receive housing were already diverging. That headline leans on
# one ZIP: Section 9.6 prints the slope on new-construction units alone and the range when each ZIP
# is left out in turn, and the stock here counts refinanced buildings, which bring no new residents,
# as if they were new homes. The completion-year dip is the exception, but split by kind it belongs to
# preservation, a financing date that brings no new residents (see RQ5), and it does not carry
# into later years; with many unadjusted tests in this notebook it is reported, not counted as a
# finding. A hundred units is a small change for a ZIP of tens of thousands of residents, so only
# a large association could show up here.

# %% [markdown]
# ### 8.3 RQ3. Do injury crashes within 250 m of a new building change after it is completed? (M2)
#
# Injury crashes within `BUFFER_M` m of new-construction sites are compared over the
# `EVENT_WINDOW` years before and after completion, against sites of the same programme not yet
# completed in that window, over the same calendar years. A plain before/after would credit the
# 2020 citywide drop to the buildings. The screens of Section 5.4 apply (Section 9.2 tightens
# them). The estimate is a difference-in-differences of log after/before ratios (7.1), compared
# inside completion cohorts, weighted by treated counts and pooled because each cohort is small;
# whole clusters of neighbouring sites are resampled.

# %%
REL_COLUMNS = [f"rel_{rel_year:+d}" for rel_year in REL_YEARS]
PRE_COLUMNS = [f"rel_{rel_year:+d}" for rel_year in PRE_YEARS]
POST_COLUMNS = [f"rel_{rel_year:+d}" for rel_year in POST_YEARS]


def build_event_sites(panel, count_column="injury_crashes"):
    """One row per clean site and cohort: counts by relative year and before/after totals."""
    clean = panel[~panel["contaminated"]]
    counts = clean.pivot(index=["site_id", "cohort"], columns="rel_year", values=count_column)
    counts.columns = [f"rel_{rel_year:+d}" for rel_year in counts.columns]
    attributes = cohort_unit_table(panel, ["cluster_id", "borough", "construction_type",
                                           "total_units"]).set_index(["site_id", "cohort"])
    table = attributes.join(counts[REL_COLUMNS], validate="one_to_one").reset_index()
    table["before"], table["after"] = table[PRE_COLUMNS].sum(axis=1), table[POST_COLUMNS].sum(axis=1)
    assert table[REL_COLUMNS].notna().all().all() and len(table) == len(counts)
    return table


def event_did(sample, before="before", after="after"):
    """Cohort-stratified DiD of the log after/before ratio, site clusters resampled."""
    return did_log_ratio(sample[before].to_numpy(), sample[after].to_numpy(), sample["treated"].to_numpy(),
                         strata=sample["cohort"].to_numpy(), clusters=sample["cluster_id"].to_numpy())


event_site_table = build_event_sites(event_panel)
new_build_sample = event_site_table[~event_site_table["treated"]
                                    | (event_site_table["construction_type"] == NEW_CONSTRUCTION)].reset_index(drop=True)
new_build_did = event_did(new_build_sample)
assert new_build_did["n_treated_dropped"] == 0 and new_build_did["n_control_dropped"] == 0
new_build_sizes = used_sizes(new_build_sample["site_id"], new_build_sample["treated"], new_build_sample["cohort"],
                             new_build_sample["cluster_id"])
assert new_build_sizes["n_treated_sites"] == new_build_did["n_treated"], "a treated site has one cohort"
# Placebo inside the pre-period (first to last pre-year): nothing was completed in between.
pretrend_did = event_did(new_build_sample, before=PRE_COLUMNS[0], after=PRE_COLUMNS[-1])
new_build_profile = event_profile(new_build_sample[REL_COLUMNS], new_build_sample["treated"],
                                  new_build_sample["cohort"], new_build_sample["cluster_id"], len(PRE_YEARS),
                                  site_ids=new_build_sample["site_id"])

fig, ax = plt.subplots(figsize=(9, 5))
ax.axhline(PRE_PERIOD_INDEX, color=PALETTE["neutral"], linewidth=1)
ax.axvspan(-0.5, 0.5, color=PALETTE["before"], alpha=0.25, linewidth=0)
for group, color, marker, label in [("treated", PALETTE["treated"], "o", "New-construction sites"),
                                    ("comparison", PALETTE["control"], "s", "Comparison sites, not yet completed")]:
    line = new_build_profile[group]
    # Treated band filled, comparison band hatched, so their overlap stays readable.
    band = {"color": color, "alpha": 0.15} if group == "treated" else \
        {"facecolor": "none", "edgecolor": color, "hatch": "///", "alpha": 0.45}
    ax.fill_between(REL_YEARS, line["low"], line["high"], linewidth=0.6 * (group != "treated"), **band)
    ax.plot(REL_YEARS, line["index"], color=color, marker=marker, linewidth=2, markeredgecolor="white",
            label=f"{label} (n = {line['n_sites']:,} sites)")
ax.set_xticks(REL_YEARS)
ax.legend(loc="lower left")
finish(ax, f"RQ3: injury crashes within {BUFFER_M} m of new buildings around completion (year 0)\n"
           f"Relative to comparison sites: {fmt_ci(new_build_did['percent_change'], new_build_did['percent_low'], new_build_did['percent_high'], 1, '%')}",
       f"Years relative to completion (bands: {CI_LEVEL:.0%} interval, site clusters resampled)",
       f"Injury crashes per site (index, years -{EVENT_WINDOW} to -1 = {PRE_PERIOD_INDEX})")
show(fig)

report("RQ3", f"Do injury crashes within {BUFFER_M} m of new-construction sites change after completion, "
       "relative to not-yet-completed sites?", "% change relative to comparison sites",
       new_build_did["percent_change"], new_build_did["percent_low"], new_build_did["percent_high"],
       new_build_did["n_treated"], unit="percent", n_unit="new-construction sites", digits=1,
       subject=f"The after-against-before change in injury crashes within {BUFFER_M} m of new buildings, "
               f"relative to comparison sites,",
       above="more injury crashes after completion than the comparison sites would suggest",
       below="fewer injury crashes after completion than the comparison sites would suggest",
       extra=f"It uses {new_build_sizes['n_comparison_sites']:,} comparison sites ({new_build_did['n_control']:,} "
             f"rows, one per cohort a site serves) in {new_build_did['n_strata']} cohorts and "
             f"{new_build_did['n_clusters']:,} resampled clusters, of which {new_build_sizes['n_treated_clusters']:,} "
             f"hold a new-construction site. Treated sites alone changed by "
             f"{log_points_to_percent(new_build_did['treated_change']):+.1f}% and comparison sites by "
             f"{log_points_to_percent(new_build_did['control_change']):+.1f}%. The pre-period placebo "
             f"(year {PRE_YEARS[0]} to {PRE_YEARS[-1]}) is "
             f"{fmt_ci(pretrend_did['percent_change'], pretrend_did['percent_low'], pretrend_did['percent_high'], 1, '%')}.")

# %% [markdown]
# The bands are resampled separately for each line, so their overlap is not the comparison; the
# interval to read is the difference-in-differences one in the chart title, which resamples both
# groups together. The two lines move together: most of the fall at new buildings also happened at comparison
# streets, and what remains has an interval that includes zero. No change is detectable, but the
# interval holds a moderate fall as well as a small rise, so this is not evidence of no change. The
# pre-period placebo is wider than the main interval (Section 9.3 gives a narrower one).
# Limits: the "before" years are largely construction years; the screened sites are the less
# densely built part of the programme (Section 9.2 looks at dense clusters); and cohorts are the
# only strata, while comparison sites spread differently across boroughs (Section 9.4).

# %% [markdown]
# ### 8.4 RQ4. Does the change around a new building grow with the size of the building? (M2)
#
# If new residents change the street, a tower should leave a bigger mark than a house. Each
# treated site's log ratio minus the mean of its cohort's comparison sites (which removes the
# calendar years, as in RQ3) is regressed on log2 of the units completed that year within the
# buffer, own building included, since neighbours finished together are one event (5.4). The
# slope reads per doubling. The comparison means are recomputed in every resample. One slope was
# preferred to size bins: it uses every site once, needs no bin edges and is a single test.

# %%
def cohort_adjusted_change(change, treated, cohort_codes, n_cohorts):
    """Each site's log ratio minus the mean log ratio of its cohort's comparison sites."""
    comparison_n = np.bincount(cohort_codes[~treated], minlength=n_cohorts)
    comparison_sum = np.bincount(cohort_codes[~treated], weights=change[~treated], minlength=n_cohorts)
    # A resample can leave a cohort without comparison sites; its treated sites get NaN there.
    comparison_mean = np.where(comparison_n > 0, comparison_sum / np.maximum(comparison_n, 1), np.nan)
    return change - comparison_mean[cohort_codes]


def add_event_units(sample, site_frame, radius_m=BUFFER_M):
    """Add `event_units` (units completed in the cohort year within radius, own building included)
    and `event_buildings` to the treated rows; comparison rows get NaN and 0."""
    first, second = site_neighbour_pairs(site_frame, radius_m)     # includes each site with itself
    neighbours = pd.DataFrame({"site_id": first,
                               "cohort": site_frame["completion_year"].astype("float64").to_numpy()[second],
                               "units": site_frame["total_units"].to_numpy(dtype=float)[second]})
    per_event = (neighbours.dropna(subset=["cohort"]).groupby(["site_id", "cohort"])["units"]
                 .agg(event_units="sum", event_buildings="size").reset_index())
    is_treated = sample["treated"].to_numpy()
    keys = sample.loc[is_treated, ["site_id", "cohort"]].astype({"site_id": "int64", "cohort": "float64"})
    matched = keys.merge(per_event.astype({"site_id": "int64"}), on=["site_id", "cohort"], how="left",
                         validate="one_to_one")
    event_units, event_buildings = np.full(len(sample), np.nan), np.zeros(len(sample), dtype=np.int64)
    event_units[is_treated] = matched["event_units"].to_numpy()
    event_buildings[is_treated] = matched["event_buildings"].to_numpy(dtype=np.int64)
    assert (event_units[is_treated] >= sample.loc[is_treated, "total_units"].to_numpy()).all()
    return sample.assign(event_units=event_units, event_buildings=event_buildings)


def dose_response(sample, n_grid=DOSE_GRID_POINTS):
    """Slope of the cohort-adjusted log ratio on log2(event units) among treated sites, with a fitted band."""
    change = log_ratio(sample["before"].to_numpy(), sample["after"].to_numpy())
    treated = sample["treated"].to_numpy()
    cohort_codes, cohort_labels = pd.factorize(sample["cohort"])
    log_units = np.log2(np.where(treated, sample["event_units"].to_numpy(dtype=float), 1.0))   # 1 = placeholder
    grid = np.linspace(log_units[treated].min(), log_units[treated].max(), n_grid)

    def slope_and_line(change_rows, treated_rows, cohort_rows, log_unit_rows):
        """[slope, fitted value at each grid point] on one resample."""
        adjusted = cohort_adjusted_change(change_rows, treated_rows, cohort_rows, len(cohort_labels))
        usable = treated_rows & ~np.isnan(adjusted)
        if usable.sum() < MIN_GROUP_N:
            return np.full(1 + n_grid, np.nan)
        slope = linear_slope(log_unit_rows[usable], adjusted[usable])
        intercept = adjusted[usable].mean() - slope * log_unit_rows[usable].mean()
        return np.r_[slope, intercept + slope * grid]

    boot = bootstrap_ci(slope_and_line, change, treated, cohort_codes, log_units,
                        clusters=sample["cluster_id"].to_numpy())
    adjusted = cohort_adjusted_change(change, treated, cohort_codes, len(cohort_labels))
    return {"estimate": float(boot["estimate"][0]), "low": float(boot["low"][0]), "high": float(boot["high"][0]),
            "n_treated": int(treated.sum()), "n_clusters": boot["n_clusters"],
            "n_treated_clusters": int(sample.loc[treated, "cluster_id"].nunique()),
            "points": pd.DataFrame({"units": sample.loc[treated, "event_units"].to_numpy(dtype=float),
                                    "adjusted_change": adjusted[treated]}),
            "line": pd.DataFrame({"units": 2.0 ** grid, "fit": boot["estimate"][1:],
                                  "low": boot["low"][1:], "high": boot["high"][1:]})}


dose_sample = add_event_units(new_build_sample, sites)
dose = dose_response(dose_sample)
dose_pct = {key: float(log_points_to_percent(dose[key])) for key in ["estimate", "low", "high"]}
points, line = dose["points"], dose["line"]

fig, ax = plt.subplots(figsize=(9, 4.8))
ax.axhline(0, color=PALETTE["neutral"], linewidth=1)
ax.scatter(points["units"], points["adjusted_change"], s=34, color=PALETTE["treated"], alpha=0.5,
           edgecolor="white", linewidth=0.6, label=f"One new-construction site (n = {len(points)})")
ax.fill_between(line["units"], line["low"], line["high"], color=PALETTE["crash"], alpha=0.18, linewidth=0,
                label=f"{CI_LEVEL:.0%} interval of the line, site clusters resampled")
ax.plot(line["units"], line["fit"], color=PALETTE["crash"], linewidth=2, label="Fitted line")
ax.set_xscale("log")
thousands(ax, axis="x")
ticks = [t for t in RATIO_TICKS if points["adjusted_change"].min() - 0.3 <= np.log(t) <= points["adjusted_change"].max() + 0.3]
ax.set_yticks(np.log(ticks), [f"x{t:g}" for t in ticks])
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3)
finish(ax, f"RQ4: change in injury crashes around a new building against the units completed there\n"
           f"Per doubling of units: {fmt_ci(dose_pct['estimate'], dose_pct['low'], dose_pct['high'], 1, '%')}",
       f"Units completed in that year within {BUFFER_M} m of the site, own building included (log scale)",
       "Injury crashes after / before,\nrelative to comparison sites (log scale)")
show(fig)

report("RQ4", "Does the before/after change in injury crashes at a new-construction site scale with the number "
       "of units?", "% change per doubling of units", dose_pct["estimate"], dose_pct["low"], dose_pct["high"],
       dose["n_treated"], unit="percent per doubling of units", n_unit="new-construction sites", digits=1,
       subject=f"The slope of the after-against-before change in injury crashes on the units completed in that "
               f"year within {BUFFER_M} m",
       above="a larger rise (or smaller fall) in injury crashes where more units were completed",
       below="a larger fall (or smaller rise) in injury crashes where more units were completed",
       extra=f"Units completed nearby range from {int(points['units'].min())} to {int(points['units'].max()):,} "
             f"(median {points['units'].median():.0f}); "
             f"{n_pct((dose_sample['event_buildings'] > 1).sum(), dose['n_treated'])} sites share their event with "
             f"another building; {dose['n_clusters']:,} clusters are resampled, of which "
             f"{dose['n_treated_clusters']:,} hold a new-construction site.")

# %% [markdown]
# No relation with size is detectable: at every size the sites scatter far more widely than any
# tilt of the line. The smallest and largest events lie several doublings apart, so a narrow
# interval per doubling still allows a sizeable difference between them. Units only stand in for
# residents (no counts of residents, trips or cars exist), many buildings are small, and the screen
# of 5.4 tends to remove large projects built in groups, so the remaining large buildings may not be
# typical.

# %% [markdown]
# ### 8.5 RQ5. Is the change different for new construction than for preservation? (M3)
#
# Preservation refinances or renovates an occupied building, so nobody new arrives: it is a
# **negative control**. A change that comes with new residents should appear around new
# construction and not around preservation; if both show it, it belongs to something else (the
# kind of street, or the calendar years). Both types are compared with the same comparison sites
# using RQ3's design, and `type_contrast` (7.1) recomputes both estimates in one bootstrap, so the
# interval of their difference accounts for the shared comparison sites. Subtracting two separate
# bootstraps would treat them as independent and overstate the width.

# %%
CONTRAST_NAMES = [NEW_CONSTRUCTION, PRESERVATION, "New construction relative to preservation"]
treated = event_site_table["treated"].to_numpy()
construction = event_site_table["construction_type"].astype(str).to_numpy()
assert set(construction[treated]) <= {NEW_CONSTRUCTION, PRESERVATION}
arm = np.where(~treated, 0, np.where(construction == NEW_CONSTRUCTION, 1, 2))    # 0 = comparison
contrast = type_contrast(event_site_table["before"], event_site_table["after"], arm,
                                event_site_table["cohort"], event_site_table["cluster_id"])
rq5_contrast = pd.DataFrame.from_dict(
    {name: {"estimate_pct": row["percent_change"], "low_pct": row["percent_low"], "high_pct": row["percent_high"],
            "p_value": row["p_value"], "n_treated": row["n_treated"], "n_comparison": row["n_control"],
            "n_clusters": row["n_clusters"]} for name, row in zip(CONTRAST_NAMES, contrast.values())},
    orient="index").rename_axis("contrast")
assert np.isclose(rq5_contrast.loc[NEW_CONSTRUCTION, "estimate_pct"], new_build_did["percent_change"]), \
    "the new-construction row must reproduce RQ3"

fig, ax = plt.subplots(figsize=(9, 3.4))
interval_rows(ax, [f"New construction (n = {rq5_contrast['n_treated'].iloc[0]})",
                   f"Preservation, negative control (n = {rq5_contrast['n_treated'].iloc[1]})",
                   "Difference: new construction\nrelative to preservation"],
              rq5_contrast["estimate_pct"], rq5_contrast["low_pct"], rq5_contrast["high_pct"],
              color=PALETTE["treated"],
              title="RQ5: change in injury crashes near a site after completion, by project type",
              xlabel=f"After against before within {BUFFER_M} m, relative to comparison sites "
                     f"(%, {CI_LEVEL:.0%} interval, one joint bootstrap)")
show(fig)

rq5 = rq5_contrast.loc[CONTRAST_NAMES[2]]
preserved_by_cohort = event_site_table[treated & (construction == PRESERVATION)].groupby("cohort").size()
report("RQ5", "Is the before/after change in injury crashes different near New Construction than near "
       "Preservation (the negative control)?", "% difference between the two after/before ratios",
       rq5["estimate_pct"], rq5["low_pct"], rq5["high_pct"], int(rq5["n_treated"]),
       unit="percent", n_unit="completed sites", digits=1,
       subject="The after-to-before ratio of injury crashes around new construction, relative to the same "
               "ratio around preservation,",
       above="a more positive change around new construction than around preservation",
       below="a more negative change around new construction than around preservation",
       extra=f"Preservation alone: {fmt_ci(*rq5_contrast.loc[PRESERVATION, ['estimate_pct', 'low_pct', 'high_pct']], 1, '%')}, "
             f"with {pct(preserved_by_cohort.max(), preserved_by_cohort.sum()):.0f}% of its sites in the "
             f"{preserved_by_cohort.idxmax()} cohort. The new-construction interval differs slightly from RQ3's "
             f"because the joint bootstrap also draws clusters holding only preservation sites.")

# %% [markdown]
# The two types cannot be told apart: each interval and the interval of their difference include
# zero. The negative control is weak, though. It is imprecise, most of its sites come from one
# cohort, its completion date is often an administrative date equal to the start date (Section
# 4.4), and preserved buildings stand on older, established streets unlike those of new
# construction. The contrast is the least precise number of these five questions.

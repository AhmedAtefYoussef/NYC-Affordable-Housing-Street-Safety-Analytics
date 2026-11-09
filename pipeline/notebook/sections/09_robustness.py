# %% [markdown]
# ## 9. Robustness checks
#
# The before/after comparison around new-construction sites (RQ3) rests on choices that the data do
# not dictate: the 250 m buffer, the injury-crash outcome, the screen against nearby completions,
# the comparison strata and the cohorts used. This section re-estimates it with one choice changed
# at a time and collects every estimate in one table and one chart. A conclusion is kept only if it
# survives choices that could reasonably have been made differently.
#
# **Central comparison.** Treated units are new-construction sites of the cohorts with a full window;
# comparison units are sites still not completed at the end of that window. Both pass the screen of
# Section 5.4. Injury crashes within the buffer are summed over the `EVENT_WINDOW` years before and
# after the completion year (the year itself is skipped). The estimate is the mean log ratio
# after/before at treated minus comparison sites, inside each cohort, weighted by treated sites per
# cohort, with whole clusters resampled for the interval.

# %%
ALTERNATIVE_RADII_M = [150, 400]   # metres; one clearly smaller and one clearly larger than BUFFER_M (Section 5.3)
SHORT_WINDOW = 2                   # years; the placebo is also run with this shorter window
PLACEBO_SHIFT = EVENT_WINDOW       # years by which the placebo moves the completion date earlier
CENTRAL_OUTCOME, ALTERNATIVE_OUTCOME = "injury_crashes", "crashes"
EVENT_UNIT_COLUMNS = ["cluster_id", "contaminated", "construction_type", "borough"]
EARLY_COHORT = YEAR_START + EVENT_WINDOW   # first full-window cohort; its before years start in YEAR_START
LARGEST_CLUSTERS_SHOWN = 3         # clusters whose joint weight Section 10 reports
KIND_CENTRAL, KIND_CHECK, KIND_PLACEBO = "central", "check", "placebo"
CHECK_OUTCOME = "Outcome"          # the all-crashes row; Section 10 reads it
CHECK_SCREEN = "Nearby completions"
CHECK_COMPARISON_SUBSET = "Comparison subset"   # the rows that cut the comparison group; Section 10 and the site read it
WIDE_CLUSTER_M = 2 * BUFFER_M      # two buffers overlap up to twice the radius, so sites that far apart still share crashes
assert all(radius in RADIUS_CANDIDATES_M for radius in ALTERNATIVE_RADII_M)


def yearly_counts(site_year_frame, outcome):
    """Sites x study-years matrix of one count column (site_year is sorted by site, then year)."""
    return site_year_frame[outcome].to_numpy().reshape(-1, N_STUDY_YEARS)


def before_after_counts(units, counts, window=EVENT_WINDOW):
    """Add `before` and `after`: the outcome summed over `window` years on each side of the cohort year."""
    relative_years = np.concatenate([np.arange(-window, 0), np.arange(1, window + 1)])
    years = units["cohort"].to_numpy()[:, None] + relative_years[None, :]
    assert years.min() >= YEAR_START and years.max() <= YEAR_END, "a window leaves the study years"
    values = counts[units["site_id"].to_numpy()[:, None], years - YEAR_START]
    return units.assign(before=values[:, :window].sum(axis=1), after=values[:, window:].sum(axis=1))


def comparison_units(panel, counts, keep_contaminated=False):
    """The one event-units builder: new-construction treated and all comparison units, with before/after sums."""
    units = cohort_unit_table(panel, EVENT_UNIT_COLUMNS, keep_contaminated=True)
    keep = ~units["treated"] | (units["construction_type"] == NEW_CONSTRUCTION)
    if not keep_contaminated:
        keep &= ~units["contaminated"]
    return before_after_counts(units[keep].reset_index(drop=True), counts)


def estimate_check(units, check, variant, kind=KIND_CHECK, strata=("cohort",), keeps_screen=True):
    """Difference-in-differences on the log ratio for one specification, as one table row.

    Strata with sites on one side only are left out and counted in the `dropped` columns. No
    estimate is reported when either arm has fewer than MIN_GROUP_N unique sites. `n_comparison`
    counts rows (a comparison site has one per cohort it serves); `n_comparison_sites` counts sites.
    """
    strata_labels = units[list(strata)].astype(str).agg("|".join, axis=1).to_numpy()
    result = did_log_ratio(units["before"].to_numpy(), units["after"].to_numpy(), units["treated"].to_numpy(),
                           strata=strata_labels, clusters=units["cluster_id"].to_numpy())
    sizes = used_sizes(units["site_id"], units["treated"], strata_labels, units["cluster_id"])
    assert (sizes["n_treated"], sizes["n_control"]) == (result["n_treated"], result["n_control"])
    row = {"check": check, "variant": variant, "kind": kind, "keeps_screen": keeps_screen,
           "n_treated": result["n_treated"], "n_comparison": result["n_control"],
           "n_comparison_sites": sizes["n_comparison_sites"],
           "n_treated_dropped": result["n_treated_dropped"], "n_comparison_dropped": result["n_control_dropped"],
           "n_resampled_units": result["n_clusters"], "n_treated_clusters": sizes["n_treated_clusters"],
           "n_strata": result["n_strata"],
           "treated_change": result["treated_change"], "comparison_change": result["control_change"]}
    large_enough = min(sizes["n_treated_sites"], sizes["n_comparison_sites"]) >= MIN_GROUP_N
    for column in ["estimate", "low", "high", "p_value", "percent_change", "percent_low", "percent_high"]:
        row[column] = result[column] if large_enough else float("nan")
    return row


def reading(row):
    """Estimate, interval and sample of one table row as a phrase."""
    if np.isnan(row["estimate"]):
        return f"not reported (fewer than {MIN_GROUP_N} sites in an arm)"
    return (f"{row['percent_change']:+.1f}% ({CI_LEVEL:.0%} interval {row['percent_low']:+.1f}% to "
            f"{row['percent_high']:+.1f}%; {row['n_treated']:,} treated and {row['n_comparison_sites']:,} comparison "
            f"sites, the latter in {row['n_comparison']:,} rows; {row['n_treated_clusters']:,} treated clusters of "
            f"{row['n_resampled_units']:,} resampled)")


injury_counts = yearly_counts(site_year, CENTRAL_OUTCOME)
assert injury_counts.shape == (len(sites), N_STUDY_YEARS)
central_units = comparison_units(event_panel, injury_counts)
central = estimate_check(central_units, "Central estimate", f"{BUFFER_M} m, {EVENT_WINDOW} years, injury crashes",
                         kind=KIND_CENTRAL)
robustness_rows = [central]
show_table(central_units.groupby(["cohort", "group"], observed=True).size().unstack("group"))
say(f"Central estimate: injury crashes change by {log_points_to_percent(central['treated_change']):+.1f}% at "
    f"treated and {log_points_to_percent(central['comparison_change']):+.1f}% at comparison sites; the "
    f"difference is {reading(central)}, bootstrap p = {central['p_value']:.2f}.")

# %% [markdown]
# ### 9.1 Outcome: all crashes
#
# Reports of property-damage-only crashes collapsed in 2020 (Section 3) and every window straddles
# that year. Replacing injury crashes with all crashes shows how large the break is in a raw
# before/after count, and whether comparison sites, which went through the same break, cancel it.

# %%
all_crashes = estimate_check(comparison_units(event_panel, yearly_counts(site_year, ALTERNATIVE_OUTCOME)),
                             CHECK_OUTCOME, "All crashes, including property damage only")
robustness_rows.append(all_crashes)
say(f"Undifferenced, all crashes near treated sites change by {log_points_to_percent(all_crashes['treated_change']):+.1f}% "
    f"(comparison sites {log_points_to_percent(all_crashes['comparison_change']):+.1f}%), against "
    f"{log_points_to_percent(central['treated_change']):+.1f}% for injury crashes. After differencing: "
    f"{reading(all_crashes)}.")

# %% [markdown]
# The raw all-crash fall is far larger than the injury-crash fall, and a before/after count without
# comparison sites would report it as a safety gain near new housing. Comparison sites show almost
# the same fall, so the difference agrees with the central estimate. Injury crashes stay the primary
# outcome because they do not need the comparison group to cancel the break exactly.
#
# ### 9.2 The screen for nearby completions
#
# The screen removes most candidate sites and keeps the less dense part of the programme. Switching
# it off admits every candidate, at the cost of comparison streets that already have a completed
# building. Neighbouring buildings of one development then enter as separate rows that count the
# same streets, so each cluster of treated sites is left out in turn and the estimate is repeated
# without the one that moves it most.

# %%
def leave_one_cluster_out(units):
    """Point estimate (log points) with each cluster that holds a treated site left out in turn."""
    change = log_ratio(units["before"].to_numpy(), units["after"].to_numpy())
    treated = units["treated"].to_numpy()
    strata_codes, strata_labels = pd.factorize(units["cohort"])
    clusters = units["cluster_id"].to_numpy()
    return pd.Series({cluster: stratified_difference(change[clusters != cluster], treated[clusters != cluster],
                                                     strata_codes[clusters != cluster], len(strata_labels))["estimate"]
                      for cluster in np.unique(clusters[treated])})


unscreened_units = comparison_units(event_panel, injury_counts, keep_contaminated=True)
unscreened = estimate_check(unscreened_units, CHECK_SCREEN, "Screen switched off: every candidate site",
                            keeps_screen=False)
without_one = leave_one_cluster_out(unscreened_units)
dominant_cluster = (without_one - unscreened["estimate"]).abs().idxmax()
in_dominant = (unscreened_units["cluster_id"] == dominant_cluster).to_numpy()
without_dominant = estimate_check(unscreened_units[~in_dominant], CHECK_SCREEN,
                                  "Screen off, without the most influential cluster", keeps_screen=False)
robustness_rows += [unscreened, without_dominant]

dominant_rows = unscreened_units[in_dominant & unscreened_units["treated"].to_numpy()]
dominant_projects = sites["project_name"].astype(str).to_numpy()[dominant_rows["site_id"]]
central_without_one = leave_one_cluster_out(central_units)
say(f"Screen off: {reading(unscreened)}. Leaving out one treated cluster at a time moves it between "
    f"{log_points_to_percent(without_one.min()):+.1f}% and {log_points_to_percent(without_one.max()):+.1f}%. The most "
    f"influential cluster holds {len(dominant_rows):,} treated rows, mostly from \"{pd.Series(dominant_projects).mode()[0]}\" "
    f"(median injury crashes per row: {dominant_rows['before'].median():.0f} before, "
    f"{dominant_rows['after'].median():.0f} after). Without it: {reading(without_dominant)}. In the central sample "
    f"the same exercise moves the estimate only between {log_points_to_percent(central_without_one.min()):+.1f}% and "
    f"{log_points_to_percent(central_without_one.max()):+.1f}%.")

# %% [markdown]
# The positive estimate without the screen rests on one development of small houses on streets that
# had almost no injury crashes before: each house counts those streets again, and a rise from near
# zero is a large log ratio. Without it the estimate is small with an interval that includes zero.
# Removing the most influential cluster must lower the estimate, so that row is not evidence of the
# opposite either; it shows the positive sign rests on one place.
#
# ### 9.3 Placebo: a completion date that is too early
#
# If streets about to get a building were already on a different path, the central estimate would
# pick that up. Each new-construction site is entered `PLACEBO_SHIFT` years before its real
# completion, so both false periods precede the building, and compared with the clean comparison
# sites of that earlier cohort. With the 3-year window the last false "after" year is the real
# completion year, so the placebo is repeated with a `SHORT_WINDOW`-year window. Both should be near
# zero. A false date needs a full window, so only later completers can enter, and the placebo sites
# are mostly not the sites of the central estimate; the overlap is printed below.

# %%
def placebo_units(shift, window=EVENT_WINDOW):
    """Units in which new-construction sites are dated `shift` years before their real completion."""
    completion = sites["completion_year"].astype("float64").to_numpy()
    first, second = site_neighbour_pairs(sites, BUFFER_M)
    base = cohort_unit_table(event_panel, EVENT_UNIT_COLUMNS, keep_contaminated=True)
    parts = [base.loc[~base["treated"] & ~base["contaminated"], ["site_id", "cohort", "group", "treated", "cluster_id"]]]
    for cohort in sorted(base["cohort"].unique()):
        # The screen of Section 5.4 applied to the false date: no other completion in the window.
        neighbour_done = completion[second]
        in_window = ((first != second) & (neighbour_done >= cohort - window) & (neighbour_done <= cohort + window)
                     & (neighbour_done != completion[first]))
        contaminated = np.bincount(first[in_window], minlength=len(sites)) > 0
        chosen = sites[(completion == cohort + shift) & (sites["construction_type"] == NEW_CONSTRUCTION).to_numpy()
                       & ~contaminated]
        parts.append(pd.DataFrame({"site_id": chosen["site_id"].to_numpy(), "cohort": cohort, "group": "treated",
                                   "treated": True, "cluster_id": chosen["cluster_id"].to_numpy()}))
    units = pd.concat(parts, ignore_index=True)
    assert not units.duplicated(["site_id", "cohort"]).any(), "a site is on both sides of one cohort"
    return units


placebo_base = placebo_units(PLACEBO_SHIFT)
for window in (EVENT_WINDOW, SHORT_WINDOW):
    robustness_rows.append(estimate_check(before_after_counts(placebo_base, injury_counts, window), "Placebo",
                                          f"Completion dated {PLACEBO_SHIFT} years early, {window}-year window",
                                          kind=KIND_PLACEBO))
say("; ".join(f"{row['variant']}: {reading(row)}" for row in robustness_rows[-2:]) + ".")
placebo_treated = set(placebo_base.loc[placebo_base["treated"], "site_id"])
central_treated = set(central_units.loc[central_units["treated"], "site_id"])
placebo_overlap = {"placebo_treated": len(placebo_treated), "central_treated": len(central_treated),
                   "in_both": len(placebo_treated & central_treated)}
placebo_real_years = sites["completion_year"].astype("float64").to_numpy()[sorted(placebo_treated)]
say(f"Overlap with the central sample: {placebo_overlap['in_both']} of the {placebo_overlap['central_treated']} central "
    f"treated sites are among the {placebo_overlap['placebo_treated']} placebo sites, whose real completions fall in "
    f"{placebo_real_years.min():.0f} to {placebo_real_years.max():.0f}.")

# %% [markdown]
# Both placebo estimates are near zero with intervals that include it, so among later completers
# the pre-completion years give no sign that treated streets were already diverging. Most central
# sites are not in this placebo, so it does not test them; the only check on those same sites is the
# pre-period comparison of 8.3, which is wide. The placebo intervals are about as wide as the central
# one, so they rule out a large difference in earlier trends, not one the size of the central estimate.
#
# ### 9.4 Strata, cohorts and duplicated projects
#
# Three changes to who is compared with whom. **Inside cohort and borough:** treated and comparison
# sites are spread differently over the boroughs, and reporting did not move alike everywhere after
# 2020. **Without the earliest cohort:** its before years start in `YEAR_START`, when a much larger
# share of crashes lacked usable coordinates (printed below), so fewer crashes could be placed near
# any site. **One building per project:** a few projects hold many treated buildings that count the
# same streets; keeping one building per project (the first site) in each cohort and arm stops
# them from weighing as many independent sites. **Who is in the comparison group:** "not yet
# completed" pools sites at different stages. A site that starts construction inside the window has
# construction years in its after period, while most treated sites have them in their before period,
# and sites of the other construction type stand on different streets (8.5). So the comparison group is
# cut four ways, by start date and by type. **Clusters at twice the radius:** two buffers overlap up
# to `WIDE_CLUSTER_M` apart, so sites that far apart share crashes and still resample independently;
# the same units are repeated with clusters linked at that distance. The subsets are plain cuts with no
# adjustment for the several tries or for what differs between the subsets, so an interval that
# excludes zero there is not evidence of a fall; it shows how much this choice matters.

# %%
inside_borough = estimate_check(central_units, "Comparison group", "Compared inside cohort and borough",
                                strata=("cohort", "borough"))
without_early = estimate_check(central_units[central_units["cohort"] != EARLY_COHORT], "Cohorts",
                               f"Without the {EARLY_COHORT} cohort")
project_of_unit = sites["project_id"].to_numpy()[central_units["site_id"]]
one_per_project = estimate_check(
    central_units[~central_units.assign(project=project_of_unit).duplicated(["cohort", "group", "project"])],
    "Projects", "One building per project")
robustness_rows += [inside_borough, without_early, one_per_project]

unit_start = sites["start_year"].astype("float64").to_numpy()[central_units["site_id"]]
unit_cohort = central_units["cohort"].to_numpy()
unit_is_treated = central_units["treated"].to_numpy()
unit_is_new = (central_units["construction_type"].astype(str) == NEW_CONSTRUCTION).to_numpy()
not_started = unit_start > unit_cohort + EVENT_WINDOW
started_in_window = (unit_start > unit_cohort - EVENT_WINDOW) & (unit_start <= unit_cohort + EVENT_WINDOW)
comparison_subsets = [("Only sites not started by the window's end", not_started),
                      ("Only sites started inside the window", started_in_window),
                      ("Only new-construction sites (same type)", unit_is_new),
                      ("Only preservation sites (other type)", ~unit_is_new)]
subset_rows = [estimate_check(central_units[unit_is_treated | subset], CHECK_COMPARISON_SUBSET, variant)
               for variant, subset in comparison_subsets]
robustness_rows += subset_rows
# The same check on the before years of the first cut: the pre-period comparison of 8.3 on those comparison sites.
subset_start = sites["start_year"].astype("float64").to_numpy()[new_build_sample["site_id"]]
pretrend_not_started = event_did(
    new_build_sample[new_build_sample["treated"].to_numpy()
                     | (subset_start > new_build_sample["cohort"].to_numpy() + EVENT_WINDOW)],
    before=PRE_COLUMNS[0], after=PRE_COLUMNS[-1])

wide_clusters = connected_clusters(*site_neighbour_pairs(sites, WIDE_CLUSTER_M), len(sites))
wide_cluster_row = estimate_check(central_units.assign(cluster_id=wide_clusters[central_units["site_id"]]), "Clusters",
                                  f"Same units, clusters linked at {WIDE_CLUSTER_M} m")
robustness_rows.append(wide_cluster_row)

unlocated_by_year = PERCENT * (1 - crashes.groupby("year")["is_located"].mean())
treated_projects = pd.Series(project_of_unit[central_units["treated"].to_numpy()]).value_counts()
say(f"Inside cohort and borough: {reading(inside_borough)} ({inside_borough['n_comparison_dropped']} comparison "
    f"rows in one-sided strata left out). Crashes without usable coordinates: {unlocated_by_year[YEAR_START]:.1f}% in "
    f"{YEAR_START}, {unlocated_by_year.drop(YEAR_START).min():.1f}% to {unlocated_by_year.drop(YEAR_START).max():.1f}% "
    f"later; without the {EARLY_COHORT} cohort: {reading(without_early)}. The {treated_projects.sum():,} treated "
    f"units belong to {len(treated_projects):,} projects, the largest with {treated_projects.max()} buildings; one "
    f"building per project: {reading(one_per_project)}.")
comparison_rows_only = ~unit_is_treated
treated_start_in_window = started_in_window[unit_is_treated]
say(f"{pct(started_in_window[comparison_rows_only].sum(), comparison_rows_only.sum()):.1f}% of comparison rows start "
    f"construction inside the window and {pct((~unit_is_new)[comparison_rows_only].sum(), comparison_rows_only.sum()):.1f}% "
    f"are preservation sites; {pct(treated_start_in_window.sum(), len(treated_start_in_window)):.1f}% of treated rows have "
    f"their start inside the window. " + " ".join(f"{row['variant']}: {reading(row)}." for row in subset_rows)
    + f" Pre-period comparison (year {PRE_YEARS[0]} to {PRE_YEARS[-1]}) with the first cut: "
      f"{fmt_ci(pretrend_not_started['percent_change'], pretrend_not_started['percent_low'], pretrend_not_started['percent_high'], 1, '%')}.")
say(f"{wide_cluster_row['variant']}: {reading(wide_cluster_row)}.")

# %% [markdown]
# ### 9.5 Buffer radius
#
# A smaller buffer keeps only the closest crashes but leaves small, noisy counts; a larger one adds
# streets with little to do with the building. The screen and the clusters use the same distance,
# so both are rebuilt at 150 m and 400 m, which changes which sites pass.

# %%
for radius in ALTERNATIVE_RADII_M:
    # A smaller buffer is a subset of the pairs already found; a larger one needs a new tree query.
    pairs = (site_pairs[site_pairs["distance_m"] <= radius] if radius < BUFFER_M
             else site_crash_pairs(sites, crash_tree, crash_tree_rows, radius))
    first, second = site_neighbour_pairs(sites, radius)
    sites_at_radius = sites.assign(cluster_id=connected_clusters(first, second, len(sites)))
    site_year_at_radius = build_site_year(pairs, crashes, len(sites))
    panel = build_event_panel(sites_at_radius, site_year_at_radius, radius_m=radius, neighbour_pairs=(first, second))
    row = estimate_check(comparison_units(panel, yearly_counts(site_year_at_radius, CENTRAL_OUTCOME)),
                         "Buffer radius", f"{radius} m, screen and clusters rebuilt at {radius} m")
    robustness_rows.append(row)
    say(f"{radius} m: {reading(row)}.")
release("pairs", "panel", "site_year_at_radius", "sites_at_radius")

# %% [markdown]
# The radius changes which sites pass the screen, so the sample moves a lot; the point estimate can
# change sign, but every interval includes zero.
#
# ### 9.6 ZIP-level results on reported ZIP codes only
#
# RQ1, RQ2 and RQ9 count crashes by ZIP code, and part of the codes were recovered from coordinates
# (Section 6.1). A recovered code can be wrong near a boundary, and the recovered share varies by
# year. The panel's crash columns are rebuilt from crashes with a police-reported ZIP code and the
# three results are estimated again.
#
# The RQ2 slope gets two more rows. Its stock counts every affordable unit, and refinanced preservation
# units bring no new residents, so the slope is repeated on the stock of each kind. And a two-way
# fixed-effects slope is set by the ZIPs whose stock moves most, so each ZIP is left out in turn. Both
# are association checks; a heterogeneity-robust estimator for staggered completions was not run.

# %%
def reported_zip_panel(panel, crash_frame):
    """The ZIP x year panel with its crash columns recounted from crashes whose ZIP code was reported."""
    is_reported = (~crash_frame["zip_imputed"] & crash_frame["in_zip_panel"]).to_numpy()
    counts = aggregate_crashes_to_zip_year(crash_frame[is_reported])
    counts = counts.assign(zip=counts["zip"].astype(str), year=counts["year"].astype(int)).set_index(["zip", "year"])
    keys = pd.MultiIndex.from_arrays([panel["zip"].astype(str), panel["year"].astype(int)])
    aligned = counts[CRASH_PANEL_MEASURES].reindex(keys, fill_value=0)
    reported = panel.copy()
    for column in CRASH_PANEL_MEASURES:
        reported[column] = aligned[column].to_numpy().astype(panel[column].dtype)
    # Row conservation: the panel already records how many of its crashes rest on a recovered code.
    assert (reported["injury_crashes"] == panel["injury_crashes"] - panel["injury_crashes_zip_imputed"]).all()
    return reported


def interval_text(estimate, low, high, digits=2):
    """Estimate and interval in one table cell."""
    return f"{estimate:+.{digits}f} ({low:+.{digits}f} to {high:+.{digits}f})"


def percent_slope(slope):
    """One row of `within_slope` with its estimate and interval in percent per UNITS_PER_STEP units."""
    return {key: float(log_points_to_percent(slope[key])) for key in ["estimate", "low", "high"]}


def stock_slope_of_kind(panel, units_column):
    """RQ2's slope on the stock of one kind of unit, cumulated inside the study years.

    Units completed before the study years would only add a constant per ZIP, which the ZIP effects remove.
    """
    log_injury = np.log(panel_matrix(panel, "injury_crashes") + LOG_RATIO_OFFSET)
    stock = np.cumsum(panel_matrix(panel, units_column), axis=1) / UNITS_PER_STEP
    return percent_slope(within_slope(log_injury, {"stock": stock}).iloc[0])


def leave_one_zip_out(panel):
    """RQ2's stock slope with each ZIP left out in turn, and the slope and interval without the most influential."""
    log_injury = np.log(panel_matrix(panel, "injury_crashes") + LOG_RATIO_OFFSET)
    stock = panel_matrix(panel, "cum_affordable_units") / UNITS_PER_STEP
    zip_codes = panel.pivot(index="zip", columns="year", values="injury_crashes").index.astype(str).to_numpy()
    assert len(zip_codes) == len(stock)
    headline = float(log_points_to_percent(within_coefficients(log_injury, stock[:, None, :])[0]))
    slopes = pd.Series({zip_code: float(log_points_to_percent(
        within_coefficients(log_injury[zip_codes != zip_code], stock[zip_codes != zip_code][:, None, :])[0]))
        for zip_code in zip_codes})
    influential = (slopes - headline).abs().idxmax()
    keep = zip_codes != influential
    variation = two_way_demean(stock) ** 2
    in_panel = panel[panel["zip"].astype(str) == influential]
    return {"low": float(slopes.min()), "high": float(slopes.max()), "n_zips": len(zip_codes),
            "zip": influential, "share_of_stock_variation_pct": pct(variation[~keep].sum(), variation.sum()),
            "units_completed": int(in_panel["affordable_units_completed"].sum()),
            "preservation_units": int(in_panel["preservation_units"].sum()),
            "new_construction_units": int(in_panel["new_construction_units"].sum()),
            "without": percent_slope(within_slope(log_injury[keep], {"stock": stock[keep]}).iloc[0])}


reported_panel = reported_zip_panel(zip_year, crashes)
reported_forecast = forecast_comparison(build_forecast_frame(reported_panel))[0].loc[FORECAST_FULL]
reported_stock, reported_timing = stock_regression(reported_panel)
rq2_new_stock, rq2_preserved_stock = (stock_slope_of_kind(zip_year, column)
                                      for column in ["new_construction_units", "preservation_units"])
rq2_new_stock_reported = stock_slope_of_kind(reported_panel, "new_construction_units")
rq2_without_one = leave_one_zip_out(zip_year)
rq2_without_one_reported = leave_one_zip_out(reported_panel)
rq2_without_zip = rq2_without_one["without"]
reported_equity = deep_share_associations(zip_equity_table(reported_panel))
reported_ped = reported_equity.loc["ped_cyc_share_pct"]
same_year_all = timing_slopes[timing_slopes["shift"] == 0].iloc[0]
same_year_reported = reported_timing[reported_timing["shift"] == 0].iloc[0]
rq9_ped_all = rq9_result.loc["ped_cyc_share_pct"]
zip_level_checks = pd.DataFrame(
    [("RQ1: change in forecast error with housing (injury crashes per ZIP-year)",
      interval_text(rq1["mae_minus_baseline"], rq1["low"], rq1["high"]),
      interval_text(reported_forecast["mae_minus_baseline"], reported_forecast["low"], reported_forecast["high"])),
     (f"RQ2: slope on the cumulative stock (% per {UNITS_PER_STEP} units)",
      interval_text(stock_slope["estimate_pct"], stock_slope["low_pct"], stock_slope["high_pct"]),
      interval_text(reported_stock["estimate_pct"], reported_stock["low_pct"], reported_stock["high_pct"])),
     (f"RQ2: slope on same-year completions (% per {UNITS_PER_STEP} units)",
      interval_text(same_year_all["estimate_pct"], same_year_all["low_pct"], same_year_all["high_pct"]),
      interval_text(same_year_reported["estimate_pct"], same_year_reported["low_pct"], same_year_reported["high_pct"])),
     (f"RQ2: slope on the new-construction stock only (% per {UNITS_PER_STEP} units)",
      interval_text(rq2_new_stock["estimate"], rq2_new_stock["low"], rq2_new_stock["high"]),
      interval_text(rq2_new_stock_reported["estimate"], rq2_new_stock_reported["low"], rq2_new_stock_reported["high"])),
     (f"RQ2: stock slope with one ZIP left out in turn, lowest to highest (% per {UNITS_PER_STEP} units)",
      f"{rq2_without_one['low']:+.2f} to {rq2_without_one['high']:+.2f}",
      f"{rq2_without_one_reported['low']:+.2f} to {rq2_without_one_reported['high']:+.2f}"),
     ("RQ9: within-borough rank correlation, pedestrian and cyclist share",
      interval_text(rq9_ped_all["rho_within_borough"], rq9_ped_all["low"], rq9_ped_all["high"], 3),
      interval_text(reported_ped["rho_within_borough"], reported_ped["low"], reported_ped["high"], 3))],
    columns=["estimate", "all ZIP codes", "reported ZIP codes only"]).set_index("estimate")
show_table(zip_level_checks)
say(f"{pct(zip_year['injury_crashes_zip_imputed'].sum(), zip_year['injury_crashes'].sum()):.1f}% of panel injury "
    f"crashes have a recovered ZIP code. Adjusted p on reported codes: RQ2 same-year slope "
    f"{same_year_reported['p_adjusted']:.3f} (all codes {same_year_all['p_adjusted']:.3f}); RQ9 "
    f"{reported_ped['p_adjusted']:.3f} (all codes {rq9_ped_all['p_adjusted']:.3f}).")
say(f"RQ2 beside its headline {interval_text(stock_slope['estimate_pct'], stock_slope['low_pct'], stock_slope['high_pct'])}: "
    f"new-construction stock only {interval_text(rq2_new_stock['estimate'], rq2_new_stock['low'], rq2_new_stock['high'])}, "
    f"preservation stock only {interval_text(rq2_preserved_stock['estimate'], rq2_preserved_stock['low'], rq2_preserved_stock['high'])}. "
    f"With one ZIP left out in turn the slope runs from {rq2_without_one['low']:+.3f} to {rq2_without_one['high']:+.3f}. "
    f"ZIP {rq2_without_one['zip']} moves it most: it holds {rq2_without_one['share_of_stock_variation_pct']:.1f}% of the "
    f"variation in the demeaned stock and completed {rq2_without_one['units_completed']:,} affordable units, "
    f"{rq2_without_one['preservation_units']:,} of them preservation and {rq2_without_one['new_construction_units']:,} new "
    f"construction. Without it the slope is {interval_text(rq2_without_zip['estimate'], rq2_without_zip['low'], rq2_without_zip['high'])}.")
release("reported_panel")

# %% [markdown]
# The forecast gap of RQ1 does not appear on reported codes, so RQ1 reads "housing did not improve
# the forecast" and Section 10 does not keep it. The RQ2 headline depends on one ZIP's refinancing:
# its reading of "compatible with no change" holds with that ZIP in and does not hold without it, and
# the new-construction stock gives a larger slope, so no single size is claimed for RQ2. The RQ9 correlation barely moves and stays a hint. The RQ2
# same-year slope keeps its sign in both columns; it belongs to preserved units (see 11). Neither
# column is the true one, because leaving out recovered codes removes a share that varies by year;
# a ZIP-level result counts as solid only if it appears in both.
#
# ### 9.7 All checks together
#
# Every specification of the RQ3 comparison, as a percent difference with its interval. The shaded
# band is the central interval; the dashed line is no difference.

# %%
robustness_table = pd.DataFrame(robustness_rows)
robustness_table["interval_excludes_zero"] = (robustness_table["low"] > 0) | (robustness_table["high"] < 0)
assert not robustness_table.duplicated(["check", "variant"]).any()
show_table(robustness_table.set_index(["check", "variant"])[
    ["n_treated", "n_comparison_sites", "n_comparison", "n_treated_clusters", "n_resampled_units", "percent_change",
     "percent_low", "percent_high", "p_value", "interval_excludes_zero"]].round(2))

# %%
plotted = robustness_table[robustness_table["estimate"].notna()]
fig, ax = plt.subplots(figsize=(11, 0.42 * len(plotted) + 1.6))
ax.axvspan(central["percent_low"], central["percent_high"], color=PALETTE["treated"], alpha=0.12)
interval_rows(ax, [f"{row.variant} ({row.n_treated:,} / {row.n_comparison_sites:,})" for row in plotted.itertuples()],
              plotted["percent_change"], plotted["percent_low"], plotted["percent_high"],
              title="RQ3 under each change of method: injury crashes near new-construction sites\n"
                    "(treated / comparison sites per row; shaded: central interval)",
              xlabel=f"Difference in the before-to-after change, treated minus comparison (%, {CI_LEVEL:.0%} interval)")
show(fig)

# %%
changed_rows = robustness_table[(robustness_table["kind"] == KIND_CHECK) & robustness_table["estimate"].notna()]
screened_rows = changed_rows[changed_rows["keeps_screen"]
                             & (changed_rows["check"] != CHECK_COMPARISON_SUBSET)]
cut_rows = changed_rows[changed_rows["check"] == CHECK_COMPARISON_SUBSET]
placebo_rows = robustness_table[robustness_table["kind"] == KIND_PLACEBO]
say(f"Of {len(changed_rows)} specifications that change one choice, {int((~changed_rows['interval_excludes_zero']).sum())} "
    f"have an interval that includes zero; point estimates run from {changed_rows['percent_change'].min():+.1f}% to "
    f"{changed_rows['percent_change'].max():+.1f}% (central {central['percent_change']:+.1f}%). Across the "
    f"{len(screened_rows)} that keep the screen and the whole comparison group, the intervals span "
    f"{screened_rows['percent_low'].min():+.1f}% to {screened_rows['percent_high'].max():+.1f}%, and "
    f"{int(screened_rows['interval_excludes_zero'].sum())} exclude zero. Of the {len(cut_rows)} cuts of the comparison "
    f"group, {int(cut_rows['interval_excludes_zero'].sum())} exclude zero, with estimates from "
    f"{cut_rows['percent_change'].min():+.1f}% to {cut_rows['percent_change'].max():+.1f}%. Placebo intervals excluding "
    f"zero: {int(placebo_rows['interval_excludes_zero'].sum())} of {len(placebo_rows)}.")

# %% [markdown]
# **What holds.** With the screen on and the whole comparison group, the change in injury crashes
# around newly completed new-construction sites cannot be told apart from the change around comparison
# sites, whatever the radius, the outcome, borough strata, the earliest cohort, duplicated projects or
# the link distance of the clusters. **What does not hold in every version.** Who is in the comparison
# group matters: the counts above show that some cuts of it exclude zero and others do not. Those cuts
# are unadjusted and the groups differ in more than their start date or type, so they are not evidence
# that crashes fall after completion; they do mean "no change" should be read as "no change against this
# pooled group". The placebo says little here, because most central sites are not in it (9.3). **What
# depends on a choice.** The sign of the point estimate moves with which sites are admitted, so "crashes
# fall a little after completion" is not claimed. The positive estimate without the screen rests on one
# development (9.2). The screened sample is the less dense part of the programme, and all of this is
# association, not cause (see 11).

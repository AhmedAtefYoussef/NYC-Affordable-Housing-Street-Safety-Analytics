# %% [markdown]
# ### 8.6 RQ6. Does the pedestrian and cyclist share of injury crashes near affordable-housing sites change after completion, by borough? (M3)
#
# **Method.** RQ6, RQ8 and RQ10 ask whether the *mix* of injury crashes near a site shifts after
# completion, so they share one design. For each clean (site, cohort) unit of Section 5 we count
# injury crashes per category in the `EVENT_WINDOW` years before and after the completion year
# (the year itself is skipped). The share change at completed sites minus the change at
# not-yet-completed comparison sites of the same cohort is the gap; cohorts are averaged with the
# treated crash counts as weights, and whole clusters are resampled. A plain before/after
# comparison was rejected because the citywide victim mix moved in these years (pandemic, e-bikes).
# Shares are pooled over sites, because a share at a site with two crashes can only be 0, ½ or 1.
# Completed sites of both kinds are pooled to keep the sample usable, and each gap is repeated with
# new construction alone (preservation brings no new residents, see 11).

# %%
PEDESTRIAN_CYCLIST_LABELS = ["Pedestrian or cyclist hurt", "Only vehicle occupants hurt"]
ALL_BOROUGHS_LABEL = "All boroughs"
N_BOOT_JOINT = 5000          # resamples for tables whose widened interval is read: at 99.44% about 14 replicates lie beyond each bound
COMPOSITION_UNIT_COLUMNS = ["cluster_id", "borough", "construction_type"]   # carried by every (site, cohort) unit


def period_category_counts(units, pairs, crash_frame, category_codes, n_categories, window=EVENT_WINDOW):
    """(before, after) injury-crash counts of shape (units, categories); a negative code leaves a crash out."""
    is_counted = crash_frame["is_injury_crash"].to_numpy() & (category_codes >= 0)
    near = pairs.loc[is_counted[pairs["crash_row"].to_numpy()], ["site_id", "crash_row"]]
    # A comparison site serves several cohorts, so this merge is many to many on purpose.
    near = near.merge(units[["site_id", "cohort"]].assign(unit=np.arange(len(units))), on="site_id")
    crash_rows = near["crash_row"].to_numpy()
    relative_year = crash_frame["year"].to_numpy()[crash_rows].astype(np.int64) - near["cohort"].to_numpy()
    cell = near["unit"].to_numpy() * n_categories + category_codes[crash_rows]
    size = len(units) * n_categories

    def period_counts(in_period):
        return np.bincount(cell[in_period], minlength=size).reshape(len(units), n_categories)

    return (period_counts((relative_year >= -window) & (relative_year <= -1)),
            period_counts((relative_year >= 1) & (relative_year <= window)))


def cohort_weighted_shifts(before, after, treated, cohort_codes, n_cohorts):
    """(3, categories) array: share change at treated sites, at comparison sites, and their gap.

    Cohorts in which either arm has no crashes in a period cannot be compared and are left out.
    """
    n_categories = before.shape[1]
    # Every count belongs to one (arm, cohort, category) cell; one bincount sums all cells at once.
    cell = ((treated.astype(np.int64) * n_cohorts + cohort_codes)[:, None] * n_categories
            + np.arange(n_categories)[None, :]).ravel()
    shape = (2, n_cohorts, n_categories)
    before_sums = np.bincount(cell, weights=before.ravel(), minlength=np.prod(shape)).reshape(shape)
    after_sums = np.bincount(cell, weights=after.ravel(), minlength=np.prod(shape)).reshape(shape)
    before_totals, after_totals = before_sums.sum(axis=2), after_sums.sum(axis=2)
    comparable = ((before_totals > 0) & (after_totals > 0)).all(axis=0)
    if not comparable.any():
        return np.full((3, n_categories), np.nan)
    change = (after_sums[:, comparable] / after_totals[:, comparable, None]
              - before_sums[:, comparable] / before_totals[:, comparable, None])
    treated_events = before_totals[1, comparable] + after_totals[1, comparable]   # arm 1 is the treated arm
    weights = treated_events / treated_events.sum()
    treated_change, comparison_change = (weights[:, None] * change[1]).sum(axis=0), (weights[:, None] * change[0]).sum(axis=0)
    return np.vstack([treated_change, comparison_change, treated_change - comparison_change])


def pooled_shares(counts, is_member):
    """Category shares in percent, pooled over the selected units."""
    totals = counts[is_member].sum(axis=0)
    return PERCENT * totals / totals.sum() if totals.sum() > 0 else np.full(counts.shape[1], np.nan)


def composition_shift(units, before, after, labels, n_boot=N_BOOT):
    """Gap in category shares (percentage points) with a cluster bootstrap; returns (table, summary).

    `low_joint`/`high_joint` widen the interval for the number of categories (Bonferroni): they
    are the interval to quote for a category picked after looking at all of them. A table whose
    widened interval is the headline passes `n_boot=N_BOOT_JOINT`, since its tails are thin.
    """
    treated = units["treated"].to_numpy()
    cohort_codes, cohort_labels = pd.factorize(units["cohort"].to_numpy(), sort=True)
    n_categories = len(labels)
    boot = bootstrap_ci(lambda b, a, t, c: cohort_weighted_shifts(b, a, t, c, len(cohort_labels)).ravel(),
                        before, after, treated, cohort_codes, clusters=units["cluster_id"].to_numpy(),
                        n_boot=n_boot)
    joint_level = 1 - (1 - CI_LEVEL) / n_categories
    joint = percentile_ci(boot["replicates"], level=joint_level)
    points = {key: PERCENT * np.asarray(values).reshape(3, n_categories) for key, values in
              [("estimate", boot["estimate"]), ("low", boot["low"]), ("high", boot["high"]),
               ("low_joint", joint["low"]), ("high_joint", joint["high"])]}
    p_values = np.asarray(boot["p_value"]).reshape(3, n_categories)[2]
    table = pd.DataFrame({
        "treated_before": pooled_shares(before, treated), "treated_after": pooled_shares(after, treated),
        "comparison_before": pooled_shares(before, ~treated), "comparison_after": pooled_shares(after, ~treated),
        "treated_change": points["estimate"][0], "comparison_change": points["estimate"][1],
        "gap": points["estimate"][2], "low": points["low"][2], "high": points["high"][2],
        "low_joint": points["low_joint"][2], "high_joint": points["high_joint"][2],
        "p_value": p_values, "p_adjusted": benjamini_hochberg(p_values),
    }, index=pd.Index(labels, name="category"))
    table["flagged"] = table["p_adjusted"] < FALSE_DISCOVERY_RATE
    summary = {"n_treated_sites": int(units.loc[treated, "site_id"].nunique()),
               "n_comparison_sites": int(units.loc[~treated, "site_id"].nunique()),
               "n_clusters": boot["n_clusters"], "joint_level": joint_level,
               "n_treated_clusters": int(units.loc[treated, "cluster_id"].nunique()),
               "treated_crashes": int(before[treated].sum() + after[treated].sum())}
    return table, summary


def units_of_kind(kind):
    """Mask of event units with the treated group limited to one kind (comparison units all stay)."""
    return (~event_units["treated"] | (event_units["construction_type"] == kind)).to_numpy()


def new_construction_line(before, after, labels, category):
    """One sentence: the gap of `category` with only new-construction sites as the treated group."""
    keep = units_of_kind(NEW_CONSTRUCTION)
    table, summary = composition_shift(event_units[keep], before[keep], after[keep], labels)
    row = table.loc[category]
    return (f"With only new-construction sites treated ({summary['n_treated_sites']:,} sites) the gap is "
            f"{row['gap']:+.2f} points ({CI_LEVEL:.0%} interval {row['low']:+.2f} to {row['high']:+.2f}).")


event_units = cohort_unit_table(event_panel, COMPOSITION_UNIT_COLUMNS)

# %% [markdown]
# For RQ6 the two categories are "a pedestrian or cyclist was hurt" and "only vehicle occupants were
# hurt". A borough is estimated only with at least `MIN_GROUP_N` completed and comparison sites, and
# the borough p-values are adjusted together (Benjamini-Hochberg), because several boroughs give
# chance several tries.

# %%
rq6_before, rq6_after = period_category_counts(event_units, site_pairs, crashes,
                                               np.where(crashes["ped_cyc_harm"].to_numpy(), 0, 1), 2)
rq6_rows, rq6_samples = {}, {}
for area in [ALL_BOROUGHS_LABEL, *BOROUGHS]:
    in_area = (np.ones(len(event_units), bool) if area == ALL_BOROUGHS_LABEL
               else (event_units["borough"] == area).to_numpy())
    area_units = event_units[in_area]
    n_treated = int(area_units["treated"].sum())
    n_comparison = int(area_units.loc[~area_units["treated"], "site_id"].nunique())
    rq6_samples[area] = {"n_treated_sites": n_treated, "n_comparison_sites": n_comparison}
    if min(n_treated, n_comparison) < MIN_GROUP_N:
        continue
    table, summary = composition_shift(area_units, rq6_before[in_area], rq6_after[in_area], PEDESTRIAN_CYCLIST_LABELS)
    rq6_rows[area] = table.loc[PEDESTRIAN_CYCLIST_LABELS[0]].drop(["p_adjusted", "flagged", "low_joint", "high_joint"])
    rq6_samples[area].update(summary)
rq6_table = pd.DataFrame(rq6_rows).T.astype(float)
is_borough_row = rq6_table.index != ALL_BOROUGHS_LABEL
rq6_table.loc[is_borough_row, "p_adjusted"] = benjamini_hochberg(rq6_table.loc[is_borough_row, "p_value"].to_numpy())
show_table(rq6_table[["treated_before", "comparison_before", "treated_change", "comparison_change",
                      "gap", "low", "high", "p_value", "p_adjusted"]].round(2))

# %%
fig, ax = plt.subplots(figsize=(9, 3.8))
interval_rows(ax, [f"{area} ({rq6_samples[area]['n_treated_sites']} / {rq6_samples[area]['n_comparison_sites']} sites)"
                   for area in rq6_table.index], rq6_table["gap"], rq6_table["low"], rq6_table["high"],
              title=f"RQ6: change in pedestrian and cyclist share of injury crashes within {BUFFER_M} m,\n"
                    f"completed minus comparison sites (completed / comparison sites per row)",
              xlabel=f"Gap in percentage points, {EVENT_WINDOW} years after vs before ({CI_LEVEL:.0%} interval)")
show(fig)

# %%
rq6_city, rq6_sample = rq6_table.loc[ALL_BOROUGHS_LABEL], rq6_samples[ALL_BOROUGHS_LABEL]
rq6_skipped = [area for area in BOROUGHS if area not in rq6_table.index]
report("RQ6", "Does the pedestrian and cyclist share of injury crashes near sites change after completion?",
       "percentage points, completed minus comparison sites",
       rq6_city["gap"], rq6_city["low"], rq6_city["high"], rq6_sample["n_treated_sites"],
       unit="percentage points",
       n_unit=f"completed sites, against {rq6_sample['n_comparison_sites']:,} comparison sites, in "
              f"{rq6_sample['n_clusters']:,} clusters, {rq6_sample['n_treated_clusters']:,} of them with a completed site",
       subject="The gap in the pedestrian and cyclist share of injury crashes (completed minus comparison sites)",
       above="a larger rise in that share around completed buildings",
       below="a smaller rise in that share around completed buildings",
       extra=f"Borough gaps run from {rq6_table.loc[is_borough_row, 'gap'].min():+.1f} to "
             f"{rq6_table.loc[is_borough_row, 'gap'].max():+.1f} points; smallest adjusted p = "
             f"{rq6_table['p_adjusted'].min():.2f}. Not estimated (fewer than {MIN_GROUP_N} sites): "
             f"{', '.join(rq6_skipped) or 'none'}. "
             + new_construction_line(rq6_before, rq6_after, PEDESTRIAN_CYCLIST_LABELS, PEDESTRIAN_CYCLIST_LABELS[0]))

# %% [markdown]
# **Reading.** The share changed little around completed sites and fell slightly more around
# comparison sites; the gap's interval crosses zero citywide, no borough gap survives the
# adjustment, and new construction alone gives almost the same gap. A real shift smaller than the
# interval width (a few points) would not be visible. The design allows the two groups to start at
# different levels and assumes only that they would have moved alike. The flag misses e-scooter
# riders and the clean sites are the less dense part of the programme (see 11).

# %% [markdown]
# ### 8.7 RQ7. Before the project starts, are affordable-housing sites already on streets with more injury crashes than typical street locations of the same borough? (M4)
#
# **Method.** There is no street map in the two datasets, so "typical street locations" are a
# regular grid of points `REFERENCE_SPACING_M` apart, kept when any crash was reported within
# `STREET_SNAP_M` m in the baseline years (that drops water, parks and airports, and no later crash
# decides which streets count). Every grid point and every site gets the
# number of injury crashes within `BUFFER_M` m in the baseline years `BASELINE_YEARS`, and each site
# is ranked (midrank percentile) among the grid points of its borough. Only sites started after the
# baseline are used, so a new building cannot have affected its own count; the headline is new
# construction. Typical locations would average `NEUTRAL_PERCENTILE`. Sites linked within 250 m
# (the clusters of Section 5) share almost the same buffer, so whole clusters are resampled. A few
# clusters chain through whole neighbourhoods and hold most of the sites, so the site-weighted mean
# answers "where is the average building". A fourth row counts each cluster once and answers "where
# is the average place"; the size of the excess depends on that choice of weights.
# Alternative rejected: a cell-level correlation of units and crashes mostly measures that both are
# absent from parks. The ranking within the site's own ZIP code separates neighbourhood from street.
# This counts injury crashes; it is not a rate per traveller, so it says "more injury crashes", not
# "more dangerous", and the benchmark is street points, not other apartment buildings.

# %%
REFERENCE_SPACING_M = BUFFER_M     # one buffer radius, so neighbouring reference buffers overlap
STREET_SNAP_M = 100                # metres; a point is "on a street" if a crash was ever reported this close
PERCENTILE_BIN_WIDTH = 10          # percentile points per bin of the RQ7 histogram
LARGEST_RQ7_CLUSTERS = 3           # clusters whose joint share of the RQ7 sites is printed
RQ7_BOOTSTRAP_UNIT = "cluster_id"  # sites linked within BUFFER_M (Section 5) are resampled together
RQ7_NEW = "New construction, ranked in the borough"
RQ7_POOLED = "Both kinds pooled, ranked in the borough"
RQ7_WITHIN_ZIP = "New construction, ranked in its own ZIP code"
RQ7_ONE_VOTE = "New construction, ranked in the borough, one vote per cluster"


def most_common_per_place(places, column):
    """For each (lat, lon), the most frequent value of `column`; equal counts go to the first value in sort order,
    and a missing value only wins where nothing else is recorded."""
    counts = places.groupby(["lat", "lon", column], dropna=False, observed=True).size().rename("n").reset_index()
    counts["missing"] = counts[column].isna()
    counts = counts.sort_values(["lat", "lon", "missing", "n", column], ascending=[True, True, True, False, True],
                                kind="stable")
    return counts.drop_duplicates(["lat", "lon"]).set_index(["lat", "lon"])[column]


def reference_street_points(crash_frame, rows):
    """Grid points on the street network, with borough and ZIP of the nearest crash location.

    Many crashes share exact coordinates, so a grid point often has several nearest crashes. Which of them a tree
    returns is an implementation detail that changes between library versions, so the crashes are first reduced to
    one entry per location, carrying the borough and ZIP most often recorded there; the result is then the same on
    every machine."""
    located = crash_frame.iloc[rows][["lat", "lon", "borough", "zip"]].astype({"zip": object})
    place = pd.concat([most_common_per_place(located, "borough"), most_common_per_place(located, "zip")],
                      axis=1).reset_index()
    tree = build_haversine_tree(place["lat"].to_numpy(), place["lon"].to_numpy())
    lat_step = REFERENCE_SPACING_M / METRES_PER_DEGREE
    lon_step = lat_step / math.cos(math.radians(MID_LATITUDE_DEG))   # same spacing in metres both ways
    grid_lat, grid_lon = (axis.ravel() for axis in np.meshgrid(np.arange(*NYC_BOUNDS["lat"], lat_step),
                                                               np.arange(*NYC_BOUNDS["lon"], lon_step), indexing="ij"))
    distance, nearest = tree.query(to_radians(grid_lat, grid_lon), k=1)
    on_street = distance[:, 0] * EARTH_RADIUS_M <= STREET_SNAP_M
    nearest_place = place.iloc[nearest[on_street, 0]]
    points = pd.DataFrame({"lat": grid_lat[on_street], "lon": grid_lon[on_street],
                           "borough": nearest_place["borough"].to_numpy(), "zip": nearest_place["zip"].to_numpy()})
    return points.dropna(subset=["borough"]).reset_index(drop=True)


def midrank_percentile(values, reference_values):
    """Percentile of each value within the reference, ties counted as half below (so the reference averages 50)."""
    ordered = np.sort(np.asarray(reference_values))
    below = np.searchsorted(ordered, values, side="left")
    below_or_equal = np.searchsorted(ordered, values, side="right")
    return PERCENT * (below + below_or_equal) / (2 * len(ordered))


def percentile_within_groups(values, groups, reference_values, reference_groups):
    """Midrank percentile among the reference values of the same group; NaN for groups under MIN_GROUP_N."""
    percentiles = np.full(len(values), np.nan)
    groups = np.asarray(groups, dtype=object)
    for group, reference in pd.Series(np.asarray(reference_values)).groupby(np.asarray(reference_groups, dtype=object)):
        in_group = groups == group
        if len(reference) >= MIN_GROUP_N and in_group.any():
            percentiles[in_group] = midrank_percentile(np.asarray(values)[in_group], reference.to_numpy())
    return percentiles


# Baseline injury crashes within BUFFER_M of every reference point and of every site started after the baseline.
in_baseline = (crashes["is_injury_crash"] & crashes["is_located"] & crashes["year"].between(*BASELINE_YEARS)).to_numpy()
baseline_tree = build_haversine_tree(crashes["lat"].to_numpy()[in_baseline], crashes["lon"].to_numpy()[in_baseline])
# A street point is one with a crash of any severity in the baseline years: injury crashes alone would
# select on the outcome, and later years would let crashes after the baseline decide which streets count.
street_rows = np.flatnonzero((crashes["is_located"] & crashes["year"].between(*BASELINE_YEARS)).to_numpy())
rq7_reference = reference_street_points(crashes, street_rows)
rq7_sites = sites[sites["start_year"] > BASELINE_YEARS[1]].copy()
for frame in (rq7_reference, rq7_sites):
    frame["baseline_crashes"] = baseline_tree.query_radius(to_radians(frame["lat"].to_numpy(), frame["lon"].to_numpy()),
                                                           BUFFER_M / EARTH_RADIUS_M, count_only=True)
for column, group in [("borough_percentile", "borough"), ("zip_percentile", "zip")]:
    rq7_sites[column] = percentile_within_groups(rq7_sites["baseline_crashes"], rq7_sites[group],
                                                 rq7_reference["baseline_crashes"], rq7_reference[group])
assert rq7_sites["borough_percentile"].notna().all()

# Three specifications, each with whole linked clusters resampled.
is_rq7_new = (rq7_sites["construction_type"].astype(str) == NEW_CONSTRUCTION).to_numpy()
rq7_rows = {}
for name, column, used in [(RQ7_NEW, "borough_percentile", is_rq7_new),
                           (RQ7_POOLED, "borough_percentile", np.ones(len(rq7_sites), bool)),
                           (RQ7_WITHIN_ZIP, "zip_percentile", is_rq7_new & rq7_sites["zip_percentile"].notna().to_numpy())]:
    boot = bootstrap_ci(mean_percentile_excess, rq7_sites.loc[used, column].to_numpy(),
                        clusters=rq7_sites.loc[used, RQ7_BOOTSTRAP_UNIT].to_numpy())
    rq7_rows[name] = {"estimate": boot["estimate"], "low": boot["low"], "high": boot["high"],
                      "n_sites": boot["n"], "units_resampled": boot["n_clusters"]}
rq7_new_sites_table = rq7_sites[is_rq7_new]
rq7_one_vote = one_vote_per_cluster(rq7_new_sites_table["borough_percentile"], rq7_new_sites_table[RQ7_BOOTSTRAP_UNIT])
rq7_rows[RQ7_ONE_VOTE] = {"estimate": rq7_one_vote["estimate"], "low": rq7_one_vote["low"], "high": rq7_one_vote["high"],
                          "n_sites": len(rq7_new_sites_table), "units_resampled": rq7_one_vote["n_clusters"]}
rq7_estimates = pd.DataFrame(rq7_rows).T.astype(float).astype({"n_sites": int, "units_resampled": int})
rq7_estimates["bootstrap_unit"] = RQ7_BOOTSTRAP_UNIT
show_table(rq7_estimates.round(2))

rq7_cluster_sizes = rq7_new_sites_table[RQ7_BOOTSTRAP_UNIT].value_counts()
rq7_largest_share = pct(rq7_cluster_sizes.head(LARGEST_RQ7_CLUSTERS).sum(), len(rq7_new_sites_table))
by_borough = rq7_sites.groupby("borough", observed=True)
rq7_by_borough = pd.DataFrame({
    "reference_points": rq7_reference.groupby("borough", observed=True).size(),
    "median_crashes_reference": rq7_reference.groupby("borough", observed=True)["baseline_crashes"].median(),
    "sites": by_borough.size(),
    "median_crashes_sites": by_borough["baseline_crashes"].median(),
    "mean_percentile_sites": by_borough["borough_percentile"].mean(),
    "share_above_borough_median_pct": by_borough["borough_percentile"].apply(
        lambda values: PERCENT * (values > NEUTRAL_PERCENTILE).mean()),
})


def rq7_borough_views(new_sites):
    """New construction by borough: site-weighted excess and one vote per cluster, with their intervals.

    A borough under MIN_GROUP_N sites gets no site-weighted statistic and one under MIN_GROUP_N clusters no one-vote one.
    """
    rows = {}
    for borough, group in new_sites.groupby("borough", observed=True):
        percentiles, clusters = group["borough_percentile"].to_numpy(), group[RQ7_BOOTSTRAP_UNIT].to_numpy()
        by_site = (bootstrap_ci(mean_percentile_excess, percentiles, clusters=clusters) if len(group) >= MIN_GROUP_N
                   else {"estimate": float("nan"), "low": float("nan"), "high": float("nan")})
        one_vote = one_vote_per_cluster(percentiles, clusters, min_clusters=MIN_GROUP_N)
        rows[borough] = {"new_sites": len(group), "new_clusters": one_vote["n_clusters"],
                         "new_excess": by_site["estimate"], "new_low": by_site["low"], "new_high": by_site["high"],
                         "new_one_vote_excess": one_vote["estimate"], "new_one_vote_low": one_vote["low"],
                         "new_one_vote_high": one_vote["high"], "new_clusters_above_pct": one_vote["share_above_pct"]}
    return pd.DataFrame(rows).T.rename_axis("borough")


rq7_by_borough = rq7_by_borough.join(rq7_borough_views(rq7_new_sites_table))
show_table(rq7_by_borough.round(1))

# %% [markdown]
# The chart shows how new-construction sites rank: the share of sites in each tenth of the
# borough's street points (blue), and the same sites ranked inside their own ZIP code (orange).
# Typical street locations would give the flat dashed line.

# %%
fig, ax = plt.subplots(figsize=(9, 4.8))
edges = np.arange(0, PERCENT + PERCENTILE_BIN_WIDTH, PERCENTILE_BIN_WIDTH)
for name, column, color in [(RQ7_NEW, "borough_percentile", PALETTE["housing"]),
                            (RQ7_WITHIN_ZIP, "zip_percentile", PALETTE["placebo"])]:
    values = rq7_sites.loc[is_rq7_new, column].dropna()
    row = rq7_estimates.loc[name]
    ax.hist(values, bins=edges, weights=np.full(len(values), PERCENT / len(values)), histtype="step",
            linewidth=2.2, color=color,
            label=f"{name}: mean {NEUTRAL_PERCENTILE + row['estimate']:.1f} "
                  f"({CI_LEVEL:.0%} interval {NEUTRAL_PERCENTILE + row['low']:.1f} to "
                  f"{NEUTRAL_PERCENTILE + row['high']:.1f}; {row['n_sites']:,} sites)")
ax.axhline(PERCENTILE_BIN_WIDTH, color=PALETTE["neutral"], linestyle="--", label="Typical street points (even spread)")
ax.set_xticks(edges)
ax.set_xlim(0, PERCENT)
ax.legend(loc="upper left", fontsize=8.5)
finish(ax, f"RQ7: new-construction sites started after {BASELINE_YEARS[1]} stand where injury crashes were\n"
           f"already above the borough's typical street point",
       f"Percentile among street points: injury crashes within {BUFFER_M} m, {BASELINE_YEARS[0]}-{BASELINE_YEARS[1]}",
       "Share of new-construction sites (%)")
show(fig)

# %%
rq7_new = rq7_estimates.loc[RQ7_NEW]
rq7_by_kind = rq7_sites.groupby(rq7_sites["construction_type"].astype(str))["borough_percentile"].mean()
report("RQ7", "Before the project starts, are new-construction sites on streets with more injury crashes "
       "than typical street locations of the borough?",
       "percentile points above the typical street point of the borough",
       rq7_new["estimate"], rq7_new["low"], rq7_new["high"], int(rq7_new["n_sites"]),
       unit="percentile points",
       n_unit=f"new-construction sites in {int(rq7_new['units_resampled']):,} linked clusters",
       subject=f"The mean borough percentile of new-construction sites before their project started, minus "
               f"{NEUTRAL_PERCENTILE},",
       above="sites standing where there were already more injury crashes than at the typical street point of the borough",
       below="sites standing where there were fewer injury crashes than at the typical street point of the borough",
       extra=f"Both kinds pooled: {rq7_estimates.loc[RQ7_POOLED, 'estimate']:+.1f} "
             f"({rq7_estimates.loc[RQ7_POOLED, 'low']:+.1f} to {rq7_estimates.loc[RQ7_POOLED, 'high']:+.1f}); new "
             f"construction ranked inside its own ZIP code: {rq7_estimates.loc[RQ7_WITHIN_ZIP, 'estimate']:+.1f} "
             f"({rq7_estimates.loc[RQ7_WITHIN_ZIP, 'low']:+.1f} to {rq7_estimates.loc[RQ7_WITHIN_ZIP, 'high']:+.1f}). "
             f"Mean borough percentile by kind: " + ", ".join(f"{kind} {value:.1f}" for kind, value in rq7_by_kind.items())
             + f". Median baseline count: {rq7_sites.loc[is_rq7_new, 'baseline_crashes'].median():.0f} injury crashes at "
               f"new-construction sites against {rq7_reference['baseline_crashes'].median():.0f} at the median of "
               f"{len(rq7_reference):,} street points. The {LARGEST_RQ7_CLUSTERS} largest clusters hold "
               f"{rq7_largest_share:.1f}% of these sites; counting each cluster once gives "
               f"{rq7_one_vote['estimate']:+.1f} ({rq7_one_vote['low']:+.1f} to {rq7_one_vote['high']:+.1f}, "
               f"{rq7_one_vote['n_clusters']:,} clusters), and {rq7_one_vote['share_above_pct']:.1f}% of clusters "
               f"have a mean above {NEUTRAL_PERCENTILE}.")

# %%
rq7_borough_rows = rq7_by_borough[rq7_by_borough["new_one_vote_low"].notna()]
rq7_includes_zero = rq7_borough_rows[(rq7_borough_rows["new_one_vote_low"] <= 0) & (rq7_borough_rows["new_one_vote_high"] >= 0)]
say("One vote per cluster inside each borough (new construction): " + "; ".join(
    f"{borough} {row['new_one_vote_excess']:+.1f} ({row['new_one_vote_low']:+.1f} to {row['new_one_vote_high']:+.1f}, "
    f"{int(row['new_clusters'])} clusters), against {row['new_excess']:+.1f} ({row['new_low']:+.1f} to {row['new_high']:+.1f}) "
    f"counting sites" for borough, row in rq7_borough_rows.iterrows())
    + f". The one-vote interval includes zero in: {', '.join(rq7_includes_zero.index) or 'none'}.")

# %% [markdown]
# **Reading.** Citywide, new-construction sites rank above the typical street point of their
# borough, and that direction holds with whole clusters resampled and with each cluster counted once.
# The size does not: it depends on the weighting, because a few chained clusters with similar
# percentiles hold most of the sites and each draw of the largest one moves the whole interval. Inside a
# borough the site-weighted interval can reach far from its estimate, and where the largest clusters
# stand the one-vote interval includes zero (printed above), so no borough-level direction is claimed
# there. Part of this is neighbourhood and part is street: inside their own ZIP code the excess is smaller but still above
# zero. Apartment buildings stand on dense blocks near avenues and transit, where more people and
# vehicles meet, so this shows where the buildings are, not that the programme picks streets that
# are more dangerous per traveller. For the tenants it means the street outside already had more
# injury crashes than most of the borough before the project started. Requiring a crash within
# `STREET_SNAP_M` in the baseline years drops the quietest streets (raising the benchmark), while edge
# points have part of their buffer over water (lowering it); the net direction is unknown.

# %% [markdown]
# ### 8.8 RQ8. Does the hour-of-day mix of injury crashes near sites shift after completion? (M4)
#
# **Method.** The design of RQ6 with the part of the day (the four `HOUR_BANDS` of Section 4) as the
# category. Crashes logged at exactly 0:00 are left out (`time_unknown`, Section 4), because 0:00 is
# the default for a missing time and would inflate the night. Twenty-four hourly shares were
# rejected as too noisy for this sample. The headline is the largest of the four band gaps; a gap
# picked for being largest is biased away from zero, so all four are shown with the interval widened
# for four tests.

# %%
band_codes = np.where(crashes["time_unknown"].to_numpy(), -1, crashes["hour_band"].cat.codes.to_numpy()).astype(np.int64)
rq8_before, rq8_after = period_category_counts(event_units, site_pairs, crashes, band_codes, len(HOUR_BANDS))
rq8_bands, rq8_sample = composition_shift(event_units, rq8_before, rq8_after, list(HOUR_BANDS), n_boot=N_BOOT_JOINT)
rq8_band_ranges = {name: f"{first:02d}:00-{last:02d}:59" for name, (first, last) in HOUR_BANDS.items()}
say(f"Crashes with an unknown time left out of hour-of-day work: "
    f"{n_pct(crashes['time_unknown'].sum(), len(crashes))}.")
show_table(rq8_bands.drop(columns="flagged").round(2))

# %%
fig, ax = plt.subplots(figsize=(9, 3.4))
interval_rows(ax, [f"{name} ({rq8_band_ranges[name]})" for name in rq8_bands.index],
              rq8_bands["gap"], rq8_bands["low_joint"], rq8_bands["high_joint"],
              title=f"RQ8: change in each part of the day's share of injury crashes within {BUFFER_M} m,\n"
                    f"completed minus comparison sites ({rq8_sample['n_treated_sites']:,} completed sites)",
              xlabel=f"Gap in percentage points ({level_text(rq8_sample['joint_level'])} interval, widened for "
                     f"{len(rq8_bands)} tests)")
show(fig)

# %%
rq8_top_band = rq8_bands["gap"].abs().idxmax()
rq8_top = rq8_bands.loc[rq8_top_band]
report("RQ8", "Does the hour-of-day mix of injury crashes near sites shift after completion?",
       f"percentage points; largest of {len(rq8_bands)} gaps, interval widened for {len(rq8_bands)} tests",
       rq8_top["gap"], rq8_top["low_joint"], rq8_top["high_joint"], rq8_sample["n_treated_sites"],
       unit="percentage points",
       n_unit=f"completed sites in {rq8_sample['n_clusters']:,} clusters, "
              f"{rq8_sample['n_treated_clusters']:,} of them with a completed site",
       level=rq8_sample["joint_level"], adjusted_p=rq8_top["p_adjusted"],
       subject=f"The largest of the {len(rq8_bands)} part-of-day gaps, for the {rq8_top_band.lower()} "
               f"({rq8_band_ranges[rq8_top_band]}), with its interval widened for {len(rq8_bands)} tests,",
       above=f"relatively more injury crashes in the {rq8_top_band.lower()} around completed buildings",
       below=f"relatively fewer injury crashes in the {rq8_top_band.lower()} around completed buildings",
       extra=f"After Benjamini-Hochberg adjustment {int(rq8_bands['flagged'].sum())} of {len(rq8_bands)} bands keep an "
             f"interval away from zero (adjusted p for the {rq8_top_band.lower()}: {rq8_top['p_adjusted']:.2f}). "
             + new_construction_line(rq8_before, rq8_after, list(HOUR_BANDS), rq8_top_band))

# %% [markdown]
# **Reading.** No part of the day shifts detectably: every widened interval crosses zero, and no
# band survives the adjustment. With a six-hour band the interval is a few points wide, so a smaller
# move towards the evening or night would go unseen. The hour is the one the officer wrote down, and
# weekdays and weekends are pooled, so opposite changes on the two would cancel.

# %% [markdown]
# ### 8.9 RQ9. Across ZIP codes, is the share of deeply affordable units associated with the severity of injury crashes or with the pedestrian and cyclist share of harm? (M5)
#
# **Method.** One row per ZIP code of the Section 6 panel: the share of deeply affordable units
# (extremely and very low income) among affordable units completed by `YEAR_END`, against two
# ten-year outcomes, the pedestrian and cyclist share of injury crashes and deaths per
# `PER_THOUSAND` injury crashes. Both are ratios within injury crashes, so the 2020 reporting break
# does not enter them. ZIP codes under `MIN_ZIP_AFFORDABLE_UNITS` units are dropped (their share
# rests on one or two buildings). A raw citywide correlation would mostly compare boroughs, so
# borough means are removed before ranking (Spearman, robust to skew); the two p-values are adjusted
# together.

# %%
MIN_ZIP_AFFORDABLE_UNITS = 50      # units; below this a ZIP's deep share jumps between 0 and 100%
BOROUGH_MARKERS = dict(zip(BOROUGHS, ["o", "s", "^", "D", "v"]))   # shape as a second cue next to colour
RQ9_OUTCOMES = {   # outcome column -> (panel title, unit of a difference)
    "ped_cyc_share_pct": ("Who is hurt: pedestrian and cyclist share of injury crashes", "percentage points"),
    "deaths_per_1000": (f"How severe: deaths per {PER_THOUSAND:,} injury crashes", "deaths"),
}


def zip_equity_table(panel, min_units=MIN_ZIP_AFFORDABLE_UNITS):
    """One row per ZIP code with at least `min_units` affordable units: deep share and the two outcomes."""
    stock = panel[panel["year"] == YEAR_END].set_index("zip")
    totals = panel.groupby("zip")[["injury_crashes", "ped_cyc_crashes", "persons_killed"]].sum()
    table = pd.DataFrame({
        "borough": stock["borough"].astype(str),
        "affordable_units": stock["cum_affordable_units"],
        "deep_share_pct": PERCENT * stock["cum_deep_affordable_units"]
                          / stock["cum_affordable_units"].where(stock["cum_affordable_units"] > 0),
        "ped_cyc_share_pct": PERCENT * totals["ped_cyc_crashes"] / totals["injury_crashes"],
        "deaths_per_1000": PER_THOUSAND * totals["persons_killed"] / totals["injury_crashes"],
    })
    return table[table["affordable_units"] >= min_units]


def deep_share_associations(zip_table):
    """Borough-adjusted (and raw) Spearman correlation of the deep share with each outcome."""
    rows = {}
    for column in RQ9_OUTCOMES:
        deep, outcome = zip_table["deep_share_pct"].to_numpy(), zip_table[column].to_numpy()
        adjusted = group_adjusted_spearman_ci(deep, outcome, zip_table["borough"].to_numpy())
        raw = spearman_ci(deep, outcome)
        rows[column] = {"rho_within_borough": adjusted["estimate"], "low": adjusted["low"], "high": adjusted["high"],
                        "p_value": adjusted["p_value"], "n": adjusted["n"], "n_boroughs": adjusted["n_groups"],
                        "rho_unadjusted": raw["estimate"], "unadjusted_low": raw["low"], "unadjusted_high": raw["high"]}
    result = pd.DataFrame(rows).T
    result["p_adjusted"] = benjamini_hochberg(result["p_value"].to_numpy(dtype=float))
    return result


rq9_zips = zip_equity_table(zip_year)
rq9_result = deep_share_associations(rq9_zips)
show_table(rq9_result.astype(float).round(3))

# %% [markdown]
# Each point is a ZIP code; both axes are differences from the ZIP's own borough mean, which is what
# the coefficient ranks. The dashed least-squares line only guides the eye.

# %%
shown = rq9_zips[rq9_zips.groupby("borough")["borough"].transform("size") >= 2]   # one ZIP: no within-borough variation
deep_within = shown["deep_share_pct"] - shown.groupby("borough")["deep_share_pct"].transform("mean")
fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))
for ax, (column, (title, unit)) in zip(axes, RQ9_OUTCOMES.items()):
    outcome_within = shown[column] - shown.groupby("borough")[column].transform("mean")
    for borough in BOROUGHS:
        in_borough = (shown["borough"] == borough).to_numpy()
        ax.scatter(deep_within[in_borough], outcome_within[in_borough], s=36, color=BOROUGH_COLORS[borough],
                   marker=BOROUGH_MARKERS[borough], edgecolor=PALETTE["neutral"], linewidth=0.5,
                   label=f"{borough} ({int(in_borough.sum())})")
    ends = np.array([deep_within.min(), deep_within.max()])
    ax.plot(ends, linear_slope(deep_within.to_numpy(), outcome_within.to_numpy()) * ends, "--",
            color=PALETTE["neutral"], label="Least-squares line (guide)")
    row = rq9_result.loc[column]
    finish(ax, f"{title}\nwithin-borough rho {row['rho_within_borough']:+.3f} "
               f"({row['low']:+.3f} to {row['high']:+.3f})",
           "Deep-affordable share, difference from borough mean (points)", f"Difference from borough mean ({unit})")
axes[0].legend(title="Borough (ZIP codes)", fontsize=8)
fig.suptitle(f"RQ9: depth of affordability and injury crashes by ZIP code, inside boroughs, {YEAR_START}-{YEAR_END}",
             x=0.01, ha="left", fontweight="bold")
show(fig)

# %%
RQ9_DIGITS = 3   # a correlation is shown to three decimals, and the interval is read at that precision
rq9_ped, rq9_deaths = rq9_result.loc["ped_cyc_share_pct"], rq9_result.loc["deaths_per_1000"]
# One decision rule: the interval as printed (rounded to RQ9_DIGITS) decides "includes zero".
rq9_sentence = describe_effect(
    *(round(float(rq9_ped[key]), RQ9_DIGITS) for key in ["rho_within_borough", "low", "high"]), "", int(rq9_ped["n"]),
    n_unit=f"ZIP codes in {int(rq9_ped['n_boroughs'])} boroughs", digits=RQ9_DIGITS,
    subject="The within-borough rank correlation between the deep-affordable share and the pedestrian and "
            "cyclist share of injury crashes",
    above="a higher pedestrian and cyclist share where the affordable stock is deeper",
    below="a lower pedestrian and cyclist share where the affordable stock is deeper")
rq9_sentence += (f" Bootstrap p = {rq9_ped['p_value']:.3f}, {rq9_ped['p_adjusted']:.3f} after adjustment for the "
                 f"two outcomes.")
say(rq9_sentence)
say(describe_effect(
    *(round(float(rq9_deaths[key]), RQ9_DIGITS) for key in ["rho_within_borough", "low", "high"]), "",
    int(rq9_deaths["n"]), n_unit="ZIP codes", digits=RQ9_DIGITS,
    subject=f"For deaths per {PER_THOUSAND:,} injury crashes the within-borough rank correlation",
    above="more deaths per injury crash where the stock is deeper",
    below="fewer deaths per injury crash where the stock is deeper")
    + f" Adjusted p = {rq9_deaths['p_adjusted']:.3f}. Without the borough adjustment the two correlations are "
      f"{rq9_ped['rho_unadjusted']:+.2f} and {rq9_deaths['rho_unadjusted']:+.2f}; {len(rq9_zips)} of "
      f"{zip_year['zip'].nunique()} ZIP codes have at least {MIN_ZIP_AFFORDABLE_UNITS} affordable units.")
# Stored at the printed precision, so Section 10 applies the same decision rule.
store_result("RQ9", "Across ZIP codes, is the deep-affordable share associated with the pedestrian and cyclist "
             "share of harm?", *(round(float(rq9_ped[key]), RQ9_DIGITS) for key in ["rho_within_borough", "low", "high"]),
             rq9_ped["n"],
             rq9_sentence, "rank correlation within borough", adjusted_p=rq9_ped["p_adjusted"])

# %% [markdown]
# **Reading.** Inside a borough, ZIP codes with a deeper affordable mix lean towards a slightly
# *lower* pedestrian and cyclist share, the opposite of the concern behind the question; at the
# printed precision the interval reaches zero and the adjusted p-value is above the threshold, so it
# is a hint, not a finding. Deaths per injury crash show no association either way. These are area
# data: the housing variable describes financed units, not who was in the crashes. Neighbouring ZIP
# codes resemble each other, which the interval ignores, so it is probably too narrow.

# %% [markdown]
# ### 8.10 RQ10. Which contributing-factor groups are over- or under-represented near completed housing, after against before? (M5)
#
# **Method.** The design of RQ6 with the contributing-factor group of Section 4 as the category.
# Crashes with no factor recorded are left out of the shares (the group is large, says nothing about
# the street, and depends on reporting habits); its own shift is shown as a separate check row.
# Several groups are tested at once, so p-values are Benjamini-Hochberg adjusted and the headline,
# the largest gap, carries the interval widened for the number of groups. Comparing crashes near
# housing with crashes elsewhere was rejected: it would compare dense blocks with highways.

# %%
UNRECORDED_FACTOR = "Unspecified"  # factor group meaning that the report names no factor
UNRECORDED_LABELS = [UNRECORDED_FACTOR, "Recorded factor"]
factor_names = [name for name in crashes["factor_group"].cat.categories if name != UNRECORDED_FACTOR]
factor_codes = pd.Categorical(crashes["factor_group"], categories=factor_names).codes.astype(np.int64)
rq10_before, rq10_after = period_category_counts(event_units, site_pairs, crashes, factor_codes, len(factor_names))
rq10_factors, rq10_sample = composition_shift(event_units, rq10_before, rq10_after, factor_names, n_boot=N_BOOT_JOINT)
rq10_factors = rq10_factors.sort_values("gap", ascending=False)

# The check: share of all injury crashes with no factor named, pooled and for each kind of project.
unrecorded_before, unrecorded_after = period_category_counts(
    event_units, site_pairs, crashes, np.where(crashes["factor_group"] == UNRECORDED_FACTOR, 0, 1), 2)
rq10_unrecorded_by_kind = {
    label: composition_shift(event_units[keep], unrecorded_before[keep], unrecorded_after[keep],
                             UNRECORDED_LABELS)[0].loc[UNRECORDED_FACTOR]
    for label, keep in [("both kinds", np.ones(len(event_units), bool)),
                        ("new construction", units_of_kind(NEW_CONSTRUCTION)),
                        ("preservation", units_of_kind(PRESERVATION))]}
rq10_unrecorded = rq10_unrecorded_by_kind["both kinds"]
show_table(rq10_factors.drop(columns="flagged").round(2))

# %%
check_label = "Check: no factor recorded (share of all)"
fig, ax = plt.subplots(figsize=(9, 5.2))
labels = [f"{name} ({row.treated_before:.0f}%)" for name, row in rq10_factors.iterrows()] + [check_label]
interval_rows(ax, labels, [*rq10_factors["gap"], rq10_unrecorded["gap"]],
              [*rq10_factors["low_joint"], rq10_unrecorded["low"]], [*rq10_factors["high_joint"], rq10_unrecorded["high"]],
              title=f"RQ10: change in each contributing factor's share of injury crashes within {BUFFER_M} m,\n"
                    f"completed minus comparison sites (share before completion in brackets)",
              xlabel=f"Gap in percentage points (groups: {level_text(rq10_sample['joint_level'])} interval widened for "
                     f"{len(rq10_factors)} tests; check: {CI_LEVEL:.0%})")
ax.errorbar(rq10_unrecorded["gap"], 0, xerr=[[rq10_unrecorded["gap"] - rq10_unrecorded["low"]],
                                             [rq10_unrecorded["high"] - rq10_unrecorded["gap"]]],
            fmt="D", capsize=3, color=PALETTE["placebo"])   # the check row (bottom) is not one of the tested groups
ax.axhline(0.5, color=PALETTE["neutral"], linewidth=0.8)
show(fig)

# %%
rq10_top_name = rq10_factors["gap"].abs().idxmax()
rq10_top = rq10_factors.loc[rq10_top_name]
report("RQ10", "Which contributing-factor groups are over- or under-represented near completed housing, "
       "after against before?",
       f"percentage points; largest of {len(rq10_factors)} gaps, interval widened for {len(rq10_factors)} tests",
       rq10_top["gap"], rq10_top["low_joint"], rq10_top["high_joint"], rq10_sample["n_treated_sites"],
       unit="percentage points",
       n_unit=f"completed sites in {rq10_sample['n_clusters']:,} clusters, "
              f"{rq10_sample['n_treated_clusters']:,} of them with a completed site",
       level=rq10_sample["joint_level"], adjusted_p=rq10_top["p_adjusted"],
       subject=f"The largest of the {len(rq10_factors)} factor-group gaps, for \"{rq10_top_name}\" among injury "
               f"crashes with a recorded factor, with its interval widened for {len(rq10_factors)} tests,",
       above=f"a growing share of \"{rq10_top_name}\" around completed buildings",
       below=f"a shrinking share of \"{rq10_top_name}\" around completed buildings",
       extra=f"Groups kept after Benjamini-Hochberg adjustment: {int(rq10_factors['flagged'].sum())} of {len(rq10_factors)} "
             f"(smallest adjusted p = {rq10_factors['p_adjusted'].min():.2f}). "
             + new_construction_line(rq10_before, rq10_after, factor_names, rq10_top_name))
say("Check, gap in the share with no factor recorded: " + "; ".join(
    f"{label} {row['gap']:+.1f} points ({row['low']:+.1f} to {row['high']:+.1f})"
    for label, row in rq10_unrecorded_by_kind.items()) + ".")

# %% [markdown]
# **Reading.** No factor group moves in a way these data can separate from chance: every interval
# crosses zero and none survives the adjustment. The check row does move: the share of reports with
# no factor named fell around completed sites relative to comparison sites, and the split shows it
# belongs to preservation, where nobody new moves in (see 11). It concerns how completely reports
# were filled in, is outside the tested set, and is a caveat for the shares above, which are taken
# among reports with a recorded factor. The factor is the officer's judgement for the first vehicle
# only, and the smallest groups rest on few crashes.

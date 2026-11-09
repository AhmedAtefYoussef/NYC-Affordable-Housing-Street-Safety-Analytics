# %% [markdown]
# ## 10. What we found
#
# One row per research question, read from `RESULTS` exactly as Section 8 stored it. `kept` means
# the interval excludes zero and, where several things were tested together, the adjusted p-value
# is below `FALSE_DISCOVERY_RATE`. A ZIP-level question must also exclude zero on reported ZIP codes
# alone (the rule of Section 9.6). Units differ, so every row names its own.

# %%
OWNERS = {"RQ1": "M1", "RQ2": "M1", "RQ3": "M2", "RQ4": "M2", "RQ5": "M3",
          "RQ6": "M3", "RQ7": "M4", "RQ8": "M4", "RQ9": "M5", "RQ10": "M5"}
# Short chart label, what n counts and what a value right of zero means, per question (labels only).
RESULT_LAYOUT = {
    "RQ1": ("Forecast error when housing is added", "ZIP codes", "right of zero = larger forecast error with housing"),
    "RQ2": ("Injury crashes as the unit stock grows", "ZIP codes", "right of zero = more injury crashes with a larger stock"),
    "RQ3": ("After against before, new buildings", "new-construction sites", "right of zero = more injury crashes after completion"),
    "RQ4": ("Change by units completed nearby", "new-construction sites", "right of zero = larger rise where more units were completed"),
    "RQ5": ("New construction against preservation", "completed sites", "right of zero = change more positive at new construction"),
    "RQ6": ("Pedestrian and cyclist share", "completed sites", "right of zero = share rose more at completed sites"),
    "RQ7": ("Where new sites stand before the project", "new-construction sites",
            "right of zero = more injury crashes than the typical street point"),
    "RQ8": ("Hour of day (largest band gap)", "completed sites", "right of zero = share rose more at completed sites"),
    "RQ9": ("Deep-affordable share and who is hurt", "ZIP codes",
            "right of zero = higher pedestrian and cyclist share where the stock is deeper"),
    "RQ10": ("Contributing factor (largest group gap)", "completed sites", "right of zero = share rose more at completed sites"),
}
SURPLUS_FROM_YEAR = BREAK_YEAR + 1   # first year in which injured totals above their parts appear regularly (4.9)
STAGE_ORDER = ["raw", "cleaned", "integrated"]


# The ZIP-level intervals on reported ZIP codes only (Section 9.6). RQ9 is read at its printed precision.
REPORTED_ZIP_INTERVALS = {
    "RQ1": (float(reported_forecast["low"]), float(reported_forecast["high"])),
    "RQ2": (float(reported_stock["low_pct"]), float(reported_stock["high_pct"])),
    "RQ9": (round(float(reported_ped["low"]), RQ9_DIGITS), round(float(reported_ped["high"]), RQ9_DIGITS)),
}


def interval_excludes_zero(low, high):
    """True when the whole interval lies on one side of zero."""
    return bool(low > 0 or high < 0)


rows = []
for key, (label, n_unit, direction) in RESULT_LAYOUT.items():
    stored = RESULTS[key]
    excludes_zero = interval_excludes_zero(stored["ci_low"], stored["ci_high"])
    adjusted_p = stored["adjusted_p"]
    # None for a question that is not at ZIP level, where the rule of Section 9.6 does not apply.
    excludes_zero_reported = (interval_excludes_zero(*REPORTED_ZIP_INTERVALS[key])
                              if key in REPORTED_ZIP_INTERVALS else None)
    rows.append({"rq": key, "owner": OWNERS[key], "label": label, "question": stored["question"],
                 "estimate": stored["estimate"], "low": stored["ci_low"], "high": stored["ci_high"],
                 "level": stored["level"], "unit": stored["unit"], "n": stored["n"], "n_unit": n_unit,
                 "direction": direction, "adjusted_p": float("nan") if adjusted_p is None else adjusted_p,
                 "excludes_zero": excludes_zero, "excludes_zero_reported": excludes_zero_reported,
                 "kept": (excludes_zero and (adjusted_p is None or adjusted_p < FALSE_DISCOVERY_RATE)
                          and excludes_zero_reported is not False)})
summary_table = pd.DataFrame(rows).set_index("rq")
assert set(summary_table.index) == set(RESULTS), "every research question stores exactly one result"
digits = [3 if "correlation" in unit else 2 for unit in summary_table["unit"]]
show_table(pd.DataFrame({
    "owner": summary_table["owner"], "question": summary_table["question"],
    "estimate (interval)": [f"{row.estimate:+.{d}f} ({row.low:+.{d}f} to {row.high:+.{d}f}, {level_text(row.level)})"
                            for row, d in zip(summary_table.itertuples(), digits)],
    "unit": summary_table["unit"], "n": [f"{n:,} {u}" for n, u in zip(summary_table["n"], summary_table["n_unit"])],
    "kept": summary_table["kept"].map({True: "yes", False: "no"})}))

# %% [markdown]
# The same ten rows, each on its own axis (a percentage, a correlation and a percentile cannot share
# a scale, so interval widths are not comparable between panels). Blue = kept.

# %%
fig, axes = plt.subplots(5, 2, figsize=(12, 11))
for ax, (key, row) in zip(axes.ravel(), summary_table.iterrows()):
    color = PALETTE["treated"] if row["kept"] else PALETTE["control"]
    ax.errorbar(row["estimate"], 0, xerr=[[row["estimate"] - row["low"]], [row["high"] - row["estimate"]]],
                fmt="o", color=color, capsize=3, linewidth=2.5)
    ax.axvline(0, color=PALETTE["neutral"], linestyle="--", linewidth=1)
    reach = max(abs(row["low"]), abs(row["high"]))
    ax.set_xlim(min(row["low"], 0) - 0.25 * reach, max(row["high"], 0) + 0.25 * reach)
    ax.set_yticks([])
    finish(ax, f"{key}  {row['label']} (n = {row['n']:,})", f"{row['unit']}\n{row['direction']}", "")
    ax.title.set_fontsize(10)
    ax.xaxis.label.set_fontsize(8.5)
fig.suptitle(f"The ten headline estimates with their bootstrap intervals ({level_text(CI_LEVEL)}; widened to "
             f"{level_text(summary_table.loc['RQ8', 'level'])} for RQ8 and {level_text(summary_table.loc['RQ10', 'level'])} for RQ10)",
             x=0.01, ha="left", fontweight="bold")
show(fig)

# %%
kept = summary_table.index[summary_table["kept"]].tolist()
not_kept = summary_table.index[summary_table["excludes_zero"] & ~summary_table["kept"]].tolist()
say(f"Intervals that exclude zero and are kept: {', '.join(kept) or 'none'}. Excluding zero but not kept, after "
    f"adjustment or because the interval includes zero on reported ZIP codes: {', '.join(not_kept) or 'none'}. All "
    f"others include zero. The ten intervals are not adjusted for each other, so one can exclude zero by chance.")

# RQ1 on reported ZIP codes only (Section 9.6): the footnote reads its numbers from the stored objects.
rq1_low, rq1_high = float(reported_forecast["low"]), float(reported_forecast["high"])
rq1_reading = "improved the forecast" if rq1_high < 0 else "did not improve the forecast"
say(f"*RQ1 footnote.* On ZIP codes with a police-reported code only (Section 9.6) the change in forecast error is "
    f"{float(reported_forecast['mae_minus_baseline']):+.2f} ({rq1_low:+.2f} to {rq1_high:+.2f}), so on those codes housing "
    f"{rq1_reading}. With either version of the data, housing did not improve the forecast; the \"kept\" mark needs "
    f"the interval to exclude zero on both versions.")

# %% [markdown]
# **Findings, one line per question.** RQ1: housing information did not improve a ZIP-level crash
# forecast. RQ2: the slope on the whole affordable stock cannot be told from zero, but that reading
# depends on one refinanced ZIP and on counting refinanced units as stock (9.6). RQ3: around isolated new buildings, injury crashes changed after completion about as much
# as around unfinished sites of the same programme. RQ4: no relation with the number of units
# completed. RQ5: new construction cannot be told apart from preservation. RQ6, RQ8, RQ10: no
# detectable shift in who is hurt, the time of day or the recorded cause. RQ7: new-construction
# sites stand where injury crashes were already above the borough's typical street point before the
# project started; citywide that direction holds, and its size depends on whether sites or clusters
# are counted. RQ9: a weak, not-kept hint that ZIP codes with a deeper affordable mix have a lower
# pedestrian and cyclist share. Section 9 changed the radius, outcome, strata, cohorts, clusters and
# screen, and the RQ3 reading held in the versions that kept the screen and the whole comparison group.
# Cutting the comparison group by start date or type moves the estimate, and some cuts exclude zero;
# those cuts are unadjusted, so they do not show a fall, but they limit how far "no change" can be read.
#
# **Answer to the main question.** For the buildings we could isolate, the crash records do not show
# the feared rise after an affordable building opens, but the intervals leave room for a moderate
# fall or a small rise. What the records do show is where the buildings are: on streets that already
# had many injury crashes (RQ7), though how far above the typical street depends on whether a building
# or a cluster of buildings is the unit.
#
# ### 10.1 What surprised us

# %%
last_year = city_year.loc[city_year["year"] == YEAR_END].iloc[0]
central_row = robustness_table.loc[robustness_table["kind"] == KIND_CENTRAL].iloc[0]
all_crash_row = robustness_table.loc[robustness_table["check"] == CHECK_OUTCOME].iloc[0]
cluster_counts = sites["cluster_id"].value_counts()
treated_candidates = event_panel[(event_panel["group"] == "treated") & (event_panel["rel_year"] == 0)]
surplus = crashes[crashes["other_injured"] > 0]
facts = {
    "crash_index": float(last_year["crash_index"]), "injury_index": float(last_year["injury_crash_index"]),
    "all_crash_change": log_points_to_percent(all_crash_row["treated_change"]),
    "injury_change": log_points_to_percent(central_row["treated_change"]),
    "all_crash_difference": float(all_crash_row["percent_change"]),
    "sites": len(sites), "share_in_largest": pct(cluster_counts.head(LARGEST_CLUSTERS_SHOWN).sum(), len(sites)),
    "median_neighbours": float(sites["n_sites_within_buffer"].median()),
    "treated_candidates": len(treated_candidates), "treated_clean": int((~treated_candidates["contaminated"]).sum()),
    "surplus_crashes": len(surplus), "surplus_share_late": pct((surplus["year"] >= SURPLUS_FROM_YEAR).sum(), len(surplus)),
}
say(f"With {INDEX_BASE_YEAR} = 100, all reported crashes stand at {facts['crash_index']:.0f} in {YEAR_END} and injury "
    f"crashes at {facts['injury_index']:.0f}. Near the RQ3 buildings all crashes change by "
    f"{facts['all_crash_change']:+.0f}% after completion and injury crashes by {facts['injury_change']:+.0f}%. The "
    f"{LARGEST_CLUSTERS_SHOWN} largest clusters hold {facts['share_in_largest']:.0f}% of {facts['sites']:,} sites; the "
    f"median site has {facts['median_neighbours']:.0f} others within {BUFFER_M} m; only {facts['treated_clean']:,} of "
    f"{facts['treated_candidates']:,} completed sites had no other completion nearby in their window. "
    f"{facts['surplus_crashes']:,} crashes report more injured than pedestrians, cyclists and motorists together, "
    f"{facts['surplus_share_late']:.0f}% of them from {SURPLUS_FROM_YEAR} on.")

# %% [markdown]
# - **The record-keeping drop.** Counted as all crashes, streets near a new building seem to lose a
#   large part of their crashes after completion. The same fall appears everywhere, because
#   property-damage reports dropped in 2020. Without injury crashes and comparison sites we would
#   have reported a large safety gain that was only record keeping.
# - **How tightly the programme is packed.** Most buildings have other financed buildings within the
#   buffer, so the before/after comparison rests on far fewer buildings than the table has rows.
# - **Housing did not help a forecast** of ZIP-level injury crashes.
# - **Injured totals stopped adding up** after the break; e-scooter and e-bike crashes are
#   over-represented among them (4.9), which fits riders counted outside the three categories.
#
# ## 11. What the data cannot tell us
#
# Each caveat is stated here once; Sections 8 and 9 point back to it.

# %%
confidential = housing["is_confidential"]
panel_crashes = crashes[crashes["in_zip_panel"]]
first_year = crashes[crashes["year"] == YEAR_START]
limits = {
    "confidential_rows": int(confidential.sum()), "confidential_row_share": pct(confidential.sum(), len(housing)),
    "confidential_unit_share": pct(housing.loc[confidential, "total_units"].sum(), housing["total_units"].sum()),
    "same_day_share": pct(housing["same_day_completion"].sum(), housing["is_completed"].sum()),
    "unlocated_share": pct((~crashes["is_located"]).sum(), len(crashes)),
    "unlocated_share_first_year": pct((~first_year["is_located"]).sum(), len(first_year)),
    "outside_panel_share": pct((~crashes["in_zip_panel"]).sum(), len(crashes)),
    "imputed_zip_share": pct(panel_crashes["zip_imputed"].sum(), len(panel_crashes)),
    "no_factor_share": pct((crashes["factor_group"] == UNRECORDED_FACTOR).sum(), len(crashes)),
    "headline_intervals": len(RESULTS), "robustness_intervals": len(robustness_table),
}
say(f"Housing: {limits['confidential_rows']:,} confidential rows ({limits['confidential_row_share']:.1f}%, "
    f"{limits['confidential_unit_share']:.2f}% of units) cannot be located; {limits['same_day_share']:.0f}% of "
    f"completed rows have a completion date equal to the start date. Crashes: {limits['unlocated_share']:.1f}% "
    f"lack usable coordinates ({limits['unlocated_share_first_year']:.1f}% in {YEAR_START}); "
    f"{limits['outside_panel_share']:.1f}% fall outside the ZIP panel and {limits['imputed_zip_share']:.1f}% of those "
    f"inside it have a recovered ZIP code; {limits['no_factor_share']:.1f}% name no contributing factor. Tests: "
    f"{limits['headline_intervals']} headline intervals and {limits['robustness_intervals']} robustness specifications.")

# %% [markdown]
# - **Association, not cause.** Sites are not placed at random (RQ7). Completed sites are compared
#   with unfinished sites of the same programme, but the groups still differ (the estimate moves when
#   that group is cut by start date or type, 9.4), and streets also get bike lanes, rezonings or
#   rebuilt junctions that neither table records. For a new building the "before" years are
#   construction years, and many completion dates are administrative.
# - **The 2020 reporting break.** Property-damage reports collapsed in 2020 and the pandemic changed
#   traffic for months; every three-year window contains that year. Injury crashes and comparison
#   sites are the defence (9.1), and no cohort lets us look at a completion without the pandemic.
# - **Preservation brings no new residents.** It is the placebo of RQ5. The two side results that
#   exclude zero, the RQ2 completion-year slope and the RQ10 drop in reports with no factor, are both
#   found for preservation and absent for new construction, so neither says what new housing does.
# - **The less dense part of the programme.** The screen keeps only sites without another completion
#   nearby, so RQ3 to RQ6, RQ8 and RQ10 describe the edges of the programme; inside dense clusters the
#   only estimates are those without the screen (9.2).
# - **E-scooter and e-bike riders are missing** from the pedestrian and cyclist columns, so those
#   shares understate harm to people outside cars. Crashes are police-reported only, and nothing
#   measures traffic, so a count of injury crashes is not a risk per trip.
# - **Location gaps.** Unlocated crashes are most common in the first study year (9.4); recovered ZIP
#   codes can be wrong at boundaries (9.6); confidential housing rows are mostly single homes, so the
#   spatial results describe buildings with a published address.
# - **Areas are not streets.** RQ1, RQ2 and RQ9 compare ZIP codes; they say nothing about one corner.
# - **Many tests.** We adjusted inside each question but not across the notebook.
# - **Only financed housing.** Market-rate buildings are in neither table, so a comparison street may
#   have gained a private tower unseen, and RQ7 cannot compare with other apartment buildings.
#
# ## 12. Who can use this
#
# - **Department of Transportation / Vision Zero.** The housing table lists financed buildings
#   before completion, and new-construction addresses lean towards streets with many injury crashes
#   (RQ7). Street work could be scheduled along that pipeline. Any before/after evaluation spanning
#   2020 should count injury crashes and use comparison streets (9.1).
# - **Housing Preservation and Development and developers.** Around the sites we could isolate, a
#   completion was not followed by a detectable change in nearby injury crashes (RQ3 to RQ5); this is
#   one input when traffic safety comes up in a project review, with the caveat that the interval
#   allows a moderate change either way. A separate move-in date in the table would sharpen every
#   before/after comparison.
# - **Community boards** could ask for street improvements on the strength of the existing crash
#   record (RQ7) rather than tie them to the building.
# - **Residents** can read RQ6, RQ8 and RQ10 as "no detectable change in who is hurt, when, or why",
#   within intervals several points wide.
#
# ## 13. Contributions
#
# | Member | Name | Research questions and charts | Data cleaning | Integration | Website | Other work |
# |---|---|---|---|---|---|---|
# | M1 | Ahmed Atef | RQ1 forecast comparison (dot plot of forecast error); RQ2 within-ZIP slopes (coefficient plot with leads and lags) | Housing: blank unit counts, duplicates, geographic identifiers, dates, unit consistency, size outliers (4.1-4.6) | ZIP by year panel (5.2) | Dropdown filters and the Generate report button | Setup and data loading (1, 2), housing exploration (3.3), README run steps |
# | M2 | Nour Mostafa Aly | RQ3 event study (lines with interval bands); RQ4 building size (scatter with fitted slope) | Crashes: key, duplicates, dates, time of day, borough and ZIP (4.7, 4.8) | Ball-tree distance join, choice of the 250 m buffer (5.3) | Event-study cards and the bootstrap callback | Crash exploration (3.4), bootstrap and difference-in-differences toolkit (7) |
# | M3 | Yahia Mohamed | RQ5 new construction vs preservation (interval plot); RQ6 pedestrian and cyclist share by borough (interval plot) | Crashes: coordinates, casualty totals, extreme injury counts, factor groups (4.8-4.11) | Sites, clusters and the nearby-completion screen (5.4) | Search box and query parser | Robustness checks (9), data dictionary |
# | M4 | Moaz Ahmed | RQ7 site selection (percentile histogram); RQ8 hour of day (interval plot of day parts) | ZIP recovery from coordinates and its holdout validation (6.1) | Tagging crashes with their nearest site (5.5), conservation checks (6.4) | Map and heat-map cards, page layout, accessibility | Deployment configuration, architecture notes |
# | M5 | Yassin Fady | RQ9 deep-affordable share across ZIP codes (scatter by borough); RQ10 contributing factors (interval plot) | Post-integration cleaning: borough, redundant columns, data types (6.2, 6.3) | Cumulative stock and citywide index (6.2, 6.5), final schema | Findings and data-and-method sections of the page | Findings, limits, impact, reproducibility (10-14), hosting |
#
# Each member reviewed the code and text of their own two questions and can explain them.
#
# ## 14. Reproducibility
#
# Put the notebook in any folder and run all cells. If `housing_hg8x-zxpr.csv` and
# `crashes_h9gi-nx95.csv.gz` are missing, Section 2 downloads them from NYC Open Data (several minutes
# for the crash table); later runs work offline. Delete the two files to refresh the data. Every
# random step uses the seed of Section 1, so a rerun on the same files gives the same numbers. The
# written readings were checked against the copy dated below. Website code:
# https://github.com/AhmedAtefYoussef/Data-Engineering-Visualization-Project

# %%
stages = pd.DataFrame([
    ("raw", "housing, as loaded", len(raw_housing)),
    # The raw crash frame is released after Section 4, so its length is read from the cleaning log.
    ("raw", "crashes, as loaded", next(e["rows_before"] for e in CLEANING_LOG if e["dataset"] == "crashes")),
    ("cleaned", "housing: one row per project and building", len(housing)),
    ("cleaned", "crashes: one row per collision", len(crashes)),
    ("integrated", "zip_year: ZIP code by year", len(zip_year)),
    ("integrated", "sites: located buildings", len(sites)),
    ("integrated", "site_year: site by year", len(site_year)),
    ("integrated", "event_panel: site by cohort by relative year", len(event_panel)),
    ("integrated", "crashes tagged with ZIP code and nearest site", len(crashes)),
], columns=["stage", "table", "rows"])
stages["stage"] = pd.Categorical(stages["stage"], categories=STAGE_ORDER, ordered=True)
stages = stages.set_index(["stage", "table"])
assert stages.loc[("raw", "crashes, as loaded"), "rows"] == len(crashes), "cleaning keeps every crash"
assert crashes["collision_id"].is_unique and not zip_year.duplicated(["zip", "year"]).any()
show_table(stages)
show_table(pd.DataFrame({"version": {
    "Python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
    "scipy": scipy.__version__, "scikit-learn": sklearn.__version__, "matplotlib": mpl.__version__,
    "seaborn": sns.__version__, "requests": requests.__version__, "pyarrow": pyarrow.__version__}}))


def file_stamp(path):
    """Date on which a local data file was last written (the day it was downloaded)."""
    return pd.Timestamp(path.stat().st_mtime, unit="s").strftime("%Y-%m-%d")


say(f"Seed {SEED}; {N_BOOT:,} bootstrap resamples per interval ({N_BOOT_JOINT:,} for the tables of RQ8 and RQ10); "
    f"study window {YEAR_START}-{YEAR_END}. Data as of: "
    f"latest crash {crashes['crash_date'].max():%Y-%m-%d}, latest housing completion "
    f"{housing['completion_date'].max():%Y-%m-%d}; housing file saved {file_stamp(HOUSING_FILE)}, crash file "
    f"{file_stamp(CRASH_FILE)}.")

# %% [markdown]
# ## 15. Prompts and AI use
#
# The project brief asks the notebook to contain the prompts used. Claude models (through Claude
# Code) drafted the code and text under the team's direction; the notebook and website call no model.
# The key prompt patterns were:
#
# - **A request with the project description attached**, asking to analyse the data catalogue, pick
#   the datasets, split the work among assistants and audit the result against the requirements.
# - **One shared brief for every section author**, with checkable rules: injury crashes as the primary
#   outcome because of the 2020 break, the two integration levels (ZIP x year, 250 m proximity), no
#   data-derived number typed into markdown, an `assert` for each invariant, one chart per question,
#   no causal wording.
# - **Ownership boundaries:** each assistant edited one file and reported the interface it provides.
# - **Reviewers who read but do not edit**, returning findings with location, severity and fix, then
#   fix passes by the authors, each run on the real data before acceptance.
# - **Model tiering:** a stronger model for design and review, a cheaper one for routine code.
#
# The prompt texts and the build process are in `docs/AI_USE.md`.

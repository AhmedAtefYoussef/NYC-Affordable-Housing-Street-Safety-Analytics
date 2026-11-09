# %% [markdown]
# ## 6. Post-integration cleaning
#
# Section 4 cleaned each table by itself. Some problems only exist once the tables meet, and the
# naive panel of 5.2 showed them: cells that became missing because one side had no row, a housing
# ZIP the crash table never uses, and many crashes absent because they carry no ZIP. This section
# repairs what can be repaired, counts what cannot, fixes the form of the integrated tables, and
# records each rule in the same log as Section 4.
#
# | Problem created by integration | Where |
# |---|---|
# | New missing values from the joins | 6.1 |
# | Inconsistent or redundant columns | 6.2 |
# | Data type mismatches between the tables | 6.3 |
# | Conservation of rows and totals | 6.4 |
# | A citywide reference series | 6.5 |

# %%
# --- Constants for Section 6 ------------------------------------------------------------------
ZIP_FINE_CANDIDATES = [0.0005, 0.001, 0.002]   # fine grid cells tried for the ZIP vote (degrees)
ZIP_COARSE_DEGREES = 0.004                       # fallback cell when the fine cell has no labelled crash
BOROUGH_CELL_DEGREES = (0.004, 0.016, 0.05)      # cascade for the borough vote (a borough is large)
SELECT_SHARE, TEST_SHARE = 0.10, 0.10            # shares of crash locations held out to choose and to test
CELL_KEY_BASE = 10_000_000                       # cell key = row * base + column; |column| stays far below it
# Street names that mark highways, bridges, tunnels and ramps, where few crashes report a ZIP.
HIGHWAY_PATTERN = (r"EXPRESSWAY|EXPWY|EXPY|PARKWAY|PKWY|HIGHWAY|HWY|BRIDGE|BRDG|RAMP|TUNNEL|THRUWAY|"
                   r"TURNPIKE|\bFDR\b|HENRY HUDSON|HARLEM RIVER DR|MAJOR DEEGAN|\bBQE\b|\bBELT\b")
# A report contradicts its location when its ~5 km area has many reports and nearly all name another borough.
CONFLICT_CELL_DEGREES, CONFLICT_MIN_REPORTS, CONFLICT_MIN_SHARE = 0.05, 200, 0.99
# A ZIP needs this many crashes over the study years (50 a year) to enter the panel; smaller codes
# are single office towers or post-office codes, not neighbourhoods.
MIN_ZIP_CRASHES = 500
INDEX_BASE = 100               # the index equals this value in INDEX_BASE_YEAR (Section 1)
PER_THOUSAND = 1000            # deaths are expressed per 1,000 injury crashes
AXIS_HEADROOM = 1.15           # axes extend this factor past the largest value so labels fit
POST_LOG_START = len(CLEANING_LOG)   # rules logged from here on belong to this section

# %% [markdown]
# ### 6.1 New missing values created by the joins
#
# The naive panel's gaps are restated as counts so that the same table can be shown after the
# repair. The three kinds of gap of 5.2 get three treatments: a ZIP-year without completions is a
# known zero and is filled with 0 (a mean would invent completions); a housing ZIP the crash
# table never uses gets no zero and is left out with its units counted; crashes without a ZIP
# are given one from their coordinates where possible.

# %%
def panel_gap_report(panel, crash_frame):
    """Counts that describe how complete a ZIP x year table is against the crash table."""
    measures = [column for column in HOUSING_PANEL_MEASURES + CRASH_PANEL_MEASURES if column in panel]
    crashes_placed = int(panel["crashes"].sum())
    return {
        "rows": len(panel), "ZIP codes": panel["zip"].nunique(),
        "rows missing from a balanced panel": panel["zip"].nunique() * N_STUDY_YEARS - len(panel),
        "missing cells": int(panel[measures].isna().sum().sum()),
        "crashes placed in a row": crashes_placed,
        "% of all crashes placed": round(pct(crashes_placed, len(crash_frame)), 1),
        "crashes with no ZIP": int(crash_frame["zip"].isna().sum()),
    }


gaps_before = panel_gap_report(naive_panel, crashes)

# %% [markdown]
# #### 6.1.1 Recovering the ZIP of a crash from its coordinates
#
# No boundary file is used, but most crashes report both a ZIP and coordinates, so the crash table
# can teach the boundaries itself. The city is divided into square cells and each cell takes the
# ZIP reported most often inside it; a crash without a ZIP takes the ZIP of its cell, falling back
# to a coarser cell when its fine cell holds no labelled crash. One helper, `cell_mode`, does the
# vote here, for the borough in 6.2 and for the screen of contradictory reports.
#
# The accuracy test must hide whole locations, not single rows: crashes are recorded at
# intersections, and a hidden crash usually has a twin at exactly the same point that would vote
# for it. The labelled crashes are therefore split by exact coordinate into a training part, a
# selection part (to choose the fine cell size) and a separate test part (to report accuracy).
# Two alternatives were rejected: the ZIP of the single nearest crash (one mislabelled report
# would decide everything around it), and leaving the ZIP missing (three of the ten research
# questions, RQ1, RQ2 and RQ9, are ZIP-level).

# %%
def cell_key(lat, lon, cell_degrees):
    """One int64 per square grid cell of side `cell_degrees` degrees."""
    row = np.floor(np.asarray(lat, dtype="float64") / cell_degrees).astype("int64")
    column = np.floor(np.asarray(lon, dtype="float64") / cell_degrees).astype("int64")
    return row * CELL_KEY_BASE + column


def cell_mode(lat, lon, labels, cell_degrees):
    """Per grid cell: the most frequent label (ties to the lowest), its share and the number of reports."""
    votes = (pd.DataFrame({"cell": cell_key(lat, lon, cell_degrees), "label": np.asarray(labels, dtype=object)})
             .value_counts().rename("votes").reset_index()
             .sort_values(["cell", "votes", "label"], ascending=[True, False, True]))
    reports = votes.groupby("cell")["votes"].sum()
    top = votes.drop_duplicates("cell").set_index("cell")
    return pd.DataFrame({"label": top["label"], "share": top["votes"] / reports, "reports": reports})


def learn_lookups(frame, column, cell_sizes):
    """One `cell_mode` lookup of `column` per cell size, finest first."""
    return [(size, cell_mode(frame["lat"], frame["lon"], frame[column], size)) for size in cell_sizes]


def label_from_cells(lat, lon, lookups):
    """Label of each point from the first lookup whose cell holds a vote; level 0 = no lookup covers it."""
    label = np.full(len(lat), None, dtype=object)
    level = np.zeros(len(lat), dtype="int8")
    for number, (size, modes) in enumerate(lookups, start=1):
        found = pd.Series(cell_key(lat, lon, size)).map(modes["label"]).to_numpy(dtype=object)
        fill = (level == 0) & pd.notna(found)
        label[fill], level[fill] = found[fill], number
    return label, level


def contradicts_area(reports):
    """True for reports whose borough differs from the one nearly every report in their wide area gives."""
    with_borough = reports[reports["borough"].notna()]
    borough = with_borough["borough"].astype(str)
    areas = cell_mode(with_borough["lat"], with_borough["lon"], borough, CONFLICT_CELL_DEGREES)
    settled = areas.loc[(areas["reports"] >= CONFLICT_MIN_REPORTS) & (areas["share"] >= CONFLICT_MIN_SHARE), "label"]
    expected = pd.Series(cell_key(with_borough["lat"], with_borough["lon"], CONFLICT_CELL_DEGREES),
                         index=with_borough.index).map(settled)
    return (expected.notna() & (expected != borough)).reindex(reports.index, fill_value=False)


# The recovery overwrites `zip`; a second run would find nothing left to recover.
assert "zip_imputed" not in crashes.columns, "6.1 has already run on this `crashes`; restart and run all"
labelled = crashes.loc[crashes["is_located"] & crashes["zip"].notna(), ["lat", "lon", "zip", "borough"]]
zip_targets = crashes["is_located"].to_numpy() & crashes["zip"].isna().to_numpy()

# Split by exact location, so that all crashes at one point fall in the same part.
location = labelled.groupby(["lat", "lon"], sort=False).ngroup().to_numpy()
draw = np.random.default_rng(SEED).random(location.max() + 1)[location]
part = np.where(draw < SELECT_SHARE, "select", np.where(draw < SELECT_SHARE + TEST_SHARE, "test", "train"))
train_all = labelled[part == "train"]
# Reports that their own coordinates contradict (for example a Brooklyn ZIP on a point in Staten
# Island) are not used as evidence; on a highway one of them could decide a whole cell. The screen
# sees the training part only.
train_rows = train_all[~contradicts_area(train_all).to_numpy()]
select_rows, test_rows = labelled[part == "select"], labelled[part == "test"]

# Choose the fine cell on the selection part: share of rows given the reported ZIP (uncovered = wrong).
cell_trial_rows = []
for fine in ZIP_FINE_CANDIDATES:
    predicted, level = label_from_cells(select_rows["lat"], select_rows["lon"],
                                        learn_lookups(train_rows, "zip", (fine, ZIP_COARSE_DEGREES)))
    cell_trial_rows.append({"fine cell (degrees)": f"{fine:g}", "fine cell side (m)": round(fine * METRES_PER_DEGREE),
                            "answered by the fine cell (%)": 100 * (level == 1).mean(),
                            "correct (% of selection rows)": 100 * (predicted == select_rows["zip"].to_numpy(dtype=object)).mean()})
cell_comparison = pd.DataFrame(cell_trial_rows).set_index("fine cell (degrees)")
display(cell_comparison.round(2))
ZIP_CELL_DEGREES = (float(cell_comparison["correct (% of selection rows)"].idxmax()), ZIP_COARSE_DEGREES)

# %% [markdown]
# The chosen cascade is then scored once on the untouched test locations, overall and on crashes
# on highways, bridges, tunnels and ramps (found by street name in the raw file). Those roads
# matter because few of their crashes report a ZIP, so they are a far larger share of the rows to
# fill than of the rows used to test.

# %%
street = pd.read_csv(CRASH_FILE, usecols=["collision_id", "on_street_name"], dtype="string[pyarrow]")
street["collision_id"] = pd.to_numeric(street["collision_id"], errors="coerce")
street = street.dropna(subset=["collision_id"]).drop_duplicates("collision_id")
on_highway_by_id = street.set_index(street["collision_id"].astype("int64"))["on_street_name"].str.upper().str.contains(
    HIGHWAY_PATTERN, regex=True).fillna(False).astype(bool)
on_highway = crashes["collision_id"].astype("int64").map(on_highway_by_id).fillna(False).to_numpy(bool)

test_predicted, test_level = label_from_cells(test_rows["lat"], test_rows["lon"],
                                              learn_lookups(train_rows, "zip", ZIP_CELL_DEGREES))
test_correct = test_predicted == test_rows["zip"].to_numpy(dtype=object)
test_highway = on_highway[test_rows.index]
accuracy_rows = {}
for name, rows in [("all test crashes", np.ones(len(test_rows), bool)), ("highway, bridge or ramp", test_highway),
                   ("other streets", ~test_highway)]:
    covered = rows & (test_level > 0)
    accuracy_rows[name] = {"test crashes": int(rows.sum()), "covered (%)": pct(covered.sum(), rows.sum()),
                           "fine cell (% of covered)": pct((rows & (test_level == 1)).sum(), covered.sum()),
                           "accuracy where covered (%)": 100 * test_correct[covered].mean()}
zip_accuracy = pd.DataFrame(accuracy_rows).T
display(zip_accuracy.round(2))

holdout_accuracy = zip_accuracy.loc["all test crashes", "accuracy where covered (%)"]
highway_share_labelled = 100 * on_highway[labelled.index].mean()
highway_share_targets = 100 * on_highway[zip_targets].mean()
# Expected accuracy on the rows actually filled: test accuracy reweighted to their highway share.
expected_accuracy = (highway_share_targets * zip_accuracy.loc["highway, bridge or ramp", "accuracy where covered (%)"]
                     + (100 - highway_share_targets) * zip_accuracy.loc["other streets", "accuracy where covered (%)"]) / 100
say(f"{pct(labelled.duplicated(['lat', 'lon'], keep=False).sum(), len(labelled)):.1f}% of labelled crashes share "
    f"their exact coordinates with another, which is why the holdout hides whole locations. The fine cell of "
    f"{ZIP_CELL_DEGREES[0]:g} degrees (about {ZIP_CELL_DEGREES[0] * METRES_PER_DEGREE:.0f} m) scores best on the "
    f"selection part. On the test locations the recovered ZIP equals the reported one for "
    f"{holdout_accuracy:.2f}% of covered crashes. Highways, bridges and ramps are "
    f"{highway_share_labelled:.1f}% of labelled crashes but {highway_share_targets:.1f}% of the crashes to fill, "
    f"and there the accuracy is {zip_accuracy.loc['highway, bridge or ramp', 'accuracy where covered (%)']:.1f}%. "
    f"Reweighted to that mix the expected accuracy of the filled values is about {expected_accuracy:.1f}%. Both "
    f"figures are upper bounds: the rows to fill lie, by definition, where fewer neighbours report a ZIP.")

# %% [markdown]
# Most remaining errors are intersections on a ZIP boundary, reported with either code. The lookup
# is now learned from all labelled crashes (minus contradictory reports) and applied; `zip_imputed`
# marks every filled row so any result can be recomputed on reported ZIPs only.

# %%
location_conflict = contradicts_area(labelled).reindex(crashes.index, fill_value=False)
zip_lookups = learn_lookups(labelled[~location_conflict[labelled.index].to_numpy()], "zip", ZIP_CELL_DEGREES)
recovered_zip, recovered_level = label_from_cells(crashes["lat"].to_numpy()[zip_targets],
                                                  crashes["lon"].to_numpy()[zip_targets], zip_lookups)

zip_missing_before = crashes["zip"].isna().to_numpy()
zip_reported = crashes["zip"].copy()
filled_zip = crashes["zip"].to_numpy(dtype=object)
filled_zip[zip_targets] = recovered_zip
crashes["zip"] = pd.Series(filled_zip).where(pd.notna(filled_zip), pd.NA).astype(zip_reported.dtype)
crashes["zip_imputed"] = zip_reported.isna().to_numpy() & crashes["zip"].notna().to_numpy()
zip_missing_after = crashes["zip"].isna().to_numpy()

n_imputed = int(crashes["zip_imputed"].sum())
n_no_cell = int((zip_targets & zip_missing_after).sum())
n_no_location = int((~crashes["is_located"].to_numpy() & zip_missing_after).sum())
# Reported ZIPs are untouched, filled values are ZIPs the crash table already uses, and every gap is counted.
assert crashes.loc[zip_reported.notna(), "zip"].eq(zip_reported.dropna()).all()
assert set(crashes.loc[crashes["zip_imputed"], "zip"].unique()) <= set(labelled["zip"].unique())
assert n_imputed + n_no_cell + n_no_location == int(zip_missing_before.sum())
log_rule("crashes", "reports whose borough contradicts their coordinates not used to teach the ZIP lookup",
         "flag", len(crashes), len(crashes), int(location_conflict.sum()),
         "Their wide area has many reports and nearly all give another borough. The reported values are kept.")
log_rule("crashes", f"missing zip recovered from coordinates (modal ZIP of a {ZIP_CELL_DEGREES[0]:g} degree cell, "
         f"else a {ZIP_CELL_DEGREES[1]:g} degree cell); flagged zip_imputed", "impute", len(crashes), len(crashes),
         n_imputed, f"Location-grouped test accuracy {holdout_accuracy:.1f}% (upper bound). Dropping the rows "
         f"would lose {100 * zip_missing_before.mean():.0f}% of the crashes, unevenly by year.")
log_rule("crashes", "zip still missing after recovery (no coordinates, or no labelled crash in either cell)",
         "flag", len(crashes), len(crashes), n_no_cell + n_no_location,
         "No value with evidence; kept for city totals and spatial work, excluded from the ZIP panel.")

missing_by_year = pd.DataFrame({"ZIP as reported": zip_missing_before, "After recovery": zip_missing_after}
                               ).groupby(crashes["year"].to_numpy()).mean() * 100
fig, ax = plt.subplots(figsize=(9.5, 4.4))
for column, color in zip(missing_by_year.columns, [PALETTE["crash"], PALETTE["after"]]):
    ax.plot(missing_by_year.index, missing_by_year[column], color=color, linewidth=2, marker="o", label=column)
    for year in sorted({missing_by_year.index[0], missing_by_year[column].idxmax(), missing_by_year.index[-1]}):
        ax.annotate(f"{missing_by_year.loc[year, column]:.0f}%", (year, missing_by_year.loc[year, column]),
                    xytext=(0, 8), textcoords="offset points", ha="center", fontsize=9)
ax.set_xticks(missing_by_year.index)
ax.set_ylim(0, missing_by_year.to_numpy().max() * AXIS_HEADROOM * 1.05)
ax.legend(loc="upper right")
finish(ax, "Crashes without a ZIP code, by year, before and after the recovery",
       "Crash year", "Crashes with no ZIP (% of the year's crashes)")
show(fig)

# %%
before_range, after_range = missing_by_year["ZIP as reported"], missing_by_year["After recovery"]
say(f"{n_imputed:,} crashes received a ZIP ({pct(n_imputed, int(zip_missing_before.sum())):.1f}% of those without "
    f"one; {pct((recovered_level == 1).sum(), n_imputed):.0f}% from the fine cell). The share without a ZIP falls "
    f"from {100 * zip_missing_before.mean():.1f}% to {100 * zip_missing_after.mean():.1f}%, and its spread across "
    f"years from {before_range.max() - before_range.min():.1f} to {after_range.max() - after_range.min():.1f} "
    f"points. {n_no_location:,} crashes have neither ZIP nor coordinates and {n_no_cell:,} lie in cells where no "
    f"crash reports a ZIP; these {n_pct(n_no_location + n_no_cell, len(crashes))} stay out of the ZIP panel.")

# %% [markdown]
# The upper line is the artificial trend the naive panel would have carried: the share of crashes
# missing from it moved by many points between years for reasons unrelated to safety. After the
# recovery the gap is much smaller and flatter. What remains comes mainly from crashes without
# coordinates, a share that was higher in the first study year, so ZIP-level comparisons that
# include that year should be read with it in mind; the panel carries the number of imputed
# crashes per row for checks on reported ZIPs only (Section 9).
#
# #### 6.1.2 The final ZIP by year panel
#
# The panel is rebuilt with the aggregation functions of 5.2 on the recovered ZIPs. Its ZIP codes
# are those with at least `MIN_ZIP_CRASHES` crashes over the study years (the housing ZIP the
# crash table never uses falls below it too); every such ZIP is crossed with every study year, and
# cells without a source row are zeros on both sides.

# %%
def build_zip_year_panel(housing_aggregate, crash_aggregate, panel_zips):
    """Balanced ZIP x study-year table: every ZIP in `panel_zips` in every study year, zeros filled in.

    The keys are converted to plain text and integers first, because the two aggregates arrive
    with different key dtypes (6.3).
    """
    grid = pd.MultiIndex.from_product([sorted(panel_zips), STUDY_YEARS], names=["zip", "year"])

    def on_grid(aggregate, measures):
        keyed = aggregate.assign(zip=aggregate["zip"].astype(object), year=aggregate["year"].astype("int64"))
        return keyed.set_index(["zip", "year"])[measures].reindex(grid, fill_value=0)

    return pd.concat([on_grid(housing_aggregate, HOUSING_PANEL_MEASURES),
                      on_grid(crash_aggregate, CRASH_PANEL_MEASURES)], axis=1).reset_index()


crashes_by_zip_year = aggregate_crashes_to_zip_year(crashes)
crashes_per_zip = crashes_by_zip_year.groupby("zip")["crashes"].sum()
panel_zips = sorted(crashes_per_zip.index[crashes_per_zip >= MIN_ZIP_CRASHES])
n_small_zips = int((crashes_per_zip < MIN_ZIP_CRASHES).sum())
zip_year = build_zip_year_panel(housing_by_zip_year, crashes_by_zip_year, panel_zips)

# How many of each row's crashes rest on a recovered ZIP (for checks on reported ZIPs only).
imputed = crashes[crashes["zip_imputed"]]
imputed_counts = (pd.DataFrame({"zip": imputed["zip"].astype(object), "year": imputed["year"].astype("int64"),
                                "crashes_zip_imputed": 1, "injury_crashes_zip_imputed": imputed["is_injury_crash"]})
                  .groupby(["zip", "year"]).sum())
zip_year = zip_year.join(imputed_counts, on=["zip", "year"])
zip_year[list(imputed_counts.columns)] = zip_year[list(imputed_counts.columns)].fillna(0)
crashes["in_zip_panel"] = crashes["zip"].isin(panel_zips).to_numpy()

structural_zero_rows = int((zip_year["buildings_completed"] == 0).sum())
housing_zips_excluded = sorted(set(housing["zip"].dropna()) - set(panel_zips))
log_rule("zip panel", "ZIP-years with crashes and no completion: housing measures set to 0", "impute",
         len(zip_year), len(zip_year), structural_zero_rows,
         "Structural zero: no row in the housing aggregate means nothing was completed there that year.")
log_rule("zip panel", f"ZIP codes with fewer than {MIN_ZIP_CRASHES} crashes in {N_STUDY_YEARS} years left out",
         "drop", (len(panel_zips) + n_small_zips) * N_STUDY_YEARS, len(zip_year), n_small_zips,
         "Single-building and post-office codes, and a housing ZIP the crash table never uses; a zero crash "
         "count there would be false. Rows are ZIP-years, affected counts ZIP codes.")
display(pd.DataFrame({"naive panel (5.2)": gaps_before, "final panel": panel_gap_report(zip_year, crashes)},
                     dtype=object))
say(f"The final panel has {len(zip_year):,} rows, {len(panel_zips)} ZIP codes in each of {N_STUDY_YEARS} years, "
    f"with no missing cell. {n_pct(structural_zero_rows, len(zip_year), 0)} ZIP-years had no completion and carry "
    f"zeros on the housing side; {n_small_zips} low-volume ZIP codes were left out. Housing ZIP codes outside the "
    f"panel: {', '.join(housing_zips_excluded)} (their units are counted in 6.4).")

# %% [markdown]
# Zero completions is a fact; zero crashes in a ZIP the crash table never uses would be an artefact.
#
# ### 6.2 Inconsistent or redundant columns
#
# #### 6.2.1 Borough: one attribute, two sources
#
# Both tables carry a borough, so a ZIP has two candidate boroughs, and a crash with a recovered
# ZIP has no borough at all, because borough and ZIP are missing together in the crash table
# (Section 4.8). The panel takes one borough per ZIP: the crash table decides (thousands of rows
# per ZIP), housing fills in. A crash keeps the borough it reported, because the report is the
# observation and the lookup a summary; a crash without one takes the borough of its ZIP.
# Overwriting every crash with its ZIP's borough was the alternative, rejected because it would
# replace reported values for tidiness.

# %%
def modal_borough_by_zip(frame, zip_column):
    """Per ZIP: the most frequent borough among rows that have both."""
    rows = frame[frame[zip_column].notna() & frame["borough"].notna()]
    counts = pd.DataFrame({"zip": rows[zip_column].astype(object), "borough": rows["borough"].astype(object)}).value_counts().rename("count")
    return counts.reset_index().sort_values(["zip", "count", "borough"], ascending=[True, False, True]
                                            ).drop_duplicates("zip").set_index("zip")["borough"]


borough_from_crashes = modal_borough_by_zip(crashes.assign(zip=zip_reported), "zip")
borough_from_housing = modal_borough_by_zip(housing, "zip")
shared = borough_from_crashes.index.intersection(borough_from_housing.index)
sources_disagree = int((borough_from_crashes[shared] != borough_from_housing[shared]).sum())
zip_borough = borough_from_crashes.combine_first(borough_from_housing)
assert set(panel_zips) <= set(zip_borough.index)

borough_reported = crashes["borough"].notna().to_numpy()      # what the police wrote down
borough_of_zip = crashes["zip"].astype(object).map(zip_borough).to_numpy(dtype=object)
fill_from_zip = ~borough_reported & pd.notna(borough_of_zip)
# A second check of the ZIP recovery, on rows that really lacked a ZIP: does the borough of the
# recovered ZIP match the borough the officer wrote down?
check_rows = crashes["zip_imputed"].to_numpy() & borough_reported
recovery_agrees = borough_of_zip[check_rows] == crashes["borough"].astype(object).to_numpy()[check_rows]
filled_borough = crashes["borough"].astype(object).to_numpy()
filled_borough[fill_from_zip] = borough_of_zip[fill_from_zip]

zip_year["borough"] = zip_year["zip"].map(zip_borough)
log_rule("zip panel", "two borough sources (crash reports, housing rows) resolved into one borough per ZIP",
         "standardise", len(zip_year), len(zip_year), sources_disagree,
         "Crash-modal borough, housing as fallback. Affected counts ZIPs where the two sources disagreed.")
log_rule("crashes", "missing borough filled from the main borough of the crash's ZIP", "impute",
         len(crashes), len(crashes), int(fill_from_zip.sum()),
         "Borough and ZIP are missing together; once the ZIP is recovered the borough follows from it.")

# %% [markdown]
# A crash can have coordinates and still lie in a cell where no crash reported a ZIP, so its
# borough stays empty, and such gaps fall unevenly on the boroughs. For these crashes the borough
# alone is voted by `cell_mode` over reported boroughs, from a 0.004 degree cell up to a 0.05
# degree one; a borough is large, so a wide cell rarely crosses its edge. The vote is checked on
# the same location-grouped test part as the ZIP. The ZIP stays empty: ZIP areas are small and the
# panel should hold only ZIPs with cell-level evidence.

# %%
voters = labelled.assign(borough=labelled["borough"].astype(object))
train_voters = voters.loc[train_rows.index].dropna(subset=["borough"])
test_voters = voters.loc[test_rows.index].dropna(subset=["borough"])
voted_test, _ = label_from_cells(test_voters["lat"], test_voters["lon"],
                                 learn_lookups(train_voters, "borough", BOROUGH_CELL_DEGREES))
borough_vote_accuracy = 100 * (voted_test == test_voters["borough"].to_numpy(dtype=object)).mean()

# Final vote: every reported, uncontradicted borough of a located crash votes.
all_voters = crashes.loc[crashes["is_located"].to_numpy() & borough_reported & ~location_conflict.to_numpy(),
                         ["lat", "lon", "borough"]].astype({"borough": object})
lacking = crashes["is_located"].to_numpy() & pd.isna(filled_borough)
voted, _ = label_from_cells(crashes["lat"].to_numpy()[lacking], crashes["lon"].to_numpy()[lacking],
                            learn_lookups(all_voters, "borough", BOROUGH_CELL_DEGREES))
filled_borough[np.flatnonzero(lacking)] = voted
crashes["borough"] = pd.Categorical(filled_borough, categories=BOROUGHS)
n_voted = int(pd.notna(voted).sum())
log_rule("crashes", "borough of located crashes with no ZIP voted by reported boroughs in their grid cell",
         "impute", len(crashes), len(crashes), n_voted,
         f"Cells with no reported ZIP left an uneven gap by borough; test accuracy {borough_vote_accuracy:.1f}%. "
         "The ZIP stays empty.")
say(f"Housing and crashes name a different borough for {sources_disagree} of the {len(shared)} ZIP codes they share. "
    f"{int(fill_from_zip.sum()):,} crashes take the borough of their ZIP; where a recovered ZIP can be compared "
    f"with a reported borough ({int(check_rows.sum()):,} crashes) the two agree {100 * recovery_agrees.mean():.1f}% "
    f"of the time. {n_voted:,} more located crashes get a voted borough (test accuracy "
    f"{borough_vote_accuracy:.1f}%), and {n_pct(crashes['borough'].isna().sum(), len(crashes))} crashes, almost "
    f"all without coordinates, stay without one.")

# %% [markdown]
# #### 6.2.2 Duplicate and leftover columns
#
# Integration left columns that say the same thing twice or only served a step above. Each was
# reviewed; the claim behind every drop is checked first.

# %%
assert (crashes["zip"].where(~crashes["zip_imputed"]).isna() == zip_reported.isna().to_numpy()).all()
assert (sites["is_completed"] == sites["completion_year"].notna()).all()
assert (zip_year["new_construction_units"] + zip_year["preservation_units"]
        <= zip_year["affordable_units_completed"]).all()
column_review = pd.DataFrame([
    ("crashes", "zip as reported", "drop", "Equal to zip wherever zip_imputed is False, and missing elsewhere."),
    ("naive_panel, crashes_by_zip_year_reported", "whole tables", "drop", "Replaced by zip_year."),
    ("crashes", "is_located", "keep", "Same as lat not missing, but used as a filter in every spatial step."),
    ("sites", "is_completed", "keep", "Same as completion_year not missing; kept for readable filters."),
    ("sites / zip_year", "borough and zip in both", "keep",
     "Not duplicates: one is the building's own borough and ZIP, the other the panel key."),
    ("zip_year", "new_construction_units, preservation_units", "keep",
     "Parts of affordable_units_completed, but each is a variable of its own in Section 8."),
], columns=["table", "column", "decision", "reason"])
show_table(column_review)
release("naive_panel", "crashes_by_zip_year_reported", "zip_reported")

# %% [markdown]
# #### 6.2.3 Cumulative units
#
# Several questions need the stock (affordable units standing in the ZIP by a given year) rather
# than the yearly flow. A running sum over the unbalanced housing aggregate would skip years
# without a completion and lose completions before the first study year, so the stock is summed
# on a complete grid from the first completion year in the housing table, then cut to the study
# years. Housing built before the table starts is not in the data, so the stock is the stock added
# since then.

# %%
CUMULATIVE_COLUMNS = {"cum_affordable_units": "affordable_units_completed",
                      "cum_deep_affordable_units": "deep_affordable_units"}
housing_first_year = int(housing_by_zip_year["year"].min())
history = pd.MultiIndex.from_product([panel_zips, range(housing_first_year, YEAR_END + 1)], names=["zip", "year"])
keyed = housing_by_zip_year.assign(zip=housing_by_zip_year["zip"].astype(object),
                                   year=housing_by_zip_year["year"].astype("int64")).set_index(["zip", "year"])
cumulative = (keyed[list(CUMULATIVE_COLUMNS.values())].reindex(history, fill_value=0)
              .groupby(level="zip").cumsum().set_axis(list(CUMULATIVE_COLUMNS), axis=1))
zip_year = zip_year.join(cumulative, on=["zip", "year"])

# The stock grows by exactly the year's completions, and ends at the sum of all completions to date.
stock_change = zip_year.groupby("zip")["cum_affordable_units"].diff()
assert (stock_change.dropna() == zip_year.loc[stock_change.notna(), "affordable_units_completed"]).all()
assert (zip_year.loc[zip_year["year"] == YEAR_END, "cum_affordable_units"].sum()
        == keyed.loc[keyed.index.get_level_values("zip").isin(panel_zips)
                     & (keyed.index.get_level_values("year") <= YEAR_END), "affordable_units_completed"].sum())
log_rule("zip panel", "cumulative unit columns computed on a complete grid from the first housing year",
         "standardise", len(zip_year), len(zip_year), len(CUMULATIVE_COLUMNS),
         "A running sum over the unbalanced aggregate would skip empty years and lose earlier completions. "
         "Affected counts columns.")
start_rows = zip_year["year"] == YEAR_START
stock_at_start = int((zip_year.loc[start_rows, "cum_affordable_units"] - zip_year.loc[start_rows, "affordable_units_completed"]).sum())
say(f"The housing table starts in {housing_first_year}. The panel's ZIP codes enter {YEAR_START} with "
    f"{stock_at_start:,} affordable units completed earlier and end {YEAR_END} with a stock of "
    f"{int(zip_year.loc[zip_year['year'] == YEAR_END, 'cum_affordable_units'].sum()):,}.")

# %% [markdown]
# ### 6.3 Data type mismatches
#
# A join compares key values exactly, so keys that look alike but are stored differently do not
# match. With a default load, pandas reads the housing postcode as a decimal number (the column
# has blanks) while crash ZIPs are text, which is why Section 2 loaded every column as text; the
# cell below shows what a join on default types would have found. The year is a nullable integer
# in housing (unfinished buildings have none) and a plain integer in crashes, and merges and grids
# turn counts into decimals or 64-bit integers and labels into plain objects. Every integrated
# table is therefore cast to one declared schema, and the schema is asserted.

# %%
default_zip_text = set(pd.read_csv(HOUSING_FILE, usecols=["postcode"])["postcode"].dropna().astype(str))
crash_zip_text = set(crashes["zip"].dropna().astype(object))
clean_zip_text = set(housing["zip"].dropna().astype(object))
key_match = pd.DataFrame({"distinct housing ZIPs": [len(default_zip_text), len(clean_zip_text)],
                          "found among crash ZIPs": [len(default_zip_text & crash_zip_text),
                                                     len(clean_zip_text & crash_zip_text)],
                          "example": [sorted(default_zip_text)[0], sorted(clean_zip_text)[0]]},
                         index=["default load (number)", "as cleaned (text)"])
display(key_match)

COUNT = "int32"
ZIP_DTYPE = housing["zip"].dtype
SCHEMAS = {
    "zip_year": {"zip": ZIP_DTYPE, "year": "int16", "borough": "category",
                 **dict.fromkeys(HOUSING_PANEL_MEASURES + list(CUMULATIVE_COLUMNS) + CRASH_PANEL_MEASURES, COUNT),
                 "crashes_zip_imputed": COUNT, "injury_crashes_zip_imputed": COUNT},
    "sites": {"site_id": "int32", "cluster_id": "int32", "housing_id": "int32",
              "project_id": "int64", "building_id": "int64", "project_name": housing["project_name"].dtype,
              "borough": "category", "zip": ZIP_DTYPE, "lat": "float64", "lon": "float64", "start_year": "int16",
              "completion_year": "Int16", "is_completed": "bool", "same_day_completion": "bool",
              "completion_before_start": "bool", "construction_type": "category", "total_units": "int16",
              "all_counted_units": "int16", "deep_affordable_units": "int16", "deep_affordable_share": "float64",
              "size_band": "category", "is_size_outlier": "bool", "n_sites_within_buffer": "int32"},
    "site_year": {"site_id": "int32", "year": "int16", **dict.fromkeys(SITE_COUNT_COLUMNS, COUNT)},
    "event_panel": {"site_id": "int32", "cluster_id": "int32", "cohort": "int16",
                    "group": "category", "rel_year": "int8", "year": "int16", **dict.fromkeys(SITE_COUNT_COLUMNS, COUNT),
                    "contaminated": "bool", "near_completion_in_window": "bool", "near_earlier_completion": "bool",
                    "completion_year": "Int16", "construction_type": "category", "borough": "category",
                    "size_band": "category", "total_units": "int16"},
}
CRASH_NEW_COLUMNS = {"zip": ZIP_DTYPE, "zip_imputed": "bool", "borough": "category", "in_zip_panel": "bool",
                     "near_site_id": "Int32"}


def cast_to_schema(frame, schema):
    """The frame with exactly the schema's columns, in its order and dtypes; counts must be whole and complete."""
    assert set(schema) == set(frame.columns), set(schema) ^ set(frame.columns)
    result = frame[list(schema)].copy()
    for column, dtype in schema.items():
        if dtype == "category" and result[column].dtype != "category":
            result[column] = pd.Categorical(result[column], categories=BOROUGHS)   # only borough arrives as text
            assert result[column].notna().all(), f"{column}: label outside the declared levels"
        elif dtype != "category":
            if dtype == COUNT:
                values = result[column].astype("float64")
                assert values.notna().all() and (values == np.floor(values)).all(), f"{column}: not a whole count"
            result[column] = result[column].astype(dtype)
    return result


tables = {"zip_year": zip_year, "sites": sites, "site_year": site_year, "event_panel": event_panel}
n_dtype_changes = sum(str(frame[column].dtype) != str(dtype) for name, frame in tables.items()
                      for column, dtype in SCHEMAS[name].items() if dtype != "category")
zip_year, sites, site_year, event_panel = (cast_to_schema(tables[name], SCHEMAS[name]) for name in tables)
release("tables")

# The schema holds, join keys share one dtype, and the keys really join.
for name, frame in [("zip_year", zip_year), ("sites", sites), ("site_year", site_year), ("event_panel", event_panel)]:
    assert all(frame[column].dtype == dtype for column, dtype in SCHEMAS[name].items()), name
assert all(crashes[column].dtype == dtype for column, dtype in CRASH_NEW_COLUMNS.items())
assert zip_year["zip"].dtype == crashes["zip"].dtype == housing["zip"].dtype == sites["zip"].dtype
assert zip_year["year"].dtype == crashes["year"].dtype == site_year["year"].dtype == event_panel["year"].dtype
for frame in (zip_year, sites, event_panel, crashes, housing):
    assert list(frame["borough"].cat.categories) == BOROUGHS
assert crashes["near_site_id"].dropna().isin(sites["site_id"]).all()
assert set(zip_year["zip"]) <= set(crashes["zip"].dropna())
assert key_match.loc["default load (number)", "found among crash ZIPs"] == 0   # the sentence below relies on it

log_rule("zip panel", "integrated tables cast to a declared schema (keys, counts, categories)", "standardise",
         len(zip_year), len(zip_year), n_dtype_changes,
         "Merges and grids returned object keys, 64-bit and decimal counts. Affected counts columns across the "
         "four tables.")
say(f"Read with default types, none of the {key_match.iloc[0, 0]} housing postcodes equals a crash ZIP as text; as "
    f"cleaned, {key_match.iloc[1, 1]} of {key_match.iloc[1, 0]} do. A merge on the default keys would have "
    f"returned an empty match without an error. The cast changed {n_dtype_changes} columns across the four "
    f"tables. Identifiers that can be missing keep a nullable integer type on purpose (`near_site_id`, "
    f"`completion_year`): a zero or minus one there would look like a real value.")

# %% [markdown]
# ### 6.4 Conservation checks
#
# Every crash is either in a row of the panel or in one excluded group, measure by measure, and
# every housing unit is in the panel's yearly columns or a counted exclusion; the asserts stop the run otherwise.

# %%
crash_measure_sources = {"crashes": None, "injury_crashes": "is_injury_crash", "persons_injured": "injured",
                         "persons_killed": "killed", "ped_cyc_crashes": "ped_cyc_harm"}
crash_groups = {
    "In the ZIP panel": crashes["in_zip_panel"].to_numpy(),
    f"ZIP with fewer than {MIN_ZIP_CRASHES} crashes": (crashes["zip"].notna() & ~crashes["in_zip_panel"]).to_numpy(),
    "No ZIP, coordinates in an unlabelled cell": (crashes["zip"].isna() & crashes["is_located"]).to_numpy(),
    "No ZIP and no coordinates": (crashes["zip"].isna() & ~crashes["is_located"]).to_numpy(),
}
assert (np.column_stack(list(crash_groups.values())).sum(axis=1) == 1).all(), "every crash is in exactly one group"
conservation = pd.DataFrame({
    measure: {group: int(mask.sum()) if source is None else int(crashes[source].to_numpy()[mask].sum())
              for group, mask in crash_groups.items()}
    for measure, source in crash_measure_sources.items()})
conservation.loc["Total"] = conservation.sum()
conservation["% of crashes"] = (100 * conservation["crashes"] / len(crashes)).round(2)
display(conservation)
for measure, source in crash_measure_sources.items():
    assert conservation.loc["Total", measure] == (len(crashes) if source is None else int(crashes[source].sum()))
    assert zip_year[measure].sum() == conservation.loc["In the ZIP panel", measure], measure

# Housing: units of a repeated building are counted once, at its first completion (5.2).
completed, repeat = housing["is_completed"], is_repeat_building(housing)
in_panel_zip = housing["zip"].isin(panel_zips)
housing_groups = {
    "In the ZIP panel": completed & ~repeat & in_panel_zip & housing["completion_year"].between(YEAR_START, YEAR_END),
    f"Completed before {YEAR_START} (in the stock only)": completed & ~repeat & in_panel_zip & (housing["completion_year"] < YEAR_START),
    f"Completed after {YEAR_END}": completed & ~repeat & in_panel_zip & (housing["completion_year"] > YEAR_END),
    "Completed again under a later project": completed & repeat,
    "Completed, ZIP not in the panel": completed & ~repeat & housing["zip"].notna() & ~in_panel_zip,
    "Completed, no ZIP (confidential)": completed & ~repeat & housing["zip"].isna(),
    "No completion date": ~completed,
}
housing_conservation = pd.DataFrame({
    "rows": {group: int(mask.sum()) for group, mask in housing_groups.items()},
    "total_units": {group: int(housing.loc[mask, "total_units"].sum()) for group, mask in housing_groups.items()},
})
housing_conservation.loc["Total"] = housing_conservation.sum()
housing_conservation["% of units"] = (100 * housing_conservation["total_units"] / housing["total_units"].sum()).round(1)
display(housing_conservation)
assert housing_conservation.loc["Total", "rows"] == len(housing)
assert housing_conservation.loc["Total", "total_units"] == housing["total_units"].sum()
assert zip_year["units_completed"].sum() == housing_conservation.loc["In the ZIP panel", "total_units"]
# The panel is unique on its key, balanced, complete and its counts are nested.
assert not zip_year.duplicated(["zip", "year"]).any() and len(zip_year) == len(panel_zips) * N_STUDY_YEARS
assert zip_year.notna().all().all()
assert (zip_year["ped_cyc_crashes"] <= zip_year["injury_crashes"]).all()
assert (zip_year["injury_crashes"] <= zip_year["crashes"]).all()
assert (zip_year["deep_affordable_units"] <= zip_year["affordable_units_completed"]).all()

say(f"All checks pass. {n_pct(conservation.loc['In the ZIP panel', 'crashes'], len(crashes))} crashes and "
    f"{pct(conservation.loc['In the ZIP panel', 'injury_crashes'], conservation.loc['Total', 'injury_crashes']):.1f}% "
    f"of injury crashes are in the panel; the rest are in three counted groups. The panel's yearly columns hold "
    f"{housing_conservation.loc['In the ZIP panel', '% of units']:.1f}% of all housing units; the largest group "
    f"outside is buildings with no completion date "
    f"({housing_conservation.loc['No completion date', '% of units']:.1f}%), which the spatial level uses as "
    f"comparison sites.")

# %% [markdown]
# ### 6.5 A citywide yearly index for reference
#
# Every comparison over time has to be read against the city as a whole. `city_year` gives yearly
# totals over all cleaned crashes, with or without a ZIP or coordinates, and an index that sets
# `INDEX_BASE_YEAR` to 100; both series share one axis as indices since their levels differ.

# %%
city_year = (crashes.groupby("year")
             .agg(crashes=("collision_id", "size"), injury_crashes=("is_injury_crash", "sum"),
                  persons_injured=("injured", "sum"), persons_killed=("killed", "sum"),
                  ped_cyc_crashes=("ped_cyc_harm", "sum"))
             .astype(COUNT).reset_index())
city_year["year"] = city_year["year"].astype("int16")
city_year["injury_share"] = city_year["injury_crashes"] / city_year["crashes"]
# Deaths are recorded whatever the severity, so this ratio shows whether the remaining injury
# crashes are more severe after the break, or whether minor ones went missing.
city_year["deaths_per_1000_injury_crashes"] = PER_THOUSAND * city_year["persons_killed"] / city_year["injury_crashes"]
base_row = city_year.set_index("year").loc[INDEX_BASE_YEAR]
city_year["crash_index"] = INDEX_BASE * city_year["crashes"] / base_row["crashes"]
city_year["injury_crash_index"] = INDEX_BASE * city_year["injury_crashes"] / base_row["injury_crashes"]
assert list(city_year["year"]) == STUDY_YEARS and city_year["crashes"].sum() == len(crashes)
show_table(city_year.round(3))

city_by_year = city_year.set_index("year")
fig, ax = plt.subplots(figsize=(9.5, 4.8))
for column, label, color in [("crash_index", "All reported crashes", PALETTE["before"]),
                             ("injury_crash_index", "Injury crashes (primary outcome)", PALETTE["crash"])]:
    ax.plot(city_year["year"], city_year[column], color=color, linewidth=2.2, marker="o", label=label)
    ax.annotate(f"{city_year[column].iloc[-1]:.0f}", (YEAR_END, city_year[column].iloc[-1]), xytext=(8, 0),
                textcoords="offset points", va="center", fontsize=9.5)
ax.axhline(INDEX_BASE, color=PALETTE["neutral"], linewidth=0.8, linestyle=":")
ax.axvspan(BREAK_YEAR - 0.5, BREAK_YEAR + 0.5, color=PALETTE["before"], alpha=0.25, linewidth=0)
ax.annotate(f"{BREAK_YEAR}: reporting of\nminor crashes drops", (BREAK_YEAR + 0.55, INDEX_BASE * 1.07),
            fontsize=9, color=PALETTE["neutral"], va="center")
ax.set_xticks(STUDY_YEARS)
ax.set_xlim(YEAR_START - 0.3, YEAR_END + 0.8)
ax.set_ylim(0, city_year[["crash_index", "injury_crash_index"]].max().max() * AXIS_HEADROOM)
ax.legend(loc="lower left")
finish(ax, f"In {BREAK_YEAR} all crashes fall {INDEX_BASE - city_by_year.loc[BREAK_YEAR, 'crash_index']:.0f}% and "
           f"injury crashes {INDEX_BASE - city_by_year.loc[BREAK_YEAR, 'injury_crash_index']:.0f}%",
       "Crash year", f"Index ({INDEX_BASE_YEAR} = {INDEX_BASE})")
show(fig)

# %%
deaths_rate = city_by_year["deaths_per_1000_injury_crashes"]
say(f"Injury crashes reach index {city_by_year.loc[YEAR_END, 'injury_crash_index']:.0f} in {YEAR_END} against "
    f"{city_by_year.loc[YEAR_END, 'crash_index']:.0f} for all crashes, and the share of crashes with an injury or "
    f"death rises from {100 * city_by_year.loc[INDEX_BASE_YEAR, 'injury_share']:.0f}% to "
    f"{100 * city_by_year.loc[YEAR_END, 'injury_share']:.0f}%. Deaths per 1,000 injury crashes run from "
    f"{deaths_rate.loc[:INDEX_BASE_YEAR].min():.1f} to {deaths_rate.loc[:INDEX_BASE_YEAR].max():.1f} up to "
    f"{INDEX_BASE_YEAR} and from {deaths_rate.loc[BREAK_YEAR:].min():.1f} to {deaths_rate.loc[BREAK_YEAR:].max():.1f} "
    f"from {BREAK_YEAR}.")

# %% [markdown]
# The lines part after the base year and never rejoin: fewer minor collisions were written up, so
# a count of all crashes would drop everywhere, whatever was built there. Injury crashes dip less
# and are the outcome of Section 8. The higher death rate after the break fits more severe crashes
# or unreported minor ones, which the data cannot separate, so every before and after comparison
# is made against comparison sites or within the same calendar years.
#
# ### 6.6 Rules logged in this section and final outputs
#
# The log lists every rule recorded in Section 6; the table after it the six tables the analysis uses.

# %%
post_integration_log = pd.DataFrame(CLEANING_LOG[POST_LOG_START:])
show_table(post_integration_log)
assert set(post_integration_log["action"]) <= {"drop", "impute", "flag", "standardise"}
display(pd.DataFrame({name: {"rows": len(frame), "columns": frame.shape[1]} for name, frame in
                      [("zip_year", zip_year), ("sites", sites), ("site_year", site_year),
                       ("event_panel", event_panel), ("crashes", crashes), ("city_year", city_year)]}).T)

# These six tables are what the analysis sections use; the functions of Sections 5 and 6 stay
# defined so that Section 9 can rebuild the spatial tables at another radius or the panel on reported ZIPs.
release("train_all", "train_rows", "select_rows", "test_rows", "street", "on_highway_by_id", "filled_zip",
        "recovered_zip", "borough_of_zip", "filled_borough", "voters", "train_voters", "test_voters", "all_voters",
        "imputed", "imputed_counts", "keyed", "history", "location", "draw", "part", "default_zip_text",
        "crash_zip_text", "clean_zip_text", "completed", "repeat", "in_panel_zip", "stock_change")

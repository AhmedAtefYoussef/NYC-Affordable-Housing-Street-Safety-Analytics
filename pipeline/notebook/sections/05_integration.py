# %% [markdown]
# ## 5. Integration
#
# A housing row is a building in a subsidised project and a crash row is one collision. This
# section builds the tables that let a housing variable and a crash variable be read side by
# side, at two levels: a ZIP by year panel, where both tables are first reduced to the same grain,
# and a spatial level, where a crash is linked to the buildings within `BUFFER_M` metres of it.
#
# ### 5.1 The problem: no shared key
#
# `collision_id` identifies a crash and (`project_id`, `building_id`) a housing row. Neither
# appears in the other table, so there is nothing to join row to row. What the tables share is
# where and when, and each bridge gives a different grain.
#
# | Bridge | Grain | Can answer | Cannot answer |
# |---|---|---|---|
# | Time (year) | city by year | whether the two series move together | anything about place (ten points) |
# | Borough | borough by year | broad contrasts; the only level that includes confidential housing | neighbourhood differences |
# | ZIP code | ZIP by year | change within a neighbourhood over time | what happens on the streets next to one building |
# | Coordinates | building by year | crashes around a building before and after it is completed | records without coordinates |
#
# Time and borough are too coarse to carry the analysis and serve as controls and reference
# totals. The ZIP and the coordinates are the two working bridges.

# %%
# --- Constants for Section 5 ------------------------------------------------------------------
N_STUDY_YEARS = len(STUDY_YEARS)
RADIUS_CANDIDATES_M = [100, 150, 250, 400, 500]   # radii compared in 5.3.1; reused in Section 9
CHECK_SITE_SAMPLE = 300                          # buildings in the brute-force check of the tree
CHECK_CRASH_SAMPLE = 20_000                      # crashes in that check
BYTES_PER_GB = 1_000_000_000
CLUSTER_SIZE_EDGES = [0, 1, 5, 20, 100, np.inf]          # buildings per cluster, upper edge inclusive
CLUSTER_SIZE_LABELS = ["1", "2-5", "6-20", "21-100", "101+"]

EVENT_GROUPS = ["treated", "comparison"]
SITE_ATTRIBUTES = ["housing_id", "project_id", "building_id", "project_name", "borough", "zip", "lat", "lon",
                   "start_year", "completion_year", "is_completed", "same_day_completion",
                   "completion_before_start", "construction_type", "total_units", "all_counted_units",
                   "deep_affordable_units", "deep_affordable_share", "size_band", "is_size_outlier"]
SITE_COUNT_COLUMNS = ["crashes", "injury_crashes", "ped_cyc_crashes", "persons_injured"]
HOUSING_PANEL_MEASURES = ["buildings_completed", "units_completed", "affordable_units_completed",
                          "deep_affordable_units", "new_construction_units", "preservation_units"]
CRASH_PANEL_MEASURES = ["crashes", "injury_crashes", "persons_injured", "persons_killed", "ped_cyc_crashes"]

# %%
# How much of each table every bridge can reach.
bridge_coverage = pd.DataFrame({
    "housing rows with the key": [int(housing["completion_year"].notna().sum()), int(housing["borough"].notna().sum()),
                                  int(housing["zip"].notna().sum()), int(housing["is_located"].sum())],
    "crash rows with the key": [int(crashes["year"].notna().sum()), int(crashes["borough"].notna().sum()),
                                int(crashes["zip"].notna().sum()), int(crashes["is_located"].sum())],
}, index=["Time (completion / crash year)", "Borough", "ZIP code", "Coordinates"])
bridge_coverage.insert(1, "% of housing", (100 * bridge_coverage["housing rows with the key"] / len(housing)).round(1))
bridge_coverage["% of crashes"] = (100 * bridge_coverage["crash rows with the key"] / len(crashes)).round(1)
display(bridge_coverage)

# %% [markdown]
# The housing rows without a ZIP or coordinates are the confidential records. The crash rows
# without a ZIP are the larger gap; most of them still have coordinates, which is why the spatial
# level reaches more crashes than the ZIP level before any repair (Section 6.1).
#
# #### 5.1.1 Why the tables are not merged row to row on ZIP
#
# A ZIP is a key in neither table, so a row merge on ZIP pairs every building with every crash of
# its ZIP and any sum over the result counts each crash once per building. The size of that merge
# follows from the row counts per ZIP without running it.

# %%
housing_per_zip = housing["zip"].value_counts()
crashes_per_zip = crashes["zip"].value_counts()
shared_zips = housing_per_zip.index.intersection(crashes_per_zip.index)
injured_per_zip = crashes.groupby("zip", observed=True)["injured"].sum().reindex(shared_zips)
merged_rows_total = int((housing_per_zip[shared_zips] * crashes_per_zip[shared_zips]).sum())
injured_true = int(injured_per_zip.sum())
injured_after_merge = int((housing_per_zip[shared_zips] * injured_per_zip).sum())
say(f"A row merge on ZIP would return {merged_rows_total:,} rows, {merged_rows_total / len(crashes):,.0f} times "
    f"the crash table, and the {injured_true:,} people injured in those ZIPs would sum to "
    f"{injured_after_merge:,}, an overcount by a factor of {injured_after_merge / injured_true:.0f}. The rule "
    f"from here on is to aggregate each table to a common grain first and merge second, one row to one row.")

# %% [markdown]
# ### 5.2 Level A: a ZIP by year panel
#
# The common grain is one row per ZIP and calendar year: the crash year for crashes, and the
# completion year for housing, because a building adds residents and street activity only once
# it is finished. Buildings without a completion date and confidential rows (no ZIP) contribute
# nothing at this level.
#
# Two unit totals are kept. `units_completed` counts every unit in the building, including
# market-rate ones; `affordable_units_completed` counts the units the programme counts as
# affordable, and the split by kind (`new_construction_units`, `preservation_units`) uses the
# same affordable count so that the parts add up to it. A building can appear in two projects
# (for example a new building later preserved again); its units are counted once, at its first
# completion, while `buildings_completed` still counts every completed project-building row.
#
# This first panel is deliberately naive: reported ZIPs and an outer merge, to expose what does
# not match. Section 6 repairs the gaps and rebuilds the panel with the same functions.

# %%
def is_repeat_building(housing_frame):
    """True for completed rows whose building was already completed under an earlier project."""
    completed = housing_frame[housing_frame["is_completed"] & housing_frame["building_id"].notna()]
    ordered = completed.sort_values(["completion_date", "project_id"])
    repeat = ordered["building_id"].duplicated(keep="first")
    return repeat.reindex(housing_frame.index, fill_value=False)


def aggregate_housing_to_zip_year(housing_frame):
    """Completed housing rows with a ZIP, summed to one row per (zip, completion year).

    Unit columns use one row per building (its first completion); `year` keeps the nullable
    dtype of `completion_year`, which Section 6.3 fixes.
    """
    first = ~is_repeat_building(housing_frame)
    completed = housing_frame[housing_frame["is_completed"] & housing_frame["zip"].notna()]
    first = first[completed.index]
    affordable = completed["all_counted_units"].where(first, 0)
    kind = completed["construction_type"]
    measures = pd.DataFrame({
        "zip": completed["zip"], "year": completed["completion_year"],
        "buildings_completed": 1,
        "units_completed": completed["total_units"].where(first, 0),
        "affordable_units_completed": affordable,
        "deep_affordable_units": completed["deep_affordable_units"].where(first, 0),
        "new_construction_units": affordable.where(kind == "New Construction", 0),
        "preservation_units": affordable.where(kind == "Preservation", 0),
    })
    return (measures.groupby(["zip", "year"], as_index=False)[HOUSING_PANEL_MEASURES].sum()
            .astype({column: "int32" for column in HOUSING_PANEL_MEASURES}))


def aggregate_crashes_to_zip_year(crash_frame, zip_column="zip"):
    """Crashes that have a value in `zip_column`, summed to one row per (zip, crash year)."""
    with_zip = crash_frame[crash_frame[zip_column].notna()]
    measures = pd.DataFrame({
        "zip": with_zip[zip_column], "year": with_zip["year"], "crashes": 1,
        "injury_crashes": with_zip["is_injury_crash"].astype("int32"),
        "persons_injured": with_zip["injured"].astype("int32"),
        "persons_killed": with_zip["killed"].astype("int32"),
        "ped_cyc_crashes": with_zip["ped_cyc_harm"].astype("int32"),
    })
    return measures.groupby(["zip", "year"], as_index=False)[CRASH_PANEL_MEASURES].sum()


housing_by_zip_year = aggregate_housing_to_zip_year(housing)
crashes_by_zip_year_reported = aggregate_crashes_to_zip_year(crashes)
housing_in_study_years = housing_by_zip_year[housing_by_zip_year["year"].between(YEAR_START, YEAR_END)]
naive_panel = housing_in_study_years.merge(crashes_by_zip_year_reported, on=["zip", "year"], how="outer",
                                           indicator="match")
# Both aggregates are unique on (zip, year), so the merge is one row to one row.
assert not naive_panel.duplicated(["zip", "year"]).any()
assert len(naive_panel) <= len(housing_in_study_years) + len(crashes_by_zip_year_reported)

repeat_rows = is_repeat_building(housing)
naive_match = naive_panel["match"].value_counts()
housing_zips_without_crashes = sorted(set(housing_by_zip_year["zip"]) - set(crashes_by_zip_year_reported["zip"]))
crashes_without_zip = int(crashes["zip"].isna().sum())
say(f"{repeat_rows.sum()} completed rows repeat a building already completed under an earlier project; their "
    f"{int(housing.loc[repeat_rows, 'total_units'].sum()):,} units are not counted a second time. The naive "
    f"panel has {len(naive_panel):,} rows for {naive_panel['zip'].nunique()} ZIP codes, "
    f"{naive_panel['zip'].nunique() * N_STUDY_YEARS - len(naive_panel):,} short of a balanced panel. "
    f"{naive_match['both']:,} rows matched on both sides, {naive_match['right_only']:,} have crashes and no "
    f"housing row and {naive_match['left_only']} have housing and no crash row, which leaves "
    f"{int(naive_panel[HOUSING_PANEL_MEASURES + CRASH_PANEL_MEASURES].isna().sum().sum()):,} missing cells. "
    f"Housing ZIP codes never used by the crash table: {', '.join(housing_zips_without_crashes) or 'none'}. "
    f"{n_pct(crashes_without_zip, len(crashes))} crashes have no ZIP and reach no row at all.")

# %% [markdown]
# Three different gaps hide behind these numbers. A ZIP-year with crashes and no housing row is
# the normal case: nothing was completed there that year, so the missing housing values are
# zeros. A housing ZIP with no crash row at all is not a ZIP without crashes; the crash table
# simply does not use that code, and a zero there would be false. The crashes without a ZIP are
# the largest problem and are invisible in the panel, because a row without a key drops out of a
# grouped table without leaving a missing value; their share also changes from year to year
# (Section 4.8), which would put a record-keeping trend into the panel. Section 6.1 handles all three.

# %% [markdown]
# ### 5.3 Level B: spatial proximity
#
# The second level asks which crashes happened within `BUFFER_M` metres of each building. Degrees
# are not a unit of length (at New York's latitude a degree of longitude is about three quarters of
# a degree of latitude), so distances use the haversine great-circle formula, with latitude
# $\varphi$ and longitude $\lambda$ in radians and $R$ = `EARTH_RADIUS_M`:
#
# $$d = 2R \arcsin\sqrt{\sin^2\frac{\varphi_2-\varphi_1}{2} + \cos\varphi_1\cos\varphi_2\sin^2\frac{\lambda_2-\lambda_1}{2}}$$
#
# Treating the Earth as a sphere is wrong by a fraction of a percent, about a metre at this radius,
# less than the geocoding error. To avoid comparing every building with every crash, a ball tree
# over the crashes (the larger table) is queried once per building; a radius query skips every
# group of points that lies entirely outside the radius. The tree works on the unit sphere, so a
# radius in metres is divided by $R$ before a query and distances are multiplied by $R$ after it.

# %%
def to_radians(lat, lon):
    """Stack latitude and longitude (degrees) into the (n, 2) radian array the haversine tree expects."""
    return np.radians(np.column_stack([np.asarray(lat, dtype="float64"), np.asarray(lon, dtype="float64")]))


def haversine_m(lat_a, lon_a, lat_b, lon_b):
    """Great-circle distance in metres between points given in degrees (arrays broadcast)."""
    phi_a, phi_b = np.radians(lat_a), np.radians(lat_b)
    half_dlambda = np.radians(np.asarray(lon_b) - np.asarray(lon_a)) / 2
    inside = np.sin((phi_b - phi_a) / 2) ** 2 + np.cos(phi_a) * np.cos(phi_b) * np.sin(half_dlambda) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(inside))


def build_haversine_tree(lat, lon):
    """Ball tree over points given in degrees; point i of the tree is row i of the inputs."""
    return BallTree(to_radians(lat, lon), metric="haversine")


def pairs_within_radius(tree, lat, lon, radius_m):
    """All (query point, tree point) pairs within `radius_m`: query positions, tree positions, metres.

    The tree answers with one ragged list per query point; flattening it into three pair arrays
    lets everything downstream run as vectorised numpy.
    """
    neighbours, distances = tree.query_radius(to_radians(lat, lon), radius_m / EARTH_RADIUS_M,
                                              return_distance=True)
    sizes = np.fromiter((len(found) for found in neighbours), dtype=np.int64, count=len(neighbours))
    query_index = np.repeat(np.arange(len(neighbours)), sizes)
    if sizes.sum() == 0:
        return query_index, np.empty(0, dtype=np.int64), np.empty(0, dtype="float64")
    return query_index, np.concatenate(neighbours), np.concatenate(distances) * EARTH_RADIUS_M


# Row positions identify crashes from here on, so the index must be 0..n-1.
crashes = crashes.reset_index(drop=True)
located_housing = housing[housing["is_located"]]
crash_tree_rows = np.flatnonzero(crashes["is_located"].to_numpy())   # row in `crashes` of each tree point
crash_tree = build_haversine_tree(crashes["lat"].to_numpy()[crash_tree_rows], crashes["lon"].to_numpy()[crash_tree_rows])

# Check the tree against every distance computed directly, on a sample small enough for a full matrix.
check_sites = located_housing.sample(CHECK_SITE_SAMPLE, random_state=SEED)
check_rows = np.random.default_rng(SEED).choice(crash_tree_rows, size=CHECK_CRASH_SAMPLE, replace=False)
check_lat, check_lon = crashes["lat"].to_numpy()[check_rows], crashes["lon"].to_numpy()[check_rows]
tree_query, tree_point, tree_distance = pairs_within_radius(
    build_haversine_tree(check_lat, check_lon), check_sites["lat"].to_numpy(), check_sites["lon"].to_numpy(), BUFFER_M)
all_distances = haversine_m(check_sites["lat"].to_numpy()[:, None], check_sites["lon"].to_numpy()[:, None],
                            check_lat[None, :], check_lon[None, :])
brute_query, brute_point = np.nonzero(all_distances <= BUFFER_M)
tree_order = np.lexsort((tree_point, tree_query))     # np.nonzero returns pairs in this order
assert (tree_query[tree_order] == brute_query).all() and (tree_point[tree_order] == brute_point).all()
assert np.allclose(tree_distance[tree_order], all_distances[brute_query, brute_point], atol=1e-6)
full_matrix_cells = len(crash_tree_rows) * len(located_housing)
say(f"On a sample of {CHECK_SITE_SAMPLE} buildings and {CHECK_CRASH_SAMPLE:,} crashes the tree and the full "
    f"distance matrix return the same {len(brute_query):,} pairs and the same distances. For all the data a "
    f"distance matrix would need {full_matrix_cells:,} values, about "
    f"{full_matrix_cells * 8 / BYTES_PER_GB:.0f} GB, which the tree never forms.")

# %% [markdown]
# #### 5.3.1 Why a 250 m buffer, and why not tracts or grid cells
#
# The buffer must catch the crashes a building's residents could be part of on their way in and
# out, and tolerate crash locations that are snapped to the nearest intersection, so it should
# not be shorter than a block. It must also stay small enough to belong to the building, since
# every extra metre adds streets shared with neighbours. The table puts numbers on that trade-off
# for five radii. It uses injury crashes only (the primary outcome) and queries the tree once at
# the largest radius, then filters the distances for the smaller ones.

# %%
def site_crash_pairs(site_frame, tree, tree_rows, radius_m=BUFFER_M):
    """One row per (site, crash) with the crash within `radius_m` of the site (`crash_row` = row in `crashes`)."""
    site_position, tree_position, distance_m = pairs_within_radius(
        tree, site_frame["lat"].to_numpy(), site_frame["lon"].to_numpy(), radius_m)
    return pd.DataFrame({
        "site_id": site_frame["site_id"].to_numpy()[site_position].astype("int32"),
        "crash_row": tree_rows[tree_position].astype("int32"),
        "distance_m": distance_m.astype("float32"),
    })


injury_tree_rows = crash_tree_rows[crashes["is_injury_crash"].to_numpy()[crash_tree_rows]]
injury_tree = build_haversine_tree(crashes["lat"].to_numpy()[injury_tree_rows], crashes["lon"].to_numpy()[injury_tree_rows])
radius_sites = located_housing[["lat", "lon"]].assign(site_id=np.arange(len(located_housing), dtype="int32"))
widest_pairs = site_crash_pairs(radius_sites, injury_tree, injury_tree_rows, max(RADIUS_CANDIDATES_M))

radius_rows = []
for radius in RADIUS_CANDIDATES_M:
    pairs = widest_pairs[widest_pairs["distance_m"] <= radius]
    per_site_year = np.bincount(pairs["site_id"], minlength=len(radius_sites)) / N_STUDY_YEARS
    radius_rows.append({
        "radius (m)": radius,
        "% of located injury crashes near a site": pct(pairs["crash_row"].nunique(), len(injury_tree_rows)),
        "sites sharing each near crash (mean)": len(pairs) / pairs["crash_row"].nunique(),
        "injury crashes per site and year (median)": float(np.median(per_site_year)),
        "% of sites below one injury crash a year": 100 * float((per_site_year < 1).mean()),
    })
radius_table = pd.DataFrame(radius_rows).set_index("radius (m)")
display(radius_table.round(1))
release("widest_pairs", "injury_tree", "radius_sites", "pairs")

# %% [markdown]
# A small radius gives counts too low to compare (many sites see less than one injury crash a
# year), and a large one turns "near a building" into "anywhere in the built-up city", with each
# crash shared by many sites. 250 m is the smallest radius at which nearly every site sees at
# least one injury crash a year, a walk of about three minutes. Its overlap is handled explicitly
# in 5.4, and Section 9 repeats the main results at other radii.
#
# Census tracts would give fixed, non-overlapping areas, but the crash table has no tract and the
# notebook reads no boundary file. A fixed grid needs no file, but it is not centred on the
# buildings: a building at the edge of its cell would be compared with crashes up to a cell width
# away on one side and none on the other. A buffer is centred on each building by construction.

# %% [markdown]
# ### 5.4 Sites, clusters and the site by year table
#
# A **site** is one located housing row, one building in one project, completed or not (the
# unfinished ones are the comparison group later). Sites stand close together, and two sites
# less than `BUFFER_M` apart count many of the same crashes, so they are not independent. Sites
# are grouped into **clusters**: the connected components of the graph that links every pair
# within `BUFFER_M`. Intervals at the spatial level use a cluster bootstrap (redraw whole clusters
# many times and read the spread of the re-estimates), so sites that share crashes stay together.
#
# One more dependence is not removed by clusters: many projects complete several buildings in the
# same year (sites keep `project_id` and `cluster_id`, so later sections can check a
# one-building-per-project sample). 5.4.2 measures it once the cohorts are defined.

# %%
def connected_clusters(first, second, n_points):
    """Label the connected components of an undirected graph given as two arrays of linked points."""
    links = coo_matrix((np.ones(len(first), dtype=np.int8), (first, second)), shape=(n_points, n_points))
    return connected_components(links, directed=False)[1].astype("int32")


def site_neighbour_pairs(site_frame, radius_m):
    """Pairs of sites within `radius_m` of each other, both directions, including each site with itself."""
    lat, lon = site_frame["lat"].to_numpy(), site_frame["lon"].to_numpy()
    first, second, _ = pairs_within_radius(build_haversine_tree(lat, lon), lat, lon, radius_m)
    return first, second


sites = located_housing[SITE_ATTRIBUTES].reset_index(drop=True)
sites.insert(0, "site_id", np.arange(len(sites), dtype="int32"))
# The 250 m neighbour pairs are built once and reused by the clusters, the event screen and its check.
site_first, site_second = site_neighbour_pairs(sites, BUFFER_M)
sites.insert(1, "cluster_id", connected_clusters(site_first, site_second, len(sites)))
# Other sites within the buffer (the pair list includes each site with itself).
sites["n_sites_within_buffer"] = (np.bincount(site_first, minlength=len(sites)) - 1).astype("int32")
assert len(sites) == int(housing["is_located"].sum())
assert not sites.duplicated(["project_id", "building_id"]).any()

cluster_sizes = sites.groupby("cluster_id").size()
cluster_bands = pd.cut(cluster_sizes, CLUSTER_SIZE_EDGES, labels=CLUSTER_SIZE_LABELS)
cluster_summary = pd.DataFrame({"clusters": cluster_bands.value_counts().reindex(CLUSTER_SIZE_LABELS),
                                "sites": cluster_sizes.groupby(cluster_bands, observed=False).sum()})
cluster_summary["% of sites"] = (100 * cluster_summary["sites"] / len(sites)).round(1)
display(cluster_summary.rename_axis("sites in the cluster"))
largest_clusters = cluster_sizes.sort_values(ascending=False)
say(f"The {len(sites):,} sites form {len(cluster_sizes):,} clusters. The three largest hold "
    f"{', '.join(f'{size:,}' for size in largest_clusters.head(3))} sites, together "
    f"{pct(largest_clusters.head(3).sum(), len(sites)):.0f}% of all sites, and the median site has "
    f"{sites['n_sites_within_buffer'].median():.0f} other sites within {BUFFER_M} m.")

# %% [markdown]
# Subsidised housing is concentrated: where most of it stands, nearly every building has another
# within the buffer and the chain of neighbours runs for kilometres. The effective number of
# independent units is therefore far below the number of sites, and cluster intervals will be wide.
#
# #### 5.4.1 Counting crashes per site and calendar year
#
# For every site and study year: all crashes in the buffer, injury crashes (the primary outcome),
# injury crashes that hurt a pedestrian or cyclist, and persons injured. Each (site, crash) pair
# exists once, so a crash is counted once per site.

# %%
def build_site_year(pairs, crash_frame, n_sites):
    """Balanced site x study-year table of crash counts from a (site, crash) pair list.

    One flat position per (site, year) lets a single `bincount` per measure do the counting.
    """
    crash_rows = pairs["crash_row"].to_numpy()
    year_offset = crash_frame["year"].to_numpy()[crash_rows].astype("int64") - YEAR_START
    flat_position = pairs["site_id"].to_numpy().astype("int64") * N_STUDY_YEARS + year_offset
    weights = {"crashes": None,
               "injury_crashes": crash_frame["is_injury_crash"].to_numpy()[crash_rows].astype("float64"),
               "ped_cyc_crashes": crash_frame["ped_cyc_harm"].to_numpy()[crash_rows].astype("float64"),
               "persons_injured": crash_frame["injured"].to_numpy()[crash_rows].astype("float64")}
    table = pd.DataFrame({"site_id": np.repeat(np.arange(n_sites, dtype="int32"), N_STUDY_YEARS),
                          "year": np.tile(np.asarray(STUDY_YEARS, dtype="int16"), n_sites)})
    for column in SITE_COUNT_COLUMNS:
        table[column] = np.bincount(flat_position, weights=weights[column],
                                    minlength=n_sites * N_STUDY_YEARS).astype("int32")
    return table


site_pairs = site_crash_pairs(sites, crash_tree, crash_tree_rows, BUFFER_M)
site_year = build_site_year(site_pairs, crashes, len(sites))
# Each crash once per site, a balanced table, and nested counts.
assert not site_pairs.duplicated(["site_id", "crash_row"]).any()
assert site_year["crashes"].sum() == len(site_pairs) and len(site_year) == len(sites) * N_STUDY_YEARS
assert (site_year["ped_cyc_crashes"] <= site_year["injury_crashes"]).all()
assert (site_year["injury_crashes"] <= site_year["crashes"]).all()

injury_pairs = site_pairs[crashes["is_injury_crash"].to_numpy()[site_pairs["crash_row"].to_numpy()]]
clusters_per_crash = (injury_pairs.assign(cluster_id=sites["cluster_id"].to_numpy()[injury_pairs["site_id"]])
                      .groupby("crash_row")["cluster_id"].nunique())
say(f"There are {len(site_pairs):,} (site, crash) pairs within {BUFFER_M} m. The {len(injury_pairs):,} injury "
    f"pairs involve {len(clusters_per_crash):,} different injury crashes, so summing site counts would count "
    f"the average crash {len(injury_pairs) / len(clusters_per_crash):.1f} times. By cluster, "
    f"{pct((clusters_per_crash > 1).sum(), len(clusters_per_crash)):.1f}% of those crashes are still shared "
    f"between two or more clusters, the dependence the cluster bootstrap does not remove.")

# %% [markdown]
# Site counts are therefore never summed across sites. They are repeated measurements of the
# streets around each building, compared with the same site in other years.
#
# #### 5.4.2 The event-time table
#
# Calendar years are re-expressed relative to the completion year: `rel_year` runs from minus to
# plus `EVENT_WINDOW`. A **cohort** is the set of sites completed in one calendar year; only
# cohorts whose whole window lies inside the study years are used. Because crash reporting changed
# during these years (Section 3), each cohort gets **comparison** sites observed over the same
# calendar years: located sites not completed by the end of the window (completed later, or not
# yet). They were chosen for the same programme, so they resemble the treated sites more than
# arbitrary street corners would. A comparison site serves every cohort it qualifies for; all its
# copies are resampled together.
#
# A site is `contaminated` when another completion falls inside its buffer: for a comparison site,
# any neighbour completed inside the window (`near_completion_in_window`) or before it
# (`near_earlier_completion`); for a treated site, a neighbour completed in a different year of
# its window, which would blur before and after. Neighbours completed in the same year count as
# the same event. The flagged rows stay in the table so Section 9 can relax the screen. Buffers
# up to twice the radius apart still share crashes; the screen-off rows of Section 9.2 repeat the comparison without
# such overlaps.

# %%
def event_cohorts(completion_year, window=EVENT_WINDOW):
    """Completion years present in the data whose full window lies inside the study years."""
    years_in_data = set(np.unique(completion_year[~np.isnan(completion_year)]).astype(int).tolist())
    return [year for year in full_window_years(window) if year in years_in_data]


def cohort_members(site_frame, first, second, cohort, window):
    """Treated and comparison sites of one cohort, with their contamination flags (one row per site)."""
    completion = site_frame["completion_year"].astype("float64").to_numpy()
    is_treated = completion == cohort
    is_comparison = np.isnan(completion) | (completion > cohort + window)   # not completed by the window's end
    neighbour_completion = completion[second]
    is_other_site = first != second
    in_window = is_other_site & (neighbour_completion >= cohort - window) & (neighbour_completion <= cohort + window)
    # A neighbour completed in the site's own year is the same event; comparison sites have no own year.
    separate_event = in_window & (neighbour_completion != completion[first])
    earlier = is_other_site & (neighbour_completion < cohort - window)
    near_in_window = np.bincount(first[separate_event], minlength=len(site_frame)) > 0
    near_earlier = np.bincount(first[earlier], minlength=len(site_frame)) > 0
    member = is_treated | is_comparison
    return pd.DataFrame({
        "site_id": site_frame["site_id"].to_numpy()[member],
        "cohort": np.int16(cohort),
        "group": pd.Categorical(np.where(is_treated[member], "treated", "comparison"), categories=EVENT_GROUPS),
        "near_completion_in_window": near_in_window[member],
        "near_earlier_completion": near_earlier[member],
        "contaminated": np.where(is_treated[member], near_in_window[member],
                                 near_in_window[member] | near_earlier[member]),
    })


def build_event_panel(site_frame, site_year_frame, radius_m=BUFFER_M, window=EVENT_WINDOW, neighbour_pairs=None):
    """Site x cohort x relative-year table with crash counts, group and contamination flags.

    `radius_m` is the contamination distance (the radius used to count the crashes);
    `neighbour_pairs` is `site_neighbour_pairs(site_frame, radius_m)` when the caller has it.
    """
    first, second = neighbour_pairs if neighbour_pairs is not None else site_neighbour_pairs(site_frame, radius_m)
    cohorts = event_cohorts(site_frame["completion_year"].astype("float64").to_numpy(), window)
    members = pd.concat([cohort_members(site_frame, first, second, cohort, window) for cohort in cohorts],
                        ignore_index=True)
    relative_years = np.arange(-window, window + 1, dtype="int8")
    panel = members.loc[members.index.repeat(len(relative_years))].reset_index(drop=True)
    panel["rel_year"] = np.tile(relative_years, len(members))
    panel["year"] = (panel["cohort"] + panel["rel_year"]).astype("int16")
    panel = panel.merge(site_year_frame, on=["site_id", "year"], how="left", validate="many_to_one")
    attributes = site_frame[["site_id", "cluster_id", "completion_year", "construction_type",
                             "borough", "size_band", "total_units"]]
    panel = panel.merge(attributes, on="site_id", how="left", validate="many_to_one")
    ordered = ["site_id", "cluster_id", "cohort", "group", "rel_year", "year", *SITE_COUNT_COLUMNS,
               "contaminated", "near_completion_in_window", "near_earlier_completion", "completion_year",
               "construction_type", "borough", "size_band", "total_units"]
    return panel[ordered]


event_panel = build_event_panel(sites, site_year, neighbour_pairs=(site_first, site_second))
assert not event_panel.duplicated(["site_id", "cohort", "rel_year"]).any()
assert event_panel[SITE_COUNT_COLUMNS].notna().all().all()
event_sites = event_panel[event_panel["rel_year"] == 0]
treated_sites = event_sites[event_sites["group"] == "treated"]
assert (treated_sites["completion_year"] == treated_sites["cohort"]).all()
assert treated_sites["site_id"].is_unique, "a treated site has one cohort"

# Independent check of the screen: no clean comparison site has any other site within the buffer
# that is completed by the end of its cohort's window.
site_completion = sites["completion_year"].astype("float64").to_numpy()
is_other = site_first != site_second
earliest_neighbour = (pd.Series(site_completion[site_second[is_other]]).groupby(site_first[is_other]).min()
                      .reindex(range(len(sites))).to_numpy())
clean_comparison = event_sites[(event_sites["group"] == "comparison") & ~event_sites["contaminated"]]
assert not (earliest_neighbour[clean_comparison["site_id"]] <= clean_comparison["cohort"] + EVENT_WINDOW).any()

cohort_counts = (event_sites.assign(clean=~event_sites["contaminated"])
                 .groupby(["cohort", "group"], observed=True)
                 .agg(candidates=("site_id", "size"), clean=("clean", "sum")).unstack("group"))
cohort_counts.columns = [f"{group}: {kind}" for kind, group in cohort_counts.columns]
display(cohort_counts[[f"{group}: {kind}" for group in EVENT_GROUPS for kind in ["candidates", "clean"]]])

# Projects that complete several buildings in one cohort (see the note in 5.4).
treated_per_project = treated_sites.merge(sites[["site_id", "project_id"]], on="site_id").groupby("project_id").size()
multi_building = treated_per_project[treated_per_project > 1]
say(f"The event table has {len(event_panel):,} rows. Of {len(treated_sites):,} treated sites, "
    f"{n_pct(int(cohort_counts['treated: clean'].sum()), len(treated_sites), 0)} pass the screen. "
    f"{len(multi_building)} projects complete more than one building in a cohort and hold "
    f"{pct(multi_building.sum(), len(treated_sites)):.0f}% of the treated sites; the largest has "
    f"{multi_building.max()} buildings. Such buildings share one completion and mostly one cluster, so "
    f"they are not separate events.")

# %% [markdown]
# The screen removes most candidates on both sides; without it, most comparison sites would have
# a completed building in their buffer and the comparison would be between treated streets and
# other treated streets. The clean sites are not a random subset: a site with no completed
# neighbour lies in a less dense part of the programme, so event-table results describe those
# places and are stated with their sample sizes. Keeping contaminated sites with the number of
# nearby completions as a control was rejected, because it replaces a clear rule with an
# assumption about how effects add up.
#
# ### 5.5 The nearest site of every crash
#
# The composition questions work from the pair list, where a crash near two sites counts for
# both. For the dashboard each crash also gets one `near_site_id`, its **nearest** site within the
# buffer. Ties (one building in two projects) go to the earlier completion, then the lower
# `site_id`, so the assignment is a deterministic partition.

# %%
def nearest_site(pairs, site_frame, n_crashes):
    """Site id of the nearest site within the buffer for each crash (missing when none)."""
    crash_rows, site_ids = pairs["crash_row"].to_numpy(), pairs["site_id"].to_numpy()
    completion = site_frame["completion_year"].astype("float64").to_numpy()[site_ids]
    # Sort by crash, distance, completion (missing last), site id; the first pair per crash wins.
    order = np.lexsort((site_ids, np.nan_to_num(completion, nan=np.inf), pairs["distance_m"].to_numpy(), crash_rows))
    sorted_rows = crash_rows[order]
    winners = order[np.r_[True, sorted_rows[1:] != sorted_rows[:-1]]]
    near = pd.array(np.full(n_crashes, pd.NA), dtype="Int32")
    near[crash_rows[winners]] = site_ids[winners]
    return near


crashes["near_site_id"] = nearest_site(site_pairs, sites, len(crashes))
assert crashes["near_site_id"].notna().sum() == site_pairs["crash_row"].nunique()
say(f"{n_pct(crashes['near_site_id'].notna().sum(), len(crashes))} crashes lie within {BUFFER_M} m of at least "
    f"one site and are tagged with the nearest one.")

# %% [markdown]
# ### 5.6 What the integrated tables look like
#
# None of these tables comes from a row-level key join between housing and crashes: the spatial
# tables count crashes inside buffers and the ZIP panel aggregates first. The naive panel is
# replaced in Section 6; the spatial tables are final. The crash tree, the pair list and the
# functions stay defined because Section 9 re-runs these steps at other radii.

# %%
integrated_overview = pd.DataFrame([
    ("sites", "one located building in one project", sites, "site_id"),
    ("site_year", "site x calendar year", site_year, "site_id, year"),
    ("event_panel", "site x cohort x relative year", event_panel, "site_id, cohort, rel_year"),
    ("site_pairs", "site x crash within the buffer", site_pairs, "site_id, crash_row"),
    ("naive_panel (replaced in 6.1)", "ZIP x year, unbalanced", naive_panel, "zip, year"),
], columns=["table", "grain", "frame", "unique key"]).set_index("table")
integrated_overview.insert(1, "rows", integrated_overview["frame"].map(len))
integrated_overview.insert(2, "columns", integrated_overview["frame"].map(lambda frame: frame.shape[1]))
display(integrated_overview.drop(columns="frame"))
display(event_panel[event_panel["rel_year"].isin([-1, 0, 1])].head(3))

release("housing_per_zip", "crashes_per_zip", "injured_per_zip", "check_sites", "check_rows", "all_distances",
        "tree_query", "tree_point", "tree_distance", "brute_query", "brute_point", "tree_order", "injury_pairs",
        "clusters_per_crash", "event_sites", "treated_sites", "earliest_neighbour",
        "treated_per_project", "integrated_overview", "located_housing", "is_other", "repeat_rows")

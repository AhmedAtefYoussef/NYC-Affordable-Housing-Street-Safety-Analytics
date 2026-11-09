"""Stage 2 of the data build: the pre-aggregated crash, housing and site tables the website filters."""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.build.checks import COUNT_COLUMNS, EVENT_OUTCOMES, NOT_NEAR, UNKNOWN_BOROUGH, require
from pipeline.build.frames import as_category, smallest_unsigned, smallest_unsigned_frame


def near_kind_labels(construction_types: list[str], size_bands: list[str]) -> list[str]:
    """Labels of the nearest-site kind: 'Not near a site', then every type and size combination."""
    return [NOT_NEAR] + [f"{kind} | {band}" for kind in construction_types for band in size_bands]


def crash_facts(crashes: pd.DataFrame, sites: pd.DataFrame, boroughs: list[str],
                near_labels: list[str], grid: dict) -> pd.DataFrame:
    """One compact row per crash: the filter dimensions and the seven outcome flags.

    `near` is the kind (construction type and size band) of the nearest housing site when that
    site is within the buffer, which is how the notebook tags crashes in Section 5.
    """
    site_kind = (sites["construction_type"].astype(str) + " | " + sites["size_band"].astype(str))
    site_kind.index = sites["site_id"].to_numpy()
    near = crashes["near_site_id"].map(site_kind).fillna(NOT_NEAR)

    facts = pd.DataFrame({
        "year": crashes["year"].astype("uint16"),
        "month": crashes["month"].astype("uint8"),
        "weekday": crashes["crash_date"].dt.dayofweek.astype("uint8"),      # 0 = Monday
        "hour": crashes["hour"].astype("uint8"),
        "borough": as_category(crashes["borough"].astype(object).fillna(UNKNOWN_BOROUGH),
                               boroughs + [UNKNOWN_BOROUGH]),
        "factor": crashes["factor_group"],
        "hour_band": crashes["hour_band"],
        "near": as_category(near, near_labels),
        "zip": crashes["zip"],
        "in_zip_panel": crashes["in_zip_panel"],
        "n_all": np.uint8(1),
        "n_injury": crashes["is_injury_crash"].astype("uint8"),
        "n_pedcyc": crashes["ped_cyc_harm"].astype("uint8"),
        "n_ped": ((crashes["ped_injured"] + crashes["ped_killed"]) > 0).astype("uint8"),
        "n_cyc": ((crashes["cyc_injured"] + crashes["cyc_killed"]) > 0).astype("uint8"),
        "n_mot": ((crashes["mot_injured"] + crashes["mot_killed"]) > 0).astype("uint8"),
        "n_fatal": (crashes["killed"] > 0).astype("uint8"),
    })
    # Every harmed-road-user flag implies an injury crash, so "injury crashes" is the widest
    # of the six harm options and the others are subsets of it.
    for column in ["n_pedcyc", "n_ped", "n_cyc", "n_mot", "n_fatal"]:
        require((facts[column] <= facts["n_injury"]).all(), f"{column} outside injury crashes")
    require((facts["n_pedcyc"] == np.maximum(facts["n_ped"], facts["n_cyc"])).all(),
            "n_pedcyc is not the larger of n_ped and n_cyc")

    located = crashes["is_located"].to_numpy()
    row = np.floor((crashes["lat"].to_numpy() - grid["lat_min"]) / grid["lat_step"])
    column = np.floor((crashes["lon"].to_numpy() - grid["lon_min"]) / grid["lon_step"])
    cell = np.where(located, row * grid["n_columns"] + column, -1).astype("int32")
    require((cell[located] >= 0).all() and (cell.max() < grid["n_rows"] * grid["n_columns"]),
            "a located crash falls outside the map grid")
    facts["cell"] = cell
    return facts


def aggregate(facts: pd.DataFrame, dimensions: list[str]) -> pd.DataFrame:
    """Sum the seven counts over the given dimensions, keeping only combinations that occur."""
    cube = (facts.groupby(dimensions, observed=True, sort=True)[COUNT_COLUMNS].sum().reset_index())
    for column in COUNT_COLUMNS:
        cube[column] = smallest_unsigned(cube[column])
    require(int(cube["n_all"].sum()) == len(facts), "aggregation must conserve the crash count")
    return cube


def housing_cube(housing: pd.DataFrame, years: list[int], repeat: pd.Series) -> pd.DataFrame:
    """Completed buildings and units by borough, ZIP, completion year, type and size band.

    Confidential rows have no ZIP; they stay in with an empty ZIP so borough totals are whole.
    A building completed again under a later project counts as a building but adds no units
    (`repeat`, the notebook's rule in Section 5), so unit totals match the ZIP x year panel.
    """
    keep = housing["is_completed"] & housing["completion_year"].isin(years)
    done, units = housing[keep], (~repeat[keep]).astype("int64")
    table = pd.DataFrame({
        "borough": done["borough"], "zip": done["zip"].fillna("").astype(str),
        "year": done["completion_year"].astype("uint16"),
        "construction_type": done["construction_type"], "size_band": done["size_band"],
        "is_located": done["is_located"],
        "buildings": 1, "total_units": done["total_units"].astype("int64") * units,
        "affordable_units": done["all_counted_units"].astype("int64") * units,
        "deep_affordable_units": done["deep_affordable_units"].astype("int64") * units,
    })
    measures = ["buildings", "total_units", "affordable_units", "deep_affordable_units"]
    dimensions = [name for name in table.columns if name not in measures]
    cube = table.groupby(dimensions, observed=True, sort=True)[measures].sum().reset_index()
    for column in measures:
        cube[column] = smallest_unsigned(cube[column])
    cube["zip"] = cube["zip"].astype("category")
    require(int(cube["buildings"].sum()) == len(done), "housing_cube must conserve the building count")
    return cube


def site_table(sites: pd.DataFrame, rq7_sites: pd.DataFrame) -> pd.DataFrame:
    """Located housing sites for the map, with the RQ7 baseline percentile where it exists."""
    percentile = rq7_sites.set_index("site_id")[["baseline_crashes", "borough_percentile"]]
    table = sites[["site_id", "cluster_id", "project_name", "borough", "zip", "lat", "lon",
                   "start_year", "completion_year", "construction_type", "size_band",
                   "total_units", "all_counted_units"]].join(percentile, on="site_id")
    table = table.rename(columns={"all_counted_units": "affordable_units"})
    table["lat"] = table["lat"].astype("float32")
    table["lon"] = table["lon"].astype("float32")
    table["zip"] = table["zip"].fillna("").astype(str).astype("category")
    table["project_name"] = table["project_name"].astype(str).str.title().str.slice(0, 60)
    table["completion_year"] = table["completion_year"].astype("float32")       # NaN = not completed
    table["baseline_crashes"] = table["baseline_crashes"].astype("float32")     # NaN = not in RQ7
    # borough_percentile stays float64: the RQ7 mean is recomputed from it and must match the notebook
    require(table["site_id"].is_unique and len(table) == len(sites), "sites table lost or duplicated a site")
    return table


def event_site_table(event_panel: pd.DataFrame, notebook_event_sites: pd.DataFrame,
                     rel_years: list[int]) -> pd.DataFrame:
    """One row per clean site and cohort with yearly counts for three outcomes.

    The rows are in the order of the notebook's `event_sites`, because the bootstrap draws rows
    by position: the same order and seed give the website the notebook's intervals exactly.
    """
    clean = event_panel[~event_panel["contaminated"]]
    keys = ["site_id", "cohort"]
    attributes = clean[clean["rel_year"] == 0].set_index(keys)[
        ["group", "cluster_id", "borough", "construction_type", "size_band", "total_units"]]
    table = attributes
    for short, column in EVENT_OUTCOMES.items():
        counts = clean.pivot(index=keys, columns="rel_year", values=column)[rel_years]
        counts.columns = [f"{short}_{rel_year:+d}" for rel_year in rel_years]
        table = table.join(smallest_unsigned_frame(counts), validate="one_to_one")
    table = table.reset_index()
    table["treated"] = table["group"] == "treated"
    table = table.drop(columns="group")

    # Same rows, same order and same injury counts as the notebook's own table.
    require(len(table) == len(notebook_event_sites), "event_sites has a different row count from the notebook")
    require((table[keys].to_numpy() == notebook_event_sites[keys].to_numpy()).all(),
            "event_sites rows differ in order from the notebook")
    injury = [f"injury_{rel_year:+d}" for rel_year in rel_years]
    notebook_counts = [f"rel_{rel_year:+d}" for rel_year in rel_years]
    require((table[injury].to_numpy() == notebook_event_sites[notebook_counts].to_numpy()).all(),
            "event_sites injury counts differ from the notebook")
    return table

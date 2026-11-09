"""Accuracy audit: every number the site shows, recomputed from the raw files with separate code.

    python -m pytest tests/test_data_accuracy.py -q

Nothing in the `raw` fixture imports the notebook or the site: it reads the two raw CSVs and
applies the documented cleaning rules again (casualty totals repaired from their parts, hour
bands, the ten factor groups, coordinates inside the city box, nearest housing site within
250 m). The tests then compare that with app/data and with what the site's own filter path
returns. The raw crash file is read once per run; the tests skip when the raw files are absent.

Known and accepted differences, asserted here as bounds and not as equalities:
  * borough: the site also fills a missing borough from a ZIP code recovered from coordinates,
    so a borough count is at least the stated count and at most stated + crashes with no borough;
  * nearest-site kind: 15 of 782,969 near crashes sit at an exact distance tie between two sites
    of a different size band and are labelled with the other one.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import random
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from plotly.utils import PlotlyJSONEncoder

from app.core import data
from app.core import filters as filters_module
from app.core.filters import make_filters
from app.core.search import parse_query
from app.ui import callbacks, charts, report, story

ROOT = Path(__file__).resolve().parents[1]
RAW_HOUSING = ROOT / "notebooks" / "housing_hg8x-zxpr.csv"
RAW_CRASHES = ROOT / "notebooks" / "crashes_h9gi-nx95.csv.gz"
NOTEBOOK = ROOT / "notebooks" / "NYC_Housing_Safety.ipynb"
APP_DATA = ROOT / "app" / "data"

EARTH_RADIUS_M = 6_371_000.0
BUFFER_M = 250.0
LAT_BOX, LON_BOX = (40.45, 40.95), (-74.30, -73.65)
NOT_NEAR = "Not near a site"
COUNTS = ["n_all", "n_injury", "n_pedcyc", "n_ped", "n_cyc", "n_mot", "n_fatal"]
# The notebook's ordered keyword rules, typed again here; first match wins, no match is "Other".
FACTOR_RULES = [
    ("Unspecified", r"^unspecified$|^\d+$"),
    ("Pedestrian or cyclist error", r"pedestrian|bicyclist"),
    ("Road or environment", r"pavement|shoulders|lane marking|traffic control device|obstruct|debris|glare|animals"),
    ("Vehicle defect", r"defective|defects|steering|tire|windshield|tinted"),
    ("Impairment or medical", r"alcohol|drugs|medication|asleep|fatigued|drowsy|consciousness|illnes|disability"),
    ("Distraction", r"distraction|inattention|cell phone|electronic|texting|headphones|eating|navigation"),
    ("Speed or aggressive driving", r"speed|aggressive|following too closely"),
    ("Failure to yield or obey", r"yield|disregarded|keep right"),
    ("Improper maneuver", r"passing|lane|turning|backing|inexperience"),
    ("Other", r"other vehicular|uninvolved|vandalism|driverless|oversized"),
]


# ---------------------------------------------------------------------------------------------
# Independent recomputation from the raw files
# ---------------------------------------------------------------------------------------------
def haversine_m(lat_a, lon_a, lat_b, lon_b):
    phi_a, phi_b = np.radians(lat_a), np.radians(lat_b)
    inside = (np.sin((phi_b - phi_a) / 2) ** 2
              + np.cos(phi_a) * np.cos(phi_b) * np.sin(np.radians(lon_b - lon_a) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(inside))


def _unit_sphere(lat, lon):
    lat, lon = np.radians(lat), np.radians(lon)
    return np.c_[np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)]


def _in_city_box(lat: pd.Series, lon: pd.Series) -> pd.Series:
    return lat.between(*LAT_BOX) & lon.between(*LON_BOX)


def _factor_group(label) -> str:
    if not isinstance(label, str):
        return "Unspecified"
    text = label.strip().lower()
    for group, pattern in FACTOR_RULES:
        if re.search(pattern, text):
            return group
    return "Other"


def _raw_housing() -> pd.DataFrame:
    housing = pd.read_csv(RAW_HOUSING, dtype=str)
    for column in ["latitude", "longitude", "total_units", "all_counted_units"]:
        housing[column] = pd.to_numeric(housing[column])
    housing["all_counted_units"] = housing["all_counted_units"].fillna(0)
    housing["located"] = (housing["latitude"].notna() & housing["longitude"].notna()
                          & _in_city_box(housing["latitude"], housing["longitude"]))
    completed = housing["building_completion_date"].fillna(housing["project_completion_date"])
    housing["cyear"] = pd.to_numeric(completed.str[:4])
    # A building completed again under a later project adds no units (the notebook's Section 5 rule).
    done = housing.assign(cdate=pd.to_datetime(completed))
    done = done[done["cdate"].notna() & done["building_id"].notna()].sort_values(["cdate", "project_id"])
    repeat = done.index[done["building_id"].duplicated()]
    units = housing["total_units"]
    housing["band"] = np.select([units <= 4, units <= 19, units <= 49, units <= 149],
                                ["1-4", "5-19", "20-49", "50-149"], "150+")
    for column in ["total_units", "all_counted_units"]:            # units as the aggregates count them
        housing[f"{column}_counted"] = housing[column].where(~housing.index.isin(repeat), 0)
    housing["ctype"] = housing["reporting_construction_type"]
    housing["kind"] = housing["ctype"] + " | " + housing["band"]
    return housing


def _raw_crashes(sites: pd.DataFrame) -> pd.DataFrame:
    from scipy.spatial import cKDTree

    casualties = ["number_of_persons_injured", "number_of_persons_killed", "number_of_pedestrians_injured",
                  "number_of_pedestrians_killed", "number_of_cyclist_injured", "number_of_cyclist_killed",
                  "number_of_motorist_injured", "number_of_motorist_killed"]
    columns = ["crash_date", "crash_time", "borough", "zip_code", "latitude", "longitude",
               "contributing_factor_vehicle_1"] + casualties
    dtypes = {name: "float32" for name in casualties} | {
        "latitude": "float64", "longitude": "float64", "crash_date": str, "crash_time": str,
        "borough": "category", "zip_code": str, "contributing_factor_vehicle_1": "category"}
    source = pd.read_csv(RAW_CRASHES, usecols=columns, dtype=dtypes)
    out = pd.DataFrame(index=source.index)
    when = pd.to_datetime(source["crash_date"].str[:10], format="%Y-%m-%d")
    out["year"], out["month"] = when.dt.year.astype("int16"), when.dt.month.astype("int8")
    out["weekday"] = when.dt.dayofweek.astype("int8")
    out["hour"] = source["crash_time"].str.split(":").str[0].astype("int8")
    out["band"] = pd.Categorical.from_codes(out["hour"] // 6, ["Night", "Morning", "Afternoon", "Evening"])
    part = {name: source[name].fillna(0) for name in casualties}
    injured_parts = part[casualties[2]] + part[casualties[4]] + part[casualties[6]]
    killed_parts = part[casualties[3]] + part[casualties[5]] + part[casualties[7]]
    # the documented repair: a missing total is the sum of its parts, a total below its parts is raised
    out["injured"] = np.maximum(source[casualties[0]].fillna(injured_parts), injured_parts).astype("int32")
    out["killed"] = np.maximum(source[casualties[1]].fillna(killed_parts), killed_parts).astype("int32")
    out["n_all"] = 1
    out["n_injury"] = ((out["injured"] + out["killed"]) > 0).astype("int8")
    out["n_injury_unrepaired"] = ((source[casualties[0]].fillna(0) + source[casualties[1]].fillna(0)) > 0).astype("int8")
    out["n_ped"] = ((part[casualties[2]] + part[casualties[3]]) > 0).astype("int8")
    out["n_cyc"] = ((part[casualties[4]] + part[casualties[5]]) > 0).astype("int8")
    out["n_mot"] = ((part[casualties[6]] + part[casualties[7]]) > 0).astype("int8")
    out["n_pedcyc"] = np.maximum(out["n_ped"], out["n_cyc"])
    out["n_fatal"] = (out["killed"] > 0).astype("int8")
    labels = {label: _factor_group(label) for label in source["contributing_factor_vehicle_1"].cat.categories}
    out["factor"] = (source["contributing_factor_vehicle_1"].astype(object).map(labels)
                     .fillna("Unspecified").astype("category"))
    out["borough"] = source["borough"].astype(object).str.title().fillna("Unknown").astype("category")
    out["zip"] = source["zip_code"].str.strip()
    lat, lon = source["latitude"], source["longitude"]
    located = lat.notna() & lon.notna() & _in_city_box(lat, lon)
    out["lat"], out["lon"], out["located"] = lat.where(located), lon.where(located), located

    # Spatial join. A great-circle distance d is a chord 2 sin(d / 2R) on the unit sphere, so a
    # k-d tree on unit vectors applies the 250 m threshold exactly; the brute-force test checks it.
    tree = cKDTree(_unit_sphere(sites["latitude"].to_numpy(), sites["longitude"].to_numpy()))
    points = _unit_sphere(out.loc[located, "lat"].to_numpy(), out.loc[located, "lon"].to_numpy())
    with np.errstate(invalid="ignore"):
        distance, index = tree.query(points, k=12, distance_upper_bound=2 * np.sin(BUFFER_M / (2 * EARTH_RADIUS_M)))
        near = np.isfinite(distance[:, 0])
        # equally near sites: earliest completion year first (missing last), then the lower site id
        completion = np.append(np.where(sites["cyear"].isna(), np.inf, sites["cyear"]).astype(float), np.inf)
        tied = np.isfinite(distance) & (np.abs(distance - distance[:, [0]]) <= 1e-12)
    best = index[np.arange(len(index)), np.where(tied, completion[index] * 1e5 + index, np.inf).argmin(axis=1)]
    kinds = np.append(sites["kind"].to_numpy(), NOT_NEAR)
    kind = np.full(len(out), NOT_NEAR, dtype=object)
    kind[np.flatnonzero(located.to_numpy())] = np.where(near, kinds[np.minimum(best, len(sites))], NOT_NEAR)
    out["near"] = pd.Categorical(kind)
    out["is_near"] = out["near"] != NOT_NEAR
    return out


@pytest.fixture(scope="module")
def raw():
    """Housing rows, located sites and one row per crash, all rebuilt from the raw files."""
    if not (RAW_HOUSING.exists() and RAW_CRASHES.exists()):
        pytest.skip("raw data files are not in notebooks/")
    pytest.importorskip("scipy")
    housing = _raw_housing()
    sites = housing[housing["located"]].reset_index(drop=True)
    return {"housing": housing, "sites": sites, "crashes": _raw_crashes(sites)}


@pytest.fixture(scope="module")
def store():
    return data.load()


@pytest.fixture(scope="module")
def tables():
    return {path.stem: pd.read_parquet(path) for path in APP_DATA.glob("*.parquet")}


def _keyed(series: pd.Series) -> pd.Series:
    """A count series with a plain string key per group and zero groups removed, so two sources align."""
    series = pd.Series(series).astype("int64")

    def text(value):
        return str(int(value)) if isinstance(value, (int, np.integer, float, np.floating)) else str(value)

    series.index = ["|".join(text(part) for part in (key if isinstance(key, tuple) else (key,)))
                    for key in series.index]
    return series[series != 0].sort_index()


def assert_same_counts(independent: pd.Series, site: pd.Series) -> None:
    left, right = _keyed(independent).align(_keyed(site), fill_value=0)
    different = left[left != right]
    assert different.empty, f"{len(different)} groups differ, first: {different.index[0]} raw={different.iloc[0]}"


# ---------------------------------------------------------------------------------------------
# 1. Raw data against the exported tables
# ---------------------------------------------------------------------------------------------
def test_row_counts(raw, store):
    crashes, rows = raw["crashes"], store.meta["rows"]
    assert len(raw["housing"]) == rows["housing"] == 9551
    assert len(crashes) == rows["crashes"] == 1_504_722
    assert int(crashes["n_injury"].sum()) == rows["injury_crashes"]
    assert int(crashes["located"].sum()) == rows["crashes_located"]
    assert int(crashes["is_near"].sum()) == rows["crashes_near_a_site"]
    assert len(raw["sites"]) == rows["sites"] == rows["housing_located"]
    # the repair of casualty totals adds a few injury crashes; without it the count is lower
    assert 0 < rows["injury_crashes"] - int(crashes["n_injury_unrepaired"].sum()) < 500


def test_city_year_table(raw, tables):
    crashes, city = raw["crashes"], tables["city_year"].set_index("year")
    by_year = crashes.groupby("year")
    for raw_column, site_column in [("n_all", "crashes"), ("n_injury", "injury_crashes"), ("injured", "persons_injured"),
                                    ("killed", "persons_killed"), ("n_pedcyc", "ped_cyc_crashes")]:
        assert_same_counts(by_year[raw_column].sum(), city[site_column])
    n_all, n_injury = by_year["n_all"].sum(), by_year["n_injury"].sum()
    np.testing.assert_allclose(n_all / n_all[2019] * 100, city["crash_index"])
    np.testing.assert_allclose(n_injury / n_injury[2019] * 100, city["injury_crash_index"])
    np.testing.assert_allclose(n_injury / n_all, city["injury_share"])
    np.testing.assert_allclose(by_year["killed"].sum() / n_injury * 1000, city["deaths_per_1000_injury_crashes"])


@pytest.mark.parametrize("column", COUNTS)
def test_crash_cube_counts(raw, tables, column):
    """Every count column, by year, month, factor group and time of day (borough is tested apart)."""
    cube = tables["crash_cube"].assign(factor=lambda t: t["factor"].astype(str).replace(data.US_SPELLING))
    assert_same_counts(raw["crashes"].groupby(["year", "month", "factor", "band"], observed=True)[column].sum(),
                       cube.groupby(["year", "month", "factor", "hour_band"], observed=True)[column].sum())


def test_hour_cube_counts(raw, tables):
    for column in ["n_all", "n_injury", "n_fatal"]:
        assert_same_counts(raw["crashes"].groupby(["year", "weekday", "hour"])[column].sum(),
                           tables["hour_cube"].groupby(["year", "weekday", "hour"])[column].sum())


def test_map_grid_counts(raw, tables, store):
    grid, located = store.meta["grid"], raw["crashes"][raw["crashes"]["located"]]
    cell = (np.floor((located["lat"] - grid["lat_min"]) / grid["lat_step"]) * grid["n_columns"]
            + np.floor((located["lon"] - grid["lon_min"]) / grid["lon_step"])).astype(int).to_numpy()
    assert int(tables["map_grid"]["n_all"].sum()) == len(located)          # unlocated crashes are off the map
    for column in ["n_all", "n_injury"]:
        assert_same_counts(located.groupby([cell, located["year"].to_numpy()])[column].sum(),
                           tables["map_grid"].groupby(["cell", "year"])[column].sum())


def test_borough_counts_are_stated_plus_recovered(raw, tables, store):
    crashes, cube = raw["crashes"], tables["crash_cube"]
    stated = crashes.groupby(["borough", "year"], observed=True)["n_all"].sum().unstack(0, fill_value=0)
    site = cube.groupby(["borough", "year"], observed=True)["n_all"].sum().unstack(0, fill_value=0)
    boroughs = store.meta["dimensions"]["boroughs"]
    assert (site[boroughs] >= stated[boroughs]).to_numpy().all()           # a stated borough is never changed
    filled = int((site[boroughs] - stated[boroughs]).to_numpy().sum())
    log = tables["cleaning_log"]
    # Two logged rules fill a borough: from the crash's ZIP, and by a vote of nearby reported crashes.
    borough_rules = log["rule"].str.startswith("missing borough filled") | log["rule"].str.startswith("borough of located crashes")
    assert int(borough_rules.sum()) == 2
    logged = int(log.loc[borough_rules, "affected"].sum())
    assert filled == logged == int(stated["Unknown"].sum() - site["Unknown"].sum())
    # what stays unknown: every crash with neither borough nor coordinates, plus located ones in empty cells
    no_borough_no_point = int(((crashes["borough"] == "Unknown") & ~crashes["located"]).sum())
    assert no_borough_no_point <= int(site["Unknown"].sum()) <= no_borough_no_point + 30_000


def test_zip_tables(raw, tables):
    crashes, zip_year, zip_cube = raw["crashes"], tables["zip_year"], tables["zip_cube"]
    key = [zip_year["zip"].astype(str), zip_year["year"]]
    in_panel = crashes[crashes["zip"].isin(set(zip_year["zip"].astype(str)))]
    stated = zip_year["crashes"].astype(int) - zip_year["crashes_zip_imputed"]
    stated_injury = zip_year["injury_crashes"].astype(int) - zip_year["injury_crashes_zip_imputed"]
    assert_same_counts(in_panel.groupby(["zip", "year"])["n_all"].sum(), stated.groupby(key).sum())
    assert_same_counts(in_panel.groupby(["zip", "year"])["n_injury"].sum(), stated_injury.groupby(key).sum())
    cube_key = [zip_cube["zip"].astype(str), zip_cube["year"]]
    assert_same_counts(zip_cube.groupby(cube_key)["n_all"].sum(), zip_year.groupby(key)["crashes"].sum())
    assert_same_counts(zip_cube.groupby(cube_key)["n_injury"].sum(), zip_year.groupby(key)["injury_crashes"].sum())


def test_housing_cube(raw, tables, store):
    constants = store.meta["constants"]
    done = raw["housing"][raw["housing"]["cyear"].between(constants["year_start"], constants["year_end"])]
    done = done.assign(n=1, cyear=done["cyear"].astype(int))
    cube = tables["housing_cube"]
    assert (len(done), int(done["total_units_counted"].sum()), int(done["all_counted_units_counted"].sum())) == (
        int(cube["buildings"].sum()), int(cube["total_units"].sum()), int(cube["affordable_units"].sum()))
    raw_dims = ["borough", "cyear", "ctype", "band", "located"]
    site_dims = ["borough", "year", "construction_type", "size_band", "is_located"]
    for raw_column, site_column in [("n", "buildings"), ("all_counted_units_counted", "affordable_units"),
                                    ("total_units_counted", "total_units")]:
        assert_same_counts(done.groupby(raw_dims)[raw_column].sum(),
                           cube.groupby(site_dims, observed=True)[site_column].sum())
    assert_same_counts(done.assign(z=done["postcode"].fillna("")).groupby("z")["all_counted_units_counted"].sum(),
                       cube.groupby(cube["zip"].astype(str))["affordable_units"].sum())


def test_sites_table(raw, tables):
    sites, table = raw["sites"], tables["sites"]
    assert len(sites) == len(table)
    np.testing.assert_allclose(table["lat"], sites["latitude"], atol=1e-5)        # float32 on the site
    np.testing.assert_allclose(table["lon"], sites["longitude"], atol=1e-5)
    assert (table["construction_type"].astype(str).to_numpy() == sites["ctype"].to_numpy()).all()
    assert (table["size_band"].astype(str).to_numpy() == sites["band"].to_numpy()).all()
    assert (table["completion_year"].fillna(-1).to_numpy() == sites["cyear"].fillna(-1).to_numpy()).all()
    assert (table["total_units"].to_numpy() == sites["total_units"].to_numpy()).all()


# ---------------------------------------------------------------------------------------------
# 1b. The site's own filter path against independent counts
# ---------------------------------------------------------------------------------------------
FILTER_CASES = {
    "default": {},
    "bronx_2019_2021": dict(boroughs=["Bronx"], year_from=2019, year_to=2021),
    "brooklyn_2022_new": dict(boroughs=["Brooklyn"], year_from=2022, year_to=2022, construction=["New Construction"]),
    "pedestrians_night": dict(harm="ped", hours=["Night"]),
    "distraction": dict(factors=["Distraction"]),
    "single_year_all": dict(year_from=2020, year_to=2020, harm="all"),
    "near_preservation_pedcyc": dict(year_from=2023, year_to=2025, harm="pedcyc", scope="near",
                                     construction=["Preservation"]),
    "queens_manhattan_fatal_near": dict(boroughs=["Queens", "Manhattan"], harm="fatal", scope="near"),
    "cyclists_evening_yield_2016_2017": dict(year_from=2016, year_to=2017, harm="cyc", hours=["Evening"],
                                             factors=["Failure to yield or obey"]),
}



def _random_filter_cases(count: int = 40, seed: int = 20261101):
    """Seeded random combinations of every filter the crash path recomputes above (size bands stay out, as there)."""
    rng = random.Random(seed)
    for number in range(count):
        first = rng.randint(filters_module.YEAR_START, filters_module.YEAR_END)
        case = dict(year_from=first, year_to=rng.randint(first, filters_module.YEAR_END),
                    harm=rng.choice(list(filters_module.HARM)), scope=rng.choice(list(filters_module.SCOPE)))
        for key, values in (("boroughs", filters_module.BOROUGHS), ("hours", filters_module.HOUR_BANDS),
                            ("factors", filters_module.FACTOR_GROUPS), ("construction", filters_module.CONSTRUCTION_TYPES)):
            if rng.random() < 0.5:
                case[key] = rng.sample(list(values), rng.randint(1, len(values) - 1))
        yield f"random_{number:02d}", case


FILTER_CASES.update(_random_filter_cases())

@pytest.mark.parametrize("name", list(FILTER_CASES))
def test_headline_numbers_through_site_filters(raw, store, name):
    filters = make_filters(**FILTER_CASES[name])
    numbers = data.headline_numbers(store, filters)
    crashes, column = raw["crashes"], filters.harm_column

    rows = crashes["year"].between(filters.year_from, filters.year_to)
    if filters.factors:
        rows &= crashes["factor"].isin(filters.factors)
    if filters.hours:
        rows &= crashes["band"].isin(filters.hours)
    near = crashes["is_near"]
    if filters.construction:          # kind of the nearest site; the size band is left out (15 known tie rows)
        near = near & crashes["near"].astype(str).str.split(" | ", regex=False).str[0].isin(filters.construction)
    scoped = rows & near if filters.scope == "near" else rows
    if not filters.boroughs:
        assert numbers["crashes"] == int(crashes.loc[scoped, column].sum())
        assert numbers["crashes_near"] == int(crashes.loc[rows & near, column].sum())
        assert numbers["crashes_anywhere"] == int(crashes.loc[rows, column].sum())
        # the charts carry the same total; the trend lines leave out crashes with no borough
        assert int(data.factor_mix(store, filters).sum()) == numbers["crashes"]
        assert int(data.weekday_hour(store, filters).sum()) == numbers["crashes"]
        assert int(data.crash_trend(store, filters).to_numpy().sum()) == (
            numbers["crashes"] - numbers["crashes_unknown_borough"])
        assert int(data.map_cells(store, filters)["crashes"].sum()) == int(
            crashes.loc[scoped & crashes["located"], column].sum())
    else:
        stated = int(crashes.loc[scoped & crashes["borough"].isin(filters.boroughs), column].sum())
        no_borough = int(crashes.loc[scoped & (crashes["borough"] == "Unknown"), column].sum())
        assert stated <= numbers["crashes"] <= stated + no_borough
        assert numbers["crashes_unknown_borough"] == 0

    housing = raw["housing"]
    keep = housing["cyear"].between(filters.year_from, filters.year_to)
    if filters.boroughs:
        keep &= housing["borough"].isin(filters.boroughs)
    if filters.construction:
        keep &= housing["ctype"].isin(filters.construction)
    if filters.sizes:
        keep &= housing["band"].isin(filters.sizes)
    homes = housing[keep]
    assert numbers["buildings"] == len(homes)
    assert numbers["buildings_unlocated"] == int((~homes["located"]).sum())
    assert numbers["affordable_units"] == int(homes["all_counted_units_counted"].sum())
    assert numbers["total_units"] == int(homes["total_units_counted"].sum())
    assert len(data.map_sites(store, filters)) == int(homes["located"].sum())
    by_year = data.completions_by_year(store, filters)
    assert_same_counts(homes.groupby([homes["cyear"].astype(int), "ctype"])["all_counted_units_counted"].sum(),
                       by_year["affordable_units"].stack())


# ---------------------------------------------------------------------------------------------
# 2. The spatial claim
# ---------------------------------------------------------------------------------------------
def test_within_250m_by_brute_force(raw):
    """400 random located crashes: haversine distance to all 7,593 sites agrees with the tree join."""
    crashes, sites = raw["crashes"], raw["sites"]
    sample = crashes[crashes["located"]].sample(400, random_state=20261010)
    distance = haversine_m(sample["lat"].to_numpy()[:, None], sample["lon"].to_numpy()[:, None],
                           sites["latitude"].to_numpy()[None, :], sites["longitude"].to_numpy()[None, :])
    assert ((distance.min(axis=1) <= BUFFER_M) == sample["is_near"].to_numpy()).all()
    assert 150 < int(sample["is_near"].sum()) < 300           # 57% of located crashes citywide


def test_near_counts_match_site_tables(raw, tables, store):
    crashes, cube, grid_table = raw["crashes"], tables["crash_cube"], tables["map_grid"]
    site_flag = cube["near"].astype(str) != NOT_NEAR
    assert_same_counts(crashes.groupby(["year", "month", "is_near"])["n_all"].sum(),
                       cube.groupby(["year", "month", site_flag])["n_all"].sum())
    assert_same_counts(crashes.groupby(["year", "is_near"])["n_injury"].sum(),
                       cube.groupby(["year", site_flag])["n_injury"].sum())
    # the same flag cell by cell, which pins it to places and not only to totals
    grid, located = store.meta["grid"], crashes[crashes["located"]]
    cell = (np.floor((located["lat"] - grid["lat_min"]) / grid["lat_step"]) * grid["n_columns"]
            + np.floor((located["lon"] - grid["lon_min"]) / grid["lon_step"])).astype(int).to_numpy()
    assert_same_counts(located.groupby([cell, located["is_near"].to_numpy()])["n_all"].sum(),
                       grid_table.groupby(["cell", grid_table["near"].astype(str) != NOT_NEAR])["n_all"].sum())
    # kind of the nearest site: equal except for a handful of exact distance ties
    independent = crashes.groupby("near", observed=True)["n_all"].sum()
    site = cube.groupby("near", observed=True)["n_all"].sum()
    independent, site = _keyed(independent).align(_keyed(site), fill_value=0)
    assert int((independent - site).abs().sum()) // 2 <= 20
    construction = lambda counts: counts.groupby(counts.index.str.split(" | ", regex=False).str[0]).sum()
    assert construction(independent).equals(construction(site))


def test_event_site_counts_by_brute_force(raw, tables):
    """Yearly counts within 250 m of 40 event-study sites, and the 2016 to 2018 baseline of 40 sites."""
    located = raw["crashes"][raw["crashes"]["located"]]
    sites, event_sites, site_table = raw["sites"], tables["event_sites"], tables["sites"]

    def crashes_near(site_id: int) -> pd.DataFrame:
        lat, lon = sites["latitude"][site_id], sites["longitude"][site_id]
        box = located[(located["lat"].sub(lat).abs() < 0.004) & (located["lon"].sub(lon).abs() < 0.005)]
        return box[haversine_m(box["lat"].to_numpy(), box["lon"].to_numpy(), lat, lon) <= BUFFER_M]

    for row in event_sites.sample(40, random_state=3).itertuples():
        near = crashes_near(row.site_id)
        for offset in range(-3, 4):
            in_year = near[near["year"] == row.cohort + offset]
            for outcome, column in [("injury", "n_injury"), ("all", "n_all"), ("pedcyc", "n_pedcyc")]:
                assert int(in_year[column].sum()) == int(event_sites.loc[row.Index, f"{outcome}_{offset:+d}"])
    for row in site_table[site_table["baseline_crashes"].notna()].sample(40, random_state=5).itertuples():
        near = crashes_near(row.site_id)
        assert int(near.loc[near["year"].between(2016, 2018), "n_injury"].sum()) == int(row.baseline_crashes)


# ---------------------------------------------------------------------------------------------
# 3. Statistics: results.json against the executed notebook, and the story against results.json
# ---------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def notebook_output_text():
    if not NOTEBOOK.exists():
        pytest.skip("the executed notebook is not in notebooks/")
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    pieces = []
    for cell in notebook["cells"]:
        for output in cell.get("outputs", []):
            pieces.append("".join(output.get("text", "")))
            pieces += ["".join(value) for kind, value in output.get("data", {}).items() if kind.startswith("text/")]
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", "\n".join(pieces)))


def test_result_sentences_are_the_notebooks(store, notebook_output_text):
    questions = store.results["questions"]
    assert list(questions) == [f"RQ{number}" for number in range(1, 11)]
    for key, item in questions.items():
        assert re.sub(r"\s+", " ", item["sentence"]) in notebook_output_text, key
        assert item["low"] <= item["estimate"] <= item["high"]
        assert item["excludes_zero"] == (item["low"] > 0 or item["high"] < 0)


def test_facts_recomputed_from_raw(raw, store):
    crashes, housing = raw["crashes"], raw["housing"]
    facts, limits = store.results["facts"], store.results["limits"]
    by_year = crashes.groupby("year")
    assert facts["crash_index"] == pytest.approx(by_year["n_all"].sum()[2025] / by_year["n_all"].sum()[2019] * 100)
    assert facts["injury_index"] == pytest.approx(by_year["n_injury"].sum()[2025] / by_year["n_injury"].sum()[2019] * 100)
    assert facts["sites"] == len(raw["sites"])
    assert limits["unlocated_share"] == pytest.approx((~crashes["located"]).mean() * 100)
    assert limits["unlocated_share_first_year"] == pytest.approx((~crashes.loc[crashes["year"] == 2016, "located"]).mean() * 100)
    assert limits["no_factor_share"] == pytest.approx((crashes["factor"] == "Unspecified").mean() * 100)
    confidential = housing["project_name"].str.strip().str.upper() == "CONFIDENTIAL"
    completed = housing["building_completion_date"].fillna(housing["project_completion_date"])
    same_day = (completed == housing["project_start_date"])[completed.notna()]
    assert limits["same_day_share"] == pytest.approx(same_day.mean() * 100)
    assert limits["confidential_rows"] == int(confidential.sum())
    assert limits["confidential_unit_share"] == pytest.approx(
        housing.loc[confidential, "total_units"].sum() / housing["total_units"].sum() * 100)
    assert limits["headline_intervals"] == len(store.results["questions"])
    assert limits["robustness_intervals"] == len(store.robustness)


def test_site_statistics_reproduce_results(store):
    """The statistics the report recomputes on demand give the notebook's stored numbers."""
    questions, detail = store.results["questions"], store.results["detail"]
    new_only = data.event_study(store, make_filters(construction=["New Construction"]))
    did = new_only["treated"]["New Construction"]["did"]
    assert (did["percent_change"], did["percent_low"], did["percent_high"], did["n_treated"]) == pytest.approx(
        (questions["RQ3"]["estimate"], questions["RQ3"]["low"], questions["RQ3"]["high"], questions["RQ3"]["n"]))
    both = data.event_study(store, make_filters())
    for kind, stored in detail["rq5_by_type"].items():
        if kind in both["treated"]:
            did = both["treated"][kind]["did"]
            assert (did["percent_change"], did["percent_low"], did["percent_high"]) == pytest.approx(
                (stored["percent"], stored["low"], stored["high"]))
    assert both["difference"]["percent_change"] == pytest.approx(questions["RQ5"]["estimate"])
    selection = data.site_selection(store, make_filters(construction=["New Construction"]))
    assert (selection["excess"], selection["low"], selection["high"], selection["n"]) == pytest.approx(
        (questions["RQ7"]["estimate"], questions["RQ7"]["low"], questions["RQ7"]["high"], questions["RQ7"]["n"]))
    assert selection["share_above_median"] == pytest.approx(detail["rq7_new_sites"]["share_above_borough_median_pct"])


def _text(component) -> str:
    """All visible text of a Dash component tree."""
    if component is None:
        return ""
    if isinstance(component, (str, int, float)):
        return str(component)
    if isinstance(component, (list, tuple)):
        return " ".join(_text(child) for child in component)
    return _text(getattr(component, "children", None))


def test_story_numbers_come_from_the_data(store):
    """Change the stored results and the story text changes with them: nothing is typed in."""
    results, meta = copy.deepcopy(store.results), copy.deepcopy(store.meta)
    rq3, rq7 = results["questions"]["RQ3"], results["questions"]["RQ7"]
    rq3.update(estimate=-7.77, low=-21.21, high=6.66, n=4321)
    rq7.update(estimate=33.33, low=31.11, high=36.66, n=8765)
    results["facts"].update(crash_index=12.0, injury_index=34.0, sites=7001, treated_clean=5551,
                            treated_candidates=6661, share_in_largest=91.0)
    results["limits"].update(unlocated_share=44.4, confidential_rows=1234, no_factor_share=55.5,
                             imputed_zip_share=66.6, same_day_share=77.0)
    meta["rows"].update(housing=9001, crashes=2_600_000, panel_zips=199, zip_year=1990, crashes_near_a_site=700_001)
    changed = dataclasses.replace(store, results=results, meta=meta)

    hero = _text(story.hero(changed))
    for expected in ["−7.8%", "−21.2%", "+6.7%", "4,321 sites", "83th", "8,765 sites", "9,001", "2.6 million"]:
        assert expected in hero, expected
    assert "−4.6" not in hero and "128 sites" not in hero
    limits_text = _text(story.limits(changed))
    for expected in ["stood at 12", "stood at 34", "44.4%", "1,234 housing", "55.5%", "66.6%", "77%", "4,321 new buildings"]:
        assert expected in limits_text, expected
    findings = _text(story.findings(changed))
    for expected in ["91% of the 7,001", "5,551", "6,661", "4,321 of those"]:
        assert expected in findings, expected
    method = _text(story.data_and_method(changed))
    for expected in ["9,001 buildings", "2,600,000 crashes", "199 ZIP codes", "1,990 rows", "700,001 crashes"]:
        assert expected in method, expected
    impact = _text(story.impact(changed))
    assert "4,321 new-construction sites" in impact and "5,551 completed sites" in impact


def test_filter_constants_equal_the_exported_metadata(store):
    """The lists typed into app/core/filters.py are the ones the data was built with."""
    dimensions, constants = store.meta["dimensions"], store.meta["constants"]
    assert filters_module.BOROUGHS == dimensions["boroughs"]
    assert filters_module.CONSTRUCTION_TYPES == dimensions["construction_types"]
    assert filters_module.SIZE_BANDS == dimensions["size_bands"]
    assert filters_module.HOUR_BANDS == dimensions["hour_bands"]
    assert filters_module.FACTOR_GROUPS == [data.US_SPELLING.get(name, name) for name in dimensions["factor_groups"]]
    assert (filters_module.YEAR_START, filters_module.YEAR_END) == (constants["year_start"], constants["year_end"])
    assert filters_module.BUFFER_M == constants["buffer_m"]
    assert data.MIN_GROUP_N == constants["min_group_n"]
    assert len(data.PRE_YEARS) == len(data.POST_YEARS) == constants["event_window"]
    treated = store.event_sites.loc[store.event_sites["treated"], "cohort"]
    assert (int(treated.min()), int(treated.max())) == (2019, 2022)         # typed into the event chart's scope line
    city = store.city_year.set_index("year")
    without_injury = city["crashes"] - city["injury_crashes"]
    assert 0.45 < 1 - without_injury[2020] / without_injury[2019] < 0.55    # "fell by about half that year"


# ---------------------------------------------------------------------------------------------
# 4. Charts: what is plotted equals the filtered table
# ---------------------------------------------------------------------------------------------
CHART_CASES = {
    "default": {},
    "bronx_pedestrians_2019_2021": dict(boroughs=["Bronx"], year_from=2019, year_to=2021, harm="ped"),
    "brooklyn_2022_new_near": dict(boroughs=["Brooklyn"], year_from=2022, year_to=2022,
                                   construction=["New Construction"], scope="near"),
    "single_year_all": dict(year_from=2020, year_to=2020, harm="all"),
}


def _numbers(values) -> np.ndarray:
    return np.asarray(values, dtype=float)


@pytest.fixture(scope="module", params=list(CHART_CASES))
def built(request, store):
    filters = make_filters(**CHART_CASES[request.param])
    return filters, report.build_report(store, filters)


def test_trend_chart(built, store):
    filters, result = built
    trend, figure = data.crash_trend(store, filters), result["panels"]["trend"].figure
    assert [trace.name for trace in figure.data] == list(trend.columns)
    assert list(trend.columns) == (list(filters.boroughs) or store.meta["dimensions"]["boroughs"])
    for trace in figure.data:
        assert (_numbers(trace.y) == trend[trace.name].to_numpy()).all()
        assert len(trace.x) == filters.n_years * (12 if filters.n_years <= data.MONTHLY_UP_TO_YEARS else 1)
    numbers = result["numbers"]
    assert sum(_numbers(trace.y).sum() for trace in figure.data) == numbers["crashes"] - numbers["crashes_unknown_borough"]
    assert figure.layout.yaxis.type != "log" and figure.layout.yaxis.rangemode == "tozero"


def test_factor_chart(built, store):
    filters, result = built
    factors, bar = data.factor_mix(store, filters), result["panels"]["factors"].figure.data[0]
    assert len(bar.x) == len(factors) == 10                                   # no group is dropped
    plotted = dict(zip(bar.y, _numbers(bar.x)))
    for name, value in factors.items():
        assert plotted["No factor recorded" if name == charts.UNSPECIFIED else name] == value
    assert _numbers(bar.x).sum() == result["numbers"]["crashes"]
    assert _numbers(bar.customdata).sum() == pytest.approx(100)


def test_heatmap_chart(built, store):
    filters, result = built
    heat = result["panels"]["heatmap"].figure.data[0]
    assert (_numbers(heat.z) == data.weekday_hour(store, filters)).all()
    assert _numbers(heat.z).shape == (7, 24) and list(heat.y) == charts.WEEKDAYS and len(heat.x) == 24
    assert _numbers(heat.z).sum() == result["numbers"]["crashes"] and heat.zmin == 0


def test_completions_chart(built, store):
    filters, result = built
    tables, figure = data.completions_by_year(store, filters), result["panels"]["completions"].figure
    assert [trace.name for trace in figure.data] == list(tables["affordable_units"].columns)
    for trace in figure.data:
        assert list(trace.x) == filters.years
        assert (_numbers(trace.y) == tables["affordable_units"][trace.name].to_numpy()).all()
        assert (_numbers(trace.customdata) == tables["buildings"][trace.name].to_numpy()).all()
    assert sum(_numbers(trace.y).sum() for trace in figure.data) == result["numbers"]["affordable_units"]
    assert sum(_numbers(trace.customdata).sum() for trace in figure.data) == result["numbers"]["buildings"]
    assert figure.layout.barmode == "stack"


def test_scatter_chart(built, store):
    filters, result = built
    relation, figure = data.zip_relation(store, filters), result["panels"]["scatter"].figure
    table, points = relation["table"], figure.data[0]
    assert len(points.x) == len(table) and (_numbers(points.x) == table["affordable_units"].to_numpy()).all()
    assert (table["affordable_units"] > 0).all()                 # the log axis has no zero to hide: those ZIPs are counted
    assert len(table) + relation["n_without_units"] == len(
        [name for name in store.zip_borough.index if not filters.boroughs or store.zip_borough[name] in filters.boroughs])
    assert f"{relation['n_without_units']} ZIP codes without matching housing" in _text(result["panels"]["scatter"].note)
    drawn = table["crashes"] > 0                                  # in these selections every ZIP has a crash
    assert drawn.all() and np.allclose(_numbers(points.y), table["crashes_per_year"])
    assert figure.layout.xaxis.type == figure.layout.yaxis.type == "log"


def test_map_chart(built, store):
    filters, result = built
    cells, sites = data.map_cells(store, filters), data.map_sites(store, filters)
    figure = result["panels"]["map"].figure
    density = [trace for trace in figure.data if trace.type == "choroplethmap"][0]
    markers = [trace for trace in figure.data if trace.type == "scattermap"]
    assert (_numbers(density.z) == cells["crashes"].to_numpy()).all() and list(density.locations) == list(cells["cell"])
    assert sum(len(trace.lat) for trace in markers) == len(sites)
    for trace in markers:                                         # the legend count is the number of dots
        assert f"({len(trace.lat):,})" in trace.name
    if filters.scope != "near" and not filters.boroughs:
        assert _numbers(density.z).sum() <= result["numbers"]["crashes"]     # unlocated crashes are not drawn


def test_event_and_selection_charts(built, store):
    filters, result = built
    study, figure = data.event_study(store, filters), result["panels"]["event"].figure
    assert not study.get("empty")
    lines = [trace for trace in figure.data if trace.mode == "lines+markers"]
    bands = [trace for trace in figure.data if trace.fill == "toself"]
    profiles = [study["comparison"]] + [part["profile"] for part in study["treated"].values()]
    assert len(lines) == len(bands) == len(profiles)
    for line, band, profile in zip(lines, bands, profiles):
        assert np.allclose(_numbers(line.y), profile["index"]) and list(line.x) == data.REL_YEARS
        assert np.allclose(_numbers(band.y), np.r_[_numbers(profile["high"]), _numbers(profile["low"])[::-1]])
        assert f"n = {profile['n_sites']:,}" in line.name
    selection, bars = data.site_selection(store, filters), result["panels"]["selection"].figure.data[0]
    assert np.allclose(_numbers(bars.y), selection["bin_share"]) and len(bars.y) == 10
    assert _numbers(bars.y).sum() == pytest.approx(100)


def test_story_charts(store):
    figure = charts.reporting_break_figure(store.city_year)
    for trace, column in zip(figure.data, ["crash_index", "injury_crash_index"]):
        assert np.allclose(_numbers(trace.y), store.city_year[column]) and list(trace.x) == list(store.city_year["year"])
    low, high = figure.layout.xaxis.range
    assert low < store.city_year["year"].min() and high > store.city_year["year"].max()

    table = store.robustness[store.robustness["estimate"].notna()]
    figure = charts.robustness_figure(store.robustness)
    assert sum(len(trace.x) for trace in figure.data) == len(table) == len(store.robustness)
    kinds = {"Central estimate": "central", "One choice changed": "check", "Placebo (no change expected)": "placebo"}
    for trace in figure.data:
        rows = table[table["kind"] == kinds[trace.name]]
        limit = charts.FOREST_LIMIT
        assert np.allclose(_numbers(trace.x), rows["percent_change"])                     # no estimate is clipped
        assert np.allclose(_numbers(trace.x) + _numbers(trace.error_x.array), rows["percent_high"].clip(upper=limit))
        assert np.allclose(_numbers(trace.x) - _numbers(trace.error_x.arrayminus), rows["percent_low"].clip(lower=-limit))
        assert np.allclose(_numbers(trace.customdata)[:, :3], rows[["percent_change", "percent_low", "percent_high"]])
    # every interval cut at the plot edge is labelled with its true end
    assert (table["percent_low"] >= -charts.FOREST_LIMIT).all()
    cut = table[table["percent_high"] > charts.FOREST_LIMIT]
    notes = [note.text for note in figure.layout.annotations]
    assert sorted(notes) == sorted(f"interval runs to {value:+.0f}%" for value in cut["percent_high"])


# ---------------------------------------------------------------------------------------------
# 5. Search
# ---------------------------------------------------------------------------------------------
SEARCH_CASES = [
    ("Brooklyn 2022 new buildings", dict(boroughs=["Brooklyn"], year_from=2022, year_to=2022,
                                         construction=["New Construction"], scope="near"), []),
    ("bronx pedestrians night 2019-2021", dict(boroughs=["Bronx"], year_from=2019, year_to=2021, hours=["Night"],
                                               harm="ped"), []),
    ("queens cyclists speeding since 2021", dict(boroughs=["Queens"], year_from=2021,
                                                 factors=["Speed or aggressive driving"], harm="cyc"), []),
    ("manhattan large buildings near housing", dict(boroughs=["Manhattan"], sizes=["50-149", "150+"], scope="near"), []),
    ("brooklin 2020", dict(boroughs=["Brooklyn"], year_from=2020, year_to=2020), []),
    ("manhatan preservation", dict(boroughs=["Manhattan"], construction=["Preservation"], scope="near"), []),
    ("staten island fatal 2018 to 2020", dict(boroughs=["Staten Island"], year_from=2018, year_to=2020, harm="fatal"), []),
    ("si deaths", dict(boroughs=["Staten Island"], harm="fatal"), []),
    ("bx and bk 2017", dict(boroughs=["Bronx", "Brooklyn"], year_from=2017, year_to=2017), []),
    ("2021", dict(year_from=2021, year_to=2021), []),
    ("from 2023", dict(year_from=2023), []),
    ("until 2018", dict(year_to=2018), []),
    ("before 2019", dict(year_to=2018), []),
    ("after 2022", dict(year_from=2023), []),
    ("2022-2019", dict(year_from=2019, year_to=2022), []),
    ("between 2018 and 2020", dict(year_from=2018, year_to=2020), []),
    ("QUEENS!!! 2019–2021", dict(boroughs=["Queens"], year_from=2019, year_to=2021), []),
    ("drunk driving", dict(factors=["Impairment or medical"]), []),
    ("speeding morning", dict(factors=["Speed or aggressive driving"], hours=["Morning"]), []),
    ("failure to yield afternoon", dict(factors=["Failure to yield or obey"], hours=["Afternoon"]), []),
    ("preservation small buildings", dict(construction=["Preservation"], sizes=["1-4", "5-19"], scope="near"), []),
    ("towers", dict(sizes=["150+"], scope="near"), []),
    ("within 250m new construction 50-149 units", dict(construction=["New Construction"], sizes=["50-149"],
                                                       scope="near"), []),
    ("pedestrians and cyclists", dict(harm="pedcyc"), []),
    ("all crashes 2020", dict(year_from=2020, year_to=2020, harm="all"), []),
    ("night and morning", dict(hours=["Night", "Morning"]), []),
    ("new construction and preservation", {}, []),                # both types is no restriction
    ("brooklyn bronx queens manhattan staten island", {}, []),    # all five is no restriction
    # words the parser does not know are reported and set no filter
    ("pizza in brooklyn", dict(boroughs=["Brooklyn"]), ["pizza"]),
    ("night shift nurses", dict(hours=["Night"]), ["shift", "nurses"]),
    ("asdf qwerty", {}, ["asdf", "qwerty"]),
    ("weekend", {}, ["weekend"]),
    ("rush hour", {}, ["rush", "hour"]),
    ("trucks", {}, ["trucks"]),
    ("2015", {}, ["2015: the data covers 2016 to 2025"]),         # outside the data, not clamped
    ("1999-2005", {}, ["1999-2005: the data covers 2016 to 2025"]),
    ("last 3 years", {}, ["last", "3"]),
    ("", {}, []),
    ("   ", {}, []),
]


@pytest.mark.parametrize("query, expected, unmatched", SEARCH_CASES)
def test_search_query(query, expected, unmatched):
    parsed = parse_query(query)
    assert parsed.filters() == make_filters(**expected)
    assert parsed.unmatched == unmatched
    if not expected and unmatched:
        assert not parsed.understood
    assert parsed.is_empty == (not query.strip())
    labels = {label for _, label, _ in parsed.understood}        # a filter is set only with a chip that names it
    named = {"boroughs": "Borough", "year_from": "Years", "year_to": "Years", "construction": "Construction",
             "sizes": "Building size", "factors": "Contributing factor", "hours": "Time of day",
             "harm": "Who was harmed", "scope": "Crash location"}
    assert {named[key] for key in expected} <= labels


@pytest.mark.parametrize("query, by_hand", [
    ("Brooklyn 2022 new construction", dict(boroughs=["Brooklyn"], year_from=2022, year_to=2022,
                                            construction=["New Construction"], scope="near")),
    ("bronx pedestrians night 2019-2021", dict(boroughs=["Bronx"], year_from=2019, year_to=2021, hours=["Night"],
                                               harm="ped")),
    ("si deaths", dict(boroughs=["Staten Island"], harm="fatal")),
])
def test_search_gives_the_same_report_as_the_dropdowns(store, query, by_hand):
    from_search = callbacks.filters_from_controls(callbacks.control_values(parse_query(query).filters()))
    from_controls = make_filters(**by_hand)
    assert from_search == from_controls

    def as_json(filters):
        return json.dumps(callbacks.report_outputs(store, filters, None), cls=PlotlyJSONEncoder, sort_keys=True)

    assert as_json(from_search) == as_json(from_controls)


# ---------------------------------------------------------------------------------------------
# 6. The assignment's list for the website
# ---------------------------------------------------------------------------------------------
def _walk(component):
    yield component
    children = getattr(component, "children", None)
    for child in (children if isinstance(children, (list, tuple)) else [children]):
        if child is not None and not isinstance(child, (str, int, float)):
            yield from _walk(child)


def test_assignment_requirements(store):
    from dash import dcc, html

    from app.app import app
    from app.ui.explorer_layout import build_layout

    page = build_layout(store)
    parts = list(_walk(page))
    dropdowns = [part for part in parts if isinstance(part, dcc.Dropdown)]
    assert len(dropdowns) >= 4 and {part.id for part in dropdowns} == set(callbacks.CONTROL_IDS)
    assert any(isinstance(part, dcc.Input) and part.id == "search" for part in parts)
    buttons = [part for part in parts if isinstance(part, html.Button) and part.id == "generate"]
    assert len(buttons) == 1 and _text(buttons[0]) == "Generate report"

    # one callback, fired by the button, writes every chart
    generate = [spec for spec in app.callback_map.values()
                if any(item["id"] == "generate" for item in spec["inputs"])]
    assert len(generate) == 1
    graph_ids = {part.id for part in parts if isinstance(part, dcc.Graph)}
    assert {f"fig-{key}" for key in report.CHART_KEYS} <= graph_ids
    output_text = next(key for key, spec in app.callback_map.items() if spec is generate[0])
    for key in report.CHART_KEYS:
        assert f"fig-{key}.figure" in output_text

    panels = report.build_report(store, make_filters())["panels"]
    kinds = {(trace.type, getattr(trace, "mode", None) if trace.type == "scatter" else None)
             for panel in panels.values() for trace in panel.figure.data}
    assert {"bar", "heatmap", "choroplethmap", "scattermap"} <= {kind for kind, _ in kinds}
    assert ("scatter", "markers") in kinds and ("scatter", "lines+markers") in kinds
    for key, panel in panels.items():                              # hover on every chart, zoom not locked
        assert all(trace.hovertemplate or trace.hoverinfo == "skip" for trace in panel.figure.data), key
        assert not panel.figure.layout.xaxis.fixedrange and not panel.figure.layout.dragmode == False  # noqa: E712
    # both domains in one picture: crash cells under housing sites, and units against crashes per ZIP
    assert {trace.type for trace in panels["map"].figure.data} == {"choroplethmap", "scattermap"}
    scatter = panels["scatter"].figure
    assert "units" in scatter.layout.xaxis.title.text.lower() and "crashes" in scatter.layout.yaxis.title.text.lower()

    sections = {part.id for part in parts if isinstance(part, html.Section) and getattr(part, "id", None)}
    assert {"explore", "findings", "limits", "impact", "data"} <= sections
    assert "?" in _text(story.hero(store))                         # the question

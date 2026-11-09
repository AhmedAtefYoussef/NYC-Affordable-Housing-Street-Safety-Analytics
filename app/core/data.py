"""Load the exported tables once and answer every question the report asks of them.

The files in app/data/ are written by `python -m pipeline data` from the notebook's own code.
Everything here is a pure function of (`Store`, `Filters`) that returns a small frame or dict
for one chart. The crash tables are pre-aggregated cubes held as numpy arrays, so a filter is
a few boolean masks and one `bincount`; nothing larger than 625,000 rows is ever scanned.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from app.core import filters as filter_model
from app.core import stats
from app.core.filters import Filters

DATA_DIR = Path(__file__).resolve().parents[1] / "data"      # app/data/
REL_YEARS = [-3, -2, -1, 0, 1, 2, 3]        # replaced by meta.constants.event_window when load() runs
PRE_YEARS, POST_YEARS = [-3, -2, -1], [1, 2, 3]
MIN_GROUP_N = 30               # the notebook's rule: no statistic for a group smaller than this
MONTHLY_UP_TO_YEARS = 2        # the trend chart shows months when the selection is this short
PERCENTILE_BIN_WIDTH = 10
NEW_CONSTRUCTION, PRESERVATION = "New Construction", "Preservation"
# The event study counts three outcomes around each site; the other harm options map to the closest one.
EVENT_OUTCOME_FOR_HARM = {"injury": "injury", "pedcyc": "pedcyc", "ped": "pedcyc", "cyc": "pedcyc",
                          "mot": "injury", "fatal": "injury", "all": "all"}
EVENT_OUTCOME_NOUN = {"injury": "injury crashes", "pedcyc": "pedestrian and cyclist crashes",
                      "all": "reported crashes"}


# The columns and kinds each exported table must have. "uint" and "int" are the integer families (the
# build picks the narrowest width, so the width may change); the event table's yearly columns follow
# the event window and are added by `expected_schema`.
_COUNTS = {name: "uint" for name in ["n_all", "n_injury", "n_pedcyc", "n_ped", "n_cyc", "n_mot", "n_fatal"]}
EXPECTED_SCHEMA = {
    "crash_cube": {"year": "uint", "month": "uint", "borough": "category", "factor": "category",
                   "hour_band": "category", "near": "category", **_COUNTS},
    "hour_cube": {"year": "uint", "borough": "category", "factor": "category", "weekday": "uint",
                  "hour": "uint", "near": "category", **_COUNTS},
    "zip_cube": {"zip": "category", "year": "uint", "factor": "category", "hour_band": "category",
                 "near": "category", **_COUNTS},
    "map_grid": {"cell": "uint", "year": "uint", "borough": "category", "factor": "category",
                 "hour_band": "category", "near": "category", **_COUNTS},
    "housing_cube": {"borough": "category", "zip": "category", "year": "uint", "construction_type": "category",
                     "size_band": "category", "is_located": "bool", "buildings": "uint", "total_units": "uint",
                     "affordable_units": "uint", "deep_affordable_units": "uint"},
    "zip_year": {"zip": "category", "year": "int", "borough": "category", "buildings_completed": "uint",
                 "units_completed": "uint", "affordable_units_completed": "uint", "deep_affordable_units": "uint",
                 "new_construction_units": "uint", "preservation_units": "uint", "cum_affordable_units": "uint",
                 "cum_deep_affordable_units": "uint", "crashes": "uint", "injury_crashes": "uint",
                 "persons_injured": "uint", "persons_killed": "uint", "ped_cyc_crashes": "uint",
                 "crashes_zip_imputed": "uint", "injury_crashes_zip_imputed": "uint"},
    "sites": {"site_id": "int", "cluster_id": "int", "project_name": "object", "borough": "category",
              "zip": "category", "lat": "float", "lon": "float", "start_year": "int", "completion_year": "float",
              "construction_type": "category", "size_band": "category", "total_units": "int",
              "affordable_units": "int", "baseline_crashes": "float", "borough_percentile": "float"},
    "event_sites": {"site_id": "int", "cohort": "int", "cluster_id": "int", "borough": "category",
                    "construction_type": "category", "size_band": "category", "total_units": "int",
                    "treated": "bool"},
    "city_year": {"year": "int", "crashes": "int", "injury_crashes": "int", "persons_injured": "int",
                  "persons_killed": "int", "ped_cyc_crashes": "int", "injury_share": "float",
                  "deaths_per_1000_injury_crashes": "float", "crash_index": "float", "injury_crash_index": "float"},
    "robustness": {"check": "object", "variant": "object", "kind": "object", "keeps_screen": "bool",
                   "n_treated": "int", "n_comparison": "int", "n_comparison_sites": "int",
                   "n_treated_dropped": "int", "n_comparison_dropped": "int", "n_resampled_units": "int",
                   "n_treated_clusters": "int", "n_strata": "int", "treated_change": "float",
                   "comparison_change": "float", "estimate": "float", "low": "float", "high": "float",
                   "p_value": "float", "percent_change": "float", "percent_low": "float",
                   "percent_high": "float", "interval_excludes_zero": "bool"},
    "cleaning_log": {"dataset": "object", "rule": "object", "action": "object", "rows_before": "int",
                     "rows_after": "int", "affected": "int", "reason": "object"},
}
EVENT_OUTCOME_PREFIXES = ["injury", "all", "pedcyc"]


class DataContractError(ValueError):
    """The files in app/data/ do not match what this code reads. Rebuild with: python -m pipeline data."""


def dtype_kind(dtype) -> str:
    """The family of a pandas dtype: category, uint, int, float, bool or object."""
    if isinstance(dtype, pd.CategoricalDtype):
        return "category"
    if pd.api.types.is_bool_dtype(dtype):
        return "bool"
    if pd.api.types.is_unsigned_integer_dtype(dtype):
        return "uint"
    if pd.api.types.is_integer_dtype(dtype):
        return "int"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    return "object"


def expected_schema(name: str, event_window: int) -> dict[str, str]:
    """Expected columns of one table; the event table's yearly columns follow the event window."""
    columns = dict(EXPECTED_SCHEMA[name])
    if name == "event_sites":
        for prefix in EVENT_OUTCOME_PREFIXES:
            for rel_year in range(-event_window, event_window + 1):
                columns[f"{prefix}_{rel_year:+d}"] = "uint"
    return columns


def check_table(name: str, frame: pd.DataFrame, event_window: int, recorded: dict | None) -> None:
    """Raise DataContractError naming the table and column when a table is not what the code reads."""
    fix = "rebuild with: python -m pipeline data"
    expected = expected_schema(name, event_window)
    for column, kind in expected.items():
        if column not in frame.columns:
            raise DataContractError(f"table '{name}' has no column '{column}'; {fix}")
        actual = dtype_kind(frame[column].dtype)
        if actual != kind:
            raise DataContractError(f"table '{name}', column '{column}' is {frame[column].dtype} ({actual}), "
                                    f"expected {kind}; {fix}")
    extra = [column for column in frame.columns if column not in expected]
    if extra:
        raise DataContractError(f"table '{name}' has unexpected column '{extra[0]}'; {fix}")
    if recorded is not None:
        for column, dtype in recorded.items():
            if column in frame.columns and str(frame[column].dtype) != dtype:
                raise DataContractError(f"table '{name}', column '{column}' is {frame[column].dtype} but "
                                        f"meta.json recorded {dtype}; the files and meta.json are from different builds")


# The exported tables carry the notebook's spelling of one factor label; the site shows US spelling.
US_SPELLING = {"Improper manoeuvre": "Improper maneuver"}


@dataclass(eq=False)
class Cube:
    """A pre-aggregated crash table: integer codes per dimension and one array per count."""

    codes: dict[str, np.ndarray]
    labels: dict[str, list]
    counts: dict[str, np.ndarray]
    n_rows: int

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> "Cube":
        codes, labels, counts = {}, {}, {}
        for name in frame.columns:
            column = frame[name]
            if name.startswith("n_"):
                counts[name] = column.to_numpy()        # stays uint8 or uint16; sums widen on their own
            elif isinstance(column.dtype, pd.CategoricalDtype):
                codes[name] = column.cat.codes.to_numpy()
                labels[name] = [US_SPELLING.get(label, label) for label in column.cat.categories]
            else:
                codes[name] = column.to_numpy()
        return cls(codes, labels, counts, len(frame))

    def allowed(self, name: str, chosen) -> np.ndarray:
        """Row mask for a categorical dimension restricted to the chosen labels."""
        lookup = np.isin(np.array(self.labels[name], dtype=object), list(chosen))
        return lookup[self.codes[name]]

    def total(self, column: str, mask: np.ndarray) -> int:
        return int(self.counts[column][mask].sum(dtype=np.int64))

    def by(self, name: str, column: str, mask: np.ndarray, size: int | None = None) -> np.ndarray:
        """Sum of one count per code of one dimension."""
        size = size if size is not None else len(self.labels[name])
        return np.bincount(self.codes[name][mask], weights=self.counts[column][mask], minlength=size)


@dataclass(eq=False)
class Store:
    """Everything the site reads, loaded once per process."""

    meta: dict
    results: dict
    crash: Cube
    hour: Cube
    zips: Cube
    grid: Cube
    housing: pd.DataFrame
    sites: pd.DataFrame
    event_sites: pd.DataFrame
    zip_year: pd.DataFrame
    city_year: pd.DataFrame
    robustness: pd.DataFrame
    cleaning_log: pd.DataFrame
    zip_borough: pd.Series = field(default=None)
    hour_to_band: np.ndarray = field(default=None)


@lru_cache(maxsize=1)
def load(data_dir: Path = DATA_DIR) -> Store:
    """Read every exported file and check it against the schema the code expects.

    Raises FileNotFoundError with the fix if the data was never built, and DataContractError
    (naming the table and column) if a table has a missing, unexpected or wrongly typed column.
    """
    global REL_YEARS
    if not (data_dir / "meta.json").exists():
        raise FileNotFoundError(f"{data_dir} has no data. Run: python -m pipeline data")

    meta = json.loads((data_dir / "meta.json").read_text(encoding="utf-8"))
    constants = meta["constants"]
    if (constants["year_start"], constants["year_end"]) != (filter_model.YEAR_START, filter_model.YEAR_END):
        raise ValueError(f"app/data covers {constants['year_start']} to {constants['year_end']} but the "
                         "filters are built for another window; rebuild the data or update app/core/filters.py")
    window = int(constants["event_window"])
    recorded = meta.get("schema", {})

    def table(name: str) -> pd.DataFrame:
        # fastparquet, not pyarrow: pyarrow alone is about 170 MB installed and pushed the deployed function past
        # Vercel's 500 MB limit for Python. Every table reads identically with both (checked column by column).
        frame = pd.read_parquet(data_dir / f"{name}.parquet", engine="fastparquet")
        check_table(name, frame, window, recorded.get(name))
        return frame

    REL_YEARS = list(range(-window, window + 1))
    filter_model.configure(constants)
    store = Store(
        meta=meta, results=json.loads((data_dir / "results.json").read_text(encoding="utf-8")),
        crash=Cube.from_frame(table("crash_cube")), hour=Cube.from_frame(table("hour_cube")),
        zips=Cube.from_frame(table("zip_cube")), grid=Cube.from_frame(table("map_grid")),
        housing=table("housing_cube"), sites=table("sites"), event_sites=table("event_sites"),
        zip_year=table("zip_year"), city_year=table("city_year"), robustness=table("robustness"),
        cleaning_log=table("cleaning_log"),
    )
    store.zip_borough = (store.zip_year.drop_duplicates("zip").set_index("zip")["borough"].astype(str))
    store.zip_borough.index = store.zip_borough.index.astype(str)
    bands = meta["dimensions"]["hour_bands"]
    store.hour_to_band = np.zeros(24, dtype=np.int64)
    for name, (first, last) in meta["dimensions"]["hour_band_ranges"].items():
        store.hour_to_band[first:last + 1] = bands.index(name)
    return store


# ---------------------------------------------------------------------------------------------
# Masks
# ---------------------------------------------------------------------------------------------
def matching_near_kinds(store: Store, filters: Filters) -> list[str]:
    """Nearest-site kinds ('type | size') that satisfy the housing filters."""
    kinds = store.meta["dimensions"]["near_kinds"][1:]          # position 0 is "not near a site"
    types = set(filters.construction) or {kind.split(" | ")[0] for kind in kinds}
    sizes = set(filters.sizes) or {kind.split(" | ")[1] for kind in kinds}
    return [kind for kind in kinds if kind.split(" | ")[0] in types and kind.split(" | ")[1] in sizes]


def crash_mask(store: Store, cube: Cube, filters: Filters, apply_scope: bool = True) -> np.ndarray:
    """Rows of a crash cube that pass the borough, year, factor, time-of-day and location filters."""
    year = cube.codes["year"]
    mask = (year >= filters.year_from) & (year <= filters.year_to)
    if filters.boroughs and "borough" in cube.codes:
        mask &= cube.allowed("borough", filters.boroughs)
    if filters.factors:
        mask &= cube.allowed("factor", filters.factors)
    if filters.hours:
        if "hour_band" in cube.codes:
            mask &= cube.allowed("hour_band", filters.hours)
        else:                                            # the hour cube stores the clock hour
            bands = store.meta["dimensions"]["hour_bands"]
            wanted = np.isin(store.hour_to_band, [bands.index(name) for name in filters.hours])
            mask &= wanted[cube.codes["hour"]]
    if apply_scope and filters.scope == "near":
        mask &= cube.allowed("near", matching_near_kinds(store, filters))
    return mask


def zip_mask(store: Store, filters: Filters) -> np.ndarray:
    """`crash_mask` for the ZIP cube, where the borough is a property of the ZIP."""
    mask = crash_mask(store, store.zips, filters)
    if filters.boroughs:
        zip_labels = pd.Index(store.zips.labels["zip"])
        in_borough = store.zip_borough.reindex(zip_labels).isin(filters.boroughs).to_numpy()
        mask &= in_borough[store.zips.codes["zip"]]
    return mask


def housing_rows(store: Store, filters: Filters) -> pd.DataFrame:
    """Rows of the housing cube that pass the borough, completion-year, type and size filters."""
    rows = store.housing
    keep = rows["year"].between(filters.year_from, filters.year_to)
    if filters.boroughs:
        keep &= rows["borough"].isin(filters.boroughs)
    if filters.construction:
        keep &= rows["construction_type"].isin(filters.construction)
    if filters.sizes:
        keep &= rows["size_band"].isin(filters.sizes)
    return rows[keep]


# ---------------------------------------------------------------------------------------------
# One function per part of the report
# ---------------------------------------------------------------------------------------------
def headline_numbers(store: Store, filters: Filters) -> dict:
    """The numbers of the summary strip."""
    column = filters.harm_column
    mask = crash_mask(store, store.crash, filters)
    anywhere = crash_mask(store, store.crash, filters, apply_scope=False)
    near = anywhere & store.crash.allowed("near", matching_near_kinds(store, filters))
    homes = housing_rows(store, filters)
    unknown = 0
    if not filters.boroughs:
        unknown = store.crash.total(column, mask & store.crash.allowed(
            "borough", [store.meta["dimensions"]["unknown_borough"]]))
    return {
        "crashes": store.crash.total(column, mask),
        "crashes_anywhere": store.crash.total(column, anywhere),
        "crashes_near": store.crash.total(column, near),
        "crashes_unknown_borough": unknown,
        "buildings": int(homes["buildings"].sum()),
        "buildings_unlocated": int(homes.loc[~homes["is_located"], "buildings"].sum()),
        "affordable_units": int(homes["affordable_units"].sum()),
        "total_units": int(homes["total_units"].sum()),
    }


def crash_trend(store: Store, filters: Filters) -> pd.DataFrame:
    """Selected crashes per period and borough. Index: year, or month start for short selections."""
    cube, column = store.crash, filters.harm_column
    mask = crash_mask(store, cube, filters)
    boroughs = cube.labels["borough"]
    monthly = filters.n_years <= MONTHLY_UP_TO_YEARS
    period = (cube.codes["year"].astype(np.int64) - filters.year_from) * (12 if monthly else 1)
    if monthly:
        period = period + cube.codes["month"] - 1
    n_periods = filters.n_years * (12 if monthly else 1)
    combined = period[mask] * len(boroughs) + cube.codes["borough"][mask]
    table = np.bincount(combined, weights=cube.counts[column][mask],
                        minlength=n_periods * len(boroughs)).reshape(n_periods, len(boroughs))
    if monthly:
        index = pd.date_range(f"{filters.year_from}-01-01", periods=n_periods, freq="MS")
    else:
        index = pd.Index(filters.years, name="year")
    frame = pd.DataFrame(table.astype(np.int64), index=index, columns=boroughs)
    shown = list(filters.boroughs) or store.meta["dimensions"]["boroughs"]
    frame = frame[shown]
    frame.attrs["monthly"] = monthly
    return frame


def factor_mix(store: Store, filters: Filters) -> pd.Series:
    """Selected crashes by contributing-factor group (all ten groups, in the notebook's order)."""
    mask = crash_mask(store, store.crash, filters)
    counts = store.crash.by("factor", filters.harm_column, mask)
    return pd.Series(counts.astype(np.int64), index=store.crash.labels["factor"], name="crashes")


def weekday_hour(store: Store, filters: Filters) -> np.ndarray:
    """Selected crashes in a (7 weekdays, 24 hours) array; row 0 is Monday."""
    cube = store.hour
    mask = crash_mask(store, cube, filters)
    combined = cube.codes["weekday"][mask].astype(np.int64) * 24 + cube.codes["hour"][mask]
    return np.bincount(combined, weights=cube.counts[filters.harm_column][mask], minlength=7 * 24) \
        .reshape(7, 24).astype(np.int64)


def completions_by_year(store: Store, filters: Filters) -> dict[str, pd.DataFrame]:
    """Affordable units and buildings completed: two (years x construction types) tables."""
    homes = housing_rows(store, filters)
    types = list(filters.construction) or store.meta["dimensions"]["construction_types"]
    tables = {}
    for measure in ["affordable_units", "buildings"]:
        wide = homes.pivot_table(index="year", columns="construction_type", values=measure,
                                 aggfunc="sum", observed=False, fill_value=0)
        tables[measure] = wide.reindex(index=filters.years, columns=types, fill_value=0).astype(np.int64)
    return tables


def map_cells(store: Store, filters: Filters) -> pd.DataFrame:
    """Selected crashes per 500 m grid cell: cell id, centre and count (cells with none left out)."""
    cube, grid = store.grid, store.meta["grid"]
    mask = crash_mask(store, cube, filters)
    counts = cube.by("cell", filters.harm_column, mask, size=grid["n_rows"] * grid["n_columns"])
    cells = np.flatnonzero(counts)
    rows, columns = np.divmod(cells, grid["n_columns"])
    return pd.DataFrame({
        "cell": cells, "crashes": counts[cells].astype(np.int64),
        "lat": grid["lat_min"] + (rows + 0.5) * grid["lat_step"],
        "lon": grid["lon_min"] + (columns + 0.5) * grid["lon_step"],
    })


def map_sites(store: Store, filters: Filters) -> pd.DataFrame:
    """Located housing sites completed in the selected years that pass the housing filters."""
    sites = store.sites
    keep = sites["completion_year"].between(filters.year_from, filters.year_to)
    if filters.boroughs:
        keep &= sites["borough"].isin(filters.boroughs)
    if filters.construction:
        keep &= sites["construction_type"].isin(filters.construction)
    if filters.sizes:
        keep &= sites["size_band"].isin(filters.sizes)
    return sites[keep]


@lru_cache(maxsize=1)
def grid_geojson(store: Store) -> dict:
    """Every grid cell that holds a crash, as GeoJSON squares keyed by cell id (built once)."""
    grid = store.meta["grid"]
    features = []
    for cell in np.unique(store.grid.codes["cell"]).tolist():
        row, column = divmod(cell, grid["n_columns"])
        south = round(grid["lat_min"] + row * grid["lat_step"], 5)
        west = round(grid["lon_min"] + column * grid["lon_step"], 5)
        north, east = round(south + grid["lat_step"], 5), round(west + grid["lon_step"], 5)
        ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
        features.append({"type": "Feature", "id": cell, "properties": {},
                         "geometry": {"type": "Polygon", "coordinates": [ring]}})
    return {"type": "FeatureCollection", "features": features}


def zip_relation(store: Store, filters: Filters) -> dict:
    """Per ZIP: affordable units completed (housing filters) against selected crashes per year.

    Returns {"table": frame, "rho": Spearman correlation or None, "n_without_units": int}.
    The table holds the ZIPs with at least one matching completed unit, because the horizontal
    axis is logarithmic; the other ZIPs are counted in `n_without_units`.
    """
    mask = zip_mask(store, filters)
    crashes = store.zips.by("zip", filters.harm_column, mask)
    table = pd.DataFrame({"zip": store.zips.labels["zip"], "crashes": crashes.astype(np.int64)})
    table["borough"] = store.zip_borough.reindex(table["zip"]).to_numpy()
    if filters.boroughs:
        table = table[table["borough"].isin(filters.boroughs)]
    homes = housing_rows(store, filters)
    units = homes.groupby(homes["zip"].astype(str))[["affordable_units", "buildings"]].sum()
    table = table.join(units, on="zip").fillna({"affordable_units": 0, "buildings": 0})
    table["crashes_per_year"] = table["crashes"] / filters.n_years
    with_units = table[table["affordable_units"] > 0].reset_index(drop=True)
    rho = None
    if len(with_units) >= MIN_GROUP_N:
        value = stats.spearman_rho(with_units["affordable_units"], with_units["crashes_per_year"])
        rho = None if np.isnan(value) else value
    return {"table": with_units, "rho": rho, "n_without_units": int(len(table) - len(with_units))}


def event_outcome(filters: Filters) -> str:
    """Which of the three event-study outcomes stands in for the selected harm option."""
    return EVENT_OUTCOME_FOR_HARM[filters.harm]


def event_cohort_text(store: Store) -> str:
    """'2019 to 2022': the completion years of the event-study sites."""
    cohorts = store.event_sites.loc[store.event_sites["treated"], "cohort"]
    return f"{int(cohorts.min())} to {int(cohorts.max())}"


def event_study(store: Store, filters: Filters) -> dict:
    """Crashes within the buffer of sites by year relative to completion, completed against not-yet-completed.

    Uses the borough, construction-type, size and who-was-harmed filters. Cached, because each
    call runs up to four bootstraps. `n_comparison` counts rows (a comparison site has one per cohort it
    serves) and `n_comparison_sites` counts sites; a group needs MIN_GROUP_N unique sites to be estimated.
    """
    return _event_study(store, filters.boroughs, filters.construction, filters.sizes, event_outcome(filters))


@lru_cache(maxsize=128)
def _event_study(store: Store, boroughs: tuple, construction: tuple, sizes: tuple, outcome: str) -> dict:
    table = store.event_sites
    keep = pd.Series(True, index=table.index)
    if boroughs:
        keep &= table["borough"].isin(boroughs)
    # Type and size describe the completed building, so they select treated sites only. The
    # comparison group stays every clean not-yet-completed site, as in the notebook.
    wanted_types = list(construction) or [NEW_CONSTRUCTION, PRESERVATION]
    treated_keep = table["construction_type"].isin(wanted_types)
    if sizes:
        treated_keep &= table["size_band"].isin(sizes)
    sample = table[keep & (~table["treated"] | treated_keep)]

    treated = sample["treated"].to_numpy()
    kind = sample["construction_type"].astype(str).to_numpy()
    counts = sample[[f"{outcome}_{rel_year:+d}" for rel_year in REL_YEARS]].to_numpy(dtype=float)
    before = counts[:, :len(PRE_YEARS)].sum(axis=1)
    after = counts[:, -len(POST_YEARS):].sum(axis=1)
    cohorts, clusters = sample["cohort"].to_numpy(), sample["cluster_id"].to_numpy()
    site_ids = sample["site_id"].to_numpy()
    n_by_type = {name: int((treated & (kind == name)).sum()) for name in wanted_types}

    def rows_for(name):
        return ~treated | (kind == name)

    # Counted on what each estimate uses: a cohort with sites on one side only is left out of it.
    sizes = {name: stats.used_sizes(site_ids[rows_for(name)], treated[rows_for(name)], cohorts[rows_for(name)],
                                    clusters[rows_for(name)]) for name in wanted_types}
    result = {"outcome": outcome, "noun": EVENT_OUTCOME_NOUN[outcome], "rel_years": REL_YEARS,
              "n_by_type": n_by_type, "n_comparison": int((~treated).sum()),
              "n_comparison_sites": int(pd.unique(site_ids[~treated]).size),
              "n_clusters": int(pd.unique(clusters).size),
              "n_treated_clusters": int(pd.unique(clusters[treated]).size),
              "treated": {}, "difference": None}

    usable = [name for name in wanted_types
              if min(sizes[name]["n_treated_sites"], sizes[name]["n_comparison_sites"]) >= MIN_GROUP_N]
    if not usable:
        result["empty"] = True
        return result

    if len(usable) == 2:
        # Both types against the shared comparison sites in one joint bootstrap (the notebook's RQ5).
        arm = np.where(~treated, 0, np.where(kind == NEW_CONSTRUCTION, 1, 2))
        contrast = stats.type_contrast(before, after, arm, cohorts, clusters)
        estimates = {NEW_CONSTRUCTION: contrast["first"], PRESERVATION: contrast["second"]}
        result["difference"] = contrast["difference"]
    else:
        rows = rows_for(usable[0])
        estimates = {usable[0]: stats.did_log_ratio(before[rows], after[rows], treated[rows],
                                                    cohorts[rows], clusters[rows])}
    for name in usable:
        rows = rows_for(name)
        profile = stats.event_profile(counts[rows], treated[rows], cohorts[rows], clusters[rows], len(PRE_YEARS),
                                      site_ids=site_ids[rows])
        result["treated"][name] = {"profile": profile["treated"], "did": estimates[name]}
        if len(usable) == 1:
            result["comparison"] = profile["comparison"]
    if len(usable) == 2:
        # One comparison line for the chart, weighted by the cohort mix of all treated sites shown.
        pooled = stats.event_profile(counts, treated, cohorts, clusters, len(PRE_YEARS), site_ids=site_ids)
        result["comparison"] = pooled["comparison"]
    return result


def site_selection(store: Store, filters: Filters) -> dict:
    """Where sites stood before construction: their percentile among streets of the same borough (RQ7).

    Uses the borough, construction-type and size filters. Sites are the ones started after the
    baseline (see meta.json); the year filter does not apply. The bootstrap resamples site clusters
    (`cluster_id`, sites linked within the buffer), as the notebook does. `one_vote` repeats the mean
    with each cluster counted once; it is NaN below MIN_GROUP_N clusters.
    """
    return _site_selection(store, filters.boroughs, filters.construction, filters.sizes)


@lru_cache(maxsize=128)
def _site_selection(store: Store, boroughs: tuple, construction: tuple, sizes: tuple) -> dict:
    sites = store.sites[store.sites["borough_percentile"].notna()]
    keep = pd.Series(True, index=sites.index)
    if boroughs:
        keep &= sites["borough"].isin(boroughs)
    if construction:
        keep &= sites["construction_type"].isin(construction)
    if sizes:
        keep &= sites["size_band"].isin(sizes)
    sites = sites[keep]
    result = {"n": int(len(sites))}
    if len(sites) < MIN_GROUP_N:
        result["empty"] = True
        return result
    percentiles = sites["borough_percentile"].to_numpy(dtype=float)
    boot = stats.bootstrap_ci(stats.mean_percentile_excess, percentiles, clusters=sites["cluster_id"].to_numpy())
    one_vote = stats.one_vote_per_cluster(percentiles, sites["cluster_id"].to_numpy(), min_clusters=MIN_GROUP_N)
    n_bins = 100 // PERCENTILE_BIN_WIDTH
    bins = np.clip((percentiles // PERCENTILE_BIN_WIDTH).astype(int), 0, n_bins - 1)
    result.update({
        "excess": boot["estimate"], "low": boot["low"], "high": boot["high"],
        "mean_percentile": stats.NEUTRAL_PERCENTILE + boot["estimate"],
        "share_above_median": float((percentiles > stats.NEUTRAL_PERCENTILE).mean() * 100),
        "one_vote": one_vote,
        "n_blocks": boot["n_clusters"],
        "cluster_unit": "site clusters (sites within the buffer of each other)",
        "bin_share": np.bincount(bins, minlength=n_bins) / len(percentiles) * 100,
        "bin_width": PERCENTILE_BIN_WIDTH,
        "median_baseline_crashes": float(np.median(sites["baseline_crashes"])),
    })
    return result


"""Build the website's data files from the notebook's own code, so both show the same numbers.

The build executes the notebook section sources in pipeline/notebook/sections/ (every file except
the EDA section, in order, in one namespace, inside notebooks/ where the two raw files live) and
then exports small pre-aggregated tables to app/data/. The website reads only those files: it
never imports the notebook or the raw data, and downloads nothing.

    python -m pipeline data            # about 90 seconds, needs about 3 GB of free memory

Stages, one module each:  runner (execute the sections) -> tables (crash, housing, site tables)
-> results (results.json) -> provenance (meta.json) -> export (this module: atomic write and checks).

Exports (parquet with categorical and small-integer columns, plus two JSON files):
    crash_cube      year x month x borough x factor group x hour band x nearest-site kind
    hour_cube       year x borough x factor group x weekday x hour x nearest-site kind
    zip_cube        ZIP x year x factor group x hour band x nearest-site kind   (panel ZIPs only)
    map_grid        500 m cell x year x borough x factor group x hour band x nearest-site kind
    housing_cube    borough x ZIP x completion year x construction type x size band
    zip_year        the notebook's ZIP x year panel
    sites           located housing sites, with their pre-construction crash percentile (RQ7)
    event_sites     one row per clean site and cohort, yearly counts by relative year (RQ3, RQ5)
    city_year       citywide yearly totals and the 2019 = 100 indices
    robustness      every specification of the notebook's Section 9 (central, checks, comparison cuts, placebos)
    cleaning_log    every cleaning rule with the rows it touched
    results.json    the ten research-question results with their sentences, and the story facts
    meta.json       row counts, data-as-of dates, constants, build time, file sizes

Every crash table carries the same seven counts, one per "who was harmed" option.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.build.checks import (BYTES_PER_MB, GRID_LAT_STEP, GRID_LON_STEP, MAX_TOTAL_MB, OUTPUT_FILES,
                                   OUTPUT_TABLES, DataCheckError, require)
from pipeline.build.frames import smallest_unsigned, write_table
from pipeline.build.provenance import meta_document
from pipeline.build.results import results_document
from pipeline.build.runner import run_notebook_sections
from pipeline.build.tables import (aggregate, crash_facts, event_site_table, housing_cube, near_kind_labels,
                                   site_table)
from pipeline.paths import APP_DATA_DIR as OUTPUT_DIR
from pipeline.paths import ROOT


def check_output_folder(out_dir: Path) -> None:
    """Refuse an output folder that holds anything the build did not write (for example `--out .`)."""
    if out_dir.exists() and not out_dir.is_dir():
        raise DataCheckError(f"{out_dir} is a file, not a folder")
    if out_dir.exists():
        foreign = sorted(path.name for path in out_dir.iterdir() if path.name not in OUTPUT_FILES)
        if foreign:
            raise DataCheckError(f"{out_dir} holds files the build did not write ({', '.join(foreign[:5])}); "
                                 "refusing to replace it. Choose an empty or build-only folder with --out")


def export(ns: dict, out_dir: Path, seconds: float, skip_check: bool = False) -> None:
    """Write every file the website reads, atomically.

    Everything is written to a temporary folder beside `out_dir`, the conservation, budget and
    website checks run there, and only then does the folder replace `out_dir`. A failed check
    leaves the old output untouched and removes the temporary folder.
    """
    out_dir = out_dir.resolve()
    check_output_folder(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    previous = None
    if (out_dir / "meta.json").exists():
        previous = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    staging = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}-build-", dir=out_dir.parent))
    try:
        write_all(ns, staging, seconds, previous)
        if not skip_check:
            check_against_notebook(ns, staging)
        swap_in(staging, out_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def swap_in(staging: Path, out_dir: Path) -> None:
    """Replace `out_dir` with the finished `staging` folder; restore the old folder if that fails."""
    backup = out_dir.with_name(f".{out_dir.name}-old-{os.getpid()}")
    if out_dir.exists():
        out_dir.rename(backup)
    try:
        staging.rename(out_dir)
    except OSError:
        if backup.exists():
            backup.rename(out_dir)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def write_all(ns: dict, out_dir: Path, seconds: float, previous: dict | None) -> None:
    """Write every table, results.json and meta.json into `out_dir`, checking each against the notebook."""
    crashes, housing, sites = ns["crashes"], ns["housing"], ns["sites"]
    bounds = ns["NYC_BOUNDS"]
    schema: dict = {}
    grid = {"lat_min": bounds["lat"][0], "lon_min": bounds["lon"][0],
            "lat_step": GRID_LAT_STEP, "lon_step": GRID_LON_STEP,
            "n_rows": int(np.ceil((bounds["lat"][1] - bounds["lat"][0]) / GRID_LAT_STEP)) + 1,
            "n_columns": int(np.ceil((bounds["lon"][1] - bounds["lon"][0]) / GRID_LON_STEP)) + 1}
    construction_types = list(housing["construction_type"].cat.categories)
    near_labels = near_kind_labels(construction_types, ns["SIZE_BAND_LABELS"])

    facts = crash_facts(crashes, sites, ns["BOROUGHS"], near_labels, grid)
    write_table(aggregate(facts, ["year", "month", "borough", "factor", "hour_band", "near"]), "crash_cube", out_dir, schema)
    write_table(aggregate(facts, ["year", "borough", "factor", "weekday", "hour", "near"]), "hour_cube", out_dir, schema)

    in_panel = facts[facts["in_zip_panel"]].copy()
    in_panel["zip"] = in_panel["zip"].astype(str).astype("category")
    zip_cube = aggregate(in_panel, ["zip", "year", "factor", "hour_band", "near"])
    write_table(zip_cube, "zip_cube", out_dir, schema)

    located = facts[facts["cell"] >= 0].copy()
    located["cell"] = located["cell"].astype("uint16")
    write_table(aggregate(located, ["cell", "year", "borough", "factor", "hour_band", "near"]), "map_grid", out_dir, schema)

    homes = housing_cube(housing, ns["STUDY_YEARS"], ns["is_repeat_building"](housing))
    write_table(homes, "housing_cube", out_dir, schema)

    zip_year = ns["zip_year"].copy()
    zip_year["zip"] = zip_year["zip"].astype(str).astype("category")
    for column in zip_year.columns.difference(["zip", "year", "borough"]):
        zip_year[column] = smallest_unsigned(zip_year[column])
    write_table(zip_year, "zip_year", out_dir, schema)

    write_table(site_table(sites, ns["rq7_sites"]), "sites", out_dir, schema)
    write_table(event_site_table(ns["event_panel"], ns["event_site_table"], ns["REL_YEARS"]), "event_sites", out_dir, schema)
    write_table(ns["city_year"], "city_year", out_dir, schema)
    write_table(ns["robustness_table"], "robustness", out_dir, schema)
    write_table(pd.DataFrame(ns["CLEANING_LOG"]), "cleaning_log", out_dir, schema)
    require(set(schema) == set(OUTPUT_TABLES), "the build wrote a different set of tables from OUTPUT_TABLES")

    # The cubes must reproduce the notebook's ZIP x year panel, cell for cell.
    panel = ns["zip_year"].set_index(["zip", "year"])
    from_cube = zip_cube.groupby(["zip", "year"], observed=True)[["n_all", "n_injury", "n_pedcyc"]].sum()
    from_cube.index = from_cube.index.set_levels(from_cube.index.levels[0].astype(str), level=0)
    aligned = from_cube.reindex(pd.MultiIndex.from_arrays(
        [panel.index.get_level_values(0).astype(str), panel.index.get_level_values(1)]), fill_value=0)
    require((aligned["n_all"].to_numpy() == panel["crashes"].to_numpy()).all(), "zip_cube crashes differ from the panel")
    require((aligned["n_injury"].to_numpy() == panel["injury_crashes"].to_numpy()).all(),
            "zip_cube injury crashes differ from the panel")
    require((aligned["n_pedcyc"].to_numpy() == panel["ped_cyc_crashes"].to_numpy()).all(),
            "zip_cube pedestrian and cyclist crashes differ from the panel")
    housing_by_zip = (homes[homes["zip"].isin(zip_year["zip"].cat.categories)]
                      .groupby(["zip", "year"], observed=True)["affordable_units"].sum())
    require(int(housing_by_zip.sum()) == int(ns["zip_year"]["affordable_units_completed"].sum()),
            "housing_cube affordable units differ from the panel")

    (out_dir / "results.json").write_text(json.dumps(results_document(ns), indent=1), encoding="utf-8")
    meta = meta_document(ns, grid, near_labels, out_dir, seconds, schema, previous)
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")

    total_mb = sum(path.stat().st_size for path in out_dir.glob("*")) / BYTES_PER_MB
    print(f"  total {total_mb:.2f} MB in {out_dir}")
    require(total_mb < MAX_TOTAL_MB, f"exports are {total_mb:.1f} MB, above the {MAX_TOTAL_MB} MB budget")


def check_against_notebook(ns: dict, data_dir: Path) -> None:
    """Recompute three headline numbers with the website's own code, reading `data_dir`, and compare with the notebook."""
    sys.path.insert(0, str(ROOT))
    from app import data as site_data
    from app.filters import make_filters

    site_data.load.cache_clear()
    try:
        store = site_data.load(data_dir)     # also checks every table against the schema the site expects
    finally:
        site_data.load.cache_clear()         # never leave a store that reads the staging folder in the cache
    new_only = make_filters(construction=[ns["NEW_CONSTRUCTION"]])
    study = site_data.event_study(store, new_only)
    notebook = ns["new_build_did"]
    for key in ["percent_change", "percent_low", "percent_high"]:
        require(abs(study["treated"][ns["NEW_CONSTRUCTION"]]["did"][key] - notebook[key]) < 1e-9,
                f"website RQ3 {key} differs from the notebook")
    # RQ7: the headline (new construction) and the pooled row, each with its cluster-bootstrap interval.
    estimates = ns["rq7_estimates"]
    for filters, row_name in [(new_only, ns["RQ7_NEW"]), (make_filters(), ns["RQ7_POOLED"])]:
        selection = site_data.site_selection(store, filters)
        for site_key, notebook_key in [("excess", "estimate"), ("low", "low"), ("high", "high")]:
            require(abs(selection[site_key] - estimates.loc[row_name, notebook_key]) < 1e-6,
                    f"website RQ7 {site_key} differs from the notebook ({row_name})")
        require(selection["n"] == int(estimates.loc[row_name, "n_sites"]), f"website RQ7 site count differs ({row_name})")
    one_vote = site_data.site_selection(store, new_only)["one_vote"]
    for site_key, notebook_key in [("estimate", "estimate"), ("low", "low"), ("high", "high")]:
        require(abs(one_vote[site_key] - estimates.loc[ns["RQ7_ONE_VOTE"], notebook_key]) < 1e-6,
                f"website RQ7 one-vote {site_key} differs from the notebook")
    require(study["n_comparison_sites"] == ns["new_build_sizes"]["n_comparison_sites"],
            "website comparison site count differs from the notebook")
    print("  website code reproduces the notebook's RQ3 and RQ7 estimates, intervals and site counts")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline data", description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR, help="output directory")
    parser.add_argument("--skip-check", action="store_true", help="do not re-run the website's statistics")
    args = parser.parse_args(argv)

    check_output_folder(args.out.resolve())       # fail before the 90 seconds of work, not after
    started = time.time()
    print("Running the notebook sections")
    namespace = run_notebook_sections()
    print("Exporting")
    try:
        export(namespace, args.out, time.time() - started, args.skip_check)
    except DataCheckError as error:
        print(f"BUILD FAILED, the output folder was not changed: {error}", file=sys.stderr)
        return 1
    print(f"Done in {time.time() - started:.0f}s")
    return 0

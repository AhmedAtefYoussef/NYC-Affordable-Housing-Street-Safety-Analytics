"""Stage 4 of the data build: meta.json, what the data was built from (hashes, versions, schema, constants)."""
from __future__ import annotations

import hashlib
import importlib
import platform
from datetime import datetime, timezone
from pathlib import Path

from pipeline.build.checks import EVENT_OUTCOMES, NOT_NEAR, PACKAGES, UNKNOWN_BOROUGH
from pipeline.build.frames import to_plain
from pipeline.paths import RAW_DIR as NOTEBOOK_DIR
from pipeline.paths import ROOT, SECTIONS_DIR, STATS_MODULE


def file_sha256(path: Path) -> str:
    """SHA-256 of one file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files(root: Path = ROOT) -> list[Path]:
    """The code that decides the numbers: the notebook sections and the statistics module."""
    folder = root / SECTIONS_DIR.relative_to(ROOT)
    sections = [path for path in folder.rglob("*") if path.is_file() and "__pycache__" not in path.parts
                and path.suffix != ".pyc"]
    return sorted(sections) + [root / STATS_MODULE.relative_to(ROOT)]


def source_hash(root: Path = ROOT) -> str:
    """One SHA-256 over the names and contents of `source_files`. Line endings are ignored so a
    Windows checkout and a Linux checkout of the same commit give the same hash."""
    digest = hashlib.sha256()
    for path in source_files(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + bytes([0]))
        digest.update(path.read_bytes().replace(bytes([13, 10]), bytes([10])) + bytes([0]))
    return digest.hexdigest()


def package_versions() -> dict[str, str]:
    """Versions of the libraries that shape the numbers, read from the modules this process imports (installed
    package records can disagree with them when two copies are installed)."""
    versions = {}
    for name in PACKAGES:
        try:
            versions[name.lower()] = importlib.import_module(name).__version__
        except ImportError:
            continue
    versions["python"] = platform.python_version()
    return versions


def meta_document(ns: dict, grid: dict, near_labels: list[str], out_dir: Path, seconds: float,
                  schema: dict, previous: dict | None) -> dict:
    """Row counts, dates, constants, the category orders the website relies on, and what it was built from.

    The data date is read from the crash and housing content. `raw_files_saved` is carried over from
    the previous meta.json while the raw file's hash is unchanged (or was never recorded); a file's
    modification date is never read, because a fresh clone resets it.
    """
    crashes, housing = ns["crashes"], ns["housing"]
    latest_crash = crashes["crash_date"].max().strftime("%Y-%m-%d")
    raw_sha256 = {path.name: file_sha256(NOTEBOOK_DIR / path) for path in [ns["HOUSING_FILE"], ns["CRASH_FILE"]]}
    before = previous or {}
    saved_before = before.get("data_as_of", {}).get("raw_files_saved", {})
    hashes_before = before.get("raw_sha256")
    raw_files_saved = {name: saved_before[name] if name in saved_before
                       and (hashes_before is None or hashes_before.get(name) == digest) else latest_crash
                       for name, digest in raw_sha256.items()}
    files = {path.name: path.stat().st_size for path in sorted(out_dir.glob("*")) if path.name != "meta.json"}
    return to_plain({
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "build_seconds": round(seconds),
        "datasets": {
            "housing": {"id": ns["HOUSING_ID"], "name": "Affordable Housing Production by Building",
                        "url": ns["DATASET_PAGE"].format(ns["HOUSING_ID"])},
            "crashes": {"id": ns["CRASH_ID"], "name": "Motor Vehicle Collisions - Crashes",
                        "url": ns["DATASET_PAGE"].format(ns["CRASH_ID"])},
        },
        "data_as_of": {
            "raw_files_saved": raw_files_saved,
            "latest_crash": latest_crash,
            "earliest_crash": crashes["crash_date"].min().strftime("%Y-%m-%d"),
            "latest_housing_completion": housing["completion_date"].max().strftime("%Y-%m-%d"),
        },
        "raw_sha256": raw_sha256,
        "source_sha256": source_hash(),
        "packages": package_versions(),
        "schema": schema,
        "rows": {
            "housing": len(housing), "housing_located": int(housing["is_located"].sum()),
            "housing_confidential": int(housing["is_confidential"].sum()),
            "crashes": len(crashes), "injury_crashes": int(crashes["is_injury_crash"].sum()),
            "crashes_time_unknown": int(crashes["time_unknown"].sum()),
            "crashes_located": int(crashes["is_located"].sum()),
            "crashes_near_a_site": int(crashes["near_site_id"].notna().sum()),
            "sites": len(ns["sites"]), "zip_year": len(ns["zip_year"]),
            "panel_zips": int(ns["zip_year"]["zip"].nunique()),
            "event_site_cohorts": len(ns["event_site_table"]),
        },
        "constants": {
            "year_start": ns["YEAR_START"], "year_end": ns["YEAR_END"], "buffer_m": ns["BUFFER_M"],
            "event_window": ns["EVENT_WINDOW"], "n_boot": ns["N_BOOT"], "n_boot_joint": ns["N_BOOT_JOINT"],
            "ci_level": ns["CI_LEVEL"],
            "min_group_n": ns["MIN_GROUP_N"], "seed": ns["SEED"],
            "log_ratio_offset": ns["LOG_RATIO_OFFSET"], "baseline_years": list(ns["BASELINE_YEARS"]),
        },
        "dimensions": {
            "boroughs": ns["BOROUGHS"], "unknown_borough": UNKNOWN_BOROUGH,
            "construction_types": list(housing["construction_type"].cat.categories),
            "size_bands": ns["SIZE_BAND_LABELS"], "factor_groups": ns["FACTOR_GROUPS"],
            "hour_bands": list(ns["HOUR_BANDS"]),
            "hour_band_ranges": {name: list(hours) for name, hours in ns["HOUR_BANDS"].items()},
            "near_kinds": near_labels, "not_near": NOT_NEAR,
            "event_outcomes": EVENT_OUTCOMES,
        },
        "grid": grid,
        "files": files,
    })

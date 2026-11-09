"""Build constants and the check primitive every stage of the data build uses.

A check that fails raises DataCheckError, and the atomic export then leaves the previous output untouched.
"""
from __future__ import annotations

# Map grid: square cells of about 500 m, twice the 250 m buffer, so a cell is one "street
# neighbourhood". One degree of latitude is 111.2 km; one degree of longitude at 40.7 N is 84.3 km.
GRID_LAT_STEP = 0.0045                    # degrees, about 500 m
GRID_LON_STEP = 0.0060                    # degrees, about 506 m

NOT_NEAR = "Not near a site"              # label of crashes farther than BUFFER_M from every site
UNKNOWN_BOROUGH = "Unknown"               # crashes with neither a borough nor a recoverable ZIP
EVENT_OUTCOMES = {"injury": "injury_crashes", "all": "crashes", "pedcyc": "ped_cyc_crashes"}
COUNT_COLUMNS = ["n_all", "n_injury", "n_pedcyc", "n_ped", "n_cyc", "n_mot", "n_fatal"]
MAX_TOTAL_MB = 15                         # the files are committed and loaded on a 512 MB host
BYTES_PER_MB = 1_000_000
# Every file the build writes. An output folder holding anything else is refused, never emptied.
OUTPUT_TABLES = ["crash_cube", "hour_cube", "zip_cube", "map_grid", "housing_cube", "zip_year", "sites",
                 "event_sites", "city_year", "robustness", "cleaning_log"]
OUTPUT_FILES = {f"{name}.parquet" for name in OUTPUT_TABLES} | {"results.json", "meta.json"}
# Libraries that shape the numbers, by import name: scikit-learn's ball tree finds every distance and neighbour.
# How every table is written: pyarrow with strong zstd compression; the site reads them with fastparquet.
PARQUET_OPTIONS = {"engine": "pyarrow", "compression": "zstd", "compression_level": 19, "index": False}
PACKAGES = ["numpy", "pandas", "pyarrow", "fastparquet", "scipy", "sklearn", "statsmodels", "matplotlib", "IPython"]


class DataCheckError(RuntimeError):
    """A check on the exported data failed. Nothing has been written to the output folder."""


def require(condition, message: str) -> None:
    """Raise DataCheckError unless `condition` holds. Unlike `assert`, `python -O` cannot remove it."""
    if not bool(condition):
        raise DataCheckError(message)

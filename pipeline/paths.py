"""Every location the pipeline reads or writes, defined once.

Move a folder here and every stage, test and message follows it.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RAW_DIR = ROOT / "notebooks"                            # the two raw NYC Open Data files; the notebook runs here
NOTEBOOK_PATH = RAW_DIR / "NYC_Housing_Safety.ipynb"    # the generated, executed notebook
SECTIONS_DIR = ROOT / "pipeline" / "notebook" / "sections"   # one jupytext "percent" file per notebook section
STATS_MODULE = ROOT / "app" / "core" / "stats.py"             # the statistics shared by the notebook and the website
APP_DATA_DIR = ROOT / "app" / "data"                    # the only files the website reads

REBUILD_COMMAND = "python -m pipeline data"
NOTEBOOK_COMMAND = "python -m pipeline notebook --execute"

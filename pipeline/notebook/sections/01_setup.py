# %% [markdown]
# ## 1. Setup
#
# Everything the notebook needs is defined in this section: the libraries, one block of named
# constants, the plotting style and a few small helpers. Nothing is imported from a project
# folder, so the notebook runs on its own next to the two data files (and downloads them from
# NYC Open Data if they are not there).

# %% [markdown]
# ### 1.1 Libraries

# %%
import gc
import io
import math
import platform
import time
from pathlib import Path
from urllib.parse import urlencode

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow  # noqa: F401  (backs the "string[pyarrow]" dtype used when the tables are loaded)
import requests
import scipy
import seaborn as sns
import sklearn
from IPython.display import Markdown, display
from matplotlib import patheffects
from scipy import stats
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from sklearn.linear_model import LinearRegression
from sklearn.neighbors import BallTree

pd.set_option("display.max_columns", 60)
pd.set_option("display.width", 160)
pd.set_option("display.float_format", lambda value: f"{value:,.3f}")

# %% [markdown]
# ### 1.2 Constants
#
# Every threshold used later is named here once, with its unit and the reason for its value.
# Changing a value in this cell and re-running the notebook re-does the whole analysis. The years
# that depend on the study window (the break year, the base year of the index, the first test
# year, the baseline years) are computed from it here and never typed again further down.

# %%
# --- The two datasets (NYC Open Data, one per domain) -----------------------------------------
HOUSING_ID = "hg8x-zxpr"   # Housing & Development: Affordable Housing Production by Building
CRASH_ID = "h9gi-nx95"     # Transportation: Motor Vehicle Collisions - Crashes
DATASET_PAGE = "https://data.cityofnewyork.us/d/{}"
API_URL = "https://data.cityofnewyork.us/resource/{}.csv"

# --- Local copies: the only two files this notebook reads or writes ---------------------------
DATA_DIR = Path(".")                                   # same folder as the notebook
HOUSING_FILE = DATA_DIR / f"housing_{HOUSING_ID}.csv"
CRASH_FILE = DATA_DIR / f"crashes_{CRASH_ID}.csv.gz"

# --- Study window --------------------------------------------------------------------------
YEAR_START, YEAR_END = 2016, 2025   # ten full calendar years; 2026 is still incomplete
STUDY_YEARS = list(range(YEAR_START, YEAR_END + 1))

# --- Crash extraction (a filtered, column-limited copy of a 2.2-million-row table) -------------
CRASH_COLUMNS = [
    "collision_id", "crash_date", "crash_time", "borough", "zip_code", "latitude", "longitude",
    "on_street_name", "number_of_persons_injured", "number_of_persons_killed",
    "number_of_pedestrians_injured", "number_of_pedestrians_killed",
    "number_of_cyclist_injured", "number_of_cyclist_killed",
    "number_of_motorist_injured", "number_of_motorist_killed",
    "contributing_factor_vehicle_1", "contributing_factor_vehicle_2", "vehicle_type_code1",
]
CRASH_WHERE = (f"crash_date between '{YEAR_START}-01-01T00:00:00' "
               f"and '{YEAR_END}-12-31T23:59:59'")
PAGE_SIZE = 50_000          # rows per API request
HOUSING_ROW_LIMIT = 50_000  # far above the table size, so one request returns every row
REQUEST_RETRIES = 6         # attempts per request, with exponential back-off
REQUEST_TIMEOUT_S = 240

# --- Geography -----------------------------------------------------------------------------
BOROUGHS = ["Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"]
NYC_BOUNDS = {"lat": (40.45, 40.95), "lon": (-74.30, -73.65)}  # generous box around the five boroughs
EARTH_RADIUS_M = 6_371_000
METRES_PER_DEGREE = EARTH_RADIUS_M * math.pi / 180   # length of one degree of latitude on the sphere
BUFFER_M = 250              # "near a building" = within 250 m, roughly three short Manhattan blocks

# --- Analysis ---------------------------------------------------------------------------------
EVENT_WINDOW = 3            # years compared before and after a building's completion
MIN_GROUP_N = 30            # no statistic is reported for a group smaller than this

# --- Years derived from the study window -----------------------------------------------------
BREAK_YEAR = 2020                       # first year of the reporting change (Section 3)
INDEX_BASE_YEAR = BREAK_YEAR - 1        # last full year before the break; indices equal 100 here
N_TEST_YEARS = 3                        # study years held out of every forecast fit
FIRST_TEST_YEAR = YEAR_END - N_TEST_YEARS + 1   # first held-out year
BASELINE_YEARS = (YEAR_START, YEAR_START + EVENT_WINDOW - 1)   # first and last year of the pre-construction baseline

# %%
# INLINE-CONSTANTS: app/stats.py

# %% [markdown]
# ### 1.3 Plot style
#
# Figures are static images, so they stay visible in any viewer (Jupyter, Colab, GitHub, a PDF
# export) without an internet connection. The role colours (housing, crash, treated, control,
# placebo) come from the Okabe-Ito palette, which remains distinguishable under the common forms
# of colour blindness. The five boroughs use a separate set so that a borough is never mistaken
# for a role.

# %%
PALETTE = {
    "housing": "#0072B2",    # blue: anything measured on the housing side
    "crash": "#D55E00",      # vermilion: anything measured on the crash side
    "treated": "#0072B2",
    "control": "#7F7F7F",
    "placebo": "#E69F00",
    "before": "#B0B0B0",
    "after": "#009E73",
    "accent": "#CC79A7",
    "neutral": "#4D4D4D",
}
# Boroughs get their own qualitative set (Paul Tol's "muted" scheme, chosen because its colours stay
# apart under the common forms of colour blindness), so none of them borrows the colour of a role
# above (blue = housing, vermilion = crash, orange = placebo). No grey is used, because grey reads as
# "no data". Borough figures also carry a label or a marker, so colour is never the only cue.
BOROUGH_COLORS = dict(zip(BOROUGHS, ["#DDCC77", "#44AA99", "#AA4499", "#88CCEE", "#332288"]))
SEQUENTIAL_CMAP = "viridis"   # ordered quantities

sns.set_theme(style="whitegrid", context="notebook")
mpl.rcParams.update({
    "figure.figsize": (9, 4.8), "figure.dpi": 110, "savefig.dpi": 110,
    "axes.titlesize": 12.5, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.labelsize": 10.5, "axes.spines.top": False, "axes.spines.right": False,
    "legend.frameon": False, "legend.fontsize": 9.5, "grid.alpha": 0.35,
    "font.family": "DejaVu Sans",
})


def finish(ax, title, xlabel, ylabel, note=None):
    """Label one axes consistently: title, axis labels with units, and an optional footnote."""
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if note:
        ax.annotate(note, xy=(0, -0.2), xycoords="axes fraction", fontsize=8.5,
                    color=PALETTE["neutral"], va="top")
    return ax


def show(fig=None):
    """Lay out and draw the current figure (the one place that calls plt.show)."""
    (fig or plt.gcf()).tight_layout()
    plt.show()


def interval_rows(ax, labels, estimate, low, high, null=0.0, color=None, title="", xlabel=""):
    """Dot-and-interval chart: one row per label, a dashed line at the null value."""
    rows = np.arange(len(labels))[::-1]
    estimate, low, high = (np.asarray(v, dtype=float) for v in (estimate, low, high))
    ax.errorbar(estimate, rows, xerr=[estimate - low, high - estimate], fmt="o", capsize=3,
                color=color or PALETTE["treated"])
    ax.axvline(null, color=PALETTE["neutral"], linestyle="--", linewidth=1)
    ax.set_yticks(rows, labels)
    return finish(ax, title, xlabel, "")


def thousands(ax, axis="y"):
    """Show an axis in plain integers with thousands separators instead of 1e6 notation."""
    formatter = mpl.ticker.FuncFormatter(lambda value, _: f"{value:,.0f}")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(formatter)
    return ax


# %% [markdown]
# ### 1.4 Small helpers
#
# `say` prints a sentence whose numbers come from the data, so the commentary never goes stale.
# `log_rule` records every cleaning decision in one audit table that Section 4 prints at the end.

# %%
CLEANING_LOG = []   # one dict per cleaning rule, filled in Sections 4 and 6


def full_window_years(window=EVENT_WINDOW):
    """Study years that have `window` whole years of crash history on both sides."""
    return [year for year in STUDY_YEARS if year - window >= YEAR_START and year + window <= YEAR_END]


def release(*names):
    """Delete large working objects by name; names that are already gone are skipped.

    A bare `del` fails with a NameError when a cell is run a second time. This version can be
    re-run, and it hands the memory back straight away.
    """
    for name in names:
        globals().pop(name, None)
    gc.collect()


def say(text):
    """Render a Markdown sentence built from computed values (used for data-driven commentary)."""
    display(Markdown(text))


def pct(part, whole):
    """Percentage of `part` in `whole`, safe against an empty denominator."""
    return 100 * part / whole if whole else float("nan")


def n_pct(part, whole, digits=1):
    """'1,234 (5.6%)': a count with its share of a total."""
    return f"{int(part):,} ({pct(part, whole):.{digits}f}%)"


def fmt_ci(estimate, low, high, digits=1, unit=""):
    """'-4.6% (95% CI -11.9% to +3.3%)': an estimate with its interval."""
    f = lambda v: f"{v:+.{digits}f}{unit}"
    return f"{f(estimate)} (95% CI {f(low)} to {f(high)})"


def show_table(frame, rows=20):
    """Display a table without truncating its rows or text columns."""
    with pd.option_context("display.max_rows", rows, "display.max_colwidth", 60):
        display(frame)


def log_rule(dataset, rule, action, rows_before, rows_after, affected, reason):
    """Append one cleaning decision to the audit trail.

    action is one of 'drop', 'impute', 'flag' or 'standardise'; `affected` is the number of rows
    (or cells) the rule changed, which can be non-zero even when no row is dropped.
    """
    CLEANING_LOG.append({
        "dataset": dataset, "rule": rule, "action": action, "rows_before": int(rows_before),
        "rows_after": int(rows_after), "affected": int(affected), "reason": reason,
    })


def missing_table(frame):
    """Per-column missing count and share, sorted from most to least missing."""
    missing = frame.isna().sum()
    table = pd.DataFrame({"missing": missing, "missing_pct": 100 * missing / max(len(frame), 1),
                          "dtype": frame.dtypes.astype(str)})
    return table.sort_values("missing_pct", ascending=False)

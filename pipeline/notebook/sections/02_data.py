# %% [markdown]
# ## 2. The data
#
# ### 2.1 Loading the two datasets
#
# Both tables come from the NYC Open Data API (Socrata) as the assignment shows: dataset id, `$where`,
# `$limit` and a stable `$order`. Housing arrives in one request; crashes is a filtered copy (2.5) paged
# on the unique, never-missing `collision_id`, so pages cannot overlap or skip rows. The first run saves
# both files (several minutes, needs internet); later runs read them offline. Delete a file to refresh it.

# %%
# --- Constants shared by Sections 3 and 4 (defined once so the two cannot drift apart) ----------
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"   # the one timestamp layout the API returns for both tables
BYTES_PER_MB = 1_000_000
CONFIDENTIAL_NAME = "CONFIDENTIAL"     # project_name the publisher uses for withheld records
WITHHELD_ADDRESS = "----"              # house number and street of a withheld record
ZIP_PLACEHOLDER = "10000"              # not a real ZIP: written in the crash table when the officer had none
IQR_MULTIPLIER = 1.5                   # Tukey's fence: 1.5 interquartile ranges beyond the quartiles
EXTREME_INJURED = 10                   # persons; more than this cannot fit in a few cars (bus-scale events)
INTEGER_BIN_COUNT = 30                 # log-spaced bin edges for histograms of unit counts
TOO_MANY_REQUESTS = 429                # HTTP "slow down": worth a retry

# Housing unit columns. A blank in any of them means zero units (shown in Section 3, applied in 4.1).
INCOME_UNIT_COLUMNS = ["extremely_low_income_units", "very_low_income_units", "low_income_units",
                       "moderate_income_units", "middle_income_units", "other_income_units"]
BEDROOM_UNIT_COLUMNS = ["studio_units", "_1_br_units", "_2_br_units", "_3_br_units", "_4_br_units",
                        "_5_br_units", "_6_br_units", "unknown_br_units"]
TENURE_UNIT_COLUMNS = ["counted_rental_units", "counted_homeownership_units"]
TOTAL_UNIT_COLUMNS = ["all_counted_units", "total_units"]
UNIT_COLUMNS = INCOME_UNIT_COLUMNS + BEDROOM_UNIT_COLUMNS + TENURE_UNIT_COLUMNS + TOTAL_UNIT_COLUMNS
HOUSING_REQUIRED = ["project_id", "building_id", "project_name", "borough", "postcode", "latitude", "longitude",
                    "project_start_date", "building_completion_date", "reporting_construction_type", *UNIT_COLUMNS]


def fetch_csv(dataset_id, params):
    """One API request returned as an all-text DataFrame, retried with back-off on 429 and 5xx."""
    url = API_URL.format(dataset_id) + "?" + urlencode(params)
    problem = "no attempt"
    for attempt in range(REQUEST_RETRIES):
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT_S)
        except requests.RequestException as error:
            problem = f"network error: {error}"
        else:
            if response.status_code == 200:   # an empty body is the end of the paging
                return pd.read_csv(io.StringIO(response.text), dtype=str) if response.text.strip() else pd.DataFrame()
            problem = f"HTTP {response.status_code}"
            # Any other 4xx means the request itself is wrong, so retrying cannot help.
            if 400 <= response.status_code < 500 and response.status_code != TOO_MANY_REQUESTS:
                raise RuntimeError(f"NYC Open Data rejected the request ({problem}): {url}")
        time.sleep(2 ** attempt)
    raise RuntimeError(f"No answer after {REQUEST_RETRIES} attempts ({problem}): {url}")


def download_housing(path):
    """Download the whole housing table in one request."""
    table = fetch_csv(HOUSING_ID, {"$limit": HOUSING_ROW_LIMIT, "$order": "building_id, project_id"})
    assert len(table) < HOUSING_ROW_LIMIT, "row limit reached (a cut request raises no error): raise it"
    table.to_csv(path, index=False)


def download_crashes(path):
    """Download the filtered crash table with keyset paging, appending each page to a temporary file."""
    partial = path.with_name(path.name + ".part")
    partial.unlink(missing_ok=True)          # a half-finished earlier download is started again
    last_id, saved = 0, 0
    while True:
        page = fetch_csv(CRASH_ID, {"$select": ",".join(CRASH_COLUMNS),
                                    "$where": f"{CRASH_WHERE} AND collision_id > {last_id}",
                                    "$order": "collision_id", "$limit": PAGE_SIZE})
        if page.empty:
            break
        # The API omits a column that is empty on a page, so the full layout is restored.
        page = page.reindex(columns=CRASH_COLUMNS)
        page.to_csv(partial, mode="a", header=saved == 0, index=False, compression="gzip")
        last_id = int(pd.to_numeric(page["collision_id"]).max())
        saved += len(page)
        print(f"  downloaded {saved:>9,} crash rows", end="\r")
    partial.replace(path)                    # renamed only once the last page is in


def load_raw(path, download, required):
    """Read the local copy (downloading it first if missing) as Arrow text, and check its column names."""
    pd.array([], dtype="string[pyarrow]")    # fails at once if pyarrow is missing, not after a download
    if not path.exists():
        print(f"{path.resolve()} not found: downloading from NYC Open Data ...")
        download(path)
    frame = pd.read_csv(path, dtype="string[pyarrow]")   # Arrow strings: a fraction of object memory
    assert set(required) <= set(frame.columns), f"{path.name} lacks API columns {set(required) - set(frame.columns)}"
    return frame


raw_housing = load_raw(HOUSING_FILE, download_housing, HOUSING_REQUIRED)
raw_crashes = load_raw(CRASH_FILE, download_crashes, CRASH_COLUMNS)
print("housing columns:", list(raw_housing.columns), "\ncrash columns:  ", list(raw_crashes.columns))

# --- Helpers shared by Sections 3 and 4, so each rule exists once ---------------------------------
CLOCK_PATTERN = r"^(\d{1,2}):(\d{2})$"                  # crash_time is written H:MM or HH:MM
MID_LATITUDE_DEG = float(np.mean(NYC_BOUNDS["lat"]))    # middle of the city box, for map proportions


def to_number(text, strict=True):
    """Text column to float64; with `strict`, a non-blank value that is not a number stops the notebook."""
    number = pd.Series(pd.to_numeric(text, errors="coerce").to_numpy(dtype="float64", na_value=np.nan),
                       index=text.index, name=text.name)
    if strict:
        unparseable = int((text.notna() & number.isna()).sum())
        assert unparseable == 0, f"{unparseable} non-numeric values in column {text.name}"
    return number


def tukey_upper_fence(values):
    """Third quartile plus IQR_MULTIPLIER interquartile ranges."""
    q1, q3 = np.percentile(values, [25, 75])
    return q3 + IQR_MULTIPLIER * (q3 - q1)


def parse_hour(time_text):
    """Hour (nullable Int8) and minute (float64) from 'H:MM' text; anything else becomes missing."""
    parts = time_text.str.strip().str.extract(CLOCK_PATTERN).astype("float64")
    is_valid = parts[0].between(0, 23) & parts[1].between(0, 59)
    return parts[0].where(is_valid).astype("Int8"), parts[1].where(is_valid)


def memory_mb(frame):
    """Memory held by a frame in megabytes, counting the text inside string columns."""
    return frame.memory_usage(deep=True).sum() / BYTES_PER_MB


def map_axes(ax):
    """Give longitude/latitude axes the proportions of the ground and remove the grid."""
    ax.set_aspect(1 / math.cos(math.radians(MID_LATITUDE_DEG)))
    ax.grid(False)
    return ax


def join_and(items):
    """'a', 'a and b', 'a, b and c'."""
    items = [str(item) for item in items]
    return " and ".join(items) if len(items) <= 2 else ", ".join(items[:-1]) + " and " + items[-1]


def integer_log_bins(maximum):
    """Log-axis histogram edges halfway between integers, so small counts leave no empty gaps."""
    steps = np.unique(np.round(np.logspace(0, np.log10(maximum), INTEGER_BIN_COUNT)))
    return np.append(steps - 0.5, maximum + 0.5)


# %% [markdown]
# ### 2.2 Dataset overview
# One profile per copy: size, grain, time and place attributes and their completeness (also used in 2.4).

# %%
def profile(name, dataset_id, domain, frame, grain, date_column, zip_column, time_columns, place_columns):
    """One column of the overview table for one raw dataset."""
    filled = lambda columns: f"{100 * frame[columns].notna().all(axis=1).mean():.1f}"
    days = frame[date_column].dropna().str.slice(0, 10)   # ISO text: the first ten characters are the day
    return name, {
        "domain": domain, "id": dataset_id, "page": DATASET_PAGE.format(dataset_id), "one row is": grain,
        "rows": f"{len(frame):,}", "columns": frame.shape[1],   # the API column names are printed in 2.1
        "time attributes": ", ".join(time_columns), "place attributes": ", ".join(place_columns),
        "date range": f"{days.min()} to {days.max()} ({date_column})",
        "rows with coordinates (%)": filled(["latitude", "longitude"]),
        "rows with a ZIP code (%)": filled([zip_column]),
        "rows with a borough (%)": filled(["borough"]),
        "distinct ZIP values": frame[zip_column].nunique(),
    }


overview = pd.DataFrame(dict([
    profile("Affordable Housing Production by Building", HOUSING_ID, "Housing & Development", raw_housing,
            "a building in a city-financed affordable housing project", "project_start_date", "postcode",
            ["project_start_date", "project_completion_date", "building_completion_date"],
            ["borough", "postcode", "community_board", "census_tract", "latitude", "longitude"]),
    profile("Motor Vehicle Collisions - Crashes", CRASH_ID, "Transportation", raw_crashes,
            "a police-reported motor vehicle collision", "crash_date", "zip_code",
            ["crash_date", "crash_time"], ["borough", "zip_code", "on_street_name", "latitude", "longitude"]),
]))
shared_columns = set(raw_housing.columns) & set(raw_crashes.columns)
overview.loc["column names shared by both"] = ", ".join(sorted(shared_columns))
with pd.option_context("display.max_colwidth", 90):
    display(overview)
# The assignment requires at least 9 columns per dataset and a shared integration attribute.
assert min(raw_housing.shape[1], raw_crashes.shape[1]) >= 9 and {"borough", "latitude", "longitude"} <= shared_columns

# %% [markdown]
# ### 2.3 Why these two datasets
#
# Do streets around new affordable housing differ in injury crashes, and change at completion? Both
# sides need a precise place and date. Housing gives the events: completion date, units by income
# band, new construction or preservation (no new residents: a natural comparison) and a point. Crashes
# give the outcome: date, time, point, casualties by pedestrian, cyclist and motorist.
#
# | Catalog | Alternative considered | Why it was weaker for this question |
# |---|---|---|
# | Housing | DOB violations, HPD complaints | Describe existing buildings; no date when new homes open, no household count. |
# | Housing | DOB permits and job filings | An intention to build; no affordable-unit count, no dependable completion date. |
# | Transportation | Parking meters, street permits | Inventory or activity with no safety outcome. |
# | Transportation | Traffic and bike counts, bus delays | Few locations, or no coordinate, so most sites have no observation nearby. |
# | Transportation | Taxi trips | Located by taxi zone only, and too large for a notebook. |
#
# The deciding point: both tables carry coordinates, ZIP, borough and exact date, allowing two
# independent joins (ZIP by year, and distance) that check each other. No other pair had all four.
#
# ### 2.4 Feasibility check
#
# The catalog lists the crash table as "SIRTA Data", so a feasibility check is included (from 2.2):
#
# * **Size.** Both clear nine columns; ten years of crashes put many collisions around each building.
# * **Geographic and temporal attributes.** Borough, ZIP, coordinates and date on both; crash time too.
# * **Expected integration.** No shared row key; the tables meet at ZIP by year and by distance
#   (a crash within 250 m of a building), both built in Section 5.
# * **Support for the question.** Most rows have coordinates and crash years span before and after
#   most completions. Coverage gaps are not random (Section 3).
#
# ### 2.5 Why the crash table is a filtered copy
#
# The cell prints the exact request (constants from 1.2), checks the copy matches it, and sizes it.

# %%
CRASH_COLUMNS_NOT_LOADED = ["location", "off_street_name", "cross_street_name",   # text repeated elsewhere
                            *[f"contributing_factor_vehicle_{n}" for n in (3, 4, 5)],
                            "vehicle_type_code2", *[f"vehicle_type_code_{n}" for n in (3, 4, 5)]]
crash_request = pd.Series({
    "$select": ", ".join(CRASH_COLUMNS), "$order": "collision_id",
    "$where": CRASH_WHERE + " AND collision_id > (last collision_id of the previous page)",
    "$limit": f"{PAGE_SIZE:,} rows per request, repeated until a request returns no rows",
    "columns not requested": ", ".join(CRASH_COLUMNS_NOT_LOADED)}, name="value")
with pd.option_context("display.max_colwidth", None):
    display(crash_request.to_frame())

# The copy must match the request: every year inside the window and every collision once.
assert raw_crashes["crash_date"].str.slice(0, 4).astype(int).between(YEAR_START, YEAR_END).all()
assert raw_crashes["collision_id"].is_unique, "paging returned a collision twice"
cohort_years = full_window_years()   # completion years with EVENT_WINDOW whole years on each side
say(f"The copy holds **{len(raw_crashes):,} crashes** from {YEAR_START} to {YEAR_END} ({len(STUDY_YEARS)} "
    f"years), {len(CRASH_COLUMNS)} of the {len(CRASH_COLUMNS) + len(CRASH_COLUMNS_NOT_LOADED)} source "
    f"columns, no `collision_id` twice, and **{memory_mb(raw_crashes):,.0f} MB** as text. Buildings completed "
    f"{cohort_years[0]}-{cohort_years[-1]} have {EVENT_WINDOW} full crash years before and after.")

# %% [markdown]
# The filter restricts rows by date and columns by name; it does not sample, so every crash in the
# window is loaded. **Memory:** the full text table leaves free Colab no room for the spatial join.
# **2026** is out because a partial year looks like a fall in crashes; **before 2016** no question
# reads (the earliest window starts in 2016). **Columns** left out are later vehicles' factors and
# types and street text repeating `on_street_name` and the coordinates. A random sample was rejected:
# crashes within 250 m of one building in one year are already few, and sampling would zero many.
#
# ### 2.6 Known issues at a glance
#
# | Dataset | Issue | Handled in |
# |---|---|---|
# | Housing | Unit counts blank where zero; confidential rows without address, ZIP or coordinates | 4.1, 4.3 |
# | Housing | No completion date; one building under several projects; right-skewed size | 4.4, 4.2, 4.6 |
# | Crashes | ZIP and borough missing together for a large, year-varying share | Section 6 (ZIP recovered from coordinates) |
# | Crashes | Coordinates missing, at (0, 0) or outside the city; placeholder ZIP codes | 4.8 |
# | Crashes | Reports of crashes without injuries fall sharply from 2020 | Section 3; analyses use injury crashes |
# | Crashes | Injured total differs from its parts; a few crashes with very many injured | 4.9, 4.10 |
# | Crashes | Factor spelling variants and a large "Unspecified" group; 0:00 doubles as unknown time | 4.11, 4.7 |
# | Both | All text; borough letter case differs; rows without a partner after the join | Section 4; Section 6 |

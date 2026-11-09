# %% [markdown]
# ## 4. Pre-integration cleaning
#
# ### 4.0 Policy, and how each decision is recorded
#
# The raw text tables become two typed frames, `housing` and `crashes`, through four actions:
#
# * **Drop** a row only when unusable: no key, a repeat, or outside the window. Missing fields alone
#   never drop a row (a crash without a ZIP still counts toward its borough).
# * **Impute** only what follows from the same row: blank unit counts that mean zero, a missing
#   casualty total equal to its parts. No statistical imputation; missing coordinates and dates stay missing.
# * **Flag** what is unusual but plausible, or wrong but unrepairable: the row stays, a boolean marks it.
# * **Standardise** when only the form changes: text to dates, case, categories, placeholders to missing.
#
# Every rule goes to `CLEANING_LOG` with rows before and after and the rows (or cells) touched; rules
# that find nothing are logged too, so the log also shows what was checked (4.13).
#
# | Task | Housing | Crashes |
# |---|---|---|
# | Missing values (drop against impute) | 4.1, 4.3, 4.4 | 4.8, 4.9 |
# | Outliers (IQR and domain rules) | 4.6 | 4.8 (coordinates), 4.10 |
# | Inconsistent data | 4.4, 4.5 | 4.8, 4.9 |
# | Format standardisation | 4.1, 4.3, 4.4 | 4.7, 4.8, 4.11 |
# | Duplicates | 4.2 | 4.7, 4.8 |

# %%
# --- Constants for Section 4 (those shared with Section 3 are in 2.1) ----------------------------
# USPS ZIP ranges per borough (inclusive). 11001 and 11040 straddle the Queens / Nassau line and are
# listed under Queens; 11500-11599 is Nassau County, so Queens is split around it.
NYC_ZIP_RANGES = {
    "Manhattan": [(10001, 10282)], "Staten Island": [(10301, 10314)], "Bronx": [(10451, 10475)],
    "Queens": [(11001, 11001), (11004, 11005), (11040, 11040), (11101, 11120), (11351, 11499), (11690, 11697)],
    "Brooklyn": [(11201, 11256)]}
DEEP_AFFORDABLE_COLUMNS = ["extremely_low_income_units", "very_low_income_units"]
HOUSING_DATE_COLUMNS = ["project_start_date", "project_completion_date", "building_completion_date"]

SIZE_BAND_EDGES = [0, 4, 19, 49, 149, np.inf]                   # total units, upper edge inclusive
SIZE_BAND_LABELS = ["1-4", "5-19", "20-49", "50-149", "150+"]   # from row houses to towers

# Crash casualty columns: raw name -> short name used from here on.
CASUALTY_COLUMNS = {
    "number_of_persons_injured": "injured", "number_of_persons_killed": "killed",
    "number_of_pedestrians_injured": "ped_injured", "number_of_pedestrians_killed": "ped_killed",
    "number_of_cyclist_injured": "cyc_injured", "number_of_cyclist_killed": "cyc_killed",
    "number_of_motorist_injured": "mot_injured", "number_of_motorist_killed": "mot_killed",
}
ROAD_USER_PREFIXES = ["ped", "cyc", "mot"]

# Time-of-day bands as (first hour, last hour), inclusive, 24-hour clock.
HOUR_BANDS = {"Night": (0, 5), "Morning": (6, 11), "Afternoon": (12, 17), "Evening": (18, 23)}

# Contributing-factor groups. Each raw label is trimmed and lower-cased, then takes the group of
# the FIRST pattern it matches, so the order matters (explained line by line).
FACTOR_RULES = [
    # the "no factor recorded" label and bare numeric codes ("80", "1") carry no information
    ("Unspecified", r"^unspecified$|^\d+$"),
    # the one factor that blames a person outside a vehicle; kept apart for RQ6
    ("Pedestrian or cyclist error", r"pedestrian|bicyclist"),
    # before "Vehicle defect" ("defective" pavement), "Improper manoeuvre" ("lane marking") and
    # "Failure to yield or obey" ("traffic control device")
    ("Road or environment", r"pavement|shoulders|lane marking|traffic control device|obstruct|debris"
                            r"|glare|animals"),
    # named parts, so "tire failure" is not caught by "failure to yield" below
    ("Vehicle defect", r"defective|defects|steering|tire|windshield|tinted"),
    # "illnes" absorbs the misspelling "Illnes"; "drugs" absorbs both "(illegal)" spellings
    ("Impairment or medical", r"alcohol|drugs|medication|asleep|fatigued|drowsy|consciousness"
                              r"|illnes|disability"),
    # "cell phone" absorbs "(hand-held)", "(hand-Held)" and "(hands-free)"
    ("Distraction", r"distraction|inattention|cell phone|electronic|texting|headphones|eating"
                    r"|navigation"),
    ("Speed or aggressive driving", r"speed|aggressive|following too closely"),
    ("Failure to yield or obey", r"yield|disregarded|keep right"),
    # after "Road or environment", so "lane" here means lane use, not lane markings
    ("Improper manoeuvre", r"passing|lane|turning|backing|inexperience"),
    ("Other", r"other vehicular|uninvolved|vandalism|driverless|oversized"),
]
FACTOR_GROUPS = [group for group, _ in FACTOR_RULES]
FACTOR_FALLBACK = "Other"   # group for a label no pattern recognises
MAP_SAMPLE_ROWS = 60_000    # crashes drawn in the coordinate figure; enough to show the street grid


def note(dataset, frame, rule, action, affected, reason):
    """Log a rule that keeps every row of `frame`."""
    log_rule(dataset, rule, action, len(frame), len(frame), affected, reason)


def standardise_zip(zip_text):
    """(zip, implied borough): a 5-digit NYC ZIP or missing (blank, 10000 and non-NYC fail the range test)."""
    text = zip_text.str.strip().str.replace(r"\.0$", "", regex=True)
    number = pd.to_numeric(text.where(text.str.fullmatch(r"\d{5}").fillna(False).astype(bool)),
                           errors="coerce").astype("float64")
    implied = pd.Series(np.nan, index=zip_text.index, dtype=object)
    for borough_name, ranges in NYC_ZIP_RANGES.items():
        for low, high in ranges:
            implied[number.between(low, high)] = borough_name
    return text.where(implied.notna()).astype("string[pyarrow]"), implied


def validate_coordinates(lat, lon):
    """(lat, lon, n_zero, n_outside): kept inside NYC_BOUNDS; (0, 0), a failed geocode, is counted apart."""
    is_zero = (lat == 0) & (lon == 0)
    in_box = lat.between(*NYC_BOUNDS["lat"]) & lon.between(*NYC_BOUNDS["lon"])
    is_outside = lat.notna() & lon.notna() & ~in_box & ~is_zero
    keep = in_box & ~is_zero
    return lat.where(keep), lon.where(keep), int(is_zero.sum()), int(is_outside.sum())


# %% [markdown]
# ### 4.1 Housing: blank unit counts are structural zeros
#
# The unit columns are mostly blank and never zero (Section 3): the publisher writes zero as blank,
# so blanks are **imputed as 0**. Dropping those rows would remove almost the whole table; leaving
# them missing would make every sum missing. The claim is tested in 4.5: after the fill each
# breakdown must add up to `all_counted_units` in every row.

# %%
raw_units = raw_housing[UNIT_COLUMNS].apply(to_number)
assert ((raw_units.fillna(0) % 1 == 0) & (raw_units.fillna(0) >= 0)).all().all(), "units must be whole, >= 0"
display(pd.DataFrame({"blank (%)": 100 * raw_units.isna().mean(),
                      "zero before fill (%)": 100 * (raw_units == 0).mean(),
                      "zero after fill (%)": 100 * raw_units.fillna(0).eq(0).mean()}).round(1))

# %% [markdown]
# Blank and zero swap places column by column: a pure relabelling.
#
# ### 4.2 Housing: duplicates on the true key
#
# A building can appear in several projects (construction, later preservation): separate investments
# with their own dates and units. The key is therefore (`project_id`, `building_id`); rows repeating
# it, or identical in every column, are dropped. Withheld rows have no `building_id` (pandas would
# match two of them), so only rows with one are compared on the key.

# %%
project_id = to_number(raw_housing["project_id"]).astype("int64")
building_id = to_number(raw_housing["building_id"]).astype("Int64")
key = pd.DataFrame({"project_id": project_id, "building_id": building_id})
is_key_repeat = building_id.notna() & key.duplicated()
is_duplicate = (is_key_repeat | raw_housing.duplicated()).to_numpy()
repeated_building = building_id.notna() & building_id.duplicated()
display(pd.Series({
    "identical in every column": int(raw_housing.duplicated().sum()),
    "repeat (project_id, building_id)": int(is_key_repeat.sum()),
    "would go if deduplicated on building_id alone": int(repeated_building.sum()),
}, name="rows").to_frame())

housing_source = raw_housing.loc[~is_duplicate].reset_index(drop=True)
log_rule("housing", "blank unit counts set to 0", "impute", len(raw_housing), len(raw_housing),
         int(raw_units.isna().sum().sum()), "The publisher writes zero as blank; sums need a number. Cells.")
log_rule("housing", "duplicate rows on (project_id, building_id) or on every column", "drop",
         len(raw_housing), len(housing_source), int(is_duplicate.sum()),
         "A repeated key would double count units; building_id alone is not the key.")

housing = pd.DataFrame({
    "housing_id": np.arange(len(housing_source), dtype="int32"),      # surrogate key for later joins
    "project_id": project_id[~is_duplicate].to_numpy(),
    "building_id": building_id[~is_duplicate].reset_index(drop=True),
    "project_name": housing_source["project_name"].str.strip(),
})
units = raw_units.loc[~is_duplicate].reset_index(drop=True).fillna(0).astype("int16")

# %% [markdown]
# Deduplicating on `building_id` alone would delete the repeat investments above, so it was rejected;
# counts of places rather than investments use the sites of Section 5.
#
# ### 4.3 Housing: geographic identifiers, and records that cannot be located
#
# Borough becomes a `BOROUGHS` category; the ZIP stays a five-character string (a label) inside a
# borough ZIP range; coordinates must fall inside `NYC_BOUNDS`. Withheld (CONFIDENTIAL) records have
# no address, ZIP or coordinates and nothing below the borough, so they cannot be imputed (a random
# ZIP would invent a link to crashes), and dropping them would lose their units from borough totals:
# they are **kept and flagged** (`is_confidential`). `is_located` is the filter of every spatial analysis.

# %%
housing["borough"] = pd.Categorical(housing_source["borough"].str.strip().str.title(), categories=BOROUGHS)
housing["zip"], zip_borough = standardise_zip(housing_source["postcode"])
housing["lat"], housing["lon"], housing_zero, housing_outside = validate_coordinates(
    to_number(housing_source["latitude"]), to_number(housing_source["longitude"]))
housing["is_confidential"] = (housing_source["project_name"].str.strip().str.upper()
                              .eq(CONFIDENTIAL_NAME).fillna(False).to_numpy(dtype=bool))
housing["is_located"] = housing["lat"].notna() & housing["lon"].notna()
house_number = housing_source["house_number"].str.strip()
housing["address"] = (house_number + " " + housing_source["street_name"].str.strip()).where(
    house_number != WITHHELD_ADDRESS)
confidential = housing["is_confidential"]
housing_zip_disagree = zip_borough.notna() & (zip_borough != housing["borough"].astype(object))

note("housing", housing, "borough to category with the BOROUGHS spelling", "standardise",
     int(housing["borough"].isna().sum()), "One spelling on both tables; affected = unrecognised values.")
note("housing", housing, "postcode to 5-character string, checked against NYC ZIP ranges", "standardise",
     int(housing_source["postcode"].notna().sum() - housing["zip"].notna().sum()),
     "ZIP is a label and a join key; affected = codes rejected as not NYC.")
note("housing", housing, "coordinates at (0,0) or outside NYC_BOUNDS set to missing", "standardise",
     housing_zero + housing_outside, "A point outside the city would corrupt distance joins.")
note("housing", housing, "confidential records kept and flagged (is_confidential)", "flag",
     int(confidential.sum()), "No address, ZIP or coordinates, so not imputable; valid for borough totals.")
note("housing", housing, "rows without usable coordinates flagged (is_located = False)", "flag",
     int((~housing["is_located"]).sum()), "Spatial analyses need a point; ZIP and borough analyses do not.")
note("housing", housing, "ZIP range borough differs from stated borough (stated borough kept)", "flag",
     int(housing_zip_disagree.sum()), "Checked only; a few ZIPs legitimately cross a borough line.")

display(housing.assign(units=units["total_units"])
        .groupby(["is_confidential", "is_located"])
        .agg(rows=("housing_id", "size"), total_units=("units", "sum"), with_zip=("zip", "count")))
assert housing["borough"].notna().all()
assert not housing.loc[confidential, ["zip", "lat", "lon", "building_id", "address"]].notna().any().any()
say(f"Unrecognised boroughs: {int(housing['borough'].isna().sum())}; rejected ZIPs: "
    f"{int(housing_source['postcode'].notna().sum() - housing['zip'].notna().sum())}; coordinates at (0,0): "
    f"{housing_zero}, outside the city: {housing_outside}. Confidential: {n_pct(confidential.sum(), len(housing))} "
    f"of rows but {pct(units.loc[confidential, 'total_units'].sum(), units['total_units'].sum()):.2f}% of units. "
    f"ZIP range and stated borough disagree in {int(housing_zip_disagree.sum())} rows, in ZIP "
    f"{join_and(sorted(housing.loc[housing_zip_disagree, 'zip'].unique()))}.")

# %% [markdown]
# The fields were already clean, so the work is typing and flags. The few named rows without
# coordinates lack a ZIP and tax lot too; an outside geocoding service was rejected as a third source
# and network dependency. The disagreeing ZIP is Marble Hill (Manhattan with Bronx mail): borough kept.
#
# ### 4.4 Housing: dates, completion and date consistency
#
# Dates are parsed with the one exact layout and `errors="raise"`, so an odd value stops the notebook
# instead of silently going missing. Completion is the building's date, else the project's (same-row
# imputation); with neither the building is unfinished and the date stays missing. A typical
# construction time was rejected: the completion year is the event-study treatment date, and an
# invented one would put crashes on the wrong side of it. Completion before the start (the financing
# close, which can follow the work) is flagged since the wrong date is unknown; so is same-day completion.

# %%
housing_dates = pd.DataFrame({column: pd.to_datetime(housing_source[column], format=DATE_FORMAT, errors="raise")
                              for column in HOUSING_DATE_COLUMNS})
assert housing_dates["project_start_date"].notna().all()
housing["project_start_date"] = housing_dates["project_start_date"]
housing["completion_date"] = housing_dates["building_completion_date"].fillna(housing_dates["project_completion_date"])
housing["start_year"] = housing["project_start_date"].dt.year.astype("int16")
housing["completion_year"] = housing["completion_date"].dt.year.astype("Int16")
housing["is_completed"] = housing["completion_date"].notna()
housing["completion_before_start"] = (housing["completion_date"] < housing["project_start_date"]).to_numpy()
housing["same_day_completion"] = (housing["completion_date"] == housing["project_start_date"]).to_numpy()
filled_from_project = int((housing_dates["building_completion_date"].isna() & housing["is_completed"]).sum())
in_window = housing["is_completed"] & housing["completion_year"].between(YEAR_START, YEAR_END).fillna(False)

note("housing", housing, "three date columns parsed from text with one exact layout", "standardise", 0,
     "Dates must be comparable; any unparseable value would stop the notebook.")
note("housing", housing, "completion_date = building date, else project date", "impute", filled_from_project,
     "Deterministic fill from the same row; rows with neither date stay missing.")
note("housing", housing, "no completion date: is_completed = False, date left missing", "flag",
     int((~housing["is_completed"]).sum()), "No treatment date; an invented one would misplace crashes.")
note("housing", housing, "completion before project start flagged (completion_before_start)", "flag",
     int(housing["completion_before_start"].sum()), "Impossible order, but which date is wrong is unknown.")
note("housing", housing, "completion on the start date flagged (same_day_completion)", "flag",
     int(housing["same_day_completion"].sum()), "No observable construction period.")

say(f"The project date fills {filled_from_project} missing building dates; "
    f"{n_pct((~housing['is_completed']).sum(), len(housing))} rows have neither and count as not completed. "
    f"Completion precedes the start in {int(housing['completion_before_start'].sum())} rows and equals it in "
    f"{int(housing['same_day_completion'].sum()):,}. {int(in_window.sum()):,} completions fall in "
    f"{YEAR_START}-{YEAR_END}, {int((in_window & housing['is_located']).sum()):,} of them located.")

# %% [markdown]
# ### 4.5 Housing: unit consistency and derived unit measures
#
# Income bands, bedroom counts and tenure must each add up to `all_counted_units`, which cannot exceed
# `total_units` (it adds market-rate units). Had a blank meant "unknown" (4.1), sums would fall short.
# `deep_affordable_share` (extremely + very low income over counted units) is left **missing** where
# nothing is counted: zero would claim "no deep affordability" rather than "no restricted units".

# %%
counted = units["all_counted_units"]
unit_checks = pd.Series({
    "income bands sum to counted units": int((units[INCOME_UNIT_COLUMNS].sum(axis=1) != counted).sum()),
    "bedroom counts sum to counted units": int((units[BEDROOM_UNIT_COLUMNS].sum(axis=1) != counted).sum()),
    "rental + homeownership = counted units": int((units[TENURE_UNIT_COLUMNS].sum(axis=1) != counted).sum()),
    "counted units exceed total units": int((counted > units["total_units"]).sum()),
    "total units below 1": int((units["total_units"] < 1).sum()),
}, name="rows violating")
display(unit_checks.to_frame())
note("housing", housing, "unit identities (three breakdowns = counted <= total, total >= 1)", "flag",
     int(unit_checks.sum()), "Must hold if blank means zero; affected = violations.")
assert unit_checks.sum() == 0, "a unit identity is broken: blank may not mean zero"

housing[UNIT_COLUMNS] = units
housing["construction_type"] = pd.Categorical(housing_source["reporting_construction_type"].str.strip().str.title(),
                                              categories=["New Construction", "Preservation"])
housing["deep_affordable_units"] = units[DEEP_AFFORDABLE_COLUMNS].sum(axis=1).astype("int16")
housing["deep_affordable_share"] = (housing["deep_affordable_units"] / counted.where(counted > 0)).astype("float64")
note("housing", housing, "deep_affordable_share left missing where counted units = 0", "flag",
     int((counted == 0).sum()), "A share with a zero denominator is undefined.")
assert housing["construction_type"].notna().all()

# %% [markdown]
# No row breaks an identity, which confirms that blank means zero, so no repair rule is needed.
#
# ### 4.6 Housing: size outliers
#
# Size drives RQ4. Tukey's rule assumes symmetry but sizes are right-skewed, so it runs on the raw
# count and on log10. Decision: **flag and keep**. The largest records are real developments (below),
# and removing or capping them deletes the buildings most likely to change a street. `size_band`
# gives five ordered bands for analyses sensitive to the tail.

# %%
total_units = units["total_units"].astype("float64")
size_fence = tukey_upper_fence(total_units)
log_size_fence = 10 ** tukey_upper_fence(np.log10(total_units))   # fence in log units, back to units
housing["is_size_outlier"] = (total_units > size_fence).to_numpy()
housing["size_band"] = pd.cut(total_units, bins=SIZE_BAND_EDGES, labels=SIZE_BAND_LABELS, ordered=True)
note("housing", housing, "total_units above the Tukey fence flagged (is_size_outlier), not removed", "flag",
     int(housing["is_size_outlier"].sum()), "Large buildings are real and are what RQ4 needs.")

display(housing.nlargest(5, "total_units")[["project_name", "borough", "total_units", "construction_type",
                                             "completion_year"]])
display(housing.groupby("size_band", observed=True)
        .agg(rows=("housing_id", "size"), total_units=("total_units", "sum"), flagged=("is_size_outlier", "sum")))
say(f"The raw-scale fence is {size_fence:.0f} units and flags {n_pct(housing['is_size_outlier'].sum(), len(housing))} "
    f"rows holding {pct(total_units[housing['is_size_outlier']].sum(), total_units.sum()):.0f}% of all units. "
    f"On the log scale the fence is {log_size_fence:,.0f} units and flags {int((total_units > log_size_fence).sum())} "
    f"rows; the largest building has {int(total_units.max()):,} units.")

# %% [markdown]
# A rule that flags this large a share is measuring skew, not finding errors: on the log scale,
# where its assumption holds better, nothing is extreme. The flag therefore reads "large building".
#
# ### 4.7 Crashes: key, duplicates, dates and time of day
#
# Crash rows are dropped only for no `collision_id`, a repeated one, or a date that fails to parse or
# lies outside the window; the tests run although the download filtered on date, so a changed
# download cannot slip through. A unique key rules out full-row duplicates (double filings: 4.8).
# The hour becomes a small integer in four six-hour bands (RQ8). 0:00 is also written when the time
# is unknown, so crashes at exactly 0:00 are flagged `time_unknown` and left out of hour-of-day work.

# %%
crash_rows_raw, crash_raw_names, crash_memory_raw = len(raw_crashes), list(raw_crashes.columns), memory_mb(raw_crashes)
crash_columns_raw = len(crash_raw_names)

collision_id = pd.to_numeric(raw_crashes["collision_id"], errors="coerce").astype("float64")
has_id = collision_id.notna()
is_repeat = has_id & collision_id.duplicated()
crash_date = pd.to_datetime(raw_crashes["crash_date"], format=DATE_FORMAT, errors="coerce")
keep = has_id & ~is_repeat & crash_date.dt.year.between(YEAR_START, YEAR_END)
log_rule("crashes", "missing or non-numeric collision_id", "drop", crash_rows_raw, int(has_id.sum()),
         int((~has_id).sum()), "A crash without a key cannot be counted once and only once.")
log_rule("crashes", "duplicate collision_id (first kept)", "drop", int(has_id.sum()), int((has_id & ~is_repeat).sum()),
         int(is_repeat.sum()), "One row per collision; a repeat would double count its casualties.")
log_rule("crashes", f"crash_date unparseable or outside {YEAR_START}-{YEAR_END}", "drop",
         int((has_id & ~is_repeat).sum()), int(keep.sum()), int((has_id & ~is_repeat & ~keep).sum()),
         "Only full calendar years are comparable.")
# Usually nothing is dropped; then the raw frame is used as it is instead of copying 1.5 million rows.
crash_source = raw_crashes if keep.all() else raw_crashes.loc[keep].reset_index(drop=True)
crash_date = crash_date[keep].reset_index(drop=True)

crashes = pd.DataFrame({
    "collision_id": collision_id[keep].astype("int64").to_numpy(),
    "crash_date": crash_date.to_numpy(),
    "year": crash_date.dt.year.astype("int16").to_numpy(),
    "month": crash_date.dt.month.astype("int8").to_numpy(),
})
release("collision_id", "has_id", "is_repeat", "keep")
crash_hour, crash_minute = parse_hour(crash_source["crash_time"])
crashes["hour"] = crash_hour        # same 0..n index as crashes; keeps the nullable Int8 dtype
band = pd.Series(np.nan, index=crashes.index, dtype=object)
for band_name, (first_hour, last_hour) in HOUR_BANDS.items():
    band[crashes["hour"].between(first_hour, last_hour).fillna(False).to_numpy(dtype=bool)] = band_name
crashes["hour_band"] = pd.Categorical(band, categories=list(HOUR_BANDS), ordered=True)
crashes["time_unknown"] = ((crash_hour == 0) & (crash_minute == 0)).fillna(False).to_numpy(dtype=bool)

note("crashes", crashes, "crash_date parsed to datetime; year and month derived", "standardise", 0,
     "Text dates cannot be grouped by year.")
note("crashes", crashes, "crash_time to hour (Int8) and four named hour bands; invalid time left missing",
     "standardise", int(crashes["hour"].isna().sum()), "Time of day is analysed in bands; affected = invalid times.")
note("crashes", crashes, "crash time exactly 0:00 flagged as unknown time", "flag", int(crashes["time_unknown"].sum()),
     "0:00 is the default for a missing time; excluded from hour-of-day work")
assert crashes["collision_id"].is_unique

at_one = int(((crash_hour == 1) & (crash_minute == 0)).sum())
say(f"Rows in {crash_rows_raw:,}, out {len(crashes):,}: the key is complete and unique and every date lies "
    f"between {crashes['crash_date'].min():%Y-%m-%d} and {crashes['crash_date'].max():%Y-%m-%d}. Invalid times: "
    f"{int(crashes['hour'].isna().sum())}. Exactly 0:00 is recorded {int(crashes['time_unknown'].sum()):,} times "
    f"against {at_one:,} at 1:00, so it is flagged. Minutes are rounded by the recorder: "
    f"{pct((crash_minute == 0).sum(), len(crashes)):.1f}% fall on the hour (1.7% if even), so time is "
    f"analysed by band or hour, never by minute.")
release("crash_hour", "crash_minute", "band")

# %% [markdown]
# ### 4.8 Crashes: borough, ZIP code, coordinates and possible double filings
#
# Borough (upper case here, title case in housing) becomes the same category. The housing ZIP
# validator sets blanks, the 10000 placeholder (a fake neighbourhood) and non-NYC codes to missing; the
# row stays. Coordinates at (0, 0) or outside `NYC_BOUNDS` become missing, not clipped (clipping piles
# crashes onto boundary streets). Missing ZIPs are **not filled here**: Section 6 recovers them from
# coordinates, where accuracy can be tested on held-out rows.

# %%
raw_lat, raw_lon = to_number(crash_source["latitude"]), to_number(crash_source["longitude"])
raw_lat_range, raw_lon_range = (raw_lat.min(), raw_lat.max()), (raw_lon.min(), raw_lon.max())
coordinates_missing = int(raw_lat.isna().sum())
crash_lat, crash_lon, crash_zero, crash_outside = validate_coordinates(raw_lat, raw_lon)
crashes["lat"], crashes["lon"] = crash_lat.to_numpy(), crash_lon.to_numpy()
crashes["is_located"] = crashes["lat"].notna().to_numpy()
release("raw_lat", "raw_lon", "crash_lat", "crash_lon")

crashes["borough"] = pd.Categorical(crash_source["borough"].str.strip().str.title(), categories=BOROUGHS)
zip_text = crash_source["zip_code"].str.strip()
clean_zip, crash_zip_borough = standardise_zip(crash_source["zip_code"])
crashes["zip"] = clean_zip          # a Series, so the Arrow string dtype matches housing
zip_rejected = int((zip_text.notna() & clean_zip.isna()).sum())
zip_placeholder = int((zip_text == ZIP_PLACEHOLDER).sum())
crash_zip_disagree = (crash_zip_borough.notna() & crashes["borough"].notna()
                      & (crash_zip_borough != crashes["borough"].astype(object))).to_numpy()
release("zip_text", "clean_zip", "crash_zip_borough")

note("crashes", crashes, "borough to title case, category with the BOROUGHS spelling", "standardise",
     int(crash_source["borough"].notna().sum()), "Upper case here, title case in housing; one spelling needed.")
note("crashes", crashes, "zip_code blank, placeholder 10000 or outside NYC ranges set to missing", "standardise",
     zip_rejected, "Junk codes would form fake neighbourhoods in the ZIP panel; the crash row is kept.")
note("crashes", crashes, "coordinates at (0,0) set to missing", "standardise", crash_zero,
     "A failed geocode leaves this placeholder; it marks no place.")
note("crashes", crashes, "coordinates outside NYC_BOUNDS set to missing", "standardise", crash_outside,
     "Domain rule: a crash in this table cannot lie outside the city; clipping would misplace it.")
note("crashes", crashes, "rows without usable coordinates flagged (is_located = False)", "flag",
     int((~crashes["is_located"]).sum()), "Kept for borough and ZIP totals; excluded from distance analyses.")
note("crashes", crashes, "missing zip left missing at this stage", "flag", int(crashes["zip"].isna().sum()),
     "Recovered from coordinates after integration (Section 6), where accuracy can be tested.")
note("crashes", crashes, "ZIP range borough differs from stated borough (stated borough kept)", "flag",
     int(crash_zip_disagree.sum()), "Checked only; ZIPs on the Brooklyn / Queens line cross the boundary.")

border_zip_boroughs = crashes.loc[crashes["zip"].isin(["11001", "11040"]), "borough"].value_counts()
say(f"ZIP: {zip_rejected:,} codes rejected ({zip_placeholder} of them the 10000 placeholder); "
    f"{n_pct(crashes['zip'].isna().sum(), len(crashes))} rows now have no ZIP and {crashes['zip'].nunique()} "
    f"distinct ZIPs remain. Borough is missing in {n_pct(crashes['borough'].isna().sum(), len(crashes))} rows, "
    f"nearly always together with the ZIP ({int((crashes['borough'].notna() & crashes['zip'].isna()).sum()):,} "
    f"rows have a borough but no ZIP). ZIP range and stated borough disagree in {int(crash_zip_disagree.sum())} "
    f"rows, mostly in {join_and(crashes.loc[crash_zip_disagree, 'zip'].value_counts().index[:3])}. The two ZIPs "
    f"shared with Nassau County carry {int(border_zip_boroughs.sum())} crashes, "
    f"{int(border_zip_boroughs.get('Queens', 0))} of them recorded in Queens.")

# %% [markdown]
# Borough and ZIP go missing together (highways and bridges have no postal address); disagreements sit
# on the Brooklyn-Queens line, so the stated borough is kept. The figure validates the coordinate rule:
# every raw pair's outcome (left) and a sample of cleaned points by borough (right; rings: no borough).

# %%
coordinate_outcomes = pd.Series({
    "kept (inside the city box)": int(crashes["is_located"].sum()),
    "no coordinates": coordinates_missing,
    "outside the city box": crash_outside,
    "at (0, 0): failed geocode": crash_zero,
})
assert coordinate_outcomes.sum() == len(crashes), "every raw coordinate pair has exactly one outcome"
map_sample = crashes.loc[crashes["is_located"], ["lat", "lon", "borough"]].sample(MAP_SAMPLE_ROWS, random_state=SEED)

fig, (ax_outcome, ax_map) = plt.subplots(1, 2, figsize=(12.5, 5.2), gridspec_kw={"width_ratios": [1, 1.1]})
bars = ax_outcome.barh(coordinate_outcomes.index[::-1], coordinate_outcomes.to_numpy()[::-1], height=0.65,
                       color=[PALETTE["crash"], PALETTE["accent"], PALETTE["before"], PALETTE["housing"]])
ax_outcome.bar_label(bars, labels=[f"{v:,}" for v in coordinate_outcomes.to_numpy()[::-1]], padding=4, fontsize=9)
ax_outcome.set_xlim(0, coordinate_outcomes.max() * 1.18)
ax_outcome.xaxis.set_major_locator(mpl.ticker.MaxNLocator(nbins=4))
thousands(ax_outcome, axis="x")
finish(ax_outcome, "Before: what happens to each raw coordinate pair", "Crashes", "")
for borough_name in BOROUGHS:
    points = map_sample[map_sample["borough"] == borough_name]
    ax_map.scatter(points["lon"], points["lat"], s=1, color=BOROUGH_COLORS[borough_name], rasterized=True,
                   label=borough_name, zorder=2)
    ax_map.text(points["lon"].median(), points["lat"].median(), borough_name, ha="center", fontsize=9,
                fontweight="bold", zorder=5, path_effects=[patheffects.withStroke(linewidth=3, foreground="white")])
no_borough = map_sample[map_sample["borough"].isna()]
ax_map.scatter(no_borough["lon"], no_borough["lat"], s=4, facecolors="none", edgecolors="black",
               linewidths=0.25, alpha=0.5, rasterized=True, label="No borough recorded", zorder=1)
map_axes(ax_map)
ax_map.legend(loc="upper left", fontsize=8.5, markerscale=5)
finish(ax_map, f"After: a sample of {MAP_SAMPLE_ROWS:,} located crashes", "Longitude (degrees)", "Latitude (degrees)")
show(fig)
say(f"Raw longitudes ran from {raw_lon_range[0]:.1f} to {raw_lon_range[1]:.1f} and latitudes from "
    f"{raw_lat_range[0]:.1f} to {raw_lat_range[1]:.1f}; after cleaning they run from {crashes['lon'].min():.3f} "
    f"to {crashes['lon'].max():.3f} and {crashes['lat'].min():.3f} to {crashes['lat'].max():.3f}.")

# %% [markdown]
# The rejected pairs would stretch any map across half the globe; cleaned, the sample draws the street
# grid with each colour in its borough. The second figure shows which location fields each year keeps.

# %%
LOCATION_STATES = ["ZIP and coordinates", "Coordinates only", "ZIP only", "Neither"]
has_zip = crashes["zip"].notna().to_numpy()
location_state = np.select([has_zip & crashes["is_located"], ~has_zip & crashes["is_located"], has_zip],
                           LOCATION_STATES[:3], default=LOCATION_STATES[3])
location_by_year = (pd.crosstab(crashes["year"], location_state, normalize="index")
                    .reindex(columns=LOCATION_STATES, fill_value=0) * 100)

fig, ax = plt.subplots(figsize=(9.5, 4.8))
bottom = np.zeros(len(location_by_year))
state_colors = [PALETTE["housing"], PALETTE["placebo"], PALETTE["accent"], PALETTE["before"]]
for state, color in zip(LOCATION_STATES, state_colors):
    ax.bar(location_by_year.index, location_by_year[state], bottom=bottom, color=color, edgecolor="white",
           width=0.8, label=state)
    bottom += location_by_year[state].to_numpy()
for year, share in location_by_year["Coordinates only"].items():
    ax.text(year, location_by_year.loc[year, "ZIP and coordinates"] + share / 2, f"{share:.0f}", ha="center",
            va="center", fontsize=8.5)
ax.set_xticks(location_by_year.index)
ax.set_ylim(0, 100)
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=4)
finish(ax, "Location fields available per crash after cleaning, by year", "Crash year",
       "Share of the year's crashes (%)")
show(fig)
coordinates_only = location_by_year["Coordinates only"]
say(f"Coordinates without a ZIP: {n_pct((location_state == 'Coordinates only').sum(), len(crashes))} crashes, from "
    f"{coordinates_only.min():.0f}% in {int(coordinates_only.idxmin())} to {coordinates_only.max():.0f}% in "
    f"{int(coordinates_only.idxmax())}. Neither field: {n_pct((location_state == 'Neither').sum(), len(crashes))}.")

# %% [markdown]
# The orange band is why ZIP recovery matters: a ZIP panel from the blue band alone would move with
# reporting practice, and dropping these rows would remove a different share each year.
#
# **Possible double filings** agree on date, time, exact coordinates, first vehicle and injured count.
# They are counted but **kept**: two real crashes at a busy junction in one minute look identical.
# Only located rows are compared; without a point, two crashes match on little more than the clock.

# %%
signature = pd.DataFrame({
    "date": crashes["crash_date"], "time": crash_source["crash_time"].array,
    "lat": crashes["lat"], "lon": crashes["lon"], "vehicle": crash_source["vehicle_type_code1"].array,
    "injured": crash_source["number_of_persons_injured"].array,
})[crashes["is_located"]]
possible_duplicates = int(signature.duplicated().sum())
release("signature")
note("crashes", crashes, "same date, time, coordinates, vehicle type and injuries under another id (counted, kept)",
     "flag", possible_duplicates, "Double filing or two real crashes at one junction; they cannot be told apart.")
say(f"{n_pct(possible_duplicates, len(crashes), digits=2)} rows repeat an earlier row's signature under another "
    f"collision_id: too few for the keep-or-drop choice to move any result.")

# %% [markdown]
# ### 4.9 Crashes: casualty counts, and totals that do not match their parts
#
# Casualty columns must be whole and non-negative and become small integers. A blank total is
# **imputed** as the sum of its parts (its definition). A total **below** its parts is raised to them
# (a total cannot hold fewer people than it names). A total **above** is kept: the three roles miss
# e.g. e-scooter riders, so lowering it would delete injured people and assigning a role would be a
# guess. The surplus goes to `other_injured`, so total = ped + cyc + mot + other in every row.

# %%
casualties = pd.DataFrame({short: to_number(crash_source[column]) for column, short in CASUALTY_COLUMNS.items()})
values = casualties.to_numpy()
assert not (values < 0).any() and not (values % 1 > 0).any(), "casualty counts must be whole and >= 0"
casualty_report = {}
for outcome in ["injured", "killed"]:
    part_columns = [f"{prefix}_{outcome}" for prefix in ROAD_USER_PREFIXES]
    assert casualties[part_columns].notna().all().all(), "role counts are expected to be complete"
    parts = casualties[part_columns].sum(axis=1)
    reported = casualties[outcome]
    # Missing total -> sum of parts; below its parts -> raised; above -> kept, surplus stored apart.
    cleaned = np.maximum(reported.fillna(parts), parts)
    # Conservation: people after cleaning = reported + imputed + raised, so no one was removed.
    assert cleaned.sum() == reported.sum() + parts[reported.isna()].sum() + (parts - reported).clip(lower=0).sum()
    casualty_report[outcome] = {"missing": int(reported.isna().sum()), "below": int((reported < parts).sum()),
                                "above": int((reported > parts).sum()),
                                "surplus_people": int((reported - parts).clip(lower=0).sum())}
    casualties[outcome] = cleaned
    casualties[f"other_{outcome}"] = cleaned - parts
assert casualties.max().max() <= np.iinfo(np.int8).max, "a casualty count no longer fits in int8"
for column in [*CASUALTY_COLUMNS.values(), "other_injured"]:
    crashes[column] = casualties[column].astype("int8").to_numpy()
crashes["is_injury_crash"] = ((crashes["injured"].astype("int16") + crashes["killed"]) > 0).to_numpy()
crashes["ped_cyc_harm"] = (crashes[["ped_injured", "ped_killed", "cyc_injured", "cyc_killed"]]
                          .sum(axis=1) > 0).to_numpy()
surplus_rows = (casualties["other_injured"] > 0).to_numpy()
release("casualties", "values")

report = pd.DataFrame(casualty_report).T
note("crashes", crashes, "eight casualty columns to small integers; checked whole and non-negative", "standardise", 0,
     "Counts were text; a negative or fractional value would stop the notebook.")
note("crashes", crashes, "missing persons injured / killed total = sum of pedestrians, cyclists, motorists", "impute",
     int(report["missing"].sum()), "The total is defined as the sum of its parts, so the fill is exact.")
note("crashes", crashes, "persons total below the sum of its parts raised to the sum", "impute",
     int(report["below"].sum()), "A total cannot be smaller than the people it contains.")
note("crashes", crashes, "persons total above the sum of its parts kept; injured surplus stored in "
     "other_injured", "flag", int(report["above"].sum()),
     "The surplus is people outside the three roles (e.g. e-scooter riders); lowering would delete them.")
display(report.rename(columns={"missing": "total missing (imputed)", "below": "total below parts (raised)",
                               "above": "total above parts (kept)", "surplus_people": "people in the surplus"}))

first_vehicle = crash_source["vehicle_type_code1"].str.strip().str.title()
is_micromobility = first_vehicle.isin(["E-Scooter", "E-Bike"]).fillna(False).to_numpy(dtype=bool)
say(f"{pct((crashes['year'].to_numpy()[surplus_rows] > BREAK_YEAR).sum(), surplus_rows.sum()):.0f}% of the "
    f"{surplus_rows.sum():,} surplus rows fall after {BREAK_YEAR}, and an e-scooter or e-bike is the first vehicle "
    f"in {pct((is_micromobility & surplus_rows).sum(), surplus_rows.sum()):.1f}% of them against "
    f"{pct(is_micromobility.sum(), len(crashes)):.2f}% of all crashes. After cleaning: "
    f"{n_pct(crashes['is_injury_crash'].sum(), len(crashes))} injury crashes, "
    f"{int(crashes['ped_cyc_harm'].sum()):,} harming a pedestrian or cyclist, {int(crashes['injured'].sum()):,} "
    f"people injured and {int(crashes['killed'].sum()):,} killed.")

# %% [markdown]
# The surplus follows the reporting change and is rich in e-scooters and e-bikes: a change in who is
# counted, not random error, so it is real people (named `other_`, as cars still dominate). Note that
# `ped_cyc_harm` excludes injured e-scooter and e-bike riders.
#
# ### 4.10 Crashes: extreme injury counts
#
# Dozens injured could be a typo or a bus crash. Tukey's rule is tried, then a domain rule (more than
# `EXTREME_INJURED`). Decision: **flag and keep**; capping would erase real events and break 4.9's identity.

# %%
injury_fence = tukey_upper_fence(crashes["injured"])
injury_only_fence = tukey_upper_fence(crashes.loc[crashes["is_injury_crash"], "injured"])
extreme = (crashes["injured"] > EXTREME_INJURED).to_numpy()
note("crashes", crashes, f"more than {EXTREME_INJURED} injured in one crash (counted, not capped)", "flag",
     int(extreme.sum()), "Bus-scale events are real; capping would erase them and break total = sum of parts.")
display(crashes.loc[extreme, ["crash_date", "borough", "injured", "ped_injured", "mot_injured", "killed"]]
        .assign(first_vehicle=first_vehicle[extreme].to_numpy()).nlargest(8, "injured"))
is_bus = first_vehicle.eq("Bus").fillna(False).to_numpy(dtype=bool)
say(f"Tukey's fence is {injury_fence:.1f} injured on all crashes and {injury_only_fence:.1f} on injury crashes, "
    f"flagging {int((crashes['injured'] > injury_fence).sum()):,} and "
    f"{int((crashes['injured'] > injury_only_fence).sum()):,} ordinary multi-injury crashes. The domain rule "
    f"finds {int(extreme.sum())} crashes with {int(crashes.loc[extreme, 'injured'].sum()):,} injured (maximum "
    f"{int(crashes['injured'].max())}); a bus is the first vehicle in {pct((is_bus & extreme).sum(), extreme.sum()):.0f}% "
    f"of them against {pct(is_bus.sum(), len(crashes)):.1f}% of all crashes.")

# %% [markdown]
# Most crashes injure nobody, so the IQR fence flags ordinary multi-injury crashes (skew, not
# errors). Buses are over-represented among the largest events (the two shares are printed above), kept as reported; "did a crash injure anyone" ignores them.
#
# ### 4.11 Crashes: contributing factors grouped into categories
#
# The first factor is free text with spelling and case variants, numeric codes and rare labels. For
# RQ10 the ordered keywords of `FACTOR_RULES` reduce it to ten groups (a keyword also catches a future
# variant, unlike a label dictionary). Missing, "Unspecified" and numeric codes share one kept group,
# whose size is a finding in itself; an unrecognised label goes to "Other" and is counted.

# %%
factor_text = crash_source["contributing_factor_vehicle_1"]
label_counts = factor_text.value_counts()
normalised = pd.Series(label_counts.index.astype(str), index=label_counts.index).str.strip().str.lower()
label_group = pd.Series(np.nan, index=label_counts.index, dtype=object)
for group_name, pattern in FACTOR_RULES:          # first match wins: only unclaimed labels are assigned
    label_group[normalised.str.contains(pattern, regex=True) & label_group.isna()] = group_name
unrecognised = int(label_group.isna().sum())
label_group = label_group.fillna(FACTOR_FALLBACK)
# Patterns run on the few dozen distinct labels; the result is mapped back to 1.5 million rows.
label_to_group = dict(zip(label_counts.index.astype(str), label_group))
crashes["factor_group"] = pd.Categorical(factor_text.astype(object).map(label_to_group).fillna("Unspecified"),
                                         categories=FACTOR_GROUPS)
factor_missing = int(factor_text.isna().sum())
numeric_rows = int(label_counts[normalised.str.fullmatch(r"\d+")].sum())
note("crashes", crashes, "contributing_factor_vehicle_1 mapped to ten factor groups by ordered keywords",
     "standardise", len(crashes) - factor_missing, "Dozens of labels with spelling variants are too fragmented.")
note("crashes", crashes, "missing factor and numeric junk codes assigned to 'Unspecified'", "standardise",
     factor_missing + numeric_rows, "No factor was recorded; the crash is kept and the gap stays visible.")
assert set(crashes["factor_group"].unique()) == set(FACTOR_GROUPS), "a factor group is empty"

group_counts = crashes["factor_group"].value_counts().sort_values()
fig, ax = plt.subplots(figsize=(9.5, 5.2))
ax.barh(group_counts.index.astype(str), group_counts.to_numpy(), height=0.72,
        color=[PALETTE["before"] if g in ("Unspecified", "Other") else PALETTE["crash"] for g in group_counts.index])
for position, count in enumerate(group_counts):
    ax.text(count + group_counts.max() * 0.01, position, f"{count:,}  ({pct(count, len(crashes)):.1f}%)",
            va="center", fontsize=9, color=PALETTE["neutral"])
ax.set_xlim(0, group_counts.max() * 1.22)
thousands(ax, axis="x")
ax.grid(axis="y", visible=False)
finish(ax, f"{len(label_counts)} raw factor labels reduced to {len(FACTOR_GROUPS)} groups",
       f"Crashes, {YEAR_START} to {YEAR_END}", "Factor group (first contributing factor)",
       note="Grey bars carry no usable cause: not recorded, or a catch-all label.")
show(fig)
say(f"{len(label_counts)} labels ({normalised.nunique()} after trimming and lower-casing) and {factor_missing:,} "
    f"missing values become {len(FACTOR_GROUPS)} groups; numeric codes cover {numeric_rows} rows and "
    f"{unrecognised} labels fell to the fallback. 'Unspecified' holds "
    f"{pct(group_counts['Unspecified'], len(crashes)):.1f}% of crashes, a limit RQ10 has to state.")

# The raw crash text is no longer needed (crash_source is the same object when no row was dropped).
release("raw_crashes", "crash_source", "crash_date", "first_vehicle", "is_micromobility", "is_bus", "factor_text",
        "map_sample", "no_borough", "points", "location_state", "has_zip", "surplus_rows", "extreme")

# %% [markdown]
# ### 4.12 Final shape and invariants
#
# Columns are put in a fixed order. Raw columns no later section reads are not carried forward:
# finer housing identifiers with no crash counterpart (tax lot, census tract, council district,
# community board), the second coordinate pair, the status fields and the two source completion
# dates (merged into `completion_date`); for crashes, street name, second factor and vehicle type,
# used above for checks only. Flags that were only counted (possible duplicates, extreme injuries)
# live in the log rather than as columns.

# %%
HOUSING_COLUMN_ORDER = [
    "housing_id", "project_id", "building_id", "project_name", "address",
    "borough", "zip", "lat", "lon", "is_confidential", "is_located",
    "project_start_date", "completion_date", "start_year", "completion_year", "is_completed",
    "completion_before_start", "same_day_completion", "construction_type", *UNIT_COLUMNS,
    "deep_affordable_units", "deep_affordable_share", "is_size_outlier", "size_band",
]
CRASH_COLUMN_ORDER = [
    "collision_id", "crash_date", "year", "month", "hour", "hour_band", "time_unknown",
    "borough", "zip", "lat", "lon", "is_located",
    "injured", "killed", "ped_injured", "ped_killed", "cyc_injured", "cyc_killed",
    "mot_injured", "mot_killed", "other_injured", "is_injury_crash", "ped_cyc_harm", "factor_group",
]
assert set(HOUSING_COLUMN_ORDER) == set(housing.columns), set(HOUSING_COLUMN_ORDER) ^ set(housing.columns)
assert set(CRASH_COLUMN_ORDER) == set(crashes.columns), set(CRASH_COLUMN_ORDER) ^ set(crashes.columns)
housing, crashes = housing[HOUSING_COLUMN_ORDER], crashes[CRASH_COLUMN_ORDER]
note("housing", housing, "raw columns not carried forward under their raw name (typed, renamed or unused)", "drop",
     len(set(raw_housing.columns) - set(housing.columns)), "Affected counts columns, not rows.")
note("crashes", crashes, "raw text columns not carried forward under their raw name (typed, renamed or unused)",
     "drop", len(set(crash_raw_names) - set(crashes.columns)), "Affected counts columns, not rows.")


def logged_drops(dataset):
    """Rows removed by the logged rules of one dataset."""
    return sum(entry["rows_before"] - entry["rows_after"] for entry in CLEANING_LOG if entry["dataset"] == dataset)


# Row conservation: every row that left was removed by a logged rule; keys stay unique.
assert len(housing) == len(raw_housing) - logged_drops("housing")
assert len(crashes) == crash_rows_raw - logged_drops("crashes")
assert housing["housing_id"].is_unique and crashes["collision_id"].is_unique
assert list(housing["borough"].cat.categories) == BOROUGHS == list(crashes["borough"].cat.categories)
assert housing["zip"].dtype == crashes["zip"].dtype

# %% [markdown]
# ### 4.13 Cleaning log and before/after summary
#
# Every rule in the order it ran; `affected` counts rows unless the rule says cells or columns.

# %%
cleaning_log_table = pd.DataFrame(CLEANING_LOG)
with pd.option_context("display.max_colwidth", None, "display.max_rows", 100):
    display(cleaning_log_table)
display(cleaning_log_table.assign(rows_dropped=cleaning_log_table["rows_before"] - cleaning_log_table["rows_after"])
        .groupby(["dataset", "action"]).agg(rules=("rule", "size"), rows_dropped=("rows_dropped", "sum")))

before_after = pd.DataFrame({
    "rows before": [len(raw_housing), crash_rows_raw], "rows after": [len(housing), len(crashes)],
    "columns before": [raw_housing.shape[1], crash_columns_raw], "columns after": [housing.shape[1], crashes.shape[1]],
    "memory before (MB)": [memory_mb(raw_housing), crash_memory_raw],
    "memory after (MB)": [memory_mb(housing), memory_mb(crashes)],
    "missing cells after": [int(housing.isna().sum().sum()), int(crashes.isna().sum().sum())],
}, index=["housing", "crashes"]).round(1)
display(before_after)
remaining = pd.concat({"housing": housing.isna().sum(), "crashes": crashes.isna().sum()})
display(remaining[remaining > 0].rename("missing after cleaning").to_frame())
say(f"{len(cleaning_log_table)} rules logged; {logged_drops('housing')} housing and {logged_drops('crashes')} crash "
    f"rows dropped, leaving {len(housing):,} and {len(crashes):,}. The typed crash frame takes "
    f"{before_after.loc['crashes', 'memory after (MB)']:.0f} MB against "
    f"{before_after.loc['crashes', 'memory before (MB)']:.0f} MB as raw text.")

# %% [markdown]
# No row was lost: the keys were sound and every other problem was standardised or flagged. Missing
# values remain only where the information never existed. The crash frame shrinks because counts are
# one-byte integers and labels categories. Raw crashes were released after 4.11, so re-running
# Section 4 needs Section 2.1 first.

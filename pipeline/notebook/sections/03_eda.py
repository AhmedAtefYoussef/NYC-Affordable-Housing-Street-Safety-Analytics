# %% [markdown]
# ## 3. Exploratory data analysis
#
# This section looks at both tables as loaded, before any cleaning, to find what is in them, what
# is wrong with them and what that means for joining them. Every rule in Section 4 answers a
# problem seen here first. The raw frames hold text only, so each table gets a temporary numeric
# view; the views are deleted at the end and nothing defined here is used later. Text that does not
# convert becomes missing in the view and is counted, which is itself a finding.

# %%
# --- Constants and helpers used only in this section ---------------------------------------------
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
INJURY_COLUMNS = ["number_of_persons_injured", "number_of_persons_killed",
                  "number_of_pedestrians_injured", "number_of_pedestrians_killed",
                  "number_of_cyclist_injured", "number_of_cyclist_killed",
                  "number_of_motorist_injured", "number_of_motorist_killed"]
INJURY_PARTS = ["number_of_pedestrians_injured", "number_of_cyclist_injured", "number_of_motorist_injured"]
TYPE_COLORS = {"New Construction": PALETTE["housing"], "Preservation": PALETTE["placebo"]}


def to_date(text):
    """Parse a raw ISO timestamp column; anything that does not match the format becomes NaT."""
    return pd.to_datetime(text, format=DATE_FORMAT, errors="coerce")


def column_profile(frame):
    """Per-column profile of a raw table: dtype as loaded, missing count and share, distinct values."""
    table = missing_table(frame)
    table["distinct"] = frame.nunique().reindex(table.index)
    return table.rename(columns={"dtype": "dtype as loaded", "missing_pct": "missing %"}).round(1)


def housing_view(raw):
    """Numeric and datetime view of the raw housing table."""
    view = pd.DataFrame(index=raw.index)
    view["is_confidential"] = (raw["project_name"].str.strip().str.upper() == CONFIDENTIAL_NAME).fillna(False).to_numpy()
    view["construction_type"] = raw["reporting_construction_type"].astype(object)
    for column in UNIT_COLUMNS + ["latitude", "longitude"]:
        view[column] = to_number(raw[column], strict=False)
    for column in ["project_start_date", "project_completion_date", "building_completion_date"]:
        view[column] = to_date(raw[column])
    # The building date is the precise one; the project date stands in when it is absent.
    view["completion_date"] = view["building_completion_date"].fillna(view["project_completion_date"])
    return view


def crash_view(raw):
    """Lean numeric view of the 1.5M-row crash table: only what the charts and facts need."""
    date = to_date(raw["crash_date"])
    assert date.notna().all(), "a crash date does not follow the API date format"
    view = pd.DataFrame({"year": date.dt.year.astype("int16"), "weekday": date.dt.dayofweek.astype("int8")})
    view["hour"], minute = parse_hour(raw["crash_time"])
    view["on_the_hour"] = (minute == 0).to_numpy()
    casualties = pd.DataFrame({c: to_number(raw[c], strict=False).astype("float32") for c in INJURY_COLUMNS})
    view["injured"] = casualties["number_of_persons_injured"]
    view["is_injury"] = casualties.fillna(0).sum(axis=1).gt(0).to_numpy()
    # Compared only where the total is recorded; a missing total is counted as a gap, not a mismatch.
    view["parts_differ"] = ((casualties["number_of_persons_injured"] != casualties[INJURY_PARTS].sum(axis=1))
                            & casualties["number_of_persons_injured"].notna()).to_numpy()
    lat, lon = to_number(raw["latitude"], strict=False), to_number(raw["longitude"], strict=False)
    view["coord_missing"] = (lat.isna() | lon.isna()).to_numpy()
    view["coord_zero"] = ((lat == 0) & (lon == 0)).to_numpy()
    in_box = lat.between(*NYC_BOUNDS["lat"]) & lon.between(*NYC_BOUNDS["lon"])
    view["coord_unusable"] = (~in_box).to_numpy()          # missing, (0, 0) and outside the city box
    view["zip_missing"] = raw["zip_code"].isna().to_numpy()
    view["borough_missing"] = raw["borough"].isna().to_numpy()
    return view


def spelling_report(frame, table_name, columns):
    """Distinct values as written vs after trimming and case-folding, plus stray spaces and digit-only labels."""
    rows = []
    for column in columns:
        text = frame[column].dropna()
        rows.append({"table": table_name, "column": column, "distinct as written": text.nunique(),
                     "after trim + case-fold": text.str.strip().str.casefold().nunique(),
                     "padded with spaces": int((text != text.str.strip()).sum()),
                     "digit-only labels": int(text.str.fullmatch(r"\d+").sum())})
    return pd.DataFrame(rows).set_index(["table", "column"])


eda_housing = housing_view(raw_housing)
eda_crashes = crash_view(raw_crashes)
housing_profile, crash_profile = column_profile(raw_housing), column_profile(raw_crashes)

# %% [markdown]
# ### 3.1 Descriptive statistics
#
# One profile per table (every column was loaded as text, so dtype shows the loading choice, not the
# content), then the summary of the numeric fields. Reading everything as text and converting
# explicitly was chosen over letting pandas guess types: guessing turns ZIP codes and identifiers
# into decimals as soon as one value is missing, and a decimal ZIP no longer matches a text ZIP.

# %%
say(f"**Housing:** {raw_housing.shape[0]:,} rows x {raw_housing.shape[1]} columns, "
    f"{int((housing_profile['missing'] > 0).sum())} columns with gaps. **Crashes:** "
    f"{raw_crashes.shape[0]:,} rows x {raw_crashes.shape[1]} columns, "
    f"{int((crash_profile['missing'] > 0).sum())} columns with gaps.")
show_table(housing_profile, rows=60)
show_table(crash_profile, rows=30)

numeric = pd.DataFrame({"housing total_units": eda_housing["total_units"].reset_index(drop=True),
                        "crash persons injured": eda_crashes["injured"].reset_index(drop=True)})
describe = numeric.describe(percentiles=[0.5, 0.95, 0.99]).T.round(2)
describe.insert(0, "rows with a value", describe.pop("count").astype(int))
show_table(describe)

# %% [markdown]
# ### 3.2 Missing values (chart 1)
#
# Both tables are shown on the same 0 to 100% scale. The housing gaps are of three kinds (unit
# counts, location fields, dates) and the crash gaps are concentrated in location.

# %%
fig, axes = plt.subplots(1, 2, figsize=(13, 7), sharex=True, gridspec_kw={"width_ratios": [1.6, 1]})
for ax, table, title in [(axes[0], housing_profile, "Housing"), (axes[1], crash_profile, "Crashes")]:
    gaps = table[table["missing"] > 0].sort_values("missing %")
    bars = ax.barh(gaps.index, gaps["missing %"], color=PALETTE["housing" if title == "Housing" else "crash"])
    ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=8.5, color=PALETTE["neutral"])
    ax.grid(axis="y", visible=False)
    finish(ax, f"{title}: columns with missing values", "rows with no value (%)", "")
axes[0].set_xlim(0, 112)
show(fig)

# %% [markdown]
# Most housing unit columns are blank for most rows, the location fields share one gap, and in the
# crash table ZIP code and borough go missing together.

# %%
housing_blank = eda_housing[UNIT_COLUMNS].isna()
filled = eda_housing[UNIT_COLUMNS].fillna(0)
located = eda_housing["latitude"].notna() & eda_housing["longitude"].notna()
hidden = eda_housing["is_confidential"]
units = eda_housing["total_units"]
same_day = int((eda_housing["completion_date"] == eda_housing["project_start_date"]).sum())
repeat_ids = int(raw_housing["building_id"].dropna().duplicated().sum())
say(f"**Housing facts (computed).** {n_pct(housing_blank.to_numpy().sum(), housing_blank.size)} of unit cells "
    f"are blank and only {int((eda_housing[UNIT_COLUMNS] == 0).to_numpy().sum())} hold a written zero; with blanks "
    f"read as zero the income bands add up to `all_counted_units` in "
    f"{n_pct((filled[INCOME_UNIT_COLUMNS].sum(axis=1) == filled['all_counted_units']).sum(), len(filled))} of rows, "
    f"so blank means zero. **Confidential** rows: {n_pct(hidden.sum(), len(hidden))}, holding "
    f"{n_pct(units[hidden].sum(), units.sum())} of units; {int((~hidden & ~located).sum())} other rows lack "
    f"coordinates. **{repeat_ids}** rows repeat a `building_id`. "
    f"{n_pct(same_day, len(eda_housing))} of buildings complete on their project start day, and {int((eda_housing['completion_date'] > pd.Timestamp(f'{YEAR_END}-12-31')).sum())} "
    f"completion dates fall after {YEAR_END}.")

crash_year = eda_crashes.groupby("year")
say(f"**Crash facts (computed).** ZIP and borough both missing in "
    f"{n_pct((eda_crashes['zip_missing'] & eda_crashes['borough_missing']).sum(), len(eda_crashes))} of crashes. "
    f"Coordinates are missing in {n_pct(eda_crashes['coord_missing'].sum(), len(eda_crashes))} and "
    f"{eda_crashes['coord_zero'].sum():,} sit at (0, 0). Persons injured differs from the sum of its three "
    f"parts in {eda_crashes['parts_differ'].sum():,} crashes. "
    f"{n_pct((raw_crashes['contributing_factor_vehicle_1'] == 'Unspecified').sum(), raw_crashes['contributing_factor_vehicle_1'].notna().sum())} "
    f"of recorded first factors are `Unspecified`. {n_pct(eda_crashes['on_the_hour'].sum(), eda_crashes['hour'].notna().sum())} "
    f"of crashes are logged exactly on the hour.")

# %% [markdown]
# ### 3.3 Housing: building size, completions and location (charts 2 to 4)
#
# `total_units` drives several questions, so its shape matters. The histogram uses a log axis
# because almost every building would otherwise fall in the first bar. It marks the median and the
# Tukey upper fence (third quartile + 1.5 x IQR), the usual outlier rule.

# %%
sizes = units.dropna()
fence = tukey_upper_fence(sizes)
fig, ax = plt.subplots(figsize=(9.5, 4.4))
ax.hist(sizes, bins=integer_log_bins(sizes.max()), color=PALETTE["housing"], edgecolor="white")
ax.set_xscale("log")
thousands(ax, axis="x")
ax.axvline(sizes.median(), color=PALETTE["neutral"], linestyle=":", label=f"median = {sizes.median():.0f}")
ax.axvline(fence, color=PALETTE["accent"], linestyle="--", label=f"IQR fence = {fence:.0f}")
ax.legend()
finish(ax, "Housing: most buildings are small, a few are very large",
       "total units in the building (log scale)", "buildings")
show(fig)
say(f"{n_pct((sizes > fence).sum(), len(sizes))} of buildings lie above the fence and the largest has "
    f"{sizes.max():,.0f} units. Large buildings are real and are what RQ4 needs, so Section 4 flags them and "
    f"does not remove them.")

# %% [markdown]
# Completions per year, split by type. A building counts in the year of its completion date.

# %%
by_year = (eda_housing.groupby([eda_housing["completion_date"].dt.year, "construction_type"]).size()
           .unstack(fill_value=0))
fig, ax = plt.subplots(figsize=(9.5, 4.2))
bottom = np.zeros(len(by_year))
for name, color in TYPE_COLORS.items():
    ax.bar(by_year.index, by_year[name], bottom=bottom, color=color, label=name)
    bottom += by_year[name].to_numpy()
ax.legend()
finish(ax, "Housing: buildings completed per year", "completion year", "buildings",
       note=f"Years after {YEAR_END} are planned or recent completion dates.")
show(fig)

# %% [markdown]
# Map of the buildings that have coordinates. Confidential rows have none, so they are absent
# here; Section 4 keeps them for borough totals only.

# %%
in_city = located & eda_housing["latitude"].between(*NYC_BOUNDS["lat"]) & eda_housing["longitude"].between(*NYC_BOUNDS["lon"])
fig, ax = plt.subplots(figsize=(7.5, 7.5))
for name, color in TYPE_COLORS.items():
    points = eda_housing[in_city & (eda_housing["construction_type"] == name)]
    ax.scatter(points["longitude"], points["latitude"], s=4, alpha=0.5, color=color,
               label=f"{name} ({len(points):,})")
ax.legend(markerscale=3, loc="upper left")
map_axes(ax)
finish(ax, f"Housing: {in_city.sum():,} located buildings", "longitude", "latitude")
show(fig)

# %% [markdown]
# ### 3.4 Crashes: location gaps, the 2020 break, time of day and outliers (charts 5 to 8)
#
# The first chart splits two location gaps by year: crashes without a ZIP code, and crashes
# without usable coordinates (missing, at (0, 0) or outside the city box). They decide which
# crashes can take part in the ZIP join and the distance join.

# %%
gap_by_year = pd.DataFrame({
    "no ZIP code": crash_year["zip_missing"].mean() * 100,
    "no usable coordinates": crash_year["coord_unusable"].mean() * 100})
fig, ax = plt.subplots(figsize=(9, 4.4))
for column, color in [("no ZIP code", PALETTE["crash"]), ("no usable coordinates", PALETTE["housing"])]:
    ax.plot(gap_by_year.index, gap_by_year[column], marker="o", color=color, label=column)
ax.set_xticks(gap_by_year.index)
ax.set_ylim(0)
ax.legend()
finish(ax, "Crashes: the share without a ZIP code or coordinates changes with the year",
       "crash year", "crashes (%)")
show(fig)
say(f"No ZIP code: {gap_by_year['no ZIP code'].iloc[0]:.1f}% in {YEAR_START} and "
    f"{gap_by_year['no ZIP code'].iloc[-1]:.1f}% in {YEAR_END}. No usable coordinates: "
    f"{gap_by_year['no usable coordinates'].loc[YEAR_START]:.1f}% in {YEAR_START} against "
    f"{gap_by_year['no usable coordinates'].loc[YEAR_START + 1:].min():.1f}% to "
    f"{gap_by_year['no usable coordinates'].loc[YEAR_START + 1:].max():.1f}% later. A gap that varies by year "
    f"would bias any before/after count, so Section 6.1 recovers ZIP codes from coordinates and checks the result.")

# %% [markdown]
# **The 2020 reporting break.** The outcome of the whole project is the crash count, so its
# definition has to be stable over time. The chart compares all crashes with injury crashes (at
# least one person injured or killed).

# %%
yearly = pd.DataFrame({"all crashes": crash_year.size(), "injury crashes": crash_year["is_injury"].sum()})
fig, ax = plt.subplots(figsize=(9, 4.4))
ax.plot(yearly.index, yearly["all crashes"], marker="o", color=PALETTE["control"], label="all crashes")
ax.plot(yearly.index, yearly["injury crashes"], marker="o", color=PALETTE["crash"], label="injury crashes")
ax.axvline(BREAK_YEAR - 0.5, color=PALETTE["neutral"], linestyle="--", linewidth=1)
ax.set_xticks(yearly.index)
ax.set_ylim(0)
thousands(ax)
ax.legend()
finish(ax, f"Crashes: all crashes roughly halve in {BREAK_YEAR}, injury crashes fall much less",
       "crash year", "crashes per year", note=f"Dashed line: start of {BREAK_YEAR}.")
show(fig)
drop_all = pct(yearly.loc[BREAK_YEAR, "all crashes"], yearly.loc[BREAK_YEAR - 1, "all crashes"]) - 100
drop_injury = pct(yearly.loc[BREAK_YEAR, "injury crashes"], yearly.loc[BREAK_YEAR - 1, "injury crashes"]) - 100
say(f"From {BREAK_YEAR - 1} to {BREAK_YEAR} all crashes change by {drop_all:+.1f}% and injury crashes by "
    f"{drop_injury:+.1f}%. The part of the fall beyond the injury crashes fits a change in reporting of "
    f"crashes without injury, which has nothing to do with housing (the pandemic fall in traffic affects both), so **the outcome used throughout is the injury crash**. Counting all "
    f"crashes would let a city-wide reporting change look like a local effect.")

# %% [markdown]
# Crashes by weekday and hour. The 0:00 column is not a rush of midnight crashes: 0:00 is the
# value stored when the time is unknown (see the count below).

# %%
valid = eda_crashes["hour"].notna()
cells = np.bincount(eda_crashes.loc[valid, "weekday"].astype(int) * 24 + eda_crashes.loc[valid, "hour"].astype(int),
                    minlength=7 * 24).reshape(7, 24)
fig, ax = plt.subplots(figsize=(11, 3.8))
sns.heatmap(pd.DataFrame(cells, index=WEEKDAYS), cmap=SEQUENTIAL_CMAP, ax=ax,
            cbar_kws={"label": "crashes", "format": mpl.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}")})
ax.set_yticklabels(WEEKDAYS, rotation=0)
finish(ax, "Crashes by weekday and hour: the 0:00 column is the unknown-time default", "hour of day", "")
show(fig)
midnight, one_am = (int((raw_crashes["crash_time"] == t).sum()) for t in ("0:00", "1:00"))
say(f"{midnight:,} crashes are stamped 0:00 against {one_am:,} at 1:00. Section 4 flags them as unknown "
    f"time and keeps them out of every hour-of-day result.")

# %% [markdown]
# Persons injured per crash, on a log count axis, to see how far the tail reaches. More than
# `EXTREME_INJURED` people cannot fit in a few cars, so the tail marks bus-scale events.

# %%
injured_counts = eda_crashes["injured"].dropna().astype(int).value_counts().sort_index()
fig, ax = plt.subplots(figsize=(9, 4.2))
ax.bar(injured_counts.index, injured_counts.values, color=PALETTE["crash"], width=0.8)
ax.set_yscale("log")
ax.axvline(EXTREME_INJURED + 0.5, color=PALETTE["neutral"], linestyle="--", linewidth=1,
           label=f"more than {EXTREME_INJURED} injured")
ax.legend()
finish(ax, "Crashes: persons injured per crash", "persons injured in the crash", "crashes (log scale)")
show(fig)
say(f"{int((eda_crashes['injured'] > EXTREME_INJURED).sum())} crashes injure more than {EXTREME_INJURED} people "
    f"(maximum {int(eda_crashes['injured'].max())}). They are real events, so Section 4 flags and does not cap them "
    f"(Section 4.10 counts one more extreme crash, because 4.9 raises some injury totals).")

# %% [markdown]
# ### 3.5 Category spellings and duplicates
#
# Categorical columns are compared as written and after trimming and case-folding. Differences
# between the two counts mean the same category is spelled in several ways and would split a
# group-by. The two tables also write the borough differently, which matters for the join.

# %%
spellings = pd.concat([
    spelling_report(raw_housing, "housing", ["borough", "reporting_construction_type", "extended_affordability_status"]),
    spelling_report(raw_crashes, "crashes", ["borough", "contributing_factor_vehicle_1", "vehicle_type_code1"])])
show_table(spellings)
zip_text = raw_crashes["zip_code"].dropna()
not_five_digits = int((~zip_text.str.fullmatch(r"\d{5}")).sum())
say(f"Borough is written in title case in housing (e.g. `{raw_housing['borough'].dropna().iloc[0]}`) and in upper case "
    f"in crashes (e.g. `{raw_crashes['borough'].dropna().iloc[0]}`). Crash ZIP codes: "
    f"{n_pct((zip_text == ZIP_PLACEHOLDER).sum(), len(raw_crashes), digits=2)} are the placeholder `{ZIP_PLACEHOLDER}` and "
    f"{not_five_digits:,} are not five digits.")

duplicates = pd.DataFrame({
    "rows": [len(raw_housing), len(raw_crashes)],
    "full-row duplicates": [int(raw_housing.duplicated().sum()), int(raw_crashes.duplicated().sum())],
    "repeated key": [repeat_ids, int(raw_crashes["collision_id"].duplicated().sum())]},
    index=["housing (key: building_id)", "crashes (key: collision_id)"])
show_table(duplicates)

# %% [markdown]
# ### 3.6 Issues found and how Section 4 handles them

# %%
issues = pd.DataFrame([
    ("Housing: confidential rows with no address, ZIP or coordinates",
     n_pct(hidden.sum(), len(hidden)), "Flagged and kept for borough totals; excluded from ZIP and distance joins."),
    ("Housing: unit columns blank where the value is zero",
     n_pct(housing_blank.to_numpy().sum(), housing_blank.size), "Blank filled with 0; identity checks confirm the sums."),
    ("Housing: repeated building_id", f"{repeat_ids:,} rows", "Duplicate rows dropped so units are not double counted."),
    ("Housing: heavy right tail in building size", n_pct((sizes > fence).sum(), len(sizes)),
     "Flagged above the IQR fence, not removed."),
    ("Housing: completion on the start day",
     n_pct(same_day, len(eda_housing)), "Flagged: no observable construction period."),
    ("Crashes: ZIP code missing (and a few placeholder codes)", n_pct(eda_crashes["zip_missing"].sum(), len(eda_crashes)),
     "Set to missing, recovered from coordinates after the join (Section 6)."),
    ("Crashes: coordinates missing, at (0, 0) or outside the city box", n_pct(eda_crashes["coord_unusable"].sum(), len(eda_crashes)),
     "Set to missing and flagged; used for borough and ZIP totals only."),
    (f"Crashes: reporting break in {BREAK_YEAR}", f"{drop_all:+.1f}% all vs {drop_injury:+.1f}% injury",
     "Outcome restricted to injury crashes."),
    ("Crashes: 0:00 is the unknown-time default", f"{midnight:,} at 0:00 vs {one_am:,} at 1:00",
     "Flagged and excluded from hour-of-day work."),
    ("Crashes: injured total differs from sum of parts", f"{eda_crashes['parts_differ'].sum():,} crashes",
     "Total raised to the sum when smaller; surplus stored separately and flagged."),
    ("Crashes: very large injury counts", f"{int((eda_crashes['injured'] > EXTREME_INJURED).sum())} crashes",
     "Flagged, not capped."),
    ("Categories: borough case differs; factor labels vary", f"{len(spellings)} columns compared",
     "One spelling per category; labels standardised."),
], columns=["issue", "size", "handling in Section 4"]).set_index("issue")
show_table(issues, rows=15)

# %%
# Release the temporary views: nothing later in the notebook uses them.
release("eda_housing", "eda_crashes", "numeric", "crash_year", "cells", "valid",
        "housing_blank", "filled", "located", "hidden", "units", "in_city", "by_year")

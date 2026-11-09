# Data dictionary

This file describes the tables of the notebook after each stage and the files the website reads in `app/data/`. The notebook builds its tables in memory, so the code in `pipeline/notebook/sections/` is the authority if this file and the code disagree. The file list, row counts and column lists of `app/data/` were checked against the files themselves, and the notebook columns against the section sources.

Conventions: `zip` is a 5-character string. `year` is a calendar year. A row is "located" if it has valid coordinates. An injury crash is a crash with at least one person injured or killed. Types written with a capital letter (`Int16`, `Int32`) are pandas integers that allow missing values.

## 1. Source datasets

| Dataset | ID | Page | API (CSV) | One row is |
|---|---|---|---|---|
| Affordable Housing Production by Building | `hg8x-zxpr` | https://data.cityofnewyork.us/d/hg8x-zxpr | https://data.cityofnewyork.us/resource/hg8x-zxpr.csv | one building of a city-financed project |
| Motor Vehicle Collisions - Crashes | `h9gi-nx95` | https://data.cityofnewyork.us/d/h9gi-nx95 | https://data.cityofnewyork.us/resource/h9gi-nx95.csv | one police-reported collision |

The local copies were saved on 10 October 2026 (`meta.json`, `data_as_of.raw_files_saved`). The housing file has 9,551 rows. The crash copy keeps crashes from 2016-01-01 to 2025-12-31 (1,504,722 rows) and 19 of the 29 columns: `collision_id`, `crash_date`, `crash_time`, `borough`, `zip_code`, `latitude`, `longitude`, `on_street_name`, the injured and killed counts for persons, pedestrians, cyclists and motorists, `contributing_factor_vehicle_1`, `contributing_factor_vehicle_2` and `vehicle_type_code1`. The latest crash in the copy is dated 2025-12-31 and the latest housing completion 2026-08-21.

## 2. Cleaned tables (Section 4 of the notebook)

### `housing`: 9,551 rows, 41 columns

Unique on (`project_id`, `building_id`) and on `housing_id`.

| Group | Columns |
|---|---|
| Keys and names | `housing_id` (int32, 0 to n-1, assigned by the notebook), `project_id`, `building_id` (missing for confidential rows), `project_name`, `address` |
| Geography | `borough` (five names, never missing), `zip` (5 characters or missing), `lat`, `lon`, `is_confidential`, `is_located` |
| Dates | `project_start_date`, `completion_date` (the building's date, else the project's date), `start_year`, `completion_year` (missing if not completed), `is_completed`, `completion_before_start`, `same_day_completion` |
| Type | `construction_type` (New Construction or Preservation) |
| Units (blanks set to 0) | six income bands (`extremely_low_income_units`, `very_low_income_units`, `low_income_units`, `moderate_income_units`, `middle_income_units`, `other_income_units`), bedroom counts (`studio_units`, `_1_br_units` to `_6_br_units`, `unknown_br_units`), `counted_rental_units`, `counted_homeownership_units`, `all_counted_units`, `total_units` |
| Derived | `deep_affordable_units` (extremely low plus very low income units), `deep_affordable_share` (missing where no units are counted), `is_size_outlier` (above the Tukey fence), `size_band` (ordered: 1-4, 5-19, 20-49, 50-149, 150+) |

`all_counted_units` is the units the programme counts as affordable. `total_units` is every unit in the building, market-rate units included. Raw columns that no later step reads (tax lot, census tract, council district, community board, the second coordinate pair, status fields, the two source completion dates) are not carried forward.

### `crashes`: 1,504,722 rows, 24 columns after cleaning

Unique on `collision_id`.

| Group | Columns |
|---|---|
| Time | `collision_id`, `crash_date`, `year`, `month`, `hour` (missing if the time is invalid), `hour_band` (ordered: Night 0-5, Morning 6-11, Afternoon 12-17, Evening 18-23), `time_unknown` (the time is exactly 0:00, the default for a missing time; excluded from hour-of-day work) |
| Geography | `borough` (category, may be missing), `zip` (string or missing), `lat`, `lon` (missing if absent, at (0, 0) or outside the NYC box), `is_located` |
| Casualties | `injured`, `killed`, `ped_injured`, `ped_killed`, `cyc_injured`, `cyc_killed`, `mot_injured`, `other_injured` |
| Flags | `is_injury_crash`, `ped_cyc_harm` (a pedestrian or cyclist was injured or killed) |
| Category | `factor_group`, never missing: Unspecified, Pedestrian or cyclist error, Road or environment, Vehicle defect, Impairment or medical, Distraction, Speed or aggressive driving, Failure to yield or obey, Improper manoeuvre, Other |

`mot_killed` is cleaned and used inside the casualty checks but is not carried forward as a column. `other_injured` holds the part of the persons injured total that the pedestrian, cyclist and motorist counts do not explain. `ped_cyc_harm` leaves out riders of e-scooters and e-bikes, who fall into that remainder. Possible duplicates and crashes with more than 10 injured are counted in the cleaning log and not kept as columns.

The notebook's cleaning log (49 entries, shown in `app/data/cleaning_log.parquet`) has columns `dataset` (housing, crashes or zip panel), `rule`, `action` (drop, impute, flag or standardise), `rows_before`, `rows_after`, `affected` and `reason`.

## 3. Integrated tables (Sections 5 and 6)

### `zip_year`: 1,720 rows

One row per ZIP and year for 172 ZIP codes and the 10 years 2016 to 2025, with no gaps. Unique on (`zip`, `year`).

| Group | Columns |
|---|---|
| Keys | `zip`, `year`, `borough` |
| Housing completed in the year (int32) | `buildings_completed`, `units_completed` (all units), `affordable_units_completed`, `deep_affordable_units`, `new_construction_units`, `preservation_units` |
| Stock since 2014 (int32) | `cum_affordable_units`, `cum_deep_affordable_units` |
| Crashes in the year (int32) | `crashes`, `injury_crashes`, `persons_injured`, `persons_killed`, `ped_cyc_crashes`, and `crashes_zip_imputed`, `injury_crashes_zip_imputed` (the part whose ZIP was recovered from coordinates) |

A building completed again under a later project is counted once in the unit columns. `new_construction_units` and `preservation_units` are affordable units, so they add up to `affordable_units_completed`.

### `sites`: 7,593 rows

One row per located housing row. `site_id` is the row position (0 to n-1).

Columns: `site_id`, `cluster_id` (connected group of sites within 250 m of each other), `housing_id`, `project_id`, `building_id`, `project_name`, `borough`, `zip`, `lat`, `lon`, `start_year`, `completion_year`, `is_completed`, `same_day_completion`, `completion_before_start`, `construction_type`, `total_units`, `all_counted_units`, `deep_affordable_units`, `deep_affordable_share`, `size_band`, `is_size_outlier` and `n_sites_within_buffer` (other sites within 250 m).

### `site_year`: 75,930 rows

One row per site and year: `site_id`, `year` and the counts of `crashes`, `injury_crashes`, `ped_cyc_crashes` and `persons_injured` within 250 m. A crash near several sites appears in each site's count, so these counts must not be summed across sites.

### `event_panel`: 93,618 rows

One row per site, cohort (completion year 2019 to 2022) and relative year (-3 to +3). Columns: `site_id`, `cluster_id`, `cohort`, `group` (treated or comparison), `rel_year`, `year`, the four counts of `site_year`, `contaminated`, `near_completion_in_window`, `near_earlier_completion` (the screen of Section 5.4), and the site's `completion_year`, `construction_type`, `borough`, `size_band` and `total_units`. The analyses drop the rows where `contaminated` is true. A comparison site appears once for every cohort it serves.

### `crashes` after integration: 27 columns

The 24 cleaned columns, with `zip` and `borough` filled where possible, plus these:

| Column | Meaning |
|---|---|
| `zip_imputed` | The ZIP was recovered from coordinates in Section 6 |
| `in_zip_panel` | The crash's ZIP is one of the 172 panel ZIP codes |
| `near_site_id` | The nearest site within 250 m (nullable integer; missing if none). Ties go to the earlier completion, then the lower `site_id` |

`city_year` has 10 rows (one per year) with `crash_index` and `injury_crash_index`, both equal to 100 in 2019.

## 4. Website data: `app/data/`

The files hold counts, not rows of the source tables. Parquet files use small integer types and categories. Their total size is about 3.3 MB (`meta.json`, `files`).

### The seven counts

Every crash table carries these counts, one per option of the site's "who was harmed" filter.

| Column | Counts crashes in which |
|---|---|
| `n_all` | any crash was reported |
| `n_injury` | at least one person was injured or killed |
| `n_pedcyc` | a pedestrian or cyclist was injured or killed |
| `n_ped`, `n_cyc`, `n_mot` | a pedestrian, a cyclist or a motorist was injured or killed |
| `n_fatal` | at least one person was killed |

### Crash cubes

The `near` column is the kind of the nearest housing site within 250 m, written "construction type | size band" (for example `New Construction | 50-149`), or `Not near a site`.

| File | Rows | Dimensions |
|---|---|---|
| `crash_cube.parquet` | 150,293 | `year`, `month`, `borough` (five boroughs plus Unknown), `factor`, `hour_band`, `near` |
| `hour_cube.parquet` | 348,395 | `year`, `borough`, `factor`, `weekday` (0 is Monday), `hour`, `near` |
| `zip_cube.parquet` | 218,548 | `zip` (panel ZIP codes only), `year`, `factor`, `hour_band`, `near` |
| `map_grid.parquet` | 623,042 | `cell`, `year`, `borough`, `factor`, `hour_band`, `near` |

The map grid has cells of 0.0045 degrees of latitude by 0.006 degrees of longitude (about 500 m), 113 rows by 110 columns from 40.45 N, 74.30 W. `cell` is row times 110 plus column. The cubes sum to the same totals, and the tests check this. The hour cube includes the 23,717 crashes logged at 0:00; the heat map says so in a note.

### Housing and site tables

| File | Rows | Contents |
|---|---|---|
| `housing_cube.parquet` | 2,164 | Completed buildings by `borough`, `zip`, `year`, `construction_type`, `size_band`, `is_located`, with `buildings`, `total_units`, `affordable_units`, `deep_affordable_units`. Confidential rows have an empty ZIP |
| `zip_year.parquet` | 1,720 | The integrated ZIP by year panel of section 3 |
| `sites.parquet` | 7,593 | `site_id`, `cluster_id`, `project_name`, `borough`, `zip`, `lat`, `lon`, `start_year`, `completion_year` (missing if not completed), `construction_type`, `size_band`, `total_units`, `affordable_units`, `baseline_crashes` and `borough_percentile` (RQ7; missing for sites outside that question) |
| `event_sites.parquet` | 2,175 | One row per clean site and cohort: `site_id`, `cohort`, `cluster_id`, `borough`, `construction_type`, `size_band`, `total_units`, `treated`, and yearly counts for relative years -3 to +3 in three families: `injury_-3` to `injury_+3`, `all_-3` to `all_+3`, `pedcyc_-3` to `pedcyc_+3` |
| `city_year.parquet` | 10 | `year` and yearly citywide `crashes`, `injury_crashes`, `persons_injured`, `persons_killed`, `ped_cyc_crashes`, `injury_share`, `deaths_per_1000_injury_crashes`, `crash_index`, `injury_crash_index` |

### Results and logs

| File | Contents |
|---|---|
| `robustness.parquet` | 16 rows, one per specification of Section 9: `check`, `variant`, `kind` (central, check or placebo), `keeps_screen`, `n_treated` (treated rows, one per site), `n_comparison` (comparison rows, one per cohort a site serves, so not a count of sites), `n_comparison_sites` (unique comparison sites), `n_treated_dropped`, `n_comparison_dropped`, `n_resampled_units` (all clusters in the sample), `n_treated_clusters` (those holding a treated row), `n_strata`, `treated_change`, `comparison_change`, `estimate`, `low`, `high` (log points), `p_value`, `percent_change`, `percent_low`, `percent_high`, `interval_excludes_zero` |
| `cleaning_log.parquet` | The 49 cleaning rules (columns in section 2) |
| `results.json` | `questions` (RQ1 to RQ10: question, sentence, estimate, `low`, `high`, `level`, `adjusted_p`, `n`, `owner`, `label`, `unit`, `n_unit`, `direction`, `excludes_zero`, `excludes_zero_reported` (ZIP-level questions only, otherwise empty), `kept`), `detail` (extra results such as the RQ5 split by type, the RQ7 variants including `one_vote`, the RQ7 borough views, the reported-ZIP checks, `rq2_checks`, `placebo_overlap` and `comparison_subset_pretrend`), `facts`, `limits` and `stages` (row counts by stage) |
| `meta.json` | Build time, dataset names and links, data-as-of dates, row counts, constants (window, buffer, bootstrap settings including `n_boot_joint` for the RQ8 and RQ10 tables, seed), the category lists of every dimension, the map grid definition and file sizes, and what the data was built from: `schema` (every table's columns and dtypes), `raw_sha256` (SHA-256 of each raw file), `source_sha256` (one SHA-256 of `pipeline/notebook/sections/*` and `app/core/stats.py`, ignoring line endings) and `packages` (library versions). The site checks every table against `schema` and an expected-column list when it starts, and `tests/test_pipeline.py` fails when the sources or raw files no longer match these hashes: rebuild with `python -m pipeline data`. The data dates come from the content (`data_as_of.latest_crash`), not from file dates. The build writes to a temporary folder, runs its checks there and only then replaces `app/data`; it refuses an `--out` folder that holds files it did not write |

The estimates in `results.json` are in the unit named in each entry's `unit` field: percent, percentage points, a rank correlation, percentile points, or injury crashes per ZIP and year.

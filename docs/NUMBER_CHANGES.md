# Number changes

Paths in entries before 9 November 2026 refer to the earlier layout: `tools/notebook_src/` is now `pipeline/notebook/sections/`, `tools/build_app_data.py` is `python -m pipeline data`, and `app/stats.py` is `app/core/stats.py`. The restructure of that date moved no number.

## Reproducible RQ7 reference points (November 2026)

Rebuilding `app/data` from the raw files on another machine moved RQ7 slightly. The cause: many crashes share
exact coordinates, so a street point often has several nearest crashes, and which one the ball tree returned (and so
the point's borough and ZIP) depended on library versions. For 18 of the 9,483 street points the tied crashes named
different boroughs. `reference_street_points` now reduces the crashes to one entry per location, carrying the borough
and ZIP recorded there most often, so the result is the same on every machine and for any order of the crash rows.
The street points themselves are unchanged (9,483); only those borough assignments moved.

| Value | Before | After |
|---|---|---|
| RQ7 headline (new construction, ranked in the borough) | +19.13 (+9.38 to +22.30) | +19.14 (+9.39 to +22.31) |
| Both kinds pooled | +14.54 (+4.62 to +19.62) | +14.56 (+4.64 to +19.64) |
| New construction, ranked in its own ZIP code | +8.72 (+5.62 to +12.29) | +8.68 (+5.61 to +12.29) |
| One vote per cluster | +10.50 (+7.72 to +13.21) | +10.52 (+7.73 to +13.23) |
| `sites.parquet` `borough_percentile` | | moved by 0.02 points on average, 0.11 at most |

Every other table and every other result is identical. Two builds from scratch now produce identical tables.

## The statistics correction

Every reader-facing number that moved in the statistics correction, against commit `75c0ffd`. The tables are written by a script that compares `app/data/results.json`, `robustness.parquet`, the other parquet tables and `meta.json` from git with the rebuilt files, not by hand. `built_at`, `build_seconds` and file sizes change on every build and are left out.

## Headlines

| RQ | Before (estimate, interval) | After (estimate, interval) | Kept before | Kept after |
|---|---|---|---|---|
| RQ1 | +0.59 (+0.17 to +1.11) | +0.59 (+0.17 to +1.11) | yes | no |
| RQ2 | +0.06 (-0.07 to +0.39) | +0.06 (-0.07 to +0.39) | no | no |
| RQ3 | -4.56 (-11.90 to +3.33) | -4.56 (-11.90 to +3.33) | no | no |
| RQ4 | -2.20 (-5.78 to +1.09) | -2.20 (-5.78 to +1.09) | no | no |
| RQ5 | -8.10 (-19.58 to +4.86) | -8.10 (-19.58 to +4.86) | no | no |
| RQ6 | +1.22 (-1.08 to +3.39) | +1.22 (-1.08 to +3.39) | no | no |
| RQ7 | +19.99 (+10.39 to +23.06) | +19.13 (+9.38 to +22.30) | yes | yes |
| RQ8 | +1.38 (-2.16 to +4.29) | +1.38 (-1.93 to +4.45) | no | no |
| RQ9 | -0.202 (-0.376 to +0.012) | -0.202 (-0.376 to +0.012) | no | no |
| RQ10 | -0.83 (-2.76 to +0.67) | -0.83 (-2.54 to +0.67) | no | no |

The RQ3 estimate and interval are identical to the last digit: the published estimate is unchanged. 7 of the ten headline estimates and intervals did not move; only their wording or tags can differ.

## Why numbers moved

1. **RQ7 reference points.** Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). This moves the RQ7 headline and every percentile in `sites.parquet`. The task named `baseline_tree` for this, but that tree holds injury crashes only, which would select street points on the outcome, so the snap uses a tree of all located crashes in the baseline years.
2. **RQ8 and RQ10.** RQ8 and RQ10 tables now use 5,000 resamples, because a widened interval rests on its thin tails. The 95% columns and p-values of those two tables use the same 5,000 draws, so they moved too. The printed level also changed from "99%" to 98.75% and 99.44%.
3. **RQ1 kept.** ZIP-level questions count as kept only if the interval excludes zero on both versions (Section 9.6). The estimate did not move; its tag and the words "less accurate" did.
4. **Comparison counts.** Comparison rows were shown as sites; unique sites are now exported beside rows. No estimate moved. The gate now counts unique sites. Of 108 report views scanned (each borough or all, one type or both, each size band or all; multi-select views were not scanned), 0 passed the old row count and now show the empty state.
5. **New rows and fields.** Five robustness rows, the RQ2 checks, one vote per cluster and the placebo overlap have no earlier value.

## Printed text with no change in the stored number

| Where | Before | After |
|---|---|---|
| RQ8 interval level, in sentence, tag and page | 99% | 98.75% |
| RQ10 interval level, in sentence, tag and page | 99% | 99.44% |
| RQ3 event chart and notebook chart legend, comparison line | n = 1,869 | n = 696 sites |
| Event panel scope line | 1,869 comparison | 696 comparison sites (1,869 rows) |
| RQ1 tag | Clear of zero | Clear of zero on all ZIP codes only, so not counted as a finding |
| RQ7 wording | "largest effect", "far from zero" | Direction citywide, size stated as dependent on the weighting |
| Robustness text | "the data support no direction", "exceptions all switch the screen off" | Read from the rows, with the comparison cuts named and no fall claimed |

## results.json, every leaf that differs

| Where | What | Before | After | Why |
|---|---|---|---|---|
| results.json | questions/RQ1/direction | right of zero = forecast less accurate with housing | right of zero = larger forecast error with housing | Axis wording: 'less accurate' became 'larger forecast error'. |
| results.json | questions/RQ1/kept | yes | no | ZIP-level questions count as kept only if the interval excludes zero on both versions (Section 9.6). |
| results.json | questions/RQ1/excludes_zero_reported | absent | no | ZIP-level questions count as kept only if the interval excludes zero on both versions (Section 9.6). |
| results.json | questions/RQ2/excludes_zero_reported | absent | no | ZIP-level questions count as kept only if the interval excludes zero on both versions (Section 9.6). |
| results.json | questions/RQ3/excludes_zero_reported | absent | none | New field; empty outside the ZIP-level questions. |
| results.json | questions/RQ4/excludes_zero_reported | absent | none | New field; empty outside the ZIP-level questions. |
| results.json | questions/RQ5/excludes_zero_reported | absent | none | New field; empty outside the ZIP-level questions. |
| results.json | questions/RQ6/excludes_zero_reported | absent | none | New field; empty outside the ZIP-level questions. |
| results.json | questions/RQ7/estimate | 19.994 | 19.127 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | questions/RQ7/low | 10.388 | 9.381 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | questions/RQ7/high | 23.060 | 22.297 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | questions/RQ7/excludes_zero_reported | absent | none | New field; empty outside the ZIP-level questions. |
| results.json | questions/RQ8/low | -2.164 | -1.932 | RQ8 and RQ10 tables now use 5,000 resamples, because a widened interval rests on its thin tails. |
| results.json | questions/RQ8/high | 4.295 | 4.453 | RQ8 and RQ10 tables now use 5,000 resamples, because a widened interval rests on its thin tails. |
| results.json | questions/RQ8/adjusted_p | 0.527 | 0.561 | RQ8 and RQ10 tables now use 5,000 resamples, because a widened interval rests on its thin tails. |
| results.json | questions/RQ8/excludes_zero_reported | absent | none | New field; empty outside the ZIP-level questions. |
| results.json | questions/RQ9/excludes_zero_reported | absent | no | ZIP-level questions count as kept only if the interval excludes zero on both versions (Section 9.6). |
| results.json | questions/RQ10/low | -2.755 | -2.544 | RQ8 and RQ10 tables now use 5,000 resamples, because a widened interval rests on its thin tails. |
| results.json | questions/RQ10/high | 0.669 | 0.666 | RQ8 and RQ10 tables now use 5,000 resamples, because a widened interval rests on its thin tails. |
| results.json | questions/RQ10/adjusted_p | 0.933 | 0.918 | RQ8 and RQ10 tables now use 5,000 resamples, because a widened interval rests on its thin tails. |
| results.json | questions/RQ10/excludes_zero_reported | absent | none | New field; empty outside the ZIP-level questions. |
| results.json | detail/rq3_did/n_clusters | absent | 356 | Comparison rows were shown as sites; unique sites are now exported beside rows. |
| results.json | detail/rq3_did/n_comparison_sites | absent | 696 | Comparison rows were shown as sites; unique sites are now exported beside rows. |
| results.json | detail/rq3_did/n_treated_clusters | absent | 85 | Comparison rows were shown as sites; unique sites are now exported beside rows. |
| results.json | detail/rq7/new/estimate | 19.994 | 19.127 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7/new/low | 10.388 | 9.381 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7/new/high | 23.060 | 22.297 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7/pooled/estimate | 15.511 | 14.541 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7/pooled/low | 5.679 | 4.616 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7/pooled/high | 20.494 | 19.623 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7/within_zip/estimate | 8.387 | 8.724 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7/within_zip/low | 4.838 | 5.620 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7/within_zip/high | 12.053 | 12.291 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7/within_zip/n | 2,662 | 2,546 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7/within_zip/units_resampled | 315 | 306 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7/one_vote/estimate | absent | 10.500 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7/one_vote/low | absent | 7.716 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7/one_vote/high | absent | 13.215 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7/one_vote/n | absent | 350 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7/one_vote/units_resampled | absent | 350 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_new_sites/share_above_borough_median_pct | 80.316 | 78.594 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_new_sites/median_baseline_crashes_reference | 27.000 | 29.000 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_new_sites/reference_points | 9,985 | 9,483 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_new_sites/share_clusters_above_borough_median_pct | absent | 65.429 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_new_sites/largest_clusters_shown | absent | 3 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_new_sites/largest_clusters_share_pct | absent | 59.448 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Bronx/reference_points | 1,430 | 1,368 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Bronx/median_crashes_reference | 34.000 | 35.000 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Bronx/mean_percentile_sites | 67.800 | 66.462 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Bronx/share_above_borough_median_pct | 78.394 | 74.888 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Bronx/new_sites | absent | 848.000 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Bronx/new_clusters | absent | 63.000 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Bronx/new_excess | absent | 18.703 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Bronx/new_low | absent | 0.421 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Bronx/new_high | absent | 22.295 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Bronx/new_one_vote_excess | absent | 3.376 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Bronx/new_one_vote_low | absent | -2.029 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Bronx/new_one_vote_high | absent | 8.414 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Bronx/new_clusters_above_pct | absent | 52.381 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Brooklyn/reference_points | 2,517 | 2,448 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Brooklyn/median_crashes_reference | 41.000 | 42.000 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Brooklyn/mean_percentile_sites | 68.970 | 68.316 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Brooklyn/share_above_borough_median_pct | 80.449 | 79.299 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Brooklyn/new_sites | absent | 1,319.000 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Brooklyn/new_clusters | absent | 111.000 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Brooklyn/new_excess | absent | 19.168 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Brooklyn/new_low | absent | -12.067 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Brooklyn/new_high | absent | 23.830 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Brooklyn/new_one_vote_excess | absent | 2.316 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Brooklyn/new_one_vote_low | absent | -2.243 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Brooklyn/new_one_vote_high | absent | 7.063 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Brooklyn/new_clusters_above_pct | absent | 54.955 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Manhattan/reference_points | 878 | 857 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Manhattan/median_crashes_reference | 64.000 | 65.000 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Manhattan/mean_percentile_sites | 54.640 | 53.997 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Manhattan/new_sites | absent | 177.000 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Manhattan/new_clusters | absent | 34.000 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Manhattan/new_excess | absent | 11.833 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Manhattan/new_low | absent | 2.548 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Manhattan/new_high | absent | 17.130 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Manhattan/new_one_vote_excess | absent | 11.186 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Manhattan/new_one_vote_low | absent | 1.166 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Manhattan/new_one_vote_high | absent | 21.263 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Manhattan/new_clusters_above_pct | absent | 64.706 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Queens/reference_points | 3,748 | 3,569 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Queens/median_crashes_reference | 22.000 | 23.000 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Queens/mean_percentile_sites | 65.163 | 64.038 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Queens/share_above_borough_median_pct | 70.569 | 68.896 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Queens/new_sites | absent | 416.000 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Queens/new_clusters | absent | 131.000 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Queens/new_excess | absent | 23.520 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Queens/new_low | absent | 16.538 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Queens/new_high | absent | 28.894 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Queens/new_one_vote_excess | absent | 20.008 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Queens/new_one_vote_low | absent | 16.524 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Queens/new_one_vote_high | absent | 23.394 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Queens/new_clusters_above_pct | absent | 80.916 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Staten Island/reference_points | 1,412 | 1,241 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Staten Island/median_crashes_reference | 7.000 | 8.000 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Staten Island/mean_percentile_sites | 54.031 | 51.535 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_by_borough/Staten Island/new_sites | absent | 29.000 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Staten Island/new_clusters | absent | 12.000 | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Staten Island/new_excess | absent | none | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Staten Island/new_low | absent | none | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Staten Island/new_high | absent | none | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Staten Island/new_one_vote_excess | absent | none | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Staten Island/new_one_vote_low | absent | none | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Staten Island/new_one_vote_high | absent | none | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_by_borough/Staten Island/new_clusters_above_pct | absent | none | New check: one vote per cluster and the size of the largest clusters. |
| results.json | detail/rq7_mean_percentile_by_type/New Construction | 69.994 | 69.127 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq7_mean_percentile_by_type/Preservation | 59.529 | 58.420 | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |
| results.json | detail/rq2_checks/new_construction_stock/estimate | absent | 0.262 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/rq2_checks/new_construction_stock/low | absent | -0.014 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/rq2_checks/new_construction_stock/high | absent | 0.560 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/rq2_checks/preservation_stock/estimate | absent | 0.038 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/rq2_checks/preservation_stock/low | absent | -0.096 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/rq2_checks/preservation_stock/high | absent | 0.650 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/rq2_checks/leave_one_zip_out/low | absent | 0.025 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/rq2_checks/leave_one_zip_out/high | absent | 0.254 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/rq2_checks/leave_one_zip_out/n_zips | absent | 172 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/rq2_checks/most_influential_zip/estimate | absent | 0.254 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/rq2_checks/most_influential_zip/low | absent | 0.041 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/rq2_checks/most_influential_zip/high | absent | 0.451 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/rq2_checks/most_influential_zip/zip | absent | 10475 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/rq2_checks/most_influential_zip/share_of_stock_variation_pct | absent | 48.724 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/rq2_checks/most_influential_zip/units_completed | absent | 15,531 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/rq2_checks/most_influential_zip/preservation_units | absent | 15,531 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/rq2_checks/most_influential_zip/new_construction_units | absent | 0 | New check beside the RQ2 headline (Section 9.6). |
| results.json | detail/comparison_subset_check | absent | Comparison subset | New check. |
| results.json | detail/comparison_subset_pretrend/percent_change | absent | 9.687 | New check. |
| results.json | detail/comparison_subset_pretrend/percent_low | absent | -9.617 | New check. |
| results.json | detail/comparison_subset_pretrend/percent_high | absent | 28.126 | New check. |
| results.json | detail/placebo_overlap/placebo_treated | absent | 245 | New: the placebo's overlap with the central sample. |
| results.json | detail/placebo_overlap/central_treated | absent | 128 | New: the placebo's overlap with the central sample. |
| results.json | detail/placebo_overlap/in_both | absent | 30 | New: the placebo's overlap with the central sample. |
| results.json | limits/robustness_intervals | 11 | 16 | Five rows added to the robustness table. |

## Result sentences that changed

Before and after of each stored sentence.

| Where | What | Before | After | Why |
|---|---|---|---|---|
| results.json | questions/RQ1/sentence | The change in out-of-time forecast error from adding affordable-housing completions and stock is +0.59 injury crashes per ZIP per year (95% interval +0.17 to +1.11, n = 172 ZIP codes). The interval lies above zero, which fits a less accurate forecast. | The change in out-of-time forecast error from adding affordable-housing completions and stock is +0.59 injury crashes per ZIP per year (95% interval +0.17 to +1.11, n = 172 ZIP codes). The interval lies above zero, which fits a forecast that housing did not improve. | Wording of the sentence changed, or a number inside it moved for the reason of its question. |
| results.json | questions/RQ6/sentence | The gap in the pedestrian and cyclist share of injury crashes (completed minus comparison sites) is +1.22 percentage points (95% interval -1.08 to +3.39, n = 306 completed sites, against 696 comparison sites, in 409 clusters). The interval includes zero. | The gap in the pedestrian and cyclist share of injury crashes (completed minus comparison sites) is +1.22 percentage points (95% interval -1.08 to +3.39, n = 306 completed sites, against 696 comparison sites, in 409 clusters, 147 of them with a completed site). The interval includes zero. | Wording of the sentence changed, or a number inside it moved for the reason of its question. |
| results.json | questions/RQ7/sentence | The mean borough percentile of new-construction sites before their project started, minus 50, is +19.99 percentile points (95% interval +10.39 to +23.06, n = 2,789 new-construction sites in 350 linked clusters). The interval lies above zero, which fits sites standing where there were already more injury crashes than at the typical street point of the borough. | The mean borough percentile of new-construction sites before their project started, minus 50, is +19.13 percentile points (95% interval +9.38 to +22.30, n = 2,789 new-construction sites in 350 linked clusters). The interval lies above zero, which fits sites standing where there were already more injury crashes than at the typical street point of the borough. | Wording of the sentence changed, or a number inside it moved for the reason of its question. |
| results.json | questions/RQ8/sentence | The largest of the 4 part-of-day gaps, for the afternoon (12:00-17:59), with its interval widened for 4 tests, is +1.38 percentage points (99% interval -2.16 to +4.29, n = 306 completed sites in 409 clusters). The interval includes zero. | The largest of the 4 part-of-day gaps, for the afternoon (12:00-17:59), with its interval widened for 4 tests, is +1.38 percentage points (98.75% interval -1.93 to +4.45, n = 306 completed sites in 409 clusters, 147 of them with a completed site). The interval includes zero. | Wording of the sentence changed, or a number inside it moved for the reason of its question. |
| results.json | questions/RQ10/sentence | The largest of the 9 factor-group gaps, for "Impairment or medical" among injury crashes with a recorded factor, with its interval widened for 9 tests, is -0.83 percentage points (99% interval -2.76 to +0.67, n = 306 completed sites in 409 clusters). The interval includes zero. | The largest of the 9 factor-group gaps, for "Impairment or medical" among injury crashes with a recorded factor, with its interval widened for 9 tests, is -0.83 percentage points (99.44% interval -2.54 to +0.67, n = 306 completed sites in 409 clusters, 147 of them with a completed site). The interval includes zero. | Wording of the sentence changed, or a number inside it moved for the reason of its question. |

## robustness.parquet

| Where | What | Before | After | Why |
|---|---|---|---|---|
| robustness hover and notebook | Central estimate: 250 m, 3 years, injury crashes, comparison count shown as sites | 1,869 comparison sites | 696 comparison sites (1,869 rows); 85 of 356 clusters hold a treated site | Comparison rows were shown as sites; unique sites are now exported beside rows. |
| robustness hover and notebook | Outcome: All crashes, including property damage only, comparison count shown as sites | 1,869 comparison sites | 696 comparison sites (1,869 rows); 85 of 356 clusters hold a treated site | Comparison rows were shown as sites; unique sites are now exported beside rows. |
| robustness hover and notebook | Nearby completions: Screen switched off: every candidate site, comparison count shown as sites | 11,288 comparison sites | 3,721 comparison sites (11,288 rows); 152 of 462 clusters hold a treated site | Comparison rows were shown as sites; unique sites are now exported beside rows. |
| robustness hover and notebook | Nearby completions: Screen off, without the most influential cluster, comparison count shown as sites | 11,228 comparison sites | 3,691 comparison sites (11,228 rows); 151 of 461 clusters hold a treated site | Comparison rows were shown as sites; unique sites are now exported beside rows. |
| robustness hover and notebook | Placebo: Completion dated 3 years early, 3-year window, comparison count shown as sites | 1,869 comparison sites | 696 comparison sites (1,869 rows); 159 of 327 clusters hold a treated site | Comparison rows were shown as sites; unique sites are now exported beside rows. |
| robustness hover and notebook | Placebo: Completion dated 3 years early, 2-year window, comparison count shown as sites | 1,869 comparison sites | 696 comparison sites (1,869 rows); 159 of 327 clusters hold a treated site | Comparison rows were shown as sites; unique sites are now exported beside rows. |
| robustness hover and notebook | Comparison group: Compared inside cohort and borough, comparison count shown as sites | 1,806 comparison sites | 696 comparison sites (1,806 rows); 85 of 356 clusters hold a treated site | Comparison rows were shown as sites; unique sites are now exported beside rows. |
| robustness hover and notebook | Cohorts: Without the 2019 cohort, comparison count shown as sites | 1,173 comparison sites | 538 comparison sites (1,173 rows); 66 of 288 clusters hold a treated site | Comparison rows were shown as sites; unique sites are now exported beside rows. |
| robustness hover and notebook | Projects: One building per project, comparison count shown as sites | 1,187 comparison sites | 463 comparison sites (1,187 rows); 85 of 336 clusters hold a treated site | Comparison rows were shown as sites; unique sites are now exported beside rows. |
| robustness | Comparison subset: Only sites not started by the window's end | absent | -9.65% (-16.64 to -1.56); 128 treated, 444 comparison sites, 944 rows, 85 of 280 clusters | New check. |
| robustness | Comparison subset: Only sites started inside the window | absent | -1.57% (-10.72 to +7.04); 128 treated, 449 comparison sites, 890 rows, 85 of 316 clusters | New check. |
| robustness | Comparison subset: Only new-construction sites (same type) | absent | -7.90% (-15.15 to -0.36); 128 treated, 374 comparison sites, 980 rows, 85 of 280 clusters | New check. |
| robustness | Comparison subset: Only preservation sites (other type) | absent | +0.38% (-9.00 to +10.61); 128 treated, 322 comparison sites, 889 rows, 85 of 184 clusters | New check. |
| robustness | Clusters: Same units, clusters linked at 500 m | absent | -4.56% (-12.97 to +4.29); 128 treated, 696 comparison sites, 1,869 rows, 42 of 126 clusters | New check. |
| robustness hover and notebook | Buffer radius: 150 m, screen and clusters rebuilt at 150 m, comparison count shown as sites | 3,847 comparison sites | 1,444 comparison sites (3,847 rows); 239 of 881 clusters hold a treated site | Comparison rows were shown as sites; unique sites are now exported beside rows. |
| robustness hover and notebook | Buffer radius: 400 m, screen and clusters rebuilt at 400 m, comparison count shown as sites | 1,090 comparison sites | 387 comparison sites (1,090 rows); 37 of 150 clusters hold a treated site | Comparison rows were shown as sites; unique sites are now exported beside rows. |

## Other exported tables

Unchanged: city_year, cleaning_log, crash_cube, event_sites, hour_cube, housing_cube, map_grid, zip_cube, zip_year.

| Where | What | Before | After | Why |
|---|---|---|---|---|
| sites | borough_percentile | mean 65.511 | mean 64.541; 4,878 of 7,593 rows moved | Street points now qualify on crashes of the baseline years only, so no crash after the baseline decides which streets count (9,985 points to 9,483). |

## meta.json

| Where | What | Before | After | Why |
|---|---|---|---|---|
| meta.json | constants/n_boot_joint | absent | 5,000 | New constant: the resamples behind the RQ8 and RQ10 tables. |

"""Stage 3 of the data build: results.json, the ten research-question results and the story facts."""
from __future__ import annotations

import pandas as pd

from pipeline.build.frames import to_plain

# Short keys for the rows of the notebook's RQ7 table (the notebook's row labels are sentences).
RQ7_ROWS = {"new": "RQ7_NEW", "pooled": "RQ7_POOLED", "within_zip": "RQ7_WITHIN_ZIP", "one_vote": "RQ7_ONE_VOTE"}


def estimate_row(row: pd.Series, estimate: str, low: str, high: str, **extra: str) -> dict:
    """One estimate with its interval, under the same three keys whatever the source columns are called."""
    record = {"estimate": row[estimate], "low": row[low], "high": row[high]}
    record.update({name: row[column] for name, column in extra.items()})
    return record


def unscreened_variants(robustness: pd.DataFrame) -> list[str]:
    """Robustness rows that admit treated sites with other completions nearby."""
    return robustness.loc[~robustness["keeps_screen"].astype(bool), "variant"].astype(str).tolist()


def results_document(ns: dict) -> dict:
    """The ten headline results with their sentences, plus the facts quoted in the story."""
    summary = ns["summary_table"]
    questions = {}
    for key, stored in ns["RESULTS"].items():
        row = summary.loc[key]
        questions[key] = {
            "question": stored["question"], "sentence": stored["sentence"],
            "estimate": stored["estimate"], "low": stored["ci_low"], "high": stored["ci_high"],
            "level": stored["level"], "adjusted_p": stored["adjusted_p"],
            "n": stored["n"], "owner": row["owner"], "label": row["label"], "unit": row["unit"],
            "n_unit": row["n_unit"], "direction": row["direction"],
            "excludes_zero": row["excludes_zero"], "excludes_zero_reported": row["excludes_zero_reported"],
            "kept": row["kept"],
        }
    contrast = ns["rq5_contrast"]
    rq7_sites, rq7_estimates = ns["rq7_sites"], ns["rq7_estimates"]
    is_new = rq7_sites["construction_type"].astype(str) == ns["NEW_CONSTRUCTION"]
    by_type = rq7_sites.groupby("construction_type", observed=True)["borough_percentile"].mean()
    reported_ped, rq9_all = ns["reported_ped"], ns["rq9_result"].loc["ped_cyc_share_pct"]
    detail = {
        # n_control counts comparison rows, one per cohort a site serves; n_comparison_sites counts sites.
        "rq3_did": {**{key: ns["new_build_did"][key] for key in
                       ["percent_change", "percent_low", "percent_high", "p_value", "n_treated", "n_control",
                        "n_clusters"]},
                    **{key: ns["new_build_sizes"][key] for key in ["n_comparison_sites", "n_treated_clusters"]}},
        "rq3_pretrend": {key: ns["pretrend_did"][key] for key in
                         ["percent_change", "percent_low", "percent_high"]},
        "rq5_by_type": {name: {"percent": contrast.loc[name, "estimate_pct"],
                               "low": contrast.loc[name, "low_pct"], "high": contrast.loc[name, "high_pct"],
                               "n": contrast.loc[name, "n_treated"]} for name in contrast.index},
        "rq7": {short: {**estimate_row(rq7_estimates.loc[ns[constant]], "estimate", "low", "high"),
                        # One vote per cluster: n is the clusters, the units that were averaged.
                        "n": int(rq7_estimates.loc[ns[constant], "units_resampled" if short == "one_vote" else "n_sites"]),
                        "units_resampled": int(rq7_estimates.loc[ns[constant], "units_resampled"])}
                for short, constant in RQ7_ROWS.items()},
        "rq7_new_sites": {
            "share_above_borough_median_pct": float((rq7_sites.loc[is_new, "borough_percentile"]
                                                     > ns["NEUTRAL_PERCENTILE"]).mean() * 100),
            "median_baseline_crashes": float(rq7_sites.loc[is_new, "baseline_crashes"].median()),
            "median_baseline_crashes_reference": float(ns["rq7_reference"]["baseline_crashes"].median()),
            "reference_points": len(ns["rq7_reference"]),
            "share_clusters_above_borough_median_pct": ns["rq7_one_vote"]["share_above_pct"],
            "largest_clusters_shown": ns["LARGEST_RQ7_CLUSTERS"],
            "largest_clusters_share_pct": ns["rq7_largest_share"],
        },
        "rq7_by_borough": ns["rq7_by_borough"].reset_index().to_dict("records"),
        "rq7_mean_percentile_by_type": by_type.to_dict(),
        "rq9_adjusted_p": rq9_all["p_adjusted"],
        # Section 9.10: the three ZIP-level results again, on crashes with a reported ZIP code only.
        "reported_zips": {
            "rq1": estimate_row(ns["reported_forecast"], "mae_minus_baseline", "low", "high"),
            "rq2_stock": estimate_row(ns["reported_stock"], "estimate_pct", "low_pct", "high_pct"),
            "rq2_same_year": estimate_row(ns["same_year_reported"], "estimate_pct", "low_pct", "high_pct",
                                          adjusted_p="p_adjusted"),
            "rq2_same_year_all_zips": estimate_row(ns["same_year_all"], "estimate_pct", "low_pct", "high_pct",
                                                   adjusted_p="p_adjusted"),
            "rq9": estimate_row(reported_ped, "rho_within_borough", "low", "high", adjusted_p="p_adjusted"),
        },
        # Section 9.6: the RQ2 slope beside its headline.
        "rq2_checks": {
            "new_construction_stock": ns["rq2_new_stock"], "preservation_stock": ns["rq2_preserved_stock"],
            "leave_one_zip_out": {key: ns["rq2_without_one"][key] for key in ["low", "high", "n_zips"]},
            "most_influential_zip": {**ns["rq2_without_one"]["without"],
                                     **{key: ns["rq2_without_one"][key] for key in
                                        ["zip", "share_of_stock_variation_pct", "units_completed", "preservation_units",
                                         "new_construction_units"]}},
        },
        "false_discovery_rate": ns["FALSE_DISCOVERY_RATE"],
        "unscreened_variants": unscreened_variants(ns["robustness_table"]),
        "comparison_subset_check": ns["CHECK_COMPARISON_SUBSET"],
        "comparison_subset_pretrend": {key: ns["pretrend_not_started"][key] for key in
                                       ["percent_change", "percent_low", "percent_high"]},
        "placebo_overlap": ns["placebo_overlap"],
        "largest_clusters": ns["LARGEST_CLUSTERS_SHOWN"],
    }
    return to_plain({"questions": questions, "detail": detail, "facts": ns["facts"],
                     "limits": ns["limits"],
                     "stages": [{"stage": stage, "table": table, "rows": rows}
                                for (stage, table), rows in ns["stages"]["rows"].items()]})

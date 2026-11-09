"""The data behind the overview's live canvas: one record per located building, plus the RQ3 outcomes.

Pure functions of the `Store`. `story_payload` builds compact arrays for assets/js/20-stage.js; `encoded`
serialises it once per process, and the URL carries a hash of those bytes, so a rebuilt payload is never
read from an old cache. Every figure here comes from the tables; none is typed.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from functools import lru_cache

import numpy as np
import pandas as pd

from app.core import stats
from app.core.data import NEW_CONSTRUCTION, POST_YEARS, PRE_YEARS, Store

STORY_URL = "/data/story.json"
N_OUTCOMES = 50                # dots of the quantile dotplot (Fernandes et al. 2018)
COORD_SCALE = 10_000           # coordinates travel as integers of 1/10,000 degree, about 10 m
PERCENTILE_SCALE = 10          # percentiles travel as integers of 1/10 point, cut down so no site changes bin
NO_PERCENTILE = -1             # a site outside RQ7: its project started before the baseline ended
OUTCOME_DIGITS = 2
PRINTED_DIGITS = 1             # RQ3 is printed to one decimal in results.json
# How far a building gets through the comparison: the integers in `stage` index this list.
FUNNEL_LOCATED, FUNNEL_COMPLETED, FUNNEL_CLEAN, FUNNEL_COMPARED = range(4)


def _rq3_sample(store: Store) -> pd.DataFrame:
    """The RQ3 rows in the order of the table, because the bootstrap draws rows by position."""
    table = store.event_sites
    return table[~table["treated"] | (table["construction_type"].astype(str) == NEW_CONSTRUCTION)]


@lru_cache(maxsize=2)
def rq3_outcomes(store: Store) -> dict:
    """The RQ3 bootstrap, summarised as evenly spaced quantiles, in percent.

    It is `stats.did_log_ratio`'s own call (statistic, arrays, clusters, seed), written out here because that
    function keeps only the interval. Asserted to reproduce RQ3 as results.json prints it.
    """
    sample = _rq3_sample(store)
    counts = {rel_year: sample[f"injury_{rel_year:+d}"].to_numpy(dtype=float) for rel_year in PRE_YEARS + POST_YEARS}
    before = sum(counts[rel_year] for rel_year in PRE_YEARS)
    after = sum(counts[rel_year] for rel_year in POST_YEARS)
    treated = sample["treated"].to_numpy()
    codes, labels = pd.factorize(sample["cohort"].to_numpy())
    n_strata = len(labels)

    def did_estimate(change_rows, treated_rows, strata_rows):
        return stats.stratified_difference(change_rows, treated_rows, strata_rows, n_strata)["estimate"]

    boot = stats.bootstrap_ci(did_estimate, stats.log_ratio(before, after), treated, codes,
                              clusters=sample["cluster_id"].to_numpy())
    printed = store.results["questions"]["RQ3"]
    for name, value, expected in [("estimate", boot["estimate"], printed["estimate"]),
                                  ("low", boot["low"], printed["low"]), ("high", boot["high"], printed["high"])]:
        assert round(float(stats.log_points_to_percent(value)), PRINTED_DIGITS) == round(expected, PRINTED_DIGITS), name
    probabilities = (np.arange(N_OUTCOMES) + 0.5) / N_OUTCOMES
    quantiles = stats.log_points_to_percent(np.nanquantile(boot["replicates"], probabilities))
    return {"quantiles": [round(float(value), OUTCOME_DIGITS) for value in quantiles],
            "below_zero": int((quantiles < 0).sum()), "n_boot": int(len(boot["replicates"])),
            "estimate": printed["estimate"]}


def funnel_stage(store: Store) -> np.ndarray:
    """For each located site, the last stage of the RQ3 funnel it reaches. In the order of `store.sites`."""
    sites, table = store.sites, store.event_sites
    treated = table[table["treated"]]
    stage = np.full(len(sites), FUNNEL_LOCATED, dtype=np.int64)
    stage[sites["completion_year"].isin(treated["cohort"].unique()).to_numpy()] = FUNNEL_COMPLETED
    stage[sites["site_id"].isin(treated["site_id"]).to_numpy()] = FUNNEL_CLEAN
    compared = treated.loc[treated["construction_type"].astype(str) == NEW_CONSTRUCTION, "site_id"]
    stage[sites["site_id"].isin(compared).to_numpy()] = FUNNEL_COMPARED
    return stage


def funnel_counts(store: Store) -> list[int]:
    """How many sites reach each stage: all located, completed in a usable year, clean, new construction."""
    stage = funnel_stage(store)
    return [int((stage >= position).sum()) for position in (FUNNEL_LOCATED, FUNNEL_COMPLETED, FUNNEL_CLEAN, FUNNEL_COMPARED)]


def _variants(store: Store) -> list[dict]:
    """One record per robustness row, for the canvas strip and its hover text."""
    return [{"label": str(row.variant), "estimate": round(float(row.percent_change), OUTCOME_DIGITS)}
            for row in store.robustness.itertuples()]


def story_payload(store: Store) -> dict:
    """Everything the canvas draws, in compact arrays aligned on one building per position."""
    sites = store.sites
    lon = np.round(sites["lon"].to_numpy(dtype=float) * COORD_SCALE).astype(np.int64)
    lat = np.round(sites["lat"].to_numpy(dtype=float) * COORD_SCALE).astype(np.int64)
    lon_origin, lat_origin = int(lon.min()), int(lat.min())
    percentile = sites["borough_percentile"].to_numpy(dtype=float)
    # Rounded down, not to nearest: a site at 69.99 must stay in the 65 to 70 bin the statistics put it in.
    percentile_code = np.where(np.isnan(percentile), NO_PERCENTILE,
                               np.floor(np.nan_to_num(percentile) * PERCENTILE_SCALE)).astype(np.int64)
    boroughs = [str(name) for name in store.meta["dimensions"]["boroughs"]]
    borough_code = pd.Categorical(sites["borough"].astype(str), categories=boroughs).codes
    outcomes = rq3_outcomes(store)
    return {
        "n": int(len(sites)),
        "scale": COORD_SCALE, "percentile_scale": PERCENTILE_SCALE,
        "origin": [lon_origin, lat_origin],
        "lon": (lon - lon_origin).tolist(), "lat": (lat - lat_origin).tolist(),
        "new": (sites["construction_type"].astype(str) == NEW_CONSTRUCTION).astype(int).tolist(),
        "units": sites["total_units"].astype(int).tolist(),
        "percentile": percentile_code.tolist(),
        "borough": [int(code) for code in borough_code], "boroughs": boroughs,
        "stage": funnel_stage(store).tolist(),
        "name": sites["project_name"].astype(str).tolist(),
        "funnel": funnel_counts(store),
        "outcomes": outcomes["quantiles"], "below_zero": outcomes["below_zero"],
        "variants": _variants(store),
    }


@lru_cache(maxsize=2)
def encoded(store: Store) -> tuple[bytes, bytes, str]:
    """(JSON, gzip of it, hash of it). `mtime=0` keeps the gzip bytes the same from one build to the next."""
    payload = json.dumps(story_payload(store), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return payload, gzip.compress(payload, compresslevel=9, mtime=0), hashlib.sha256(payload).hexdigest()[:12]


def versioned_url(store: Store) -> str:
    """The one place callers get the payload's address: the hash names the content, so it can be cached for good."""
    return f"{STORY_URL}?v={encoded(store)[2]}"

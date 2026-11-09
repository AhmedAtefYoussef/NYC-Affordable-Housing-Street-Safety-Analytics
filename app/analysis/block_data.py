"""Answers for the Your block page: find a site or ZIP, read its record in context, rank and export.

Pure functions of the store that return JSON-ready data. Input is validated here, so a route can pass
whatever arrived in a URL. Prepared lookups are built on first use and cached.
"""
from __future__ import annotations

import csv
import io
import math
import re
from functools import lru_cache
from types import SimpleNamespace

import numpy as np
import pandas as pd

from app.core.data import POST_YEARS, PRE_YEARS, REL_YEARS, Store

MAX_QUERY = 64
MAX_SITE_RESULTS = 8
MAX_ZIP_RESULTS = 4
PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
MAX_OFFSET = 1_000_000
NEARBY_SHOWN = 10
STRIP_BIN_WIDTH = 5
EARTH_RADIUS_M = 6_371_000.0
ZIP_PATTERN = re.compile(r"[0-9]{5}")
SITE_ID_PATTERN = re.compile(r"[0-9]{1,7}")
CSV_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
SORTS = {"baseline": "baseline_crashes", "percentile": "borough_percentile", "units": "total_units",
         "completion": "completion_year", "project": "project_name"}
DEFAULT_SORT, DEFAULT_DIRECTION = "baseline", "desc"
CSV_COLUMNS = {"rank": "rank", "site_id": "site_id", "project": "project", "borough": "borough", "zip": "zip",
               "type": "construction_type", "units": "total_units", "completion_year": "completion_year",
               "baseline_crashes": "injury_crashes_nearby_in_baseline_years", "percentile": "percentile_in_borough"}


def clean_query(query) -> str:
    """A search string: text only, no control characters, single spaces, capped in length."""
    if not isinstance(query, str):
        return ""
    printable = "".join(character if character.isprintable() else " " for character in query[:MAX_QUERY * 4])
    return " ".join(printable.split())[:MAX_QUERY]


def _as_int(value) -> int | None:
    return None if value is None or pd.isna(value) else int(value)


def _as_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


@lru_cache(maxsize=2)
def _lookup(store: Store) -> SimpleNamespace:
    """Text columns ready to match, cluster members by id, and borough context."""
    sites = store.sites.copy()
    for name in ("borough", "zip", "construction_type", "size_band"):
        sites[name] = sites[name].astype(str)
    sites["project_name"] = sites["project_name"].astype(str)
    sites = sites.set_index(sites["site_id"].rename(None))
    with_baseline = sites[sites["baseline_crashes"].notna()]
    medians = with_baseline.groupby("borough")["baseline_crashes"].median()
    panel = store.zip_year.copy()
    panel["zip"] = panel["zip"].astype(str)
    panel["borough"] = panel["borough"].astype(str)
    totals = panel.groupby("zip")[["units_completed", "injury_crashes", "injury_crashes_zip_imputed"]].sum()
    return SimpleNamespace(
        sites=sites, names=sites["project_name"].str.casefold(), with_baseline=with_baseline, medians=medians,
        panel=panel, panel_by_zip=dict(tuple(panel.groupby("zip"))), zip_totals=totals,
        site_zips=sites.groupby("zip").size(), boroughs=sorted(sites["borough"].unique()),
        zip_borough={**sites.groupby("zip")["borough"].first().to_dict(), **panel.groupby("zip")["borough"].first().to_dict()},
        clusters=sites.groupby("cluster_id").indices, event_rows=store.event_sites.groupby("site_id").indices)


def _site_detail(row) -> str:
    done = f"completed {int(row.completion_year)}" if pd.notna(row.completion_year) else "not recorded as completed"
    return f"{row.borough} {row.zip}, {row.total_units:,} units, {done}"


def search(store: Store, query, limit: int = MAX_SITE_RESULTS) -> dict:
    """Gazetteer lookup: ZIPs by prefix, boroughs by name, projects by every word typed (never a regex)."""
    lookup = _lookup(store)
    text = clean_query(query)
    answer = {"query": text, "results": [], "n_sites": 0}
    if not text:
        return answer
    folded = text.casefold()
    results = []
    if folded.isascii() and folded.isdigit() and len(folded) <= 5:
        for code in sorted(code for code in lookup.zip_borough if code.startswith(folded))[:MAX_ZIP_RESULTS]:
            n_sites = int(lookup.site_zips.get(code, 0))
            results.append({"kind": "zip", "id": code, "label": f"ZIP {code}",
                            "detail": f"{lookup.zip_borough[code]}, {n_sites:,} located sites"})
    for name in lookup.boroughs:
        if name.casefold().startswith(folded) or (len(folded) >= 3 and folded in name.casefold()):
            n_sites = int((lookup.sites["borough"] == name).sum())
            results.append({"kind": "borough", "id": name, "label": name,
                            "detail": f"Rank the {n_sites:,} located sites in this borough"})
    matches = pd.Series(True, index=lookup.names.index)
    for word in folded.split():
        matches &= lookup.names.str.contains(word, regex=False)
    found = lookup.sites[matches]
    if len(found):
        starts = lookup.names[matches].str.startswith(folded)
        found = (found.assign(_starts=starts).sort_values(["_starts", "total_units", "site_id"],
                                                          ascending=[False, False, True]))
    for row in found.head(limit).itertuples():
        results.append({"kind": "site", "id": int(row.site_id), "label": row.project_name, "detail": _site_detail(row)})
    return {**answer, "results": results, "n_sites": int(len(found))}


def parse_site_id(value) -> int | None:
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        return int(value)
    return int(value) if isinstance(value, str) and SITE_ID_PATTERN.fullmatch(value) else None


def _distance_m(lat, lon, lats, lons) -> np.ndarray:
    lat, lon, lats, lons = (np.radians(np.asarray(value, dtype=float)) for value in (lat, lon, lats, lons))
    chord = np.sin((lats - lat) / 2) ** 2 + np.cos(lat) * np.cos(lats) * np.sin((lons - lon) / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(chord))


def _nearby(store: Store, lookup: SimpleNamespace, site) -> tuple[list[dict], int]:
    members = lookup.sites.iloc[lookup.clusters[site.cluster_id]]
    members = members[members["site_id"] != site.site_id]
    if members.empty:
        return [], 0
    distances = _distance_m(site.lat, site.lon, members["lat"], members["lon"])
    within = distances <= store.meta["constants"]["buffer_m"]
    near = members[within].assign(distance=distances[within]).sort_values(["distance", "site_id"])
    return ([{"site_id": int(row.site_id), "project": row.project_name, "distance_m": int(round(row.distance)),
              "units": int(row.total_units), "type": row.construction_type} for row in near.head(NEARBY_SHOWN).itertuples()],
            int(len(near)))


def _strip(lookup: SimpleNamespace, borough: str) -> dict:
    """Share of the borough's sites in each percentile bin: the context the one site's mark sits on."""
    values = lookup.with_baseline.loc[lookup.with_baseline["borough"] == borough, "borough_percentile"].to_numpy(dtype=float)
    n_bins = 100 // STRIP_BIN_WIDTH
    bins = np.clip((values // STRIP_BIN_WIDTH).astype(int), 0, n_bins - 1)
    return {"bin_width": STRIP_BIN_WIDTH, "shares": (100 * np.bincount(bins, minlength=n_bins) / max(len(values), 1)).tolist(),
            "n_sites": int(len(values)), "share_above_50": float(100 * (values > 50).mean()) if len(values) else None}


def _event(store: Store, lookup: SimpleNamespace, site) -> dict | None:
    rows = lookup.event_rows.get(site.site_id)
    if rows is None:
        return None
    table = store.event_sites.iloc[rows].sort_values("cohort")
    role = "tested" if bool(table["treated"].iloc[0]) else "comparison"
    counts: dict[int, int] = {}
    for row in table.to_dict("records"):
        for offset in REL_YEARS:
            counts[int(row["cohort"]) + offset] = int(row[f"injury_{offset:+d}"])
    first = table.iloc[0]
    before = sum(int(first[f"injury_{offset:+d}"]) for offset in PRE_YEARS)
    after = sum(int(first[f"injury_{offset:+d}"]) for offset in POST_YEARS)
    cohorts = [int(year) for year in table["cohort"]]
    return {"role": role, "cohorts": cohorts, "cohort": cohorts[0], "before": before, "after": after,
            "years": [{"year": year, "count": counts[year]} for year in sorted(counts)],
            "scenario_link": "#lab" if site.construction_type != "Preservation" or role == "comparison"
            else "?scenario=sites:preservation#lab"}


def site_record(store: Store, site_id) -> dict | None:
    """One site's record in context, or None for an id that does not exist."""
    lookup = _lookup(store)
    parsed = parse_site_id(site_id)
    if parsed is None or parsed not in lookup.sites.index:
        return None
    site = next(lookup.sites.loc[[parsed]].itertuples())
    has_baseline = pd.notna(site.baseline_crashes)
    nearby, nearby_total = _nearby(store, lookup, site)
    median = _as_float(lookup.medians.get(site.borough))
    return {"kind": "site", "site_id": parsed, "project": site.project_name, "borough": site.borough, "zip": site.zip,
            "type": site.construction_type, "size_band": site.size_band, "units": int(site.total_units),
            "affordable_units": int(site.affordable_units), "start_year": _as_int(site.start_year),
            "completion_year": _as_int(site.completion_year), "has_baseline": bool(has_baseline),
            "baseline_crashes": _as_int(site.baseline_crashes), "borough_median": median,
            "percentile": _as_float(site.borough_percentile), "strip": _strip(lookup, site.borough),
            "event": _event(store, lookup, site), "nearby": nearby, "nearby_total": nearby_total,
            "buffer_m": store.meta["constants"]["buffer_m"], "baseline_years": store.meta["constants"]["baseline_years"]}


def zip_record(store: Store, code) -> dict | None:
    """One ZIP's years in context, or None for a value that is not a known ZIP."""
    lookup = _lookup(store)
    if not isinstance(code, str) or not ZIP_PATTERN.fullmatch(code) or code not in lookup.zip_borough:
        return None
    in_zip = lookup.sites[lookup.sites["zip"] == code].sort_values(["total_units", "site_id"], ascending=[False, True])
    answer = {"kind": "zip", "zip": code, "borough": lookup.zip_borough[code], "n_sites": int(len(in_zip)),
              "in_panel": code in lookup.panel_by_zip, "n_panel_zips": int(len(lookup.zip_totals)),
              "sites": [{"site_id": int(row.site_id), "project": row.project_name, "units": int(row.total_units),
                         "type": row.construction_type} for row in in_zip.head(NEARBY_SHOWN).itertuples()]}
    if not answer["in_panel"]:
        return answer
    years = lookup.panel_by_zip[code].sort_values("year")
    totals = lookup.zip_totals.loc[code]
    others = lookup.zip_totals.drop(index=code)

    def share_below(column: str) -> float:
        return float(100 * (others[column] < totals[column]).mean())

    injuries, imputed = int(totals["injury_crashes"]), int(totals["injury_crashes_zip_imputed"])
    return {**answer,
            "years": [{"year": int(row.year), "units": int(row.units_completed), "injury": int(row.injury_crashes)}
                      for row in years.itertuples()],
            "total_units": int(totals["units_completed"]), "total_injury": injuries,
            "injury_percentile": share_below("injury_crashes"), "units_percentile": share_below("units_completed"),
            "imputed_injury": imputed, "imputed_share": float(100 * imputed / injuries) if injuries else None,
            "city_imputed_share": float(store.results["limits"]["imputed_zip_share"])}


def _ranked_frame(store: Store, borough, kind, sort, direction) -> tuple[pd.DataFrame, dict]:
    lookup = _lookup(store)
    table = lookup.with_baseline
    borough = borough if isinstance(borough, str) and borough in lookup.boroughs else "all"
    kinds = sorted(table["construction_type"].unique())
    kind = kind if isinstance(kind, str) and kind in kinds else "all"
    sort = sort if isinstance(sort, str) and sort in SORTS else DEFAULT_SORT
    direction = direction if direction in ("asc", "desc") else DEFAULT_DIRECTION
    if borough != "all":
        table = table[table["borough"] == borough]
    if kind != "all":
        table = table[table["construction_type"] == kind]
    table = table.assign(rank=table["baseline_crashes"].rank(method="min", ascending=False).astype(int))
    key = {"key": lambda column: column.str.casefold()} if sort == "project" else {}
    table = table.sort_values("site_id").sort_values(SORTS[sort], ascending=direction == "asc", kind="stable",
                                                     na_position="last", **key)
    return table, {"borough": borough, "type": kind, "sort": sort, "dir": direction, "kinds": kinds}


def _ranked_row(row) -> dict:
    return {"rank": int(row.rank), "site_id": int(row.site_id), "project": row.project_name, "borough": row.borough,
            "zip": row.zip, "type": row.construction_type, "units": int(row.total_units),
            "completion_year": _as_int(row.completion_year), "baseline_crashes": int(row.baseline_crashes),
            "percentile": round(float(row.borough_percentile), 1)}


def _bounded(value, default: int, low: int, high: int) -> int:
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 9:
        value = int(value)
    if not isinstance(value, int) or isinstance(value, bool):
        return default
    return max(low, min(high, value))


def ranked(store: Store, borough=None, kind=None, sort=None, direction=None, offset=0, limit=PAGE_SIZE) -> dict:
    """One page of the sites on the most crash-heavy streets, with the total for the filter."""
    table, chosen = _ranked_frame(store, borough, kind, sort, direction)
    start = _bounded(offset, 0, 0, MAX_OFFSET)
    size = _bounded(limit, PAGE_SIZE, 1, MAX_PAGE_SIZE)
    page = table.iloc[start:start + size]
    return {**chosen, "rows": [_ranked_row(row) for row in page.itertuples()], "total": int(len(table)), "offset": start,
            "limit": size, "has_more": start + size < len(table),
            "baseline_years": store.meta["constants"]["baseline_years"]}


def _csv_safe(text: str) -> str:
    """A spreadsheet runs a cell that starts with these as a formula, so such text is marked as text."""
    return "'" + text if text.startswith(CSV_FORMULA_START) else text


def ranked_csv(store: Store, borough=None, kind=None, sort=None, direction=None) -> str:
    """Every row of the current filter as CSV, in the current order."""
    table, _ = _ranked_frame(store, borough, kind, sort, direction)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS.values())
    for row in table.itertuples():
        values = _ranked_row(row)
        writer.writerow([_csv_safe(value) if isinstance(value, str) else ("" if value is None else value)
                         for value in (values[name] for name in CSV_COLUMNS)])
    return out.getvalue()

"""The what-if lab: the central before-and-after comparison, recomputed for one reader's choices.

`run(store, spec)` takes anything as a spec (a value that is not an allowed one falls back to its
default) and returns plain JSON-ready data. The default spec keeps the rows of `event_sites` in their
exported order, so the seeded bootstrap draws what the notebook drew and RQ3 comes back exactly.
Nothing here runs at import: the columns are prepared on first use and results are kept in a bounded cache.
"""
from __future__ import annotations

import math
from functools import lru_cache
from types import SimpleNamespace

import numpy as np

from app.core import stats
from app.core.data import MIN_GROUP_N, NEW_CONSTRUCTION, POST_YEARS, PRE_YEARS, PRESERVATION, Store

CACHE_SIZE = 512
OUTCOME = "injury"
SITE_TYPES = {"new": NEW_CONSTRUCTION, "preservation": PRESERVATION}
SITE_NOUN = {"new": "new-construction", "preservation": "preservation"}
GROUP_LABEL = {"all": "All not yet completed", "not_started": "Not started by window end",
               "started": "Started inside the window", "same": "Same type", "other": "Other type"}
GROUP_PHRASE = {"all": "every comparison site not yet completed by the end of its window",
                "not_started": "comparison sites not started by the end of the window",
                "started": "comparison sites started inside the window",
                "same": "comparison sites of the same type", "other": "comparison sites of the other type"}
DEFAULT_SPEC = {"sites": "new", "borough": "all", "size": "all", "group": "all", "cluster": "in", "cohort": "all"}
TAG_UNCLEAR = "Cannot be told from no change"
TAG_EXCLUDES = "Excludes zero: an unadjusted association"


@lru_cache(maxsize=2)
def options(store: Store) -> dict:
    """The allowed values of each control, as {key: [(value, label), ...]}, default first."""
    table = store.event_sites
    bands = [band for band in store.meta["dimensions"]["size_bands"] if (table["size_band"] == band).any()]
    return {"sites": [("new", "New construction"), ("preservation", "Preservation")],
            "borough": [("all", "All"), *[(name, name) for name in sorted(table["borough"].astype(str).unique())]],
            "size": [("all", "All"), *[(band, band) for band in bands]],
            "group": list(GROUP_LABEL.items()),
            "cluster": [("in", "Keep it"), ("out", "Leave it out")],
            "cohort": [("all", "Keep all"), *[(str(year), f"Without {year}")
                                              for year in sorted(int(year) for year in table["cohort"].unique())]]}


def normalise(store: Store, spec) -> dict:
    """A full spec of allowed values. Whatever is unknown, missing or of the wrong type becomes the default."""
    given = spec if isinstance(spec, dict) else {}
    clean = {}
    for key, default in DEFAULT_SPEC.items():
        value = given.get(key)
        allowed = {option for option, _ in options(store)[key]}
        clean[key] = value if isinstance(value, str) and value in allowed else default
    return clean


@lru_cache(maxsize=2)
def _columns(store: Store) -> SimpleNamespace:
    """The event table as arrays and ready masks. uint8 counts are widened before they are summed."""
    table = store.event_sites
    before = table[[f"{OUTCOME}_{year:+d}" for year in PRE_YEARS]].to_numpy(dtype=float).sum(axis=1)
    after = table[[f"{OUTCOME}_{year:+d}" for year in POST_YEARS]].to_numpy(dtype=float).sum(axis=1)
    window = int(store.meta["constants"]["event_window"])
    start = store.sites.set_index("site_id")["start_year"].reindex(table["site_id"]).to_numpy(dtype=float)
    cohort = table["cohort"].to_numpy(dtype=np.int64)
    kind = table["construction_type"].astype(str).to_numpy()
    return SimpleNamespace(
        before=before, after=after, cohort=cohort, kind=kind, treated=table["treated"].to_numpy(dtype=bool),
        clusters=table["cluster_id"].to_numpy(), site_ids=table["site_id"].to_numpy(),
        borough=table["borough"].astype(str).to_numpy(), size=table["size_band"].astype(str).to_numpy(),
        not_started=start > cohort + window, started=(start > cohort - window) & (start <= cohort + window))


def _select(columns: SimpleNamespace, spec: dict) -> tuple[np.ndarray, dict | None]:
    """Row mask for a spec, and the cluster it left out. Size describes the tested sites only."""
    site_type = SITE_TYPES[spec["sites"]]
    tested = columns.treated & (columns.kind == site_type)
    if spec["size"] != "all":
        tested = tested & (columns.size == spec["size"])
    comparison = ~columns.treated
    group = spec["group"]
    if group == "not_started":
        comparison = comparison & columns.not_started
    elif group == "started":
        comparison = comparison & columns.started
    elif group == "same":
        comparison = comparison & (columns.kind == site_type)
    elif group == "other":
        comparison = comparison & (columns.kind != site_type)
    keep = tested | comparison
    if spec["borough"] != "all":
        keep = keep & (columns.borough == spec["borough"])
    if spec["cohort"] != "all":
        keep = keep & (columns.cohort != int(spec["cohort"]))
    left_out = None
    if spec["cluster"] == "out" and keep.any():
        labels, counts = np.unique(columns.clusters[keep], return_counts=True)
        largest = labels[np.argmax(counts)]          # np.unique sorts, so a tie takes the lowest id
        in_it = keep & (columns.clusters == largest)
        left_out = {"cluster_id": int(largest), "n_rows": int(in_it.sum()),
                    "n_tested_sites": int((in_it & columns.treated).sum())}
        keep = keep & ~in_it
    return keep, left_out


def _sizes(columns: SimpleNamespace, keep: np.ndarray) -> dict:
    if not keep.any():
        return {"n_treated": 0, "n_control": 0, "n_treated_sites": 0, "n_comparison_sites": 0,
                "n_clusters": 0, "n_treated_clusters": 0}
    return stats.used_sizes(columns.site_ids[keep], columns.treated[keep], columns.cohort[keep], columns.clusters[keep])


def _option_label(store: Store, key: str, value: str) -> str:
    return dict(options(store)[key])[value]


def describe(store: Store, spec: dict) -> str:
    """The choices that differ from the published comparison, in a few words."""
    parts = []
    if spec["sites"] != DEFAULT_SPEC["sites"]:
        parts.append(_option_label(store, "sites", spec["sites"]))
    if spec["borough"] != "all":
        parts.append(spec["borough"])
    if spec["size"] != "all":
        parts.append(f"{spec['size']} units")
    if spec["group"] != "all":
        parts.append(f"compared with {GROUP_LABEL[spec['group']].lower()}")
    if spec["cluster"] == "out":
        parts.append("without the largest cluster")
    if spec["cohort"] != "all":
        parts.append(f"without {spec['cohort']}")
    return ", ".join(parts) if parts else "The published comparison"


def _loosen(store: Store, columns: SimpleNamespace, spec: dict) -> list[dict]:
    """Each choice that could be undone, and how many sites undoing it would give."""
    moves = []
    for key, default in DEFAULT_SPEC.items():
        if spec[key] == default:
            continue
        keep, _ = _select(columns, {**spec, key: default})
        sizes = _sizes(columns, keep)
        moves.append({"key": key, "value": default, "label": _control_name(key),
                      "n_tested_sites": sizes["n_treated_sites"], "n_comparison_sites": sizes["n_comparison_sites"],
                      "enough": min(sizes["n_treated_sites"], sizes["n_comparison_sites"]) >= MIN_GROUP_N})
    return sorted(moves, key=lambda move: (not move["enough"], -min(move["n_tested_sites"], move["n_comparison_sites"])))


def _control_name(key: str) -> str:
    return {"sites": "which sites", "borough": "borough", "size": "building size", "group": "comparison group",
            "cluster": "the largest cluster", "cohort": "the left-out year"}[key]


def _number(value) -> float | None:
    """A float for JSON; NaN and infinity are not numbers a browser can parse."""
    value = float(value)
    return value if math.isfinite(value) else None


def _sentence(store: Store, spec: dict, result: dict, sizes: dict, left_out: dict | None) -> str:
    place = "" if spec["borough"] == "all" else f" in {spec['borough']}"
    size = "" if spec["size"] == "all" else f" with {spec['size']} units"
    level = stats.level_text(store.meta["constants"]["ci_level"])
    text = (f"Measured against {GROUP_PHRASE[spec['group']]} ({sizes['n_comparison_sites']:,} sites), injury crashes "
            f"within {store.meta['constants']['buffer_m']} m of {sizes['n_treated_sites']:,} {SITE_NOUN[spec['sites']]} "
            f"sites{place}{size} changed by {result['percent_change']:+.1f}% after completion ({level} interval "
            f"{result['percent_low']:+.1f}% to {result['percent_high']:+.1f}%, {sizes['n_clusters']:,} clusters).")
    if left_out:
        text += f" The largest cluster here, {left_out['n_rows']:,} rows, is left out."
    return text


@lru_cache(maxsize=CACHE_SIZE)
def _compute(store: Store, key: tuple) -> dict:
    spec = dict(key)
    columns = _columns(store)
    keep, left_out = _select(columns, spec)
    sizes = _sizes(columns, keep)
    answer = {"spec": spec, "label": describe(store, spec), "is_default": spec == DEFAULT_SPEC,
              "n_tested_sites": sizes["n_treated_sites"], "n_comparison_sites": sizes["n_comparison_sites"],
              "n_comparison_rows": sizes["n_control"], "n_clusters": sizes["n_clusters"],
              "n_tested_clusters": sizes["n_treated_clusters"], "left_out": left_out}

    def empty(message: str) -> dict:
        return {**answer, "status": "empty", "message": message, "loosen": _loosen(store, columns, spec),
                "estimate": None, "low": None, "high": None, "excludes_zero": False}

    noun = SITE_NOUN[spec["sites"]]
    if min(sizes["n_treated_sites"], sizes["n_comparison_sites"]) < MIN_GROUP_N:
        return empty(f"This choice leaves {sizes['n_treated_sites']:,} {noun} sites and "
                     f"{sizes['n_comparison_sites']:,} comparison sites. The project reports no estimate "
                     f"with fewer than {MIN_GROUP_N} of either.")
    result = stats.did_log_ratio(columns.before[keep], columns.after[keep], columns.treated[keep],
                                 columns.cohort[keep], columns.clusters[keep])
    low, high, estimate = (_number(result[name]) for name in ("percent_low", "percent_high", "percent_change"))
    if low is None or high is None or estimate is None:
        return empty("This choice leaves too few crashes for the resampling to give a steady interval.")
    excludes_zero = low > 0 or high < 0
    return {**answer, "status": "ok", "estimate": estimate, "low": low, "high": high, "excludes_zero": excludes_zero,
            "p_value": _number(result["p_value"]), "n_failed": int(result["n_failed"]),
            "tested_change": _number(stats.log_points_to_percent(result["treated_change"])),
            "comparison_change": _number(stats.log_points_to_percent(result["control_change"])),
            "tag": TAG_EXCLUDES if excludes_zero else TAG_UNCLEAR,
            "sentence": _sentence(store, spec, result, sizes, left_out)}


def run(store: Store, spec=None) -> dict:
    """One scenario. Never raises on hostile input: an unknown spec is answered as the default."""
    clean = normalise(store, spec)
    return dict(_compute(store, tuple(sorted(clean.items()))))


@lru_cache(maxsize=2)
def reference(store: Store) -> dict:
    """What the page holds still: the published result and the published robustness rows."""
    rows = []
    for row in store.robustness.itertuples():
        low, high, estimate = _number(row.percent_low), _number(row.percent_high), _number(row.percent_change)
        if estimate is None or low is None or high is None:
            continue
        rows.append({"check": row.check, "variant": row.variant, "kind": row.kind, "estimate": estimate, "low": low,
                     "high": high, "excludes_zero": bool(row.interval_excludes_zero),
                     "n_tested_sites": int(row.n_treated), "n_comparison_sites": int(row.n_comparison_sites)})
    published = next(row for row in rows if row["kind"] == "central")
    return {"published": published, "rows": rows, "defaults": DEFAULT_SPEC, "level": store.meta["constants"]["ci_level"],
            "level_text": stats.level_text(store.meta["constants"]["ci_level"])}

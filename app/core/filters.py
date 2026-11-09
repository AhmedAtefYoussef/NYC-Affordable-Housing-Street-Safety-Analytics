"""The filter model shared by the controls, the search parser, the data layer and the charts.

A `Filters` value is immutable and hashable, so it can key a cache and travel through a
`dcc.Store` as a plain dict. Empty tuples mean "no restriction".
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields

YEAR_START, YEAR_END = 2016, 2025
YEARS = list(range(YEAR_START, YEAR_END + 1))

BOROUGHS = ["Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"]
CONSTRUCTION_TYPES = ["New Construction", "Preservation"]
SIZE_BANDS = ["1-4", "5-19", "20-49", "50-149", "150+"]
FACTOR_GROUPS = [
    "Unspecified", "Pedestrian or cyclist error", "Road or environment", "Vehicle defect",
    "Impairment or medical", "Distraction", "Speed or aggressive driving",
    "Failure to yield or obey", "Improper maneuver", "Other",
]
HOUR_BANDS = ["Night", "Morning", "Afternoon", "Evening"]
HOUR_BAND_RANGES = {"Night": "00:00 to 05:59", "Morning": "06:00 to 11:59",
                    "Afternoon": "12:00 to 17:59", "Evening": "18:00 to 23:59"}

# Who was harmed. Each key names one count column of the crash tables (see pipeline/build/tables.py).
# `noun` completes "N ..." in chart titles; `label` is the dropdown text.
HARM = {
    "injury": {"label": "Anyone injured or killed", "noun": "injury crashes",
               "column": "n_injury"},
    "pedcyc": {"label": "Pedestrians or cyclists", "noun": "crashes that hurt a pedestrian or cyclist",
               "column": "n_pedcyc"},
    "ped": {"label": "Pedestrians", "noun": "crashes that hurt a pedestrian", "column": "n_ped"},
    "cyc": {"label": "Cyclists", "noun": "crashes that hurt a cyclist", "column": "n_cyc"},
    "mot": {"label": "Motorists", "noun": "crashes that hurt a motorist", "column": "n_mot"},
    "fatal": {"label": "Someone killed", "noun": "fatal crashes", "column": "n_fatal"},
    "all": {"label": "All reported crashes (see note)", "noun": "reported crashes",
            "column": "n_all"},
}
DEFAULT_HARM = "injury"
HARM_SHORT = {key: item["label"].replace(" (see note)", "") for key, item in HARM.items()}

# Where the crash happened relative to the housing sites (the spatial join of the two datasets).
SCOPE = {
    "city": "Anywhere in the city",
    "near": "Within 250 m of a housing site",
}
DEFAULT_SCOPE = "city"

# Study constants that live in meta.json; data.load() calls `configure` so every caption reads them from there.
BUFFER_M = 250        # default; `configure` replaces it from meta.json (the tests check they agree)
_CONSTANTS = {"buffer_m": BUFFER_M, "baseline_years": (2016, 2018), "event_window": 3}
HOUSING_ONLY_NEAR = "housing filters apply only near housing"


def configure(constants: dict) -> None:
    """Take the buffer distance, baseline years and event window from meta.json."""
    _CONSTANTS["buffer_m"] = int(constants["buffer_m"])
    _CONSTANTS["baseline_years"] = tuple(constants["baseline_years"])
    _CONSTANTS["event_window"] = int(constants["event_window"])


def buffer_m() -> int:
    return _CONSTANTS["buffer_m"]


def baseline_text() -> str:
    first, last = _CONSTANTS["baseline_years"]
    return f"{first} to {last}"


def pre_window_text() -> str:
    """'-3 to -1': the years before completion that make up the event-study baseline."""
    return f"-{_CONSTANTS['event_window']} to -1"


@dataclass(frozen=True)
class Filters:
    """One selection of the eight controls."""

    boroughs: tuple[str, ...] = ()
    year_from: int = YEAR_START
    year_to: int = YEAR_END
    construction: tuple[str, ...] = ()
    sizes: tuple[str, ...] = ()
    factors: tuple[str, ...] = ()
    hours: tuple[str, ...] = ()
    harm: str = DEFAULT_HARM
    scope: str = DEFAULT_SCOPE
    # not a control: kept so `describe` can say where a selection came from
    source: str = field(default="controls", compare=False)

    @property
    def years(self) -> list[int]:
        """The selected calendar years, in order."""
        return list(range(self.year_from, self.year_to + 1))

    @property
    def n_years(self) -> int:
        return self.year_to - self.year_from + 1

    @property
    def harm_noun(self) -> str:
        return HARM[self.harm]["noun"]

    @property
    def harm_column(self) -> str:
        return HARM[self.harm]["column"]

    @property
    def housing_filter_ignored(self) -> bool:
        """Construction or size is set but the crash location is the whole city, where they cannot apply."""
        return self.has_housing_filter and self.scope != "near"

    @property
    def has_housing_filter(self) -> bool:
        return bool(self.construction or self.sizes)

    def to_dict(self) -> dict:
        """JSON-safe dict for a dcc.Store."""
        return {key: (list(value) if isinstance(value, tuple) else value) for key, value in asdict(self).items()}


def _keep_known(values, allowed: list[str]) -> tuple[str, ...]:
    """Selected values in canonical order; anything unknown is dropped, and 'all selected' means no filter."""
    chosen = {value for value in values if isinstance(value, str)} if isinstance(values, (list, tuple)) else set()
    kept = tuple(value for value in allowed if value in chosen)
    return () if len(kept) == len(allowed) else kept


def _year(value, fallback: int) -> int:
    """A year clamped to the study window; `fallback` when the control is empty or malformed."""
    whole = _whole_number(value)
    return fallback if whole is None else max(YEAR_START, min(YEAR_END, whole))


def _whole_number(value) -> int | None:
    """`int(value)` for a number or numeric string; None for anything else (lists, dicts, NaN, Infinity)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def make_filters(boroughs=None, year_from=None, year_to=None, construction=None, sizes=None,
                 factors=None, hours=None, harm=None, scope=None, source: str = "controls") -> Filters:
    """Build a valid `Filters` from raw control values. Never raises: bad input falls back to the default."""
    first, last = sorted((_year(year_from, YEAR_START), _year(year_to, YEAR_END)))   # reversed = same range
    return Filters(
        boroughs=_keep_known(boroughs, BOROUGHS),
        year_from=first, year_to=last,
        construction=_keep_known(construction, CONSTRUCTION_TYPES),
        sizes=_keep_known(sizes, SIZE_BANDS),
        factors=_keep_known(factors, FACTOR_GROUPS),
        hours=_keep_known(hours, HOUR_BANDS),
        harm=harm if isinstance(harm, str) and harm in HARM else DEFAULT_HARM,
        scope=scope if isinstance(scope, str) and scope in SCOPE else DEFAULT_SCOPE,
        source=source,
    )


def from_dict(stored: dict | None) -> Filters:
    """Inverse of `Filters.to_dict`, tolerant of missing keys."""
    names = {item.name for item in fields(Filters)}
    return make_filters(**{key: value for key, value in (stored or {}).items() if key in names})


def reversed_years_note(year_from, year_to) -> str | None:
    """A sentence when the dropdowns hold a reversed range (it is read the other way round), else None."""
    first, last = _whole_number(year_from), _whole_number(year_to)
    if first is None or last is None or first <= last:
        return None
    return f"The years were entered as {first} to {last}; they are read as {last} to {first}."


def year_text(filters: Filters) -> str:
    """'2022' or '2019 to 2021'."""
    if filters.year_from == filters.year_to:
        return str(filters.year_from)
    return f"{filters.year_from} to {filters.year_to}"


def _joined(values: tuple[str, ...], everything: str) -> str:
    return ", ".join(values) if values else everything


def place_text(filters: Filters) -> str:
    """'Brooklyn' or 'all five boroughs'."""
    return _joined(filters.boroughs, "all five boroughs")


def crash_scope_text(filters: Filters) -> str:
    """One line naming every crash-side filter in force, for chart subtitles."""
    parts = [place_text(filters), year_text(filters), HARM_SHORT[filters.harm].lower()]
    if filters.factors:
        parts.append("factor: " + ", ".join(filters.factors).lower())
    if filters.hours:
        parts.append("time: " + ", ".join(filters.hours).lower())
    if filters.scope == "near":
        parts.append(nearest_site_text(filters))
    elif filters.housing_filter_ignored:
        parts.append(HOUSING_ONLY_NEAR + ": not applied to a city-wide count")
    return " · ".join(parts)


def nearest_site_text(filters: Filters) -> str:
    """Wording for the crash-location filter. Only the nearest site's kind is stored, so say exactly that."""
    if not filters.has_housing_filter:
        return f"within {buffer_m()} m of an affordable-housing site"
    kind = " or ".join(filters.construction).lower() if filters.construction else ""
    size = ("with " + ", ".join(filters.sizes) + " units") if filters.sizes else ""
    wanted = " ".join(part for part in (kind, size) if part)
    return f"nearest affordable-housing site within {buffer_m()} m is {wanted}"


def housing_kind_text(filters: Filters) -> str:
    """'new construction sites with 150+ units' or 'any affordable-housing site'."""
    if not filters.has_housing_filter:
        return "any affordable-housing site"
    kind = " or ".join(filters.construction).lower() if filters.construction else "affordable-housing"
    text = f"{kind} sites"
    if filters.sizes:
        text += " with " + ", ".join(filters.sizes) + " units"
    return text


def housing_scope_text(filters: Filters) -> str:
    """One line naming every housing-side filter in force."""
    parts = [place_text(filters), f"completed {year_text(filters)}",
             _joined(filters.construction, "both construction types").lower()]
    if filters.sizes:
        parts.append("size: " + ", ".join(filters.sizes) + " units")
    return " · ".join(parts)


def chips(filters: Filters) -> list[tuple[str, str]]:
    """(label, value) pairs for every control, used by the report header."""
    return [
        ("Borough", _joined(filters.boroughs, "All")),
        ("Years", year_text(filters)),
        ("Construction", _joined(filters.construction, "Both types")),
        ("Building size", _joined(filters.sizes, "Any") + (" units" if filters.sizes else "")),
        ("Contributing factor", _joined(filters.factors, "Any")),
        ("Time of day", _joined(filters.hours, "Any")),
        ("Who was harmed", HARM_SHORT[filters.harm]),
        ("Crash location", SCOPE[filters.scope]),
    ]

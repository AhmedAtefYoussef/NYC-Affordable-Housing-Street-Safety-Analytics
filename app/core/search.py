"""Search mode: turn a typed query into filter values. Pure functions, no Dash and no data.

    parse_query("bronx pedestrians night 2019-2021")
    -> ParsedQuery(values={"boroughs": ["Bronx"], "harm": "ped", "hours": ["Night"],
                           "year_from": 2019, "year_to": 2021}, understood=[...], unmatched=[])

The parser is a vocabulary lookup, longest phrase first, so "staten island" wins over "island"
and "new construction" over "new". After the exact pass, a leftover word of five or more letters
that is a close misspelling of a borough or construction word is corrected and shown as such
("Brooklyn (from brookyln)"). Any other word it does not know is reported back in `unmatched`
and changes nothing.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from app.core.filters import (
    BOROUGHS,
    CONSTRUCTION_TYPES,
    FACTOR_GROUPS,
    HARM_SHORT,
    HOUR_BANDS,
    SCOPE,
    SIZE_BANDS,
    YEAR_END,
    YEAR_START,
    Filters,
    make_filters,
)

# phrase -> canonical value, one table per control -------------------------------------------------
BOROUGH_WORDS = {
    "bronx": "Bronx", "the bronx": "Bronx", "bx": "Bronx",
    "brooklyn": "Brooklyn", "bk": "Brooklyn", "bklyn": "Brooklyn", "kings county": "Brooklyn",
    "manhattan": "Manhattan", "mn": "Manhattan", "new york county": "Manhattan",
    "queens": "Queens", "qns": "Queens",
    "staten island": "Staten Island", "staten": "Staten Island", "si": "Staten Island",
    "richmond county": "Staten Island",
}
CONSTRUCTION_WORDS = {
    "new construction": "New Construction", "new buildings": "New Construction",
    "new building": "New Construction", "new builds": "New Construction",
    "new build": "New Construction", "newly built": "New Construction", "new": "New Construction",
    "preservation": "Preservation", "preserved": "Preservation", "renovation": "Preservation",
    "renovations": "Preservation", "renovated": "Preservation", "rehab": "Preservation",
    "rehabilitation": "Preservation",
}
# A size word selects one or more of the five unit bands.
SIZE_WORDS = {
    "small buildings": ("1-4", "5-19"), "small": ("1-4", "5-19"),
    "medium buildings": ("20-49",), "mid-size": ("20-49",), "medium": ("20-49",),
    "large buildings": ("50-149", "150+"), "big buildings": ("50-149", "150+"),
    "large": ("50-149", "150+"), "big": ("50-149", "150+"),
    "towers": ("150+",), "tower": ("150+",), "150+": ("150+",), "150+ units": ("150+",),
    "1-4 units": ("1-4",), "5-19 units": ("5-19",), "20-49 units": ("20-49",),
    "50-149 units": ("50-149",),
}
FACTOR_WORDS = {
    "speeding": "Speed or aggressive driving", "speed": "Speed or aggressive driving",
    "aggressive driving": "Speed or aggressive driving", "aggressive": "Speed or aggressive driving",
    "road rage": "Speed or aggressive driving", "tailgating": "Speed or aggressive driving",
    "following too closely": "Speed or aggressive driving",
    "distracted driving": "Distraction", "distracted": "Distraction", "distraction": "Distraction",
    "inattention": "Distraction", "texting": "Distraction", "phone": "Distraction",
    "cell phone": "Distraction",
    "failure to yield": "Failure to yield or obey", "yield": "Failure to yield or obey",
    "red light": "Failure to yield or obey", "ran a light": "Failure to yield or obey",
    "disregarded signal": "Failure to yield or obey",
    "drunk driving": "Impairment or medical", "drunk": "Impairment or medical",
    "alcohol": "Impairment or medical", "dui": "Impairment or medical", "dwi": "Impairment or medical",
    "drugs": "Impairment or medical", "impaired": "Impairment or medical",
    "impairment": "Impairment or medical", "fatigue": "Impairment or medical",
    "drowsy": "Impairment or medical", "asleep": "Impairment or medical",
    "medical": "Impairment or medical", "illness": "Impairment or medical",
    "road conditions": "Road or environment", "pavement": "Road or environment",
    "slippery": "Road or environment", "glare": "Road or environment",
    "obstruction": "Road or environment", "debris": "Road or environment",
    "vehicle defect": "Vehicle defect", "defect": "Vehicle defect", "brakes": "Vehicle defect",
    "brake failure": "Vehicle defect", "tire": "Vehicle defect", "tyre": "Vehicle defect",
    "steering": "Vehicle defect",
    "pedestrian error": "Pedestrian or cyclist error", "cyclist error": "Pedestrian or cyclist error",
    "jaywalking": "Pedestrian or cyclist error",
    "improper turn": "Improper maneuver", "turning": "Improper maneuver",
    "lane change": "Improper maneuver", "unsafe lane change": "Improper maneuver",
    "backing": "Improper maneuver", "reversing": "Improper maneuver",
    "passing": "Improper maneuver", "inexperience": "Improper maneuver",
    "unspecified": "Unspecified", "no factor": "Unspecified", "unknown factor": "Unspecified",
}
HOUR_WORDS = {
    "late night": "Night", "overnight": "Night", "night": "Night", "nights": "Night",
    "at night": "Night",
    "morning": "Morning", "mornings": "Morning",
    "afternoon": "Afternoon", "afternoons": "Afternoon", "midday": "Afternoon",
    "evening": "Evening", "evenings": "Evening",
}
HARM_WORDS = {
    "pedestrians": "ped", "pedestrian": "ped", "peds": "ped", "ped": "ped", "walking": "ped", "on foot": "ped", "walkers": "ped",
    "cyclists": "cyc", "cyclist": "cyc", "bicyclists": "cyc", "bicyclist": "cyc",
    "bikes": "cyc", "bike": "cyc", "bicycle": "cyc", "bicycles": "cyc", "cycling": "cyc",
    "biking": "cyc",
    "motorists": "mot", "motorist": "mot", "drivers": "mot", "driver": "mot",
    "passengers": "mot", "vehicle occupants": "mot",
    "fatal": "fatal", "fatalities": "fatal", "fatality": "fatal", "deadly": "fatal",
    "killed": "fatal", "deaths": "fatal", "death": "fatal",
    "injuries": "injury", "injury": "injury", "injured": "injury", "hurt": "injury",
    "all crashes": "all", "every crash": "all", "all collisions": "all", "property damage": "all",
    "any crash": "all",
}
SCOPE_WORDS = {
    "near affordable housing": "near", "near housing": "near", "near sites": "near",
    "near the sites": "near", "near buildings": "near", "around housing": "near",
    "next to housing": "near", "within 250 m": "near", "within 250m": "near",
    "near": "near", "nearby": "near",
    "citywide": "city", "city-wide": "city", "anywhere": "city",
}
# Words that carry no filter and should not be reported as "not understood".
STOP_WORDS = {
    "a", "an", "and", "the", "of", "in", "on", "at", "to", "for", "with", "by", "from", "or",
    "crash", "crashes", "collision", "collisions", "accident", "accidents", "housing",
    "affordable", "building", "buildings", "site", "sites", "units", "unit", "street", "streets",
    "show", "me", "only", "during", "between", "since", "before", "after", "until", "through",
    "people", "who", "were", "was", "that", "involving", "construction", "year", "years", "nyc",
    "new", "york", "city", "report", "data", "time", "factor", "caused", "m",
}

NEUTRAL_PHRASES = ["new york city", "new york", "nyc"]

LABELS = {"boroughs": "Borough", "years": "Years", "construction": "Construction",
          "sizes": "Building size", "factors": "Contributing factor", "hours": "Time of day",
          "harm": "Who was harmed", "scope": "Crash location"}

FUZZY_MIN_LETTERS, FUZZY_CUTOFF = 5, 0.8
_YEAR = r"((?:19|20)\d{2})"
_DASH = "(?:-|\\u2013|\\u2014|to|through|thru|and)"   # a hyphen, or the en or em dash a phone keyboard inserts


@dataclass
class ParsedQuery:
    """What the parser took from one query."""

    text: str
    values: dict = field(default_factory=dict)        # only the controls the query set
    understood: list[tuple[str, str, str]] = field(default_factory=list)   # (typed text, control, value)
    unmatched: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()

    def filters(self) -> Filters:
        """Defaults for every control the query did not mention, the parsed value for the rest."""
        return make_filters(**self.values, source="search")


def _clamp(year: int) -> int:
    return max(YEAR_START, min(YEAR_END, year))


def _take_years(text: str) -> tuple[tuple[int, int] | None, str | None, str, bool]:
    """Find a year or a year range.

    Returns (range, the matched text, the text with it blanked out, whether the range was clamped to the
    data). Two separate bare years are read as a range.
    """
    patterns = [
        (rf"\b(?:between\s+|from\s+)?{_YEAR}\s*{_DASH}\s*{_YEAR}\b", lambda m: (int(m[1]), int(m[2]))),
        (rf"\b(?:since|from|starting)\s+{_YEAR}\b", lambda m: (int(m[1]), YEAR_END)),
        (rf"\bafter\s+{_YEAR}\b", lambda m: (int(m[1]) + 1, YEAR_END)),
        (rf"\bbefore\s+{_YEAR}\b", lambda m: (YEAR_START, int(m[1]) - 1)),
        (rf"\b(?:until|through|thru|up to)\s+{_YEAR}\b", lambda m: (YEAR_START, int(m[1]))),
        (rf"\b{_YEAR}\b", lambda m: (int(m[1]), int(m[1]))),
    ]
    for pattern, to_range in patterns:
        match = re.search(pattern, text)
        if match:
            first, last = to_range(match)
            if pattern in (patterns[0][0], patterns[-1][0]):    # "2020-2018" is the same range as "2018-2020"
                first, last = sorted((first, last))
            typed = match.group(0).strip()
            blanked = text[:match.start()] + " " + text[match.end():]
            if pattern == patterns[-1][0]:                   # a second bare year closes the range
                other = re.search(patterns[-1][0], blanked)
                if other and YEAR_START <= int(other[1]) <= YEAR_END and YEAR_START <= first <= YEAR_END:
                    first, last = sorted((first, int(other[1])))
                    typed = f"{typed} {other.group(0).strip()}"
                    blanked = blanked[:other.start()] + " " + blanked[other.end():]
            if first > last or last < YEAR_START or first > YEAR_END:   # outside the data: set nothing
                return None, typed, blanked, False
            clamped = first < YEAR_START or last > YEAR_END
            return (_clamp(first), _clamp(last)), typed, blanked, clamped
    return None, None, text, False


MAX_QUERY_CHARS = 200


def _take_phrases(text: str, table: dict) -> tuple[list[tuple[str, object]], str]:
    """Every phrase of `table` found in `text` (longest first), and the text with them blanked out."""
    found = []
    for phrase in sorted(table, key=len, reverse=True):
        pattern = rf"(?<![\w+]){re.escape(phrase)}(?![\w+])"
        text, count = re.subn(pattern, " ", text)   # one pass per phrase, not one search per match
        found.extend([(phrase, table[phrase])] * count)
    return found, text


def _ordered(values, canonical: list[str]) -> list[str]:
    chosen = set(values)
    return [value for value in canonical if value in chosen]


def _correct_spelling(parsed: ParsedQuery, leftover: list[str]) -> list[str]:
    """Apply close misspellings of borough and construction words; return the words still not understood."""
    vocabulary = {word: ("boroughs", value, BOROUGHS) for word, value in BOROUGH_WORDS.items()}
    vocabulary.update({word: ("construction", value, CONSTRUCTION_TYPES)
                       for word, value in CONSTRUCTION_WORDS.items()})
    vocabulary = {word: target for word, target in vocabulary.items()
                  if " " not in word and len(word) >= FUZZY_MIN_LETTERS}
    still_unmatched = []
    for word in leftover:
        close = []
        if len(word) >= FUZZY_MIN_LETTERS:
            close = difflib.get_close_matches(word, [*vocabulary, "construction"], n=1, cutoff=FUZZY_CUTOFF)
        if not close:
            still_unmatched.append(word)
        elif close[0] != "construction":           # a misspelt "construction" only repeats "new construction"
            key, value, canonical = vocabulary[close[0]]
            parsed.values[key] = _ordered([*parsed.values.get(key, []), value], canonical)
            parsed.understood.append((word, LABELS[key], f"{value} (from {word})"))
    return still_unmatched


_NEGATION = r"(?<![\w-])(?:not|no|non|except|excluding|exclude|without)(?:-|\s+)"
_YEAR_TERM = r"(?:19|20)\d{2}(?:\s*(?:-|–|—|to)\s*(?:19|20)\d{2})?"


def _negated_terms(text: str) -> tuple[str, list[str]]:
    """Remove each negation word and the term after it. Negation is never applied, only reported."""
    tables = [BOROUGH_WORDS, FACTOR_WORDS, HOUR_WORDS, CONSTRUCTION_WORDS, HARM_WORDS, SIZE_WORDS, SCOPE_WORDS]
    phrases = sorted({phrase for table in tables for phrase in table}, key=len, reverse=True)
    term = rf"(?:{_YEAR_TERM}|{'|'.join(re.escape(phrase) for phrase in phrases)}|[a-z0-9+]+)"
    pattern = re.compile(rf"{_NEGATION}({term}(?:\s+(?:or|and|nor)\s+{term})*)(?![\w+])")
    reported = []

    def blank(match):
        reported.append(f"negation is not supported: {match.group(1)}")
        return " "

    return pattern.sub(blank, text), reported


SPECIFIC_HARM = ("ped", "cyc", "mot")      # road users; these win over the generic injury, fatal and all words


def _read_years(parsed: ParsedQuery, remaining: str, notes: list[str]) -> str:
    years, typed, remaining, clamped = _take_years(remaining)
    if typed and not years:
        notes.append(f"{typed}: the data covers {YEAR_START} to {YEAR_END}")
    if years:
        parsed.values["year_from"], parsed.values["year_to"] = years
        shown = str(years[0]) if years[0] == years[1] else f"{years[0]} to {years[1]}"
        if clamped:
            shown += f" (data covers {YEAR_START} to {YEAR_END})"
        parsed.understood.append((typed, LABELS["years"], shown))
    return remaining


def _read_scope(parsed: ParsedQuery, remaining: str) -> str:
    found, remaining = _take_phrases(remaining, SCOPE_WORDS)
    if found:
        parsed.values["scope"] = found[0][1]
        parsed.understood.append((found[0][0], LABELS["scope"], SCOPE[found[0][1]]))
    return remaining


def _read_multi(parsed: ParsedQuery, remaining: str, key: str, table: dict, canonical: list[str]) -> str:
    found, remaining = _take_phrases(remaining, table)
    if found:
        parsed.values[key] = _ordered([value for _, value in found], canonical)
        parsed.understood.extend((phrase, LABELS[key], value) for phrase, value in found)
    return remaining


def _read_sizes(parsed: ParsedQuery, remaining: str) -> str:
    found, remaining = _take_phrases(remaining, SIZE_WORDS)
    if found:
        parsed.values["sizes"] = _ordered([band for _, group in found for band in group], SIZE_BANDS)
        for phrase, group in found:
            parsed.understood.append((phrase, LABELS["sizes"], ", ".join(group) + " units"))
    return remaining


def _choose_harm(kinds: set[str]) -> tuple[str, set[str]]:
    """The one 'who was harmed' option for the kinds named, and the kinds it covers.

    Pedestrians with cyclists are one option. Otherwise a road user beats the generic words, so
    "bike injuries" is cyclists and "pedestrians killed" is pedestrians.
    """
    if {"ped", "cyc"} <= kinds:
        return "pedcyc", {"ped", "cyc"}
    chosen = next((kind for kind in SPECIFIC_HARM if kind in kinds), None)
    if chosen is None:
        chosen = next(kind for kind in ("fatal", "injury", "all") if kind in kinds)
    return chosen, {chosen}


def _read_harm(parsed: ParsedQuery, harm_found: list[tuple[str, str]], notes: list[str]) -> None:
    if not harm_found:
        return
    harm, used = _choose_harm({value for _, value in harm_found})
    parsed.values["harm"] = harm
    typed = " + ".join(dict.fromkeys(phrase for phrase, value in harm_found if value in used))
    parsed.understood.append((typed, LABELS["harm"], HARM_SHORT[harm]))
    has_road_user = any(value in SPECIFIC_HARM for _, value in harm_found)
    for phrase, value in dict.fromkeys(harm_found):
        generic_beside_road_user = has_road_user and value not in SPECIFIC_HARM
        if value not in used and not generic_beside_road_user:
            notes.append(f"{phrase}: only one 'who was harmed' option applies at a time")


def _link_housing_to_location(parsed: ParsedQuery) -> None:
    """Construction and size describe the nearest housing site, so they only act on crashes near housing.

    A query that names one and does not name a crash location therefore means 'near housing'.
    """
    restricts = make_filters(construction=parsed.values.get("construction"), sizes=parsed.values.get("sizes"))
    if restricts.has_housing_filter and "scope" not in parsed.values:
        parsed.values["scope"] = "near"
        parsed.understood.append(("housing filter", LABELS["scope"], SCOPE["near"]))


def parse_query(text: str | None) -> ParsedQuery:
    """Parse a free-text query into control values, the pieces understood and the words left over."""
    text = (text if isinstance(text, str) else "")[:MAX_QUERY_CHARS]   # a long paste is cut, not parsed
    parsed = ParsedQuery(text=text)
    remaining = " " + re.sub(r"[,;:!?()\"']", " ", (text or "").lower()) + " "
    remaining, notes = _negated_terms(remaining)
    remaining = _read_years(parsed, remaining, notes)
    # "near housing" is read before the borough and construction tables see its words. Boroughs come
    # before the place names that contain a filter word, so "new york county" is Manhattan.
    remaining = _read_scope(parsed, remaining)
    remaining = _read_multi(parsed, remaining, "boroughs", BOROUGH_WORDS, BOROUGHS)
    _, remaining = _take_phrases(remaining, dict.fromkeys(NEUTRAL_PHRASES))
    # Factors come before road users, so that "pedestrian error" is read as a factor.
    remaining = _read_multi(parsed, remaining, "factors", FACTOR_WORDS, FACTOR_GROUPS)
    harm_found, remaining = _take_phrases(remaining, HARM_WORDS)
    remaining = _read_multi(parsed, remaining, "hours", HOUR_WORDS, HOUR_BANDS)
    remaining = _read_multi(parsed, remaining, "construction", CONSTRUCTION_WORDS, CONSTRUCTION_TYPES)
    remaining = _read_sizes(parsed, remaining)
    _read_harm(parsed, harm_found, notes)
    _link_housing_to_location(parsed)
    words = re.findall(r"[a-z0-9+'-]+", remaining)
    leftover = list(dict.fromkeys(word for word in words if word not in STOP_WORDS and word.strip("-'+")))
    parsed.unmatched = notes + _correct_spelling(parsed, leftover)
    return parsed

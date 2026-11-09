"""Tests for the website: the search parser, the data layer, the report and the Dash callbacks.

    python -m pytest tests/test_site.py -q

The callback tests post to Dash's own endpoint through the Flask test client, with the same
payload a browser sends, so they exercise routing, callbacks and JSON serialisation together.
"""
from __future__ import annotations

import dataclasses
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

from app.analysis.story_text import signed
from app.core import data, stats
from app.core.filters import BOROUGHS, FACTOR_GROUPS, HOUR_BANDS, YEAR_END, YEAR_START, from_dict, make_filters
from app.core.search import BOROUGH_WORDS, CONSTRUCTION_WORDS, FACTOR_WORDS, HOUR_WORDS, SIZE_WORDS, parse_query
from app.ui.callbacks import CONTROL_IDS, control_values
from app.ui.report import CHART_KEYS, build_report

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def store():
    return data.load()


# ---------------------------------------------------------------------------------------------
# Search parser (pure functions, no data)
# ---------------------------------------------------------------------------------------------
def test_assignment_example_query():
    parsed = parse_query("Brooklyn 2022 new construction")
    assert parsed.values == {"year_from": 2022, "year_to": 2022, "boroughs": ["Brooklyn"],
                             "construction": ["New Construction"], "scope": "near"}
    assert parsed.unmatched == []


def test_second_example_query():
    parsed = parse_query("bronx pedestrians night 2019-2021")
    assert parsed.values == {"year_from": 2019, "year_to": 2021, "boroughs": ["Bronx"],
                             "hours": ["Night"], "harm": "ped"}
    assert [label for _, label, _ in parsed.understood] == ["Years", "Borough", "Time of day", "Who was harmed"]


@pytest.mark.parametrize("query, expected", [
    ("staten island fatal since 2021", {"boroughs": ["Staten Island"], "harm": "fatal", "year_from": 2021,
                                        "year_to": YEAR_END}),
    ("queens and the bronx cyclists speeding", {"boroughs": ["Bronx", "Queens"], "harm": "cyc",
                                                "factors": ["Speed or aggressive driving"]}),
    ("pedestrians and cyclists before 2020", {"harm": "pedcyc", "year_from": YEAR_START, "year_to": 2019}),
    ("manhattan large buildings near housing", {"boroughs": ["Manhattan"], "sizes": ["50-149", "150+"],
                                               "scope": "near"}),
    ("preservation evening distracted driving", {"construction": ["Preservation"], "hours": ["Evening"],
                                                 "factors": ["Distraction"], "scope": "near"}),
    ("all crashes 2016 to 2018", {"harm": "all", "year_from": 2016, "year_to": 2018}),
])
def test_queries(query, expected):
    assert parse_query(query).values == expected


def test_corrected_typo_is_shown_in_the_understood_chip():
    parsed = parse_query("Brookyln 2022")
    assert ("brookyln", "Borough", "Brooklyn (from brookyln)") in parsed.understood
    clamped = parse_query("bronx 1999-2030")
    assert "data covers 2016 to 2025" in clamped.understood[0][2]


def test_unknown_words_are_reported_and_change_nothing():
    parsed = parse_query("brooklyn unicorns 2022")
    assert parsed.unmatched == ["unicorns"]
    assert parsed.values == {"year_from": 2022, "year_to": 2022, "boroughs": ["Brooklyn"]}
    nothing = parse_query("zzz qqq")
    assert nothing.values == {} and nothing.understood == [] and nothing.unmatched == ["zzz", "qqq"]


def test_year_outside_the_data_sets_nothing():
    assert "year_from" not in parse_query("brooklyn 1999").values
    assert parse_query("").is_empty and parse_query(None).values == {}


def test_parser_vocabulary_maps_to_real_filter_values():
    assert set(BOROUGH_WORDS.values()) == set(BOROUGHS)
    assert set(FACTOR_WORDS.values()) <= set(FACTOR_GROUPS)
    assert set(HOUR_WORDS.values()) <= set(HOUR_BANDS)
    assert set(CONSTRUCTION_WORDS.values()) == {"New Construction", "Preservation"}
    assert all(make_filters(sizes=list(bands)).sizes == bands for bands in SIZE_WORDS.values())


# ---------------------------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------------------------
def test_filters_are_forgiving_and_round_trip():
    filters = make_filters(boroughs=["Brooklyn", "Atlantis"], year_from=2030, year_to="2019", harm="nonsense")
    assert filters.boroughs == ("Brooklyn",) and (filters.year_from, filters.year_to) == (2019, YEAR_END)
    assert filters.harm == "injury"
    assert from_dict(filters.to_dict()) == filters
    assert make_filters(boroughs=["Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"]).boroughs == ()
    assert control_values(make_filters()) == [[], YEAR_START, YEAR_END, [], [], [], [], "injury", "city"]


# ---------------------------------------------------------------------------------------------
# Data layer: the exported tables agree with each other and with the notebook's totals
# ---------------------------------------------------------------------------------------------
def test_cubes_agree_on_totals(store):
    rows = store.meta["rows"]
    assert int(store.crash.counts["n_all"].sum()) == rows["crashes"]
    assert int(store.hour.counts["n_all"].sum()) == rows["crashes"]
    assert int(store.crash.counts["n_injury"].sum()) == rows["injury_crashes"]
    assert int(store.grid.counts["n_all"].sum()) == rows["crashes_located"]
    assert int(store.zips.counts["n_injury"].sum()) == int(store.zip_year["injury_crashes"].sum())


def test_default_selection_matches_the_notebook(store):
    filters = make_filters()
    numbers = data.headline_numbers(store, filters)
    assert numbers["crashes"] == store.meta["rows"]["injury_crashes"]
    assert int(data.weekday_hour(store, filters).sum()) == numbers["crashes"]
    assert int(data.factor_mix(store, filters).sum()) == numbers["crashes"]
    yearly = data.crash_trend(store, filters).sum(axis=1) + 0
    assert int(yearly.sum()) == numbers["crashes"] - numbers["crashes_unknown_borough"]

    questions, rq7 = store.results["questions"], store.results["detail"]["rq7"]
    new_only = make_filters(construction=["New Construction"])
    # RQ7 is headlined on new construction; with both types the site gives the notebook's pooled row.
    for selection, expected in [(data.site_selection(store, new_only), questions["RQ7"]),
                                (data.site_selection(store, filters), rq7["pooled"])]:
        assert selection["excess"] == pytest.approx(expected["estimate"], abs=1e-6)
        assert selection["low"] == pytest.approx(expected["low"], abs=1e-6)
        assert selection["high"] == pytest.approx(expected["high"], abs=1e-6)
        assert selection["n"] == expected["n"]
    did = data.event_study(store, new_only)["treated"]["New Construction"]["did"]
    assert did["percent_change"] == pytest.approx(questions["RQ3"]["estimate"], abs=1e-9)
    assert did["percent_low"] == pytest.approx(questions["RQ3"]["low"], abs=1e-9)
    assert did["percent_high"] == pytest.approx(questions["RQ3"]["high"], abs=1e-9)
    both = data.event_study(store, filters)
    assert both["difference"]["percent_change"] == pytest.approx(questions["RQ5"]["estimate"], abs=1e-9)


def test_filters_narrow_every_table_consistently(store):
    filters = make_filters(boroughs=["Brooklyn"], year_from=2022, year_to=2022, harm="ped", hours=["Night"])
    numbers = data.headline_numbers(store, filters)
    assert 0 < numbers["crashes"] < store.meta["rows"]["injury_crashes"]
    assert int(data.weekday_hour(store, filters).sum()) == numbers["crashes"]
    assert int(data.weekday_hour(store, filters)[:, 6:].sum()) == 0          # night is 00:00 to 05:59
    trend = data.crash_trend(store, filters)
    assert list(trend.columns) == ["Brooklyn"] and len(trend) == 12 and trend.attrs["monthly"]
    near = data.headline_numbers(store, make_filters(boroughs=["Brooklyn"], scope="near"))
    assert near["crashes"] == near["crashes_near"] <= near["crashes_anywhere"]


# ---------------------------------------------------------------------------------------------
# Report: every selection yields eight figures, including selections with no data
# ---------------------------------------------------------------------------------------------
SELECTIONS = {
    "default": {},
    "brooklyn 2022 new construction": {"boroughs": ["Brooklyn"], "year_from": 2022, "year_to": 2022,
                                       "construction": ["New Construction"]},
    "bronx pedestrians night": {"boroughs": ["Bronx"], "year_from": 2019, "year_to": 2021, "harm": "ped",
                                "hours": ["Night"]},
    "all crashes": {"harm": "all"},
    "near large new buildings": {"scope": "near", "construction": ["New Construction"], "sizes": ["150+"],
                                 "harm": "cyc"},
    "empty": {"boroughs": ["Staten Island"], "year_from": 2020, "year_to": 2020, "factors": ["Vehicle defect"],
              "hours": ["Night"], "harm": "fatal", "scope": "near", "sizes": ["150+"]},
}


@pytest.mark.parametrize("name", SELECTIONS)
def test_report_builds_for_every_selection(store, name):
    report = build_report(store, make_filters(**SELECTIONS[name]))
    assert list(report["panels"]) == CHART_KEYS
    for key, panel in report["panels"].items():
        assert isinstance(panel.figure, go.Figure), key
        assert panel.scope and panel.note, key
        json.dumps(panel.figure.to_plotly_json(), default=_plain)            # serialisable


def test_empty_selection_shows_empty_states_not_broken_charts(store):
    report = build_report(store, make_filters(**SELECTIONS["empty"]))
    assert report["numbers"]["crashes"] == 0
    for key in ["trend", "factors", "heatmap", "scatter", "event", "selection"]:
        figure = report["panels"][key].figure
        assert len(figure.data) == 0 and figure.layout.annotations, key
    assert "No crashes match" in str(report["header"])


def test_all_crashes_carries_the_reporting_caution(store):
    report = build_report(store, make_filters(harm="all"))
    assert "cannot be compared across 2020" in str(report["header"])
    assert "cannot be compared across 2020" not in str(build_report(store, make_filters())["header"])


# ---------------------------------------------------------------------------------------------
# Story: the text is generated from the exported results, so it must quote them
# ---------------------------------------------------------------------------------------------
def _text(component) -> str:
    """All strings inside a Dash component tree, joined."""
    if component is None:
        return ""
    if isinstance(component, (str, int, float)):
        return str(component)
    if isinstance(component, (list, tuple)):
        return " ".join(_text(child) for child in component)
    return _text(getattr(component, "children", None))


def test_story_quotes_the_exported_results(store):
    from app.ui import story
    questions = store.results["questions"]
    assert len(questions) == 10 and all(item["sentence"] for item in questions.values())
    hero = _text(story.hero(store))
    assert story.signed(questions["RQ3"]["estimate"]) in hero
    assert f"{50 + questions['RQ7']['estimate']:.0f}th" in hero and f"{questions['RQ7']['n']:,}" in hero
    findings = _text(story.findings(store))
    for item in questions.values():
        assert item["sentence"].split("; the interval includes zero")[0] in findings
    page = " ".join(_text(part(store)) for part in
                    [story.hero, story.findings, story.limits, story.impact, story.data_and_method, story.footer])
    for banned in ["—", "causes", "caused by", "leads to", "because of the housing"]:
        assert banned not in page, banned


def test_robustness_table_matches_the_story(store):
    table = store.robustness
    assert (table["kind"] == "central").sum() == 1
    central = table[table["kind"] == "central"].iloc[0]
    assert central["percent_change"] == pytest.approx(store.results["questions"]["RQ3"]["estimate"], abs=1e-9)
    assert set(store.results["detail"]["unscreened_variants"]) <= set(table["variant"])


def test_site_imports_nothing_from_the_old_code():
    """The deployed site must run from app/ and app/data/ alone."""
    code = ("import sys; import app.app; "
            "bad = [name for name in sys.modules if name.split('.')[0] in {'pipeline', 'analysis', 'config'}]; "
            "print(bad)")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr[-800:]
    assert result.stdout.strip().splitlines()[-1] == "[]"


def _plain(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return str(value)


# ---------------------------------------------------------------------------------------------
# Dash callbacks over HTTP (Flask test client)
# ---------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    from app.app import server
    return server.test_client()


def _callback(client, trigger: str, values: dict, output: str = ""):
    """Post one callback the way the browser does and return the 'response' part of the reply.

    `output` picks, among the callbacks that `trigger` fires, the one writing that output.
    """
    dependencies = client.get("/_dash-dependencies").get_json()
    spec = next(item for item in dependencies if output in item["output"] and any(
        f"{entry['id']}.{entry['property']}" == trigger for entry in item["inputs"]))

    def with_values(entries):
        return [{"id": entry["id"], "property": entry["property"],
                 "value": values.get(f"{entry['id']}.{entry['property']}")} for entry in entries]

    outputs = [{"id": part.rsplit(".", 1)[0], "property": part.rsplit(".", 1)[1].split("@")[0]}
               for part in spec["output"].strip(".").split("...")]
    payload = {"output": spec["output"], "outputs": outputs if len(outputs) > 1 else outputs[0],
               "inputs": with_values(spec["inputs"]), "state": with_values(spec["state"]),
               "changedPropIds": [trigger]}
    reply = client.post("/_dash-update-component", json=payload)
    assert reply.status_code == 200, reply.get_data(as_text=True)[:500]
    return reply.get_json()["response"]


def _control_state(filters) -> dict:
    return {f"{control_id}.value": value for control_id, value in zip(CONTROL_IDS, control_values(filters))}


def test_page_and_grid_are_served(client):
    page = client.get("/")
    assert page.status_code == 200 and b"design-tokens" in page.data
    layout = client.get("/_dash-layout").get_data(as_text=True)
    assert "Generate report" in layout and "Do injury crashes rise" in layout
    grid = client.get("/data/crash-grid.geojson", headers={"Accept-Encoding": "gzip"})
    assert grid.status_code == 200 and grid.headers["Content-Encoding"] == "gzip"


def test_search_callback_fills_the_dropdowns(client):
    response = _callback(client, "search.value", {"search.value": "Brooklyn 2022 new construction"})
    assert response["f-borough"]["value"] == ["Brooklyn"]
    assert (response["f-year-from"]["value"], response["f-year-to"]["value"]) == (2022, 2022)
    assert response["f-construction"]["value"] == ["New Construction"]
    assert "Understood" in json.dumps(response["search-feedback"])


@pytest.mark.parametrize("name", SELECTIONS)
def test_generate_report_callback_updates_every_chart(client, name):
    filters = make_filters(**SELECTIONS[name])
    response = _callback(client, "generate.n_clicks", {"generate.n_clicks": 1, **_control_state(filters)})
    for key in CHART_KEYS:
        assert "layout" in response[f"fig-{key}"]["figure"], key
        assert response[f"scope-{key}"]["children"] and response[f"note-{key}"]["children"], key
    assert from_dict(response["report-filters"]["data"]) == filters
    assert response["report-tiles"]["children"]


def test_enter_in_the_search_box_generates_from_the_query(client):
    stale_controls = _control_state(make_filters())                 # dropdowns have not caught up yet
    response = _callback(client, "search.n_submit", {"search.n_submit": 1, **stale_controls,
                                                     "search.value": "bronx pedestrians night 2019-2021"})
    shown = from_dict(response["report-filters"]["data"])
    assert shown == make_filters(boroughs=["Bronx"], year_from=2019, year_to=2021, hours=["Night"], harm="ped")
    assert "From your search" in json.dumps(response["report-header"])


# =============================================================================================
# Added coverage: a wider query list, conservation across filters, every chart builder on its own,
# and the wiring of the Generate report button.
# =============================================================================================
from app.ui import charts  # noqa: E402

QUERY_TABLE = [
    # (query, values the parser must set, words it must report as not understood)
    ("BROOKLYN 2022 NEW BUILDINGS", {"boroughs": ["Brooklyn"], "year_from": 2022, "year_to": 2022,
                                     "construction": ["New Construction"], "scope": "near"}, []),
    ("BrOoKlYn   2022   New   Buildings", {"boroughs": ["Brooklyn"], "year_from": 2022, "year_to": 2022,
                                          "construction": ["New Construction"], "scope": "near"}, []),
    ("Queens 2018-2020", {"boroughs": ["Queens"], "year_from": 2018, "year_to": 2020}, []),
    ("queens 2018–2020", {"boroughs": ["Queens"], "year_from": 2018, "year_to": 2020}, []),
    ("queens 2020-2018", {"boroughs": ["Queens"], "year_from": 2018, "year_to": 2020}, []),
    ("between 2017 and 2019 manhattan", {"boroughs": ["Manhattan"], "year_from": 2017, "year_to": 2019}, []),
    ("bronx through 2018", {"boroughs": ["Bronx"], "year_from": YEAR_START, "year_to": 2018}, []),
    ("after 2022 brooklyn", {"boroughs": ["Brooklyn"], "year_from": 2023, "year_to": YEAR_END}, []),
    ("SI cyclists", {"boroughs": ["Staten Island"], "harm": "cyc"}, []),
    ("Brooklyn, 2022; new buildings!", {"boroughs": ["Brooklyn"], "year_from": 2022, "year_to": 2022,
                                        "construction": ["New Construction"], "scope": "near"}, []),
    ("brooklyn and queens", {"boroughs": ["Brooklyn", "Queens"]}, []),
    ("bronx 1999-2030", {"boroughs": ["Bronx"], "year_from": YEAR_START, "year_to": YEAR_END}, []),
    ("manhattan towers fatal", {"boroughs": ["Manhattan"], "sizes": ["150+"], "harm": "fatal", "scope": "near"}, []),
    ("pedestrian error brooklyn", {"boroughs": ["Brooklyn"], "factors": ["Pedestrian or cyclist error"]}, []),
    ("new york city", {}, []),
    # a close misspelling of a borough or construction word is corrected and shown as such
    ("Brookyln 2022", {"boroughs": ["Brooklyn"], "year_from": 2022, "year_to": 2022}, []),
    ("manhatan pedestrians", {"boroughs": ["Manhattan"], "harm": "ped"}, []),
    ("brooklin new construciton", {"boroughs": ["Brooklyn"], "construction": ["New Construction"], "scope": "near"}, []),
    # two separate years make a range
    ("2020 2018 bronx", {"boroughs": ["Bronx"], "year_from": 2018, "year_to": 2020}, []),
    # nothing usable
    ("", {}, []),
    ("   ", {}, []),
    ("???", {}, []),
    ("asdf qwerty 12345", {}, ["asdf", "qwerty", "12345"]),
    ("brooklyn 20222", {"boroughs": ["Brooklyn"]}, ["20222"]),
]


@pytest.mark.parametrize("query, values, unmatched", QUERY_TABLE, ids=[repr(row[0])[:40] for row in QUERY_TABLE])
def test_query_table(query, values, unmatched):
    parsed = parse_query(query)
    assert parsed.values == values
    assert parsed.unmatched == unmatched
    filters = parsed.filters()                                # always convertible to a valid selection
    assert YEAR_START <= filters.year_from <= filters.year_to <= YEAR_END


def test_parser_never_raises_on_odd_input():
    for text in [None, "\u0000", "a" * 5000, "2022" * 50, "\U0001F4A5 brooklyn", "(((", "\\", "[a-z", "+",
                 "150+ 150+ 150+"]:
        parsed = parse_query(text)
        assert isinstance(parsed.values, dict)
        parsed.filters()


# --- conservation and impossible combinations ----------------------------------------------------
def test_borough_partition_conserves_totals(store):
    """Crashes of the five boroughs plus the unknown-borough rows add up to the citywide count."""
    whole = data.headline_numbers(store, make_filters())
    per_borough = sum(data.headline_numbers(store, make_filters(boroughs=[b]))["crashes"] for b in BOROUGHS)
    assert per_borough + whole["crashes_unknown_borough"] == whole["crashes"]


def test_year_partition_conserves_totals(store):
    whole = data.headline_numbers(store, make_filters(harm="all"))["crashes"]
    split = sum(data.headline_numbers(store, make_filters(harm="all", year_from=y, year_to=y))["crashes"]
                for y in range(YEAR_START, YEAR_END + 1))
    assert split == whole


def test_hour_band_partition_conserves_totals(store):
    whole = int(data.weekday_hour(store, make_filters()).sum())
    parts = sum(int(data.weekday_hour(store, make_filters(hours=[band])).sum()) for band in HOUR_BANDS)
    assert parts == whole


def test_factor_partition_conserves_totals(store):
    whole = int(data.factor_mix(store, make_filters()).sum())
    parts = sum(int(data.factor_mix(store, make_filters(factors=[group])).sum()) for group in FACTOR_GROUPS)
    assert parts == whole


def test_stricter_filters_never_add_crashes(store):
    wide = data.headline_numbers(store, make_filters(harm="all"))["crashes"]
    injury = data.headline_numbers(store, make_filters(harm="injury"))["crashes"]
    fatal = data.headline_numbers(store, make_filters(harm="fatal"))["crashes"]
    near = data.headline_numbers(store, make_filters(harm="all", scope="near"))["crashes"]
    assert wide >= injury >= fatal >= 0 and wide >= near >= 0


def test_housing_filters_partition_the_buildings(store):
    both = data.headline_numbers(store, make_filters())["buildings"]
    kinds = sum(data.headline_numbers(store, make_filters(construction=[kind]))["buildings"]
                for kind in ["New Construction", "Preservation"])
    assert kinds == both
    assert len(data.map_sites(store, make_filters())) <= both


IMPOSSIBLE = make_filters(boroughs=["Staten Island"], year_from=2020, year_to=2020, factors=["Vehicle defect"],
                          hours=["Night"], harm="fatal", scope="near", sizes=["150+"],
                          construction=["Preservation"])


def test_impossible_combination_gives_empty_frames_without_raising(store):
    numbers = data.headline_numbers(store, IMPOSSIBLE)
    assert numbers["crashes"] == 0 and numbers["buildings"] == 0
    assert data.map_cells(store, IMPOSSIBLE).empty and data.map_sites(store, IMPOSSIBLE).empty
    trend = data.crash_trend(store, IMPOSSIBLE)
    assert int(trend.to_numpy().sum()) == 0 and list(trend.columns) == ["Staten Island"]
    assert int(data.factor_mix(store, IMPOSSIBLE).sum()) == 0
    assert int(data.weekday_hour(store, IMPOSSIBLE).sum()) == 0
    tables = data.completions_by_year(store, IMPOSSIBLE)
    assert all(int(table.to_numpy().sum()) == 0 for table in tables.values())
    assert data.zip_relation(store, IMPOSSIBLE)["table"].empty
    assert data.event_study(store, IMPOSSIBLE) is not None
    assert data.site_selection(store, IMPOSSIBLE) is not None


# --- every chart builder, fed from the data layer ------------------------------------------------
FILTERS_FOR_CHARTS = {
    "normal": make_filters(),
    "one borough one year": make_filters(boroughs=["Staten Island"], year_from=2021, year_to=2021),
    "empty": IMPOSSIBLE,
}


def _assert_valid(figure, label):
    assert isinstance(figure, go.Figure), label
    json.dumps(figure.to_plotly_json(), default=_plain)
    figure.to_dict()                                           # plotly validates the whole tree here
    assert figure.layout.template is not None, label


def _builders(store, filters):
    yield "map", charts.map_figure(data.map_cells(store, filters), data.map_sites(store, filters),
                                   filters.harm_noun, "/data/crash-grid.geojson", bool(filters.boroughs))
    yield "trend", charts.trend_figure(data.crash_trend(store, filters), filters.harm_noun, filters.harm == "all")
    yield "factors", charts.factor_figure(data.factor_mix(store, filters))
    yield "heatmap", charts.heatmap_figure(data.weekday_hour(store, filters), filters.harm_noun)
    yield "completions", charts.completions_figure(data.completions_by_year(store, filters))
    yield "scatter", charts.scatter_figure(data.zip_relation(store, filters)["table"], filters.harm_noun)
    study, selection = data.event_study(store, filters), data.site_selection(store, filters)
    # report.py swaps in empty_figure when these say "empty"; the builders need a populated dict
    yield "event", charts.empty_figure("n/a") if study.get("empty") else charts.event_figure(study)
    yield "selection", charts.empty_figure("n/a") if selection.get("empty") else charts.selection_figure(selection)
    yield "break", charts.reporting_break_figure(store.city_year)
    yield "robustness", charts.robustness_figure(store.robustness)
    yield "empty", charts.empty_figure("nothing here")


@pytest.mark.parametrize("name", FILTERS_FOR_CHARTS)
def test_every_chart_builder_returns_a_valid_figure(store, name):
    seen = []
    for label, figure in _builders(store, FILTERS_FOR_CHARTS[name]):
        _assert_valid(figure, f"{name}/{label}")
        seen.append(label)
    assert len(seen) == 11


def test_chart_types_cover_the_assignment_list(store):
    """The brief asks for bars, lines, a heatmap, a map and a scatter plot."""
    kinds = {type(trace).__name__ for _, figure in _builders(store, make_filters()) for trace in figure.data}
    assert {"Bar", "Scatter", "Heatmap", "Choroplethmap", "Scattermap"} <= kinds


def test_a_chart_shows_the_two_domains_together(store):
    """Required: one visualisation relating housing to transport (map overlay and ZIP scatter)."""
    report = build_report(store, make_filters())
    map_traces = {type(trace).__name__ for trace in report["panels"]["map"].figure.data}
    assert {"Choroplethmap", "Scattermap"} <= map_traces                  # crashes under housing sites
    assert len(report["panels"]["scatter"].figure.data) >= 1


# --- the Generate report button -----------------------------------------------------------------
def _callbacks(client):
    return client.get("/_dash-dependencies").get_json()


def test_generate_button_drives_every_chart_and_the_numbers(client):
    spec = next(item for item in _callbacks(client)
                if "generate.n_clicks" in {f"{i['id']}.{i['property']}" for i in item["inputs"]})
    outputs = spec["output"]
    for key in CHART_KEYS:
        assert f"fig-{key}.figure" in outputs, key
        assert f"scope-{key}.children" in outputs and f"note-{key}.children" in outputs, key
    assert "report-tiles.children" in outputs and "report-header.children" in outputs
    # the dropdowns are State, not Input: changing a dropdown must not redraw charts by itself
    inputs = {f"{i['id']}.{i['property']}" for i in spec["inputs"]}
    states = {f"{s['id']}.{s['property']}" for s in spec["state"]}
    # lazy-report-ready: the report is drawn once its charts are on the page (app/ui/lazy.py), not at page load
    assert inputs == {"generate.n_clicks", "search.n_submit", "reset.n_clicks", "lazy-report-ready.data"}
    assert spec.get("prevent_initial_call") is True
    assert {f"{control}.value" for control in CONTROL_IDS} <= states and "search.value" in states


def test_no_other_callback_writes_to_the_charts(client):
    for item in _callbacks(client):
        inputs = {f"{i['id']}.{i['property']}" for i in item["inputs"]}
        if "generate.n_clicks" in inputs:
            continue
        if inputs == {"report-filters.data"}:          # the before and after chart has its own callback
            assert item["output"].count("fig-") == 1 and "fig-event.figure" in item["output"], item["output"]
            continue
        assert "fig-" not in item["output"], item["output"]


def test_changing_a_dropdown_only_flags_the_report_as_stale(client):
    filters = make_filters(boroughs=["Queens"])
    response = _callback(client, "f-borough.value", {**_control_state(filters),
                                                     "report-filters.data": make_filters().to_dict()})
    assert "Press Generate report" in json.dumps(response["stale-hint"])
    assert "is-stale" in response["generate"]["className"]


def test_generate_with_an_impossible_selection_still_answers(client):
    response = _callback(client, "generate.n_clicks", {"generate.n_clicks": 1, **_control_state(IMPOSSIBLE)})
    for key in CHART_KEYS:
        assert "layout" in response[f"fig-{key}"]["figure"], key
    assert "No crashes match" in json.dumps(response["report-header"])


def test_reset_restores_defaults(client):
    response = _callback(client, "reset.n_clicks", {"reset.n_clicks": 1, "search.value": "bronx"})
    assert [response[control_id]["value"] for control_id in CONTROL_IDS] == control_values(make_filters())


def test_reset_also_redraws_the_report_with_defaults(client):
    response = _callback(client, "reset.n_clicks",
                         {"reset.n_clicks": 1, **_control_state(make_filters(boroughs=["Queens"]))}, "fig-map")
    assert response["report-filters"]["data"] == make_filters().to_dict()


def test_a_reversed_year_range_is_put_back_in_order(client):
    response = _callback(client, "f-year-from.value", {"f-year-from.value": 2022, "f-year-to.value": 2018},
                         "f-year-to")
    values = {key.split("@")[0]: item["value"] for key, item in response.items()}
    assert (values["f-year-from"], values["f-year-to"]) == (2018, 2022)


def test_search_with_nothing_understood_leaves_the_dropdowns_alone(client):
    response = _callback(client, "search.value", {"search.value": "zzz qqq"})
    assert response["search-feedback"]["children"]
    assert not any(control_id in response for control_id in CONTROL_IDS)


@pytest.mark.parametrize("query, term", [
    ("not brooklyn", "brooklyn"), ("non-fatal", "fatal"), ("except queens", "queens"),
    ("excluding 2020", "2020"), ("without pedestrians", "pedestrians"), ("not near housing", "near housing"),
])
def test_negated_terms_are_reported_and_never_applied(query, term):
    parsed = parse_query(query)
    assert parsed.values == {}
    assert parsed.unmatched == [f"negation is not supported: {term}"]
    assert parse_query("bronx not queens").values == {"boroughs": ["Bronx"]}


@pytest.mark.parametrize("query", ["after 2025", "before 2016", "since 2030", "until 2015", "2015"])
def test_year_phrases_outside_the_data_set_no_year_filter(query):
    parsed = parse_query(query)
    assert "year_from" not in parsed.values and "year_to" not in parsed.values
    assert parsed.unmatched and "data covers 2016 to 2025" in parsed.unmatched[0]
    assert parse_query("after 2024").values == {"year_from": 2025, "year_to": 2025}


def test_conflicting_harm_terms_report_the_one_not_used():
    parsed = parse_query("pedestrians motorists")
    assert parsed.values["harm"] == "ped" and len(parsed.unmatched) == 1
    assert "only one" in parsed.unmatched[0]
    assert parse_query("pedestrians and cyclists").unmatched == []


def test_scatter_hover_keeps_the_true_zero():
    table = pd.DataFrame({"zip": ["10001", "10002"], "borough": ["Manhattan", "Bronx"],
                          "buildings": [1, 2], "affordable_units": [10, 20], "crashes": [0, 5],
                          "crashes_per_year": [0.0, 0.5]})
    trace = charts.scatter_figure(table, "injury crashes").data[0]
    assert list(trace.y) == [0.1, 0.5]
    assert trace.customdata[0][4].startswith("0.0") and "axis floor" in trace.customdata[0][4]
    assert trace.customdata[1][4] == "0.5"


# ---------------------------------------------------------------------------------------------
# Audit fixes: housing filters at city scope, harm precedence, "new york county", reversed years
# ---------------------------------------------------------------------------------------------
def test_housing_word_in_a_query_switches_the_location_to_near_housing():
    assert parse_query("brooklyn new construction").values["scope"] == "near"
    assert parse_query("towers").values["scope"] == "near"
    assert parse_query("new construction anywhere").values["scope"] == "city"     # said explicitly: kept
    assert "scope" not in parse_query("brooklyn 2020").values
    assert "scope" not in parse_query("new construction and preservation").values   # both types = no filter


def test_scope_lines_say_housing_filters_apply_only_near_housing(store):
    ignored = make_filters(construction=["New Construction"])
    report = build_report(store, ignored)
    for key in ["map", "trend", "factors", "heatmap", "scatter"]:
        assert "housing filters apply only near housing" in _text(report["panels"][key].scope)
    assert "housing filters apply only near housing" in _text(report["tiles"][0].children)
    near = build_report(store, make_filters(construction=["New Construction"], scope="near"))
    assert "only near housing" not in _text(near["panels"]["trend"].scope)


@pytest.mark.parametrize("query, harm, unmatched", [
    ("bronx bike injuries", "cyc", []),
    ("queens pedestrians killed", "ped", []),
    ("manhattan peds", "ped", []),
    ("motorists fatal", "mot", []),
    ("pedestrians cyclists injured", "pedcyc", []),
])
def test_a_road_user_beats_the_generic_harm_words(query, harm, unmatched):
    parsed = parse_query(query)
    assert parsed.values["harm"] == harm and parsed.unmatched == unmatched


def test_new_york_county_is_manhattan_and_new_york_city_is_ignored():
    assert parse_query("new york county").values["boroughs"] == ["Manhattan"]
    assert parse_query("new york city 2020").values == {"year_from": 2020, "year_to": 2020}


def test_reversed_years_are_normalised_and_the_report_says_so(store):
    from app.core.filters import reversed_years_note
    filters = make_filters(year_from=2022, year_to=2018)
    assert (filters.year_from, filters.year_to) == (2018, 2022)
    assert reversed_years_note(2022, 2018) == "The years were entered as 2022 to 2018; they are read as 2018 to 2022."
    assert reversed_years_note(2018, 2022) is None and reversed_years_note(None, 2022) is None
    header = build_report(store, filters, None, [reversed_years_note(2022, 2018)])["header"]
    assert "read as 2018 to 2022" in _text(header[-1:]) or any("read as 2018 to 2022" in str(item) for item in header)


def test_rq7_resamples_site_clusters(store):
    result = data.site_selection(store, make_filters(construction=["New Construction"]))
    assert "site clusters" in result["cluster_unit"]
    assert result["n_blocks"] == store.sites.loc[store.sites["borough_percentile"].notna()
                                                 & (store.sites["construction_type"] == "New Construction"),
                                                 "cluster_id"].nunique()


# ---------------------------------------------------------------------------------------------
# Regressions: comparison counts, the RQ7 weighting, the ZIP-level "kept" rule and constant ownership
# ---------------------------------------------------------------------------------------------
def test_used_sizes_counts_sites_not_rows():
    """One comparison site serves two cohorts: two rows, one site. A cohort lacking an arm is not used."""
    sizes = stats.used_sizes(site_ids=[1, 2, 3, 3, 4, 5],
                             treated=[True, True, False, False, False, True],
                             strata=[2019, 2020, 2019, 2020, 2019, 2021],
                             clusters=["a", "a", "b", "b", "c", "d"])
    assert sizes == {"n_treated": 2, "n_control": 3, "n_treated_sites": 2, "n_comparison_sites": 2,
                     "n_clusters": 4, "n_treated_clusters": 1}


def test_comparison_sites_and_rows_are_not_confused(store):
    table, events = store.robustness, store.event_sites
    comparison = events[~events["treated"]]
    central = table[table["kind"] == "central"].iloc[0]
    assert central["n_comparison"] == len(comparison)
    assert central["n_comparison_sites"] == comparison["site_id"].nunique() < central["n_comparison"]
    assert (table["n_comparison_sites"] <= table["n_comparison"]).all()
    assert (table["n_comparison_sites"] <= store.meta["rows"]["sites"]).all()   # a row count here exceeded every site
    assert (table["n_treated_clusters"] <= table["n_resampled_units"]).all()
    rq3 = store.results["detail"]["rq3_did"]
    new_build = events[events["treated"] & (events["construction_type"] == "New Construction")]
    assert rq3["n_comparison_sites"] == comparison["site_id"].nunique() and rq3["n_control"] == len(comparison)
    assert rq3["n_treated_clusters"] == new_build["cluster_id"].nunique()
    assert f"{rq3['n_comparison_sites']:,} comparison sites" in store.results["questions"]["RQ6"]["sentence"]

    filters = make_filters(construction=["New Construction"])
    study = data.event_study(store, filters)
    assert study["comparison"]["n_sites"] == study["n_comparison_sites"] == rq3["n_comparison_sites"]
    assert study["comparison"]["n_rows"] == study["n_comparison"] == rq3["n_control"]
    scope = _text(build_report(store, filters)["panels"]["event"].scope)
    assert f"{rq3['n_comparison_sites']:,} comparison sites ({rq3['n_control']:,} rows" in scope
    assert f"{rq3['n_control']:,} comparison sites" not in scope


def test_a_group_needs_enough_unique_sites_not_rows(store):
    """Comparison rows above MIN_GROUP_N do not pass the gate when they come from fewer unique sites."""
    events = store.event_sites
    comparison = events[~events["treated"]]
    per_site = comparison.groupby("site_id").size()
    repeated = per_site[per_site >= 2].index.to_numpy()

    def view(n_sites):
        rows = comparison["site_id"].isin(repeated[:n_sites])
        sample = pd.concat([events[events["treated"]], comparison[rows]]).sort_index()
        assert rows.sum() >= data.MIN_GROUP_N
        changed = dataclasses.replace(store, event_sites=sample)
        return data.event_study(changed, make_filters(construction=["New Construction"]))

    assert view(data.MIN_GROUP_N - 1).get("empty")
    assert not view(data.MIN_GROUP_N).get("empty")


def test_type_contrast_reports_the_rows_it_used():
    """15 of 30 first-type sites sit in a stratum without comparison rows, so they are not used."""
    strata = np.array(["A"] * 15 + ["B"] * 15 + ["A"] * 20 + ["A"] * 40)
    arm = np.array([1] * 30 + [2] * 20 + [0] * 40)
    change = np.arange(len(arm), dtype=float) % 5
    result = stats.type_contrast(np.ones(len(arm)), change, arm, strata, np.arange(len(arm)))
    assert (result["first"]["n_treated"], result["first"]["n_treated_dropped"]) == (15, 15)
    assert (result["second"]["n_treated"], result["second"]["n_control"]) == (20, 40)
    assert (result["difference"]["n_treated"], result["difference"]["n_control"]) == (35, 40)


def test_robustness_rows_cover_the_comparison_group_and_wide_clusters(store):
    table, detail = store.robustness, store.results["detail"]
    cuts = table[table["check"] == detail["comparison_subset_check"]]
    assert len(cuts) == 4 and cuts["estimate"].notna().all()
    assert (table["check"] == "Clusters").sum() == 1
    central = table[table["kind"] == "central"].iloc[0]
    wide = table[table["check"] == "Clusters"].iloc[0]
    assert wide["percent_change"] == pytest.approx(central["percent_change"])       # the same units
    assert wide["n_resampled_units"] < central["n_resampled_units"]
    assert wide["n_treated_clusters"] < central["n_treated_clusters"]


def test_robustness_text_reads_from_the_rows_and_claims_no_fall(store):
    from app.analysis.story_text import robustness_text
    text = robustness_text(store)
    table, detail = store.robustness, store.results["detail"]
    cuts = table[table["check"] == detail["comparison_subset_check"]]
    for row in cuts.itertuples():
        assert row.variant in text and f"{row.n_comparison_sites:,} comparison sites" in text
    assert "do not show that crashes fall" in text
    for overstated in ["every version", "support no direction", "The exceptions all switch the screen off"]:
        assert overstated not in text
    overlap = detail["placebo_overlap"]
    assert 0 < overlap["in_both"] < overlap["central_treated"] < overlap["placebo_treated"]
    assert f"{overlap['in_both']} of the {overlap['central_treated']} central sites" in text


def test_one_vote_per_cluster_counts_each_cluster_once():
    percentiles = np.r_[np.full(100, 90.0), 50.0, 40.0]
    clusters = np.r_[np.zeros(100), 1, 2]
    result = stats.one_vote_per_cluster(percentiles, clusters)
    assert result["estimate"] == pytest.approx((90 + 50 + 40) / 3 - 50)
    assert result["n_clusters"] == 3 and result["share_above_pct"] == pytest.approx(100 / 3)
    too_few = stats.one_vote_per_cluster(percentiles, clusters, min_clusters=4)
    assert np.isnan(too_few["estimate"]) and np.isnan(too_few["low"]) and too_few["n_clusters"] == 3


def test_rq7_one_vote_is_exported_and_matches_the_sites_table(store):
    detail = store.results["detail"]
    sites = store.sites[store.sites["borough_percentile"].notna() & (store.sites["construction_type"] == "New Construction")]
    means = sites.groupby("cluster_id")["borough_percentile"].mean()
    one_vote = detail["rq7"]["one_vote"]
    assert one_vote["estimate"] == pytest.approx(means.mean() - 50)
    assert one_vote["n"] == len(means) and one_vote["low"] < one_vote["estimate"] < one_vote["high"]
    assert one_vote["low"] > 0                                                      # the direction claim stays
    assert one_vote["estimate"] < detail["rq7"]["new"]["estimate"]                  # the size depends on the weighting
    assert detail["rq7_new_sites"]["share_clusters_above_borough_median_pct"] == pytest.approx((means > 50).mean() * 100)

    by_borough = {row["borough"]: row for row in detail["rq7_by_borough"]}
    filters = make_filters(construction=["New Construction"], boroughs=["Brooklyn"])
    selection = data.site_selection(store, filters)
    in_brooklyn = sites[sites["borough"] == "Brooklyn"].groupby("cluster_id")["borough_percentile"].mean()
    assert selection["one_vote"]["estimate"] == pytest.approx(in_brooklyn.mean() - 50)
    assert by_borough["Brooklyn"]["new_one_vote_excess"] == pytest.approx(in_brooklyn.mean() - 50)
    assert by_borough["Brooklyn"]["new_excess"] == pytest.approx(selection["excess"])
    assert signed(selection["one_vote"]["estimate"]) in _text(build_report(store, filters)["panels"]["selection"].note)


def test_rq7_reference_points_use_no_crash_after_the_baseline(store):
    """The street-point grid was snapped to crashes up to 2025 before; baseline years only now."""
    assert store.results["detail"]["rq7_new_sites"]["reference_points"] < 9985


def test_page_states_rq7_size_as_dependent_on_weighting(store):
    from app.ui import story
    questions, one_vote = store.results["questions"], store.results["detail"]["rq7"]["one_vote"]
    page = " ".join(_text(part(store)) for part in [story.hero, story.findings, story.impact])
    assert "largest effect" not in page and "far from zero" not in page
    assert "depends on the weighting" in page and signed(one_vote["estimate"], 1) in page
    assert questions["RQ7"]["kept"]
    # A borough whose one-vote interval includes zero is named, so the citywide direction is not read as local.
    for row in store.results["detail"]["rq7_by_borough"]:
        if row.get("new_one_vote_low") is not None and row["new_one_vote_low"] <= 0 <= row["new_one_vote_high"]:
            assert f"{row['borough']} ({signed(row['new_one_vote_excess'])}" in page


def test_zip_level_questions_are_kept_only_if_both_versions_exclude_zero(store):
    questions, reported = store.results["questions"], store.results["detail"]["reported_zips"]
    for key, stored in [("RQ1", reported["rq1"]), ("RQ2", reported["rq2_stock"]), ("RQ9", reported["rq9"])]:
        item = questions[key]
        low, high = (stored["low"], stored["high"]) if key != "RQ9" else (round(stored["low"], 3), round(stored["high"], 3))
        assert item["excludes_zero_reported"] == (low > 0 or high < 0), key
        if item["kept"]:
            assert item["excludes_zero"] and item["excludes_zero_reported"], key
    assert questions["RQ1"]["excludes_zero"] and not questions["RQ1"]["kept"]
    for key, item in questions.items():
        if key not in {"RQ1", "RQ2", "RQ9"}:
            assert item["excludes_zero_reported"] is None, key


def test_rq1_says_did_not_improve_and_carries_no_strong_tag(store):
    from app.analysis.story_text import findings_lead, reading_label
    from app.ui import story
    questions = store.results["questions"]
    text, css = reading_label(questions["RQ1"])
    assert "strong" not in css and "ZIP" in text
    assert reading_label(questions["RQ7"])[1] == "tag tag-strong"
    lead = findings_lead(questions)
    assert "did not improve the forecast" in lead
    page = " ".join(_text(part(store)) for part in [story.hero, story.findings, story.limits, story.impact])
    for wording in ["less accurate", "made the forecast", "made it worse"]:
        assert wording not in page, wording
    assert "less accurate" not in questions["RQ1"]["sentence"]


def test_rq2_checks_are_beside_the_headline_on_the_page(store):
    from app.analysis.story_text import finding_extras
    checks, headline = store.results["detail"]["rq2_checks"], store.results["questions"]["RQ2"]
    assert checks["leave_one_zip_out"]["low"] <= headline["estimate"] <= checks["leave_one_zip_out"]["high"]
    assert checks["leave_one_zip_out"]["high"] == pytest.approx(checks["most_influential_zip"]["estimate"])
    text = finding_extras(store)["RQ2"]
    assert signed(checks["new_construction_stock"]["estimate"], 2) in text
    assert signed(checks["leave_one_zip_out"]["low"], 2) in text and signed(checks["leave_one_zip_out"]["high"], 2) in text
    assert f"ZIP {checks['most_influential_zip']['zip']}" in text


def test_widened_levels_are_printed_exactly_and_rest_on_enough_replicates(store):
    from app.ui import story
    assert stats.level_text(0.95) == "95%"
    assert stats.level_text(0.9875) == "98.75%"
    assert stats.level_text(1 - 0.05 / 9) == "99.44%"
    questions = store.results["questions"]
    assert "98.75% interval" in questions["RQ8"]["sentence"] and "99.44% interval" in questions["RQ10"]["sentence"]
    findings = _text(story.findings(store))
    assert "98.75%" in findings and "99.44%" in findings and "99% interval" not in findings
    assert store.meta["constants"]["n_boot_joint"] >= 5000


def test_the_three_shared_constants_have_one_owner():
    """A value changed in the notebook's Section 1 must survive the paste of app/core/stats.py into Section 7."""
    assemble = importlib.import_module("pipeline.notebook.assemble")
    pasted = assemble.inline_source("# INLINE: app/core/stats.py")
    block = assemble.inline_source("# INLINE-CONSTANTS: app/core/stats.py")
    defined = {name: getattr(stats, name) for name in ["SEED", "N_BOOT", "CI_LEVEL"]}
    namespace = {}
    exec(block, namespace)
    assert {name: namespace[name] for name in defined} == defined
    namespace = {"SEED": 7, "N_BOOT": 50, "CI_LEVEL": 0.90}
    exec(pasted, namespace)
    assert (namespace["SEED"], namespace["N_BOOT"], namespace["CI_LEVEL"]) == (7, 50, 0.90)
    assert namespace["bootstrap_ci"].__kwdefaults__ == {"clusters": None, "n_boot": 50, "seed": 7, "level": 0.90}
    setup = (ROOT / "pipeline" / "notebook" / "sections" / "01_setup.py").read_text(encoding="utf-8")
    for name in defined:
        assert not re.search(rf"^{name} = ", setup, re.M), name
    assert "# INLINE-CONSTANTS: app/core/stats.py" in setup


def test_event_chart_note_points_to_the_joint_interval(store):
    note = _text(build_report(store, make_filters(construction=["New Construction"]))["panels"]["event"].note)
    assert "not the overlap of the bands" in note

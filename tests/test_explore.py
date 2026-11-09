"""The Explore section: named outputs, the separate before and after callback, links, the CSV and hostile clicks."""
from __future__ import annotations

import csv
import io
import json

import pytest
from plotly.utils import PlotlyJSONEncoder

from app.core import data
from app.core.filters import make_filters
from app.ui import callbacks, charts, report

BOUND_KB = 260      # the default report was 449.5 KB before the map stopped carrying per-site hover strings


@pytest.fixture(scope="module")
def store():
    return data.load()


@pytest.fixture(scope="module")
def client():
    from app.app import server
    return server.test_client()


def _fill_search(client, trigger_id: str, value=1):
    payload = {"output": "search.value", "outputs": {"id": "search", "property": "value"},
               "inputs": [[{"id": {"index": 0, "type": "example"}, "property": "n_clicks", "value": value}],
                          {"id": "reset", "property": "n_clicks", "value": None}],
               "changedPropIds": [trigger_id]}
    return client.post("/_dash-update-component", json=payload)


@pytest.mark.parametrize("trigger", [
    '{"index":99,"type":"example"}.n_clicks', '{"index":-1,"type":"example"}.n_clicks',
    '{"index":"x","type":"example"}.n_clicks', '{"index":null,"type":"example"}.n_clicks',
    '{"index":1e400,"type":"example"}.n_clicks', '{"type":"other"}.n_clicks', "example-99.n_clicks", "example-x.n_clicks"])
def test_a_crafted_example_id_never_gives_a_500(client, trigger):
    assert _fill_search(client, trigger).status_code == 200


def test_a_real_example_fills_the_search_box(client):
    reply = _fill_search(client, '{"index":0,"type":"example"}.n_clicks')
    assert reply.status_code == 200
    assert reply.get_json()["response"]["search"]["value"] == callbacks.EXAMPLE_QUERIES[0]


def test_generate_returns_outputs_by_name_and_the_event_card_is_a_placeholder(store):
    outputs = callbacks.report_outputs(store, make_filters(), None)
    assert {"header", "tiles", "filters", "share", "fig-map", "fig-event", "scope-event", "note-event"} <= set(outputs)
    assert "Calculating" in json.dumps(outputs["scope-event"], cls=PlotlyJSONEncoder)
    assert outputs["share"] == ""                                  # the default selection leaves the address alone


def test_the_event_study_has_its_own_callback(client):
    specs = client.get("/_dash-dependencies").get_json()
    writers = [spec for spec in specs if "fig-event.figure" in spec["output"]]
    assert len(writers) == 2                                       # generate (placeholder) and the event callback
    own = [spec for spec in writers if {f"{i['id']}.{i['property']}" for i in spec["inputs"]} == {"report-filters.data"}]
    assert len(own) == 1 and own[0]["output"].count("fig-") == 1


def test_main_report_does_not_wait_for_the_event_study(store):
    built = report.build_main(store, make_filters())
    assert "event" not in built["panels"]
    assert list(report.build_report(store, make_filters())["panels"]) == report.CHART_KEYS


def test_the_map_sends_no_per_site_hover_text_and_a_versioned_grid(store):
    panel = report._map_panel(store, make_filters())
    dots = [trace for trace in panel.figure.data if trace.type == "scattermap"]
    assert dots and all(trace.customdata is None for trace in dots)
    choropleth = next(trace for trace in panel.figure.data if trace.type == "choroplethmap")
    assert choropleth.geojson.startswith(report.GEOJSON_URL + "?v=")


def test_the_default_report_stays_small(store):
    outputs = callbacks.report_outputs(store, make_filters(), None)
    outputs |= callbacks._panel_values({"event": report.build_event(store, make_filters())})
    assert len(json.dumps(outputs, cls=PlotlyJSONEncoder)) / 1024 < BOUND_KB


@pytest.mark.parametrize("fields", [dict(), dict(boroughs=["Bronx"], year_from=2019, year_to=2021, hours=["Night"], harm="ped"),
                                    dict(construction=["Preservation"], sizes=["150+"], scope="near")])
def test_a_link_round_trips_the_filters(fields):
    filters = make_filters(**fields)
    again = callbacks.filters_from_query(callbacks.query_for(filters))
    assert (again or make_filters()) == filters


@pytest.mark.parametrize("search", [None, "", "?", "borough=Bronx", "?" + "a=1&" * 500, "?borough=%00&from=inf",
                                    "?from=1e999&to=abc&who=%E2%80%AE", 7, ["?borough=Bronx"]])
def test_hostile_addresses_never_raise(search):
    callbacks.filters_from_query(search)


def test_opening_a_link_builds_the_report_from_it():
    filters, query, notes = callbacks.request_filters(None, [None] * 9, "", "?borough=Queens&from=2018&to=2020")
    assert filters.boroughs == ("Queens",) and (filters.year_from, filters.year_to) == (2018, 2020) and query is None


def test_the_csv_adds_up_to_the_headline(store):
    filters = make_filters(boroughs=["Brooklyn"], year_from=2018, year_to=2022)
    rows = list(csv.DictReader(io.StringIO(report.summary_csv(store, filters))))
    headline = next(int(row["value"]) for row in rows if row["section"] == "Headline" and row["item"] == "Injury crashes")
    by_borough = sum(int(row["value"]) for row in rows if row["section"] == "Crashes by period and borough")
    assert by_borough == headline == data.headline_numbers(store, filters)["crashes"]


def test_the_download_callback_answers(client):
    from app.ui.callbacks import CSV_NAME
    payload = {"output": "download.data", "outputs": {"id": "download", "property": "data"},
               "inputs": [{"id": "download-csv", "property": "n_clicks", "value": 1}],
               "state": [{"id": "report-filters", "property": "data", "value": make_filters().to_dict()}],
               "changedPropIds": ["download-csv.n_clicks"]}
    reply = client.post("/_dash-update-component", json=payload)
    assert reply.status_code == 200 and CSV_NAME in reply.get_data(as_text=True)


def test_empty_figure_text_is_light_enough_for_the_dark_ground():
    figure = charts.empty_figure("Nothing here")
    assert figure.layout.annotations[0].font.color == "#c9cad6"

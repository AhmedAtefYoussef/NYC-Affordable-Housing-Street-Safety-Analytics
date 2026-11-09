"""Your block: find a building or a ZIP code and see its record against its borough. Ids here start with `bk-`.

The containers are drawn here and filled by assets/js/45-tools.js from the JSON routes registered below.
"""
from __future__ import annotations

import json
from datetime import date

from dash import Dash, html
from flask import Response, jsonify, request

from app.analysis import block_data
from app.core.data import Store
from app.ui import components

CACHE_SECONDS = 300
CSV_NAME = "sites_on_crash_heavy_streets.csv"


def _long_date(iso: str) -> str:
    day = date.fromisoformat(iso)
    return f"{day.day} {day:%B %Y}"


def as_of_text(store: Store) -> str:
    as_of = store.meta["data_as_of"]
    saved = max(as_of["raw_files_saved"].values())
    return f"Crash records through {_long_date(as_of['latest_crash'])}. City files saved {_long_date(saved)}."


def layout(store: Store) -> html.Section:
    rows, constants = store.meta["rows"], store.meta["constants"]
    first, last = constants["baseline_years"]
    published = store.results["questions"]["RQ3"]
    config = {"bufferM": constants["buffer_m"], "baselineYears": [first, last], "boroughs": store.meta["dimensions"]["boroughs"],
              "testedSites": int(published["n"]), "window": constants["event_window"]}
    lead = (f"Type a ZIP code, a project name or a borough. You see how crash-heavy the streets around one of "
            f"{rows['sites']:,} city-financed buildings already were, and where that falls in its borough.")
    return components.section("block", "Your block", lead, [
        # A workbench: the search and the ranked streets on the left, the chosen record on the right. The record
        # panel stays in view while the list scrolls, so choosing a site never moves the page.
        html.Div(id="bk-root", className="bk-root bk-workbench", **{"data-config": json.dumps(config)}, children=[
            html.Div(className="bk-pane bk-pane-list", children=[
                html.Div(id="bk-search", className="bk-search"),
                html.Div(className="bk-rank", children=[
                    html.Div(className="bk-rank-head", children=[
                        html.H3("Sites on the most crash-heavy streets", className="bk-rank-title"),
                        html.P(f"Injury crashes within {constants['buffer_m']} m, {first} to {last}. This ranks streets and "
                               f"blames no building: the counts come from {first} to {last}, before any of these sites "
                               "began construction, so this is not blame on the buildings and says nothing about cause.",
                               className="aside bk-rank-note"),
                    ]),
                    html.Div(id="bk-ranked", className="bk-ranked"),
                ]),
            ]),
            html.Aside(className="bk-pane bk-pane-record", **{"aria-label": "The chosen site"}, children=[
                html.Div(id="bk-record", className="bk-record surface spot", **{"aria-live": "polite"}),
            ]),
        ]),
        html.P([f"{rows['housing_confidential']:,} of the {rows['housing']:,} housing records are confidential. The city "
                "withholds where they are, so they cannot be looked up here and are not counted. ", as_of_text(store)],
               className="aside bk-asof", id="bk-asof"),
    ], "harbor", "chapter-block")


def _cached(payload) -> Response:
    response = jsonify(payload)
    response.headers["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    return response


def register(app: Dash, store: Store) -> None:
    def search():
        return _cached(block_data.search(store, request.args.get("q")))

    def site():
        record = block_data.site_record(store, request.args.get("id"))
        return _cached(record) if record else (jsonify({"error": "not_found"}), 404)

    def zip_code():
        record = block_data.zip_record(store, request.args.get("zip"))
        return _cached(record) if record else (jsonify({"error": "not_found"}), 404)

    def ranked():
        args = request.args
        return _cached(block_data.ranked(store, args.get("borough"), args.get("type"), args.get("sort"), args.get("dir"),
                                         args.get("offset", 0), args.get("limit", block_data.PAGE_SIZE)))

    def ranked_csv():
        args = request.args
        body = block_data.ranked_csv(store, args.get("borough"), args.get("type"), args.get("sort"), args.get("dir"))
        return Response(body, mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{CSV_NAME}"',
                                 "Cache-Control": f"public, max-age={CACHE_SECONDS}"})

    routes = [("/api/block/search", search), ("/api/block/site", site), ("/api/block/zip", zip_code),
              ("/api/block/ranked", ranked), ("/block/ranked.csv", ranked_csv)]
    for path, handler in routes:
        endpoint = "bk_" + path.strip("/").replace("/", "_").replace(".", "_")
        if endpoint not in app.server.view_functions:
            app.server.add_url_rule(path, endpoint, handler)

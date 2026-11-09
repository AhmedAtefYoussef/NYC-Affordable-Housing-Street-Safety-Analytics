"""The opening and the story: the question over a live city where every point of light is a real building, then
five chapters in which the same points regroup into what each one says.

The canvas is one stage shared by the chapters: assets/js/20-stage.js draws it and assets/js/25-story.js names an
arrangement for each chapter (its `data-layout`). Ids here start with `ov-` or `chapter-`.
"""
from __future__ import annotations

import gzip

from dash import Dash, html
from flask import Response, request

from app.analysis import story_data
from app.analysis.story_text import signed
from app.core.data import Store
from app.core.filters import YEAR_END, YEAR_START, buffer_m
from app.core.stats import NEUTRAL_PERCENTILE
from app.ui import components

ONE_YEAR_S = 31_536_000


def _figure(value: str, tone: str = "gold") -> html.Span:
    """A figure inside a sentence. It rolls into place when the sentence is read (assets/js/00-motion.js)."""
    number = float(value.replace(",", "").replace("\u2212", "-").rstrip("%").removesuffix("th") or 0)
    return html.Span(value, className=f"fig fig-{tone}", **{"data-countup": str(number), "data-final": value})


def _place(name: str, start: bool = False) -> str:
    """A borough as it is said in a sentence: "the Bronx", "The Bronx" at the start."""
    if name != "Bronx":
        return name
    return "The Bronx" if start else "the Bronx"


def _legend() -> html.Div:
    return html.Div(className="stage-legend", children=[
        html.Span([html.I(className="dot dot-new"), "New construction"]),
        html.Span([html.I(className="dot dot-preservation"), "Preservation"]),
    ])


def _hero(store: Store) -> html.Div:
    rows, questions = store.meta["rows"], store.results["questions"]
    after, where = questions["RQ3"], questions["RQ7"]
    percentile = NEUTRAL_PERCENTILE + where["estimate"]
    return html.Div(className="hero story-step", **{"data-layout": "city"}, children=[
        html.P("NYC Open Data, 2016 to 2025", className="step-kicker hero-kicker"),
        html.H1("Do injury crashes rise around affordable housing once it opens?", **{"data-kinetic": "words"}),
        html.P(f"Each point of light is one of {len(store.sites):,} city-financed buildings, set against "
               f"{rows['crashes']:,} police crash reports from {YEAR_START} to {YEAR_END}.",
               className="hero-lead", **{"data-kinetic": "lines"}),
        _legend(),
        html.Div(className="hero-answers", children=[
            components.metric(signed(after["estimate"]) + "%", f"change in injury crashes within {buffer_m()} m after a new "
                              "building opens, against sites not yet finished",
                              f"95% interval {signed(after['low'])}% to {signed(after['high'])}%, {after['n']:,} sites. "
                              "The records cannot tell this from no change.", "is-crash", count_to=after["estimate"]),
            components.metric(f"{percentile:.0f}th", "percentile: how crash-heavy the average new site's streets "
                              "already were, before construction",
                              f"A typical street point in its borough is the {NEUTRAL_PERCENTILE}th. The sites were "
                              "chosen where crashes already happen.", "is-housing", count_to=round(percentile)),
        ]),
        html.Div(className="hero-actions", children=[
            html.A("Follow the story", href="#chapter-1", className="button button-primary"),
            html.A("Find your block", href="#block", className="button button-secondary"),
        ]),
        html.A([html.Span("Scroll"), html.I(className="cue-line")], href="#chapter-1", className="scroll-cue",
               **{"aria-label": "Scroll to the story"}),
    ])


def _step(number: int, total: int, layout_name: str, kicker: str, title: str, text: list, extra=None) -> html.Article:
    return html.Article(id=f"chapter-{number}", className="story-step chapter-step", **{"data-layout": layout_name}, children=[
        html.Div(className="step-card", children=[
            html.P([html.Span(f"{number:02d}", className="step-number"), html.Span(f" / {total:02d}", className="step-total"),
                    html.Span(kicker, className="step-name")], className="step-kicker"),
            html.H2(title, className="step-title", **{"data-kinetic": "words"}),
            html.P(text, className="step-text", **{"data-kinetic": "lines"}),
            extra,
        ]),
    ])


def _chapters(store: Store) -> list[html.Article]:
    """The story, one arrangement of the same points per chapter. Every figure is read from the store."""
    sites, questions = store.sites, store.results["questions"]
    after, where = questions["RQ3"], questions["RQ7"]
    by_borough = sites["borough"].astype(str).value_counts()
    largest, second, smallest = by_borough.index[0], by_borough.index[1], by_borough.index[-1]
    located, completed, clean, compared = story_data.funnel_counts(store)
    outcomes = story_data.rq3_outcomes(store)
    percentile = NEUTRAL_PERCENTILE + where["estimate"]
    total = 5
    return [
        _step(1, total, "boroughs", "Where", "Where the city builds", [
            "The same points, gathered by borough. ", _place(largest), " holds ", _figure(f"{by_borough[largest]:,}"),
            " buildings and ", _place(second), " ", _figure(f"{by_borough[second]:,}"), ". ", _place(smallest, start=True), " has ", _figure(f"{by_borough[smallest]:,}"),
            ". Gold points are new buildings, teal points are older ones kept affordable."]),
        _step(2, total, "percentile", "Before", "The streets were already busy", [
            "Before any project began, every street point in each borough was ranked by its injury crashes. The ",
            _figure(f"{where['n']:,}"), " new buildings stood, on average, at the ", _figure(f"{percentile:.0f}th"),
            " percentile. A typical street point stands at the ", f"{NEUTRAL_PERCENTILE}th."]),
        _step(3, total, "funnel", "Fair test", "Few clean comparisons", [
            "To see what changes once a building opens, it must open inside the study window with no other completion "
            "close by. Of ", _figure(f"{located:,}"), " located buildings, ", _figure(f"{completed:,}"),
            " finished in a usable year, ", _figure(f"{clean:,}"), " passed that screen and ",
            _figure(f"{compared:,}"), " are new construction."]),
        _step(4, total, "outcomes", "After", "Fifty ways the answer could fall", [
            f"The comparison was redrawn {outcomes['n_boot']:,} times. Each dot stands for one fiftieth of those results: ",
            _figure(f"{outcomes['below_zero']}"), " of 50 fall below zero, and the middle is ",
            _figure(signed(after["estimate"]) + "%", "crash"), ". Zero still sits inside the 95% interval, from ",
            f"{signed(after['low'])}% to {signed(after['high'])}%, so the records cannot tell this from no change."]),
        _step(5, total, "city", "Your turn", "Every point is a place you can look up", [
            "Find the streets around one building, try to break the main result, or build your own report."],
            extra=html.Div(className="step-actions", children=[
                html.A("Find your block", href="#block", className="button button-primary"),
                html.A("Try to break it", href="#lab", className="button button-secondary"),
                html.A("Build a report", href="#explore", className="button button-secondary"),
            ])),
    ]


def layout(store: Store) -> html.Section:
    return html.Section(id="story", className="story-root", **{"data-tint": "midnight"}, children=[
        html.Div(className="stage", id="ov-stage", **{"data-url": story_data.versioned_url(store)}, children=[
            html.Canvas(id="ov-canvas", className="stage-canvas", role="img",
                        **{"aria-label": f"A map of New York City drawn from {len(store.sites):,} points of light, "
                                         "one for each located affordable-housing building. As the story moves on, "
                                         "the points regroup into the chart each chapter describes."}),
            html.Ol(className="story-progress", **{"aria-hidden": "true"},
                    children=[html.Li(html.Span()) for _ in range(6)]),
        ]),
        html.Div(className="story-steps", children=[_hero(store), *_chapters(store)]),
    ])


def register(app: Dash, store: Store) -> None:
    def story_json() -> Response:
        payload, compressed, digest = story_data.encoded(store)
        accepts_gzip = "gzip" in request.headers.get("Accept-Encoding", "")
        response = Response(compressed if accepts_gzip else payload, mimetype="application/json")
        if accepts_gzip:
            response.headers["Content-Encoding"] = "gzip"
        response.headers["Cache-Control"] = f"public, max-age={ONE_YEAR_S}, immutable" if request.args.get("v") == digest else "no-cache"
        response.headers["Vary"] = "Accept-Encoding"
        response.set_etag(digest)
        return response.make_conditional(request)

    assert gzip is not None
    app.server.add_url_rule(story_data.STORY_URL, "story_json", story_json)

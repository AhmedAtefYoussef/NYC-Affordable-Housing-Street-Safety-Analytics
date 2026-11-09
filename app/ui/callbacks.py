"""What the Explore section does when the reader acts.

Typing and Enter, the dropdowns with Generate report, and Reset are the main route.

1. Search: typing a query fills the dropdowns and says what was understood.
2. Generate report: one callback redraws the figures and every chart but one. The before and after chart has a
   callback of its own, because its bootstrap can take a second on a cold process and must not hold the rest.
3. A hint when the controls no longer match the report on screen.
4. A link: Generate writes the filters into the address, and opening an address with them restores them.
5. The numbers behind the report as a CSV file.

Outputs are returned by name (dict), never by position.
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlencode

from dash import ALL, ClientsideFunction, Dash, Input, Output, State, ctx, dcc, html, no_update

from app.core.data import Store
from app.core.filters import Filters, from_dict, make_filters, reversed_years_note
from app.core.search import ParsedQuery, parse_query
from app.ui import report
from app.ui.explorer_layout import EXAMPLE_QUERIES, GENERATE_CLASS, search_hint

log = logging.getLogger(__name__)

CONTROL_IDS = ["f-borough", "f-year-from", "f-year-to", "f-construction", "f-size", "f-factor", "f-hour",
               "f-harm", "f-scope"]
GENERATE_LABEL, GENERATING_LABEL = "Generate report", "Generating…"
# Filters field -> name in the address. Only filters that differ from the default are written.
QUERY_NAMES = [("boroughs", "borough"), ("year_from", "from"), ("year_to", "to"), ("construction", "type"),
               ("sizes", "size"), ("factors", "factor"), ("hours", "time"), ("harm", "who"), ("scope", "where")]
MAX_QUERY_CHARS = 2000
CSV_NAME = "nyc-housing-crashes-summary.csv"


# ---------------------------------------------------------------------------------------------
# Controls <-> Filters <-> address
# ---------------------------------------------------------------------------------------------
def control_values(filters: Filters) -> list:
    """The nine dropdown values for a selection, in CONTROL_IDS order."""
    return [list(filters.boroughs), filters.year_from, filters.year_to, list(filters.construction),
            list(filters.sizes), list(filters.factors), list(filters.hours), filters.harm, filters.scope]


def control_dict(filters: Filters) -> dict:
    return dict(zip(CONTROL_IDS, control_values(filters)))


def filters_from_controls(values: list, source: str = "controls") -> Filters:
    """Inverse of `control_values`."""
    boroughs, year_from, year_to, construction, sizes, factors, hours, harm, scope = values
    return make_filters(boroughs, year_from, year_to, construction, sizes, factors, hours, harm, scope, source)


def query_for(filters: Filters) -> str:
    """The address query for a selection: '' for the default, else '?borough=Bronx&from=2019'."""
    defaults, pairs = make_filters(), []
    for field, name in QUERY_NAMES:
        value, default = getattr(filters, field), getattr(defaults, field)
        if value != default:
            pairs += [(name, item) for item in value] if isinstance(value, tuple) else [(name, value)]
    return "?" + urlencode(pairs) if pairs else ""


def filters_from_query(search) -> Filters | None:
    """The selection an address query names, or None when it names no filter. Never raises."""
    if not isinstance(search, str) or not search.startswith("?") or len(search) > MAX_QUERY_CHARS:
        return None
    try:
        params = parse_qs(search[1:], max_num_fields=60)
    except ValueError:
        return None
    if not any(name in params for _, name in QUERY_NAMES):
        return None

    def one(name):
        return (params.get(name) or [None])[0]

    return make_filters(boroughs=params.get("borough"), year_from=one("from"), year_to=one("to"),
                        construction=params.get("type"), sizes=params.get("size"), factors=params.get("factor"),
                        hours=params.get("time"), harm=one("who"), scope=one("where"), source="link")


def request_filters(trigger, values: list, text, search) -> tuple[Filters, str | None, list[str] | None]:
    """Which selection a Generate asks for, the query behind it (if any) and notes for the header.

    The page opening (no trigger) reads the address; Reset means the defaults; Enter in the search box uses
    the query itself, so a fast typist never gets a report built from dropdowns that have not caught up.
    """
    if trigger == "reset":                     # the dropdowns are being reset in the same round trip
        return make_filters(), None, None
    if trigger is None:
        linked = filters_from_query(search)
        if linked is not None:
            return linked, None, None
    if not isinstance(values, list) or len(values) != len(CONTROL_IDS):
        return make_filters(), None, None
    filters, query = filters_from_controls(values), None
    year_note = reversed_years_note(values[1], values[2])
    parsed = parse_query(text)
    if trigger == "search" and parsed.understood:
        filters, query, year_note = parsed.filters(), parsed.text.strip(), None
    elif parsed.understood and parsed.filters() == filters:
        query = parsed.text.strip()            # the dropdowns still show exactly what the query set
    return filters, query, [year_note] if year_note else None


def example_text(trigger, clicks) -> str | None:
    """The query behind an example button, or None for anything that is not a real, pressed example."""
    if not isinstance(trigger, dict) or trigger.get("type") != "example":
        return None
    index = trigger.get("index")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(EXAMPLE_QUERIES):
        return None
    pressed = ctx.triggered[0].get("value") if ctx.triggered else None
    return EXAMPLE_QUERIES[index] if pressed else None


# ---------------------------------------------------------------------------------------------
# What the reader is told
# ---------------------------------------------------------------------------------------------
def search_feedback(parsed: ParsedQuery) -> list:
    """What the parser understood, as labelled chips that spring in one after another, and the words it could not place."""
    if parsed.is_empty:
        return search_hint()
    if not parsed.understood:
        return [html.P(["Nothing in ", html.Q(parsed.text.strip()), " matched a filter, so the filters are "
                        "unchanged. Try a borough, a year or range, new construction or preservation, a road "
                        "user, a time of day or a factor such as speeding."], className="feedback-miss")]
    children = [html.Span("Understood", className="feedback-lead"),
                html.Ul([html.Li([html.Span(label, className="chip-label"), value], className="chip chip-found",
                                 title=f"from “{typed}”", style={"--i": position})
                         for position, (typed, label, value) in enumerate(parsed.understood)], className="chips")]
    if parsed.unmatched:
        children.append(html.P(["Not used: ", ", ".join(parsed.unmatched), "."], className="feedback-unused"))
    children.append(html.P("Filters not named in the query were set back to their defaults. "
                           "Press Enter or Generate report.", className="feedback-next"))
    return children


# ---------------------------------------------------------------------------------------------
# Outputs, by name
# ---------------------------------------------------------------------------------------------
def figure_outputs(keys: list[str], duplicate: bool = False) -> dict:
    """The three outputs of each chart, under names the callback returns them by."""
    outputs = {}
    for key in keys:
        outputs |= {f"fig-{key}": Output(f"fig-{key}", "figure", allow_duplicate=duplicate),
                    f"scope-{key}": Output(f"scope-{key}", "children", allow_duplicate=duplicate),
                    f"note-{key}": Output(f"note-{key}", "children", allow_duplicate=duplicate)}
    return outputs


def _panel_values(panels: dict) -> dict:
    values = {}
    for key, panel in panels.items():
        values |= {f"fig-{key}": panel.figure, f"scope-{key}": panel.scope, f"note-{key}": panel.note}
    return values


def share_query(filters: Filters) -> str:
    return query_for(filters)


def report_outputs(store: Store, filters: Filters, query: str | None, notes: list[str] | None = None) -> dict:
    """Everything the generate callback returns, by name. The event card gets its placeholder; its callback fills it."""
    built = report.build_main(store, filters, query, notes)
    panels = {**built["panels"], "event": report.pending_event_panel()}
    return {"header": built["header"], "tiles": built["tiles"], **_panel_values(panels),
            "filters": filters.to_dict(), "share": share_query(filters)}


def register(app: Dash, store: Store) -> None:
    """Attach the callbacks to the app."""

    def controls_out(duplicate: bool) -> dict:
        return {control_id: Output(control_id, "value", allow_duplicate=duplicate) for control_id in CONTROL_IDS}

    # -- the address ------------------------------------------------------------------------
    @app.callback(output=controls_out(False), inputs=Input("url", "search"))
    def restore_controls(search):
        """Opening an address with filters in it puts them in the controls (the report is generated from it too)."""
        linked = filters_from_query(search)
        return control_dict(linked) if linked is not None else {control_id: no_update for control_id in CONTROL_IDS}

    app.clientside_callback(ClientsideFunction("explore", "mirrorUrl"), Output("explore-sink", "data"),
                            Input("share-url", "data"))
    app.clientside_callback(ClientsideFunction("explore", "copyLink"), Output("copy-status", "children"),
                            Input("copy-link", "n_clicks"), State("share-url", "data"), prevent_initial_call=True)

    # -- search -----------------------------------------------------------------------------
    @app.callback(output={**controls_out(True), "feedback": Output("search-feedback", "children")},
                  inputs=[Input("search", "value"), Input("reset", "n_clicks")], prevent_initial_call=True)
    def apply_search(text, _reset):
        """Fill the dropdowns from the query as it is typed; Reset puts every control back."""
        if ctx.triggered_id == "reset":
            return {**control_dict(make_filters()), "feedback": search_hint()}
        parsed = parse_query(text if isinstance(text, str) else "")
        if not parsed.understood:
            return {**{control_id: no_update for control_id in CONTROL_IDS}, "feedback": search_feedback(parsed)}
        return {**control_dict(parsed.filters()), "feedback": search_feedback(parsed)}

    @app.callback(Output("search", "value"),
                  Input({"type": "example", "index": ALL}, "n_clicks"), Input("reset", "n_clicks"),
                  prevent_initial_call=True)
    def fill_search(_clicks, _reset):
        """An example button writes its query into the search box; Reset clears the box. Crafted ids change nothing."""
        trigger = ctx.triggered_id
        if trigger == "reset":
            return ""
        text = example_text(trigger, _clicks)
        return text if text is not None else no_update

    # -- the report -------------------------------------------------------------------------
    @app.callback(
        output={"header": Output("report-header", "children"), "tiles": Output("report-tiles", "children"),
                **figure_outputs(report.CHART_KEYS), "filters": Output("report-filters", "data"),
                "share": Output("share-url", "data")},
        inputs=[Input("generate", "n_clicks"), Input("search", "n_submit"), Input("reset", "n_clicks"),
                Input("lazy-report-ready", "data")],
        state=[State(control_id, "value") for control_id in CONTROL_IDS] + [State("search", "value"),
                                                                           State("url", "search")],
        running=[(Output("generate", "disabled"), True, False),
                 (Output("generate", "children"), GENERATING_LABEL, GENERATE_LABEL),
                 (Output("report", "className"), "report is-loading", "report")],
        prevent_initial_call=True)
    def generate(_clicks, _submits, _reset, _ready, *state):
        """Redraw the figures and every chart but the last. Runs once its charts are on the page (app/ui/lazy.py: the
        reader came near; from the address if it names filters), and on Generate, Enter and Reset."""
        *values, text, search = state
        filters, query, notes = request_filters(ctx.triggered_id, values, text if isinstance(text, str) else "", search)
        return report_outputs(store, filters, query, notes)

    @app.callback(
        output=figure_outputs(["event"], duplicate=True), inputs=Input("report-filters", "data"),
        running=[(Output("scope-event", "className"), "card-scope is-loading", "card-scope")],
        prevent_initial_call=True)
    def generate_event(shown):
        """The before and after chart, drawn once the rest is on screen (it may run a bootstrap)."""
        if not isinstance(shown, dict):
            return {name: no_update for name in ("fig-event", "scope-event", "note-event")}
        return _panel_values({"event": report.build_event(store, from_dict(shown))})

    @app.callback(
        output={"hint": Output("stale-hint", "children"), "class": Output("generate", "className")},
        inputs=[Input(control_id, "value") for control_id in CONTROL_IDS] + [Input("report-filters", "data")])
    def flag_stale(*inputs):
        """Tell the reader when the dropdowns differ from the report on screen."""
        *values, shown = inputs
        if not isinstance(shown, dict) or filters_from_controls(values) == from_dict(shown):
            return {"hint": "", "class": GENERATE_CLASS}
        return {"hint": "Filters changed. Press Generate report to update the charts.",
                "class": GENERATE_CLASS + " is-stale"}

    @app.callback(
        Output("f-year-from", "value", allow_duplicate=True), Output("f-year-to", "value", allow_duplicate=True),
        Input("f-year-from", "value"), Input("f-year-to", "value"),
        prevent_initial_call=True)
    def order_years(first, last):
        """A reversed year range is put back in order in the dropdowns themselves."""
        if reversed_years_note(first, last) is None:
            return no_update, no_update
        return last, first

    # -- download -----------------------------------------------------------------------------
    @app.callback(Output("download", "data"), Input("download-csv", "n_clicks"), State("report-filters", "data"),
                  prevent_initial_call=True)
    def download_summary(clicks, shown):
        """The numbers behind the report on screen, as a CSV file."""
        if not clicks or not isinstance(shown, dict):
            return no_update
        return dcc.send_string(report.summary_csv(store, from_dict(shown)), CSV_NAME)

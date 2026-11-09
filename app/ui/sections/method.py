"""Method: what the data cannot tell us, what it means for the city, how it was joined, the cleaning log and the credits.

Ids here start with `md-`. Every figure is read from the store. assets/js/50-findings.js counts the pipeline rows up,
carries a line of light through the stages as the reader scrolls, and filters the cleaning log.
"""
from __future__ import annotations

from dash import Dash, dcc, html

from app.core.data import Store
from app.ui import charts, components, story

REPO = "https://github.com/AhmedAtefYoussef/Data-Engineering-Visualization-Project"
DOCS = f"{REPO}/blob/main/docs"
STAGES = {
    "raw": ("Raw", "The two tables as downloaded from NYC Open Data."),
    "cleaned": ("Cleaned", "After the rules in the cleaning log: problems are flagged or filled with a rule."),
    "integrated": ("Integrated", "Joined by ZIP code and year, and by distance from each building."),
}
# Each reader, the parts of the impact text they take, and the tools they can open.
READERS = [
    ("Resident", ["Residents"], [("#block", "Your block"), ("#explore", "Explore the records")]),
    ("Planner", ["Department of Transportation and Vision Zero", "Housing Preservation and Development",
                 "Community boards"], [("#lab", "Test it"), ("#explore", "Explore the records"),
                                       ("#rq7", "Finding on street records")]),
    ("Journalist", [], [("#findings", "Findings"), ("#lab", "Test it"), (f"{DOCS}/NUMBER_CHANGES.md", "Number changes")]),
    ("Researcher", [], [("#findings", "Findings"), ("#md-cleaning", "Cleaning log"), (f"{DOCS}/METHODOLOGY.md", "Methodology")]),
]
GUIDES = {
    "Journalist": "Every figure comes with its interval and the number of sites or ZIP codes behind it. Findings "
                  "lists all ten, and the record of number changes shows what moved between versions.",
    "Researcher": "The methodology note, the data dictionary and the notebook describe each step from the two raw "
                  "tables to the results. The cleaning log below lists every rule.",
}


def _link(text: str, href: str) -> html.A:
    return html.A(text, href=href, target="_blank", rel="noopener")


def _tool(label: str, href: str) -> html.A:
    """A button to another part of this page, or to a document in the repository."""
    extra = {"target": "_blank", "rel": "noopener"} if href.startswith("http") else {}
    return html.A(label, href=href, className="button button-secondary", **extra)


def _part(part_id: str, title: str, children: list, lead: str | list | None = None) -> html.Div:
    """One movement of the chapter: a large heading, an optional line under it, then its content."""
    return html.Div(id=part_id, className="md-part", children=[
        html.H3(title, className="md-title", **{"data-kinetic": "words"}),
        html.P(lead, className="md-lead lift") if lead else None,
        *children,
    ])


def _limits(store: Store) -> html.Div:
    items = story.limit_items(store)
    return _part("md-limits", "What this cannot tell us", [
        html.Ul([html.Li([html.H4(title), html.P(text)], className="md-limit lift", style={"--i": min(index, 3)})
                 for index, (title, text) in enumerate(items)], className="md-limits")])


def _readers(store: Store) -> html.Div:
    parts = dict(story.impact_items(store))
    blocks = []
    for name, sources, tools in READERS:
        body = [html.P(parts[source]) if len(sources) == 1 else
                html.Div([html.H5(source), html.P(parts[source])], className="md-source") for source in sources]
        if name in GUIDES:
            body.append(html.P(GUIDES[name]))
        blocks.append(html.Article(className="md-reader lift", id=f"md-reader-{name.lower()}", children=[
            html.H4(name),
            html.Div(className="md-reader-body", children=[
                *body,
                html.Div(className="md-tools", children=[
                    _tool(label, href) for href, label in tools]),
            ]),
        ]))
    return _part("md-city", "What this means for the city", [html.Div(blocks, className="md-readers")],
                 lead=story.IMPACT_LEAD)


def _count(rows: int) -> html.Span:
    return html.Span(f"{rows:,}", className="md-count", **{"data-countup": str(rows), "data-final": f"{rows:,}"})


def _journey(store: Store) -> html.Div:
    """Raw, cleaned, integrated: the row counts of every table, with a line of light that follows the scroll."""
    stages = store.results["stages"]
    columns = []
    for index, (key, (title, blurb)) in enumerate(STAGES.items()):
        tables = [row for row in stages if row["stage"] == key]
        columns.append(html.Li(className="md-stage", **{"data-stage": str(index)}, children=[
            html.Span(className="md-node", **{"aria-hidden": "true"}),
            html.H4(title), html.P(blurb, className="md-stage-blurb"),
            html.Ul([html.Li([_count(row["rows"]), html.Span(row["table"], className="md-table-name")],
                             className="md-table") for row in tables], className="md-tables"),
        ]))
    return html.Div(className="md-journey", id="md-journey", children=[
        html.Div(className="md-track", **{"aria-hidden": "true"}, children=[
            html.Span(className="md-fill"), html.Span(className="md-head")]),
        html.Ol(columns, className="md-stages", **{"aria-label": "From the raw tables to the integrated tables"}),
        html.P("Rows in each table, read from the build.", className="md-journey-note"),
    ])


def _joined(store: Store) -> html.Div:
    return _part("md-joined", "How the data was joined", [
        _journey(store),
        html.Div(story.join_paragraphs(store), className="md-prose lift"),
        components.surface([
            html.H4("Why we count injury crashes"),
            html.Div(components.graph("md-reporting", charts.reporting_break_figure(store.city_year), size_class="graph-small"),
                     **{"data-lazy": "lazy-reporting"}),   # built when the reader comes near (app/lazy.py)
            html.P(story.reporting_note(store), className="md-note"),
        ], class_name="md-chart lift"),
    ])


def _cleaning(store: Store) -> html.Div:
    log = store.cleaning_log
    head = html.Thead(html.Tr([html.Th(name, scope="col") for name in
                               ["Table", "Rule", "Action", "Rows or cells affected", "Why"]]))
    rows = [html.Tr([html.Td(row.dataset), html.Td(row.rule), html.Td(row.action),
                     html.Td(f"{row.affected:,}", className="num"), html.Td(row.reason)])
            for row in log.itertuples(index=False)]
    return _part("md-cleaning", "Cleaning log", [
        html.Div(className="md-filter lift", children=[
            html.Label("Filter the rules", htmlFor="md-clean-filter", className="field-label"),
            html.Div(className="md-filter-row", children=[
                dcc.Input(id="md-clean-filter", type="search", className="md-input", autoComplete="off", debounce=False,
                           placeholder="A table, rule or word, such as ZIP"),
                html.P(f"Showing all {len(log)} rules", id="md-clean-count", role="status",
                       className="md-clean-count", **{"aria-live": "polite"}),
            ]),
        ]),
        components.surface(
            html.Div(html.Table([html.Caption("Every cleaning rule applied in the notebook, in order"), head,
                                 html.Tbody(rows, id="md-clean-body")], className="table"),
                     className="table-wrap", tabIndex=0, role="region", **{"aria-label": "Cleaning log"}),
            class_name="md-table-surface lift"),
        html.P("No rule matches that filter. Clear the box to see all of them.", id="md-clean-empty",
               className="md-empty", hidden=True),
    ], lead=f"{len(log)} rules, in the order the notebook applies them. Filter by any word in a row.")


def _team(store: Store) -> html.Ul:
    owners: dict[str, list] = {}
    for key, item in store.results["questions"].items():
        owners.setdefault(item["owner"], []).append((key, item["label"]))
    return html.Ul([html.Li([html.Span(owner, className="md-member"),
                             html.Span("; ".join(f"{key} {label}" for key, label in asked), className="md-meta")])
                    for owner, asked in owners.items()], className="md-team")


def _credits(store: Store) -> html.Div:
    meta = store.meta
    as_of = meta["data_as_of"]
    datasets = []
    for key, role in [("housing", "Affordable housing"), ("crashes", "Crash reports")]:
        info = meta["datasets"][key]
        datasets.append(html.Li([_link(info["name"], info["url"]),
                                 html.Span(f"{role}, {meta['rows'][key]:,} rows.", className="md-meta")]))
    documents = [("Methodology", "How each question was asked and answered", f"{DOCS}/METHODOLOGY.md"),
                 ("Data dictionary", "Every column of every table", f"{DOCS}/DATA_DICTIONARY.md"),
                 ("Number changes", "Every figure that changed after the audit", f"{DOCS}/NUMBER_CHANGES.md"),
                 ("Notebook", "The whole analysis, step by step", f"{REPO}/blob/main/notebooks/NYC_Housing_Safety.ipynb"),
                 ("AI use", "Prompts, process and checks", f"{DOCS}/AI_USE.md")]
    return _part("md-credits", "Where it comes from and who made it", [
        html.Div(className="md-credits", children=[
            html.Div(className="md-credit lift", children=[
                html.H4("Datasets"), html.Ul(datasets, className="md-list"),
                html.P(f"The crash records run to {as_of['latest_crash']}, the latest housing completion is "
                       f"{as_of['latest_housing_completion']}, and the site data was built {meta['built_at']} from the "
                       "project notebook.", className="md-meta md-asof")]),
            html.Div(className="md-credit lift", style={"--i": 1}, children=[
                html.H4("Credits"), html.Ul([
                    html.Li([_link("NYC Open Data", "https://opendata.cityofnewyork.us/"),
                             html.Span("Both datasets. This project is not a city agency product.", className="md-meta")]),
                    html.Li([_link("CARTO", "https://carto.com/attributions"),
                             html.Span("Map background tiles.", className="md-meta")]),
                    html.Li([_link("OpenStreetMap contributors", "https://www.openstreetmap.org/copyright"),
                             html.Span("Map data, under the ODbL.", className="md-meta")])], className="md-list")]),
            html.Div(className="md-credit lift", style={"--i": 2}, children=[
                html.H4("Project files"), html.Ul([
                    html.Li([_link(name, href), html.Span(what, className="md-meta")]) for name, what, href in documents],
                    className="md-list"),
                html.P(["All of it lives in the ", _link("project repository", REPO), "."], className="md-meta")]),
            html.Div(className="md-credit lift", style={"--i": 3}, children=[
                html.H4("Team contributions"), _team(store),
                html.P(["The full table of who did what is in the ",
                        _link("project README", f"{REPO}#team-contributions"), "."], className="md-meta")]),
        ]),
    ])


def layout(store: Store) -> html.Section:
    rows = store.meta["rows"]
    lead = (f"Two NYC Open Data tables with no shared key, {rows['housing']:,} buildings and {rows['crashes']:,} "
            "crash reports, joined building by building. What the data cannot tell us, how it was cleaned and "
            "where it comes from.")
    return components.section("method", "How we know, and where we stop", lead, [
        _limits(store), _readers(store), _joined(store), _cleaning(store), _credits(store),
    ], tint="ember", class_name="method-chapter")


def register(app: Dash, store: Store) -> None:
    return None

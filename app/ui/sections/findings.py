"""Findings: the ten research questions as one tall composition that opens row by row. Ids here start with `fd-`.

Every number is read from the store and every sentence comes from app/story_text.py, so a changed result changes the
page. assets/js/50-findings.js opens a row in place, filters the rows, and follows a #rq7 style link.
"""
from __future__ import annotations

from dash import Dash, html

from app.analysis.story_text import (
    SAME_AS_ZERO,
    finding_extras,
    findings_lead,
    interval_level_text,
    interval_text,
    number_word,
    reading_label,
    robustness_text,
    signed,
    unit_digits,
)
from app.core.data import Store
from app.core.stats import level_text
from app.ui import charts, components, story

ZIP_UNIT = "ZIP codes"


def _is_zip_level(item: dict) -> bool:
    return item["n_unit"] == ZIP_UNIT


def _short_reading(item: dict) -> tuple[str, str]:
    """(text, CSS class) of the tag in a row. The full reading, with the reason, is inside the row."""
    if not item["excludes_zero"]:
        return "Cannot be told from zero", "tag"
    if item["kept"]:
        return "Clear of zero", "tag tag-strong"
    return "Clear of zero, not counted", "tag"


def robustness_note(store: Store, key: str, item: dict) -> str | None:
    """What was re-checked for one question, read from the stored checks. None when nothing was re-run."""
    if key == "RQ3":
        table = store.robustness[store.robustness["estimate"].notna()]
        checks = table[table["kind"] == "check"]
        including = int((~checks["interval_excludes_zero"]).sum())
        return (f"{number_word(len(checks)).capitalize()} one-change versions of this result are charted below. "
                f"{number_word(including).capitalize()} of them include zero.")
    reported = item.get("excludes_zero_reported")
    if reported is not None:
        return (f"Counting only crashes with a reported ZIP code, the interval "
                f"{'excludes' if reported else 'includes'} zero.")
    return None


def _fact(term: str, value) -> list:
    return [html.Dt(term), html.Dd(value)]


def _row(store: Store, key: str, item: dict, extra: str | None) -> html.Li:
    slug = key.lower()
    digits = unit_digits(item["unit"])
    short, short_class = _short_reading(item)
    full, _ = reading_label(item)
    note = robustness_note(store, key, item)
    level = level_text(item["level"])
    estimate = signed(item["estimate"], digits)
    facts = [
        *_fact("Estimate", f"{estimate} ({item['unit']})"),
        *_fact(f"{level} interval", interval_text(item, digits)),
        *_fact("Based on", f"{item['n']:,} {item['n_unit']}"),
        *_fact("Reading", full),
    ]
    if item.get("adjusted_p") is not None:
        facts += _fact("Adjusted p", f"{item['adjusted_p']:.2f}")
    if note:
        facts += _fact("Robustness", note)
    return html.Li(id=f"fd-{slug}", className="fd-row lift", children=html.Div(className="fd-clip", children=[
        html.Div(className="fd-summary", children=[
            html.Span(key, className="fd-key"),
            html.H3(html.Button(item["question"], type="button", id=f"fd-{slug}-toggle", className="fd-toggle",
                                **{"aria-expanded": "false", "aria-controls": f"fd-{slug}-body",
                                   "aria-describedby": f"fd-{slug}-figure fd-{slug}-tag", "data-rq": slug}),
                    className="fd-question"),
            html.Div(className="fd-meta", children=[
                html.P(f"Asked by team member {item['owner']}", className="fd-owner"),
                html.P(short, id=f"fd-{slug}-tag", className=f"fd-tag {short_class}"),
            ]),
            html.Div(id=f"fd-{slug}-figure", className="fd-figure", children=[
                html.P(estimate, className="fd-estimate",
                       **{"data-countup": str(item["estimate"]), "data-final": estimate}),
                html.P(item["unit"], className="fd-unit"),
                html.P(f"{level} interval {interval_text(item, digits)}", className="fd-range"),
            ]),
            html.Div(components.interval_mark(item["low"], item["estimate"], item["high"]), className="fd-ground"),
            html.Span([html.Span("Details", className="fd-more-text"), html.Span(className="fd-chevron")],
                      className="fd-more", **{"aria-hidden": "true"}),
        ]),
        html.Div(className="fd-collapse", children=html.Div(
            id=f"fd-{slug}-body", className="fd-inner", role="region", **{"aria-labelledby": f"fd-{slug}-toggle"},
            children=html.Div(className="fd-detail", children=[
                html.P(SAME_AS_ZERO.sub("", item["sentence"]), className="fd-sentence"),
                html.P(extra, className="fd-extra") if extra else None,
                html.Dl(facts, className="fd-facts"),
                html.Div(className="fd-links", children=[
                    html.A("Explore the records", href="#explore", className="button button-secondary"),
                    html.A("Test it", href="#lab", className="button button-secondary"),
                    html.A("Link to this finding", href=f"#{slug}", className="button button-quiet",
                           **{"data-rq-link": slug}),
                ]),
            ]))),
    ]), **{"data-rq": slug, "data-reading": "clear" if item["excludes_zero"] else "zero",
           "data-scope": "zip" if _is_zip_level(item) else "site", "data-owner": item["owner"]})


def _chip(group: str, value: str, label: str, pressed: bool = False) -> html.Button:
    return html.Button(label, type="button", className="fd-chip",
                       **{"aria-pressed": "true" if pressed else "false", "data-group": group, "data-value": value})


def _filters(questions: dict) -> html.Div:
    owners = sorted({item["owner"] for item in questions.values()})
    return html.Div(className="fd-filters lift", children=[
        html.Div(className="fd-filter-group", role="group", **{"aria-label": "Show"}, children=[
            html.Span("Show", className="field-label"),
            html.Div(className="chips", children=[
                _chip("show", "all", "All", True), _chip("show", "clear", "Clear of zero"),
                _chip("show", "zero", "Cannot be told from zero"), _chip("show", "zip", "ZIP level"),
                _chip("show", "site", "Site level")]),
        ]),
        html.Div(className="fd-filter-group", role="group", **{"aria-label": "Team member"}, children=[
            html.Span("Team member", className="field-label"),
            html.Div(className="chips", children=[_chip("owner", "all", "All", True),
                                                  *[_chip("owner", owner, owner) for owner in owners]]),
        ]),
    ])


def _robustness(store: Store) -> html.Div:
    return html.Div(className="fd-robust", children=[
        html.H3("How the main result changes with our choices", **{"data-kinetic": "words"}),
        html.P(robustness_text(store), className="fd-prose lift"),
        # A forest plot needs width for its row labels: on a phone it scrolls sideways inside its own box.
        components.surface(html.Div(components.graph("fd-robustness", charts.robustness_figure(store.robustness),
                                                     size_class="graph-forest"),
                                    className="scroll-x", tabIndex=0, role="region", **{"data-lazy": "lazy-robustness"},
                                    **{"aria-label": "Chart of the main result under each change of method"}),
                           class_name="fd-chart lift"),
        html.P(story.robustness_chart_note(store), className="fd-note lift"),
    ])


def _surprises(store: Store) -> html.Div:
    return html.Div(className="fd-surprise", children=[
        html.H3("What surprised us", **{"data-kinetic": "words"}),
        *[html.P(paragraph.children, className="fd-prose lift") for paragraph in story.surprise_paragraphs(store)],
    ])


def layout(store: Store) -> html.Section:
    questions = store.results["questions"]
    extras = finding_extras(store)
    count = len(questions)
    return components.section(
        "findings", f"{number_word(count).capitalize()} questions and what the records show",
        findings_lead(questions), [
            html.P([interval_level_text(questions), " If it crosses the vertical zero line, the records are "
                    "compatible with no change. Each mark is drawn on its own scale, in the unit named under the "
                    "estimate, so compare where a bar sits against zero, not how long it is from one row to the "
                    "next. Select a question to read its sentence, its checks and its numbers."],
                   className="fd-guide lift"),
            _filters(questions),
            html.P(f"Showing all {count} questions", id="fd-count", className="fd-count", role="status",
                   **{"aria-live": "polite", "data-total": str(count)}),
            html.Ol([_row(store, key, item, extras.get(key)) for key, item in questions.items()],
                    id="fd-list", className="fd-list"),
            html.Div(className="fd-empty", id="fd-empty", hidden=True, children=[
                html.P("No question matches these filters."),
                html.Button("Show all questions", type="button", className="button button-secondary",
                            id="fd-reset"),
            ]),
            _robustness(store),
            _surprises(store),
        ], tint="midnight", class_name="findings-chapter")


def register(app: Dash, store: Store) -> None:
    return None

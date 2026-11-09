"""Try to break the result: change the comparison and watch the estimate respond. Ids here start with `sc-`.

There is no Generate button: every choice asks /api/scenario at once. The page is drawn here and driven by
assets/js/45-tools.js.
"""
from __future__ import annotations

import json

from dash import Dash, dcc, html
from flask import jsonify, request

from app.analysis import scenarios
from app.core.data import Store
from app.ui import components

CACHE_SECONDS = 300
CONTROLS = [
    ("sites", "Which sites", "The kind of completed building being tested."),
    ("borough", "Borough", "Applies to the tested and the comparison sites."),
    ("size", "Building size, in units", "Applies to the tested sites."),
    ("group", "Comparison group", "Which sites stand in for no building."),
    ("cluster", "Leave out the largest cluster", "Sites within 250 m of each other are resampled together."),
    ("cohort", "Leave out a cohort", "Drop the sites completed in one year."),
]


def _control(key: str, label: str, help_text: str, store: Store) -> html.Div:
    """A named radio group. The radios stay native, so arrow keys and screen readers work as usual."""
    choices = [{"label": text, "value": value} for value, text in scenarios.options(store)[key]]
    group = html.Div(className="segmented-field", children=[
        html.Span(label, className="field-label", id=f"sc-{key}-label"),
        dcc.RadioItems(id=f"sc-{key}", options=choices, value=scenarios.DEFAULT_SPEC[key], inline=True,
                       className="segmented", labelClassName="segment")])
    return html.Div(className="sc-control", role="radiogroup", **{"aria-labelledby": f"sc-{key}-label"},
                    children=[group, html.P(help_text, className="field-help")])


def _button(button_id: str, text: str, **extra) -> html.Button:
    return html.Button(text, id=button_id, type="button", className="button button-secondary", **extra)


def layout(store: Store) -> html.Section:
    reference = scenarios.reference(store)
    published = reference["published"]
    lead = (f"The published result compares {published['n_tested_sites']:,} new buildings with {published['n_comparison_sites']:,} "
            "sites not yet finished. Change who is compared and the answer is recomputed from the records at once. "
            "If a small change makes it jump, it was never solid.")
    options = {key: [value for value, _ in choices] for key, choices in scenarios.options(store).items()}
    # A workbench: the choices on the left, the live answer on the right. The answer panel stays in view while
    # the choices change, so every click is seen landing. On a phone a small readout floats at the foot instead.
    return components.section("lab", "Try to break the result", lead, [
        html.Div(id="sc-root", className="sc-root sc-workbench", **{"data-reference": json.dumps(reference), "data-options": json.dumps(options)}, children=[
            html.Div(className="sc-pane sc-pane-controls", children=[
                html.P("Change one choice at a time", className="sc-pane-kicker"),
                html.Div(className="sc-controls", children=[_control(key, label, help_text, store) for key, label, help_text in CONTROLS]),
                html.Div(className="sc-actions", children=[
                    _button("sc-back", "Back one step", disabled=True), _button("sc-reset", "Reset", disabled=True),
                    _button("sc-copy", "Copy link")]),
            ]),
            html.Aside(className="sc-pane sc-pane-result", **{"aria-label": "The answer for these choices"}, children=[
                html.Div(className="sc-panel surface spot", children=[
                    html.P("This scenario", className="sc-pane-kicker"),
                    html.Div(className="sc-readout", children=[
                        html.P(id="sc-value", className="sc-value", children=f"{published['estimate']:+.1f}%".replace("-", "−")),
                        html.P(id="sc-tag", className="sc-tag"),
                    ]),
                    html.P(id="sc-range", className="sc-range"),
                    html.Div(id="sc-axis", className="sc-axis"),
                    html.P(id="sc-sentence", className="sc-sentence"),
                    html.Div(id="sc-empty", className="sc-empty", hidden=True),
                    html.Div(className="sc-lower", children=[
                        html.Div(className="sc-tally", children=[
                            html.P(id="sc-count", className="sc-count"),
                            html.P(id="sc-count-note", className="sc-count-note"),
                        ]),
                        html.Div(className="sc-history-wrap", children=[
                            html.H3("The last 8 scenarios", className="sc-history-title"),
                            html.Ol(id="sc-history", className="sc-history"),
                        ]),
                    ]),
                ]),
            ]),
            html.P(id="sc-status", className="visually-hidden", role="status", **{"aria-live": "polite"}),
            html.Div(id="sc-float", className="sc-float", **{"aria-hidden": "true"}),
        ]),
    ], "plum", "chapter-lab")


def register(app: Dash, store: Store) -> None:
    def scenario():
        response = jsonify(scenarios.run(store, request.args.to_dict()))
        response.headers["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
        return response

    if "api_scenario" not in app.server.view_functions:
        app.server.add_url_rule("/api/scenario", "api_scenario", scenario)

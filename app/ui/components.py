"""Shared building blocks for the sections. Pure functions returning Dash components; no data logic, no callbacks.

Motion is declared here and run by assets/js/00-motion.js:
  data-kinetic  a heading whose words rise out of a mask as it enters the window
  data-scrub    a paragraph whose words light up with the scroll position
  data-countup  a figure that counts up to its value when it enters the window
Text stays plain and fully visible if the script does not run or the reader asks for less motion.
"""
from __future__ import annotations

from dash import dcc, html

from app.ui.theme import GRAPH_CONFIG


def section(section_id: str, title: str, lead: str | list | None, children: list, tint: str = "midnight",
            class_name: str = "") -> html.Section:
    """One chapter of the page. `tint` names the ground the page drifts to while this section is in view."""
    return html.Section(id=section_id, className=f"chapter {class_name}".strip(), **{"data-tint": tint}, children=[
        html.Header(className="chapter-head", children=[
            html.H2(title, **{"data-kinetic": "words"}),
            html.P(lead, className="chapter-lead", **{"data-scrub": "words"}) if lead else None,
        ]),
        *children,
    ])


def surface(children: list, class_name: str = "", **attrs) -> html.Div:
    """A raised area with a soft light that follows the pointer."""
    return html.Div(children, className=f"surface spot {class_name}".strip(), **attrs)


def metric(value: str, label: str, detail: str | None = None, tone: str = "", count_to: float | None = None) -> html.Div:
    """One figure with its label. `count_to` makes it count up, ending exactly on `value`."""
    extra = {"data-countup": str(count_to), "data-final": value} if count_to is not None else {}
    return html.Div(className="metric", children=[
        html.P(value, className=f"metric-value {tone}".strip(), **extra),
        html.P(label, className="metric-label"),
        html.P(detail, className="metric-detail") if detail else None,
    ])


def interval_mark(low: float, estimate: float, high: float, reach: float | None = None, label: str | None = None) -> html.Div:
    """One interval against zero. It is read by the text beside it unless a `label` is given."""
    reach = reach or max(abs(low), abs(high), abs(estimate)) * 1.15 or 1.0

    def position(value: float) -> float:
        return min(100.0, max(0.0, 50 + 50 * value / reach))

    attrs = {"role": "img", "aria-label": label} if label else {"aria-hidden": "true"}
    return html.Div(className="interval", **attrs, children=[
        html.Span(className="interval-zero"),
        html.Span(className="interval-bar", style={"left": f"{position(low):.2f}%",
                                                   "right": f"{100 - position(high):.2f}%"}),
        html.Span(className="interval-dot", style={"left": f"{position(estimate):.2f}%"}),
    ])


def graph(graph_id: str, figure=None, *, size_class: str = "", config: dict | None = None) -> html.Div:
    """A chart in a box whose height is set in CSS, so a new figure never moves the page."""
    props = {"figure": figure} if figure is not None else {}
    return html.Div(dcc.Graph(id=graph_id, config=config or GRAPH_CONFIG, responsive=True,
                              style={"height": "100%"}, **props),
                    className=f"graph {size_class}".strip())


def segmented(control_id: str, options: list[dict], value, label: str) -> html.Div:
    """A row of mutually exclusive choices: a real radio group, styled as one track."""
    return html.Div(className="segmented-field", role="radiogroup", **{"aria-labelledby": f"{control_id}-label"}, children=[
        html.Span(label, className="field-label", id=f"{control_id}-label"),
        dcc.RadioItems(id=control_id, options=options, value=value, inline=True, className="segmented",
                       labelClassName="segment"),
    ])


def fx_button(label, button_id: str, primary: bool = True, **attrs) -> html.Button:
    """A button with the page's hover: it leans toward the pointer, a light sweeps it, a press sends a ripple."""
    kind = "button-primary" if primary else "button-secondary"
    return html.Button(label, id=button_id, n_clicks=0, type="button", className=f"button {kind}", **attrs)

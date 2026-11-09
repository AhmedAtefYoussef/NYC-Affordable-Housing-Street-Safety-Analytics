"""The whole page, top to bottom. One continuous page: each part is a module in app/sections/ with
`layout(store)` and `register(app, store)`, and owns its id prefix."""
from __future__ import annotations

from dash import Dash, html

from app.core.data import Store
from app.ui import story
from app.ui.sections import block, explorer, findings, lab, method, overview

SECTIONS = [overview, block, lab, explorer, findings, method]
NAV = [("story", "The story"), ("block", "Your block"), ("lab", "Test it"), ("explore", "Explore"),
       ("findings", "Findings"), ("method", "Method")]


def _nav_link(target: str, label: str) -> html.A:
    """One link. A lit pill glides beneath it on hover and rests under the section in view (assets/js/00-motion.js)."""
    return html.A(label, href=f"#{target}", className="nav-link")


def _masthead() -> html.Header:
    return html.Header(className="masthead", children=[
        # The title alone is the way back to the top; the picture lives in the browser tab and the home-screen icon.
        html.A("Housing & Streets, NYC", href="#top", className="brand", title="Back to the top"),
        html.Nav([_nav_link(*item) for item in NAV], className="nav", **{"aria-label": "Sections"}),
    ])


def _facts(store: Store) -> html.Div:
    """Real figures for the browser's animations, so no script types a number."""
    rows = store.meta["rows"]
    return html.Div(id="facts", hidden=True, **{"data-crashes": f"{rows['crashes']:,}", "data-housing": f"{rows['housing']:,}",
                                                "data-sites": f"{len(store.sites):,}"})


def build_page(store: Store) -> html.Div:
    return html.Div(className="page", id="top", children=[
        html.A("Skip to the report", href="#explore", className="skip-link"),
        html.Div(id="thread", className="thread", **{"aria-hidden": "true"}),
        _facts(store),
        _masthead(),
        html.Main([section.layout(store) for section in SECTIONS]),
        story.footer(store),
    ])


def register(app: Dash, store: Store) -> None:
    for section in SECTIONS:
        section.register(app, store)

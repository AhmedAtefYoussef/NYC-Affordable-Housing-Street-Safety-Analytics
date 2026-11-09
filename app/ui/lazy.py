"""Parts of the page that are built only when the reader comes near them.

The charts are Plotly figures, and the first one on the page makes the browser fetch and parse about 4.5 MB of
Plotly, then draw every figure. On a phone that held up the opening story for many seconds. So a part marked
`data-lazy="<name>"` in a section's layout is served as an empty frame of the same height; when the reader
scrolls within about two screens of it, assets/js/12-lazy.js sets the store `<name>-seen`, and the callback below
returns the real content and sets `<name>-ready`, which later callbacks can wait for (the report waits for
`lazy-report-ready` before drawing its charts).

The sections keep building their full content, so their tests and the callback checks see every chart:
`defer` returns the page to serve and leaves the full page for `app.validation_layout`.
"""
from __future__ import annotations

import copy

from dash import Dash, Input, Output, dcc, html


def _attribute(node, name: str):
    return getattr(node, "_prop_names", None) is not None and node.to_plotly_json()["props"].get(name)


def _walk(node):
    yield node
    children = getattr(node, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    elif children is not None and not isinstance(children, (str, int, float)):
        yield from _walk(children)


def defer(page) -> tuple[object, dict, list]:
    """(page to serve, {name: the content it stands in for}, the stores it added). `page` keeps its content."""
    for node in _walk(page):                     # the frame takes its name as id, in both pages
        name = _attribute(node, "data-lazy")
        if name:
            node.id = name
    served = copy.deepcopy(page)
    held = {}
    for node in _walk(served):
        name = _attribute(node, "data-lazy")
        if name:
            held[name] = node.children
            node.children = html.Div(className="lazy-frame", **{"aria-hidden": "true"})
    stores = [store for name in held for store in (dcc.Store(id=f"{name}-seen"), dcc.Store(id=f"{name}-ready"))]
    served.children = [*served.children, *stores]
    return served, held, copy.deepcopy(stores)


def register(app: Dash, held: dict) -> None:
    for name, content in held.items():
        def mount(_seen, content=content):
            return content, True

        app.callback(Output(name, "children"), Output(f"{name}-ready", "data"), Input(f"{name}-seen", "data"),
                     prevent_initial_call=True)(mount)

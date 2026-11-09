"""The charts load Plotly (about 4.5 MB), so they are not in the page the browser first receives: each part marked
data-lazy is an empty frame until the reader comes near (app/lazy.py), and the full page still checks the callbacks."""
from __future__ import annotations

import json

import pytest

from app import app as site
from app.ui import lazy


def _types(component) -> str:
    return json.dumps(component.to_plotly_json(), default=lambda o: o.to_plotly_json() if hasattr(o, "to_plotly_json") else str(o))


@pytest.fixture(scope="module")
def client():
    return site.server.test_client()


def test_the_served_page_has_no_chart_and_the_full_page_has_all_ten():
    assert _types(site.app.layout).count('"type": "Graph"') == 0
    assert _types(site.app.validation_layout).count('"type": "Graph"') == 10


def test_each_deferred_part_is_a_frame_with_its_two_stores():
    served = _types(site.app.layout)
    for name in ("lazy-report", "lazy-robustness", "lazy-reporting"):
        assert f'"id": "{name}"' in served and f'"id": "{name}-seen"' in served and f'"id": "{name}-ready"' in served
    assert served.count("lazy-frame") == 3


def test_coming_near_returns_the_real_content(client):
    for name, graph_id in (("lazy-report", "fig-map"), ("lazy-robustness", "fd-robustness"), ("lazy-reporting", "md-reporting")):
        payload = {"output": f"..{name}.children...{name}-ready.data..",
                   "outputs": [{"id": name, "property": "children"}, {"id": f"{name}-ready", "property": "data"}],
                   "inputs": [{"id": f"{name}-seen", "property": "data", "value": 1}], "changedPropIds": [f"{name}-seen.data"],
                   "state": []}
        reply = client.post("/_dash-update-component", json=payload)
        assert reply.status_code == 200, name
        body = reply.get_json()["response"]
        assert graph_id in json.dumps(body[name]["children"]) and body[f"{name}-ready"]["data"] is True


def test_defer_leaves_the_full_page_whole():
    from dash import dcc, html
    page = html.Div([html.Div(dcc.Graph(id="g"), **{"data-lazy": "lazy-x"})])
    served, held, stores = lazy.defer(page)
    assert '"type": "Graph"' in _types(page) and '"type": "Graph"' not in _types(served)
    assert set(held) == {"lazy-x"} and [s.id for s in stores] == ["lazy-x-seen", "lazy-x-ready"]

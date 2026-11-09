"""Hostile client values: the filter model never raises and the endpoints answer 200 with the security headers."""
from __future__ import annotations

import itertools

import pytest

from app.core.filters import (
    DEFAULT_HARM,
    DEFAULT_SCOPE,
    YEAR_END,
    YEAR_START,
    from_dict,
    make_filters,
    reversed_years_note,
)

HOSTILE = [
    float("inf"), float("-inf"), float("nan"), 10**400, -(10**400), 2019.7, True, False, 0, -1, 5,
    "abc", "", "9" * 5000, "Bronx", "injury", None,
    [], [[]], [["Bronx"]], [{"a": 1}], [None], [1, 2], ["Bronx", ["Brooklyn"]], [float("inf")],
    {}, {"a": 1}, {"Bronx": True}, ("Bronx",), b"Bronx", object(),
]
FIELDS = ["boroughs", "year_from", "year_to", "construction", "sizes", "factors", "hours", "harm", "scope"]


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", HOSTILE, ids=repr)
def test_make_filters_never_raises(field, value):
    filters = make_filters(**{field: value})
    assert YEAR_START <= filters.year_from <= filters.year_to <= YEAR_END
    assert filters.harm_noun and filters.scope in {DEFAULT_SCOPE, "near", "city"}
    reversed_years_note(value, value)
    assert from_dict(filters.to_dict()) == filters


def test_make_filters_with_every_field_hostile_at_once():
    for first, second in itertools.permutations(HOSTILE[:12], 2):
        filters = make_filters(*([first, second] * 5)[:9])
        assert filters.harm == DEFAULT_HARM or isinstance(filters.harm, str)
    assert make_filters(*([HOSTILE[0]] * 9)) == make_filters(year_from=None, year_to=None)


def test_invalid_values_fall_back_to_the_default():
    default = make_filters()
    for value in (float("inf"), [["Bronx"]], {"a": 1}, 5, ["injury"], []):
        assert make_filters(boroughs=value, year_from=value, harm=value, scope=value) == default
    assert make_filters(year_from=float("inf"), year_to=2020).year_from == YEAR_START
    assert make_filters(year_to=float("-inf")).year_to == YEAR_END
    assert make_filters(boroughs=[["Bronx"], "Queens", 7]).boroughs == ("Queens",)


def test_from_dict_survives_a_hostile_store():
    assert from_dict({"boroughs": {"a": 1}, "year_from": [2019], "harm": ["x"], "unknown": 1}) == make_filters()


# ---- the HTTP boundary ---------------------------------------------------------------------
SECURITY = ("Content-Security-Policy", "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy")


@pytest.fixture(scope="module")
def client():
    from app.app import server
    return server.test_client()


def _payload(client, trigger: str, overrides: dict, output_hint: str = ""):
    dependencies = client.get("/_dash-dependencies").get_json()
    spec = next(item for item in dependencies if output_hint in item["output"] and any(
        f"{entry['id']}.{entry['property']}" == trigger for entry in item["inputs"]))

    def fill(entries):
        return [{"id": entry["id"], "property": entry["property"],
                 "value": overrides.get(f"{entry['id']}.{entry['property']}")} for entry in entries]

    outputs = [{"id": part.rsplit(".", 1)[0], "property": part.rsplit(".", 1)[1].split("@")[0]}
               for part in spec["output"].strip(".").split("...")]
    return {"output": spec["output"], "outputs": outputs if len(outputs) > 1 else outputs[0],
            "inputs": fill(spec["inputs"]), "state": fill(spec["state"]), "changedPropIds": [trigger]}


def _assert_secure(reply):
    for name in SECURITY:
        assert reply.headers.get(name), f"{name} missing"
    assert reply.headers["X-Content-Type-Options"] == "nosniff"
    assert reply.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in reply.headers["Content-Security-Policy"]


def test_every_kind_of_response_carries_the_security_headers(client):
    from app.ui.grid import grid_url
    for path in ("/", "/_dash-layout", "/_dash-dependencies", "/assets/site.css", grid_url(),
                 "/data/crash-grid.geojson", "/no-such-page"):
        _assert_secure(client.get(path))


def test_csp_allows_the_hosts_the_page_loads(client):
    policy = client.get("/").headers["Content-Security-Policy"]
    for needed in ("https://fonts.googleapis.com", "https://fonts.gstatic.com", "basemaps.cartocdn.com",
                   "worker-src 'self' blob:"):
        assert needed in policy


def test_the_grid_url_is_versioned_and_immutable_but_the_bare_url_revalidates(client):
    from app.ui.grid import grid_url
    url = grid_url()
    assert url.startswith("/data/crash-grid.geojson?v=") and len(url.split("=")[1]) == 12
    versioned = client.get(url)
    assert "immutable" in versioned.headers["Cache-Control"]
    bare = client.get("/data/crash-grid.geojson")
    assert bare.headers["Cache-Control"] == "no-cache"
    assert client.get(url, headers={"If-None-Match": versioned.headers["ETag"]}).status_code == 304
    assert "immutable" not in client.get("/data/crash-grid.geojson?v=stale").headers["Cache-Control"]


CONTROL_STATE = {"f-borough": "value", "f-year-from": "value", "f-year-to": "value", "f-construction": "value",
                 "f-size": "value", "f-factor": "value", "f-hour": "value", "f-harm": "value", "f-scope": "value"}
SAMPLE = [float("inf"), float("-inf"), [["Bronx"]], [{"a": 1}], 5, ["injury"], {"a": 1}, [], "abc", None, 10**400]


@pytest.mark.parametrize("value", SAMPLE, ids=repr)
def test_generate_callback_answers_200_for_hostile_state(client, value):
    overrides = {f"{control}.{prop}": value for control, prop in CONTROL_STATE.items()}
    overrides["generate.n_clicks"] = 1
    reply = client.post("/_dash-update-component", json=_payload(client, "generate.n_clicks", overrides, "fig-map"))
    assert reply.status_code == 200, reply.get_data(as_text=True)[:300]
    _assert_secure(reply)


@pytest.mark.parametrize("control", sorted(CONTROL_STATE))
def test_generate_callback_with_one_hostile_control(client, control):
    for value in ([["Bronx"]], float("inf"), {"a": 1}):
        overrides = {f"{control}.value": value, "generate.n_clicks": 1}
        reply = client.post("/_dash-update-component",
                            json=_payload(client, "generate.n_clicks", overrides, "fig-map"))
        assert reply.status_code == 200, (control, value, reply.get_data(as_text=True)[:300])


@pytest.mark.parametrize("text", ["", "x" * 5000, "<script>alert(1)</script>", "\x00‮", "2016 2020 2025", None, 5])
def test_search_callback_answers_200_for_hostile_text(client, text):
    overrides = {"search.value": text}
    reply = client.post("/_dash-update-component", json=_payload(client, "search.value", overrides))
    assert reply.status_code == 200, reply.get_data(as_text=True)[:300]
    _assert_secure(reply)

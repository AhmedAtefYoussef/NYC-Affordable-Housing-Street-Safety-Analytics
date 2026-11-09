"""The overview's canvas data: real records, the funnel the report states, and RQ3's own bootstrap."""
from __future__ import annotations

import gzip
import json
import re

import numpy as np
import pytest

from app.analysis import story_data
from app.analysis.story_text import signed
from app.core import stats
from app.core.data import load
from app.ui import page
from app.ui.sections import overview

MAX_GZIP_BYTES = 150 * 1024
HISTOGRAM_BIN = 5


@pytest.fixture(scope="module")
def store():
    return load()


@pytest.fixture(scope="module")
def payload(store):
    return story_data.story_payload(store)


@pytest.fixture(scope="module")
def client():
    from app.app import server
    return server.test_client()


def test_one_record_per_located_site(store, payload):
    assert payload["n"] == len(store.sites) == store.results["facts"]["sites"]
    for name in ["lon", "lat", "new", "units", "percentile", "borough", "stage", "name"]:
        assert len(payload[name]) == payload["n"], name


def test_coordinates_decode_to_the_real_buildings(store, payload):
    scale = payload["scale"]
    lon = (np.array(payload["lon"]) + payload["origin"][0]) / scale
    lat = (np.array(payload["lat"]) + payload["origin"][1]) / scale
    assert np.abs(lon - store.sites["lon"].to_numpy(dtype=float)).max() < 1 / scale
    assert np.abs(lat - store.sites["lat"].to_numpy(dtype=float)).max() < 1 / scale


def test_funnel_equals_the_stated_facts(store, payload):
    facts = store.results["facts"]
    assert payload["funnel"] == [facts["sites"], facts["treated_candidates"], facts["treated_clean"],
                                 store.results["questions"]["RQ3"]["n"]]
    assert payload["funnel"] == [7593, 2086, 306, 128]


def test_funnel_stages_nest_and_end_on_the_rq3_sites(store, payload):
    stage = np.array(payload["stage"])
    assert [int((stage >= position).sum()) for position in range(4)] == payload["funnel"]
    table = store.event_sites
    compared = table[table["treated"] & (table["construction_type"].astype(str) == "New Construction")]
    assert set(store.sites["site_id"].to_numpy()[stage == 3]) == set(compared["site_id"])


def test_the_robustness_central_row_has_the_same_128(store, payload):
    assert int(store.robustness.iloc[0]["n_treated"]) == payload["funnel"][3]


def test_outcomes_are_sorted_and_counted(payload):
    outcomes = np.array(payload["outcomes"])
    assert len(outcomes) == story_data.N_OUTCOMES == 50
    assert (np.diff(outcomes) >= 0).all()
    assert payload["below_zero"] == int((outcomes < 0).sum())


def test_quantile_median_is_the_rq3_estimate_within_one_quantile_step(store, payload):
    outcomes = np.array(payload["outcomes"])
    middle = len(outcomes) // 2
    step = outcomes[middle] - outcomes[middle - 1]
    assert abs(np.median(outcomes) - store.results["questions"]["RQ3"]["estimate"]) <= step


def test_outcomes_span_the_rq3_interval(store, payload):
    rq3 = store.results["questions"]["RQ3"]
    outcomes = payload["outcomes"]
    # The 50 quantiles run from the 1st to the 99th percentile, so they reach past the 95% interval.
    assert outcomes[0] <= rq3["low"] and outcomes[-1] >= rq3["high"]


def test_outcomes_use_the_same_draws_as_did_log_ratio(store):
    """The written-out bootstrap in story_data must stay the same call as stats.did_log_ratio."""
    sample = store.event_sites[~store.event_sites["treated"]
                               | (store.event_sites["construction_type"].astype(str) == "New Construction")]
    before = sample[["injury_-3", "injury_-2", "injury_-1"]].to_numpy(dtype=float).sum(axis=1)
    after = sample[["injury_+1", "injury_+2", "injury_+3"]].to_numpy(dtype=float).sum(axis=1)
    did = stats.did_log_ratio(before, after, sample["treated"].to_numpy(), sample["cohort"].to_numpy(),
                              sample["cluster_id"].to_numpy())
    rq3 = store.results["questions"]["RQ3"]
    assert did["percent_change"] == pytest.approx(rq3["estimate"], abs=1e-9)
    assert did["percent_low"] == pytest.approx(rq3["low"], abs=1e-9)
    assert did["percent_high"] == pytest.approx(rq3["high"], abs=1e-9)
    assert story_data.rq3_outcomes(store)["n_boot"] == stats.N_BOOT


def test_percentile_histogram_matches_the_statistics(store, payload):
    """Stacking by the rounded percentile must put every building in the bin of its true percentile."""
    is_new = np.array(payload["new"]) == 1
    codes = np.array(payload["percentile"])
    used = is_new & (codes >= 0)
    assert used.sum() == store.results["questions"]["RQ7"]["n"]
    drawn = np.clip(codes[used] // (HISTOGRAM_BIN * payload["percentile_scale"]), 0, 19)
    true = np.clip(store.sites["borough_percentile"].to_numpy(dtype=float)[used] // HISTOGRAM_BIN, 0, 19)
    assert (drawn == true).all()


def test_units_and_names_are_the_records(store, payload):
    assert payload["units"] == store.sites["total_units"].astype(int).tolist()
    assert payload["name"] == store.sites["project_name"].astype(str).tolist()
    assert sorted(set(payload["borough"])) == list(range(len(payload["boroughs"])))


def test_variants_come_from_the_robustness_table(store, payload):
    assert [item["label"] for item in payload["variants"]] == store.robustness["variant"].astype(str).tolist()
    assert np.allclose([item["estimate"] for item in payload["variants"]], store.robustness["percent_change"], atol=0.005)


def test_payload_is_under_the_size_limit(store):
    assert len(story_data.encoded(store)[1]) < MAX_GZIP_BYTES


def test_bytes_are_deterministic(store):
    first = story_data.encoded.__wrapped__(store)
    second = story_data.encoded.__wrapped__(store)
    assert first == second
    assert json.loads(gzip.decompress(first[1])) == json.loads(first[0])
    assert story_data.versioned_url(store).endswith(first[2])


def test_route_serves_gzip_and_caches_only_the_hashed_url(store, client):
    url = story_data.versioned_url(store)
    hashed = client.get(url, headers={"Accept-Encoding": "gzip"})
    assert hashed.status_code == 200 and hashed.headers["Content-Encoding"] == "gzip"
    assert "immutable" in hashed.headers["Cache-Control"]
    assert json.loads(gzip.decompress(hashed.data))["n"] == 7593
    bare = client.get(story_data.STORY_URL)
    assert "Content-Encoding" not in bare.headers and bare.headers["Cache-Control"] == "no-cache"
    assert json.loads(bare.data)["n"] == 7593


def test_a_stale_hash_is_not_cached_for_good(client):
    assert client.get(f"{story_data.STORY_URL}?v=<script>").headers["Cache-Control"] == "no-cache"


def _text(component) -> str:
    """All the text under a Dash component."""
    children = getattr(component, "children", component)
    if isinstance(children, (list, tuple)):
        return " ".join(_text(child) for child in children if child is not None)
    if isinstance(children, (str, int, float)):
        return str(children)
    return "" if children is None or children is component else _text(children)


def test_the_view_states_the_answers_from_the_store(store):
    text = _text(page.build_page(store))
    results = store.results
    assert "Do injury crashes rise around affordable housing once it opens?" in text
    for figure in [f"{results['questions']['RQ3']['estimate']:.1f}".replace("-", "−"),
                   f"{50 + results['questions']['RQ7']['estimate']:.0f}th",
                   signed(results['detail']['rq7']['one_vote']['estimate'])]:
        assert figure in text, figure
    for count in story_data.funnel_counts(store):
        assert f"{count:,}" in text


def test_the_view_names_the_comparison_cuts_that_exclude_zero(store):
    text = _text(page.build_page(store))
    table = store.robustness
    cuts = table[(table["check"].astype(str) == "Comparison subset") & table["interval_excludes_zero"]]
    assert len(cuts) == 2
    for name in cuts["variant"].astype(str):
        assert name in text
    assert "unadjusted" in text


def test_copy_has_no_banned_marks(store):
    text = _text(overview.layout(store))
    assert "—" not in text
    assert not re.search(r"\bcaused?\b", text)

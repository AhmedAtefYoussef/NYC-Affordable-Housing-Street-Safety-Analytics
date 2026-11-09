"""The what-if lab: the default is RQ3 exactly, every comparison group matches its published row, input is never trusted."""
from __future__ import annotations

import json
import math
import random
import time

import numpy as np
import pytest

from app.analysis import scenarios
from app.core.data import MIN_GROUP_N, load


@pytest.fixture(scope="module")
def store():
    return load()


@pytest.fixture(scope="module")
def client():
    from app.app import server
    return server.test_client()


def _row(store, variant):
    return store.robustness[store.robustness["variant"] == variant].iloc[0]


def test_default_spec_reproduces_rq3_exactly(store):
    result = scenarios.run(store, scenarios.DEFAULT_SPEC)
    published = store.results["questions"]["RQ3"]
    assert result["status"] == "ok" and result["is_default"]
    # Recomputed, not read back: the last digit can differ between the machine that built the data and this one.
    assert (result["estimate"], result["low"], result["high"]) == pytest.approx(
        (published["estimate"], published["low"], published["high"]), rel=1e-12)
    assert result["n_tested_sites"] == published["n"]
    detail = store.results["detail"]["rq3_did"]
    assert result["p_value"] == pytest.approx(detail["p_value"], rel=1e-12)
    assert result["n_comparison_sites"] == detail["n_comparison_sites"]
    assert result["n_comparison_rows"] == detail["n_control"]
    assert result["n_clusters"] == detail["n_clusters"]
    assert result["n_tested_clusters"] == detail["n_treated_clusters"]
    assert not result["excludes_zero"] and result["tag"] == scenarios.TAG_UNCLEAR


@pytest.mark.parametrize("group, variant", [
    ("not_started", "Only sites not started by the window's end"),
    ("started", "Only sites started inside the window"),
    ("same", "Only new-construction sites (same type)"),
    ("other", "Only preservation sites (other type)"),
])
def test_each_comparison_group_matches_its_robustness_row(store, group, variant):
    result, row = scenarios.run(store, {"group": group}), _row(store, variant)
    assert result["n_tested_sites"] == row["n_treated"]
    assert result["n_comparison_rows"] == row["n_comparison"]
    assert result["n_comparison_sites"] == row["n_comparison_sites"]
    assert result["n_clusters"] == row["n_resampled_units"]
    assert result["n_tested_clusters"] == row["n_treated_clusters"]
    assert (result["estimate"], result["low"], result["high"]) == pytest.approx(
        (row["percent_change"], row["percent_low"], row["percent_high"]), rel=1e-12)
    assert result["excludes_zero"] == row["interval_excludes_zero"]


def test_leaving_out_a_cohort_matches_its_robustness_row(store):
    result, row = scenarios.run(store, {"cohort": "2019"}), _row(store, "Without the 2019 cohort")
    assert (result["n_tested_sites"], result["n_comparison_rows"]) == (row["n_treated"], row["n_comparison"])
    assert (result["estimate"], result["low"], result["high"]) == pytest.approx(
        (row["percent_change"], row["percent_low"], row["percent_high"]), rel=1e-12)


def test_a_result_that_excludes_zero_is_labelled_an_unadjusted_association(store):
    result = scenarios.run(store, {"group": "not_started"})
    assert result["excludes_zero"] and "unadjusted association" in result["tag"]


def test_the_sentence_is_built_from_the_numbers(store):
    result = scenarios.run(store, {"group": "same", "borough": "Queens"})
    if result["status"] == "ok":
        assert f"{result['estimate']:+.1f}%" in result["sentence"] and "Queens" in result["sentence"]
    default = scenarios.run(store)
    for piece in (f"{default['estimate']:+.1f}%", f"{default['low']:+.1f}%", f"{default['high']:+.1f}%", "128", "696"):
        assert piece in default["sentence"]


def test_leaving_out_the_largest_cluster_removes_the_largest_in_the_selection(store):
    result = scenarios.run(store, {"cluster": "out"})
    events = store.event_sites
    sample = events[~events["treated"] | (events["construction_type"] == "New Construction")]
    counts = sample["cluster_id"].value_counts()
    assert result["left_out"]["cluster_id"] == counts.index[0] and result["left_out"]["n_rows"] == counts.iloc[0]
    assert result["n_comparison_rows"] + result["left_out"]["n_rows"] - result["left_out"]["n_tested_sites"] == 1869


def test_an_empty_scenario_names_what_to_loosen(store):
    result = scenarios.run(store, {"borough": "Staten Island", "size": "150+", "group": "started"})
    assert result["status"] == "empty" and result["estimate"] is None
    assert str(MIN_GROUP_N) in result["message"]
    keys = {move["key"] for move in result["loosen"]}
    assert keys == {"borough", "size", "group"}
    assert all({"label", "n_tested_sites", "n_comparison_sites", "enough"} <= set(move) for move in result["loosen"])


def _hostile_values():
    return [None, 7, 1.5, True, [], ["new"], {}, {"a": 1}, "", " ", "new ", "NEW", "'; DROP TABLE", "<script>alert(1)</script>",
            "../../etc/passwd", "\x00", "😀", "9" * 5000, "2019.0", "-1", float("nan"), float("inf"), b"new", object()]


def test_hostile_specs_fall_back_to_the_default(store):
    default = scenarios.run(store)
    for spec in [None, 3, "new", [], ["sites"], *_hostile_values()]:
        assert scenarios.run(store, spec)["spec"] == scenarios.DEFAULT_SPEC
    for key in scenarios.DEFAULT_SPEC:
        for value in _hostile_values():
            assert scenarios.run(store, {key: value})["estimate"] == default["estimate"], (key, value)
    assert scenarios.run(store, {"unknown": "x", "__class__": "y"})["spec"] == scenarios.DEFAULT_SPEC


def test_random_specs_always_answer_and_stay_json_safe(store):
    choices = scenarios.options(store)
    generator = random.Random(7)
    for _ in range(40):
        spec = {key: generator.choice([value for value, _ in values] + ["nope", None]) for key, values in choices.items()}
        result = scenarios.run(store, spec)
        assert result["status"] in ("ok", "empty")
        text = json.dumps(result, allow_nan=False)      # raises on NaN or infinity
        assert "NaN" not in text
        if result["status"] == "ok":
            assert result["low"] <= result["estimate"] <= result["high"]
            assert min(result["n_tested_sites"], result["n_comparison_sites"]) >= MIN_GROUP_N
        else:
            assert result["message"]


def test_unsigned_counts_do_not_wrap(store):
    from app.analysis.scenarios import _columns
    columns = _columns(store)
    table = store.event_sites
    wide = sum(table[f"injury_{year:+d}"].to_numpy(dtype=np.int64) for year in (-3, -2, -1))
    assert columns.before.dtype == np.float64 and (columns.before == wide).all()
    assert table["injury_-3"].dtype == np.uint8          # the trap this guards against is still in the data


def test_the_cache_is_bounded_and_a_repeat_is_immediate(store):
    assert scenarios._compute.cache_info().maxsize == scenarios.CACHE_SIZE
    scenarios.run(store, {"group": "started", "cohort": "2020"})
    started = time.perf_counter()
    scenarios.run(store, {"group": "started", "cohort": "2020"})
    assert time.perf_counter() - started < 0.01


def test_a_new_scenario_stays_under_the_time_budget_warm(store):
    scenarios.run(store)
    scenarios._compute.cache_clear()
    timings = []
    for spec in ({"group": "same"}, {"sites": "preservation"}, {"cohort": "2021"}, {"group": "other"}, {"cluster": "out"}):
        started = time.perf_counter()
        scenarios.run(store, spec)
        timings.append(time.perf_counter() - started)
    assert sorted(timings)[len(timings) // 2] < 0.4        # 200 ms on the target; doubled to hold on a busy CI runner


def test_the_reference_carries_every_published_row_and_is_json(store):
    reference = scenarios.reference(store)
    assert len(reference["rows"]) == int(store.robustness["percent_change"].notna().sum())
    assert reference["published"]["estimate"] == store.results["questions"]["RQ3"]["estimate"]
    assert json.loads(json.dumps(reference, allow_nan=False))["defaults"] == scenarios.DEFAULT_SPEC


def test_the_route_answers_hostile_queries(client):
    assert client.get("/api/scenario").get_json()["is_default"]
    for query in ("sites=%00&borough=%3Cscript%3E", "size=" + "9" * 3000, "group=1&group=2&cluster[]=x", "cohort=-1"):
        response = client.get(f"/api/scenario?{query}")
        assert response.status_code == 200 and response.get_json()["is_default"]
    chosen = client.get("/api/scenario?group=not_started&borough=all").get_json()
    assert chosen["spec"]["group"] == "not_started" and chosen["excludes_zero"]


def test_every_published_number_is_finite(store):
    for row in scenarios.reference(store)["rows"]:
        assert all(math.isfinite(row[name]) for name in ("estimate", "low", "high"))


def test_the_page_names_each_control_and_never_shows_a_generate_button(store):
    from app.ui.sections import lab as view
    rendered = str(view.layout(store))
    for key in scenarios.DEFAULT_SPEC:
        assert f"sc-{key}" in rendered
    assert "Generate" not in rendered and "sc-back" in rendered and "sc-reset" in rendered


def test_a_scenario_url_spec_round_trips_through_the_route(client):
    got = client.get("/api/scenario?sites=preservation&borough=Queens").get_json()
    assert got["spec"]["sites"] == "preservation" and got["spec"]["borough"] == "Queens"

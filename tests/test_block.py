"""Your block: search, the site and ZIP records, the ranked list and its CSV. Hostile input never raises."""
from __future__ import annotations

import csv
import dataclasses
import io
import json

import numpy as np
import pytest

from app.analysis import block_data
from app.core.data import load


@pytest.fixture(scope="module")
def store():
    return load()


@pytest.fixture(scope="module")
def client():
    from app.app import server
    return server.test_client()


HOSTILE = [None, 7, [], {}, "", "   ", "\x00\x01", "<script>alert(1)</script>", "(((", "[a-", "*", "\\", ".*", "%", "9" * 5000,
           "😀", "'; DROP TABLE sites;--", "../../etc/passwd"]


def test_search_finds_a_zip_by_prefix(store):
    results = block_data.search(store, "1002")["results"]
    assert results and results[0]["kind"] == "zip" and results[0]["id"].startswith("1002")


def test_search_finds_a_borough_and_a_project_by_every_word(store):
    assert any(item["kind"] == "borough" and item["id"] == "Queens" for item in block_data.search(store, "que")["results"])
    answer = block_data.search(store, "townsend 1670")
    assert any(item["kind"] == "site" and item["label"] == "1670 Townsend Ave" for item in answer["results"])
    assert answer["n_sites"] >= 1


def test_search_is_case_insensitive_and_capped(store):
    upper, lower = block_data.search(store, "TOWNSEND"), block_data.search(store, "townsend")
    assert upper["results"] == lower["results"] and upper["n_sites"] == lower["n_sites"]
    wide = block_data.search(store, "a")
    assert sum(item["kind"] == "site" for item in wide["results"]) == block_data.MAX_SITE_RESULTS
    assert wide["n_sites"] > block_data.MAX_SITE_RESULTS


def test_search_with_no_match_returns_an_empty_list(store):
    assert block_data.search(store, "zzzzqqqq")["results"] == []


@pytest.mark.parametrize("query", HOSTILE, ids=range(len(HOSTILE)))
def test_search_never_raises_and_caps_its_input(store, query):
    answer = block_data.search(store, query)
    assert len(answer["query"]) <= block_data.MAX_QUERY
    assert json.dumps(answer)


def test_site_record_holds_the_record_in_context(store):
    row = store.sites[store.sites["baseline_crashes"].notna()].iloc[100]
    record = block_data.site_record(store, str(row["site_id"]))
    assert record["project"] == row["project_name"] and record["zip"] == str(row["zip"])
    assert record["percentile"] == pytest.approx(row["borough_percentile"])
    assert record["baseline_crashes"] == int(row["baseline_crashes"])
    borough = store.sites[(store.sites["borough"] == row["borough"]) & store.sites["baseline_crashes"].notna()]
    assert record["borough_median"] == pytest.approx(borough["baseline_crashes"].median())
    assert sum(record["strip"]["shares"]) == pytest.approx(100)
    assert record["strip"]["n_sites"] == len(borough)
    assert json.dumps(record, allow_nan=False)


def test_a_site_without_a_baseline_says_so(store):
    row = store.sites[store.sites["baseline_crashes"].isna()].iloc[0]
    record = block_data.site_record(store, int(row["site_id"]))
    assert not record["has_baseline"] and record["percentile"] is None and record["baseline_crashes"] is None
    assert json.dumps(record, allow_nan=False)


def test_a_site_without_a_completion_year_stays_valid(store):
    row = store.sites[store.sites["completion_year"].isna()].iloc[0]
    assert block_data.site_record(store, int(row["site_id"]))["completion_year"] is None


def test_a_tested_site_has_its_before_and_after_counts(store):
    row = store.event_sites[store.event_sites["treated"]].iloc[0]
    event = block_data.site_record(store, int(row["site_id"]))["event"]
    assert event["role"] == "tested" and event["cohorts"] == [int(row["cohort"])]
    assert event["before"] == sum(int(row[f"injury_{year:+d}"]) for year in (-3, -2, -1))
    assert event["after"] == sum(int(row[f"injury_{year:+d}"]) for year in (1, 2, 3))
    assert len(event["years"]) == 7
    assert {item["year"]: item["count"] for item in event["years"]}[int(row["cohort"]) + 1] == int(row["injury_+1"])


def test_a_comparison_site_joins_its_cohorts_into_calendar_years(store):
    events = store.event_sites
    many = events[~events["treated"]].groupby("site_id").size()
    site_id = int(many[many > 1].index[0])
    event = block_data.site_record(store, site_id)["event"]
    assert event["role"] == "comparison" and len(event["cohorts"]) > 1
    years = [item["year"] for item in event["years"]]
    assert years == sorted(set(years))
    for row in events[events["site_id"] == site_id].itertuples():
        table = events.loc[row.Index]
        assert {item["year"]: item["count"] for item in event["years"]}[int(row.cohort)] == int(table["injury_+0"])


def test_a_site_outside_the_comparison_has_no_event(store):
    outside = sorted(set(store.sites["site_id"]) - set(store.event_sites["site_id"]))[0]
    assert block_data.site_record(store, int(outside))["event"] is None


def test_nearby_sites_are_in_the_same_cluster_and_within_the_buffer(store):
    site_id = int(store.sites[store.sites["cluster_id"] == store.sites["cluster_id"].value_counts().index[0]].iloc[0]["site_id"])
    record = block_data.site_record(store, site_id)
    me = store.sites.set_index("site_id").loc[site_id]
    assert record["nearby"] and record["nearby_total"] >= len(record["nearby"])
    assert len(record["nearby"]) <= block_data.NEARBY_SHOWN
    assert [item["distance_m"] for item in record["nearby"]] == sorted(item["distance_m"] for item in record["nearby"])
    for item in record["nearby"]:
        other = store.sites.set_index("site_id").loc[item["site_id"]]
        assert other["cluster_id"] == me["cluster_id"] and item["site_id"] != site_id and item["distance_m"] <= 250


@pytest.mark.parametrize("value", [None, -1, "-1", "abc", "1.5", "99999999", "", " 1", "1;2", "٣", [], {}, True, 10_000_000])
def test_a_bad_site_id_is_not_found(store, value):
    assert block_data.site_record(store, value) is None


def test_zip_record_has_years_percentiles_and_the_recovered_zip_caveat(store):
    record = block_data.zip_record(store, "10029")
    panel = store.zip_year[store.zip_year["zip"].astype(str) == "10029"]
    assert [item["year"] for item in record["years"]] == sorted(panel["year"].tolist())
    assert record["total_injury"] == int(panel["injury_crashes"].sum())
    assert record["total_units"] == int(panel["units_completed"].sum())
    totals = store.zip_year.groupby("zip", observed=True)["injury_crashes"].sum()
    totals.index = totals.index.astype(str)
    assert record["injury_percentile"] == pytest.approx(100 * (totals.drop("10029") < totals["10029"]).mean())
    assert record["city_imputed_share"] == store.results["limits"]["imputed_zip_share"]
    assert record["imputed_injury"] == int(panel["injury_crashes_zip_imputed"].sum())
    assert record["n_sites"] == int((store.sites["zip"].astype(str) == "10029").sum())
    assert json.dumps(record, allow_nan=False)


def test_a_zip_with_sites_outside_the_panel_is_honest(store):
    record = block_data.zip_record(store, "10044")
    assert record and not record["in_panel"] and record["n_sites"] > 0 and "years" not in record


@pytest.mark.parametrize("value", [None, 10029, "1002", "100299", "abcde", "", "00000", "10029'", "1002\n", []])
def test_a_bad_zip_is_not_found(store, value):
    assert block_data.zip_record(store, value) is None


def test_ranked_defaults_to_the_most_crash_heavy_streets(store):
    page = block_data.ranked(store)
    with_baseline = store.sites[store.sites["baseline_crashes"].notna()]
    assert page["total"] == len(with_baseline) and len(page["rows"]) == block_data.PAGE_SIZE and page["has_more"]
    values = [row["baseline_crashes"] for row in page["rows"]]
    assert values == sorted(values, reverse=True) and values[0] == with_baseline["baseline_crashes"].max()
    assert page["rows"][0]["rank"] == 1 and page["baseline_years"] == store.meta["constants"]["baseline_years"]


def test_ranked_filters_sort_and_pages(store):
    page = block_data.ranked(store, "Queens", "Preservation", "units", "asc")
    expected = store.sites[store.sites["baseline_crashes"].notna() & (store.sites["borough"] == "Queens")
                           & (store.sites["construction_type"] == "Preservation")]
    assert page["total"] == len(expected)
    units = [row["units"] for row in page["rows"]]
    assert units == sorted(units) and {row["borough"] for row in page["rows"]} == {"Queens"}
    seen, offset = [], 0
    while True:
        chunk = block_data.ranked(store, "Staten Island", offset=offset, limit=25)
        seen += [row["site_id"] for row in chunk["rows"]]
        offset += 25
        if not chunk["has_more"]:
            break
    assert len(seen) == len(set(seen)) == chunk["total"]


def test_the_order_is_the_same_on_every_call(store):
    assert block_data.ranked(store)["rows"] == block_data.ranked(store)["rows"]


@pytest.mark.parametrize("value", HOSTILE, ids=range(len(HOSTILE)))
def test_ranked_ignores_hostile_values(store, value):
    page = block_data.ranked(store, value, value, value, value, value, value)
    assert (page["borough"], page["type"], page["sort"], page["dir"]) == ("all", "all", "baseline", "desc") or value == "9" * 5000
    assert page["rows"] or page["offset"] > 0


def test_ranked_bounds_its_page(store):
    assert len(block_data.ranked(store, limit="100000")["rows"]) == block_data.MAX_PAGE_SIZE
    assert block_data.ranked(store, offset="999999999")["rows"] == []
    assert block_data.ranked(store, offset="-5")["offset"] == 0
    assert block_data.ranked(store, limit=0)["limit"] == 1


def _rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def test_csv_holds_every_row_of_the_filter_in_order(store):
    rows = _rows(block_data.ranked_csv(store, "Bronx", "New Construction", "percentile", "desc"))
    page = block_data.ranked(store, "Bronx", "New Construction", "percentile", "desc", limit=100)
    assert len(rows) == page["total"] and rows[0]["site_id"] == str(page["rows"][0]["site_id"])
    assert {row["borough"] for row in rows} == {"Bronx"} and {row["construction_type"] for row in rows} == {"New Construction"}
    numbers = [float(row["percentile_in_borough"]) for row in rows]
    assert numbers == sorted(numbers, reverse=True)
    assert set(rows[0]) == set(block_data.CSV_COLUMNS.values())


def test_csv_cannot_carry_a_formula_into_a_spreadsheet(store):
    sites = store.sites.copy()
    picked = sites["baseline_crashes"].notna().idxmax()
    sites.loc[picked, "project_name"] = '=HYPERLINK("http://bad","x"),\n@cmd'
    changed = dataclasses.replace(store, sites=sites)
    rows = _rows(block_data.ranked_csv(changed))
    target = next(row for row in rows if row["site_id"] == str(sites.loc[picked, "site_id"]))
    assert target["project"].startswith("'=")
    for row in rows:
        assert not row["project"].startswith(("=", "+", "-", "@"))


def test_csv_and_json_routes_answer(client):
    response = client.get("/block/ranked.csv?borough=Queens&sort=units&dir=asc")
    assert response.status_code == 200 and response.mimetype == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]
    assert _rows(response.get_data(as_text=True))[0]["borough"] == "Queens"
    assert client.get("/api/block/search?q=1002").get_json()["results"]
    assert client.get("/api/block/ranked").get_json()["total"] > 25
    assert client.get("/api/block/zip?zip=10029").get_json()["kind"] == "zip"
    assert client.get("/api/block/site?id=100").get_json()["kind"] == "site"


@pytest.mark.parametrize("path", ["/api/block/site?id=abc", "/api/block/site", "/api/block/site?id=999999",
                                  "/api/block/zip?zip=abc", "/api/block/zip"])
def test_unknown_records_are_a_clean_404(client, path):
    response = client.get(path)
    assert response.status_code == 404 and response.get_json() == {"error": "not_found"}


@pytest.mark.parametrize("query", ["q=%00", "q=%3Cscript%3E", "q=" + "a" * 5000, "q=((("])
def test_the_search_route_survives_hostile_queries(client, query):
    assert client.get(f"/api/block/search?{query}").status_code == 200


def test_the_page_has_the_ranked_list_and_states_what_cannot_be_looked_up(store):
    from app.ui.sections import block
    rendered = str(block.layout(store))
    assert "id='bk-ranked'" in rendered
    assert "bk-record" in rendered and "bk-search" in rendered
    assert f"{store.meta['rows']['housing_confidential']:,}" in rendered
    assert "2025" in block.as_of_text(store) and "2026" in block.as_of_text(store)


def test_the_baseline_is_never_blamed_on_the_building(store):
    from app.ui.sections import block
    assert "not blame on the buildings" in str(block.layout(store))


def test_counts_stay_plain_integers_after_uint8_reads(store):
    events = store.event_sites
    assert events["injury_-3"].dtype == np.uint8
    event = block_data.site_record(store, int(events.iloc[0]["site_id"]))["event"]
    assert type(event["before"]) is int and type(event["after"]) is int
    assert all(type(item["count"]) is int for item in event["years"])

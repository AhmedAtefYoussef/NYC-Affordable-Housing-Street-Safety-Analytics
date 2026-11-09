"""Findings and Method chapters keep every fact and credit, and are built from the stored results."""
from __future__ import annotations

import copy
import dataclasses
import re
from pathlib import Path

import pytest

from app.analysis.story_text import number_word
from app.core.data import load
from app.ui import story
from app.ui.sections import findings, method

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "app" / "assets"


@pytest.fixture(scope="module")
def store():
    return load()


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    for child in children if isinstance(children, (list, tuple)) else [children]:
        if child is not None and not isinstance(child, (str, int, float)):
            yield from _walk(child)


def _text(component) -> str:
    if component is None:
        return ""
    if isinstance(component, (str, int, float)):
        return str(component)
    if isinstance(component, (list, tuple)):
        return " ".join(_text(child) for child in component)
    return _text(getattr(component, "children", None))


def _by_class(tree, name: str) -> list:
    return [node for node in _walk(tree) if name in (getattr(node, "className", None) or "").split()]


def _prop(node, name: str, default=None):
    return getattr(node, name, default)


# ---------------------------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------------------------
def test_findings_is_a_midnight_chapter_with_a_kinetic_heading_and_scrubbed_lead(store):
    tree = findings.layout(store)
    assert tree.id == "findings" and _prop(tree, "data-tint") == "midnight"
    heading = [node for node in _walk(tree) if type(node).__name__ == "H2"][0]
    assert _prop(heading, "data-kinetic") == "words"
    lead = _by_class(tree, "chapter-lead")[0]
    assert _prop(lead, "data-scrub") == "words"
    questions = store.results["questions"]
    excluding = [key for key, item in questions.items() if item["excludes_zero"]]
    assert f"{len(questions) - len(excluding)} of the {len(questions)} intervals include zero" in _text(lead)
    for key in excluding:
        assert key in _text(lead)


def test_all_ten_questions_are_rows_with_their_owner_credited(store):
    rows = _by_class(findings.layout(store), "fd-row")
    questions = store.results["questions"]
    assert [row.id for row in rows] == [f"fd-{key.lower()}" for key in questions]
    for row, (key, item) in zip(rows, questions.items()):
        text = _text(row)
        assert f"Asked by team member {item['owner']}" in text
        assert item["question"] in text
        assert item["sentence"].split("; the interval includes zero")[0] in text
        assert _prop(row, "data-owner") == item["owner"]
    assert {_prop(row, "data-owner") for row in rows} == {item["owner"] for item in questions.values()}


def test_each_row_is_a_real_disclosure(store):
    tree = findings.layout(store)
    toggles = [node for node in _walk(tree) if "fd-toggle" in (_prop(node, "className") or "")]
    bodies = {node.id: node for node in _walk(tree) if "fd-inner" in (_prop(node, "className") or "")}
    assert len(toggles) == 10
    for toggle in toggles:
        assert type(toggle).__name__ == "Button" and toggle.type == "button"
        assert _prop(toggle, "aria-expanded") == "false"
        body = bodies[_prop(toggle, "aria-controls")]
        assert _prop(body, "aria-labelledby") == toggle.id and _prop(body, "role") == "region"


def test_each_estimate_counts_up_and_ends_on_its_printed_value(store):
    rows = _by_class(findings.layout(store), "fd-row")
    for row, item in zip(rows, store.results["questions"].values()):
        estimate = _by_class(row, "fd-estimate")[0]
        assert float(_prop(estimate, "data-countup")) == pytest.approx(item["estimate"])
        assert _prop(estimate, "data-final") == _text(estimate)


def test_each_expanded_row_links_to_explore_and_lab_and_the_row_itself(store):
    for row in _by_class(findings.layout(store), "fd-row"):
        hrefs = [_prop(node, "href") for node in _walk(row) if _prop(node, "href")]
        assert "#explore" in hrefs and "#lab" in hrefs and f"#{_prop(row, 'data-rq')}" in hrefs


def test_levels_are_printed_exactly_in_the_rows(store):
    text = _text(findings.layout(store))
    assert "98.75% interval" in text and "99.44% interval" in text and "99% interval" not in text


def test_the_robustness_note_names_the_chart_and_the_zip_check(store):
    rows = {row.id: _text(row) for row in _by_class(findings.layout(store), "fd-row")}
    assert "one-change versions of this result are charted below" in rows["fd-rq3"]
    zip_level = [key for key, item in store.results["questions"].items() if item["excludes_zero_reported"] is not None]
    assert zip_level
    for key in zip_level:
        assert "Counting only crashes with a reported ZIP code" in rows[f"fd-{key.lower()}"]


def test_filters_cover_reading_level_and_every_team_member(store):
    tree = findings.layout(store)
    chips = [(_prop(node, "data-group"), _prop(node, "data-value"), _text(node))
             for node in _walk(tree) if "fd-chip" in (_prop(node, "className") or "")]
    shows = {value: label for group, value, label in chips if group == "show"}
    assert shows == {"all": "All", "clear": "Clear of zero", "zero": "Cannot be told from zero",
                     "zip": "ZIP level", "site": "Site level"}
    owners = {value for group, value, _ in chips if group == "owner"}
    assert owners == {"all", *(item["owner"] for item in store.results["questions"].values())}


def test_rows_carry_the_data_the_filters_use(store):
    rows = _by_class(findings.layout(store), "fd-row")
    for row, (key, item) in zip(rows, store.results["questions"].items()):
        assert _prop(row, "data-reading") == ("clear" if item["excludes_zero"] else "zero")
        assert _prop(row, "data-scope") == ("zip" if item["n_unit"] == "ZIP codes" else "site")
        assert _prop(row, "data-rq") == key.lower()


def test_the_robustness_chart_has_the_comparison_subset_and_cluster_rows(store):
    tree = findings.layout(store)
    graphs = [node for node in _walk(tree) if getattr(node, "id", None) == "fd-robustness"]
    assert len(graphs) == 1
    variants = " ".join(str(label) for trace in graphs[0].figure.data for label in trace.y)
    assert "comparison" in variants.lower() and "cluster" in variants.lower()
    assert "How the main result changes with our choices" in _text(tree)
    assert "What surprised us" in _text(tree)


def test_findings_follow_the_stored_results(store):
    results = copy.deepcopy(store.results)
    for key in ("RQ3", "RQ4", "RQ5"):
        results["questions"][key]["excludes_zero"] = True
    changed = dataclasses.replace(store, results=results)
    rows = {row.id: row for row in _by_class(findings.layout(changed), "fd-row")}
    assert _prop(rows["fd-rq4"], "data-reading") == "clear"


def test_findings_text_has_no_cause_words_or_dashes(store):
    text = _text(findings.layout(store))
    for banned in ["—", "causes", "caused by", "leads to", "because of the housing"]:
        assert banned not in text, banned


def test_hero_and_older_sections_still_render(store):
    assert "Do injury crashes rise" in _text(story.hero(store))
    for part in [story.findings, story.limits, story.impact, story.data_and_method, story.footer]:
        assert _text(part(store))


# ---------------------------------------------------------------------------------------------
# Method
# ---------------------------------------------------------------------------------------------
def test_method_is_an_ember_chapter_with_all_its_movements(store):
    tree = method.layout(store)
    assert tree.id == "method" and _prop(tree, "data-tint") == "ember"
    parts = [node.id for node in _by_class(tree, "md-part")]
    assert parts == ["md-limits", "md-city", "md-joined", "md-cleaning", "md-credits"]
    for node in _by_class(tree, "md-title"):
        assert _prop(node, "data-kinetic") == "words"


def test_pipeline_counts_are_the_stored_stage_rows(store):
    tree = method.layout(store)
    counts = [_prop(node, "data-final") for node in _by_class(tree, "md-count")]
    assert counts == [f"{row['rows']:,}" for row in store.results["stages"]]
    assert all(_prop(node, "data-countup") for node in _by_class(tree, "md-count"))
    titles = [_text(node.children[1]) for node in _by_class(tree, "md-stage")]
    assert titles == ["Raw", "Cleaned", "Integrated"]


def test_every_limit_and_every_cleaning_rule_is_on_the_page(store):
    tree = method.layout(store)
    assert len(_by_class(tree, "md-limit")) == len(story.limit_items(store))
    body = [node for node in _walk(tree) if getattr(node, "id", None) == "md-clean-body"][0]
    assert len(body.children) == len(store.cleaning_log) == 49
    assert any(getattr(node, "id", None) == "md-clean-filter" for node in _walk(tree))


def test_readers_cover_resident_planner_journalist_researcher_and_keep_the_impact_text(store):
    tree = method.layout(store)
    assert [_text(node.children[0]) for node in _by_class(tree, "md-reader")] == [
        "Resident", "Planner", "Journalist", "Researcher"]
    text = _text(tree)
    for _, what in story.impact_items(store):
        assert what in text
    hrefs = {_prop(node, "href") for node in _walk(tree) if _prop(node, "href")}
    assert {"#block", "#explore", "#lab", "#findings", "#rq7"} <= hrefs


def test_credits_links_and_as_of_date(store):
    tree = method.layout(store)
    hrefs = [_prop(node, "href") for node in _walk(tree) if _prop(node, "href")]
    assert f"{method.REPO}/blob/main/docs/NUMBER_CHANGES.md" in hrefs
    assert f"{method.REPO}/blob/main/docs/AI_USE.md" in hrefs
    assert method.REPO in hrefs
    for dataset in store.meta["datasets"].values():
        assert dataset["url"] in hrefs
    text = _text(tree)
    for credit in ["NYC Open Data", "CARTO", "OpenStreetMap"]:
        assert credit in text
    owners = {item["owner"] for item in store.results["questions"].values()}
    team = _text(_by_class(tree, "md-team"))
    assert all(owner in team for owner in owners)
    as_of = store.meta["data_as_of"]
    assert f"run to {as_of['latest_crash']}" in text
    assert not any(day in text.replace(as_of["latest_crash"], "") for day in set(as_of["raw_files_saved"].values())
                   if day != as_of["latest_crash"])


def test_the_repository_link_names_the_project():
    assert method.REPO.endswith("AhmedAtefYoussef/Data-Engineering-Visualization-Project")


def test_method_numbers_follow_the_store(store):
    meta = copy.deepcopy(store.meta)
    meta["rows"].update(housing=9001, crashes=2_600_000)
    changed = dataclasses.replace(store, meta=meta)
    text = _text(method.layout(changed))
    assert "9,001 buildings" in text and "2,600,000 crashes" in text


def test_method_text_has_no_dashes_or_cause_words(store):
    text = _text(method.layout(store))
    for banned in ["—", "causes", "caused by", "leads to"]:
        assert banned not in text, banned


def test_number_words_are_used_for_counts(store):
    assert number_word(len(store.results["questions"])) == "ten"


# ---------------------------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------------------------
def test_stylesheet_uses_tokens_and_grid_rows_for_the_disclosure():
    css = (ASSETS / "css" / "60-findings.css").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "raw hex in 60-findings.css"
    assert "grid-template-rows" in css and "max-height: 0" not in css
    assert "monospace" not in css


def test_script_handles_the_deep_link_the_filters_and_the_log_filter():
    js = (ASSETS / "js" / "50-findings.js").read_text(encoding="utf-8")
    assert "rq\\d+" in js and "hashchange" in js and "aria-expanded" in js and "md-clean-filter" in js
    assert "reducedMotion" in js

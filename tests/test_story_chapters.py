"""The opening's story chapters: one arrangement of the canvas per chapter, and every figure read from the store."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.analysis import story_data
from app.analysis.story_text import signed
from app.core.data import load
from app.core.stats import NEUTRAL_PERCENTILE
from app.ui.sections import overview

ASSETS = Path(__file__).resolve().parents[1] / "app" / "assets"


@pytest.fixture(scope="module")
def store():
    return load()


def _walk(node):
    yield node
    children = getattr(node, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    elif children is not None and not isinstance(children, (str, int, float)):
        yield from _walk(children)


def _prop(node, name):
    return getattr(node, name.replace("-", "_"), None) or (getattr(node, "_prop_names", None) and node.to_plotly_json()["props"].get(name))


def _text(node) -> str:
    children = getattr(node, "children", node)
    if isinstance(children, (list, tuple)):
        return "".join(_text(child) for child in children if child is not None)
    if isinstance(children, (str, int, float)):
        return str(children)
    return "" if children is None or children is node else _text(children)


def _steps(store):
    return [node for node in _walk(overview.layout(store)) if "story-step" in str(getattr(node, "className", "") or "").split()]


def test_the_steps_name_their_arrangements_in_order(store):
    layouts = [_prop(step, "data-layout") for step in _steps(store)]
    assert layouts == ["city", "boroughs", "percentile", "funnel", "outcomes", "city"]
    ids = [step.id for step in _steps(store)[1:]]
    assert ids == [f"chapter-{number}" for number in range(1, 6)]


def test_every_arrangement_a_chapter_names_is_defined_in_the_scripts(store):
    scripts = (ASSETS / "js" / "20-stage.js").read_text(encoding="utf-8") + (ASSETS / "js" / "25-story.js").read_text(encoding="utf-8")
    for name in {_prop(step, "data-layout") for step in _steps(store)}:
        assert re.search(rf"Stage\.layouts\.{name}\s*=", scripts), name


def test_the_progress_rail_has_one_mark_per_step(store):
    rails = [node for node in _walk(overview.layout(store)) if getattr(node, "className", None) == "story-progress"]
    assert len(rails) == 1 and len(rails[0].children) == len(_steps(store))


def test_the_chapter_figures_are_the_stored_values(store):
    figures = [_prop(node, "data-final") for node in _walk(overview.layout(store))
               if "fig" in str(getattr(node, "className", "") or "").split()]
    counts = store.sites["borough"].astype(str).value_counts()
    located, completed, clean, compared = story_data.funnel_counts(store)
    where, after = store.results["questions"]["RQ7"], store.results["questions"]["RQ3"]
    assert figures == [
        f"{counts.iloc[0]:,}", f"{counts.iloc[1]:,}", f"{counts.iloc[-1]:,}",
        f"{where['n']:,}", f"{NEUTRAL_PERCENTILE + where['estimate']:.0f}th",
        f"{located:,}", f"{completed:,}", f"{clean:,}", f"{compared:,}",
        f"{story_data.rq3_outcomes(store)['below_zero']}", signed(after["estimate"]) + "%",
    ]


def test_each_figure_counts_to_its_own_value(store):
    for node in _walk(overview.layout(store)):
        if "fig" in str(getattr(node, "className", "") or "").split():
            final = _prop(node, "data-final")
            number = float(final.replace(",", "").replace("−", "-").rstrip("%").removesuffix("th"))
            assert float(_prop(node, "data-countup")) == pytest.approx(number)
            assert _text(node) == final


def test_the_bronx_takes_its_article():
    assert overview._place("Bronx") == "the Bronx"
    assert overview._place("Bronx", start=True) == "The Bronx"
    assert overview._place("Queens", start=True) == "Queens"


def test_chapter_copy_has_no_banned_marks(store):
    text = " ".join(_text(step) for step in _steps(store))
    assert "—" not in text
    assert not re.search(r"\bcaused?\b|\bleads? to\b", text)


def test_no_style_sheet_keeps_the_old_yellow():
    for path in (ASSETS / "css").glob("*.css"):
        source = path.read_text(encoding="utf-8")
        assert "244 185 66" not in source and "f4b942" not in source.lower(), path.name

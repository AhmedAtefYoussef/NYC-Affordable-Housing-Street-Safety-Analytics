"""Your block and Try to break the result are workbenches: the choices and the answer sit side by side, and the answer
panel holds every element the scripts fill, so a click is always seen landing."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.data import load
from app.ui.sections import block, lab

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


def _classes(node) -> list[str]:
    return str(getattr(node, "className", "") or "").split()


def _find(tree, class_name):
    return [node for node in _walk(tree) if class_name in _classes(node)]


def _ids(tree) -> set[str]:
    return {node.id for node in _walk(tree) if isinstance(getattr(node, "id", None), str)}


def test_block_is_a_list_pane_beside_a_record_pane(store):
    tree = block.layout(store)
    bench = _find(tree, "bk-workbench")
    assert len(bench) == 1
    panes = [child for child in bench[0].children if "bk-pane" in _classes(child)]
    assert [("bk-pane-list" in _classes(p), "bk-pane-record" in _classes(p)) for p in panes] == [(True, False), (False, True)]
    assert {"bk-search", "bk-ranked"} <= _ids(panes[0]) and _ids(panes[1]) == {"bk-record"}


def test_lab_answer_panel_holds_everything_the_script_fills(store):
    tree = lab.layout(store)
    result = _find(tree, "sc-pane-result")
    assert len(result) == 1
    assert {"sc-value", "sc-tag", "sc-range", "sc-axis", "sc-sentence", "sc-empty", "sc-count", "sc-count-note", "sc-history"} <= _ids(result[0])
    controls = _find(tree, "sc-pane-controls")[0]
    assert {"sc-sites", "sc-borough", "sc-size", "sc-group", "sc-cluster", "sc-cohort", "sc-back", "sc-reset", "sc-copy"} <= _ids(controls)
    assert "sc-float" in _ids(tree) and "sc-status" in _ids(tree)


def test_every_id_the_tools_script_reads_is_on_the_page(store):
    script = (ASSETS / "js" / "45-tools.js").read_text(encoding="utf-8")
    ids = _ids(block.layout(store)) | _ids(lab.layout(store))
    import re
    wanted = set(re.findall(r'getElementById\("((?:bk|sc)-[a-z-]+)"\)', script))
    assert wanted and wanted <= ids, wanted - ids


def test_no_rounded_label_lights_its_outline_on_hover():
    css = "".join(path.read_text(encoding="utf-8") for path in (ASSETS / "css").glob("*.css"))
    assert "@keyframes trace" not in css
    assert ".example:hover {" not in css and "data-wave" not in css


def test_the_generate_overlay_animates_no_full_screen_mask():
    css = (ASSETS / "css" / "35-generate.css").read_text(encoding="utf-8")
    assert "--hole" not in css and "backdrop-filter" not in css


def test_the_tools_open_no_native_menus():
    """Every choice is drawn in the page's own style: no <select>, whose list the operating system draws."""
    tools = (ASSETS / "js" / "45-tools.js").read_text(encoding="utf-8")
    assert 'el("select"' not in tools and "createElement(\"select\")" not in tools
    for control in ('NYC.picker({ id: "bk-borough"', 'NYC.picker({ id: "bk-sort"', 'NYC.segmented({ id: "bk-type"', 'NYC.segmented({ id: "bk-dir"'):
        assert control in tools, control


def test_the_picker_is_a_complete_listbox():
    controls = (ASSETS / "js" / "15-controls.js").read_text(encoding="utf-8")
    for needle in ['"aria-haspopup", "listbox"', '"aria-expanded"', '"role", "listbox"', '"role", "option"', '"aria-selected"',
                   '"aria-activedescendant"', '"ArrowDown"', '"ArrowUp"', '"Home"', '"End"', '"Escape"', '"Tab"']:
        assert needle in controls, needle


def test_every_lab_group_has_a_balanced_grid():
    css = (ASSETS / "css" / "50-tools.css").read_text(encoding="utf-8")
    for key in ("sites", "borough", "size", "group", "cluster", "cohort"):
        assert f"#sc-{key}" in css, key

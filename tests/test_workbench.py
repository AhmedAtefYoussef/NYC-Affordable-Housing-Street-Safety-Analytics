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


def test_both_light_renderers_carry_the_light_kit_into_their_worker():
    kit = (ASSETS / "js" / "05-light.js").read_text(encoding="utf-8")
    assert "function lightKit(scope)" in kit and "NYC.lightKit = lightKit" in kit
    for name, renderer in (("20-stage.js", "stageRenderer"), ("40-generate.js", "reportRenderer")):
        script = (ASSETS / "js" / name).read_text(encoding="utf-8")
        assert f'"(" + NYC.lightKit + ")(self);(" + {renderer} + ")(self);"' in script, name
        assert "NYC.lightKit(local)" in script, name     # the on-page fallback gets the same kit


def test_both_renderers_draw_their_lights_on_the_graphics_processor_with_a_2d_fallback():
    """Every light in one WebGL2 call, motion blur computed per pixel; the 2D canvas still draws where WebGL2 is missing."""
    kit = (ASSETS / "js" / "05-light.js").read_text(encoding="utf-8")
    assert 'getContext("webgl2"' in kit and "drawArraysInstanced" in kit and "webglcontextlost" in kit
    assert "if (!gl) { return null; }" in kit
    stage = (ASSETS / "js" / "20-stage.js").read_text(encoding="utf-8")
    report = (ASSETS / "js" / "40-generate.js").read_text(encoding="utf-8")
    assert "Light.Particles(canvas" in stage and "Light.drawLight(context" in stage
    assert "Light.Particles(message.particles" in report and "Light.drawLight(context" in report
    # Both canvases are handed to the worker together.
    assert "[target, overlayTarget]" in stage and "[target, lightsTarget]" in report


def test_the_generate_sequence_keeps_its_exits():
    script = (ASSETS / "js" / "40-generate.js").read_text(encoding="utf-8")
    assert "NYC.reducedMotion()" in script and '"Escape"' in script and "MAX_WAIT_MS" in script


def test_the_light_version_keeps_blur_filters_off():
    css = (ASSETS / "css" / "70-motion.css").read_text(encoding="utf-8")
    assert ".is-lite :is(" in css and "filter: none !important" in css



def test_the_report_hand_off_moves_only_opacity_and_transform():
    """The report comes into focus on one composited layer: a blur over the whole report re-layers the page every frame."""
    import re
    css = (ASSETS / "css" / "35-generate.css").read_text(encoding="utf-8")
    pull = re.search(r"@keyframes pull-back \{(.*?)\}\s*\}", css, re.S)
    assert pull and "filter" not in pull.group(1)
    assert 'body[data-report="fresh"] .card' not in css


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

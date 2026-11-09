"""The package layers stay in order: app.core <- app.analysis <- app.ui <- app.app.

A module may import from its own layer and the layers before it, never from a later one, and nothing
imports the entry point. The core and analysis layers stay free of Dash and Plotly, so the domain code can
be reused by the pipeline, a notebook or another front end. The pipeline never imports the website's UI.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ORDER = ["core", "analysis", "ui", "app"]          # app = the entry point app/app.py
WEB_FRAMEWORKS = {"dash", "plotly", "flask"}


def _layer(path: Path) -> str:
    parts = path.relative_to(ROOT / "app").parts
    return "app" if parts == ("app.py",) else parts[0]


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
            if node.module == "app":                    # from app import core, ui, ...
                names += [f"app.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
    return names


APP_MODULES = sorted(path for path in (ROOT / "app").rglob("*.py") if path.name != "__init__.py" or
                     path.parent != ROOT / "app")


def test_every_module_sits_in_a_known_layer():
    assert {_layer(path) for path in APP_MODULES} <= set(ORDER)
    assert (ROOT / "app" / "app.py") in APP_MODULES


@pytest.mark.parametrize("path", APP_MODULES, ids=lambda path: path.relative_to(ROOT).as_posix())
def test_imports_point_only_to_earlier_layers(path):
    layer = _layer(path)
    for name in _imports(path):
        if not name.startswith("app."):
            continue
        target = name.split(".")[1]
        target_layer = "app" if target == "app" else target
        assert target_layer in ORDER, f"{name} is outside the layers {ORDER}"
        assert ORDER.index(target_layer) <= ORDER.index(layer), f"{layer} must not import {name}"
        assert not (target_layer == "app" and layer != "app"), f"nothing imports the entry point ({name})"


@pytest.mark.parametrize("path", [path for path in APP_MODULES if _layer(path) in {"core", "analysis"}],
                         ids=lambda path: path.relative_to(ROOT).as_posix())
def test_core_and_analysis_stay_free_of_web_frameworks(path):
    used = {name.split(".")[0] for name in _imports(path)} & WEB_FRAMEWORKS
    assert not used, f"{path.name} imports {sorted(used)}"


@pytest.mark.parametrize("path", sorted((ROOT / "pipeline").rglob("*.py")),
                         ids=lambda path: path.relative_to(ROOT).as_posix())
def test_pipeline_uses_only_the_core_of_the_website(path):
    for name in _imports(path):
        if name.startswith("app."):
            assert name.split(".")[1] == "core", f"{path.name} imports {name}; the pipeline may use app.core only"

"""Assemble the notebook from the section sources in pipeline/notebook/sections/ and optionally execute it.

Each section is a Python file in jupytext "percent" format (`# %%` code cells, `# %% [markdown]`
text cells). Sections are joined in file-name order into one self-contained notebook. A code cell
whose only line is `# INLINE: <repo path>` is replaced by that file's code, so the statistics in
app/core/stats.py exist once and the notebook still imports nothing from the repository. A cell whose only
line is `# INLINE-CONSTANTS: <repo path>` takes that file's BEGIN/END SHARED CONSTANTS block, which the
`# INLINE` paste then leaves out, so changing a value in the notebook's Section 1 reaches the statistics.

    python -m pipeline notebook --execute                       # full build into notebooks/
    python -m pipeline notebook --sections 01 02 04 --execute --out dev.ipynb --show 04
    python -m pipeline notebook --src some/dir --sections 01 02 --execute --out dev.ipynb
"""
from __future__ import annotations

import argparse
import base64
import re
import sys
import tempfile
import time
from pathlib import Path

import jupytext
import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

from pipeline.paths import NOTEBOOK_PATH as DEFAULT_OUT
from pipeline.paths import RAW_DIR as NOTEBOOK_DIR  # execution directory: the two data files live here
from pipeline.paths import ROOT
from pipeline.paths import SECTIONS_DIR as SRC_DIR

INLINE = re.compile(r"^# INLINE: (\S+)\s*$")
INLINE_CONSTANTS = re.compile(r"^# INLINE-CONSTANTS: (\S+)\s*$")
CONSTANTS_BLOCK = re.compile(r"^# BEGIN SHARED CONSTANTS[^\n]*\n(.*?)^# END SHARED CONSTANTS[^\n]*\n", re.M | re.S)
MAX_TEXT = 1800                            # characters of text output printed per cell with --show


def section_files(prefixes: list[str] | None, src: Path = SRC_DIR) -> list[Path]:
    """The section files in name order, optionally only those starting with one of `prefixes`."""
    files = sorted(src.glob("*.py"))
    if prefixes:
        files = [f for f in files if f.name.startswith(tuple(prefixes))]
    if not files:
        raise SystemExit(f"no section files matched {prefixes} in {src}")
    return files


def inline_source(source: str) -> str:
    """Replace an `# INLINE: path` cell by the code of that file (its docstring and imports kept)."""
    constants = INLINE_CONSTANTS.match(source.strip())
    if constants:
        block = CONSTANTS_BLOCK.search((ROOT / constants.group(1)).read_text(encoding="utf-8"))
        return f"# Defined once, in {constants.group(1)}; a value changed here reaches every later section.\n{block.group(1)}"
    match = INLINE.match(source.strip())
    if not match:
        return source
    code = (ROOT / match.group(1)).read_text(encoding="utf-8")
    code = code.replace("from __future__ import annotations\n", "")
    code = CONSTANTS_BLOCK.sub("", code)   # Section 1 holds them; a second copy would overwrite a changed value
    return f"# The same code as {match.group(1)}, which the website uses.\n{code.strip()}\n"


def read_cells(files: list[Path]) -> list[nbformat.NotebookNode]:
    """Parse every section, inline shared modules and give each cell a stable id."""
    cells = []
    for path in files:
        part = jupytext.reads(path.read_text(encoding="utf-8"), fmt="py:percent")
        for number, cell in enumerate(part.cells):
            if cell.cell_type == "code":
                cell.source = inline_source(cell.source)
            cell.metadata = {"section": path.stem}
            cell.id = f"{path.stem}-{number:03d}"   # stable ids keep git diffs small
            cells.append(cell)
    return cells


def build(files: list[Path]) -> nbformat.NotebookNode:
    notebook = nbformat.v4.new_notebook(cells=read_cells(files))
    notebook.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
    notebook.metadata["language_info"] = {"name": "python"}
    return notebook


def execute(notebook: nbformat.NotebookNode) -> bool:
    """Run all cells in notebooks/ (where the data files are). Return False if a cell raised."""
    client = NotebookClient(notebook, timeout=3600, kernel_name="python3",
                            resources={"metadata": {"path": str(NOTEBOOK_DIR)}})
    try:
        client.execute()
        return True
    except CellExecutionError as error:
        failed = next((c for c in notebook.cells if c.cell_type == "code" and any(
            o.get("output_type") == "error" for o in c.get("outputs", []))), None)
        if failed is not None:
            print(f"\n=== FAILED CELL ({failed.id}) ===\n{failed.source[:1500]}")
        print(f"\n=== ERROR ===\n{str(error)[-3500:]}")
        return False


def show_outputs(notebook: nbformat.NotebookNode, prefixes: list[str], image_dir: Path) -> None:
    """Print the text outputs of the chosen sections and save their figures as PNG files."""
    image_dir.mkdir(parents=True, exist_ok=True)
    for cell in notebook.cells:
        if cell.cell_type != "code" or not cell.metadata.get("section", "").startswith(tuple(prefixes)):
            continue
        print(f"\n--- {cell.id}: {cell.source.splitlines()[0][:90] if cell.source else ''}")
        for number, output in enumerate(cell.get("outputs", [])):
            data = output.get("data", {})
            if output.get("output_type") == "stream":
                print(output.text[:MAX_TEXT])
            elif "image/png" in data:
                target = image_dir / f"{cell.id}_{number}.png"
                target.write_bytes(base64.b64decode(data["image/png"]))
                print(f"[figure saved: {target}]")
            elif "text/markdown" in data or "text/plain" in data:
                print(data.get("text/markdown", data.get("text/plain"))[:MAX_TEXT])


def budget(notebook: nbformat.NotebookNode) -> None:
    """Print code and markdown line counts per section, to keep the notebook lean."""
    sections: dict[str, list[int]] = {}
    for cell in notebook.cells:
        row = sections.setdefault(cell.metadata["section"], [0, 0])
        row[cell.cell_type != "code"] += len(cell.source.splitlines())
    for name, (code, text) in sections.items():
        print(f"  {name:<24} code {code:5d}  markdown {text:5d}")


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m pipeline notebook", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", type=Path, default=SRC_DIR, help="folder with the section files")
    parser.add_argument("--sections", nargs="*", help="file-name prefixes to include (default: all)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output .ipynb path")
    parser.add_argument("--execute", action="store_true", help="run the notebook and store outputs")
    parser.add_argument("--show", nargs="*", default=[], help="print outputs of these section prefixes")
    args = parser.parse_args(argv)

    notebook = build(section_files(args.sections, args.src))
    ok = True
    if args.execute:
        started = time.time()
        ok = execute(notebook)
        print(f"executed in {time.time() - started:.0f}s: {'OK' if ok else 'FAILED'}")
    if args.show:
        show_outputs(notebook, args.show, Path(tempfile.gettempdir()) / f"{args.out.stem}_img")
    budget(notebook)
    for cell in notebook.cells:
        cell.metadata.pop("section", None)
    nbformat.validate(notebook)
    out = args.out if ok else args.out.with_suffix(".failed.ipynb")   # never overwrite with a broken run
    out.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, str(out))
    print(f"wrote {out} ({len(notebook.cells)} cells, {sum(c.cell_type == 'code' for c in notebook.cells)} code)")
    return 0 if ok else 1


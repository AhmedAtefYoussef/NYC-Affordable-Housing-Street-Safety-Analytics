"""Stage 1 of the data build: execute the notebook's section sources in one namespace."""
from __future__ import annotations

import os
import time
from pathlib import Path

from pipeline.notebook.assemble import read_cells, section_files
from pipeline.paths import RAW_DIR as NOTEBOOK_DIR

SKIPPED_SECTIONS = ("03_",)               # the EDA section defines nothing that later sections use


def run_notebook_sections() -> dict:
    """Execute the notebook's code cells in order and return the resulting namespace."""
    import IPython.display
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Outside a kernel `display` would print every table; the exports need the variables only.
    IPython.display.display = lambda *args, **kwargs: None
    plt.show = lambda *args, **kwargs: None

    namespace = {"__name__": "__notebook__"}
    started = time.time()
    previous_dir = Path.cwd()
    os.chdir(NOTEBOOK_DIR)                # the notebook reads its two data files from "."
    try:
        for path in section_files(None):
            if path.name.startswith(SKIPPED_SECTIONS):
                continue
            for cell in read_cells([path]):   # same parser as the notebook build, shared code inlined
                if cell.cell_type == "code":
                    exec(compile(cell.source, cell.id, "exec"), namespace)
                    plt.close("all")      # figures are not needed; closing them frees memory
            print(f"  ran {path.name:<26} {time.time() - started:5.0f}s", flush=True)
    finally:
        os.chdir(previous_dir)
    return namespace

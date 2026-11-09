"""Command line for the pipeline.

    python -m pipeline notebook [--execute] [--sections 01 02] [--out PATH] [--show 04] [--src DIR]
    python -m pipeline data [--out DIR] [--skip-check]

`notebook` assembles notebooks/NYC_Housing_Safety.ipynb from pipeline/notebook/sections/ (and runs it with
--execute). `data` runs the same sections and exports app/data/, the only files the website reads.
"""
from __future__ import annotations

import sys

COMMANDS = {
    "notebook": "assemble (and with --execute, run) the notebook from its section sources",
    "data": "run the notebook sections and export the website's data to app/data/",
}


def usage() -> str:
    lines = ["usage: python -m pipeline <command> [options]", "", "commands:"]
    lines += [f"  {name:<10} {text}" for name, text in COMMANDS.items()]
    lines += ["", "Run `python -m pipeline <command> --help` for the options of one command."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] in {"-h", "--help"}:
        print(usage())
        return 0
    command, rest = args[0], args[1:]
    if command == "notebook":
        from pipeline.notebook.assemble import main as run
    elif command == "data":
        from pipeline.build.export import main as run
    else:
        print(f"unknown command {command!r}\n\n{usage()}", file=sys.stderr)
        return 2
    return run(rest)


if __name__ == "__main__":
    sys.exit(main())

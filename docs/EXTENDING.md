# Extending the project

Each change below is a short path through the layers described in [ARCHITECTURE.md](ARCHITECTURE.md). The order matters: a change starts where the data is made and moves toward the reader, and every step has a test that fails if a later step is forgotten.

```
pipeline/notebook/sections  ->  pipeline/build  ->  app/data  ->  app/core  ->  app/analysis  ->  app/ui
     (the analysis)            (the export)        (contract)    (model)       (numbers, text)   (Dash)
```

Before and after every change:

```bash
ruff check app tests pipeline
python -m pytest -q tests
```

## Change the analysis

1. Edit the section file in `pipeline/notebook/sections/`. Keep data-derived numbers printed by code, never typed into markdown.
2. Try the section quickly: `python -m pipeline notebook --sections 01 02 04 05 --execute --out dev.ipynb --show 05`.
3. Rebuild both outputs: `python -m pipeline notebook --execute` and `python -m pipeline data`. The data build re-runs the website's statistics against the notebook and refuses to replace `app/data/` if they disagree.
4. If a published number moved, add an entry to [NUMBER_CHANGES.md](NUMBER_CHANGES.md) with its reason.

`tests/test_pipeline.py::test_sources_unchanged_since_the_last_build` fails until step 3 is done, because `meta.json` hashes the section sources.

## Add a research question

1. Compute it in the notebook (`08a_rq_1_5.py` or `08b_rq_6_10.py`) and store it the way the others are stored: an entry in `RESULTS` (question, estimate, interval, sentence) and a row in the summary table.
2. `pipeline/build/results.py` copies every `RESULTS` entry into `results.json`; add any extra detail the page needs to the `detail` block there.
3. The findings section (`app/ui/sections/findings.py`) and the story read `results.json`, with shared wording in `app/analysis/story_text.py`. Name the owner in the notebook so the page credits them.

## Add an exported table

1. Write the builder in `pipeline/build/tables.py` as a pure function from notebook objects to a frame. Use `smallest_unsigned` and `as_category` from `frames.py` so types stay narrow and category orders fixed, and `require()` from `checks.py` for every invariant (never `assert`).
2. Call it from `write_all` in `pipeline/build/export.py` with `write_table(...)`, and add its name to `OUTPUT_TABLES` in `checks.py`. The build refuses to finish if the two lists differ.
3. Declare its columns in `EXPECTED_SCHEMA` in `app/core/data.py` and load it into `Store`. `test_expected_schema_covers_every_exported_table` checks that the site and the build agree.
4. Describe it in [DATA_DICTIONARY.md](DATA_DICTIONARY.md), and rebuild with `python -m pipeline data`. The whole export must stay under `MAX_TOTAL_MB`.

## Add a "who was harmed" option

The crash tables carry one count column per option, so a new option is a new count.

1. Add the flag in `crash_facts` (`pipeline/build/tables.py`) and its column to `COUNT_COLUMNS` in `checks.py`, then rebuild.
2. Add the option to `HARM` in `app/core/filters.py` (label, noun, column) and its words to `HARM_WORDS` in `app/core/search.py`. The dropdown, chart titles and search pick it up from there.

## Add a filter

1. Add the field to `Filters` in `app/core/filters.py`, with a default meaning "no restriction", and accept it in `make_filters` and `from_dict`. Add its caption text to `chips`.
2. Apply it in `crash_mask` (or `housing_rows`) in `app/core/data.py`. If the dimension is not in the cubes yet, add it to the `aggregate(...)` calls in `write_all` and rebuild; mind the export budget, since every dimension multiplies rows.
3. Add the vocabulary to `app/core/search.py` so a typed query can set it.
4. Add the dropdown to `app/ui/explorer_layout.py` and its value to `control_values` and `filters_from_controls` in `app/ui/callbacks.py`.

`tests/test_site.py` round-trips filters through the controls, the share link and the parser, and checks that every table conserves its totals under each filter.

## Add a chart to the Explorer report

1. Write a pure figure builder in `app/ui/charts.py` (marks, axes, legend and hover only; no data access).
2. Add a panel to `build_report` in `app/ui/report.py`, which turns one `Filters` value into every panel with its scope line and reading note. Add its key to `CHART_KEYS`.
3. Place the card in `app/ui/explorer_layout.py`. Charts are built when the reader comes near them (`app/ui/lazy.py`), so a new card needs no change to page load.

## Add a section to the page

1. Create `app/ui/sections/<name>.py` with two functions: `layout(store) -> component` and `register(app, store) -> None`. Use one id prefix for everything the section owns.
2. Add the module to `SECTIONS`, and a link to `NAV` if it should appear in the masthead, in `app/ui/page.py`.
3. Put computation in `app/analysis/` (no Dash there) and keep the section module to layout and callbacks. Styles go in a new file under `app/assets/css/`, loaded in file-name order.

`tests/test_architecture.py` rejects a section that is imported by `app.core` or `app.analysis`, or an analysis module that imports Dash.

## Add a pipeline command

Add the stage as a module with a `main(argv)` function, register it in `COMMANDS` and the dispatch in `pipeline/__main__.py`, and keep its paths in `pipeline/paths.py`.

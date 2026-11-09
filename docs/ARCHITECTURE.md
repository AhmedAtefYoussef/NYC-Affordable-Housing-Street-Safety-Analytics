# Architecture

The project has three deliverables built from one code base: an executed notebook, a website, and the documents in `docs/`. The notebook is the source of truth. The website shows the notebook's results and lets a reader filter the underlying counts. Two packages hold all the code:

- `pipeline/` turns the raw NYC Open Data files into the notebook and into the website's data.
- `app/` is the Dash website. It reads only `app/data/`.

## Data flow

```
 NYC Open Data API (hg8x-zxpr, h9gi-nx95)
          |  downloaded by Section 2 only if the files are missing
          v
 notebooks/housing_hg8x-zxpr.csv       notebooks/crashes_h9gi-nx95.csv.gz
          |                                        |
          +----------------+-----------------------+
                           v
          pipeline/notebook/sections/*.py   (one file per section, jupytext "percent" format)
                  |                                         |
   python -m pipeline notebook                    python -m pipeline data
   (pipeline/notebook/assemble.py)                (pipeline/build/: runner -> tables -> results
   joins, executes and writes the notebook         -> provenance -> export; skips the EDA section)
                  |                                         |
                  v                                         v
 notebooks/NYC_Housing_Safety.ipynb            app/data/*.parquet, results.json, meta.json
 (stored outputs, no repository imports)       (atomic write, schema, hashes, versions)
                                                            |
                                                            v
                                     app/ (Dash: core <- analysis <- ui <- app.py)
                                                            |
                                     one Python function on Vercel

 app/core/stats.py --- pasted into the notebook's Section 7 by the assembler (# INLINE)
                   --- imported by the website, and by the data build's final check
```

All locations are defined once, in `pipeline/paths.py`.

## The pipeline package

```
pipeline/
  __main__.py          python -m pipeline notebook | data
  paths.py             ROOT, RAW_DIR, SECTIONS_DIR, NOTEBOOK_PATH, STATS_MODULE, APP_DATA_DIR, commands
  notebook/
    assemble.py        joins the sections, inlines shared code, executes, writes the notebook
    sections/          00_title.py ... 10_story.py
  build/
    checks.py          build constants (output tables, count columns, grid steps, size budget) and require()
    runner.py          executes the section sources in one namespace inside notebooks/
    frames.py          narrow integer types, fixed category orders, JSON-safe values, parquet writing
    tables.py          the crash facts and cubes, the housing cube, the site and event-site tables
    results.py         results.json: the ten research-question results and the story facts
    provenance.py      meta.json: raw-file and source hashes, library versions, schema, constants
    export.py          atomic export, re-check with the website's own code, main()
```

### The notebook

The notebook is generated from `pipeline/notebook/sections/`, one file per section, joined in name order.

| File | Section |
|---|---|
| `00_title.py` | Title, abstract, team table, dataset links, map of the assignment's requirements |
| `01_setup.py` | Libraries, constants (window, buffer, bootstrap settings, seed), plot style, helpers |
| `02_data.py` | Loading through the API, overview, why these datasets, feasibility, known issues |
| `03_eda.py` | Exploratory analysis of both tables |
| `04_cleaning.py` | Pre-integration cleaning and the cleaning log |
| `05_integration.py` | The ZIP by year panel, the distance join, sites and clusters, event panel |
| `06_post_integration.py` | New gaps from the joins, ZIP recovery, redundant columns, types, conservation checks, citywide index |
| `07_toolkit.py` | Bootstrap, rank correlation, within-unit slopes, before and after, multiple tests, forecast evaluation, with a self-test |
| `08a_rq_1_5.py`, `08b_rq_6_10.py` | The ten research questions |
| `09_robustness.py` | Robustness checks of the central comparison and of the ZIP-level results |
| `10_story.py` | What was found, limits, impact, contributions, reproducibility |

`python -m pipeline notebook --execute` parses each file, concatenates the cells, runs them with nbclient inside `notebooks/` (where the two data files sit) and writes `notebooks/NYC_Housing_Safety.ipynb` (222 cells; the section sources total about 5,300 lines). It also:

- gives every cell a stable id built from its section file and position (for example `08a_rq_1_5-003`), so a rebuild changes only the cells that changed;
- refuses to overwrite the notebook when a cell fails: it prints the failing cell, writes `NYC_Housing_Safety.failed.ipynb` instead and exits with status 1;
- prints a per-section line budget (code and markdown lines) after every build;
- accepts `--sections` (file-name prefixes), `--out`, `--show` (print the outputs of chosen sections) and `--src` (read the section files from another folder).

The notebook imports nothing from the repository. It needs only the two data files and the libraries in `requirements-dev.txt`, and downloads the files if they are missing. Numbers that come from the data are printed by code, so the text follows the data.

### One home for the statistics: the INLINE mechanism

The cluster bootstrap, the difference-in-differences and the event-study profile are written once, in `app/core/stats.py`. Section 7 holds a code cell whose only line is `# INLINE: app/core/stats.py`; at assembly that cell is replaced by the file's code, under a comment naming its source. Section 1 holds `# INLINE-CONSTANTS: app/core/stats.py`, which takes the file's shared-constants block (seed, resample count, interval level), so a value changed in Section 1 reaches the statistics. The notebook therefore still imports nothing from the repository, and the website imports the same file, so both draw the same resamples with the same seed in the same order.

### The website data

`python -m pipeline data` executes the section sources in one namespace (all except the exploratory Section 3) and exports compact tables to `app/data/` (about 3.3 MB; a build takes about a minute and about 3 GB of memory). Each crash table carries the same seven counts, one per "who was harmed" option, so a filter can change the outcome without a new table. `docs/DATA_DICTIONARY.md` lists every file.

The export is a checked contract:

- Every check uses `require()`, which `python -O` cannot remove. Counts are conserved across every cube and match the notebook's ZIP by year panel cell for cell.
- Everything is written to a staging folder; only when all checks pass does it replace `app/data/`. A failure leaves the old data untouched. An output folder that holds files the build did not write is refused.
- After the export, the website's own code (`app.core`) reloads the staged files and must reproduce the notebook's RQ3 and RQ7 estimates, intervals and site counts. `--skip-check` turns this off.
- `meta.json` records the schema of every table, SHA-256 hashes of the raw files and of the source code (section files and `app/core/stats.py`), and the library versions. The website refuses to start on tables that do not match the schema, and the tests fail when the sources or raw files change without a rebuild.

## The website package

```
app/
  app.py              entry point: Dash app, security headers, routes (app.app:server on Vercel)
  core/               no Dash or Plotly
    data.py           loads app/data/, verifies the schema, filters the pre-aggregated tables
    filters.py        the filter model
    search.py         plain-words query parser that sets filters
    stats.py          the shared statistics (pasted into the notebook)
  analysis/           numbers and sentences for the page; imports app.core only
    scenarios.py      Test it: the main result re-estimated for a reader's comparison
    block_data.py     Your block: one site's record
    story_data.py     the figures behind the scrolling story
    story_text.py     interval wording and sentences shared by the story and the findings
  ui/                 Dash and Plotly; imports app.core and app.analysis
    theme.py          design tokens: one source for the CSS variables and the Plotly template
    components.py     shared building blocks
    charts.py         pure figure builders
    report.py         one filter selection -> every panel of the Explorer report
    explorer_layout.py, callbacks.py   the Explorer's controls and their callbacks
    story.py, lazy.py, grid.py         narrative sections, deferred chart loading, the map-grid route
    page.py, sections/                 the one-page layout: overview, block, lab, explorer, findings, method
  assets/             css/ and js/, loaded in file-name order by Dash
  data/               the files written by the pipeline
```

### Layers

```
app.core  <-  app.analysis  <-  app.ui  <-  app.app
```

A module imports only from its own layer and the layers to its left. `app.core` and `app.analysis` import no web framework, so the domain code can serve another front end, and the pipeline uses only `app.core`. `tests/test_architecture.py` parses every import and fails the build when a module reaches into a later layer, imports the entry point, or brings Dash, Plotly or Flask into the core or analysis layers.

### Runtime behaviour

On Vercel the site runs as one Python function; locally it runs with `python -m app.app`. At import it loads `app/data/` once, builds the layout and registers the callbacks, and does nothing else. The default report, the map grid (gzipped GeoJSON under a content-hashed URL) and each bootstrap are computed on the first request that needs them and cached in memory. Charts are built only when the reader scrolls near them (`app/ui/lazy.py`). The site imports nothing from the pipeline, the notebook or the raw data, and downloads nothing at start-up.

Charts and numbers in the Explorer change only when the reader presses Generate report. Typing in the search box or changing a dropdown updates the filters and marks the report as out of date. Each chart card states its filters and sample size, says when a housing filter does not apply to it, and a selection with too little data shows an empty state.

If `app/data/` is missing, the page shows a short "not ready" message and the server log names the build command.

## Deployment

`pyproject.toml` tells Vercel to serve `app.app:server` on Python 3.12 or newer. `vercel.json` sets `maxDuration` to 60 seconds for `app/app.py`, so a cold start that builds the first report is not cut off. `requirements.txt` lists the five packages the site needs, pinned so their installed size stays under Vercel's 500 MB limit for a Python function (the data is read with fastparquet rather than pyarrow for the same reason). `requirements-dev.txt` adds what the notebook, the pipeline and the tests need. `.vercelignore` keeps `notebooks/`, `pipeline/`, `tests/` and `docs/` out of the deployment. The site needs no environment variables, disk or database. Each pull request gets a preview deployment; `main` is production at https://data-engineering-visualization-proj-three.vercel.app/.

## Tests

`python -m pytest -q tests` runs 885 tests in 15 files with 98% coverage of `app/`; CI (`.github/workflows/tests.yml`) runs ruff (`ruff check app tests pipeline`) and the suite with a 97% coverage floor on every push and pull request.

| File | What it guards |
|---|---|
| `test_architecture.py` | The layer order of `app/` and the pipeline's dependency on `app.core` only |
| `test_pipeline.py` | The data contract: schema checked at start-up, atomic export, provenance from content |
| `test_data_accuracy.py` | Every number the site shows, recomputed from the raw files with separate code (skips when the raw files are absent) |
| `test_stats.py` | The shared statistics against hand-computed cases |
| `test_site.py` | Query parser, filters, conservation of totals, chart builders, callbacks through Flask's test client, notebook and site agreement |
| `test_hardening.py` | Security headers, hostile inputs, the cached map-grid route |
| `test_block.py`, `test_scenarios.py`, `test_explore.py`, `test_lazy.py`, `test_story_*.py`, `test_views_story.py`, `test_workbench.py`, `test_brand.py` | Each part of the page |

## Risks and how the design handles them

| Risk | Handling |
|---|---|
| API limits, timeouts, the default row limit | Section 2 pages on `collision_id`, retries with back-off, appends to a temporary file and resumes after an interruption |
| Memory use with 1.5 million crashes | Typed columns, small integer types and string columns backed by Arrow; the raw crash frame is released after cleaning |
| Distances in degrees | Haversine distances in metres; a ball tree checked against a brute-force computation |
| The same crash counted for several overlapping buffers | One count per site, clusters of linked sites, cluster bootstrap, an overlap measurement in Section 5.4 |
| Reporting change in 2020 | Injury crashes as the outcome; a comparison group over the same years; all-crash counts only as a check |
| Gaps created by joins | Section 6 logs each repair; ZIP recovery is validated on a holdout of whole locations (an upper bound) and flagged in the data |
| Chart and text drifting from the data | Data-derived numbers are printed by code; the site's story reads `results.json`; tests compare site, exported results and the raw files |
| The statistics diverging between notebook and site | `app/core/stats.py` is the only copy; the notebook pastes it with `# INLINE` |
| A failed notebook run replacing a good notebook | The assembler writes `*.failed.ipynb` and exits with status 1 |
| A failed data build replacing good data | Staging folder, checks, then an atomic swap; the old folder is restored if the swap fails |
| Website load time | Pre-aggregated cubes, a gzipped map grid and in-memory caches filled on first use; charts built on approach; no work at import |
| Vercel function limits (500 MB bundle, 2 GB memory, duration) | About 410 MB of pinned packages and 3.3 MB of data; `maxDuration` 60 s |
| A stale site after the notebook changes | `meta.json` hashes the sources and raw files, and a test fails until `python -m pipeline data` is run again |
| Code growing tangled as features are added | Layered packages with an enforced import order; one module per pipeline stage and per page section; see `docs/EXTENDING.md` |

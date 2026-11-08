# Architecture

The project has three deliverables that share one code base: a notebook, a website and the documents in `docs/`. The notebook is the source of truth. The website shows the notebook's results and lets a reader filter the underlying counts.

## Data flow

```
 NYC Open Data API (hg8x-zxpr, h9gi-nx95)
          |  downloaded by Section 2 only if the files are missing
          v
 notebooks/housing_hg8x-zxpr.csv       notebooks/crashes_h9gi-nx95.csv.gz
          |                                        |
          +----------------+-----------------------+
                           v
            tools/notebook_src/*.py  (section files, jupytext "percent" format)
                  |                                   |
   tools/assemble_notebook.py                tools/build_app_data.py
   joins the sections, executes them          runs the same sections in one process
                  |                           (except the exploratory Section 3)
                  v                                   v
 notebooks/NYC_Housing_Safety.ipynb              app/data/*.parquet, results.json, meta.json
 (stored outputs, no repository imports)                 |
                                                         v
                                              app/ (Dash, reads only app/data/)
                                                         |
                                              one Python function on Vercel

 app/stats.py  --- pasted into Section 7 of the notebook by assemble_notebook.py (# INLINE)
               --- imported by app/data.py, so the website and build_app_data.py's check use it too
```

## The notebook

The notebook is generated from the files in `tools/notebook_src/`, one file per section, joined in name order.

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

`tools/assemble_notebook.py` parses each file, concatenates the cells, runs them with nbclient inside `notebooks/` (where the two data files sit) and writes `notebooks/NYC_Housing_Safety.ipynb` (220 cells; the section sources total about 5,000 lines). It also:

- gives every cell a stable id built from its section file and position (for example `08a_rq_1_5-003`), so a rebuild changes only the cells that changed;
- refuses to overwrite the notebook when a cell fails: it prints the failing cell, writes `NYC_Housing_Safety.failed.ipynb` instead and exits with status 1;
- prints a per-section line budget (code and markdown lines) after every build;
- accepts `--sections` (file-name prefixes), `--out`, `--show` (print the outputs of chosen sections) and `--src` (read the section files from another folder).

The notebook imports nothing from the repository. It needs only the two data files and the libraries in `requirements.txt`, and downloads the files if they are missing. Numbers that come from the data are printed by code, so the text follows the data.

### One home for the statistics: the INLINE mechanism

The cluster bootstrap, the difference-in-differences and the event-study profile are written once, in `app/stats.py`. Section 7 (`07_toolkit.py`) holds a code cell whose only line is `# INLINE: app/stats.py`. When the notebook is assembled, that cell is replaced by the code of the file (without its `from __future__` line), under a comment saying where it comes from. The notebook therefore still imports nothing from the repository, and the website imports the same file, so both draw the same resamples with the same seed in the same order. `tools/build_app_data.py` runs the notebook sections, so it gets the pasted copy, and then runs the website's own code on the exported tables to compare it with the notebook's result.

## The website data

`tools/build_app_data.py` reads the section files through `assemble_notebook.py`, executes them in one namespace (all except the exploratory Section 3) and exports compact tables to `app/data/` (about 3.3 MB in all; the last build took 47 seconds, `meta.json`). Each crash table carries the same seven counts, one per "who was harmed" option, so a filter can change the outcome without a new table. `docs/DATA_DICTIONARY.md` lists every file. After the export the script runs the website's own statistics code (`app/stats.py`) on the exported tables and asserts that it reproduces the notebook's RQ3 and RQ7 estimates and intervals; `--skip-check` turns that off.

## The website

The site is a single Dash page. On Vercel it runs as one Python function; locally it runs with `python -m app.app`. At import it loads `app/data/` once, builds the layout and registers the callbacks, and does nothing else: no report, bootstrap or map file is computed in advance. The default report, the map grid (gzipped GeoJSON) and each bootstrap are computed on the first request that needs them and cached in memory. It imports nothing from the notebook or the raw data, and it downloads nothing at start-up.

| Module | Responsibility |
|---|---|
| `app.py` | Entry point (`app.app:server` on Vercel, `python -m app.app` locally); serves the map grid as cached, gzipped GeoJSON |
| `data.py` | Loads the parquet files and filters the pre-aggregated tables |
| `filters.py` | The filter model: borough, from and to year, construction type, building size, contributing factor, time of day, who was harmed, crash location. Setting a housing filter (construction type or size) switches the crash location to "within 250 m of a housing site" |
| `search.py` | Query parser; a longest-phrase vocabulary lookup plus year patterns, with typo tolerance, and parsing of the "who was harmed" phrases. It sets filters and reports what it understood and what it ignored |
| `stats.py` | The statistics, defined once: cluster bootstrap, difference-in-differences, event-study profile. Pasted into the notebook's Section 7 and imported by `data.py` |
| `charts.py` | Figure builders (pure functions): map, site selection, borough lines, completions, factors, weekday by hour heatmap, ZIP scatter, event study |
| `report.py` | Turns one filter selection into every panel of the report |
| `story.py` | Findings, limits, impact and data sections, written from `results.json`; each finding names its owner, the team member who asked the question |
| `layout.py`, `callbacks.py` | Page layout and the callbacks |
| `theme.py`, `assets/` | Design tokens (one source for CSS variables and the plotly template), `site.css`, `site.js` |

Charts and numbers change only when the reader presses Generate report. Typing in the search box or changing a dropdown updates the filters, marks the report as out of date, and nothing is recomputed until the button is pressed. Each chart card states its filters and sample size, says when a housing filter does not apply to it, and a selection with too little data shows an empty state. The weekday by hour heat map notes how many crashes are logged at 0:00, the default for a missing time.

If `app/data/` is missing, the page shows a short "not ready" message and the server log names the build command.

## Deployment

`pyproject.toml` tells Vercel to serve `app.app:server`, the Flask server that Dash creates, on Python 3.12 or newer. `vercel.json` sets `maxDuration` to 60 seconds for `app/app.py`, so a cold start that builds the first report is not cut off. `requirements.txt` lists the five packages the site needs, pinned so their installed size stays under Vercel's 500 MB limit for a Python function (the data is read with fastparquet rather than pyarrow for the same reason), and `requirements-dev.txt` adds what the notebook, the data build and the tests need. `.vercelignore` keeps `notebooks/`, `tools/`, `tests/` and `docs/` out of the deployment. The site needs no environment variables, disk or database. It is deployed at https://data-engineering-visualization-proj-three.vercel.app/, redeployed on every push to `main`.

## Tests

`python -m pytest -q tests` runs 820 tests in 14 files; the two files below check the data.

- `tests/test_site.py` covers the query parser, the filters, conservation of totals across every table, the chart builders, the callbacks through Flask's test client, and agreement between the site's numbers and the exported results.
- `tests/test_data_accuracy.py` recomputes the numbers the site shows from the two raw files with separate code (casualty totals, hour bands, factor groups, coordinates, nearest site within 250 m) and compares them with `app/data/` and with what the filter path returns. It reads the raw crash file once per run and skips when the raw files are absent. Where the site differs on purpose (a borough filled from a recovered ZIP, exact-distance ties between sites) the test asserts a bound, not an equality.

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
| The statistics diverging between notebook and site | `app/stats.py` is the only copy; the notebook pastes it with `# INLINE` |
| A failed notebook run replacing a good notebook | `assemble_notebook.py` writes `*.failed.ipynb` and exits with status 1 |
| Website load time | Pre-aggregated cubes, a gzipped map grid and in-memory caches filled on first use; no work at import; the site never touches raw data |
| Vercel function limits (500 MB bundle, 2 GB memory, duration) | About 350 MB of packages and 3.3 MB of data; `maxDuration` 60 s in `vercel.json`; memory was about 280 MB locally and has not been measured on Vercel |
| A stale site after the notebook changes | `build_app_data.py` regenerates every file from the same section sources and checks RQ3 and RQ7 |

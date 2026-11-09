"""The data pipeline: from two NYC Open Data tables to an executed notebook and the website's data.

    notebooks/*.csv(.gz)                      raw housing and crash files
          |
    pipeline/notebook/sections/*.py           the analysis, one file per notebook section
          |                          \
    notebook.assemble                 build (runner -> tables -> results -> provenance -> export)
          |                            \
    notebooks/NYC_Housing_Safety.ipynb   app/data/*.parquet, results.json, meta.json

Run a stage with the command line in `pipeline.__main__`:

    python -m pipeline notebook --execute
    python -m pipeline data

Locations live in `pipeline.paths`.
"""

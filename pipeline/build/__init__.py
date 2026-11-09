"""Data build stage: run the notebook sections and export the website's checked, pre-aggregated data.

Modules, in the order the build uses them:

    checks       constants of the build and `require`, the check that cannot be optimised away
    runner       execute the notebook sections in one namespace
    frames       narrow types, fixed category orders, JSON-safe values, parquet writing
    tables       the crash, housing and site tables the website filters
    results      results.json: the research-question results and story facts
    provenance   meta.json: hashes, library versions, schema, constants
    export       write everything atomically, re-check it with the website's code; `main`
"""

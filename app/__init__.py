"""The interactive website: a Dash app that reads only the files in app/data/.

Layers, each importing only from the layers before it (tests/test_architecture.py enforces this):

    app.core       data loading and the schema contract, the filter model, the search parser and the
                   statistics shared with the notebook; no Dash or Plotly
    app.analysis   numbers and sentences for the page, computed from the loaded store; no Dash or Plotly
    app.ui         Dash layout, Plotly figures, the report, callbacks and the page sections
    app.app        the entry point: `app.app:server` on Vercel, `python -m app.app` locally
"""

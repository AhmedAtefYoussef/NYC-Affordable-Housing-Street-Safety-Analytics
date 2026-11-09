"""Entry point. `app.app:server` is the WSGI server Vercel runs; `python -m app.app` runs it locally.

The process loads the exported tables once, builds the layout and registers the callbacks. The
default report and the map grid are built on the first request that needs them, so a cold start
stays short. It reads only app/data/ and imports nothing from the pipeline or the notebook.

Layers: app.core (data, filters, search, statistics) <- app.analysis (numbers and text for the page)
<- app.ui (Dash layout, charts, callbacks) <- this module. tests/test_architecture.py enforces the order.
"""
from __future__ import annotations

import logging
import os

import dash
from flask import Response

from app.analysis import story_data
from app.core import data
from app.core.filters import YEAR_END, YEAR_START
from app.ui import lazy, page
from app.ui.explorer_layout import missing_data_layout
from app.ui.grid import GEOJSON_URL, grid_url, serve_grid  # noqa: F401  (grid_url: public entry point)
from app.ui.theme import COLOR, FONTS_URL, css_variables

TITLE = "Affordable housing and injury crashes in NYC"
DESCRIPTION = ("An interactive report on affordable-housing buildings and police crash reports in "
               f"New York City, {YEAR_START} to {YEAR_END}.")
DEFAULT_PORT = 8050

# One policy for every response. 'unsafe-inline' scripts and styles are needed because Dash writes its
# config and renderer into the page; MapLibre (inside Plotly) starts its tile workers from blob: URLs and
# reads the CARTO style, tiles, sprites and glyphs; the fonts come from Google Fonts.
CARTO = "https://*.basemaps.cartocdn.com https://basemaps.cartocdn.com"
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com data:",
    f"img-src 'self' data: blob: {CARTO}",
    f"connect-src 'self' {CARTO}",
    "worker-src 'self' blob:",
    "child-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("site")

app = dash.Dash(
    __name__, title=TITLE, update_title=None, suppress_callback_exceptions=False,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"},
               {"name": "description", "content": DESCRIPTION},
               {"name": "color-scheme", "content": "dark"}])
server = app.server


@server.after_request
def add_security_headers(response: Response) -> Response:
    """Set the security headers on every response (pages, assets, callbacks and the grid)."""
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response

# The design tokens are written into the head as CSS variables; the files in app/assets/css use only them.
app.index_string = """<!DOCTYPE html>
<html lang="en">
<head>
{%metas%}
<title>{%title%}</title>
{%favicon%}
<link rel="icon" type="image/svg+xml" href="/assets/favicon.svg">
<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
<meta name="theme-color" content='""" + COLOR["page"] + """'>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href='""" + FONTS_URL + """'>
<style id="design-tokens">""" + css_variables() + """</style>
{%css%}
</head>
<body>
{%app_entry%}
<div class="dash-scripts">{%config%}{%scripts%}{%renderer%}</div>
</body>
</html>"""


try:
    STORE = data.load()
except FileNotFoundError as error:
    STORE = None
    log.warning("%s", error)
    app.layout = missing_data_layout(str(error))
else:
    full_page = page.build_page(STORE)
    app.layout, deferred, lazy_stores = lazy.defer(full_page)
    app.validation_layout = dash.html.Div([full_page, *lazy_stores])   # callbacks are checked against every part
    page.register(app, STORE)
    lazy.register(app, deferred)
    server.add_url_rule(GEOJSON_URL, "crash_grid", serve_grid(STORE))
    # The opening's points are fetched as soon as the page head is read, not once Dash has mounted the stage, so the
    # city lights up sooner. The stage's own fetch() asks for the same versioned URL and is answered from this one.
    app.index_string = app.index_string.replace(
        "{%css%}", f'<link rel="preload" as="fetch" crossorigin="anonymous" href="{story_data.versioned_url(STORE)}">'
        "\n{%css%}")
    log.info("data loaded: %s crashes, %s housing rows, built %s",
             f"{STORE.meta['rows']['crashes']:,}", f"{STORE.meta['rows']['housing']:,}", STORE.meta["built_at"])


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=int(os.environ.get("PORT", DEFAULT_PORT)))

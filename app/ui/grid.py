"""The map grid route: the crash-count cells as gzipped GeoJSON, served under a content-hashed URL.

`serve_grid(store)` returns the Flask view that app.app registers at GEOJSON_URL; `grid_url()` is the one
place callers (the report's map) get the URL, carrying a hash of the content so a rebuilt grid is never read
from an old cache.
"""
from __future__ import annotations

import functools
import gzip
import hashlib
import json

from flask import Response, request

from app.core import data

GEOJSON_URL = "/data/crash-grid.geojson"      # the bare route
GEOJSON_MAX_AGE_S = 31_536_000      # only for the versioned URL; the bare URL is revalidated every time

_grid_source: list = []        # holds the grid builder once the data is loaded


def grid_url() -> str:
    """The map grid's URL with a hash of its content. Without data it is the bare route."""
    if not _grid_source:
        return GEOJSON_URL
    return f"{GEOJSON_URL}?v={_grid_source[0]()[2]}"


def serve_grid(store):
    """A view that serves the map grid, gzip-compressed. Built on first use.

    The bare URL is revalidated on every load (ETag), so it can never paint counts on stale cells;
    the same URL with `?v=<hash>` is immutable for a year because the hash names the content.
    """

    @functools.cache
    def encoded() -> tuple[bytes, bytes, str]:
        payload = json.dumps(data.grid_geojson(store), separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()[:12]
        return payload, gzip.compress(payload, compresslevel=6), digest

    def crash_grid() -> Response:
        payload, compressed, digest = encoded()
        accepts_gzip = "gzip" in request.headers.get("Accept-Encoding", "")
        response = Response(compressed if accepts_gzip else payload, mimetype="application/geo+json")
        if accepts_gzip:
            response.headers["Content-Encoding"] = "gzip"
        immutable = request.args.get("v") == digest
        response.headers["Cache-Control"] = (f"public, max-age={GEOJSON_MAX_AGE_S}, immutable" if immutable
                                             else "no-cache")
        response.headers["Vary"] = "Accept-Encoding"
        response.set_etag(digest)
        return response.make_conditional(request)

    _grid_source[:] = [encoded]
    return crash_grid

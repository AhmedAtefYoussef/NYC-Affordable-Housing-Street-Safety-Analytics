"""Core layer: the data contract and the domain model, with no web framework.

    data      load app/data/, verify its schema, filter the pre-aggregated tables
    filters   the filter model (borough, years, construction type, size, factor, hour, harm, location)
    search    the plain-words query parser that sets filters
    stats     cluster bootstrap, difference-in-differences, event study; pasted into the notebook verbatim
"""

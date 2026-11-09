"""UI layer: everything Dash and Plotly. Imports app.core and app.analysis, never app.app.

    theme, components   design tokens and shared building blocks
    charts              pure figure builders
    report              one filter selection -> every panel of the Explorer report
    explorer_layout     the Explorer's controls; callbacks wires them to the report
    story, lazy, grid   the narrative, deferred chart loading, the map-grid route
    page, sections/     the one-page layout, assembled from one module per section
"""

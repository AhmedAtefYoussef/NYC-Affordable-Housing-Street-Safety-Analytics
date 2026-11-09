"""Figure builders. Each is a pure function of an already-filtered frame or dict.

No function here touches the data files or Dash. Titles and the "filters and n" line live in
the page (app/ui/report.py), so every figure carries only marks, axes, legend and hover text.
A selection with nothing to draw gets `empty_figure`, which keeps the chart's box and says why.
"""
from __future__ import annotations

import textwrap

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app.core.filters import baseline_text, buffer_m, pre_window_text
from app.ui.theme import (
    BOROUGH_COLOR,
    BOROUGH_SYMBOL,
    COLOR,
    CONSTRUCTION_COLOR,
    CONSTRUCTION_SYMBOL,
    SEQUENTIAL,
    plotly_template,
)

TEMPLATE = plotly_template()
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
UNSPECIFIED = "Unspecified"
NYC_CENTER = {"lat": 40.705, "lon": -73.94}
CITY_ZOOM, BOROUGH_ZOOM = 9.7, 10.8
MAP_STYLE = "carto-darkmatter"
COLOR_CAP_PERCENTILE = 98          # the colour scale tops out here so a few extreme cells do not flatten the rest
SITE_MARKER_RANGE = (3, 10)        # pixels: smallest and largest housing-site marker
BAND_OPACITY = 0.14
COLORBAR_LENGTH = 180              # pixels; a fixed length, see heatmap_figure
FOREST_LIMIT = 30                  # percent; intervals reaching further are clipped and labelled
FOREST_LABEL_WIDTH = 44            # characters per line of a row label, so the label column stays narrow


def _figure(**layout) -> go.Figure:
    figure = go.Figure()
    figure.update_layout(template=TEMPLATE, **layout)
    # Warm text on the dark ground: axis titles in warm white, ticks one step softer, a quiet grid.
    figure.update_xaxes(tickfont={"color": COLOR["ink-2"]}, title_font={"color": COLOR["ink"]},
                        gridcolor="rgba(246,242,233,0.07)")
    figure.update_yaxes(tickfont={"color": COLOR["ink-2"]}, title_font={"color": COLOR["ink"]},
                        gridcolor="rgba(246,242,233,0.07)")
    return figure


def _rgba(hex_color: str, alpha: float) -> str:
    red, green, blue = (int(hex_color[position:position + 2], 16) for position in (1, 3, 5))
    return f"rgba({red},{green},{blue},{alpha})"


def empty_figure(message: str) -> go.Figure:
    """A blank plot of the usual size with one centred sentence explaining what is missing."""
    figure = _figure(xaxis={"visible": False}, yaxis={"visible": False})
    figure.add_annotation(text=message, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False,
                          font={"size": 15, "color": COLOR["ink-2"]}, align="center")
    return figure


# ---------------------------------------------------------------------------------------------
# 1. Map: housing sites over crash density (both datasets)
# ---------------------------------------------------------------------------------------------
def map_figure(cells: pd.DataFrame, sites: pd.DataFrame, crash_noun: str, geojson_url: str,
               zoom_to_selection: bool) -> go.Figure:
    """Crash counts per 500 m cell as a one-hue choropleth, housing sites as points on top."""
    figure = _figure(margin={"l": 0, "r": 0, "t": 0, "b": 0})
    if len(cells):
        cap = max(float(np.percentile(cells["crashes"], COLOR_CAP_PERCENTILE)), 1.0)
        figure.add_trace(go.Choroplethmap(
            geojson=geojson_url, featureidkey="id", locations=cells["cell"], z=cells["crashes"],
            zmin=0, zmax=cap, colorscale=SEQUENTIAL, marker={"opacity": 0.72, "line": {"width": 0}},
            colorbar={"title": {"text": "Crashes per<br>500 m cell", "font": {"size": 12}}, "thickness": 10,
                      "lenmode": "pixels", "len": COLORBAR_LENGTH, "x": 0.99, "xanchor": "right", "y": 0.08, "yanchor": "bottom",
                      "bgcolor": _rgba(COLOR["surface"], 0.85), "tickfont": {"size": 11, "color": COLOR["ink"]}, "outlinewidth": 0},
            hovertemplate="%{z:,} " + crash_noun + "<br>in this 500 m cell<extra></extra>",
            name="Crash density", showlegend=False))
    if len(sites):
        low, high = SITE_MARKER_RANGE
        scale = np.sqrt(sites["total_units"].clip(lower=1) / 400).clip(upper=1)
        sizes = low + (high - low) * scale
        for kind, color in CONSTRUCTION_COLOR.items():
            rows = sites["construction_type"] == kind
            if not rows.any():
                continue
            part = sites[rows]
            figure.add_trace(go.Scattermap(
                # four decimals is about eleven metres, a third of a pixel at borough zoom, and keeps the
                # response small. No per-site hover strings travel with the figure: dot size shows the units.
                lat=part["lat"].astype(float).round(4), lon=part["lon"].astype(float).round(4),
                mode="markers", name=f"{kind} ({int(rows.sum()):,})",
                marker={"size": sizes[rows].round(0).astype(int), "color": color, "opacity": 0.8},
                hovertemplate="<b>" + kind + "</b><br>An affordable-housing building. A larger dot means more units."
                              "<extra></extra>"))
    center, zoom = NYC_CENTER, CITY_ZOOM
    points = sites if len(sites) else cells
    if zoom_to_selection and len(points):
        center = {"lat": float(points["lat"].mean()), "lon": float(points["lon"].mean())}
        zoom = BOROUGH_ZOOM
    figure.update_layout(
        showlegend=True,                 # also with one construction type, so the dots are always named
        map={"style": MAP_STYLE, "center": center, "zoom": zoom},
        modebar={"remove": ["pan", "lasso", "select"]},      # the map keeps its zoom buttons (wheel zoom is off)
        legend={"y": 0.99, "yanchor": "top", "x": 0.01, "bgcolor": _rgba(COLOR["surface"], 0.9),
                "bordercolor": COLOR["line"], "borderwidth": 1, "orientation": "v",
                "font": {"color": COLOR["ink"]}, "title": {"text": "Housing sites (size = units)", "font": {"size": 12, "color": COLOR["ink"]}}})
    return figure


# ---------------------------------------------------------------------------------------------
# 2. Line: crashes over time by borough
# ---------------------------------------------------------------------------------------------
def trend_figure(trend: pd.DataFrame, crash_noun: str, mark_reporting_break: bool) -> go.Figure:
    """One line per borough. Monthly when the frame has a date index, yearly otherwise."""
    monthly = bool(trend.attrs.get("monthly"))
    figure = _figure(hovermode="x unified")
    for borough in trend.columns:
        figure.add_trace(go.Scatter(
            x=trend.index, y=trend[borough], name=borough, mode="lines+markers",
            line={"color": BOROUGH_COLOR[borough], "width": 2},
            marker={"symbol": BOROUGH_SYMBOL[borough], "size": 7, "color": BOROUGH_COLOR[borough],
                    "line": {"color": COLOR["surface"], "width": 1}},
            hovertemplate="%{y:,}<extra>" + borough + "</extra>"))
    if monthly:
        figure.update_xaxes(tickformat="%b %Y", hoverformat="%B %Y", showgrid=False)
    else:
        figure.update_xaxes(dtick=1, tickformat="d", showgrid=False)
        years = list(trend.index)
        if mark_reporting_break and 2020 in years and years[0] < 2020:
            figure.add_vline(x=2019.5, line={"color": COLOR["ink-3"], "width": 1, "dash": "dot"})
            figure.add_annotation(x=2019.5, y=1, yref="paper", xanchor="left", yanchor="top", showarrow=False,
                                  text=" From 2020 far fewer crashes<br> without injuries were reported",
                                  font={"size": 12, "color": COLOR["ink-3"]}, align="left")
    figure.update_yaxes(title_text=f"{crash_noun.capitalize()} per {'month' if monthly else 'year'}",
                        rangemode="tozero", tickformat=",")
    return figure


# ---------------------------------------------------------------------------------------------
# 3. Bar: contributing-factor groups
# ---------------------------------------------------------------------------------------------
def factor_figure(factors: pd.Series) -> go.Figure:
    """Horizontal bars, largest first; the 'no factor recorded' group is grey and sits last."""
    recorded = factors.drop(UNSPECIFIED, errors="ignore").sort_values(ascending=True)
    ordered = pd.concat([factors[[UNSPECIFIED]], recorded]) if UNSPECIFIED in factors.index else recorded
    total = max(int(factors.sum()), 1)
    share = ordered / total * 100
    colors = [COLOR["comparison"] if name == UNSPECIFIED else COLOR["crash"] for name in ordered.index]
    labels = ["No factor recorded" if name == UNSPECIFIED else name for name in ordered.index]
    figure = _figure(bargap=0.28, margin={"l": 8, "r": 56, "t": 12, "b": 8})
    figure.add_trace(go.Bar(
        x=ordered.to_numpy(), y=labels, orientation="h", marker={"color": colors, "cornerradius": 3},
        text=[f"{value:.0f}%" if value >= 1 else "<1%" for value in share], textposition="outside",
        textfont={"size": 12, "color": COLOR["ink-2"]}, cliponaxis=False, customdata=share,
        hovertemplate="%{y}<br>%{x:,} crashes (%{customdata:.1f}% of the selection)<extra></extra>"))
    figure.update_xaxes(title_text="Crashes", tickformat=",", rangemode="tozero")
    figure.update_yaxes(showgrid=False, ticks="")
    return figure


# ---------------------------------------------------------------------------------------------
# 4. Heatmap: weekday by hour
# ---------------------------------------------------------------------------------------------
def heatmap_figure(matrix: np.ndarray, crash_noun: str) -> go.Figure:
    """Seven weekday rows by twenty-four hour columns, one hue from light to dark."""
    hours = [f"{hour:02d}" for hour in range(24)]
    spans = [[f"{day}, {hour:02d}:00 to {hour:02d}:59" for hour in range(24)] for day in WEEKDAYS]
    figure = _figure(margin={"l": 8, "r": 8, "t": 52, "b": 8})
    figure.add_trace(go.Heatmap(
        z=matrix, x=hours, y=WEEKDAYS, colorscale=SEQUENTIAL, zmin=0, xgap=2, ygap=2, customdata=spans,
        # The colour key lies above the plot with a length in pixels. A key sized as a fraction of the
        # plot gets a negative length when the chart box is still a few pixels tall on first paint,
        # and Plotly then fails with "Something went wrong with axis scaling".
        colorbar={"orientation": "h", "lenmode": "pixels", "len": COLORBAR_LENGTH, "thickness": 8,
                  "x": 0, "xanchor": "left", "y": 1.02, "yanchor": "bottom", "xpad": 0, "ypad": 0,
                  "title": {"text": f"{crash_noun.capitalize()} per weekday and hour", "side": "top",
                            "font": {"size": 12}},
                  "tickfont": {"size": 11, "color": COLOR["ink"]}, "tickformat": ",", "nticks": 5, "outlinewidth": 0},
        hovertemplate="%{customdata}<br>%{z:,} " + crash_noun + "<extra></extra>"))
    figure.update_xaxes(title_text="Hour of day", showgrid=False, ticks="", dtick=2, fixedrange=False)
    figure.update_yaxes(autorange="reversed", showgrid=False, ticks="")
    return figure


# ---------------------------------------------------------------------------------------------
# 5. Bar: affordable units completed per year
# ---------------------------------------------------------------------------------------------
def completions_figure(tables: dict[str, pd.DataFrame]) -> go.Figure:
    """Stacked bars per completion year, one segment per construction type."""
    units, buildings = tables["affordable_units"], tables["buildings"]
    figure = _figure(barmode="stack", bargap=0.3, hovermode="x unified", legend={"traceorder": "normal"})
    for kind in units.columns:
        figure.add_trace(go.Bar(
            x=units.index, y=units[kind], name=kind, customdata=buildings[kind],
            marker={"color": CONSTRUCTION_COLOR[kind], "line": {"color": COLOR["surface"], "width": 2}},
            hovertemplate="%{y:,} units in %{customdata:,} buildings<extra>" + kind + "</extra>"))
    figure.update_xaxes(dtick=1, tickformat="d", showgrid=False, title_text="Completion year")
    figure.update_yaxes(title_text="Affordable units completed", tickformat=",", rangemode="tozero")
    return figure


# ---------------------------------------------------------------------------------------------
# 6. Scatter: housing against crashes, one point per ZIP code (both datasets)
# ---------------------------------------------------------------------------------------------
def scatter_figure(table: pd.DataFrame, crash_noun: str) -> go.Figure:
    """Units completed against crashes per year on two log axes; borough is in the hover text."""
    figure = _figure(margin={"l": 8, "r": 16, "t": 12, "b": 8})
    # Zero cannot sit on a log axis, so those ZIP codes are drawn at 0.1; the hover keeps the true value.
    true_rate = [f"{value:,.1f}" + (" (drawn at the axis floor of 0.1)" if value < 0.1 else "")
                 for value in table["crashes_per_year"]]
    figure.add_trace(go.Scatter(
        x=table["affordable_units"], y=table["crashes_per_year"].clip(lower=0.1), mode="markers",
        marker={"size": 9, "color": _rgba(COLOR["housing"], 0.7), "line": {"color": COLOR["page"], "width": 1}},
        customdata=np.column_stack([table["zip"], table["borough"], table["buildings"].astype(int),
                                    table["crashes"], true_rate]),
        hovertemplate=("<b>ZIP %{customdata[0]}</b>, %{customdata[1]}<br>"
                       "%{x:,.0f} affordable units in %{customdata[2]} buildings<br>"
                       "%{customdata[4]} " + crash_noun + " per year<extra></extra>")))
    figure.update_xaxes(type="log", title_text="Affordable units completed in the ZIP code (log scale)",
                        tickformat=",", dtick=1)
    figure.update_yaxes(type="log", title_text=f"{crash_noun.capitalize()} per year (log scale)",
                        tickformat=",", dtick=1)
    return figure


# ---------------------------------------------------------------------------------------------
# 7. Event study: before and after completion (both datasets)
# ---------------------------------------------------------------------------------------------
def event_figure(study: dict) -> go.Figure:
    """Indexed lines with 95% bands: completed sites by type, and not-yet-completed comparison sites."""
    if study.get("empty"):
        return empty_figure("Too few usable sites for a before and after comparison.")
    rel_years = study["rel_years"]
    figure = _figure(hovermode="x unified")
    figure.add_vrect(x0=-0.5, x1=0.5, fillcolor=_rgba(COLOR["housing"], 0.06), line_width=0, layer="below")
    figure.add_hline(y=100, line={"color": COLOR["line-strong"], "width": 1})

    def add_line(profile, name, color, symbol, dash):
        figure.add_trace(go.Scatter(
            x=rel_years + rel_years[::-1], y=list(profile["high"]) + list(profile["low"])[::-1],
            mode="lines", fill="toself", fillcolor=_rgba(color, BAND_OPACITY), line={"width": 0},
            hoverinfo="skip", showlegend=False))
        figure.add_trace(go.Scatter(
            x=rel_years, y=profile["index"], name=f"{name} (n = {profile['n_sites']:,} sites)",
            mode="lines+markers", line={"color": color, "width": 2, "dash": dash},
            marker={"symbol": symbol, "size": 8, "color": color, "line": {"color": COLOR["surface"], "width": 1}},
            customdata=np.column_stack([profile["low"], profile["high"]]),
            hovertemplate="%{y:.0f} (95% interval %{customdata[0]:.0f} to %{customdata[1]:.0f})<extra>"
                          + name + "</extra>"))

    add_line(study["comparison"], "Not yet completed", COLOR["reference"], "diamond", "dot")
    for kind, part in study["treated"].items():
        add_line(part["profile"], f"{kind}, completed in year 0", CONSTRUCTION_COLOR[kind],
                 CONSTRUCTION_SYMBOL[kind], "solid")
    figure.add_annotation(x=0, y=1, yref="paper", yanchor="top", showarrow=False, text="completion<br>year",
                          font={"size": 12, "color": COLOR["ink-3"]})
    figure.update_xaxes(title_text="Years relative to completion", tickvals=rel_years,
                        ticktext=[f"{year:+d}" if year else "0" for year in rel_years], showgrid=False)
    figure.update_yaxes(title_text=f"{study['noun'].capitalize()} within {buffer_m()} m per site<br>(mean of years {pre_window_text()} = 100)")
    figure.update_layout(legend={"orientation": "h", "y": 1.02})
    return figure


# ---------------------------------------------------------------------------------------------
# 8. Bar: where the sites stood before construction
# ---------------------------------------------------------------------------------------------
def selection_figure(selection: dict) -> go.Figure:
    """Share of future housing sites in each tenth of the borough's street ranking for injury crashes."""
    if selection.get("empty"):
        return empty_figure("Too few sites match this selection.")
    width = selection["bin_width"]
    starts = list(range(0, 100, width))
    labels = [f"{start} to {start + width}" for start in starts]
    figure = _figure(bargap=0, margin={"l": 8, "r": 12, "t": 20, "b": 8})
    # Bars sit on a numeric axis from 0 to 100 with ticks at the bin edges. Ten "0 to 10" labels do not
    # fit under ten bars on a phone; eleven short numbers do.
    figure.add_trace(go.Bar(
        x=[start + width / 2 for start in starts], y=selection["bin_share"], width=width * 0.84,
        customdata=labels, marker={"color": COLOR["housing"], "cornerradius": 3},
        hovertemplate="Percentile %{customdata}<br>%{y:.1f}% of sites<extra></extra>", name="Housing sites"))
    figure.add_hline(y=width, line={"color": COLOR["ink-2"], "width": 1.5, "dash": "dot"})
    figure.add_annotation(x=0, xref="paper", y=width, xanchor="left", yanchor="bottom", showarrow=False,
                          text=f"Typical streets: {width}% in every bar", xshift=6, yshift=3, borderpad=2,
                          bgcolor=_rgba(COLOR["surface"], 0.9),       # stays readable where it crosses a bar
                          font={"size": 12, "color": COLOR["ink-2"]})
    figure.update_xaxes(title_text=f"Street percentile for injury crashes, {baseline_text()}<br>(higher = more crashes)",
                        showgrid=False, tickangle=0, range=[0, 100], tickvals=starts + [100], zeroline=False)
    figure.update_yaxes(title_text="Share of sites", ticksuffix="%", rangemode="tozero")
    return figure


# ---------------------------------------------------------------------------------------------
# Story figures (not filter-driven)
# ---------------------------------------------------------------------------------------------
def reporting_break_figure(city_year: pd.DataFrame) -> go.Figure:
    """All reported crashes and injury crashes citywide, both indexed to 2019 = 100."""
    figure = _figure(hovermode="x unified", showlegend=False, margin={"l": 8, "r": 128, "t": 12, "b": 8})
    series = [("crash_index", "All reported crashes", COLOR["comparison"], "diamond"),
              ("injury_crash_index", "Injury crashes", COLOR["crash"], "circle")]
    for column, name, color, symbol in series:
        figure.add_trace(go.Scatter(
            x=city_year["year"], y=city_year[column], name=name, mode="lines+markers",
            line={"color": color, "width": 2}, marker={"symbol": symbol, "size": 7, "color": color,
                                                       "line": {"color": COLOR["surface"], "width": 1}},
            hovertemplate="%{y:.0f}<extra>" + name + "</extra>"))
        last = city_year.iloc[-1]
        # The end labels sit in the right margin (paper coordinates) so they cannot stretch the axis.
        figure.add_annotation(x=1, xref="paper", y=last[column], xanchor="left", showarrow=False, xshift=6,
                              text=f"{name}<br>{last[column]:.0f}", align="left",
                              font={"size": 12, "color": COLOR["ink-2"]})
    figure.add_hline(y=100, line={"color": COLOR["line-strong"], "width": 1})
    first_year, last_year = int(city_year["year"].min()), int(city_year["year"].max())
    figure.update_xaxes(dtick=1, tickformat="d", showgrid=False, range=[first_year - 0.4, last_year + 0.25])
    figure.update_yaxes(title_text="Index, 2019 = 100", rangemode="tozero")
    return figure


def robustness_figure(table: pd.DataFrame) -> go.Figure:
    """Forest plot of the central estimate under each alternative specification."""
    kinds = {"central": ("Central estimate", COLOR["housing"], "diamond"),
             "check": ("One choice changed", COLOR["ink-2"], "circle"),
             "placebo": ("Placebo (no change expected)", COLOR["placebo"], "square")}
    table = table[table["estimate"].notna()].reset_index(drop=True)      # a version with too few sites has no estimate
    labels = ["<br>".join(textwrap.wrap(f"{check}: {variant}", FOREST_LABEL_WIDTH))
              for check, variant in zip(table["check"], table["variant"])]
    # The legend hangs from the top left corner of the figure, not of the plot area: the long row labels
    # leave the plot area too narrow for three legend entries in one row.
    figure = _figure(margin={"l": 8, "r": 16, "t": 44, "b": 8},
                     legend={"xref": "container", "x": 0.01, "yref": "container", "y": 0.995, "yanchor": "top"})
    figure.add_vline(x=0, line={"color": COLOR["line-strong"], "width": 1})
    for kind, (name, color, symbol) in kinds.items():
        rows = table[table["kind"] == kind]
        if rows.empty:
            continue
        clipped_high = rows["percent_high"].clip(upper=FOREST_LIMIT)
        clipped_low = rows["percent_low"].clip(lower=-FOREST_LIMIT)
        estimate = rows["percent_change"].clip(-FOREST_LIMIT, FOREST_LIMIT)
        figure.add_trace(go.Scatter(
            x=estimate, y=[labels[position] for position in rows.index], mode="markers", name=name,
            marker={"color": color, "symbol": symbol, "size": 10, "line": {"color": COLOR["surface"], "width": 1}},
            error_x={"type": "data", "symmetric": False, "array": clipped_high - estimate,
                     "arrayminus": estimate - clipped_low, "color": color, "thickness": 1.5, "width": 0},
            customdata=np.column_stack([rows["percent_change"], rows["percent_low"], rows["percent_high"],
                                        rows["n_treated"], rows["n_comparison_sites"], rows["n_comparison"],
                                        rows["n_treated_clusters"], rows["n_resampled_units"]]),
            hovertemplate=("%{y}<br>%{customdata[0]:+.1f}% (95% interval %{customdata[1]:+.1f} to "
                           "%{customdata[2]:+.1f})<br>%{customdata[3]:,} completed sites and "
                           "%{customdata[4]:,} comparison sites (%{customdata[5]:,} comparison rows)<br>"
                           "%{customdata[6]:,} of %{customdata[7]:,} resampled clusters hold a completed site"
                           "<extra></extra>")))
    beyond = table[table["percent_high"] > FOREST_LIMIT]
    for position, row in beyond.iterrows():
        figure.add_annotation(x=FOREST_LIMIT, y=labels[position], xanchor="right", yanchor="bottom",
                              showarrow=False, text=f"interval runs to {row['percent_high']:+.0f}%",
                              font={"size": 11, "color": COLOR["ink-3"]})
    figure.update_xaxes(title_text="Change in injury crashes after completion, relative to comparison sites",
                        ticksuffix="%", range=[-FOREST_LIMIT - 2, FOREST_LIMIT + 2], zeroline=False)
    figure.update_yaxes(autorange="reversed", showgrid=True, ticks="", categoryorder="array",
                        categoryarray=labels, tickfont={"size": 12, "color": COLOR["ink-2"]})
    return figure

"""Turn one `Filters` value into everything the report shows.

`build_report` is the single place where data functions and figure builders meet. It returns
plain Dash components and figures keyed by chart, and it never raises for a sparse selection:
a chart without enough data gets an empty state that says what is missing.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

import numpy as np
import plotly.graph_objects as go
from dash import html

from app.analysis.story_text import signed
from app.core import data
from app.core.data import MIN_GROUP_N, Store
from app.core.filters import (
    Filters,
    baseline_text,
    buffer_m,
    chips,
    crash_scope_text,
    housing_kind_text,
    housing_scope_text,
    nearest_site_text,
    place_text,
    year_text,
)
from app.ui import charts, components
from app.ui.grid import GEOJSON_URL, grid_url  # noqa: F401  (GEOJSON_URL: the route the map reads)

MIN_ZIPS_FOR_SCATTER = 5
CHART_KEYS = ["map", "selection", "trend", "completions", "factors", "heatmap", "scatter", "event"]


@dataclass
class Panel:
    """One chart with the two lines of text around it."""

    figure: go.Figure
    scope: list          # which filters apply and the n behind the chart
    note: list           # how to read it, and what it does not show


def _scope(*parts) -> list:
    """Scope line: labelled pieces separated by thin gaps."""
    return [html.Span(part, className="scope-part") for part in parts if part]


def _n(text: str) -> html.Span:
    return html.Span(text, className="scope-n")


def _map_panel(store: Store, filters: Filters) -> Panel:
    cells, sites = data.map_cells(store, filters), data.map_sites(store, filters)
    noun = filters.harm_noun
    if cells.empty and sites.empty:
        figure = charts.empty_figure("No located crashes and no housing sites match this selection.")
    else:
        figure = charts.map_figure(cells, sites, noun, grid_url(), zoom_to_selection=bool(filters.boroughs))
    scope = _scope(f"Crashes: {crash_scope_text(filters)}", f"Housing: {housing_scope_text(filters)}",
                   _n(f"n = {int(cells['crashes'].sum()):,} located crashes in {len(cells):,} cells, "
                      f"{len(sites):,} housing sites"))
    note = ["Darker cells hold more crashes. Dots are affordable-housing buildings completed in the selected "
            "years. The two layers overlap because both follow density, which is why a map alone cannot say "
            "what housing does to a street. Crashes without coordinates are not on the map."]
    return Panel(figure, scope, note)


def _selection_panel(store: Store, filters: Filters) -> Panel:
    selection = data.site_selection(store, filters)
    baseline = store.meta["constants"]["baseline_years"]
    scope = _scope(f"Sites: {place_text(filters)} · {housing_kind_text(filters)} started after {baseline[1]}",
                   "Not applied: years and crash filters (the baseline is injury crashes in "
                   f"{baseline_text()})", _n(f"n = {selection['n']:,} sites"))
    if selection.get("empty"):
        figure = charts.empty_figure(f"Only {selection['n']} sites match.<br>This chart needs at least {MIN_GROUP_N}.")
        return Panel(figure, scope, ["Choose more boroughs, both construction types or more size bands."])
    side = "above" if selection["excess"] > 0 else "below"
    clear = selection["low"] > 0 or selection["high"] < 0
    note = [f"Each site is ranked among street points of its own borough by injury crashes within {buffer_m()} m "
            f"before construction. The average site sits at the {selection['mean_percentile']:.0f}th percentile, "
            f"{abs(selection['excess']):.1f} percentile points {side} a typical street (50th). The 95% interval "
            f"is {signed(selection['low'])} to {signed(selection['high'])}, computed by resampling "
            f"{selection['n_blocks']:,} {selection['cluster_unit']}. ",
            "The interval excludes zero. " if clear else "The interval includes zero. ",
            "The ranking uses the years before the project started, so it shows where the buildings are and "
            "is not something the project did. The benchmark is street points, not other housing."]
    one_vote = selection["one_vote"]
    if np.isnan(one_vote["estimate"]):
        note.append(f" These sites form {one_vote['n_clusters']:,} clusters, too few (under {MIN_GROUP_N}) to count each "
                    "cluster once.")
    else:
        side = "excludes" if one_vote["low"] > 0 or one_vote["high"] < 0 else "includes"
        note.append(f" Counting each cluster of linked sites once gives {signed(one_vote['estimate'])} points (interval "
                    f"{signed(one_vote['low'])} to {signed(one_vote['high'])}, {one_vote['n_clusters']:,} clusters, {side} "
                    "zero), so the size depends on whether buildings or places are counted.")
    if not filters.construction:
        note.append(" Both construction types are pooled here. The headline result in the Findings section "
                    "(RQ7) uses new-construction sites only.")
    return Panel(charts.selection_figure(selection), scope, note)


def _trend_panel(store: Store, filters: Filters, total: int) -> Panel:
    trend = data.crash_trend(store, filters)
    scope = _scope(f"Crashes: {crash_scope_text(filters)}", _n(f"n = {int(trend.to_numpy().sum()):,} crashes with a borough"))
    if total == 0:
        return Panel(charts.empty_figure("No crashes match this selection."), scope, [_widen_hint(filters)])
    figure = charts.trend_figure(trend, filters.harm_noun, mark_reporting_break=filters.harm == "all")
    step = "Monthly" if trend.attrs["monthly"] else "Yearly"
    note = [f"{step} counts. "]
    if filters.harm == "all":
        note.append("Do not read the drop in 2020 as safer streets: reports without injuries fell by half that year. ")
    elif not trend.attrs["monthly"] and 2020 in trend.index:
        note.append("The dip in 2020 coincides with the first pandemic year. ")
    note.append("Boroughs differ in size, so compare the shape of a line with itself over time, not its height "
                "with another borough.")
    return Panel(figure, scope, note)


def _completions_panel(store: Store, filters: Filters, numbers: dict) -> Panel:
    tables = data.completions_by_year(store, filters)
    scope = _scope(f"Housing: {housing_scope_text(filters)}",
                   _n(f"n = {numbers['buildings']:,} buildings, {numbers['affordable_units']:,} affordable units"))
    if numbers["buildings"] == 0:
        return Panel(charts.empty_figure("No buildings were completed in this selection."), scope,
                     ["Widen the years or remove a housing filter."])
    note = [f"Affordable units in buildings completed in each year. {numbers['buildings_unlocated']:,} of the "
            "buildings have no usable coordinates, mostly confidential records with no address. They count in "
            "these bars but cannot be placed on the map."]
    return Panel(charts.completions_figure(tables), scope, note)


def _factors_panel(store: Store, filters: Filters, total: int) -> Panel:
    factors = data.factor_mix(store, filters)
    scope = _scope(f"Crashes: {crash_scope_text(filters)}", _n(f"n = {int(factors.sum()):,} crashes"))
    if total == 0:
        return Panel(charts.empty_figure("No crashes match this selection."), scope, [_widen_hint(filters)])
    blank = factors.get(charts.UNSPECIFIED, 0) / max(factors.sum(), 1) * 100
    note = [f"The factor is the first one the police report names for the first vehicle. {blank:.0f}% of the "
            "selected reports name none, shown in grey. A factor is the officer's judgment at the scene."]
    if 0 < total < MIN_GROUP_N:
        note.append(f" Only {total} crashes match, so the shares are unstable.")
    return Panel(charts.factor_figure(factors), scope, note)


def _heatmap_panel(store: Store, filters: Filters, total: int) -> Panel:
    matrix = data.weekday_hour(store, filters)
    scope = _scope(f"Crashes: {crash_scope_text(filters)}", _n(f"n = {int(matrix.sum()):,} crashes"))
    if total == 0:
        return Panel(charts.empty_figure("No crashes match this selection."), scope, [_widen_hint(filters)])
    day, hour = divmod(int(matrix.argmax()), 24)
    note = [f"The busiest cell is {charts.WEEKDAYS[day]} from {hour:02d}:00 to {hour:02d}:59 with "
            f"{int(matrix.max()):,} crashes."]
    unknown = store.meta["rows"].get("crashes_time_unknown")
    if unknown:   # 0:00 is the police default for a missing time (notebook Section 4)
        note.append(f" The 00:00 hour includes {unknown:,} crashes city-wide whose time was recorded as 0:00, "
                    "which usually means the time is unknown; the notebook leaves them out of hour-of-day results.")
    if 0 < total < 7 * 24:
        note.append(f" With {total} crashes over 168 cells, much of the pattern may be chance.")
    return Panel(charts.heatmap_figure(matrix, filters.harm_noun), scope, note)


def _scatter_panel(store: Store, filters: Filters) -> Panel:
    relation = data.zip_relation(store, filters)
    table = relation["table"]
    scope = _scope(f"Crashes: {crash_scope_text(filters)}", f"Housing: {housing_scope_text(filters)}",
                   _n(f"n = {len(table):,} ZIP codes with matching housing"))
    if len(table) < MIN_ZIPS_FOR_SCATTER or table["crashes"].sum() == 0:
        figure = charts.empty_figure(f"{len(table)} ZIP codes have both matching housing and crashes.<br>"
                                     f"A scatter needs at least {MIN_ZIPS_FOR_SCATTER}.")
        return Panel(figure, scope, ["Choose more boroughs or a longer period."])
    note = []
    if relation["rho"] is not None:
        note.append(f"Rank correlation {signed(relation['rho'], 2)} across {len(table)} ZIP codes (+1 means the "
                    "ZIP codes with more units always have more crashes, 0 means no link). ")
    else:
        note.append(f"Too few ZIP codes for a correlation (fewer than {MIN_GROUP_N}). ")
    note.append("Both counts grow with the size and density of a ZIP code, so a positive correlation is "
                "expected whatever housing does. The chart compares places with each other and says nothing "
                "about change over time. ")
    if relation["n_without_units"]:
        note.append(f"{relation['n_without_units']} ZIP codes without matching housing are not drawn. ")
    note.append("ZIP codes with zero crashes are drawn at the axis floor (0.1); the hover shows the true value.")
    return Panel(charts.scatter_figure(table, filters.harm_noun), scope, note)


def _did_sentence(kind: str, did: dict) -> str:
    return (f"{kind}: {signed(did['percent_change'])}% (95% interval {signed(did['percent_low'])}% to "
            f"{signed(did['percent_high'])}%, {did['n_treated']:,} completed sites). ")


def _event_panel(store: Store, filters: Filters) -> Panel:
    study = data.event_study(store, filters)
    outcome_note = ""
    if filters.harm in {"ped", "cyc"}:
        outcome_note = " (pedestrians and cyclists are counted together here)"
    elif filters.harm in {"mot", "fatal"}:
        outcome_note = " (this outcome is not tracked per site, so injury crashes are shown)"
    counted = ", ".join(f"{count:,} {kind.lower()}" for kind, count in study["n_by_type"].items())
    scope = _scope(f"Sites: {place_text(filters)} · {housing_kind_text(filters)}, completed {data.event_cohort_text(store)}",
                   f"Outcome: {study['noun']}{outcome_note}",
                   "Not applied: years, contributing factor, time of day, crash location",
                   _n(f"n = {counted} completed sites in {study['n_treated_clusters']:,} of {study['n_clusters']:,} "
                      f"clusters; {study['n_comparison_sites']:,} comparison sites ({study['n_comparison']:,} rows, "
                      "one per cohort a site serves)"))
    if study.get("empty"):
        figure = charts.empty_figure(f"Too few usable sites for a before and after comparison.<br>"
                                     f"Each group needs at least {MIN_GROUP_N}. Sites with another completed "
                                     f"building within {buffer_m()} m are left out.")
        return Panel(figure, scope, ["Remove the borough or size filter. Sites with another completion inside "
                                     f"their {buffer_m()} m circle are excluded, which leaves few per borough."])
    note = ["After against before, relative to comparison sites. Read this interval, not the overlap of the "
            "bands: each band is resampled on its own, while this interval resamples both groups together. "]
    note += [_did_sentence(kind, part["did"]) for kind, part in study["treated"].items()]
    intervals = [part["did"] for part in study["treated"].values()]
    if all(did["percent_low"] < 0 < did["percent_high"] for did in intervals):
        note.append("Every interval includes zero, so these records are compatible with no change after "
                    "completion. The intervals are wide, so a modest change in either direction is not ruled out. ")
    else:
        note.append("An interval that excludes zero is an association in these records and does not show "
                    "that the building changed the street. ")
    skipped = [kind for kind in study["n_by_type"] if kind not in study["treated"]]
    if skipped:
        note.append(f"{', '.join(skipped)} has fewer than {MIN_GROUP_N} usable sites on one side here and is not drawn. ")
    if "Preservation" in study["treated"]:
        note.append("Preservation renovates buildings that already have residents, so a change there is not "
                    "expected to come from new residents. It works as a check. ")
    if len(study["treated"]) == 2:
        note.append("The two types share one resampling here, as in RQ5, so the new-construction interval "
                    "differs slightly from RQ3. Choose New Construction alone to see the RQ3 interval.")
    return Panel(charts.event_figure(study), scope, note)


def _widen_hint(filters: Filters) -> str:
    """What to loosen when nothing matches."""
    tight = []
    if filters.factors:
        tight.append("the contributing factor")
    if filters.hours:
        tight.append("the time of day")
    if filters.scope == "near":
        tight.append("the crash location")
    if filters.n_years < 3:
        tight.append("the years")
    if filters.boroughs:
        tight.append("the borough")
    tight = tight[:3]
    if not tight:
        return "Try widening the selection."
    return "Try widening " + (", ".join(tight[:-1]) + " and " + tight[-1] if len(tight) > 1 else tight[0]) + "."


def _figure(value: str, label: str, detail: str, tone: str, count_to: float | None) -> html.Div:
    """One big figure on the ground. It carries the class the Generate sequence settles in."""
    figure = components.metric(value, label, detail, tone, count_to)
    figure.className = "metric tile"
    return figure


def summary_tiles(filters: Filters, numbers: dict) -> list:
    """The four numbers above the charts; each counts up when a new report arrives."""
    anywhere = numbers["crashes_anywhere"]
    share = numbers["crashes_near"] / anywhere * 100 if anywhere else None
    place = f"within {buffer_m()} m of housing" if filters.scope == "near" else place_text(filters)
    kind = nearest_site_text(filters)
    if filters.housing_filter_ignored:
        place += " (housing filters apply only near housing)"
    return [
        _figure(f"{numbers['crashes']:,}", filters.harm_noun.capitalize(), f"{place}, {year_text(filters)}",
                "is-crash", numbers["crashes"]),
        _figure(f"{share:.0f}%" if share is not None else "n/a",
                f"of matching crashes are within {buffer_m()} m of a housing site (completed or planned)",
                f"{numbers['crashes_near']:,} of {anywhere:,}; {kind}", "is-crash", share),
        _figure(f"{numbers['buildings']:,}", "Affordable-housing buildings completed",
                f"{numbers['buildings_unlocated']:,} without a public address", "is-housing", numbers["buildings"]),
        _figure(f"{numbers['affordable_units']:,}", "Affordable units in those buildings",
                f"of {numbers['total_units']:,} units in total", "is-housing", numbers["affordable_units"]),
    ]


def report_header(filters: Filters, numbers: dict, query: str | None, notes: list[str] | None = None) -> list:
    """Active filters as labelled chips, one sentence with the n, and any caution for this selection."""
    children = [html.Ul([html.Li([html.Span(label, className="chip-label"), value], className="chip chip-found",
                                 style={"--i": position})
                         for position, (label, value) in enumerate(chips(filters))], className="chips", **{"aria-label": "Active filters"})]
    if query:
        children.insert(0, html.P(["From your search: ", html.Q(query)], className="from-search"))
    children += [html.P(note, className="aside") for note in notes or []]
    if numbers["crashes"] == 0:
        children.append(html.Div([html.Strong("No crashes match this selection. "), _widen_hint(filters),
                                  " The housing charts below still show what was built."],
                                 className="notice notice-empty", role="status"))
    if filters.harm == "all":
        children.append(html.Div(
            [html.Strong("Counts of all reported crashes cannot be compared across 2020. "),
             "Reports of crashes without injuries fell by about half that year and kept falling, so this view "
             "reflects reporting as much as safety. Injury crashes are the default for that reason."],
            className="notice notice-caution", role="note"))
    if numbers["crashes_unknown_borough"]:
        children.append(html.P(f"{numbers['crashes_unknown_borough']:,} of the matching crashes have no "
                               "recorded borough. They count in the totals and are left out of the borough lines.",
                               className="aside"))
    return children


PANEL_BUILDERS = {
    "map": lambda store, filters, numbers: _map_panel(store, filters),
    "selection": lambda store, filters, numbers: _selection_panel(store, filters),
    "trend": lambda store, filters, numbers: _trend_panel(store, filters, numbers["crashes"]),
    "completions": lambda store, filters, numbers: _completions_panel(store, filters, numbers),
    "factors": lambda store, filters, numbers: _factors_panel(store, filters, numbers["crashes"]),
    "heatmap": lambda store, filters, numbers: _heatmap_panel(store, filters, numbers["crashes"]),
    "scatter": lambda store, filters, numbers: _scatter_panel(store, filters),
}


def pending_event_panel() -> Panel:
    """What the before and after card shows until its own callback finishes."""
    return Panel(charts.empty_figure("Working out the before and after comparison."),
                 _scope("Calculating the comparison for this selection."), ["Drawn in a moment."])


def build_main(store: Store, filters: Filters, query: str | None = None, notes: list[str] | None = None) -> dict:
    """Header, figures and every chart except the event study, whose bootstrap can take a second cold."""
    numbers = data.headline_numbers(store, filters)
    panels = {key: build(store, filters, numbers) for key, build in PANEL_BUILDERS.items()}
    return {"header": report_header(filters, numbers, query, notes), "tiles": summary_tiles(filters, numbers),
            "panels": panels, "numbers": numbers}


def build_event(store: Store, filters: Filters) -> Panel:
    return _event_panel(store, filters)


def build_report(store: Store, filters: Filters, query: str | None = None, notes: list[str] | None = None) -> dict:
    """All content for one selection: header, tiles and one `Panel` per chart key."""
    report = build_main(store, filters, query, notes)
    report["panels"]["event"] = build_event(store, filters)
    report["panels"] = {key: report["panels"][key] for key in CHART_KEYS}
    return report


CSV_HEADER = ["section", "item", "period", "value"]


def summary_csv(store: Store, filters: Filters) -> str:
    """The selection, headline figures and yearly tables as one tidy CSV, from the same functions as the charts."""
    numbers = data.headline_numbers(store, filters)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for label, value in chips(filters):
        writer.writerow(["Selection", label, "", value])
    writer.writerow(["Headline", filters.harm_noun.capitalize(), "", numbers["crashes"]])
    writer.writerow(["Headline", "Matching crashes anywhere in the city", "", numbers["crashes_anywhere"]])
    writer.writerow(["Headline", f"Matching crashes within {buffer_m()} m of a housing site", "", numbers["crashes_near"]])
    writer.writerow(["Headline", "Affordable-housing buildings completed", "", numbers["buildings"]])
    writer.writerow(["Headline", "Buildings without a public address", "", numbers["buildings_unlocated"]])
    writer.writerow(["Headline", "Affordable units", "", numbers["affordable_units"]])
    writer.writerow(["Headline", "Units in total", "", numbers["total_units"]])
    trend = data.crash_trend(store, filters)
    monthly = trend.attrs["monthly"]
    for stamp, row in trend.iterrows():
        period = stamp.strftime("%Y-%m") if monthly else int(stamp)
        for borough, count in row.items():
            writer.writerow(["Crashes by period and borough", borough, period, int(count)])
    writer.writerow(["Crashes by period and borough", "No recorded borough", "all years",
                     numbers["crashes_unknown_borough"]])
    tables = data.completions_by_year(store, filters)
    for section, table in (("Affordable units completed", tables["affordable_units"]),
                           ("Buildings completed", tables["buildings"])):
        for year, row in table.iterrows():
            for kind, count in row.items():
                writer.writerow([section, kind, int(year), int(count)])
    return out.getvalue()

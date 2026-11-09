"""The story: question, findings, limits, benefit to NYC, and how the data was made.

Every number in the text is read from app/data/results.json, meta.json or one of the exported
tables, which the data build writes from the notebook, so the site and the notebook cannot
drift apart. The wording follows the notebook: associations only, each with its interval and n.
"""
from __future__ import annotations

import re

from dash import dcc, html

from app.analysis.story_text import (
    SAME_AS_ZERO,
    finding_extras,
    findings_lead,
    interval_level_text,
    interval_text,
    number_word,
    ordinal,
    reading_label,
    robustness_text,
    signed,
    unit_digits,
    zip_level_text,
)
from app.core.data import Store
from app.core.filters import YEAR_END, YEAR_START, buffer_m
from app.core.stats import NEUTRAL_PERCENTILE, level_text
from app.ui import charts
from app.ui.theme import GRAPH_CONFIG


def _graph(graph_id: str, figure, size_class: str) -> html.Div:
    """A static story figure in a box whose height comes from CSS."""
    return html.Div(dcc.Graph(id=graph_id, figure=figure, config=GRAPH_CONFIG, responsive=True,
                              style={"height": "100%"}), className=f"graph {size_class}")


# ---------------------------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------------------------
def hero(store: Store) -> html.Section:
    """The question and the two answers that matter most."""
    rows, questions = store.meta["rows"], store.results["questions"]
    after, where = questions["RQ3"], questions["RQ7"]
    baseline = store.meta["constants"]["baseline_years"]
    one_vote = store.results["detail"]["rq7"]["one_vote"]
    return html.Section(className="hero", children=[
        html.P(f"New York City, {YEAR_START} to {YEAR_END}", className="eyebrow"),
        html.H1("Do injury crashes rise around affordable housing once it opens?"),
        html.P(f"New Yorkers sometimes ask whether a new affordable building will bring more people hurt on "
               f"nearby streets. We joined {rows['housing']:,} affordable-housing buildings to "
               f"{rows['crashes'] / 1e6:.1f} million police crash reports by distance and by ZIP code. We then "
               "compared injury crashes near completed buildings, before and after completion, with crashes near "
               "buildings not yet completed.", className="lead"),
        html.Div(className="answers", children=[
            html.Div(className="answer answer-main", children=[
                html.P([html.Span(f"{signed(after['estimate'])}%", className="answer-figure"),
                        html.Span("after against before", className="answer-unit")], className="answer-head"),
                html.P(f"Injury crashes within {buffer_m()} m of a new building changed by {signed(after['estimate'])}% in "
                       f"the three years after completion, compared with the three years before and with the same "
                       f"change at sites not yet completed. The 95% interval runs from {signed(after['low'])}% to "
                       f"{signed(after['high'])}% ({after['n']:,} sites). It includes zero, so the records are "
                       f"compatible with no change; they also allow a fall of up to about {abs(after['low']):.0f}%."),
            ]),
            html.Div(className="answer", children=[
                html.P([html.Span(f"{NEUTRAL_PERCENTILE + where['estimate']:.0f}th", className="answer-figure"),
                        html.Span("percentile before the project", className="answer-unit")],
                       className="answer-head"),
                html.P(f"Ranking every new-construction site against street points in its own borough by injury "
                       f"crashes in {baseline[0]} to {baseline[1]}, before the project started, the average site sits "
                       f"at the {NEUTRAL_PERCENTILE + where['estimate']:.0f}th percentile. A typical street point is "
                       f"at the {NEUTRAL_PERCENTILE}th (95% interval {NEUTRAL_PERCENTILE + where['low']:.0f} to "
                       f"{NEUTRAL_PERCENTILE + where['high']:.0f}, {where['n']:,} sites). Citywide the direction holds and the "
                       f"size depends on the weighting: counting each cluster of linked sites once gives the "
                       f"{ordinal(NEUTRAL_PERCENTILE + one_vote['estimate'])} percentile "
                       f"({NEUTRAL_PERCENTILE + one_vote['low']:.0f} to {NEUTRAL_PERCENTILE + one_vote['high']:.0f}, "
                       f"{one_vote['n']:,} clusters)."),
            ]),
        ]),
    ])


# ---------------------------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------------------------
def _interval_mark(low: float, estimate: float, high: float) -> html.Div:
    """A small picture of one interval against zero. Decorative: the numbers are in the text beside it."""
    reach = max(abs(low), abs(high), abs(estimate)) * 1.15

    def position(value: float) -> float:
        return 50 + 50 * value / reach

    return html.Div(className="interval", **{"aria-hidden": "true"}, children=[
        html.Span(className="interval-zero"),
        html.Span(className="interval-bar", style={"left": f"{position(low):.1f}%",
                                                   "right": f"{100 - position(high):.1f}%"}),
        html.Span(className="interval-dot", style={"left": f"{position(estimate):.1f}%"}),
    ])


# The tag under each result already says "compatible with no change"; the legend explains it once.


def _finding_row(key: str, item: dict, extra: str | None) -> html.Li:
    digits = unit_digits(item["unit"])
    reading, reading_class = reading_label(item)
    return html.Li(className="finding", children=[
        html.Div(className="finding-text", children=[
            html.H3([html.Span(key, className="finding-key"), item["question"]]),
            html.P(f"Asked by team member {item['owner']}", className="finding-owner"),
            html.P(SAME_AS_ZERO.sub("", item["sentence"])),
            html.P(extra, className="finding-extra") if extra else None,
        ]),
        html.Div(className="finding-number", children=[
            html.P([html.Span(signed(item["estimate"], digits), className="finding-estimate"),
                    html.Span(item["unit"], className="finding-unit")]),
            _interval_mark(item["low"], item["estimate"], item["high"]),
            html.P(f"{level_text(item['level'])} interval {interval_text(item, digits)}", className="finding-range"),
            html.P(f"n = {item['n']:,} {item['n_unit']}", className="finding-range"),
            html.P(reading, className=reading_class),
        ]),
    ])


def surprise_paragraphs(store: Store) -> list[html.P]:
    """The two checks made before any question: the total count, and the clusters of nearby sites."""
    questions, facts = store.results["questions"], store.results["facts"]
    largest = store.results["detail"]["largest_clusters"]
    return [
        html.P(f"Before any question, we checked how the total count behaves. Counted as all crashes, the streets "
               f"around the new buildings of RQ3 fall by {abs(facts['all_crash_change']):.0f}% after completion, and "
               "the not-yet-completed comparison sites fall by almost the same amount (the change relative to "
               f"them is {signed(facts['all_crash_difference'])}%). Counted as injury crashes the fall is "
               f"{abs(facts['injury_change']):.0f}%. Reports of crashes without injuries dropped in 2020 and have "
               "not recovered, so a before and after count of all crashes with no comparison sites would mostly "
               "have measured that change in reporting.", className="prose"),
        html.P(f"Completed buildings sit in clusters. The {largest} largest clusters of neighboring sites hold "
               f"{facts['share_in_largest']:.0f}% of the {facts['sites']:,} located buildings, and the median "
               f"building has {facts['median_neighbours']:.0f} others within {buffer_m()} m. Only {facts['treated_clean']:,} "
               f"of {facts['treated_candidates']:,} completed sites had no other completion nearby during their "
               f"window, and only {questions['RQ3']['n']:,} of those are new construction. The before and after "
               "comparison therefore describes the less dense edges of the program.", className="prose"),
    ]


def findings(store: Store) -> html.Section:
    """Ten questions, each with its estimate, interval, n and a sentence that says what it shows."""
    questions = store.results["questions"]
    extras = finding_extras(store)
    return html.Section(id="findings", className="band", children=[
        html.H2(f"{number_word(len(questions)).capitalize()} questions and what the records show"),
        html.P(findings_lead(questions), className="section-lead"),
        html.P(f"{interval_level_text(questions)} If it crosses the vertical zero line, the records are "
               "compatible with no change.", className="section-lead"),
        html.Ul([_finding_row(key, item, extras.get(key)) for key, item in questions.items()], className="findings"),
        html.H3("What surprised us", className="sub-heading"),
        *surprise_paragraphs(store),
    ])


# ---------------------------------------------------------------------------------------------
# Limits and impact
# ---------------------------------------------------------------------------------------------
def limit_items(store: Store) -> list[tuple[str, str]]:
    """(title, text) of each thing the data cannot tell us, with the size of each gap."""
    facts, limit = store.results["facts"], store.results["limits"]
    central = store.results["questions"]["RQ3"]
    # The holdout accuracy of the ZIP recovery is recorded in the cleaning log by the notebook.
    accuracy = re.search(r"holdout accuracy ([\d.]+)%", " ".join(store.cleaning_log["reason"]))
    recovery_check = "The method was tested on crashes whose ZIP code was hidden, but it is still a fill."
    if accuracy:
        recovery_check = (f"On crashes whose ZIP code was hidden for the test, the method gave the right "
                          f"code {accuracy.group(1)}% of the time, but it is still a fill.")
    items = [
        ("Associations only",
         "Housing sites are not placed at random, and nothing here is an experiment. Every result describes "
         "how two things move together in these records. None shows that housing changes crashes. A street "
         "that gets a new building may also get a bike lane, a rezoning or a rebuilt junction in the same "
         "years, and neither table records that."),
        ("Crash reporting changed in 2020",
         f"By 2025 the number of reported crashes stood at {facts['crash_index']:.0f} with 2019 as 100, while "
         f"injury crashes stood at {facts['injury_index']:.0f}. Reports without injuries collapsed, so we "
         "count injury crashes everywhere and show all crashes only as a check. The first pandemic year also "
         "falls inside every three-year window we could build."),
        ("Few clean comparisons",
         f"Only {central['n']:,} new buildings pass the screen for the before and after comparison. The "
         f"interval from {signed(central['low'])}% to {signed(central['high'])}% leaves room for a fall of up to "
         f"about {abs(central['low']):.0f}% or a rise of up to about {abs(central['high']):.0f}%. The buildings "
         "that pass are the isolated ones, so the result does not describe a project inside a dense cluster."),
        ("Street points are the benchmark",
         "The ranking of sites before construction compares them with a grid of street points. Market-rate "
         "buildings are in neither table, so we cannot say whether affordable housing stands on busier "
         "streets than other apartment buildings do."),
        ("Missing places",
         f"{limit['unlocated_share']:.1f}% of crashes have no usable coordinates "
         f"({limit['unlocated_share_first_year']:.1f}% in {YEAR_START}), and {limit['confidential_rows']:,} housing "
         f"records are confidential and have no address. Those buildings hold "
         f"{limit['confidential_unit_share']:.2f}% of the units and appear only in borough totals."),
        ("Recovered ZIP codes",
         f"{limit['imputed_zip_share']:.1f}% of the crashes in the ZIP panel carry a ZIP code recovered from "
         f"their coordinates. {recovery_check} {zip_level_text(store)} change when the "
         "recovered codes are left out. Each is marked under its finding above."),
        ("No traffic volumes",
         "We count crashes. Nothing says how many people or vehicles used a street, so a count is not a risk "
         "per trip, and a busy street can have many crashes and still be safe for each person on it."),
        ("Dates are coarse",
         f"{limit['same_day_share']:.0f}% of completed buildings report the same start and completion date. "
         "Before and after are counted in whole calendar years and the completion year is left out."),
        ("Many reports name no contributing factor",
         f"{limit['no_factor_share']:.1f}% of crash reports name no contributing factor. Factor comparisons "
         "use the reports that do, and the blank share itself changes over time."),
        ("Several tests were run",
         f"This page reports {limit['headline_intervals']} headline intervals and "
         f"{limit['robustness_intervals']} versions of the main comparison. With that many 95% intervals, some "
         "will exclude zero by chance. We adjusted inside each question and did not adjust across the project."),
    ]
    return items


def limits(store: Store) -> html.Section:
    """What the data cannot tell us, with the size of each gap."""
    items = limit_items(store)
    return html.Section(id="limits", className="band", children=[
        html.H2("What this data cannot tell us"),
        html.Div([html.Div([html.H3(title), html.P(text)], className="limit") for title, text in items],
                 className="limits"),
    ])


def impact_items(store: Store) -> list[tuple[str, str]]:
    """(who, what) for each body that could use the findings and what it would do differently."""
    after, facts = store.results["questions"]["RQ3"], store.results["facts"]
    new_sites = store.results["detail"]["rq7_new_sites"]
    items = [
        ("Department of Transportation and Vision Zero",
         f"The housing table gives each building's start date as well as its completion date, and "
         f"{new_sites['share_above_borough_median_pct']:.0f}% of the new-construction sites "
         f"({new_sites['share_clusters_above_borough_median_pct']:.0f}% of their clusters of linked sites) stood above "
         f"the median street point of their borough for injury crashes before work began (a median of "
         f"{new_sites['median_baseline_crashes']:.0f} within {buffer_m()} m over three years, against "
         f"{new_sites['median_baseline_crashes_reference']:.0f} at the median street point). That record is "
         "available when a project starts, so street redesign could be timed to finish before tenants arrive. "
         "The counts are not divided by traffic, so they mark streets where many people are hurt, not streets "
         "that are riskier per trip."),
        ("Housing Preservation and Development",
         f"Around the {after['n']:,} new-construction sites we could isolate, injury crashes within {buffer_m()} m changed "
         f"by {signed(after['estimate'])}% after completion (95% interval {interval_text(after, suffix='%')}). The "
         f"records are compatible with no change, and they also allow a fall of up to "
         f"{abs(after['low']):.0f}% or a rise of up to {abs(after['high']):.0f}%. The crash record of the street "
         "outside the future front door exists at the time of site selection and could be reviewed then. A "
         "move-in date in the housing table, separate from the project start date, would make the before and "
         "after windows more exact."),
        ("Community boards",
         f"Before a proposed new building opens, {new_sites['share_above_borough_median_pct']:.0f}% of "
         f"new-construction sites, and {new_sites['share_clusters_above_borough_median_pct']:.0f}% of their clusters, "
         "stood on streets above their borough's median for injury crashes. A board can "
         "ask for street improvements on the strength of that record, without making the request depend on the "
         "building. These results say nothing about a single corner."),
        ("Residents",
         f"Near the {facts['treated_clean']:,} completed sites we could compare, the share of injuries to "
         "pedestrians and cyclists, the time of day and the recorded cause did not detectably change after "
         "completion (new construction and preservation together). Residents can look at the crash record of "
         "the street before the building opened; these records do not test whether it predicts what follows. "
         "The crash reports cover collisions involving a motor vehicle, so harm to people outside cars may be "
         "understated."),
    ]
    return items


IMPACT_LEAD = ("The crash record of a block is known before a financed building opens on it. The people who "
               "move in arrive on a street that already had that record.")


def impact(store: Store) -> html.Section:
    """Who could use the findings, and what they would do differently."""
    items = impact_items(store)
    return html.Section(id="impact", className="band", children=[
        html.H2("What this means for the city"),
        html.P(IMPACT_LEAD, className="section-lead"),
        html.Dl([part for who, what in items for part in (html.Dt(who), html.Dd(what))], className="audiences"),
    ])


# ---------------------------------------------------------------------------------------------
# Data and method
# ---------------------------------------------------------------------------------------------
def _cleaning_table(store: Store) -> html.Div:
    log = store.cleaning_log
    head = html.Thead(html.Tr([html.Th(name, scope="col") for name in
                               ["Table", "Rule", "Action", "Rows or cells affected", "Why"]]))
    body = html.Tbody([html.Tr([html.Td(row.dataset), html.Td(row.rule), html.Td(row.action),
                                html.Td(f"{row.affected:,}", className="num"), html.Td(row.reason)])
                       for row in log.itertuples(index=False)])
    return html.Div(html.Table([html.Caption("Every cleaning rule applied in the notebook, in order"),
                                head, body], className="table"),
                    className="table-wrap", tabIndex=0, role="region", **{"aria-label": "Cleaning log"})


def join_paragraphs(store: Store) -> list[html.P]:
    """The two datasets, the two ways they are linked, and what cleaning dropped."""
    meta, rows = store.meta, store.meta["rows"]
    housing, crashes = meta["datasets"]["housing"], meta["datasets"]["crashes"]
    as_of, constants = meta["data_as_of"], meta["constants"]
    log = store.cleaning_log
    dropped = int((log["rows_before"] - log["rows_after"])[log["dataset"].isin(["housing", "crashes"])].sum())
    return [
        html.P(["Housing: ", html.A(housing["name"], href=housing["url"], target="_blank", rel="noopener"),
                f", {rows['housing']:,} buildings. Transportation: ",
                html.A(crashes["name"], href=crashes["url"], target="_blank", rel="noopener"),
                f", {rows['crashes']:,} crashes from {as_of['earliest_crash'][:4]} to "
                f"{as_of['latest_crash'][:4]}. Both come from NYC Open Data."]),
        html.P(f"We link them in two ways. A ZIP code by year panel ({rows['panel_zips']} ZIP codes, "
               f"{rows['zip_year']:,} rows) puts completed units next to crash counts. A distance join "
               f"marks every crash within {constants['buffer_m']} m of one of the {rows['sites']:,} "
               f"buildings that have coordinates. {rows['crashes_near_a_site']:,} crashes are that close "
               "to a site."),
        html.P(("No crash row and no building row was dropped in cleaning. " if dropped == 0 else
                f"{dropped:,} rows were dropped in cleaning. ") +
               "Problems are flagged or filled with a rule, and each rule is in the log below."),
    ]


def reporting_note(store: Store) -> str:
    """How to read the chart of crash reports by year, 2019 = 100."""
    facts = store.results["facts"]
    return (f"Citywide crashes per year, 2019 = 100. Reports of crashes without injuries fell sharply in "
            f"2020 and kept falling: all reported crashes stood at {facts['crash_index']:.0f} "
            f"in 2025. Injury crashes fell less and stood at "
            f"{facts['injury_index']:.0f}. A before and after comparison on all "
            "crashes would mostly measure the change in reporting.")


def robustness_chart_note(store: Store) -> str:
    """How to read the forest plot of the main result under each change of method."""
    return ("Change in injury crashes around new buildings after completion, compared with the same change at "
            f"not-yet-completed sites, in percent. The bars are 95% intervals from {store.meta['constants']['n_boot']:,} "
            "resamples of whole clusters of nearby sites. The Outcome row counts all crashes. The comparison "
            "subset rows are unadjusted cuts. Hover a row for its sites, comparison rows and clusters.")


def data_and_method(store: Store) -> html.Section:
    """The two datasets, how they were joined, what was cleaned, and the checks behind the result."""
    log = store.cleaning_log
    return html.Section(id="data", className="band", children=[
        html.H2("The data and how we joined it"),
        html.Div(className="method", children=[
            html.Div([
                html.H3("Two datasets with no shared key"),
                *join_paragraphs(store),
                html.Details([html.Summary(f"Cleaning log, {len(log)} rules"), _cleaning_table(store)]),
            ]),
            html.Div([
                html.H3("Why we count injury crashes"),
                _graph("fig-reporting", charts.reporting_break_figure(store.city_year), "graph-small"),
                html.P(reporting_note(store), className="chart-note"),
            ]),
        ]),
        html.H3("How the main result changes with our choices", className="sub-heading"),
        html.P(robustness_text(store), className="prose"),
        # A forest plot needs width for its row labels: on a phone it scrolls sideways inside its own box.
        html.Div(_graph("fig-robustness", charts.robustness_figure(store.robustness), "graph-forest"),
                 className="scroll-x", tabIndex=0, role="region",
                 **{"aria-label": "Chart of the main result under each change of method"}),
        html.P(robustness_chart_note(store), className="chart-note"),
    ])


def footer(store: Store) -> html.Footer:
    meta = store.meta
    as_of = meta["data_as_of"]
    saved = sorted(set(as_of["raw_files_saved"].values()))[-1]
    return html.Footer(className="footer", children=[
        html.P(f"Source data downloaded from NYC Open Data on {saved}. Latest crash {as_of['latest_crash']}, "
               f"latest housing completion {as_of['latest_housing_completion']}. Site data built "
               f"{meta['built_at']} from the project notebook."),
    ])

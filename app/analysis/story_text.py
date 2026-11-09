"""Sentences for the story sections: number formatting and the text built from results.json.

Kept apart from app/story.py, which lays the sections out, so wording and layout change separately.
"""
from __future__ import annotations

import re

from app.core.data import Store
from app.core.stats import level_text

MINUS = "−"


def signed(value: float, digits: int = 1) -> str:
    """'+3.3' or '−4.6' with a real minus sign."""
    text = f"{abs(value):.{digits}f}"
    if float(text) == 0:
        return text
    return ("+" if value > 0 else MINUS) + text


def interval_text(item: dict, digits: int = 1, suffix: str = "", prefix: str = "") -> str:
    """'−11.9% to +3.3%' for a dict with `low` and `high` (or `percent_low` and `percent_high`)."""
    return f"{signed(item[prefix + 'low'], digits)}{suffix} to {signed(item[prefix + 'high'], digits)}{suffix}"


def unit_digits(unit: str) -> int:
    return 3 if "correlation" in unit else 2


def ordinal(value: float) -> str:
    """'61st', '62nd', '69th' for a rounded percentile."""
    number = round(value)
    suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def number_word(count: int) -> str:
    return {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight",
            9: "nine", 10: "ten"}.get(count, str(count))


def plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else many


SAME_AS_ZERO = re.compile(r"; the interval includes zero, so the data are compatible with no difference")


def reading_label(item: dict) -> tuple[str, str]:
    """(text, CSS class) of the tag under a result: includes zero, excludes zero, or not kept and why."""
    if not item["excludes_zero"]:
        return "Compatible with no change", "tag"
    if item["kept"]:
        return "Clear of zero", "tag tag-strong"
    if item.get("excludes_zero_reported") is False:
        return "Clear of zero on all ZIP codes only, so not counted as a finding", "tag"
    return "Clear of zero, but not counted after adjusting for several tests", "tag"


def finding_extras(store: Store) -> dict[str, str]:
    """A second sentence for the questions whose headline needs a check or a caveat beside it."""
    detail = store.results["detail"]
    pretrend, rq7, reported = detail["rq3_pretrend"], detail["rq7"], detail["reported_zips"]
    by_type, threshold = detail["rq5_by_type"], detail["false_discovery_rate"]
    same_year, all_zips = reported["rq2_same_year"], reported["rq2_same_year_all_zips"]
    kept_on_reported = same_year["adjusted_p"] < threshold
    kept_on_all = all_zips["adjusted_p"] < threshold
    rq1, rq2 = reported["rq1"], detail["rq2_checks"]
    rq2_zip, rq2_new = rq2["most_influential_zip"], rq2["new_construction_stock"]
    one_vote, new_sites = rq7["one_vote"], detail["rq7_new_sites"]
    includes_zero = rq1["low"] < 0 < rq1["high"]
    new_type, preservation = by_type["New Construction"], by_type["Preservation"]
    return {
        "RQ1": f"Counting only crashes whose ZIP code was reported, the change in forecast error is "
               f"{signed(rq1['estimate'], 2)} injury crashes per ZIP per year ({interval_text(rq1, 2)}), which "
               f"{'includes' if includes_zero else 'excludes'} zero. With either version of the data, adding "
               "housing information did not improve the forecast.",
        "RQ2": f"The headline leans on one ZIP code. The stock of new-construction units alone gives "
               f"{signed(rq2_new['estimate'], 2)}% per 100 units ({interval_text(rq2_new, 2, suffix='%')}). With one ZIP "
               f"code left out in turn the slope runs from {signed(rq2['leave_one_zip_out']['low'], 2)}% to "
               f"{signed(rq2['leave_one_zip_out']['high'], 2)}%. ZIP {rq2_zip['zip']} holds "
               f"{rq2_zip['share_of_stock_variation_pct']:.0f}% of the variation in the stock and completed "
               f"{rq2_zip['units_completed']:,} affordable units, {rq2_zip['preservation_units']:,} of them "
               f"preservation, which brings no new residents. Without it the slope is "
               f"{signed(rq2_zip['estimate'], 2)}% ({interval_text(rq2_zip, 2, suffix='%')}), which "
               f"{'excludes' if rq2_zip['low'] > 0 or rq2_zip['high'] < 0 else 'includes'} zero, so we do not "
               "claim one size for this slope. "
               f"Of five timing slopes, the one for the completion year is "
               f"{signed(all_zips['estimate'], 2)}% per 100 units (the change in a ZIP's injury crashes in the "
               "year new units open, compared with that ZIP's other years). With all ZIP codes it is "
               f"{'kept' if kept_on_all else 'not kept'} after adjustment (p = {all_zips['adjusted_p']:.2f}). On "
               f"reported ZIP codes alone the adjusted p is {same_year['adjusted_p']:.2f}, "
               f"{'below' if kept_on_reported else 'above'} the {threshold} false-discovery limit, so there it is "
               f"{'kept' if kept_on_reported else 'reported and not counted as a finding'}. It is an association, "
               "not evidence that housing lowers crashes.",
        "RQ3": f"Check on the comparison: in the three years before completion the two groups already differ by "
               f"{signed(pretrend['percent_change'])}% ({signed(pretrend['percent_low'])}% to "
               f"{signed(pretrend['percent_high'])}%). The interval includes zero but runs as far as "
               f"{signed(pretrend['percent_high'], 0)}%, so this check cannot rule out a pre-existing gap of that size.",
        "RQ5": f"Against the same comparison sites, new construction changes by {signed(new_type['percent'])}% "
               f"({interval_text(new_type, suffix='%')}) and preservation by "
               f"{signed(preservation['percent'])}% ({interval_text(preservation, suffix='%')}). "
               "Preservation renovates buildings that already have residents, so a change there is not expected "
               "to come from new residents. We use it as a check.",
        "RQ7": f"The benchmark is a grid of street points across each borough, so this shows where the buildings "
               f"stand. It cannot show that affordable housing is placed on busier streets than market-rate "
               f"housing would be. Part of the gap is a difference between neighbourhoods: ranked inside their "
               f"own ZIP code, new-construction sites are {rq7['within_zip']['estimate']:.1f} percentile points "
               f"above the middle ({interval_text(rq7['within_zip'])}). All intervals resample whole clusters of "
               f"linked sites. Citywide the direction holds however sites are counted, but the size depends on the "
               f"weighting: {new_sites['largest_clusters_share_pct']:.0f}% of the sites lie in the "
               f"{number_word(new_sites['largest_clusters_shown'])} largest clusters, and counting each of the "
               f"{one_vote['n']:,} clusters once gives {signed(one_vote['estimate'], 1)} points "
               f"({interval_text(one_vote)}), with {new_sites['share_clusters_above_borough_median_pct']:.0f}% of "
               f"clusters above their borough's middle.{rq7_borough_text(detail['rq7_by_borough'])}",
        "RQ9": f"On reported ZIP codes alone the interval is {interval_text(reported['rq9'], 3)}. We treat this as a "
               "hint and do not count it as a finding.",
    }


def rq7_borough_text(by_borough: list[dict]) -> str:
    """' Counted that way the interval includes zero in the Bronx and Brooklyn (...).', from the borough rows."""
    parts = [f"{row['borough']} ({signed(row['new_one_vote_excess'])}, {signed(row['new_one_vote_low'])} to "
             f"{signed(row['new_one_vote_high'])})" for row in by_borough
             if row.get("new_one_vote_low") is not None and row["new_one_vote_low"] <= 0 <= row["new_one_vote_high"]]
    if not parts:
        return ""
    return f" Counted that way, the interval inside a borough includes zero in {' and '.join(parts)}."


def interval_level_text(questions: dict) -> str:
    """Which interval level the bars show, read from each stored result."""
    levels = sorted({item["level"] for item in questions.values()})
    if len(levels) == 1:
        return f"The bar shows the {level_text(levels[0])} interval."
    return ("Each bar shows the interval at the level printed beside it ("
            + ", ".join(level_text(level) for level in levels) + ", depending on the question).")


def zip_level_text(store: Store) -> str:
    """'Three of the ZIP-level results (RQ1, RQ2 and RQ9)', from the questions stored under reported ZIP codes."""
    keys = sorted({key.split("_")[0].upper() for key in store.results["detail"]["reported_zips"]},
                  key=lambda key: int(key[2:]))
    names = keys[0] if len(keys) == 1 else ", ".join(keys[:-1]) + " and " + keys[-1]
    return f"{number_word(len(keys)).capitalize()} of the ZIP-level results ({names})"


def findings_lead(questions: dict) -> str:
    """How many intervals include zero, which exclude it, and which of those are not kept and why."""
    excluding = [key for key, item in questions.items() if item["excludes_zero"]]
    not_kept = [key for key in excluding if not questions[key]["kept"]]
    only_all_zips = [key for key in not_kept if questions[key].get("excludes_zero_reported") is False]
    after_adjustment = [key for key in not_kept if key not in only_all_zips]
    text = (f"Each of the {number_word(len({item['owner'] for item in questions.values()}))} team members asked two questions that need both datasets; RQ1 to RQ{len(questions)} "
            f"are the question numbers used throughout this page. {len(questions) - len(excluding)} of the "
            f"{len(questions)} intervals include zero and {len(excluding)} exclude it ({', '.join(excluding)}).")
    if after_adjustment:
        text += (f" {', '.join(after_adjustment)} {plural(len(after_adjustment), 'is', 'are')} not kept after "
                 f"adjustment for the tests made with {plural(len(after_adjustment), 'it', 'them')}.")
    if only_all_zips:
        text += (f" {', '.join(only_all_zips)} {plural(len(only_all_zips), 'is', 'are')} not kept, because the "
                 "interval includes zero when only crashes with a reported ZIP code are counted.")
    if "RQ1" in only_all_zips:
        text += " RQ1 is a forecast result: adding housing data did not improve the forecast."
    if questions["RQ7"]["kept"]:
        text += (" RQ7 describes the streets before anyone moves in. Citywide its direction holds however sites "
                 "are counted, and its size depends on the weighting, as its entry below shows.")
    return text


def robustness_text(store: Store) -> str:
    """What the one-change versions show, read from their rows: the pooled versions, the cuts of the
    comparison group (which exclude zero or do not, and are never read as a fall), and the screen."""
    detail = store.results["detail"]
    table = store.robustness[store.robustness["estimate"].notna()]
    checks = table[table["kind"] == "check"]
    unscreened = set(detail["unscreened_variants"])
    is_cut = checks["check"] == detail["comparison_subset_check"]
    cuts, unscreened_rows = checks[is_cut], checks[checks["variant"].isin(unscreened)]
    pretrend = detail["comparison_subset_pretrend"]
    pooled = checks[~is_cut & ~checks["variant"].isin(unscreened)]
    excluding = checks[checks["interval_excludes_zero"]]
    text = (f"We changed one choice at a time: the radius, the outcome, the screen for nearby completions, the "
            f"cohorts, one building per project, the comparison inside boroughs, the distance that links clusters "
            f"and which comparison sites are used. {len(checks) - len(excluding)} of the {len(checks)} intervals "
            "include zero. ")
    text += (f"Across the {len(pooled)} versions that keep the screen and the whole comparison group, the intervals "
             f"run from {signed(pooled['percent_low'].min())}% to {signed(pooled['percent_high'].max())}%, and "
             f"{_how_many_exclude(pooled)}. ")
    rises = pooled[pooled["percent_change"] > 0]
    if len(rises) and (pooled["percent_change"] < 0).any():
        top = rises.loc[rises["percent_change"].idxmax()]
        text += (f"The estimate itself changes sign with the choice of sites (for example "
                 f"{signed(top['percent_change'])}% in the version \u201c{top['variant']}\u201d). ")
    if len(cuts):
        text += ("Who is in the comparison group matters. "
                 + " ".join(f"{row['variant']}: {signed(row['percent_change'])}% ({signed(row['percent_low'])}% to "
                            f"{signed(row['percent_high'])}%, {row['n_comparison_sites']:,} comparison sites)."
                            for _, row in cuts.iterrows())
                 + f" {_how_many_exclude(cuts).capitalize()}. These cuts are not adjusted for the several tries, and "
                 "the groups differ in more than start date or type, so they do not show that crashes fall after "
                 f"completion. On the first cut the years before completion already differ by "
                 f"{signed(pretrend['percent_change'])}% ({signed(pretrend['percent_low'])}% to "
                 f"{signed(pretrend['percent_high'])}%). The cuts limit how far the central result can be read as no "
                 "change: it is no change against this pooled group. ")
    excluding_unscreened = unscreened_rows[unscreened_rows["interval_excludes_zero"]]
    if len(excluding_unscreened):
        text += ("With the screen off, which admits sites with other completions close by, the interval also "
                 "excludes zero. ")
        without = table[table["variant"].str.contains("without the most influential cluster", case=False)]
        if len(without):
            row = without.iloc[0]
            text += (f"One large development carries that result: leaving its cluster out gives "
                     f"{signed(row['percent_change'])}% ({signed(row['percent_low'])}% to "
                     f"{signed(row['percent_high'])}%). ")
    overlap = detail["placebo_overlap"]
    text += (f"The placebos date each completion too early, so only later completers can enter: "
             f"{overlap['in_both']} of the {overlap['central_treated']} central sites are among their "
             f"{overlap['placebo_treated']} sites, and they say little about the rest.")
    return text.strip()


def _how_many_exclude(rows) -> str:
    """'none exclude zero', 'two exclude zero' or 'one excludes zero', from the rows' own flag."""
    count = int(rows["interval_excludes_zero"].sum())
    if count == 0:
        return "none excludes zero"
    return f"{number_word(count)} {plural(count, 'excludes', 'exclude')} zero"

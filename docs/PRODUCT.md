# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: a curious New Yorker with no statistics background who has heard that a new affordable building might make nearby streets more dangerous and wants to know whether that holds, and what it means for their own block.

One click away, each with their own path: city planners and street-safety advocates deciding where to act, journalists checking a claim, and students or course reviewers checking the method. The project is also a graded ICS 503 deliverable, due 9 November 2026.

## Product Purpose

An interactive public dashboard that answers one question with records instead of opinion: do injury crashes rise around city-financed affordable housing once it opens? Success is a reader who leaves able to say what the data shows, how sure anyone can be, and what they can look up or do next.

## Positioning

Two NYC Open Data tables that share no key are joined building by building. Each of the 7,593 located buildings is a real record the reader can find. The honest answer is that the before-and-after change cannot be told from no change, while a clear finding sits elsewhere: the sites stood on more crash-heavy streets before anything was built. The dashboard makes that uncertainty something a reader can test, rather than a footnote.

## Operating Context

Read on a phone or a laptop, often arriving from a shared link, with no training. It runs as one Python function on Vercel with cold starts and a 60 second limit, reads only pre-aggregated files in `app/data/`, and has no database or user accounts.

## Capabilities and Constraints

- Stack: Dash 3.4 and Plotly 5.24 (pinned), Flask underneath. Custom JavaScript and CSS are served from `app/assets/`, with no CDN dependencies beyond web fonts and map tiles.
- Filters: borough, years, construction type, building size, contributing factor, time of day, who was harmed, crash location. A typed search sets the same filters.
- The search box, the dropdown filters and the Generate report button stay as the explorer's main route (owner's decision, 31 October 2026). Instant views may sit alongside them, not replace them.
- Every number a reader sees comes from `app/data/`, which the data build writes from the notebook. No number is typed by hand.
- Statistical errors found in audit are fixed and rebuilt, with every changed number listed.

## Brand Commitments

Language of association, never cause: "compatible with no change", each estimate with its interval and n. Team members and their research questions stay credited. Datasets are credited to NYC Open Data, and map tiles to CARTO and OpenStreetMap. The project does not present itself as a city agency product.

The owner chose a clean, refined product dashboard over any themed look (31 October 2026). Craft bar: Linear, Stripe Dashboard, Vercel Analytics. No costume or themed metaphor; distinctiveness comes from the data and what a reader can do with it.

## Evidence on Hand

Real: 9,551 housing rows, 1,504,722 crash reports (2016 to 2025), ten research questions with intervals, 11 robustness variants, 49 cleaning-log rules, per-site baseline percentile and before-and-after counts. All in `app/data/`.

Absent, and not to be fabricated: testimonials, usage figures, endorsements, photographs of the sites, any causal claim.

## Product Principles

1. The reader's question comes first; method is always available and never in the way.
2. Uncertainty is shown as something you can see and test, not a caveat to skip.
3. Every mark is a real record, and every number can be traced to its source.
4. Interaction must change what a reader understands; motion must explain a change or it goes.
5. A link captures the view, so a finding can be shared and checked.

## Accessibility & Inclusion

Keyboard use, visible focus, screen-reader names for every control and chart summary, 4.5:1 text contrast, colour never the only channel, and `prefers-reduced-motion` honoured with all content still present. Works at 390 px wide.

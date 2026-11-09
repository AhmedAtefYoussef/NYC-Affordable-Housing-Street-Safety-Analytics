# AI use: prompts and process

AI coding assistants (Claude models from Anthropic, used through Claude Code) drafted the code and text of this project under the team's direction. The notebook and the website send nothing to a language model. This file holds what the project description asks for ("prompt used in any step") and records how the work was organised. Prompts whose text the team has are quoted in full. The others are described, and the description says so.

## 1. The first requests

The first prompt came with the project description and the data catalogue. It asked the assistant to analyse both, to compare the available Claude models, to split the work among several assistants with one responsibility each, and to audit the result against the requirements of the project description. Its text is not available word for word, so it is described here and not quoted.

The follow-up in the same conversation was:

> apply these skills as necessarily as possible: 21st-ui, design-motion-principles, design-taste-frontend, humanizer, impeccable, ui-ux-pro-max

A team of five members and a light, editorial look for the website were decided in the same conversation.

## 2. Versions of the work

**First version.** A file-based pipeline (`pipeline/`), an analysis package (`analysis/`), a Dash site and a notebook generator. An orchestrating session wrote a specification, an adversarial reviewer attacked it, implementers wrote the code against it, and an auditor checked the result against the project description. The sandbox it ran in could not reach NYC Open Data, so it was tested only on synthetic data. That version was removed from the repository once the rebuild replaced it; it remains in the first commit of the git history. Its steps were handled by one assistant each, with a brief that had the same parts: a role, the files to read, the files the assistant could edit, the task, the quality bar and the form of the report. The full briefs are in the session transcript, not in this repository.

| Step | Model | Role in the brief | Task |
|---|---|---|---|
| Spec review | Opus 5.5 | Adversarial architect | Find defects in the written specification: event-study design, exposure flag, imputation leakage, paging, memory, gaps in the contract. Numbered findings with severity and exact fix text |
| Analysis and app | Sonnet 5.5 | Dash engineer and designer | Ten research-question functions, the Dash website, the search parser, the design brief |
| Notebook and docs | Sonnet 5.5 | Technical writer | Notebook builder, README, methodology, data dictionary |
| Final audit | Opus 5.5 | Independent auditor | Check every requirement in the project description against the repository, requirement by requirement |

**Second version.** Built after the datasets could be downloaded, around one rule: the notebook is the source of truth, and everything else is derived from the same code. The request that started it, with the project description and the data catalogue attached:

> Reverse engineer the entirety of the codebase in terms of architecture, technical code implementation, documentation and the finalized notebook deliverable. Apply a structural dynamic workflow incorporating multiple sub agents with their respective tasks concurrently, allowing the each subagent to effectively and productively focus on one specific task at a time. For example, a subagent is responsible for code literacy and syntax, another is responsible for logical reasoning and developing the best possible strategies to counteract potential problems in all aspects, etc. The structural workflow should allow each subagent to complete their respective tasks concurrently with maximum level of precision, accuracy and efficiency with the least possible token consumption. Finally, apply all of the necessary plugins, skills, etc. You may research through the Claude chat regarding this project to maximize your knowledge, intel, etc. Finally, the finalized version of the notebook should be perfect in all the aspects such as modularization, code organization, documentation, architecture in addition to coordinating a sub agent that checks whether the finalized notebook satisfies all of the requirements from the project description. Also, use the best datasets from the data catalog folder and I need the notebook to run independently without needing external folders or files, just both of the datasets used. Apply the best skills I have here such as humanizer, impeccable, design-motion-principle, etc. Go all out. Make no mistake.

The same conversation contained three further prompts, and the two-word prompt "Try again" was sent twice.

> Build high quality top notch interactive web application according to the project requirements and specification by incorporating these skills as well; /humanizer

> and these skills as well /anthropic-skills:impeccable /anthropic-skills:design-motion-principles /anthropic-skills:design-taste-frontend /anthropic-skills:ui-ux-pro-max

> While you are continuing building this project, I need you to cut down the token usage by incorporating cheaper models for simpler tasks. For example, allow Claude opus 5.5 to execute and perform the complex tasks while sonnet 5.5 is responsible for code syntax and literacy. Basically apply the structural workflow, maintaining the quality and productivity of the work productivity and effectiveness overall while cutting down token usage in a strategic approach.

After a usage limit interrupted the work, the request was "I hit my usage limit while you were working, but it has reset now. Please continue from where you left off." The records kept in the repository do not show which model handled each task of the second version.

How the second version was built:

1. One assistant per notebook section. The notebook was split into section files in `tools/notebook_src/`, each with one author who could edit only that file. All authors received the same brief (section 3 below).
2. Run on the real data. Each author executed their section, with the sections it depends on, through `tools/assemble_notebook.py` and looked at the figures before handing it in. Authors reported the objects and numbers later sections could rely on, and the points where they deviated from the brief.
3. Review from several points of view. Further assistants read the executed notebook, each for one concern: the requirements, the code, the statistics, the prose and the charts. They returned findings with a location, a severity, the problem and a fix, and did not edit the notebook.
4. Fix passes. The section authors applied the findings. In the largest pass, 54 of 57 findings on one group of sections were applied. Some changed results: the RQ7 headline was restricted to new construction, two comparisons (inside cohort and borough, and on reported ZIP codes only) were added to the robustness section, and the RQ8 and RQ10 intervals were widened for the number of tests.
5. The website. A separate assistant rebuilt the site so that it reads only `app/data/`, which `tools/build_app_data.py` produces by running the notebook sections. A second assistant did a design and motion pass over the style files without touching the layout or the callbacks. The assistant that rebuilt the site also wrote the first tests.
6. Documents. The README and `docs/` were brought in line with the final state, with every figure checked against `app/data/` or the section sources.

**Third version: the lean-pipeline refactor (branch `refactor/lean-pipeline`).** The notebook source went from about 11,200 to about 5,000 lines (220 cells in the executed notebook), the statistics moved to one file, and the website data was rebuilt. The process:

1. Five parallel read-only auditors, each reporting findings and none editing: the data pipeline and the statistics (two auditors, Opus), the EDA and bulk of the notebook, the dashboard, and the documents (three auditors, Sonnet).
2. Six writers, each with single-file or single-area ownership, working against a frozen interface contract (the names and shapes of the objects that sections hand to one another). Their runs on the real data went through a serialised dev-run harness, so only one writer ran the notebook at a time (`assemble_notebook.py` can build from another source folder and write to another file for this). Opus wrote the data and statistics sections; Sonnet wrote the EDA, the dashboard and the documents.
   The six writers: (W1, Opus) Sections 2 and 4, data loading and cleaning; (W2, Opus) Sections 5 and 6, integration and post-integration cleaning; (W3, Sonnet) the title and Section 3, the exploration; (W4, Opus) Section 7, RQ1 to RQ5 and `app/stats.py`; (W5, Opus) RQ6 to RQ10, Section 9 and the story sections; (W6, Sonnet) the website code and its tests. The orchestrating session wrote the shared helpers in Section 1, the notebook builder and the data build changes, and integrated the parts. A Sonnet writer then brought the README and these documents in line with the rebuilt data.
3. An Opus review of the result, whose findings (stale section references, one unsupported sentence, a name reused with another meaning, dead code) a Sonnet writer applied.
4. The rule behind the split: reasoning-heavy work (method design, statistics, the interface contract, the final review) went to the stronger model, and mechanical work (syntax, prose, charts, tests) to the cheaper one. Deterministic checks (the data dictionary against the parquet files, the test suite, the build-time reproduction of RQ3 and RQ7) were scripts, not model judgement.

**Fourth phase: hardening, the one-page dashboard and verification (31 October to 1 November 2026).** The request asked for a full analysis of the codebase, a strategy for every gap found, validation through several methods, and a rebuilt interactive dashboard, with subagents working concurrently and models routed by task: Opus for complex reasoning and architectural decisions, Sonnet for code and syntax, Haiku for repetitive tasks. The process:

1. An orchestrating session audited the repository and planned two waves of parallel work. Each worker ran in its own git worktree and branch with a bounded brief and its own files, and the orchestrator merged a branch only after its checks passed. The commit tags record the waves: `[t1]` statistical and labelling corrections with a rebuild of the notebook and data, `[t2]` server hardening, statistics and hardening tests, ruff and a coverage floor in CI, `[t3]` an atomic, checked data export with the schema verified at start-up; then `[n2]` the Your block and Test it tools, `[n3]` the explorer and Generate report, `[n4]` Findings and Method. The orchestrator built the shared page shell, design tokens and the opening story between the waves. The records kept in the repository do not show which model handled each task of this phase.
2. Design rounds on the dashboard followed, each from a short request by the project lead and each done by one session: the scroll story of particles, the colour and type system, the workbench layouts for the two tools, the in-page picker and balanced controls, the page icon. Every round was checked in a headless browser at desktop and phone widths before it was committed, and performance work was measured (frame timing before and after) rather than assumed.
3. A production incident, the page failing with "A function needed by this page temporarily failed", was diagnosed from the Vercel runtime logs (packages over the 500 MB function limit, installed at each cold start into a disk that filled up), reproduced locally in the exact deployed configuration, fixed by reading the data with fastparquet and pinning every package, and confirmed on a Vercel preview before merging.
4. A final verification compared the three parts against each other: a rebuild of `app/data` from the raw files, the notebook's stored results against `results.json`, the site against raw recounts under 40 seeded random queries, timing of every interactive path, and a click-through of the rebuilt site. It found that RQ7 depended on how a library broke distance ties between crashes at the same coordinates; the fix, the rebuild and the moved numbers are in `docs/NUMBER_CHANGES.md`.

What the refactor changed in the method is listed in `docs/METHODOLOGY.md`: crashes at 0:00 flagged as unknown time, ZIP recovery tested on a holdout of whole locations, repeated buildings counted once, resampling of linked site clusters in RQ7, and robustness rows for the 2019 cohort and one building per project.

### Repository restructure (9 November 2026)

A final session reorganised the repository without changing any result. The project lead's request, as given:

> Comprehensively analyze the attached project description and begin refining the project according to the following;
> 1. Upgrade the repository architectural layout, enhancing the pipeline's modularity and organization. Also, emphasize both maintainability and extensibility aspects in order to enhance & facilitate the process of refactoring and extending the pipeline with additional features in the future.
> 2. Clean the repository end to end, identify any stale work-trees and clean them. Basically, I want the repository to be clean and has strong foundations.
> 3. Upgrade the README file to become more documentative and demonstrate the repository accurately & precisely. Refine the README file so it becomes even more attractive for Job recruiters.

The session asked four questions before starting (how deep to restructure, what to do with the orphaned worktrees and the old remote branches, how to deliver) and then: moved `tools/` into the `pipeline/` package with one command line, split the data build by stage, split `app/` into the `core`, `analysis` and `ui` layers with a test that enforces their order, removed eleven stale worktrees and the merged branches, and rewrote the README and `docs/ARCHITECTURE.md`. A full data rebuild reproduced every table exactly. Paths written earlier in this file (`tools/notebook_src/`, `tools/assemble_notebook.py`, `tools/build_app_data.py`, `app/stats.py`) are the layout of the time; they are now `pipeline/notebook/sections/`, `python -m pipeline notebook`, `python -m pipeline data` and `app/core/stats.py`.

## 3. The shared brief for the section authors

Each notebook section was drafted by a separate assistant from one shared brief. The passages that set the content of the notebook are quoted here. Passages that only name working folders and build commands are left out.

> Datasets: H2 Affordable Housing Production by Building (hg8x-zxpr) and T4 Motor Vehicle Collisions - Crashes (h9gi-nx95). Crashes are a filtered copy: 2016-01-01 to 2025-12-31 and 19 of 29 columns.

> Crash reporting broke in 2020: total crashes halve (211k in 2019, 113k in 2020, 86k in 2025) while injuries stay near 50-60k a year, because property-damage-only reports collapsed. So the PRIMARY OUTCOME everywhere is the **injury crash** (a crash with at least one person injured or killed). All-crash counts appear only in EDA and as a robustness check. Say this plainly wherever a time comparison is made.

> Two integration levels, both justified in the text: (a) ZIP x year panel; (b) spatial proximity, a crash is "near" a building if within `BUFFER_M` = 250 m (haversine BallTree). No row-level key join exists or is faked.

> Charts: matplotlib/seaborn only, static, no plotly, no map tiles, no network at view time. Use `PALETTE`, `BOROUGH_COLORS`, `finish()`. Every chart has a title that states what it shows, axis labels with units, a legend when there is more than one series, and a labelled log axis when a log axis is used. One figure per code cell, followed by a markdown or `say()` reading of it. Pick the chart type for the question; no pie charts, no 3D, no dual axes.

> Small named functions with docstrings; descriptive names (`housing_clean`, not `h2` or `df1`); no one-letter frames; no semicolon-joined statements; no magic numbers (name them); no dead code; no try/except that hides errors.

> Comment the non-obvious logic (outlier rule, spatial index, imputation, bootstrap, difference-in-differences), explaining why, not restating the line.

> Add `assert` checks for every invariant you claim (row conservation, uniqueness, no negative counts).

> A markdown cell before every code block says what is about to be done and why. After the output, the reading of it. For every cleaning or design decision: the problem as observed in THIS data, the decision (drop, impute, flag, standardise), why, and the alternative considered and why it was rejected.

> Never type a data-derived number into markdown. Numbers that come from the data are printed by code, using `say(f"...")` for sentences. Markdown carries the reasoning; it may state design constants and qualitative conclusions that you have verified in the executed output.

> No claim of causation anywhere. This is observational data: say "is associated with", "coincides with", "differs from". State n and uncertainty with each result.

The brief also listed the ten research questions with their owners, in the wording of the team table at the top of the notebook.

## 4. Prompt patterns

- Sections marked with XML-style tags (role, context, ownership, task, output format), one responsibility and one set of editable files per assistant, and a cap on the length of each report.
- A shared brief for parallel authors, with rules that can be checked: no data-derived number typed into text, an assertion for every invariant, one figure per cell, no claim of cause.
- Ownership boundaries: each assistant edits only its own file, so parallel work does not collide and responsibility is traceable.
- Reviewers and auditors who read but cannot edit what they judge, and a fixed shape for their findings (location, severity, problem, fix).
- Execution before acceptance: nothing counts as finished until it has run on the real data and its figures have been looked at.
- Reports from authors that state the interface they provide and anything left unresolved.
- Model tiering: the stronger model for design, statistics and review, the cheaper one for routine code, prose and tests.

## 5. Prompts inside the product

None. The notebook and the website make no model calls.

## 6. What this process does not cover

- Load testing of the deployed site. It runs at https://data-engineering-visualization-proj-three.vercel.app/. A cold start was measured in the deployed configuration (about a second and about 300 MB) and the interactive paths were timed in-process, but no test has measured how it behaves under many simultaneous visitors.
- The stored outputs of the committed notebook are a snapshot. Rebuild with `python -m pipeline notebook --execute` after any change to a section file, and rebuild the website data with `python -m pipeline data`.
- Whether each student has read and can explain their parts. The code and text were drafted by AI assistants under the team's direction, and members remain responsible for understanding, running and checking what they submit. Nothing in this repository records that any student has done the checks below.

### Checks each member should do before submission

| Member | To verify |
|---|---|
| M1 Ahmed Atef | Run the notebook from the top and read Sections 2 and 4.1 to 4.6. Read the RQ1 and RQ2 code and be able to explain why RQ1's interval leaves out the uncertainty of fitting. Open the deployed site in a private window. |
| M2 Nour Mostafa Aly | Read the ball tree code and its brute-force check, and the RQ3 code in Section 8.3 with the difference-in-differences function in Section 7. Check the event-study card on the site against the notebook. |
| M3 Yahia Mohamed | Read the cluster and screen logic (5.4) and explain how the screen changes the sample. Try ten phrases in the search box and confirm that search only sets filters. Read Section 9. |
| M4 Moaz Ahmed | Read the ZIP recovery and its holdout validation (6.1), and the RQ7 code in Section 8.7 and why its benchmark is street points and not other housing. Check the map and heat map at phone width. Confirm `pyproject.toml`, `vercel.json`, `.vercelignore` and `requirements.txt`. |
| M5 Yassin Fady | Run `python -m pipeline data` and `python -m pytest -q tests`. Read the cleaning log and Sections 10 to 14 for numbers that do not match the executed outputs. Read this file for accuracy. Deploy on Vercel and test the address. |

Each member should also keep a short list of the commits or pull requests they wrote (with links), the research questions they own and can explain, and anything they ran or checked. Questions in the evaluation can target any part of the notebook, so every member should be able to explain the cleaning and integration decisions, including those they did not write.

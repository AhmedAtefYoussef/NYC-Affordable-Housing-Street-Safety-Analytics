# %% [markdown]
# # Affordable housing and street safety in New York City
#
# ICS 503 Data Engineering and Visualization, Winter Semester 2026, Project Milestone 1
#
# ## Abstract
#
# Do the crash records support the worry that new affordable housing makes nearby streets less safe? We join two NYC Open Data tables that share no key: Affordable Housing Production by Building (every city-financed building since 2014) and Motor Vehicle Collisions - Crashes (here 2016 to 2025). They are joined two ways, by ZIP code and year and by distance (crashes within 250 m of a building). The outcome is the injury crash, because reporting of crashes without injuries changed sharply in 2020 for reasons unrelated to housing. As associations, not effects: sites already stood, before construction, on streets with more injury crashes than typical street points of their borough, and after completion the change near the new buildings we could isolate cannot be told from no change once not-yet-completed sites are accounted for. Sites are not placed at random and only part of the programme could be isolated, so no result is causal.
#
# ## Team
#
# The label in the first column is the one used under each question heading in Section 8.
#
# | Member | Name | Student ID | Research questions |
# |---|---|---|---|
# | M1 | Ahmed Atef | 16007032 | RQ1 Do housing completions improve a forecast of a ZIP code's injury crashes? RQ2 Do injury crashes in a ZIP code move as its stock of affordable units grows? |
# | M2 | Nour Mostafa Aly | 16001618 | RQ3 Do injury crashes within 250 m of a new building change after completion? RQ4 Does that change grow with the size of the building? |
# | M3 | Yahia Mohamed | 16004934 | RQ5 Is the change different for new construction than for preservation? RQ6 Does the pedestrian and cyclist share of injury crashes change after completion, by borough? |
# | M4 | Moaz Ahmed | 16003110 | RQ7 Before the project starts, are the sites already on streets with more injury crashes than typical street locations of the borough? RQ8 Does the hour-of-day mix of injury crashes shift after completion? |
# | M5 | Yassin Fady | 16005869 | RQ9 Is the share of deeply affordable units in a ZIP code associated with crash severity or the pedestrian and cyclist share of harm? RQ10 Which contributing-factor groups are over- or under-represented near completed housing? |
#
# ## The two datasets
#
# | Domain | Dataset | Page | API |
# |---|---|---|---|
# | Housing & Development | Affordable Housing Production by Building (`hg8x-zxpr`) | https://data.cityofnewyork.us/d/hg8x-zxpr | https://data.cityofnewyork.us/resource/hg8x-zxpr.csv |
# | Transportation | Motor Vehicle Collisions - Crashes (`h9gi-nx95`) | https://data.cityofnewyork.us/d/h9gi-nx95 | https://data.cityofnewyork.us/resource/h9gi-nx95.csv |
#
# ## Where each requirement is met
#
# | Requirement | Section |
# |---|---|
# | Loading through the Open Data API, overview, selection reasoning, feasibility, known issues | 2 Data |
# | Exploratory data analysis with statistics and plots | 3 EDA |
# | Pre-integration cleaning: missing values, outliers, inconsistencies, formats, duplicates, cleaning log | 4 Cleaning |
# | Integration: join key, granularity and aggregation, with reasons | 5 Integration |
# | Post-integration cleaning: new missing values, redundant columns, types, conservation checks | 6 Post-integration cleaning |
# | Statistics functions used by the questions, with a self-test | 7 Toolkit |
# | Ten research questions, one chart each, with the owner named | 8 Research questions |
# | Robustness of the main comparison and of the ZIP-level results | 9 Robustness |
# | Discovery, limits, impact, individual contributions, how to run | 10 to 14 Findings, limits, impact, contributions, reproducibility |
# | Prompts and AI use | final section |

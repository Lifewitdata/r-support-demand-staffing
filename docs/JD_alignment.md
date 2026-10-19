# How the project maps to an Uber Data Analytics role

| Job responsibility | Evidence in this project |
|---|---|
| Automated reports and a single source of truth | One R pipeline builds the hourly operations table, forecast bundle, dashboard snapshot and weekly brief from documented source grains. |
| Statistical modelling and operational weaknesses | Seasonal count regression and a weekly baseline, rolling-origin validation, empirical interval calibration and hourly capacity gaps. |
| Business deep dives and clear narratives | Workload decomposition separates volume and handling-time contributions; the generated brief explains the trade-off and next action in plain language. |
| Statistical tools for operational decisions | Shiny controls expose demand, handling time, shrinkage, occupancy, opening backlog and extra staffing. Missing inputs stop the calculation. |
| Measure process/policy impact | The planner supports hypothetical handling-time scenarios. It does not estimate causal policy impact. |
| Reusable technical practices and handoff | Modular R functions, input contracts, boundary tests, a metric dictionary and an analyst handoff guide. These are artifacts, not a claim of having mentored a team. |
| Competing stakeholder priorities | The brief explains staffing workload, service pressure and uncertainty. It supports a discussion; it does not claim real stakeholder delivery. |
| R and data manipulation | Base R statistical modelling and data.table transformations; no Python or SQL is used here. |
| Visualisation | ggplot2 charts and an interactive Shiny app. Tableau or Looker experience is not demonstrated by this project. |
| AI-related data work | AI assisted drafting and debugging. Validation checks and limitations are documented; no AI-generated operational advice is presented as verified evidence. |

The role also asks for SQL and hands-on Python. This project deliberately focuses on R and Shiny, so it does not demonstrate those skills. It does not substitute for actual stakeholder-management experience or the role's experience threshold.

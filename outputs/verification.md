# Verification of the delivered build

The current outputs were built in R 4.6.0 on Windows with data.table 1.18.4, ggplot2 4.0.3 and Shiny 1.14.0. See package_versions.csv and session_info.txt for recorded versions. An earlier build in R 4.3.3 on Linux produced the same tickets, model choices, staffing summary and weekly brief; forecast values differed only at floating-point precision (about 1e-14).

- Generated and analysed 496,203 synthetic tickets across 182 days and three queues.
- Built a complete grid of 13,104 queue-hours. Ticket counts and handling workload reconcile to the raw data.
- All 18 source-data checks passed.
- Compared two methods using earlier chronological validation; calibrated intervals on separate later weeks; evaluated frozen model choices across three held-out weeks.
- Seasonal regression was selected for all three queues. Held-out WAPE was 15.6% for Fare questions, 17.5% for Payment issues and 18.8% for Account support. The respective weekly baseline WAPEs were 20.9%, 23.8% and 26.3%.
- Observed held-out band coverage ranged from 89.9% to 92.1%, against a 90% target. This is a measured diagnostic, not a guarantee of future coverage.
- All 28 checks in tests/run_tests.R passed. They cover data reconciliation, time boundaries, model selection, forecast completeness, missing schedules, backlog arithmetic, scenario monotonicity, report wording, ISO timestamps in CSV exports, the HTML report header and the root application entrypoint.
- Shiny's testServer exercised queue selection, demand changes, zero shrinkage and zero additional agents. Tables, KPI cards and all five chart outputs were evaluated.
- Forecast, workload-driver and staffing-gap PNGs were visually inspected.
- scripts/explore_data.R was executed; its output is saved in eda_findings.txt.

## Scope of validation

This is a local R and Shiny server-level check, not a browser screenshot test, load test or hosted deployment. The app has not been published. No live support platform, real policy change or actual business saving is claimed.

The project contains no Python or SQL implementation. Data generation, modelling, analysis, charts, reports and the application all use R.

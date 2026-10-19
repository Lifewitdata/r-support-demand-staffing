# Methods and time boundaries

## Source design

The simulation covers 182 consecutive days from Monday 5 January 2026 in UTC. Each ticket has one queue, an arrival timestamp and required handling minutes. Counts follow a negative-binomial process with daily peaks, weekly seasonality and gradual growth. Payment issues have an isolated demand incident and a later increase in handling work. Those are planted assumptions, not findings about Uber.

A paid-headcount schedule is generated independently of the realised ticket draws, using a planned calendar profile with anticipated growth and an 8% reserve. Future scheduled headcount repeats the last available weekly schedule. No real employees or personal data are represented.

The hourly table uses a complete time-by-queue grid. Zero-demand hours are retained. Workload is the sum of ticket handling minutes, not elapsed case duration. Weighted handling time is total handling work divided by ticket count; averaging hourly averages would give the wrong weights.

## Models and split

Candidate methods are a weekly seasonal naive forecast and quasi-Poisson regression with log link. The regression has weekday factors, three daily sine/cosine pairs and a linear day trend. Future calendar features are known at forecast time. No future outcomes, incident flags or generated true rates are supplied to the models.

- Model selection: train through weeks 18, 19 and 20; predict each following week.
- Band calibration: train through weeks 21 and 22; predict each following week with the selected method.
- Held-out evaluation: train through weeks 23, 24 and 25; predict each following week. Selection remains unchanged.
- Production forecast: refit the chosen method using all 26 observed weeks, then predict week 27.

Later test origins are allowed to use earlier test outcomes because these would be observed at that later weekly refresh. They never use outcomes from their own forecast horizon. This is rolling-origin evaluation, not three forecasts frozen at one date.

Selection uses WAPE aggregated across the earlier validation windows, separately per queue. Both candidate methods are also reported on later test weeks for transparency, but these scores do not alter the chosen method. Quasi-Poisson regression models the conditional mean; the default GLM standard errors are not used as prediction intervals.

## Empirical uncertainty

Calibration scores are abs(actual − forecast) / sqrt(max(forecast, 1)). The radius is the finite-sample adjusted empirical quantile at the configured target. Future bands use forecast ± radius × sqrt(max(forecast, 1)), with the lower end clipped at zero. The same fixed calibration radius is used for the held-out evaluation. The app reports coverage and band width.

Serial dependence, changing incident rates and extrapolated trends weaken exchangeability. Treat these as approximate empirical bands, not distribution-free coverage guarantees. The upper-band staffing option is a stress scenario, not a joint 90% probability that staffing covers every hour.

## Capacity and backlog

Productive capacity minutes = paid agents × 60 × (1 − shrinkage) × occupancy. Shrinkage represents unavailable paid time; occupancy reserves room within available time instead of treating every minute as handling time. Inputs are explicit assumptions.

Historical backlog follows max(0, previous backlog + arriving workload − productive capacity), starting from zero at the simulation boundary. It is a fluid workload approximation with fully fungible work inside a queue. Work is not pooled between queues. It does not model queueing-time distributions, priorities, abandonments or individual agents.

For future staffing requirements, opening workload is distributed over the selected clearance period and added to incoming workload. Required paid headcount is rounded up each hour. The projected-backlog path independently carries the actual opening workload through the proposed schedule; backlog is not counted twice. If the clearance period exceeds the horizon, only the corresponding fraction is allocated inside the horizon.

## Workload deep dive

The latest week's workload is compared with the previous four weeks' average weekly workload. With counts N and weighted handling time A, the change N1 A1 − N0 A0 is split symmetrically:

- Volume contribution: (N1 − N0) × (A1 + A0) / 2.
- Handling contribution: (A1 − A0) × (N1 + N0) / 2.

These add exactly to the workload change. They describe accounting contributions, not causal effects. Available-capacity change is shown separately.

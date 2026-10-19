# Limits to state clearly

- The full dataset is synthetic; patterns and incidents were generated deliberately. Findings are evidence about the scenario, not about Uber.
- Forecasts assume the historical demand structure remains useful next week. Unknown incidents, product launches and structural changes can break that assumption.
- Calibrated bands are approximate under dependent, changing time series. Report observed held-out coverage, not just a target percentage.
- The staffing model treats work as fluid and staff as interchangeable within each queue. It does not simulate individual tickets or agents, skill routing, prioritisation or queue abandonment.
- No SLA, measured customer waiting time, causal process impact, hiring requirement or realised cost saving is calculated.
- A handling-time scenario changes assumed work per ticket. It is not a prediction of what a new policy will achieve.
- Paid agent-hours cannot be directly translated into full-time hires without a shift and contract model.
- The prepared app is a batch snapshot, not a live stream. Scheduled refresh instructions are provided; no recurring job is activated.
- The default generator rebuilds the same seeded demonstration. Real operational use requires a real ingestion layer, data access controls and review of the assumptions.
- No Tableau, Looker, Python, SQL or Google Apps Script is used in this project. This is intentional: it focuses on R and Shiny.
- AI assisted the project build and documentation. Numerical outputs come from executed R code, with data-contract, temporal-boundary and reactive-server checks. No model-generated narrative is treated as evidence without its calculated inputs.

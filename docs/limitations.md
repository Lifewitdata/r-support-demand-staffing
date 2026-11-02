# Project limitations and interpretation

This repository contains two independent analytics implementations: an R/Shiny support-demand and staffing planner, and an optional Python/DuckDB/SQL conversational-commerce analytics layer. Their datasets are synthetic and their outputs are scenario evidence, not claims about Uber or any real employer. Component-specific setup and limitations are documented in the [root README](../README.md) and [Python README](../python/README.md).

## R/Shiny component

- Forecasts assume the historical demand structure remains useful next week. Unknown incidents, product launches and structural changes can break that assumption.
- Calibrated forecast bands are approximate under dependent, changing time series. Report observed held-out coverage, not just a target percentage.
- The staffing model treats work as fluid and staff as interchangeable within each queue. It does not simulate individual tickets or agents, skill routing, prioritisation or queue abandonment.
- No SLA, measured customer waiting time, causal process impact, hiring requirement or realised cost saving is calculated.
- A handling-time scenario changes assumed work per ticket. It is not a prediction of what a new policy will achieve.
- Paid agent-hours cannot be translated directly into full-time hires without a shift and contract model.
- The prepared Shiny app is a batch snapshot, not a live stream. Re-running the pipeline regenerates the seeded synthetic demonstration; it does not ingest a production feed.

## Python/DuckDB/SQL component

- Generated conversations, schedules and events are synthetic. The REST adapter is configurable but is not a verified connection to a real provider account.
- The Streamlit interface is a read-only analytics question-and-answer front end over the local DuckDB database. It is not a hosted public dashboard, and Groq explanations require a separately configured API key.
- Forecast event flags assume the supplied calendar was known at forecast time. Synthetic random event labels do not demonstrate useful predictive signal.
- Staffing coverage, risk thresholds and cost estimates are illustrative planning scenarios, not contractual SLAs, measured lost revenue or realised savings.
- Employee-level shift assignment is a greedy heuristic, not a globally optimal schedule or a substitute for validating contracts, certifications, preferences and local labour rules.
- Descriptive workload decomposition is arithmetic and associational; it does not establish causation.
- Optional AI-generated explanations are constrained to retrieved database facts, but they are not independent evidence. Review the underlying query results and caveats.

## Shared limitations

- No Tableau workbook or published Tableau dashboard is included. The Python pipeline produces Tableau-ready CSV extracts only.
- Neither app is connected to a live operational platform by default. Production use requires approved ingestion, data access controls, monitoring, privacy review and operational validation.
- The project demonstrates technical analysis and reproducibility; it does not claim stakeholder management, production deployment, measured process impact or business savings that have not been independently demonstrated.
- AI assisted parts of the project build and documentation. Numerical outputs should be judged from executable code, tests and source data, not generated narrative.

# Data and metric dictionary

| Dataset | Grain | Fields |
|---|---|---|
| tickets.rds | One synthetic ticket | ticket_id, queue, arrived_at (UTC), handling_minutes (required work) |
| hourly_schedule.rds | Queue × hour | timestamp, queue, scheduled_agents (paid concurrent headcount) |
| future_schedule.csv | Queue × future hour | Same schedule fields, covering exactly the next 168 hours |
| hourly_operations.rds | Queue × hour | Arrival count, handling workload, weighted AHT, headcount, capacity, modelled opening/closing backlog and calendar fields |
| forecast_bundle.rds | Collection of analytical tables | Selection scores, chosen methods, holdout scores, calibration radii, coverage, held-out predictions and final forecast |
| app_bundle.rds | Completed app snapshot | Hourly operations, forecast bundle, future schedule, settings and data-quality results |

| Metric | Definition / unit |
|---|---|
| Arrivals | Number of tickets opening within [hour start, next hour start) |
| Handling time | Sum of required handling minutes / ticket count; weighted across the selected period |
| Workload | Sum of required handling minutes; divide by 60 for workload hours |
| Capacity | Paid headcount × 60 × (1 − shrinkage) × occupancy, in minutes |
| Workload / capacity | Total workload divided by total productive capacity; not measured agent occupancy |
| Closing backlog | Modelled unserved handling workload after that hour; not customer count or wait time |
| MAE | Mean absolute hourly forecast error, tickets |
| RMSE | Square root of mean squared hourly error, tickets |
| WAPE | Sum of absolute errors / sum of actual arrivals; undefined when all actual arrivals are zero |
| Bias | Mean forecast minus actual; positive means overforecasting |
| Band coverage | Share of held-out hours whose arrivals lie inside the empirical band |
| Required agents | Rounded-up paid concurrent headcount needed for incoming and allocated backlog work |
| Uncovered agent-hours | Sum of max(required − scheduled, 0) over hourly rows; not unique people or hires |
| Peak gap | Largest hourly gap for an individual queue; the app does not claim it is a global simultaneous peak |

Missing required fields, duplicate keys, invalid values or incomplete future hours stop the relevant calculation. The planner does not treat missing data as spare capacity.

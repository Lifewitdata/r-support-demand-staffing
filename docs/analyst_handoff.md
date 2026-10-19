# Analyst handoff

Start with the weekly brief, then use the dashboard to challenge its assumptions.

1. Check data coverage before interpreting a gap. Every queue needs a complete hourly grid; zero demand and missing data are different.
2. Ask whether demand, handling work or scheduled capacity changed. Use the decomposition to narrow the question, then inspect case-level reasons in a real system.
3. Compare the selected model with the weekly baseline on later weeks. A more complicated method is not automatically more useful.
4. Check interval coverage. Undercoverage means the nominal target should not be treated as reliable protection.
5. Ask operations to confirm shrinkage, occupancy, agent skills and the proposed schedule. Do not substitute an average from this simulation for a real staffing assumption.
6. Compare a targeted staffing response with a plausible process change. A handling-time reduction in the app is hypothetical; measure actual changes in a separate experiment before claiming savings.
7. Present the queue, time window, workload gap, uncertainty and next action. Never report agent-hours as a number of hires.

## Maintenance practices

- Keep reusable logic in R/, not duplicated in charts.
- Keep thresholds in config/settings.R and generate report text from calculations.
- Preserve chronological validation when changing models.
- Add a boundary test when fixing a numerical or missing-data bug.
- Keep raw sources and app snapshots separate. A report should use the same snapshot as the dashboard.
- Run the pipeline and tests before publishing a new snapshot.

This document demonstrates an analytical handoff artifact. It is not a claim of mentoring or managing a real team.

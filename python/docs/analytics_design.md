# Analytics design and governance

## Fact grain
The conversations table contains one row per chat_id. UTC is the canonical event timestamp; local_timezone is retained as an IANA timezone label. Local date/hour must be calculated with timezone-aware conversion in production.

## KPI definitions
- Chat volume: count of unique chat IDs.
- First response: minutes from arrival to first agent response.
- Handling time: agent handling minutes. Interpret concurrency carefully before treating it as occupied agent time.
- Resolution: resolved chats / total chats.
- CSAT: average valid 1-5 score among surveyed chats; null is permitted for unsurveyed chats. Extracts include response counts and score totals.
- Conversion: converted chats / eligible chats. Demo denominator is all chats; business eligibility needs owner agreement.
- Converted revenue: sum attributed to converted chats; not lost revenue.
- Required agents: ceiling(workload minutes / (60 x occupancy x productive availability)).

## Assumptions
Starter assumptions: 85% occupancy, 25% shrinkage, $24 loaded cost per agent-hour. Starter flags: p90 response >10 minutes, conversion <8%, resolution <82%, concurrency >=3.5. These are fixed SQL examples, not client SLAs or observed costs. The schedule applies illustrative day (07-15), evening (15-23) and night (23-07) patterns to a shared region-language pool. A 10% break allowance reduces productive capacity; pool capacity is allocated across channels in proportion to handling workload to prevent double counting. It is not an optimized employee roster: exact break placement, leave, skill certification and labour rules are not modeled.

## Forecast governance
Evaluation uses a fixed chronological origin and recursive prediction, retaining empty hours and excluding held-out actuals from lag updates. Segment models depend on available history. Only approved calendar flags are forecast regressors; realized chat-level event proportions are descriptive, not prediction inputs. The supplied calendar is assumed known in advance for holdout evaluation. WAPE is undefined for zero total actual volume. Review segment errors, event announcement dates and baseline performance before operational use. No prediction intervals or superiority guarantee is provided.

## Root cause
Volume and handling-time effects are arithmetic workload decompositions, not causal estimates. Review reason mix, escalations, product releases, routing and QA evidence before assigning corrective action.

## Privacy and responsible AI
Use synthetic or approved de-identified data. Do not ingest message text, names, emails, payment details or sensitive attributes. Forecasts and risk flags support human decisions; do not use them for automated employee scoring, discipline or customer eligibility. Provide human review and appeal routes in production.

## Refresh
The workflow performs scheduled synthetic refreshes and archives artifacts; it is not a live provider integration or a deployment. The generic REST adapter requires confirmed provider mappings and credentials. Source/hourly/daily/weekly/monthly/team reconciliation covers eight additive metrics and blocks mismatched exports. Database schema changes are transactional; multi-file publishing is not atomic. For production, use --output-dir staging and implement atomic delivery, stale-data monitoring and approved access controls. Original R outputs are independent.

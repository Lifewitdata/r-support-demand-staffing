# Analytics design and governance

## Fact grain
The conversations table contains one row per chat_id. UTC is the canonical event timestamp; local_timezone is retained as an IANA timezone label. Local date/hour must be calculated with timezone-aware conversion in production.

## KPI definitions
- Chat volume: count of unique chat IDs.
- First response: minutes from arrival to first agent response.
- Handling time: agent handling minutes. Interpret concurrency carefully before treating it as occupied agent time.
- Resolution: resolved chats / total chats.
- CSAT: average valid 1-5 score; production reporting should include response count.
- Conversion: converted chats / eligible chats. Demo denominator is all chats; business eligibility needs owner agreement.
- Converted revenue: sum attributed to converted chats; not lost revenue.
- Required agents: ceiling(workload minutes / (60 x occupancy x productive availability)).

## Assumptions
Starter assumptions: 85% occupancy, 25% shrinkage, $24 loaded cost per agent-hour. Starter flags: p90 response >10 minutes, conversion <8%, resolution <82%, concurrency >=3.5. These are configurable examples, not client SLAs or observed costs. The schedule applies illustrative day (07-15), evening (15-23) and night (23-07) patterns to a shared region-language pool. A 10% break allowance reduces productive capacity; pool capacity is allocated across channels in proportion to handling workload to prevent double counting. It is not an optimized employee roster: exact break placement, leave, skill certification and labour rules are not modeled.

## Forecast governance
Chronological holdout avoids random temporal leakage. Segment-level models are selected by available history. Review segment volume and errors before using forecasts. Campaign, holiday, launch and incident labels are generated synthetic regressors. Human review is required for anomalies and drift.

## Root cause
Volume and handling-time effects are arithmetic workload decompositions, not causal estimates. Review reason mix, escalations, product releases, routing and QA evidence before assigning corrective action.

## Privacy and responsible AI
Use synthetic or approved de-identified data. Do not ingest message text, names, emails, payment details or sensitive attributes. Forecasts and risk flags support human decisions; do not use them for automated employee scoring, discipline or customer eligibility. Provide human review and appeal routes in production.

## Refresh
Run python src/commerce_analytics.py after each validated source batch. Publish the quality report, dated manifest, database and extracts atomically. Alert on failed checks, missing segments, row-count anomalies and stale data. A production scheduler or live connector is not included or claimed.

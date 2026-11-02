# Python + SQL conversational commerce analytics

This Python/DuckDB layer extends the existing R/Shiny support-demand project. All generated records are synthetic; this is not connected to a real contact-centre platform.

## Run

    cd python
    python -m venv .venv
    # Windows: .venv\\Scripts\\activate
    # macOS/Linux: source .venv/bin/activate
    pip install -r requirements.txt
    python src/commerce_analytics.py
    # Or use a real, approved CSV that follows the documented field contract:
    python src/commerce_analytics.py --input data/raw/approved_conversations.csv
    pytest -q

The pipeline can generate reproducible synthetic chat records or ingest an approved chat-level CSV with `--input`. It validates the full field contract, loads DuckDB, runs the SQL semantic layer, reconciles source totals to hourly/daily totals, evaluates chronological holdout forecasts, creates a recursive seven-day forecast using a supplied future event calendar, and exports Tableau-ready CSVs.

## Data model

- Conversation fact: one row per chat_id, with UTC timestamp, region, language, channel, market, team, timezone, concurrency, first response, handling, resolution, CSAT, conversion, revenue, reason and escalation.
- Hourly KPI grain: complete UTC hour x region x language x channel calendar, including zero-chat hours. Local hour is derived from the row's IANA timezone rather than copied from UTC.
- Daily, weekly and monthly grains: reporting period x region x language x channel.
- Timezone is retained for local reporting. Convert UTC to local time with timezone-aware IANA rules in a production source adapter.

## API ingestion

A vendor-neutral REST adapter is provided in `src/api_ingestion.py`. It uses a bearer token from environment variables and a field mapping file; it does not assume Zendesk, Intercom, Freshdesk or another vendor's schema.

    export SUPPORT_API_URL="https://your-support-platform.example/api/conversations"
    export SUPPORT_API_TOKEN="your-token"
    python src/api_ingestion.py --mapping config/api_field_mapping.example.json
    python src/commerce_analytics.py --input data/raw/api_conversations.csv --events config/events.example.csv

On Windows PowerShell, set environment variables with `$env:SUPPORT_API_URL` and `$env:SUPPORT_API_TOKEN`. Never commit credentials. The example field mapping is illustrative and must be matched to the actual provider's response fields and pagination contract.

## Employee-level shift planning

Prepare a roster using `config/employee_roster.example.csv`, then run:

    python src/workforce_optimizer.py --demand outputs/tableau_staffing_coverage.csv --employees data/raw/employee_roster.csv

The heuristic allocates employees only to matching region, language and channel demand. It supports a scheduled break, employee availability windows, leave windows, daily/weekly hour caps and minimum rest between shifts. Outputs are `outputs/employee_shift_schedule.csv` and `outputs/employee_shift_coverage.csv`. It is a transparent greedy heuristic, not a globally optimal solver; validate local employment law, contracts, time zones, daylight-saving transitions, split shifts, overtime, employee preferences and collective agreements before operational use.

## Event calendar

Supply a CSV with `event_id,region,language,channel,event_type,start_utc,end_utc`. Region/language/channel may be `*` to apply across all segments. Supported event types are campaign, holiday, product_launch and incident. The calendar affects future forecast regressors and produces a descriptive event-overlap extract. Event overlap is not causal attribution.

## Automated refresh

GitHub Actions runs the reproducible analytics pipeline daily and archives the generated outputs as a workflow artifact. This scheduled run is synthetic unless a provider-specific API integration and credentials are configured. The generic REST adapter can be run locally or wired into the workflow after the provider and field mapping are confirmed.

## Analytical assumptions and limits

- Forecasting uses a Random Forest per region/language/channel where history is sufficient, otherwise seasonal-naive. Holdout metrics are MAE, RMSE and WAPE. This is a baseline, not a guarantee.
- The SQL coverage model uses illustrative 85% occupancy and 25% shrinkage. The separate employee planner handles skills, availability, leave, a fixed break and hour/rest caps, but remains a greedy heuristic and does not encode certifications, contracts, preferences or jurisdiction-specific labour rules.
- Risk thresholds are starter assumptions, not contracted SLAs. Alerts are flags, not proof of service failure.
- Converted revenue is observed synthetic revenue, not estimated lost revenue.
- Volume/AHT root-cause decomposition is arithmetic and associational, not causal.

## Tableau handoff

Use outputs/tableau_hourly_commerce.csv, tableau_staffing_coverage.csv, tableau_service_commercial_risk.csv, tableau_operational_anomalies.csv, tableau_root_cause_decomposition.csv and the daily/weekly/monthly KPI exports. Filter by region, language, channel and date. Use hour_utc for globally consistent hourly analysis.

## Ingestion contract

Use `--input path/to/file.csv` to ingest an approved CSV. Required fields are: chat_id, arrived_at_utc, region, language, channel, market, team, local_timezone, event_type, concurrency, first_response_minutes, handling_minutes, resolved, csat, converted, revenue, contact_reason and escalated. `local_hour` is recalculated from UTC and the IANA timezone. Invalid batches are rejected; missing region/language is never silently imputed. A vendor-specific API connector, production credential configuration, source checksum and fully managed ingestion service are not included.

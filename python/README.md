# Python + SQL conversational commerce analytics

This Python/DuckDB layer extends the existing R/Shiny support-demand project. All generated records are synthetic; this is not connected to a real contact-centre platform.

## Run

    cd python
    python -m venv .venv
    # Windows: .venv\\Scripts\\activate
    # macOS/Linux: source .venv/bin/activate
    pip install -r requirements.txt
    python src/commerce_analytics.py
    pytest -q

The pipeline generates chat-level records, validates the ingestion contract, loads DuckDB, runs the SQL semantic layer, evaluates segment-specific chronological holdout forecasts and exports Tableau-ready CSVs.

## Data model

- Conversation fact: one row per chat_id, with UTC timestamp, region, language, channel, market, team, timezone, concurrency, first response, handling, resolution, CSAT, conversion, revenue, reason and escalation.
- Hourly KPI grain: UTC hour x region x language x channel.
- Daily, weekly and monthly grains: reporting period x region x language x channel.
- Timezone is retained for local reporting. Convert UTC to local time with timezone-aware IANA rules in a production source adapter.

## Analytical assumptions and limits

- Forecasting uses a Random Forest per region/language/channel where history is sufficient, otherwise seasonal-naive. Holdout metrics are MAE, RMSE and WAPE. This is a baseline, not a guarantee.
- Staffing uses 85% occupancy and 25% shrinkage. Day/evening/night shift patterns are represented, a 10% break allowance reduces available capacity, and the region-language skill pool is allocated across channels to avoid double-counting the same agents. This is not an employee-level roster optimizer: break timing, leave, certifications and labour rules are not modeled.
- Risk thresholds are starter assumptions, not contracted SLAs. Alerts are flags, not proof of service failure.
- Converted revenue is observed synthetic revenue, not estimated lost revenue.
- Volume/AHT root-cause decomposition is arithmetic and associational, not causal.

## Tableau handoff

Use outputs/tableau_hourly_commerce.csv, tableau_staffing_coverage.csv, tableau_service_commercial_risk.csv, tableau_operational_anomalies.csv, tableau_root_cause_decomposition.csv and the daily/weekly/monthly KPI exports. Filter by region, language, channel and date. Use hour_utc for globally consistent hourly analysis.

## Ingestion contract

Replace generate_data() with a source adapter that writes the same column contract. Run validate_chats() before loading. Reject invalid batches; do not silently impute missing region or language. Production ingestion should log source, extraction timestamp, row count and checksum.

# Python + SQL conversational commerce analytics

This optional Python/DuckDB layer coexists with the original R/Shiny application. Generated records are synthetic. The configurable REST adapter is not a verified connection to a live customer-support platform, and CSV extracts are not a Tableau dashboard.

## Run

From the repository root:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r python/requirements.txt
python -m pytest python/tests -q
python python/src/commerce_analytics.py --days 14 --chats-per-day 30
# Approved source and optional approved event calendar:
python python/src/commerce_analytics.py --input approved_conversations.csv --events python/config/events.example.csv
```

Python 3.11 and 3.14 are the workflow test targets. Paths to SQL, the default database and extracts are resolved from the source location, not the current directory. `--output-dir` isolates generated outputs for testing or a separate refresh. Default outputs are under `python/outputs/`, with the canonical source extract under `python/data/raw/`; original root-level R datasets and outputs are untouched.

The pipeline validates region-language consistency, UTC timestamps, IANA timezones, outcomes and metric ranges; loads DuckDB; executes both SQL scripts; checks additive totals at every reporting grain; evaluates recursive chronological forecasts; produces a seven-day forward forecast; and writes management reports and CSV extracts. Invalid inputs are rejected before replacing output files. Database schema changes are transactional, but the complete multi-file export is not atomically published; use a staging directory for production delivery.

## Data model and ingestion contract

Required columns: `chat_id,arrived_at_utc,region,language,channel,market,team,local_timezone,event_type,concurrency,first_response_minutes,handling_minutes,resolved,csat,converted,revenue,contact_reason,escalated`.

- One conversation fact row per unique, nonblank chat ID.
- Required dimensions cannot be missing or blank. Region/language must match the documented AMER, EMEA or APAC language pools in the source.
- `local_hour` is recalculated from UTC and an IANA timezone. Naive source timestamps are interpreted as UTC; providers must normalize their source timezone before ingestion.
- Required metrics must be finite numeric values; concurrency is a positive integer and outcome flags are 0/1. CSAT may be null for unsurveyed chats, otherwise it must be 1–5. Unconverted chats must have zero revenue.
- Hourly grain is a complete UTC hour × observed region/language/channel segment spine, including zero-chat hours. Empty-hour rates remain null, not fabricated zeros. A modal local hour is descriptive and is null in empty hours; it cannot represent multiple timezones precisely.
- Daily, weekly and monthly KPI grains are UTC period × region × language × channel. Weeks start Monday. A separate daily `team_kpis` extract includes team without duplicating pooled staffing.

## API ingestion

`src/api_ingestion.py` supports a configurable JSON REST response and field mapping; it does not assume a vendor schema. Only explicitly mapped canonical fields are exported. Full canonical validation precedes atomic replacement of the individual API CSV.

Set `SUPPORT_API_URL` to the approved HTTPS endpoint and `SUPPORT_API_TOKEN` in the environment, then run from the repository root:

```bash
python python/src/api_ingestion.py --mapping python/config/api_field_mapping.example.json --output python/data/raw/api_conversations.csv
python python/src/commerce_analytics.py --input python/data/raw/api_conversations.csv
```

On PowerShell use `$env:SUPPORT_API_URL` and `$env:SUPPORT_API_TOKEN`. Pagination is restricted to the same HTTPS origin; redirects and credentials embedded in URLs are rejected. Confirm the provider's field mapping, records/next paths and pagination behavior before use. API responses are mocked in tests; no live connection is claimed. Never commit tokens, `.env` files or approved private datasets.

## Employee-level shift planning

The separate greedy employee planner uses an approved roster following `config/employee_roster.example.csv`:

```bash
python python/src/workforce_optimizer.py --demand python/outputs/tableau_staffing_coverage.csv --employees python/config/employee_roster.example.csv --output python/outputs/employee_shift_schedule.csv
```

An employee covers at most one eligible region/language/channel segment per productive hour. Availability, leave, complete break intervals, UTC daily/ISO-week productive-hour caps and minimum rest are enforced. Outputs include the shift schedule and `employee_shift_coverage.csv`; unfilled demand remains explicit. The chronological greedy selection is not globally optimal and can miss earlier feasible shifts after selecting a later one. Caps refer to productive hours, not jurisdiction-specific paid employment time. Validate contracts, certifications, local time, overtime, preferences and labour law before operational use.

## Event calendar and forecasting

Supply `event_id,region,language,channel,event_type,start_utc,end_utc`. IDs must be unique; dimensions may be `*` (`ALL`/`all` are normalized); supported types are campaign, holiday, product_launch and incident. Intervals are start-inclusive/end-exclusive. Forecast flags mark hours overlapping the supplied event interval. Descriptive SQL overlap counts use actual conversation timestamps. Overlapping event totals are not additive and do not establish causal impact.

The model uses Random Forest when training history is sufficient, otherwise seasonal-naive. Lagged demand and rolling means are computed only from prior observations/predictions. Holdout evaluation is recursive from a fixed chronological origin and includes empty hours. Realized chat-level event proportions are not forecast inputs: only supplied calendar flags are used, with zero defaults when absent. For evaluation, the supplied calendar is assumed known in advance; this assumption must be checked against real announcement dates. Synthetic random event labels do not prove a useful event-sensitive model.

`forecast_holdout.csv` and `forecast_scores.csv` contain evaluation results; `forecast_next_7_days.csv` contains 168 future hours per observed segment and the event assumption. MAE/RMSE and WAPE are reported; WAPE is null when actual volume sums to zero. Insufficient evaluation history produces header-only evaluation CSVs, while a short-history forward baseline is still available. There are no calibrated prediction intervals or guaranteed forecast improvements.

## SQL assumptions and Tableau handoff

The coverage model uses fixed illustrative 85% occupancy, 25% shrinkage, UTC day/evening/night pool schedules and a separate 10% break allowance. Capacity is allocated across channels by workload to avoid counting the same pool repeatedly. SQL staffing is a scenario, not the employee planner's realized roster; it does not use conversation concurrency to divide handling workload. Review whether shrinkage already includes breaks before operational use. Gap cost is illustrative agent-hour cost, not measured lost revenue or savings. Risk thresholds are hardcoded examples, not contracted SLAs. Workload volume/AHT decomposition is arithmetic and associational, not causal.

Import `tableau_hourly_commerce.csv`, staffing, risk, anomaly, root-cause, daily/weekly/monthly/team KPI, event overlap and reconciliation extracts from the output directory. Filter by UTC date, region, language, channel and (in the team extract) team. Use additive numerator/count columns to recompute weighted rates; never average segment averages. Reconciliation checks eight counts/sums across source, hourly, daily, weekly, monthly and team grains. Each generated weekly/monthly narrative summarizes all segments for its latest UTC period.

No Tableau workbook, published dashboard, hosted Streamlit app or verified live provider connection is included.

## Optional Groq and Streamlit

```bash
python -m streamlit run python/src/streamlit_app.py --server.headless true
python python/src/analyse_conversations.py --input python/config/conversation_text.example.csv --output python/outputs/conversation_insights.csv
```

Streamlit displays reviewed, read-only SQL results without a key; explanations and the conversation CLI require `GROQ_API_KEY`. `GROQ_MODEL` selects the model. See [docs/groq_ai_layer.md](docs/groq_ai_layer.md) for privacy controls and limitations. Mocked HTTP/model responses validate integration contracts; they do not verify live Groq access or model quality.

## Automated refresh

The GitHub Actions workflow tests Python 3.11/3.14 without live secrets, executes a synthetic smoke pipeline on code changes, and uses the full synthetic refresh for the daily schedule. Tests execute all SQL views against real DuckDB fixtures. Test reports and validated output files are archived as artifacts, not committed or deployed. Scheduled workflows run from `main`, so the updated schedule is effective only after review and merge. No R report refresh or Pages publication is added by this workflow. Optional live integrations must use GitHub Actions secrets and require separate provider configuration; no secret is needed by the supplied workflow.

See [docs/analytics_design.md](docs/analytics_design.md) for metric definitions and governance.

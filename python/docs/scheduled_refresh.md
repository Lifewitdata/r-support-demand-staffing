# Scheduled refresh, ingestion and monitoring

This describes the batch workflow in `.github/workflows/python-analytics.yml`. It is scheduled batch
processing, not real-time streaming. Scheduled refreshes use the synthetic demonstration generator;
they are not a live feed from a support provider.

## What runs and when

| Trigger | Behaviour |
|---|---|
| Push to `main` touching `python/**` or this workflow | Python test matrix, dependency audit and synthetic smoke refresh |
| Pull request touching the same paths | Python test matrix, dependency audit and synthetic smoke refresh |
| Daily schedule (`17 2 * * *`, UTC) | Full synthetic refresh (210 days × 190 conversations/day) |
| Manual `workflow_dispatch` | Choose `smoke` or `full`, optionally override `days`, `chats_per_day` and artifact retention |

Change the frequency by editing the `cron` entry. GitHub only evaluates schedules that exist on the
default branch, and scheduled runs can be paused by GitHub after long repository inactivity.

## Job graph

```
test (Python 3.11 and 3.14) ──> analytics (synthetic refresh + reconciliation monitor)
          └──────────────────> dependencies (dependency audit)

workflow_dispatch + configured provider credentials ──> ingest (optional mapped import validation)
```

The ordinary tests and synthetic refresh require no provider or Groq credentials. The optional
`ingest` job runs only after a manual dispatch and only when both `SUPPORT_API_URL` and
`SUPPORT_API_TOKEN` are configured. It uses the same generic REST adapter documented below;
it is not a scheduled provider sync and is not automatically merged into the synthetic refresh.

## Synthetic refresh and quality gate

The analytics job runs `src/commerce_analytics.py`, then `src/refresh_monitor.py`. The pipeline:

- validates the canonical conversation schema, including nonblank region and language, supported
  region-language combinations, UTC timestamps, IANA timezones and metric constraints;
- runs SQL reconciliation for eight additive measures across source, hourly, daily, weekly, monthly
  and team grains;
- stops before publishing when canonical validation or reconciliation fails;
- records the conversation count, newest event timestamp and failed reconciliation checks.

The refresh monitor opens DuckDB read-only with `TimeZone='UTC'`, writes
`python/outputs/refresh_state.json` and a GitHub job-summary block, and exits non-zero if the
database is missing or unhealthy. `last_successful_refresh_utc` is updated only after a healthy run;
a failed run carries forward the previous successful timestamp rather than clearing or inventing one.

## Approved source imports

The generic adapter is `python/src/api_ingestion.py`; it replaces the generator only when you
explicitly supply an approved provider endpoint and field mapping. It does not assume a vendor
schema. The adapter restricts requests and pagination to the same HTTPS origin, rejects redirects,
exports only explicitly mapped fields, recalculates local hour from UTC and an IANA timezone, and
calls the same canonical validator before atomically replacing the individual CSV extract.

Required canonical fields and their grain are documented in [the Python README](../README.md#data-model-and-ingestion-contract).
The contract explicitly checks missing region and language, unsupported region-language pairs,
timestamps, timezones, unique IDs and numeric/outcome constraints.

From the repository root, use:

```bash
python -m pip install -r python/requirements.txt
python python/src/api_ingestion.py \
  --mapping python/config/api_field_mapping.example.json \
  --output python/data/raw/api_conversations.csv
python python/src/commerce_analytics.py \
  --input python/data/raw/api_conversations.csv
```

Set `SUPPORT_API_URL` and `SUPPORT_API_TOKEN` in the environment first. Confirm the provider's
records path, next-page path and field names before use; override them with `--records-path` and
`--next-path` when required. The example mapping is illustrative and must be adapted to the approved
source. The adapter and its HTTP contracts are tested with mocked responses; **no live provider
account or production feed is claimed**.

For a manual GitHub Actions import check, configure the repository variables/secrets and select
**Actions → Python analytics checks → Run workflow**. The job validates the mapped response but does
not archive source rows or publish them into the analytics database. This avoids retaining potentially
sensitive support records in workflow artifacts. Run the local command above to retain the approved
extract and then pass it to `commerce_analytics.py --input`.

## Artifacts, retention and failure handling

The synthetic analytics job archives the DuckDB database, aggregate CSV extracts, forecast files,
briefs, pipeline log, run manifest and refresh state. Test jobs archive JUnit XML. Retention is a
GitHub setting/input; artifacts expire and are not a permanent data store. Provider source rows are
not uploaded as artifacts.

A failed synthetic refresh posts a workflow summary and leaves previous validated artifacts as the
last known good run. A failed optional provider import posts a summary and does not promote an extract.
There is no configured email, Slack or PagerDuty integration.

## Verification boundaries

Unit, mocked API, SQL fixture and synthetic smoke tests run in CI. They demonstrate code behaviour
against controlled fixtures, not a working connection to a real provider. The scheduled event itself
must be observed on `main`; manual provider ingestion requires real credentials and a valid mapping.
Artifact retention behaviour is controlled by repository settings.

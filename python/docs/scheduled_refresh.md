# Scheduled refresh, ingestion and monitoring

This describes the batch pipeline in `.github/workflows/python-analytics.yml`. It is scheduled batch
processing, not real-time streaming: data becomes visible only after a run completes.

## What runs and when

| Trigger | Behaviour |
|---|---|
| `push` to `main` touching `python/**` or the workflow | test matrix + synthetic smoke refresh (14 days x 30 chats/day) |
| `pull_request` touching the same paths | same, on the PR head |
| `schedule: cron 17 2 * * *` | daily full synthetic refresh (210 days x 190 chats/day) |
| `workflow_dispatch` | choose `smoke`/`full`, optionally override `days`, `chats_per_day` and `retention_days` |

Change the frequency by editing the `cron` entry. GitHub only evaluates schedules that exist on the
default branch, and scheduled runs are skipped on repositories that have been inactive for 60 days.

## Job graph

```
secrets-audit ─┐
test (3.11, 3.14) ─┬─ ingest   (only when provider credentials are configured)
                   └─ analytics (synthetic refresh + quality monitor)
```

`analytics` and `ingest` both require `test` to pass, so a broken suite never publishes outputs.
Nothing in `test` or `analytics` reads a secret: the suite is mocked and the refresh is synthetic, so
CI stays green with zero credentials configured.

## Data-quality monitoring

`commerce_analytics.py` already refuses to publish when any `data_reconciliation` row is not `PASS`, so
a failing reconciliation aborts the refresh and the previously published outputs and artifacts remain
valid. On top of that, `src/refresh_monitor.py`:

- opens the built database read-only with `TimeZone='UTC'`,
- records conversation count, latest `arrived_at_utc`, the reconciliation check count and the names of
  any failed metrics,
- writes `python/outputs/refresh_state.json` and a GitHub job-summary block,
- exits non-zero when the database is unusable or unhealthy.

`refresh_state.json` semantics: `last_successful_refresh_utc` is stamped only for a healthy run. When a
run fails, the previous value is **carried forward** (and `carried_previous_success` says so) rather
than being cleared or faked. The state file lives in an artifact, so treat the workflow run history as
the durable record: the most recent successful `analytics` run for `main` is authoritative
(`gh run list --workflow "Python analytics checks" --branch main --status success`, or the Actions page).

## Artifacts and retention

| Artifact | Contents | Retention |
|---|---|---|
| `python-test-results-3.11` / `-3.14` | JUnit XML of the suite | `retention_days` input, default 14 |
| `commerce-analytics-outputs` | DuckDB, the `tableau_*.csv` extracts, forecast CSVs, briefs, `pipeline.log`, `run_manifest.json`, `refresh_state.json` | `retention_days` input, default 14 |
| `ingestion-state` | `ingestion.log`, `ingestion_state.json` watermark, `ingestion_last_error.json` | `retention_days` input, default 30 |

Retention is a GitHub setting, not an in-repo data store: artifacts disappear when retention expires.
The database and CSVs are generated output and are gitignored on purpose, so no run overwrites
committed data.

## Failure notifications

A failing job posts a titled block to the workflow summary (`Alert on a failed refresh`,
`Alert on failed ingestion`) and GitHub's normal notification rules then apply to watchers of the
repository. There is no configured email, Slack or PagerDuty integration: adding one needs a webhook
URL that you supply, and none is claimed here.

## Incremental provider ingestion (requires credentials)

The `ingest` job runs only when `secrets.SUPPORT_API_TOKEN` and `vars.SUPPORT_API_URL` are both set;
otherwise the `secrets-audit` job reports `ingestion=false` and the job is skipped. It calls
`src/support_api_ingest.py` with a watermark state file, so each run extracts only what changed since
the last successful run. **This path has not been executed against a real provider account** — see
[api_providers.md](api_providers.md) for what to configure before enabling it, and note that promoting
an ingested extract into the analytics database is a deliberate manual step
(`python src/commerce_analytics.py --input <extract>`), not an automatic part of the schedule.

## Backfill and recovery

A schedule that fails repeatedly leaves the last good artifact in place; the next passing run replaces
it. To rebuild history deliberately, dispatch the workflow with `profile=full` (or explicit `days`),
and for a provider backfill run `support_api_ingest.py --backfill-from YYYY-MM-DD` locally or in a
one-off dispatch after credentials are configured.

## Verification status

Verified locally: the suite, the smoke refresh, `refresh_monitor.py` against a real database, and the
quality gate rejecting a corrupted metric. Not yet verified: the `schedule` event itself (it only fires
on `main`), the `ingest` job (needs real credentials), and artifact retention behaviour in your org's
settings.

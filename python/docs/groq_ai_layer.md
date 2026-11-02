# Groq AI layer

The optional Groq integration adds a natural-language explanation layer over approved DuckDB analytics and an optional conversation-text analysis workflow.

## Setup

From the `python` directory, install requirements and generate the analytics database:

```bash
pip install -r requirements.txt
python src/commerce_analytics.py
```

## Secret configuration

`GROQ_API_KEY` must be configured wherever the code that calls Groq actually runs. The default model is `llama-3.3-70b-versatile`; set `GROQ_MODEL` to override it (an empty value falls back to the default). Never commit the key.

| Where it runs | How to configure the key | Notes |
|---|---|---|
| Local scripts and CLI | `export GROQ_API_KEY=...` (or `set` in cmd) before invoking | `.env` files are gitignored; nothing reads them automatically |
| Local Streamlit | `python/.streamlit/secrets.toml` with `GROQ_API_KEY = "..."`, or an environment variable | `python/.streamlit/secrets.toml` is gitignored; the app reads `st.secrets` first, then the environment, and never displays the value |
| GitHub Actions | Repository secret `GROQ_API_KEY` | Only the opt-in `Groq live API verification` workflow reads it; `python-analytics.yml` never references it |
| Streamlit Community Cloud | App settings → Secrets | **GitHub repository secrets are not available to Streamlit hosting.** They are separate stores; see [streamlit_deployment.md](streamlit_deployment.md) |

## Analytics Q&A

Questions are routed to fixed, reviewed SQL templates for overview, regions, languages, channels, teams, contact reasons, staffing and risks. This is category routing, not arbitrary SQL or an unrestricted question engine. DuckDB is opened read-only. The language model receives selected aggregate facts and a question with common direct identifiers masked; it does not generate SQL or access raw conversation rows. Streamlit displays these facts without an API key; explanation requests require the key.

## Conversation analysis

The synthetic analytics dataset contains metrics, not message text. Conversation analysis requires a separate approved CSV with a `conversation_text` column. Common email and phone-like strings are masked before transmission, but redaction is best-effort and is not guaranteed de-identification. Do not upload personal, payment, authentication or confidential information unless you have the appropriate authority and privacy approval. Prefer synthetic or properly de-identified text.

From the repository root, run `python -m streamlit run python/src/streamlit_app.py` for the local interface. Run `python python/src/analyse_conversations.py --input approved.csv --output python/outputs/conversation_insights.csv --id-column conversation_id` for an approved text CSV; omit --id-column to use sequential row IDs. Common identifiers are masked and text is truncated to 3,000 characters per row before transmission. Returned IDs, fields and classification types are validated and reordered to match the input; malformed responses are rejected. Null-text rows are omitted. Classification quality and privacy are not guaranteed by schema validation.

Model outputs are indicators for analyst review, not ground truth or automated customer decisions. A vendor-specific support-platform API connector, Tableau workbook and hosted deployment are not part of this layer.

## Automated tests (mocked, credential-free)

```bash
pytest -q
```

Every HTTP contract test (success, redirect, 400/401/429/500, malformed body, timeout) runs against
mocked responses, so the normal suite passes with no key and no network. Tests marked `live` are
reported as skipped unless you opt in.

## Live verification (opt-in, makes real API calls)

Mocked contracts prove our handling, not that the account works. `src/groq_live_check.py` is the
opt-in path that calls the real API. It consumes quota and is never wired into ordinary CI.

```bash
# from the python directory, after building the analytics database
export GROQ_API_KEY=...          # or configure it in your shell profile
python src/groq_live_check.py --json
python src/groq_live_check.py --checks connectivity,analytics_assistant --retries 3
```

Checks: `connectivity` (a minimal round trip), `analytics_assistant` (real DuckDB facts through the
routing templates plus an explanation), `conversation_analysis` (two synthetic transcripts through the
validated batch contract) and `prompt_injection` (transcript text that tries to break the row
contract and asks for the key). Exit codes: `0` all passed, `1` at least one check failed, `2` no key
available in this environment. Failure classification distinguishes an unusable credential (HTTP 401 /
403, never retried), rate limiting and 5xx (retried with capped exponential backoff), timeouts
(retried) and malformed model payloads (retried once). Every emitted message is scrubbed of the key
value, and the key length is never reported.

Run the same checks in GitHub Actions from **Actions → Groq live API verification → Run workflow**:
the workflow confirms the `GROQ_API_KEY` secret is present without printing it, builds a small
synthetic database, runs the checks and appends the redacted JSON summary to the job summary. If the
secret is missing, the run stops with exit `2` and no API call is made.

To run the live tests in the suite instead of the CLI:

```bash
GROQ_LIVE=1 pytest -q tests/test_groq_live.py -m live
```

# Responsible AI: scope, code validation and evidence boundaries

## What AI is used for

The optional Groq-hosted large language model (LLM) has two bounded uses in this portfolio project:

1. **Analytics explanation:** a user question is classified into a small set of reviewed categories. The application selects a fixed, allow-listed DuckDB `SELECT` template and executes it against the local database in read-only mode. Groq receives the question and the resulting aggregate facts to draft a natural-language explanation. The model does not write or execute SQL and does not query raw conversation rows in this path.
2. **Approved conversation-text analysis:** when an analyst explicitly supplies an approved CSV with a `conversation_text` column, the optional batch workflow asks Groq to suggest sentiment, contact reason, escalation-risk category, a short summary and key phrases. This is an analyst-assistance output, not an automated customer or employee decision.

The Random Forest and seasonal-naive forecasting models are conventional predictive models in the analytics pipeline; they are separate from the Groq LLM explanation/classification features.

## What is validated by code

The application applies deterministic checks around the model rather than assuming a plausible response is correct:

- **Before data analysis:** the ingestion contract validates required columns, unique nonblank conversation IDs, nonblank region and language, supported region-language combinations, UTC timestamps, IANA timezones, numeric/finite metrics, duration and revenue constraints, outcome flags and CSAT bounds.
- **Before analytics Q&A:** question routing selects only reviewed SQL templates; each template is a single read-only `SELECT`, and DuckDB is opened with `read_only=True`. The model receives the selected query results rather than database access.
- **Before conversation text is sent:** common email- and phone-like identifiers are masked on a best-effort basis and text is truncated. This is not guaranteed de-identification; only text approved for external processing should be supplied.
- **After conversation analysis:** code checks JSON structure, one result per input row, exact unique row IDs, allowed sentiment and escalation-risk labels, field types and length limits, then restores input order. Malformed or incomplete responses are rejected.

These checks establish schema, routing and processing-contract compliance. They do **not** establish that a model's interpretation is factually correct.

## What is never presented as verified evidence

Groq-generated explanations, sentiment labels, contact-reason labels, escalation-risk labels, summaries and key phrases are model-generated suggestions. They are not ground truth, verified customer statements, proof of an incident, causal root-cause findings, policy determinations or evidence that a staffing action will work.

Forecasts, scenario outputs and risk flags are also analytical estimates based on the stated data and assumptions, not guaranteed outcomes or measured business impact. Human review and source-data checks are required before operational use. The project does not authorize autonomous customer eligibility, employee scoring, discipline or other consequential decisions.

## Privacy and limitations

Use synthetic data or data that is approved for the specific processing purpose. Do not upload personal, payment, authentication or confidential information without the necessary authority and privacy approval. Identifier masking is best-effort and must not be described as anonymisation. Model access is optional; SQL facts remain available without a Groq key.

All portfolio conversation records are generated for demonstration. No real provider account, production AI deployment, verified business result or measured savings is claimed.

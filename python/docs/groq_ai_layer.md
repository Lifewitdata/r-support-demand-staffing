# Groq AI layer

The optional Groq integration adds a natural-language explanation layer over approved DuckDB analytics and an optional conversation-text analysis workflow.

## Setup

From the `python` directory, install requirements and generate the analytics database:

```bash
pip install -r requirements.txt
python src/commerce_analytics.py
```

Set `GROQ_API_KEY` in the environment where the application runs. The API key stored in GitHub Actions secrets is not automatically available to a local or hosted app. Never commit the key. The default model is `llama-3.3-70b-versatile`; `GROQ_MODEL` can override it.

## Analytics Q&A

Questions are mapped to reviewed SQL templates in `src/groq_assistant.py`. DuckDB is opened read-only. The language model does not generate SQL or access raw conversation rows; it receives only the selected query results and the question to explain.

## Conversation analysis

The synthetic analytics dataset contains metrics, not message text. Conversation analysis requires a separate approved CSV with a `conversation_text` column. Common email and phone-like strings are masked before transmission, but redaction is best-effort and is not guaranteed de-identification. Do not upload personal, payment, authentication or confidential information unless you have the appropriate authority and privacy approval. Prefer synthetic or properly de-identified text.

Model outputs are indicators for analyst review, not ground truth or automated customer decisions. Validate model classifications before operational use. A vendor-specific API connector and hosted deployment are not included.

## Tests

```bash
pytest -q
```

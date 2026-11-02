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

Questions are routed to fixed, reviewed SQL templates for overview, regions, languages, channels, teams, contact reasons, staffing and risks. This is category routing, not arbitrary SQL or an unrestricted question engine. DuckDB is opened read-only. The language model receives selected aggregate facts and a question with common direct identifiers masked; it does not generate SQL or access raw conversation rows. Streamlit displays these facts without an API key; explanation requests require the key.

## Conversation analysis

The synthetic analytics dataset contains metrics, not message text. Conversation analysis requires a separate approved CSV with a `conversation_text` column. Common email and phone-like strings are masked before transmission, but redaction is best-effort and is not guaranteed de-identification. Do not upload personal, payment, authentication or confidential information unless you have the appropriate authority and privacy approval. Prefer synthetic or properly de-identified text.

From the repository root, run `python -m streamlit run python/src/streamlit_app.py` for the local interface. Run `python python/src/analyse_conversations.py --input approved.csv --output python/outputs/conversation_insights.csv --id-column conversation_id` for an approved text CSV; omit --id-column to use sequential row IDs. Common identifiers are masked and text is truncated to 3,000 characters per row before transmission. Returned IDs, fields and classification types are validated and reordered to match the input; malformed responses are rejected. Null-text rows are omitted. Classification quality and privacy are not guaranteed by schema validation.

Model outputs are indicators for analyst review, not ground truth or automated customer decisions. API success/error contracts are tested using mocked responses, not a live Groq connection. A vendor-specific API connector, Tableau workbook and hosted deployment are not included.

## Tests

```bash
pytest -q
```

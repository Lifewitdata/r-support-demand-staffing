"""Groq explanations over a read-only, allow-listed DuckDB analytics layer."""
from __future__ import annotations
import json, os, re
from pathlib import Path
from typing import Any
import duckdb
import pandas as pd
import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = os.getenv("GROQ_MODEL") or "openai/gpt-oss-120b"
DB_PATH = Path(__file__).resolve().parents[1] / "outputs" / "commerce_analytics.duckdb"

QUERY_TEMPLATES = {
"overview": """SELECT COUNT(*) AS chats, ROUND(AVG(first_response_minutes),2) AS avg_first_response_minutes,
ROUND(AVG(handling_minutes),2) AS avg_handling_minutes, ROUND(AVG(resolved::INT),4) AS resolution_rate,
ROUND(AVG(csat),2) AS avg_csat, ROUND(AVG(converted::INT),4) AS conversion_rate,
ROUND(SUM(revenue),2) AS converted_revenue FROM conversations""",
"region": """SELECT region, COUNT(*) AS chats, ROUND(AVG(first_response_minutes),2) AS avg_first_response_minutes,
ROUND(AVG(resolved::INT),4) AS resolution_rate, ROUND(AVG(csat),2) AS avg_csat,
ROUND(AVG(converted::INT),4) AS conversion_rate, ROUND(SUM(revenue),2) AS converted_revenue
FROM conversations GROUP BY region ORDER BY chats DESC""",
"language": """SELECT region, language, COUNT(*) AS chats, ROUND(AVG(first_response_minutes),2) AS avg_first_response_minutes,
ROUND(AVG(resolved::INT),4) AS resolution_rate, ROUND(AVG(csat),2) AS avg_csat
FROM conversations GROUP BY region, language ORDER BY chats DESC LIMIT 20""",
"team": """SELECT team, COUNT(*) AS chats, ROUND(AVG(first_response_minutes),2) AS avg_first_response_minutes,
ROUND(AVG(handling_minutes),2) AS avg_handling_minutes, ROUND(AVG(resolved::INT),4) AS resolution_rate,
ROUND(AVG(csat),2) AS avg_csat, ROUND(AVG(converted::INT),4) AS conversion_rate,
ROUND(SUM(revenue),2) AS converted_revenue FROM conversations GROUP BY team ORDER BY chats DESC""",
"channel": """SELECT channel, COUNT(*) AS chats, ROUND(AVG(first_response_minutes),2) AS avg_first_response_minutes,
ROUND(AVG(handling_minutes),2) AS avg_handling_minutes, ROUND(AVG(csat),2) AS avg_csat,
ROUND(AVG(converted::INT),4) AS conversion_rate FROM conversations GROUP BY channel ORDER BY chats DESC""",
"reasons": """SELECT contact_reason, COUNT(*) AS chats, ROUND(AVG(csat),2) AS avg_csat,
ROUND(AVG(escalated::INT),4) AS escalation_rate FROM conversations
GROUP BY contact_reason ORDER BY chats DESC""",
"risks": """SELECT severity, region, language, channel, risk_type, ROUND(agent_gap,2) AS agent_gap,
ROUND(p90_first_response_minutes,2) AS p90_first_response_minutes, suggested_action
FROM service_commercial_risk ORDER BY CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2
WHEN 'MEDIUM' THEN 3 ELSE 4 END, hour_utc DESC LIMIT 25""",
"staffing": """SELECT region, language, channel, COUNT(*) AS hours_with_gap,
ROUND(SUM(agent_gap),2) AS agent_gap_hours, ROUND(AVG(required_agent_equiv),2) AS avg_required_agent_equiv
FROM staffing_coverage WHERE agent_gap > 0 GROUP BY region, language, channel
ORDER BY agent_gap_hours DESC LIMIT 20"""
}

def classify_question(question: str) -> str:
    q = question.lower()
    if any(x in q for x in ("risk", "alert", "critical", "high priority", "service issue")): return "risks"
    if any(x in q for x in ("understaff", "staffing", "coverage", "agent gap", "overstaff")): return "staffing"
    if any(x in q for x in ("reason", "contact driver", "why contact", "issue type", "customer issue")): return "reasons"
    if any(x in q for x in ("language", "locale")): return "language"
    if any(x in q for x in ("channel", "live chat", "in-app", "web channel")): return "channel"
    if any(x in q for x in ("team", "payments", "retention", "core support")): return "team"
    if any(x in q for x in ("region", "amer", "emea", "apac")): return "region"
    return "overview"

def fetch_analytics(question: str, db_path: str | Path = DB_PATH) -> tuple[str, list[dict[str, Any]]]:
    if not Path(db_path).exists():
        raise FileNotFoundError(f"Analytics database not found at {db_path}. Run python python/src/commerce_analytics.py from the repository root (or src/commerce_analytics.py from the python directory) first.")
    intent = classify_question(question)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        # Facts are labelled UTC: render timestamps in UTC regardless of the host timezone.
        con.execute("SET TimeZone='UTC'")
        frame = con.execute(QUERY_TEMPLATES[intent]).df()
    finally:
        con.close()
    return intent, frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records")

class GroqAPIError(RuntimeError):
    """Groq failure with the machine-readable context callers must branch on."""

    def __init__(self, message, *, status_code=None, kind="api"):
        super().__init__(message)
        self.status_code = status_code
        self.kind = kind


def groq_chat(messages: list[dict[str, str]], *, model: str = DEFAULT_MODEL,
              temperature: float = 0.1, max_tokens: int = 900, timeout: int = 45,
              api_key: str | None = None) -> str:
    api_key = api_key or os.getenv("GROQ_API_KEY")
    if not api_key: raise GroqAPIError("GROQ_API_KEY is not set. Configure it in the app environment.", kind="config")
    try:
        response = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
            timeout=timeout, allow_redirects=False)
    except requests.RequestException as exc:
        raise GroqAPIError("Groq API request failed", kind=type(exc).__name__) from exc
    try:
        if not 200 <= response.status_code < 300:
            raise GroqAPIError(f"Groq API returned HTTP {response.status_code}",
                               status_code=response.status_code, kind="api")
        try:
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Missing model content")
            return content.strip()
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise GroqAPIError("Groq API returned a malformed model response",
                               status_code=response.status_code, kind="response") from exc
    finally:
        response.close()

GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"

def list_models(*, timeout: int = 20) -> list[str]:
    """Model identifiers the configured key can use. Only ids are returned, never the key."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: raise GroqAPIError("GROQ_API_KEY is not set. Configure it in the app environment.", kind="config")
    try:
        response = requests.get(GROQ_MODELS_URL, headers={"Authorization": f"Bearer {api_key}"},
                                timeout=timeout, allow_redirects=False)
    except requests.RequestException as exc:
        raise GroqAPIError("Groq API request failed", kind=type(exc).__name__) from exc
    try:
        if not 200 <= response.status_code < 300:
            raise GroqAPIError(f"Groq API returned HTTP {response.status_code}",
                               status_code=response.status_code, kind="api")
        try:
            data = response.json()["data"]
            if not isinstance(data, list): raise ValueError("Model list is not an array")
            ids = sorted({item["id"] for item in data
                          if isinstance(item, dict) and isinstance(item.get("id"), str)})
            if not ids: raise ValueError("Model list is empty")
        except (ValueError, KeyError, TypeError) as exc:
            raise GroqAPIError("Groq API returned a malformed model list",
                               status_code=response.status_code, kind="response") from exc
        return ids
    finally:
        response.close()

def answer_analytics_question(question: str, db_path: str | Path = DB_PATH, *,
                              analytics: tuple[str, list[dict[str, Any]]] | None = None,
                              api_key: str | None = None) -> dict[str, Any]:
    intent, rows = analytics if analytics is not None else fetch_analytics(question, db_path)
    if not rows: return {"intent": intent, "facts": rows, "answer": "No matching analytics rows were found."}
    messages = [
        {"role": "system", "content": "You are an operations analytics assistant. Explain only supplied database facts. Do not invent causes, metrics, dates, SLAs or recommendations. Distinguish association from causation. Be concise and mention caveats."},
        {"role": "user", "content": f"Question: {redact_direct_identifiers(question)}\nAnalysis: {intent}\nDatabase results (JSON): {json.dumps(rows, allow_nan=False)}"}
    ]
    return {"intent": intent, "facts": rows, "answer": groq_chat(messages, api_key=api_key)}

def redact_direct_identifiers(text: str) -> str:
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}", "[EMAIL]", str(text))
    return re.sub(r"[0-9][0-9 .()+/-]{7,}[0-9]", "[PHONE]", text)

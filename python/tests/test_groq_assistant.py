import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import duckdb
import pandas as pd
import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import groq_assistant as groq
from groq_assistant import QUERY_TEMPLATES, classify_question, redact_direct_identifiers


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(requests, "post", Mock(side_effect=AssertionError("Unmocked API call")))


@pytest.mark.parametrize("question,intent", [
    ("Which region has most chats?", "region"), ("Show understaffed teams", "staffing"),
    ("What are the top contact reasons?", "reasons"), ("List critical service alerts", "risks"),
    ("Give me an executive overview", "overview"), ("Compare team performance", "team"),
    ("Payments performance", "team"), ("Show languages", "language"), ("Show channels", "channel")])
def test_question_router(question, intent):
    assert classify_question(question) == intent


def test_templates_are_select_only():
    for sql in QUERY_TEMPLATES.values():
        assert sql.strip().lower().startswith("select")
        assert ";" not in sql


def test_templates_execute_against_real_schema():
    # Actual chat schema and production SQL views, without importing the forecast module.
    con = duckdb.connect(":memory:")
    try:
        con.execute("""CREATE TABLE conversations (
            chat_id VARCHAR, arrived_at_utc TIMESTAMPTZ, region VARCHAR, language VARCHAR,
            channel VARCHAR, market VARCHAR, team VARCHAR, local_timezone VARCHAR,
            local_hour INTEGER, day_of_week INTEGER, event_type VARCHAR, concurrency INTEGER,
            first_response_minutes DOUBLE, handling_minutes DOUBLE, resolved INTEGER,
            csat DOUBLE, converted INTEGER, revenue DOUBLE, contact_reason VARCHAR, escalated INTEGER)""")
        con.execute("""INSERT INTO conversations VALUES ('c1', '2026-01-01 12:00:00+00',
            'AMER','en','live_chat','US','Payments','UTC',12,3,'none',2,5,10,1,NULL,0,0,'billing',0)""")
        con.execute((Path(__file__).resolve().parents[1] / "sql" / "analytics.sql").read_text())
        for sql in QUERY_TEMPLATES.values():
            frame = con.execute(sql).df()
            assert len(frame.columns) > 0
    finally:
        con.close()


def test_redaction():
    value = redact_direct_identifiers("Email jane.doe@example.com or call +1 (415) 555-0134")
    assert "jane.doe@example.com" not in value
    assert "[EMAIL]" in value and "[PHONE]" in value


def test_groq_success(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    response = Mock(status_code=200)
    response.json.return_value = {"choices": [{"message": {"content": "  Answer\n"}}]}
    post = Mock(return_value=response)
    monkeypatch.setattr(requests, "post", post)
    assert groq.groq_chat(
        [{"role": "user", "content": "hello"}], api_key="test-only-placeholder"
    ) == "Answer"
    assert post.call_args.kwargs["allow_redirects"] is False
    assert post.call_args.kwargs["timeout"] == 45
    response.close.assert_called_once()


def test_missing_key():
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        groq.groq_chat([])
    requests.post.assert_not_called()


@pytest.mark.parametrize("status", [301, 400, 401, 429, 500])
def test_http_error(monkeypatch, status):
    monkeypatch.setenv("GROQ_API_KEY", "test-only-placeholder")
    response = Mock(status_code=status)
    monkeypatch.setattr(requests, "post", Mock(return_value=response))
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        groq.groq_chat([])
    response.close.assert_called_once()


@pytest.mark.parametrize("payload", [None, [], {}, {"choices": []}, {"choices": [{}]},
    {"choices": [{"message": {"content": None}}]}, {"choices": [{"message": {"content": []}}]},
    {"choices": [{"message": {"content": "  "}}]}])
def test_malformed_response(monkeypatch, payload):
    monkeypatch.setenv("GROQ_API_KEY", "test-only-placeholder")
    response = Mock(status_code=200)
    response.json.return_value = payload
    monkeypatch.setattr(requests, "post", Mock(return_value=response))
    with pytest.raises(RuntimeError, match="malformed"):
        groq.groq_chat([])
    response.close.assert_called_once()


def test_invalid_response_json(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-only-placeholder")
    response = Mock(status_code=200)
    response.json.side_effect = ValueError("not JSON")
    monkeypatch.setattr(requests, "post", Mock(return_value=response))
    with pytest.raises(RuntimeError, match="malformed"):
        groq.groq_chat([])


def test_request_failure(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-only-placeholder")
    monkeypatch.setattr(requests, "post", Mock(side_effect=requests.Timeout("mock timeout")))
    with pytest.raises(RuntimeError, match="request failed"):
        groq.groq_chat([])


def test_missing_database(tmp_path):
    with pytest.raises(FileNotFoundError, match="Analytics database not found"):
        groq.fetch_analytics("overview", tmp_path / "missing.duckdb")


def test_fetch_normalizes_nulls_and_closes(monkeypatch, tmp_path):
    db = tmp_path / "mock.duckdb"
    db.touch()
    con = Mock()
    con.execute.return_value.df.return_value = pd.DataFrame({"metric": [float("nan")], "hour": [pd.NaT]})
    connect = Mock(return_value=con)
    monkeypatch.setattr(duckdb, "connect", connect)
    intent, rows = groq.fetch_analytics("overview", db)
    assert rows == [{"metric": None, "hour": None}]
    assert json.dumps(rows, allow_nan=False) == '[{"metric": null, "hour": null}]'
    assert connect.call_args.kwargs["read_only"] is True
    con.close.assert_called_once()


def test_fetch_closes_on_query_error(monkeypatch, tmp_path):
    db = tmp_path / "mock.duckdb"
    db.touch()
    con = Mock()
    con.execute.side_effect = RuntimeError("bad schema")
    monkeypatch.setattr(duckdb, "connect", Mock(return_value=con))
    with pytest.raises(RuntimeError, match="bad schema"):
        groq.fetch_analytics("overview", db)
    con.close.assert_called_once()


def test_question_redacted_json_and_reused_facts(monkeypatch):
    chat = Mock(return_value="explanation")
    fetch = Mock(side_effect=AssertionError("Query must not repeat"))
    monkeypatch.setattr(groq, "groq_chat", chat)
    monkeypatch.setattr(groq, "fetch_analytics", fetch)
    rows = [{"team": "Payments", "avg_csat": None}]
    result = groq.answer_analytics_question("Email a@example.com call 415-555-0134", analytics=("team", rows))
    assert result["answer"] == "explanation"
    prompt = chat.call_args.args[0][1]["content"]
    assert "a@example.com" not in prompt and "415-555-0134" not in prompt
    assert "\nAnalysis: team\n" in prompt and "\\nAnalysis" not in prompt
    assert json.loads(prompt.split("Database results (JSON): ")[1]) == rows
    fetch.assert_not_called()


def test_empty_facts_no_api(monkeypatch):
    chat = Mock(side_effect=AssertionError("API must not run"))
    monkeypatch.setattr(groq, "groq_chat", chat)
    assert groq.answer_analytics_question("overview", analytics=("overview", []))["facts"] == []
    chat.assert_not_called()


@pytest.mark.parametrize("mode", ["missing_db", "no_key", "api_error", "streamlit_secret"])
def test_streamlit_failure_and_sql_facts_paths(monkeypatch, mode):
    class Stop(Exception):
        pass
    st = Mock()
    st.text_input.return_value = "overview"
    st.button.return_value = True
    st.stop.side_effect = Stop
    if mode == "streamlit_secret":
        st.secrets = {"GROQ_API_KEY": "test-only-placeholder"}
    monkeypatch.setitem(sys.modules, "streamlit", st)
    monkeypatch.setattr(groq, "DB_PATH", SimpleNamespace(exists=lambda: mode != "missing_db"))
    fetch = Mock(return_value=("overview", [{"chats": 1}]))
    answer = Mock(side_effect=RuntimeError("mock API error"))
    monkeypatch.setattr(groq, "fetch_analytics", fetch)
    monkeypatch.setattr(groq, "answer_analytics_question", answer)
    if mode == "api_error":
        monkeypatch.setenv("GROQ_API_KEY", "test-only-placeholder")
    app = Path(__file__).resolve().parents[1] / "src" / "streamlit_app.py"
    if mode == "missing_db":
        with pytest.raises(Stop):
            runpy.run_path(str(app))
        st.error.assert_called_once()
        fetch.assert_not_called()
    else:
        runpy.run_path(str(app))
        fetch.assert_called_once()
        st.dataframe.assert_called_once()
        if mode == "no_key":
            answer.assert_not_called()
        else:
            assert answer.call_args.kwargs["analytics"] == ("overview", [{"chats": 1}])
            assert answer.call_args.kwargs["api_key"] == "test-only-placeholder"
            st.error.assert_called_once_with("mock API error")

import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import groq_live_check as live
from groq_assistant import DB_PATH, GroqAPIError

LIVE_ENABLED = os.getenv("GROQ_LIVE") == "1"
PLACEHOLDER = "gsk_placeholder-never-real-0000"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_LIVE", raising=False)
    if not LIVE_ENABLED:
        monkeypatch.setattr(requests, "post", Mock(side_effect=AssertionError("Unmocked API call")))
        monkeypatch.setattr(requests, "get", Mock(side_effect=AssertionError("Unmocked API call")))


def error(status=None, kind="api"):
    return GroqAPIError(f"Groq API returned HTTP {status}" if status else "Groq API request failed",
                        status_code=status, kind=kind)


@pytest.mark.parametrize("failure,reason,retryable", [
    (error(kind="config"), "GROQ_API_KEY is not available in this environment", False),
    (error(401), "Groq rejected the configured credential (HTTP 401)", False),
    (error(403), "Groq rejected the configured credential (HTTP 403)", False),
    (error(429), "Groq is rate limiting or unavailable (HTTP 429)", True),
    (error(503), "Groq is rate limiting or unavailable (HTTP 503)", True),
    (error(404), ("Groq returned HTTP 404: the requested model id or endpoint does not exist. "
                  "Run --checks models to list the model ids this key can use"), False),
    (GroqAPIError("bad", kind="response"), "Groq returned a malformed model response", True),
    (GroqAPIError("slow", kind="ReadTimeout"), "Groq request timed out or could not be delivered", True)])
def test_failure_classification(failure, reason, retryable):
    assert live.classify(failure) == (reason, retryable)


def test_retry_backoff_then_gives_up():
    sleeps = []
    action = Mock(side_effect=[error(429), error(429), error(429)])
    with pytest.raises(live.LiveCheckFailed, match="rate limiting"):
        live.call_with_retry(action, retries=2, sleep=sleeps.append)
    assert sleeps == [2.0, 4.0]
    assert action.call_count == 3


def test_success_after_transient_failure():
    action = Mock(side_effect=[error(503), "recovered"])
    assert live.call_with_retry(action, retries=2, sleep=lambda _: None) == "recovered"
    assert action.call_count == 2


def test_authentication_failure_is_not_retried():
    action = Mock(side_effect=error(401))
    with pytest.raises(live.LiveCheckFailed, match="rejected the configured credential"):
        live.call_with_retry(action, retries=3, sleep=lambda _: None)
    action.assert_called_once()


def test_scrub_hides_the_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", PLACEHOLDER)
    assert PLACEHOLDER not in live.scrub(f"Authorization: Bearer {PLACEHOLDER}")
    assert "[REDACTED]" in live.scrub(f"Authorization: Bearer {PLACEHOLDER}")


def test_very_short_values_are_not_scrubbed(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "abc12")
    assert live.scrub("abc12") == "abc12"


def test_validated_text_rejects_empty_and_leaked_keys(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", PLACEHOLDER)
    for value in ["", "   ", PLACEHOLDER, "x" * (live.MAX_ANSWER_CHARS + 1)]:
        with pytest.raises(live.LiveCheckFailed):
            live._validated_text(value)
    assert live._validated_text("  fine  ") == "fine"


def test_models_check_runs_first_by_default():
    assert list(live.CHECKS)[0] == "models"


def test_models_check_reports_availability(monkeypatch):
    monkeypatch.setattr(live, "list_models", Mock(return_value=["a-model", "llama-3.3-70b-versatile"]))
    result = live.check_models("llama-3.3-70b-versatile", Path("unused.duckdb"))
    assert result["status"] == "PASS" and result["model_available"] is True
    assert result["model_count"] == 2 and result["model_requested"] == "llama-3.3-70b-versatile"


def test_models_check_flags_a_retired_model(monkeypatch):
    monkeypatch.setattr(live, "list_models", Mock(return_value=["only-this"]))
    result = live.check_models("retired-model", Path("unused.duckdb"))
    assert result["status"] == "PASS" and result["model_available"] is False


def test_models_check_caps_the_published_list(monkeypatch):
    ids = [f"model-{index}" for index in range(live.MAX_MODEL_IDS + 25)]
    monkeypatch.setattr(live, "list_models", Mock(return_value=ids))
    assert len(live.check_models("model-0", Path("unused"))["available_models"]) == live.MAX_MODEL_IDS


def test_list_models_uses_get_with_timeout_and_refuses_redirects(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", PLACEHOLDER)
    response = Mock(status_code=200,
                    json=lambda: {"data": [{"id": "b-model"}, {"id": "a-model"}, {"id": "a-model"}, {"x": 1}]})
    get = Mock(return_value=response)
    monkeypatch.setattr(requests, "get", get)
    assert live.list_models() == ["a-model", "b-model"]
    kwargs = get.call_args.kwargs
    assert kwargs["timeout"] and kwargs["allow_redirects"] is False
    assert kwargs["headers"]["Authorization"] == f"Bearer {PLACEHOLDER}"
    response.close.assert_called_once()


def test_list_models_requires_a_key_before_any_request():
    with pytest.raises(GroqAPIError) as excinfo:
        live.list_models()
    assert excinfo.value.kind == "config"
    requests.get.assert_not_called()


@pytest.mark.parametrize("payload", [{"data": "not-a-list"}, {"data": []}, {"unexpected": 1}])
def test_list_models_rejects_malformed_payloads(monkeypatch, payload):
    monkeypatch.setenv("GROQ_API_KEY", PLACEHOLDER)
    monkeypatch.setattr(requests, "get",
                        Mock(return_value=Mock(status_code=200, json=lambda: payload)))
    with pytest.raises(GroqAPIError, match="malformed model list") as excinfo:
        live.list_models()
    assert PLACEHOLDER not in str(excinfo.value)


def test_list_models_reports_a_rejected_credential(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", PLACEHOLDER)
    monkeypatch.setattr(requests, "get", Mock(return_value=Mock(status_code=401, json=lambda: {})))
    with pytest.raises(GroqAPIError) as excinfo:
        live.list_models()
    assert excinfo.value.status_code == 401 and PLACEHOLDER not in str(excinfo.value)


def test_missing_database_fails_the_analytics_check(tmp_path):
    with pytest.raises(live.LiveCheckFailed, match="build it before running"):
        live.check_analytics("model", tmp_path / "absent.duckdb")


def test_main_reports_missing_key_without_network(monkeypatch, capsys):
    assert live.main(["--checks", "connectivity"]) == 2
    assert "not available" in capsys.readouterr().err
    requests.post.assert_not_called()


@pytest.mark.parametrize("arguments", [["--checks", "nope"], ["--retries", "-1"]])
def test_main_validates_arguments(arguments):
    with pytest.raises(SystemExit):
        live.main(arguments)


def test_main_summary_json_never_contains_the_key(monkeypatch, capsys):
    monkeypatch.setenv("GROQ_API_KEY", PLACEHOLDER)

    def failing(model, db):
        raise live.LiveCheckFailed(f"token {PLACEHOLDER} echoed")
    monkeypatch.setitem(live.CHECKS, "connectivity", failing)
    assert live.main(["--checks", "connectivity", "--json"]) == 1
    printed = capsys.readouterr().out
    summary = json.loads(printed)
    assert PLACEHOLDER not in printed
    assert summary["failed"] == 1 and summary["passed"] == 0
    assert summary["key_configured"] is True
    assert summary["checks"][0]["reason"] == "token [REDACTED] echoed"


def test_run_records_durations_and_isolates_failures(monkeypatch, tmp_path):
    monkeypatch.setitem(live.CHECKS, "ok", lambda model, db: {"check": "ok", "status": "PASS"})

    def bad(model, db):
        raise live.LiveCheckFailed("boom")
    monkeypatch.setitem(live.CHECKS, "bad", bad)
    results, failed = live.run(tmp_path, "model", ["ok", "bad"], retries=0)
    assert failed == 1
    assert [item["status"] for item in results] == ["PASS", "FAIL"]
    assert all("duration_ms" in item for item in results)


@pytest.mark.skipif(not LIVE_ENABLED, reason="set GROQ_LIVE=1 with a real GROQ_API_KEY")
def test_live_connectivity():
    assert live.check_connectivity(live.DEFAULT_MODEL, DB_PATH)["status"] == "PASS"


@pytest.mark.skipif(not LIVE_ENABLED, reason="set GROQ_LIVE=1 with a real GROQ_API_KEY")
def test_live_conversation_analysis():
    assert live.check_conversation_analysis(live.DEFAULT_MODEL, DB_PATH)["status"] == "PASS"


@pytest.mark.skipif(not LIVE_ENABLED, reason="set GROQ_LIVE=1 with a real GROQ_API_KEY")
def test_live_prompt_injection_resistance():
    assert live.check_prompt_injection(live.DEFAULT_MODEL, DB_PATH)["status"] == "PASS"


@pytest.mark.skipif(not LIVE_ENABLED or not DB_PATH.exists(),
                    reason="set GROQ_LIVE=1 and build the analytics database first")
def test_live_analytics_assistant():
    assert live.check_analytics(live.DEFAULT_MODEL, DB_PATH)["status"] == "PASS"

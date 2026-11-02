import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import conversation_insights as insights
from conversation_insights import RESULT_FIELDS, analyse_csv, analyse_conversation_batch
from analyse_conversations import main as cli_main


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(requests, "post", Mock(side_effect=AssertionError("Unmocked API call")))
    monkeypatch.setattr(insights, "groq_chat", Mock(side_effect=AssertionError("Unmocked model call")))


def item(row_id="0", **updates):
    result = {"row_id": row_id, "sentiment": "neutral", "contact_reason": "billing",
              "escalation_risk": "low", "summary": "Customer asked about a bill.", "key_phrases": ["bill"]}
    result.update(updates)
    return result


def model(monkeypatch, payload):
    chat = Mock(return_value=json.dumps(payload))
    monkeypatch.setattr(insights, "groq_chat", chat)
    return chat


def test_requires_text_column():
    with pytest.raises(ValueError, match="conversation_text"):
        analyse_csv(pd.DataFrame({"message": ["hello"]}))


def test_custom_text_column_diagnostic():
    with pytest.raises(ValueError, match="message"):
        analyse_csv(pd.DataFrame({"other": []}), text_column="message")


def test_batch_requires_one_result_per_row(monkeypatch):
    model(monkeypatch, {"items": []})
    with pytest.raises(ValueError, match="Expected one result per input row"):
        analyse_conversation_batch([{"row_id": "0", "text": "A sample sentence"}])


@pytest.mark.parametrize("wrapped", [True, False])
def test_shuffled_model_results_reordered(monkeypatch, wrapped):
    items = [item("b"), item("a")]
    model(monkeypatch, {"items": items} if wrapped else items)
    result = analyse_conversation_batch([{"row_id": "a", "text": "one"}, {"row_id": "b", "text": "two"}])
    assert [r["row_id"] for r in result] == ["a", "b"]


@pytest.mark.parametrize("payload", [None, 1, "text", {}, {"items": {}}, {"items": None}])
def test_invalid_json_shapes(monkeypatch, payload):
    model(monkeypatch, payload)
    with pytest.raises(ValueError, match="JSON.*list"):
        analyse_conversation_batch([{"row_id": "0", "text": "hello"}])


def test_invalid_json(monkeypatch):
    monkeypatch.setattr(insights, "groq_chat", Mock(return_value="not JSON"))
    with pytest.raises(ValueError, match="valid JSON"):
        analyse_conversation_batch([{"row_id": "0", "text": "hello"}])


@pytest.mark.parametrize("items", [[item("a"), item("a")], [item("a"), item("unknown")],
                                  [item("a"), item(1)], [item("a"), item("")]])
def test_wrong_duplicate_or_nonstring_output_ids(monkeypatch, items):
    model(monkeypatch, {"items": items})
    with pytest.raises(ValueError, match="Expected one result per input row"):
        analyse_conversation_batch([{"row_id": "a", "text": "one"}, {"row_id": "b", "text": "two"}])


@pytest.mark.parametrize("field", RESULT_FIELDS)
def test_missing_requested_field(monkeypatch, field):
    value = item()
    del value[field]
    model(monkeypatch, [value])
    with pytest.raises(ValueError, match="requested fields"):
        analyse_conversation_batch([{"row_id": "0", "text": "hello"}])


@pytest.mark.parametrize("updates", [
    {"sentiment": "happy"}, {"sentiment": []}, {"sentiment": None},
    {"escalation_risk": "urgent"}, {"escalation_risk": 1}, {"escalation_risk": {}},
    {"contact_reason": None}, {"contact_reason": []}, {"contact_reason": " "}, {"contact_reason": "x" * 201},
    {"summary": 1}, {"summary": ""}, {"summary": "x" * 1001},
    {"key_phrases": "bill"}, {"key_phrases": [1]}, {"key_phrases": [""]},
    {"key_phrases": ["x" * 201]}, {"key_phrases": ["bill"] * 11}])
def test_invalid_model_field_types_and_bounds(monkeypatch, updates):
    model(monkeypatch, [item(**updates)])
    with pytest.raises(ValueError):
        analyse_conversation_batch([{"row_id": "0", "text": "hello"}])


@pytest.mark.parametrize("sentiment,risk", [("positive", "low"), ("neutral", "medium"), ("negative", "high")])
def test_supported_enums(monkeypatch, sentiment, risk):
    model(monkeypatch, [item(sentiment=sentiment, escalation_risk=risk)])
    assert analyse_conversation_batch([{"row_id": "0", "text": "hello"}])[0]["sentiment"] == sentiment


@pytest.mark.parametrize("ids", [["a", "a"], [""], [" "], [None], [1]])
def test_invalid_input_ids_no_call(ids):
    with pytest.raises(ValueError, match="IDs"):
        analyse_conversation_batch([{"row_id": value, "text": "hello"} for value in ids])
    insights.groq_chat.assert_not_called()


def test_batch_redaction_and_text_bound(monkeypatch):
    chat = model(monkeypatch, [item()])
    analyse_conversation_batch([{"row_id": "0", "text": "a@example.com +1 (415) 555-0134 " + "x" * 4000}])
    prompt = chat.call_args.args[0][1]["content"]
    assert "a@example.com" not in prompt and "555-0134" not in prompt
    assert "[EMAIL]" in prompt and "[PHONE]" in prompt
    assert len(json.loads(prompt)[0]["text"]) == 3000


@pytest.mark.parametrize("with_id", [False, True])
def test_empty_csv_stable_headers_no_call(with_id):
    frame = pd.DataFrame(columns=["conversation_text", "id"])
    result = analyse_csv(frame, id_column="id" if with_id else None)
    assert list(result.columns) == RESULT_FIELDS + (["conversation_id"] if with_id else [])
    assert result.empty
    insights.groq_chat.assert_not_called()
    assert analyse_conversation_batch([]) == []


def test_all_missing_text_no_call():
    result = analyse_csv(pd.DataFrame({"conversation_text": [None]}))
    assert list(result.columns) == RESULT_FIELDS
    assert result.empty
    insights.groq_chat.assert_not_called()


def test_missing_requested_id_column():
    with pytest.raises(ValueError, match="requested ID column"):
        analyse_csv(pd.DataFrame({"conversation_text": ["hello"]}), id_column="id")


@pytest.mark.parametrize("ids", [["a", "a"], [None, "b"], [" ", "b"], [1, "1"]])
def test_csv_invalid_ids_rejected_before_call(ids):
    with pytest.raises(ValueError, match="IDs"):
        analyse_csv(pd.DataFrame({"conversation_text": ["hello", None], "id": ids}), id_column="id")
    insights.groq_chat.assert_not_called()


def test_csv_batches_preserve_requested_ids(monkeypatch):
    def respond(messages, **kwargs):
        rows = json.loads(messages[1]["content"])
        return json.dumps({"items": [item(r["row_id"]) for r in reversed(rows)]})
    chat = Mock(side_effect=respond)
    monkeypatch.setattr(insights, "groq_chat", chat)
    ids = [f"c{i}" for i in range(7)]
    result = analyse_csv(pd.DataFrame({"text": ["hello"] * 7, "id": ids}), "text", "id")
    assert result["row_id"].tolist() == ids
    assert result["conversation_id"].tolist() == ids
    assert chat.call_count == 2


def test_cli_approved_csv_custom_columns(monkeypatch, tmp_path):
    source, output = tmp_path / "approved.csv", tmp_path / "insights.csv"
    pd.DataFrame({"message": ["hello"], "id": ["001"]}).to_csv(source, index=False)
    model(monkeypatch, [item("001")])
    cli_main(["--input", str(source), "--output", str(output), "--text-column", "message", "--id-column", "id"])
    result = pd.read_csv(output, dtype=str)
    assert result["row_id"].tolist() == ["001"]
    assert result["conversation_id"].tolist() == ["001"]


def test_cli_empty_csv_no_call(tmp_path):
    source, output = tmp_path / "approved.csv", tmp_path / "insights.csv"
    pd.DataFrame(columns=["conversation_text"]).to_csv(source, index=False)
    cli_main(["--input", str(source), "--output", str(output)])
    assert pd.read_csv(output).columns.tolist() == RESULT_FIELDS
    insights.groq_chat.assert_not_called()
